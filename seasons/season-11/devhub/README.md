# HTB DevHub

## Overview

- Season: 11
- Difficulty: Medium
- OS: Linux
- Initial Access: MCPJam Inspector RCE
- Privilege Escalation: Jupyter token pivot -> OpsMCP root SSH key dump

> Flags, private keys, and sensitive values are redacted.

## Attack Path

1. Enumerated open ports and found SSH, HTTP, and MCPJam Inspector on port 6274.
2. Inspected the web application and discovered references to MCP Inspector, Jupyter, and internal operations tooling.
3. Downloaded and reviewed the MCPJam frontend JavaScript bundle.
4. Found `/api/mcp/connect`, which accepted `stdio` MCP server configuration.
5. Used Burp Repeater to send a crafted `serverConfig` that executed a reverse shell.
6. Got initial shell as `mcp-dev`.
7. Enumerated local services and found Jupyter running on `127.0.0.1:8888` as `analyst`.
8. Found the Jupyter token in process arguments using `ps auxww`.
9. Used the Jupyter API to create a kernel and execute commands as `analyst`.
10. Read `/home/analyst/.opsmcp_key` and inspected `/opt/opsmcp/server.py`.
11. Found a root-owned Flask service on `127.0.0.1:5000`.
12. Called the hidden `ops._admin_dump` tool with the OpsMCP API key.
13. Dumped the root SSH private key and used it to SSH as root.

## Enumeration

Initial scan:

```bash
nmap -sC -sV -p- --min-rate 5000 -oN nmap 10.129.5.34
