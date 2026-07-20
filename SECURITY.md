# Security Policy

## Supported Versions

Only the latest released version receives security updates.

| Version | Supported |
| ------- | --------- |
| Latest  | Yes       |

## Reporting a Vulnerability

If you believe you have found a security issue in CipherCLI, please report it privately to the maintainers rather than opening a public issue.

CipherCLI is a local command-line client for the Cipher encryption service that involves:
- **API communication** — sending encryption and decryption requests to the Cipher API on localhost
- **Path resolution** — accepting raw absolute paths and ultimate paths resolved through DiskIdentifier
- **Configuration loading** — reading port settings and service discovery options from `resources/configuration.json`
- **ServiceHandler fallback** — optionally querying ServiceHandler for alternative port discovery
- **File list parsing** — reading file paths from a user-supplied text file

Include as much detail as possible, such as:
- A clear description of the issue and which component is affected (CLI argument parsing, path validation, API communication, configuration loading)
- Steps to reproduce the problem, including specific command-line arguments or configuration values involved
- Whether the issue involves the Cipher API, DiskIdentifier resolution, ServiceHandler fallback, or local file path handling
- Any relevant logs, error output, or proof of concept code
- The potential impact and how severe you believe it is

If the report involves secrets or configuration values, redact sensitive information before sharing.

## What To Expect

After a report is received:

1. The issue will be reviewed and triaged.
2. You may be contacted for clarification or additional details.
3. A fix may be developed and validated before public disclosure.
4. The reporter may be credited unless they prefer to remain anonymous.

## Security Guidelines

This project is intended to follow basic security hygiene:

- **Configuration file integrity** — `resources/configuration.json` controls which ports CipherCLI uses to reach the Cipher API, DiskIdentifier, and ServiceHandler. Ensure this file is writable only by trusted users.
- **Path validation** — All paths are validated to be absolute before being sent to the Cipher API. Ultimate paths are resolved through DiskIdentifier, and the resolved root path is validated. Treat file path arguments as untrusted input.
- **Localhost API communication** — All API requests are sent to `127.0.0.1`. CipherCLI does not support remote hosts. Ensure no other process is impersonating the Cipher service on the configured port.
- **Port fallback** — When ServiceHandler integration is enabled, CipherCLI queries ServiceHandler on the loopback interface for an alternative port if the configured port is unreachable.
- **Dependency-free design** — CipherCLI has no external Python dependencies, reducing the supply-chain attack surface. Do not add external dependencies without reviewing their security posture.
- **Files list parsing** — The `--files-list` option reads a text file containing file paths. Ensure this file originates from a trusted source.
- **Treat all externally supplied input as untrusted** and validate it before use. The CLI validates paths, identifiers, and configuration values across all commands.

## Disclosure Notes

Do not publicly disclose an unpatched vulnerability until maintainers have had reasonable time to investigate and respond. If a coordinated disclosure timeline is needed, it can be discussed during the report process.
