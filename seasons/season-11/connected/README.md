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
