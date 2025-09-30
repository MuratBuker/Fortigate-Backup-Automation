# Introduction

If you have several Fortigate firewalls, you may want to back up their configurations regularly. This repository contains an Ansible playbook that automates the backup process for Fortigate devices.

## Prerequisites

- Ansible installed on your control machine (Linux/MacOS/WSL)
- Access to the Fortigate devices with API credentials
- SSH key-based authentication set up for secure access
- Basic knowledge of Ansible and YAML syntax

## Installation and Setup

For installation, the following commands will update the repository and install Ansible on your Ansible server.

~~~bash
add-apt-repository --yes --update ppa:ansible/ansible
apt install ansible
~~~

We will create a folder to store the working files.

~~~bash
mkdir ansible
~~~

We will create the necessary config file for Ansible Playbooks.

~~~bash
nano ansible.cfg
~~~

Contents to be written inside the config file:

~~~yaml
[defaults]
inventory = inventory.yaml
private_key_file = ~/.ssh/id_ed25519
host_key_checking = False
~~~

We will create the necessary Inventory files for Ansible Playbooks.

~~~bash
nano inventory.yaml
~~~

Example inventory.yaml file:

~~~yaml
---
fortigate:
  hosts:
    fortigate-test-01:
      datacenter: newyork
      ansible_host: 10.10.10.21
      ansible_network_os: fortinet.fortios.fortios
      ansible_connection: httpapi
      ansible_httpapi_use_ssl: true
      ansible_httpapi_validate_certs: no
      ansible_httpapi_port: 7949
      fortios_access_token: "token"

    fortigate-test-02:
      datacenter: boston
      ansible_host: 10.10.10.22
      ansible_network_os: fortinet.fortios.fortios
      ansible_connection: httpapi
      ansible_httpapi_use_ssl: true
      ansible_httpapi_validate_certs: no
      ansible_httpapi_port: 7949
      fortios_access_token: "token"
~~~

## Inventory content explanation

- fortigate: // Used only for naming.
- fortigate-test-01: // Hostname of the Fortigate device.
- datacenter: newyork // Custom variable to identify the data center location.
- ansible_host: IP address of the Fortigate device.
- ansible_network_os: // Specifies the network OS type for Fortigate.
- ansible_connection: // Connection type, set to httpapi for Fortigate.
- ansible_httpapi_use_ssl: // Enables SSL for the connection.
- ansible_httpapi_validate_certs: // Disables certificate validation (set to no for
self-signed certificates).
- ansible_httpapi_port: // Port number for the Fortigate API (default is 7949).
- fortios_access_token: // API access token for authentication.

You can add multiple Fortigate devices by following the same structure in the inventory file. Make sure to replace the placeholder values with your actual device details and credentials.

## Running the Playbook

To run the playbook and back up the configurations of all Fortigate devices listed in the inventory file, use the following command:

~~~bash
ansible-playbook -i inventory.yaml fortigate-backup-playbook.yml
~~~

This command will execute the playbook and create backup files for each Fortigate device in the specified directory.

### Playbook Variables

You can change below variables in the playbook as per your requirements.
~~~bash
  vars:
    dest_path: "/root/{{ datacenter }}"
    folder: "{{ dest_path }}/{{ inventory_hostname }}/{{ hostvars['localhost']['backup_date'] }}"
    filename: "{{ folder }}/backup_{{ hostvars['localhost']['backup_date'] }}_{{ hostvars['localhost']['backup_time'] }}.yaml"
    latest_file: "{{ dest_path }}/{{ inventory_hostname }}/latest/latest.yaml"
~~~


- dest_path: // Base directory where backups will be stored. You can customize it using the datacenter variable.
- folder: // Directory structure for each backup, organized by device hostname and date.
- filename: // Naming convention for the backup files, including date and time.
- latest_file: // Path to the latest backup file for comparison.

You can customize these variables to fit your directory structure and naming preferences.

## Playbook Explanation

In brief, the playbook first checks for the existence of the backup directories and creates them if they do not exist.

Then, it uses the Fortigate API to take a backup and saves it as **latest**. It also compares the new backup with the previous one and stores the differences in a **compare** file. This way, you can easily see the changes between configurations.

It backs up all VDOMs on the Fortigate. If desired, you can filter specific VDOMs or mask passwords in the backup. However, if masking is applied, the backup file cannot be directly uploaded in case of an issue.  