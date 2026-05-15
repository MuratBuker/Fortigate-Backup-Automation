import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from ansible.plugins.callback import CallbackBase  # type: ignore
from ansible.utils.display import Display  # type: ignore

display = Display()


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "email_playbook_results"

    def __init__(self):
        super(CallbackModule, self).__init__()
        # Track per-host results
        self._succeeded: list[str] = []
        self._failed: list[str] = []
        self._no_change: list[str] = []
        self._changed: list[str] = []          # hosts with diff rc==1
        self._diffs: dict[str, str] = {}       # hostname -> raw diff stdout
        self._generated_on = datetime.now().strftime("%b %d, %Y %I:%M %p")

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
    def _is_backup_task(self, task_name: str) -> bool:
        return "Backing up" in task_name

    def _is_diff_task(self, task_name: str) -> bool:
        return "Print Fortigate config differences" in task_name

    def _is_compare_task(self, task_name: str) -> bool:
        return "Compare Fortigate configs" in task_name

    # ------------------------------------------------------------------ #
    #  Event hooks                                                         #
    # ------------------------------------------------------------------ #


    def v2_runner_on_failed(self, result, ignore_errors=False):
        task_name = result._task.get_name()
        hostname = result._host.get_name()
        if self._is_backup_task(task_name):
            if hostname in self._succeeded:
                self._succeeded.remove(hostname)
            self._failed.append(hostname)

    def v2_runner_on_skipped(self, result):
        pass

    # Capture compare task result to classify no-change vs changed
    def v2_runner_on_ok(self, result):  # noqa: F811  (intentional override)
        task_name = result._task.get_name()
        hostname = result._host.get_name()

        if self._is_backup_task(task_name):
            self._succeeded.append(hostname)

        if self._is_compare_task(task_name):
            rc = result._result.get("rc", -1)
            stdout = result._result.get("stdout", "")
            if rc == 0:
                if hostname not in self._no_change:
                    self._no_change.append(hostname)
            elif rc == 1:
                if hostname not in self._changed:
                    self._changed.append(hostname)
                if stdout.strip():
                    self._diffs[hostname] = stdout.strip()

        if self._is_diff_task(task_name):
            msg = result._result.get("msg", "")
            if msg:
                hostname_key = hostname
                # Parse diff lines from the debug msg if not already captured
                if hostname_key not in self._diffs:
                    lines = str(msg).split("\n")
                    diff_lines = [l for l in lines if l.startswith(">") or l.startswith("<")]
                    if diff_lines:
                        self._diffs[hostname_key] = "\n".join(diff_lines)

    def v2_playbook_on_stats(self, stats):
        self.send_email()

    # ------------------------------------------------------------------ #
    #  HTML builder                                                        #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _diff_to_html(raw: str) -> str:
        """Convert unified diff stdout to two-column HTML table rows."""
        rows = []
        for line in raw.splitlines():
            if line.startswith(">"):
                content = line[1:].strip()
                rows.append(
                    f'<tr>'
                    f'<td class="diff-existing"></td>'
                    f'<td class="diff-added">{_esc(content)}</td>'
                    f'</tr>'
                )
            elif line.startswith("<"):
                content = line[1:].strip()
                rows.append(
                    f'<tr>'
                    f'<td class="diff-removed">{_esc(content)}</td>'
                    f'<td class="diff-existing"></td>'
                    f'</tr>'
                )
            elif line.startswith("---") or line.startswith("+++"):
                pass  # skip file headers
            else:
                content = line.strip()
                if content:
                    rows.append(
                        f'<tr>'
                        f'<td class="diff-context">{_esc(content)}</td>'
                        f'<td class="diff-context">{_esc(content)}</td>'
                        f'</tr>'
                    )
        return "\n".join(rows)

    def _build_html(self) -> str:
        total = len(set(self._succeeded + self._failed))
        failed_count = len(self._failed)
        no_change_count = len(self._no_change)
        changed_count = len(self._changed)

        # ---- Summary rows ----
        summary_rows = f"""
        <tr><td class="stat-label">Devices scheduled for backup</td><td class="stat-val">{total}</td></tr>
        <tr><td class="stat-label">Devices with backup failure</td><td class="stat-val {"stat-fail" if failed_count else ""}">{failed_count}</td></tr>
        <tr><td class="stat-label">Devices with no configuration change</td><td class="stat-val">{no_change_count}</td></tr>
        <tr><td class="stat-label">Devices with configuration change</td><td class="stat-val {"stat-change" if changed_count else ""}">{changed_count}</td></tr>
        <tr><td class="stat-label">Disabled Devices</td><td class="stat-val">0</td></tr>
        """

        # ---- Failed section ----
        failed_section = ""
        if self._failed:
            failed_rows = "".join(
                f'<tr><td class="device-name">{_esc(h)}</td>'
                f'<td class="failure-reason">Backup Operation performed during backup schedule execution failed</td></tr>'
                for h in self._failed
            )
            failed_section = f"""
            <div class="section-header section-fail">Backup operation failed for the following device(s)</div>
            <table class="device-table">
              <tbody>{failed_rows}</tbody>
            </table>
            """

        # ---- No change section ----
        no_change_section = ""
        if self._no_change:
            nc_items = "".join(
                f'<div class="device-item">{_esc(h)}</div>'
                for h in self._no_change
            )
            no_change_section = f"""
            <div class="section-header section-neutral">Configuration not changed for the following device(s)</div>
            <div class="device-list">{nc_items}</div>
            """

        # ---- Per-device diff sections ----
        diff_sections = ""
        for host in self._changed:
            raw = self._diffs.get(host, "")
            if raw:
                diff_rows = self._diff_to_html(raw)
                diff_table = f"""
                <table class="diff-table">
                  <thead>
                    <tr>
                      <th>Existing</th>
                      <th>Changed</th>
                    </tr>
                  </thead>
                  <tbody>{diff_rows}</tbody>
                </table>
                """
            else:
                diff_table = '<p class="no-diff">Configuration changed but diff output not available.</p>'

            diff_sections += f"""
            <div class="section-header section-changed">{_esc(host)}</div>
            <table class="result-meta">
              <tr><td class="meta-label">Result</td><td class="meta-val">Successfully Backed up – Configuration Changed</td></tr>
            </table>
            <div class="diff-legend">
              <span class="legend-modified">Modified</span>
              <span class="legend-added">Added</span>
              <span class="legend-deleted">Deleted</span>
            </div>
            {diff_table}
            """

        # ---- Successfully backed up (no change) per-device ----
        ok_sections = ""
        for host in self._no_change:
            ok_sections += f"""
            <div class="section-header section-ok-host">{_esc(host)}</div>
            <table class="result-meta">
              <tr><td class="meta-label">Result</td><td class="meta-val">Successfully Backed up</td></tr>
            </table>
            """

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fortigate Backup Report</title>
<style>
  body {{
    margin: 0;
    padding: 0;
    background: #f0f2f5;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 13px;
    color: #333;
  }}
  .wrapper {{
    max-width: 960px;
    margin: 24px auto;
    background: #fff;
    border: 1px solid #d0d5dd;
    border-radius: 4px;
    overflow: hidden;
  }}

  /* ---- App header ---- */
  .app-header {{
    background: #fff;
    padding: 10px 18px 4px;
    border-bottom: 2px solid #1a73a7;
  }}
  .app-header .vendor {{
    font-size: 11px;
    color: #666;
    margin: 0;
  }}
  .app-header .app-name {{
    font-size: 18px;
    font-weight: 700;
    color: #1a4e6e;
    margin: 0 0 4px;
  }}

  /* ---- Blue title bar ---- */
  .title-bar {{
    background: #1a73a7;
    color: #fff;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.3px;
  }}

  /* ---- Meta strip ---- */
  .meta-strip {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px 32px;
    padding: 10px 18px;
    border-bottom: 1px solid #e0e5eb;
    background: #fafbfc;
    font-size: 12px;
  }}
  .meta-strip span {{ color: #555; }}
  .meta-strip strong {{ color: #222; }}

  /* ---- Stats table ---- */
  .stats-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 0;
  }}
  .stats-table td {{
    padding: 5px 18px;
    border-bottom: 1px solid #eef0f3;
  }}
  .stat-label {{ color: #444; width: 320px; }}
  .stat-val {{
    font-weight: 700;
    color: #222;
    padding-left: 12px;
  }}
  .stat-fail {{ color: #c0392b; }}
  .stat-change {{ color: #d97706; }}

  /* ---- Section headers ---- */
  .section-header {{
    padding: 7px 18px;
    font-weight: 600;
    font-size: 12.5px;
    border-top: 1px solid #d0d5dd;
    border-bottom: 1px solid #d0d5dd;
    margin-top: 2px;
  }}
  .section-fail    {{ background: #fce8e8; color: #7b1c1c; }}
  .section-neutral {{ background: #eaf1fb; color: #1a4e6e; }}
  .section-changed {{ background: #fef3e2; color: #7c4700; font-size: 14px; padding: 10px 18px; }}
  .section-ok-host {{ background: #eaf5ea; color: #1a4e1a; font-size: 14px; padding: 10px 18px; }}

  /* ---- Device list (no-change) ---- */
  .device-list {{ padding: 8px 18px 12px; }}
  .device-item {{
    padding: 3px 0;
    color: #333;
    border-bottom: 1px dotted #e8eaed;
    font-size: 12.5px;
  }}

  /* ---- Failed device table ---- */
  .device-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .device-table td {{
    padding: 6px 18px;
    border-bottom: 1px solid #fce8e8;
    vertical-align: top;
  }}
  .device-name {{ width: 240px; font-weight: 600; color: #333; }}
  .failure-reason {{ color: #666; font-style: italic; }}

  /* ---- Result meta (per device) ---- */
  .result-meta {{
    width: 100%;
    border-collapse: collapse;
    margin: 0;
  }}
  .result-meta td {{ padding: 5px 18px; }}
  .meta-label {{
    width: 140px;
    font-weight: 600;
    color: #555;
  }}
  .meta-val {{ color: #2e7d32; font-weight: 600; }}

  /* ---- Diff legend ---- */
  .diff-legend {{
    padding: 6px 18px;
    display: flex;
    gap: 12px;
    background: #f7f9fc;
    border-top: 1px solid #e0e5eb;
    border-bottom: 1px solid #e0e5eb;
  }}
  .diff-legend span {{
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 3px;
  }}
  .legend-modified {{ background: #b3d4f5; color: #0d3f6e; }}
  .legend-added    {{ background: #c6efce; color: #1a4e1a; }}
  .legend-deleted  {{ background: #ffc7ce; color: #7b1c1c; }}

  /* ---- Diff table ---- */
  .diff-table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
  }}
  .diff-table th {{
    background: #e8edf2;
    color: #444;
    font-weight: 600;
    padding: 6px 12px;
    text-align: left;
    border-bottom: 2px solid #c8d0db;
    width: 50%;
  }}
  .diff-table td {{
    padding: 3px 12px;
    vertical-align: top;
    border-bottom: 1px solid #f0f2f5;
    word-break: break-all;
    white-space: pre-wrap;
  }}
  .diff-existing {{ background: #fff; color: #555; }}
  .diff-added    {{ background: #c6efce; color: #1a4e1a; }}
  .diff-removed  {{ background: #ffc7ce; color: #7b1c1c; }}
  .diff-context  {{ background: #f9f9f9; color: #666; }}

  .no-diff {{ padding: 12px 18px; color: #888; font-style: italic; }}

  /* ---- Footer ---- */
  .footer {{
    text-align: center;
    padding: 12px;
    font-size: 11px;
    color: #aaa;
    border-top: 1px solid #e8eaed;
    background: #fafbfc;
  }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="app-header">
    <p class="vendor">Ansible Automation</p>
    <p class="app-name">Fortigate Backup Report</p>
  </div>

  <div class="title-bar">Configuration Backup Schedule Notification</div>

  <div class="meta-strip">
    <span><strong>Schedule Name :</strong> Daily Fortigate Config Backup</span>
    <span><strong>Task Type :</strong> Configuration Backup</span>
    <span><strong>Created By :</strong> ansible</span>
    <span><strong>Generated On :</strong> {self._generated_on}</span>
  </div>

  <table class="stats-table">
    <tbody>{summary_rows}</tbody>
  </table>

  {failed_section}

  {no_change_section}

  {diff_sections}

  {ok_sections}

  <div class="footer">
    Generated by Ansible Fortigate Backup Automation by GH Techology Team &nbsp;|&nbsp; {self._generated_on}
  </div>
</div>
</body>
</html>"""

    # ------------------------------------------------------------------ #
    #  Email sender                                                        #
    # ------------------------------------------------------------------ #
    def send_email(self):
        html_body = self._build_html()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Ansible Notification - Fortigate Backup Automation"
        msg["From"] = "cloudnotification@glasshouse.com.tr"

        recipients = [
            "GHDesign&PlanningTeam@glasshouse.com.tr",
            "baris.serbes@glasshouse.com.tr",
            "GHNetSecTeam@glasshouse.com.tr",
            "burak.cetinkaya@glasshouse.com.tr",
            "emrah.bayarcelik@glasshouse.com.tr",
            "sevilay.kurt@glasshouse.com.tr",
            "lutfi.yunusoglu@glasshouse.com.tr",
        ]
  
        msg["To"] = ", ".join(recipients)

        # Plain-text fallback
        total = len(set(self._succeeded + self._failed))
        plain = (
            f"Fortigate Backup Report - {self._generated_on}\n"
            f"Devices scheduled : {total}\n"
            f"Failed            : {len(self._failed)}\n"
            f"No change         : {len(self._no_change)}\n"
            f"Changed           : {len(self._changed)}\n\n"
        )
        if self._failed:
            plain += "FAILED:\n" + "\n".join(self._failed) + "\n\n"
        if self._changed:
            plain += "CHANGED:\n"
            for h in self._changed:
                plain += f"\n--- {h} ---\n{self._diffs.get(h, '')}\n"

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        smtp_server = "172.21.0.61"
        smtp_port = 26589


        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.sendmail(msg["From"], recipients, msg.as_string())
                display.display("Email sent successfully.")
        except Exception as e:
            display.display(f"Failed to send email: {e}", stderr=True)


# ------------------------------------------------------------------ #
#  Utility                                                             #
# ------------------------------------------------------------------ #
def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )