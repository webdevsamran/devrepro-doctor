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

You will receive an acknowledgment within 7 days and a status update within 30
days. This project has a single maintainer; those are the windows that can
actually be met, rather than a shorter number that sounds better.

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
5. **Snapshot loading is untrusted input.** Loaded snapshots are parsed into
   frozen Pydantic models, which reject unknown and mistyped fields, and are
   additionally checked against `schemas/snapshot.schema.json`. No code is
   executed from snapshot contents.

## Hardening practices

- CI runs CodeQL (Python and JavaScript/TypeScript) and dependency scanning
  (`pip-audit`) on every pull request, plus a schema gate that verifies the
  bundled JSON Schemas are present, current and actually validate an instance.
- SBOM generation runs at **release** time (`.github/workflows/release.yml`),
  not on every CI run, and is published as `devrepro-doctor-sbom.spdx.json`.
- GitHub Actions are pinned to immutable SHAs with least-privilege permissions.
- Releases carry build provenance attested by `pypa/gh-action-pypi-publish`.
  They do **not** currently include separate `.sha256` checksum files.