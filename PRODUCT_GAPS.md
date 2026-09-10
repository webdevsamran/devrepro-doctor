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

### 5. PostgreSQL backend for the fleet service
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
| A "State of Dev Environments" report | Recommended against, not deferred. It would be the obvious content play -- aggregate what thousands of machines look like and publish the trends -- and it needs a collection channel this project does not have and will not build. Every scan stays on the machine that produced it; there is no endpoint, no opt-in beacon and no aggregate anywhere, which is the one claim here that would stop being true the moment this shipped. `devrepro repro-rate` is the honest version of the same instinct: a number this project's own maintainers record from their own corpus and publish by hand, which is a smaller claim and a true one. |
| An interactive TUI | Deferred with a reason. Every cross-platform TUI toolkit is a dependency -- `curses` is not on Windows, and Textual and its peers bring a render loop, an async runtime and a theme system into a tool whose value proposition is that it does not accumulate moving parts. What a TUI would buy is triage: filter findings, expand evidence, jump to a fix. The web console does that today over a sanitized report, offline, with a command palette -- and `devrepro doctor --json` pipes into whatever a terminal user already prefers. If somebody is working over SSH on a machine with no browser, `--json` and `jq` is the honest answer and it needs nothing from us. |
| Runtime profiling via the Chrome DevTools Protocol | Not built, deliberately. This is `react-doctor`'s territory, it does it well, and it reached 14,800 stars doing it. Driving CDP to profile a running app would mean attaching a debugger to somebody's process -- the furthest thing from read-only in this whole document -- to answer a question about *application* performance rather than about the machine. The boundary is the product: this tool explains why the app will not build; a profiler explains why it is slow once it does. `docs/interop.md` links there rather than competing. |
| A hosted rule-pack registry | Deferred with a reason, not built. Entry points already are the registration mechanism: install a package and `devrepro plugins` lists it, with nothing to submit to and nobody to approve it. A registry adds a service to run, a moderation policy to write and a supply-chain surface to defend -- and would currently list zero packs, which is worse than no registry because it advertises an empty ecosystem. `templates/rule-pack/` and `devrepro rules-test` are what an author actually needs first. |
| Attributed CI footprint / carbon reporting | Cut, not deferred. Measuring the seconds a scan adds to a CI run is easy; the honest number is a fraction of one job, and presenting it as a headline turns a diagnostic tool into a dashboard about itself. `devrepro bench` already reports where a scan spends its time, for the case where that number actually matters -- somebody deciding whether to run it on every push. |

## Where we are ahead

- Cross-platform depth including Windows App Execution Aliases, WSL interop,
  PowerShell execution policy, long-path, filesystem case-sensitivity, reserved
  filename, symlink-privilege and locale diagnostics -- all read-only, including
  case sensitivity, which is normally detected by writing two files.
- Explainable PATH precedence ("why does this executable win?").
- Container-engine identity and configuration: which of Docker Desktop, Colima,
  Rancher Desktop, OrbStack, Podman or a native daemon is behind `docker`,
  whether it is emulating another architecture, its cgroup version and storage
  driver, and how much of its disk is reclaimable -- read without creating,
  pruning or removing anything, and with the socket path classified rather than
  collected.
- Privacy-sanitized snapshots with field classification and secret-scan gates.
- Semantic machine-to-machine diff with project-critical classification.
- Local-vs-CI toolchain comparison.
- Diff-scoped gating: `guard --scope changed` gates only when a commit alters
  the environment contract, and narrows to findings that change could be about,
  so a stopped Docker daemon does not block a commit touching a Python manifest.
- Browser-driven coverage of every route in two viewports, with axe-core
  accessibility checks gating on serious and critical violations. Component
  tests in jsdom never lay anything out, so a lazy chunk that fails to resolve,
  a colour below the contrast threshold, a scroll container no keyboard can
  reach and a layout that overflows at 390px all passed them; each of those was
  real and each was found the day the browser suite was added.
- An environment bill of materials in CycloneDX: the toolchain a build ran on,
  not the dependencies it links against, with executable paths deliberately
  absent so the file can be handed to an auditor outside the company.
- Remediation plans with risk, rollback and dry-run transactions — never one-click magic.