# Product gaps — what DevRepro Doctor deliberately does and does not do

Derived from the verified competitor research in
[`docs/competitive-analysis.md`](docs/competitive-analysis.md) and
[`data/competitive-capabilities.json`](data/competitive-capabilities.json).
This file is honest about gaps so contributors can pick real work.

## Gaps we are aware of (and want)

### 1. No live managed cloud
The self-hosted fleet service (`devrepro/server`) is real and tested, but there is
no hosted/managed offering. **Status: by design for now.** The architecture docs
describe what a managed layer would add; nothing is claimed as live.

### 2. OIDC/SAML is an abstraction, not an integration
`ServerDB` supports service-account tokens and RBAC today. Real enterprise IdP
federation (OIDC/SAML) needs a live IdP to validate against.
**Status: BLOCKED on external validation** — see issue tracker.

### 3. Agent daemon mode is not yet shipped
Scheduled sanitized snapshots from enrolled machines are designed
(enrollment tokens, snapshot ingestion, retention all exist server-side), but the
resident agent process with its own installer is future work.

### 4. Remote scanning (SSH/WinRM) is not implemented
Enterprise remote machine scanning requires strict credential handling and
authorization review; it is intentionally absent rather than half-built.

### 5. There is no frontend e2e coverage
The frontend is covered by vitest component tests only (11 of them, in
`web/src/test/`). There is no Playwright, no browser-driven test and no
route-level e2e across the 32 pages -- adding any of it is an open contributor
opportunity. An earlier version of this file claimed "Playwright smoke tests
exist in CI scope"; that was never true, and the only `playwright` string in
the repository is a transitive optional peer inside `web/package-lock.json`.

### 6. Filesystem case-sensitivity is not detected
This list previously claimed case-sensitivity diagnostics under "Where we are
ahead". No such check exists -- there is no `fsutil`, no `CaseSensitiveInfo`
read and no probe for it anywhere in `devrepro/`. A case-insensitive checkout
of a repo containing `Foo.py` and `foo.py` is a real and confusing failure, so
this is worth building; it was simply never true. **Status: open, wanted.**

### 7. `guard` gates on the whole machine, so it is unusable as a commit hook
`devrepro guard` describes itself as "designed for `devrepro guard` in a git
pre-commit hook", but it runs a full scan and exits 2 on *any* ERROR/BLOCKED
finding anywhere on the machine. Adding it to this repository's
`.pre-commit-config.yaml` blocks every commit while Docker Desktop happens to
be stopped -- even though `.devrepro.toml` marks docker optional and no commit
of Python source depends on a running daemon.

That is the failure mode where a gate gets switched off in the first week. A
commit hook needs to gate on what the commit changes -- lockfiles, manifests,
CI workflows, `.devrepro.toml` -- not on ambient machine state. Until `guard`
grows that scoping, the hook is deliberately not wired here. **Status: open;
`guard` needs a diff-scoped mode before it earns a place in a hook.**

### 8. PostgreSQL backend for the fleet service
SQLite ships today; a PostgreSQL adapter for large multi-user deployments is
planned behind the same `ServerDB` call sites.

## Features deliberately NOT copied from competitors

| Competitor capability | Why we skip it |
|---|---|
| Installing/managing toolchains (mise, Devbox, Nix) | We diagnose; they manage. Duplicating invites conflicts with provenance. |
| Reproducible build guarantees (Nix) | A score can never guarantee identical builds; we explain declaration completeness instead. |
| Shell-agnostic script runners (devenv processes) | Out of scope; we validate their config, not run them. |
| Cloud workspace streaming (DevPod providers) | Different product category; no diagnostic value for us. |
| Telemetry-driven version recommendations | Conflicts with our no-telemetry privacy stance. |

## Where we are ahead

- Cross-platform depth including Windows App Execution Aliases, WSL interop,
  PowerShell execution policy and long-path diagnostics.
- Explainable PATH precedence ("why does this executable win?").
- Privacy-sanitized snapshots with field classification and secret-scan gates.
- Semantic machine-to-machine diff with project-critical classification.
- Local-vs-CI toolchain comparison.
- Remediation plans with risk, rollback and dry-run transactions — never one-click magic.