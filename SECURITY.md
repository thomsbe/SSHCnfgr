# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| `0.2.x` (Beta / Current) | Yes |
| `0.1.x` | Security fixes only |

## Security Design Principles

Because SSHCnfgr works alongside `~/.ssh/config`, security and least-privilege handling of files are core design principles:

- **No private key contents:** SSHCnfgr never reads, stores, or transmits private SSH key material. Only file paths and public key metadata (`.pub` key type and comment preview) are stored.
- **Restrictive permissions:** On POSIX systems (Linux/macOS), `~/.ssh/sshcnfgr.toml`, its timestamped backups, and generated OpenSSH config files are written atomically with `0600` permissions.
- **Safe defaults:** Generating an OpenSSH config writes to `~/.ssh/config.generated` by default and never overwrites `~/.ssh/config` unless explicitly requested. Existing target files are backed up before overwriting.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Instead, report security issues privately via one of the following channels:

1. **GitHub Security Advisories (preferred):**
   <https://github.com/thomsbe/SSHCnfgr/security/advisories/new>
2. **Email:**
   `thomas.baer@tbaer.de`

Please include a clear description of the issue, steps to reproduce, and any affected versions or operating systems. You will receive an initial response as quickly as possible.
