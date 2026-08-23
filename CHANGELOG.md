# Changelog

All notable changes to DevRepro Doctor are documented here.
Format based on Keep a Changelog; versioning follows SemVer.

## [Unreleased]

### Added — second transformation pass
- Monorepo analysis: workspace discovery, nested-project version conflicts,
  language inventory, lockfile coverage (`devrepro monorepo`).
- CI toolchain parsing (GitHub Actions, GitLab CI, Azure Pipelines, Dockerfiles)
  and local-vs-CI diff (`devrepro ci-diff`).
- Readiness profiles + explainable reproducibility maturity scoring
  (`devrepro profile`).
- Project baselines: create/diff machine against approved expectations
  (`devrepro baseline create|diff`).
- Environment-variable tracing, policy checks and dotenv safety scanning
  (`devrepro env`) — names only, values never displayed.
- Port declarations, conflict detection and opt-in service probes
  (`devrepro ports`).
- Git health: config/LFS/submodule/worktree checks, credential-safe
  (`devrepro git-health`).
- Network diagnostics: proxy chain, clock skew; opt-in TLS/DNS/registry checks
  (`devrepro network --allow-network`).
- Config generators with review-first diffs: `.devrepro.toml`, mise/asdf,
  devcontainer (`devrepro generate`).
- Drift timeline with root-cause hints across snapshot history
  (`devrepro drift`).
- Self-hosted fleet service: SQLite store, RBAC service accounts, single-use
  enrollment tokens, sanitized-only snapshot ingestion, policy-as-code,
  exceptions with expiry/review, immutable audit log, retention, signed
  webhooks, multi-tenant isolation (see docs/SERVER.md).
- Fleet analytics: readiness distribution, OS/arch segmentation,
  tool-version heatmaps, per-machine baseline compliance.
- Frontend pages for all of the above plus a fleet dashboard with a
  clearly-labelled DEMO fixture fallback.
- INTEROP.md (when DevRepro diagnoses vs defers to environment managers)
  and PRODUCT_GAPS.md (honest gap list from competitor research).

## [0.1.0] - 2026-08-22

### Added
- Typed core models, JSON schemas, stable exit codes.
- Probe engine with per-probe failure isolation.
- Platform probes: OS/kernel, CPU/arch, RAM/disk, shell, PATH, env,
  network/TLS basics, certificates.
- Toolchain probes: Git/GitHub CLI, Python, Node, Java, .NET, Go, Rust,
  PHP, Ruby, C/C++, CMake/Ninja, Docker/Podman, kubectl, Terraform,
  cloud CLIs, WSL, Homebrew, Linux/Windows package managers.
- PATH analyzer with duplicate/dead-path/shadowing/conflict detection
  and `which --all` precedence explanation.
- Project requirement detectors for major manifests and lockfiles.
- Rule engine with packs: python, node, dotnet, java, cpp, go, rust,
  containers, wsl, ai-gpu.
- Reproducibility completeness score with per-point explanations.
- Privacy-sanitized snapshots; environment diff with 7 classifications;
  local history with drift detection.
- Safe remediation planner: risk tiers, preconditions, rollback,
  dry-run by default, SAFE/LOW automation only.
- WSL diagnostics, container doctor, port/service scanner,
  network/TLS doctor, registry reachability checks, GPU/AI stack probe.
- Build preflight (`READY` / `READY_WITH_WARNINGS` / `BLOCKED`).
- `.devrepro.toml` project policy support + env-var-name audit.
- Plugin entry points: probes, rules, remediations, project_detectors,
  exporters (versioned API).
- CLI: doctor, info, scan, project, path, which, snapshot, diff,
  preflight, plan, fix, rules, plugins, report, export, history,
  serve, self-test — all with `--json`.
- Reports: terminal, JSON, Markdown, JUnit XML, standalone HTML.
- React + TypeScript + Vite frontend under `web/`.
- Localhost-only server (`devrepro serve`), no telemetry.
- Privacy redaction engine + secret-scanner gate on exports.
- Fixture-driven test suite + property-based tests.
- CI: ruff/format/mypy/pytest/coverage/build/schema validation across
  Windows/Linux/macOS; frontend lint/typecheck/tests/build; CodeQL,
  Dependabot, SBOM, pinned action SHAs, least-privilege permissions.

[0.1.0]: https://github.com/webdevsamran/devrepro-doctor/releases/tag/v0.1.0