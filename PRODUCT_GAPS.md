# Product Gaps

Derived from verified competitor research
([analysis](docs/competitive-analysis.md),
[data](data/competitive-capabilities.json)). Each gap is tracked to an
implementation area; items marked ✅ are implemented in this repository.

## Gaps we close that competitors leave open

1. ✅ **Cross-manager conflict detection** — no competitor explains why nvm,
   pyenv, mise, asdf, conda and system installs fight each other on one machine.
2. ✅ **PATH precedence explanation** — every candidate executable, its source,
   version, and why PATH resolution picks one (`devrepro path`).
3. ✅ **Privacy-sanitized machine snapshots** — shareable state for human-to-human
   "works on my machine" triage; competitors only share lockfiles.
4. ✅ **Semantic machine↔machine / time↔time diffs** — categorized as missing,
   extra, changed, shadowed, project-critical or platform-expected.
5. ✅ **Local-vs-CI environment diff** — explain why CI passes while a laptop fails.
6. ✅ **Windows/WSL first-class depth** — App Execution Aliases, MSVC/SDK,
   PowerShell policy, long paths, WSL distro/interop/PATH-contamination probes.
7. ✅ **Safe remediation planning** — risk-classified plans with rollback and
   post-checks; never silent mutation.
8. ✅ **Reviewable config generation** — draft `.devrepro.toml`, devcontainer.json,
   tool-version files behind a diff-preview guardrail.
9. ✅ **Fleet baselines & policy-as-code** — self-hosted org→team→project→machine
   inheritance without exposing secret machine data.
10. ✅ **Stable exit codes + JSON everywhere** — deterministic READY /
    READY_WITH_WARNINGS / BLOCKED for scripts and CI bootstrap.

## Gaps in our own product this pass addresses

- Snapshot protocol v2: probe/policy versions, provenance, migrations, signing.
- Monorepo discovery, nested-project conflicts, lockfile coverage analysis.
- CI parser support (GitHub Actions, GitLab CI, Azure Pipelines).
- Drift timelines with root-cause hints across snapshot history.
- Plugin API v2 with capability declarations and failure isolation.
- Self-hosted server foundation (RBAC, audit, policy, webhooks, retention).

## Deliberately out of scope

- Package/build management; cloud workspace provisioning; telemetry;
  auto-execution of generated files; certification claims (SOC 2/ISO/etc.)
  without actual audits.