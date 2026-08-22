# Privacy Model

DevRepro Doctor is **read-only by default** and designed so that no sensitive
data ever leaves your machine.

## What is collected

| Category | Examples |
| --- | --- |
| Platform | OS name/version, architecture, kernel string, shell name |
| Hardware totals | CPU count, free disk GB (no serials, no SMART data) |
| PATH | Entry list, normalized; absolute paths are redacted to `C:\Users\<user>\...` |
| Toolchains | Tool name, version, executable path (redacted), install source, duplicates |
| Project requirements | Only what manifests/lockfiles/policies *declare* |
| Container/WSL/GPU state | Versions, reachability booleans, distro names |
| Environment variables | **Names only**, and only when a policy explicitly requires them |

## What is never collected

- Usernames and home-directory absolute paths (redacted to `<user>`)
- Tokens, API keys, SSH/cloud/registry credentials
- Environment variable **values**
- File contents beyond project manifests
- Emails, browser history, telemetry beacons

## Enforcement

- `devrepro/privacy/gate.py` runs a redaction pass over every report/snapshot
  payload before it is written or served.
- `assert_no_secrets()` performs a final scan (GitHub/AWS/GCP tokens, private
  keys, bearer headers, generic `KEY=VALUE` secret shapes) and **blocks the
  export** if a probable secret is detected.
- Synthetic-secret regression tests live in `tests/test_privacy.py`; add a
  case for every new secret pattern you introduce.

## Reporting a leak

If you believe any output contains personal data, open a private security
advisory per `SECURITY.md`. Do not paste the leaked output publicly.