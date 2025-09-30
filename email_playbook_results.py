import smtplib
from email.mime.text import MIMEText
from ansible.plugins.callback import CallbackBase  # type: ignore
from ansible.utils.display import Display  # type: ignore

display = Display()

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'email_playbook_results'

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.results = ""

    def _is_relevant_task(self, task_name: str) -> bool:
        return "Backing up" in task_name

    def v2_playbook_on_task_start(self, task, is_conditional):
        task_name = task.get_name()
        if self._is_relevant_task(task_name):
            self.results += f"Starting task: {task_name}\n"

    def v2_runner_on_ok(self, result):
        task_name = result._task.get_name()
        if self._is_relevant_task(task_name):
            hostname = result._host.get_name()
            self.results += f"Task succeeded on {hostname}: {task_name}\n"

    def v2_runner_on_failed(self, result, ignore_errors=False):
        task_name = result._task.get_name()
        if self._is_relevant_task(task_name):
            hostname = result._host.get_name()
            self.results += f"Task ---FAILED--- on {hostname}: {task_name}\n"

    def v2_playbook_on_stats(self, stats):
        if self.results:
            self.send_email(self.results)

    def send_email(self, body):
        subject = "Ansible Playbook Results"
        msg = MIMEText(body)
        msg["Subject"] = "Ansible Notification - Fortigate Backup Automation"
        msg["From"] = "cloudnotification@glasshouse.com.tr"
        smtp_server = "172.21.0.61"
        smtp_port = "26589"
        recipients = [
            "GHDesign&PlanningTeam@glasshouse.com.tr",
            "baris.serbes@glasshouse.com.tr",
            "GHNetSecTeam@glasshouse.com.tr",
            "burak.cetinkaya@glasshouse.com.tr",
            "emrah.bayarcelik@glasshouse.com.tr",
            "sevilay.kurt@glasshouse.com.tr",
        ]
        msg["To"] = ", ".join(recipients)

        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.sendmail(msg["From"], recipients, msg.as_string())
                display.display("Email sent successfully.")
        except Exception as e:
            display.display(f"Failed to send email: {e}", stderr=True)
