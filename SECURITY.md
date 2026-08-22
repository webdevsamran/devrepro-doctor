# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a vulnerability

Do **not** open a public issue for security problems.

Email: use GitHub's private vulnerability reporting on
https://github.com/webdevsamran/devrepro-doctor/security/advisories/new
or contact the lead maintainer (@webdevsamran) directly.

You will receive an acknowledgment within 72 hours and a status update
within 7 days.

## Scope

In scope:
- The `devrepro` CLI, library API, report formats, local server (`devrepro serve`).
- Anything that could cause secret leakage, path traversal in snapshot
  loading, command injection via crafted manifests/policies/snapshots,
  or unsafe remediation execution.

Out of scope:
- Vulnerabilities in third-party dependencies (report upstream, but also
  tell us so we can bump).
- Social engineering of end users.

## Design guarantees we treat as security-critical

1. **Read-only default.** No command mutates the system without explicit
   user confirmation, and only SAFE/LOW-risk remediations may ever be
   automated.
2. **No network exfiltration.** `devrepro serve` binds to localhost only;
   there is no telemetry and no cloud upload anywhere in the codebase.
3. **Redaction before serialization.** Snapshots/reports pass through the
   privacy engine before being written; probable secrets block export.
4. **No TLS bypass.** Network/TLS diagnostics never disable certificate
   validation as a "fix".
5. **Snapshot loading is untrusted input.** Loaded snapshots are validated
   against schemas; no code execution from snapshot contents.

## Hardening practices

- CI runs CodeQL, dependency scanning, SBOM generation.
- GitHub Actions are pinned to immutable SHAs with least-privilege permissions.
- Releases include checksums and build provenance.