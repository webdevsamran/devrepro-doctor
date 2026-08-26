# Changelog

All notable changes to DevRepro Doctor are documented here.
Format based on Keep a Changelog; versioning follows SemVer.

## [Unreleased]
### Changed - CLI restructuring pass
- `devrepro/cli/app.py` reduced from a 1,425-line monolith to a thin Typer
  assembler; all 36 commands now live in domain modules under
  `devrepro/cli/commands/` (diagnostics, project, environment, snapshots,
  remediation, reports, platform, service) with shared helpers in
  `devrepro/cli/common.py`. The CLI surface is unchanged — commands remain
  top-level (`devrepro doctor`), all exit codes and flags identical.
- Shell completions enabled (`--install-completion` / `--show-completion`).
- Root `fixtures/` consolidated into `tests/fixtures/recordings/` (it was
  unreferenced by the suite; CONTRIBUTING already points at `tests/fixtures/`).
- Wave-named test files renamed to domain names: test_project_intel,
  test_environment_probes, test_profiles_baselines, test_plugins_selftest,
  test_signing_vault_bundle, test_server_enterprise.
- CI matrix extended to Python 3.13/3.14; coverage artifact upload; job
  concurrency cancellation.

### Added - third transformation pass
- Linux platform depth: distro/package-manager family normalization
  (Debian/Fedora/Arch/SUSE/Alpine), kernel/libc/compiler metadata,
  file-descriptor limits, inotify watch guidance and CPU governor reporting.
- macOS platform depth: Xcode/CLT inventory, SDK path/version, Rosetta
  translation status and Homebrew prefix-vs-architecture conflict detection.
- Environment-manager diagnostics (`devrepro envmanagers`): Nix flake lock
  coverage, devenv, Devbox locks, mise/asdf pinned-vs-active toolchain checks,
  direnv `.envrc` advisory handling. DevRepro diagnoses; the managers remain
  the source of truth (INTEROP.md).
- Snapshot signing/verification (`devrepro sign-snapshot`/`verify-snapshot`),
  encryption-at-rest vault (`[secure]` extra) and onboarding bundle export
  (`devrepro bundle`).
- Enterprise auth abstraction: OIDC claim-to-RBAC role mapping with validated
  config, SAML IdP metadata parsing (verification stays delegated); local dev
  auth remains default. External IdP validation: BLOCKED in CI.
- Server OpenAPI 3.1 spec at `/api/v1/openapi.json`, cross-checked against
  the live route table in tests; Prometheus-compatible `/metrics`.
- Checksummed server backup/restore with CLI commands and overwrite guards.
- Frontend: shell startup profiling, containers/WSL, GPU/AI stack, drift
  timeline, generated-environment preview with review gates, plugin catalog
  with capability warnings, enterprise console pages (audit log, exceptions,
  agents/enrollment, retention, server settings). Demo fallbacks are always
  DEMO-labelled.



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