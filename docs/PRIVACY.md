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

## What is sent, and when

**Nothing, unless a flag asks for it by name.** A default scan opens no
sockets. That includes the endpoint and TLS checks, which need `--allow-network`
on either `devrepro doctor` or `devrepro network`.

This was not always true, and the correction is worth stating plainly rather
than quietly: until the fix landed, the scan probe opened TLS connections to
`github.com`, `registry.npmjs.org` and `pypi.org` on every `doctor`, `scan`,
`preflight`, `guard` and `snapshot`, and made an HTTPS request to read a `Date`
header for the clock-skew check. Nothing about the machine was *transmitted* --
these were reachability handshakes, not uploads -- but three third-party hosts,
and any corporate proxy in the path, could see that the machine had connected.
That is a disclosure, and it contradicted this page.

What a connection reveals, when you do ask for one:

| Flag | Reaches | What the far end learns |
| --- | --- | --- |
| `doctor --allow-network` | github.com, registry.npmjs.org, pypi.org | Your IP connected and completed a TLS handshake. No request body, no identifying header. |
| `network --allow-network` | The above, plus `--host` and any registries you request | The same, plus a DNS lookup per host. |
| `network --registries` | Configured package registries | That your IP asked whether they answer. |

Proxy configuration is reported in every scan and needs no connection: it is
read from environment variables and from `git config`, with credentials in a
proxy URL redacted before the value is recorded.

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