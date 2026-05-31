# HTB Silentium

## Overview

- Season: 10
- Week: 11
- Difficulty: Easy
- OS: Linux
- Initial Access: Password reset API token disclosure -> Flowise access
- Foothold: Flowise 3.0.5 CustomMCP code injection inside Docker
- Privilege Escalation: Gogs 0.13.3 symlink bypass as root

> Flags, private keys, and sensitive values are redacted. Credentials shown here are retained only where they explain the attack path.

## Executive Summary

Silentium exposed a web application on port `80` using the hostname `silentium.htb`. Initial directory brute forcing was noisy because the server returned HTTP `200` for many invalid paths. Filtering by response size revealed the real behavior, and virtual host fuzzing exposed `staging.silentium.htb`.

The staging application contained a login page for a financial system. User enumeration revealed a valid user email, and the password reset API returned the reset token directly in the HTTP response. This allowed resetting the user's password without email access.

After logging in, the account had access to Flowise 3.0.5. A code injection vulnerability in the CustomMCP node gave command execution inside the Flowise Docker container. Environment variables inside the container leaked credentials, and password reuse allowed SSH access as `ben` on the host.

Privilege escalation came from a root-owned Gogs 0.13.3 service. The service was vulnerable to a symlink bypass in the PutContents API, allowing an authenticated Gogs user to overwrite root-owned files. By writing an attacker SSH key into `/root/.ssh/authorized_keys`, root SSH access was obtained.

## Attack Path

1. Enumerated port `80` and identified `silentium.htb`.
2. Gobuster produced noisy results because the server returned HTTP `200` for invalid paths.
3. Filtered false positives by response size.
4. Used vhost fuzzing and found `staging.silentium.htb`.
5. Found a staging login page for a financial system.
6. Used login error differences to enumerate a valid user email.
7. Abused the password reset API because it returned the reset token in the response body.
8. Reset the valid user's password and logged into the application.
9. Reached Flowise 3.0.5.
10. Exploited CustomMCP code injection for command execution inside the Flowise Docker container.
11. Dumped environment variables and found reused credentials.
12. Used the reused password to SSH as `ben` on the host.
13. Enumerated host processes and found Gogs 0.13.3 running as root.
14. Accessed Gogs through `staging-v2-code.dev.silentium.htb`.
15. Exploited CVE-2025-8110 symlink bypass in Gogs PutContents API.
16. Wrote an attacker SSH public key to `/root/.ssh/authorized_keys`.
17. SSH'd as root.

## Reconnaissance

The box exposed the main web host:

```text
silentium.htb
```

Directory enumeration initially produced false positives because the server returned HTTP `200` for invalid paths.

The fix was to filter by response size instead of relying only on status code.

Example approach:

```bash
gobuster dir -u http://silentium.htb/ \
  -w /usr/share/seclists/Discovery/Web-Content/raft-medium-words.txt \
  --exclude-length <SOFT_404_RESPONSE_SIZE>
```

Virtual host fuzzing revealed:

```text
staging.silentium.htb
```

Example:

```bash
ffuf -u http://silentium.htb/ \
  -H "Host: FUZZ.silentium.htb" \
  -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs <NORMAL_RESPONSE_SIZE>
```

Why this mattered:

- HTB machines often hide important applications behind vhosts.
- Soft 404 behavior can make directory brute forcing useless unless response sizes are filtered.

## Initial Access

The staging site hosted a login page for a financial system.

The login page leaked valid usernames through different error messages:

```text
Invalid user: "User Not Found"
Valid user: different authentication error
```

Fuzzing with an email/name list identified:

```text
ben@silentium.htb
```

The password reset endpoint was vulnerable:

```http
POST /api/v1/account/forgot-password
```

The endpoint returned the reset token directly in the response body. No email inbox access was required.

Impact:

```text
Valid email -> password reset token disclosure -> account takeover
```

Vulnerability class:

```text
Broken API authorization
Sensitive data exposure
CWE-200: Exposure of Sensitive Information
```

## Flowise Foothold

After resetting the user's password and logging in, the account had access to Flowise:

```text
Flowise 3.0.5
```

The vulnerable component was the CustomMCP node. The `listActions` load method passed user-controlled input into a `Function()` constructor.

This created a code injection vulnerability:

```text
CustomMCP node -> unsafe Function() usage -> command execution
```

Vulnerability class:

```text
CWE-94: Improper Control of Generation of Code
Unsafe eval-equivalent behavior
```

Command execution landed inside the Flowise Docker container as root.

Environment variables were dumped with:

```bash
printenv
```

Useful leaked values:

```text
FLOWISE_PASSWORD=[REDACTED]
SMTP_PASSWORD=[REDACTED]
```

The SMTP password was reused as `ben`'s SSH password on the host.

SSH access:

```bash
ssh ben@silentium.htb
```

Why this mattered:

- The first shell was inside a container, not directly on the host.
- Environment variables often contain service credentials.
- Credential reuse allowed escaping the container boundary via SSH.

## Privilege Escalation

Process monitoring with `pspy` revealed Gogs running as root:

```text
Gogs 0.13.3
Port 3001
Process owner: root
```

The nginx configuration exposed it through:

```text
staging-v2-code.dev.silentium.htb
```

Gogs 0.13.3 was vulnerable to:

```text
CVE-2025-8110
```

The issue was a symlink bypass in the PutContents API. Because Gogs was running as root, an authenticated Gogs user could use the API to overwrite arbitrary files on the host through a repository symlink.

Exploit flow:

1. Register a Gogs account manually because captcha blocked automated registration.
2. Create a Gogs API token.
3. Create a repository.
4. Push a symlink pointing to `/root/.ssh/authorized_keys`.
5. Use the PutContents API to write an attacker SSH public key through the symlink.
6. SSH as root.

Vulnerability class:

```text
CWE-61: UNIX Symbolic Link Following
Improper symlink handling in privileged file write path
```

Root access:

```bash
ssh -i root_key root@silentium.htb
```

## Key Lessons

- Always check for virtual hosts on HTB machines.
- When a server returns HTTP `200` for invalid paths, filter by response size.
- Login error messages can create user enumeration vulnerabilities.
- Password reset APIs must never return reset tokens in client responses.
- Container root is not automatically host root.
- Environment variables are a high-value enumeration target inside containers.
- Credential reuse across services can turn container access into host access.
- Watch running processes and internal services after getting a shell.
- Manual browser steps can bypass automation blockers such as captcha.
- Root-owned developer services are high-risk if they expose file-write functionality.
- Be careful with shell special characters when handling credentials.

## Remediation

- Return generic login and password reset responses.
- Never expose password reset tokens in API responses.
- Patch or restrict vulnerable Flowise components.
- Avoid unsafe dynamic code execution such as `Function()` with user input.
- Do not store sensitive credentials in broadly readable environment variables.
- Enforce unique passwords across services.
- Do not run Gogs as root.
- Patch Gogs against CVE-2025-8110.
- Harden file-write APIs against symlink traversal and path confusion.
- Restrict internal developer services behind proper authentication and network controls.

