# Changelog

All notable changes to DevRepro Doctor are documented here.
Format based on Keep a Changelog; versioning follows SemVer.

## [Unreleased]

## [0.2.0] - 2026-09-07

The first release. Everything below already existed in the repository; what
changed in this pass is that several things it claimed to do, it now actually
does.

### Fixed - the shipped Action could not gate a build

- `action/action.yml` advertised gating on an exit-code contract (0 READY,
  1 READY_WITH_WARNINGS, 2 BLOCKED). It captured `$?` after a pipe, which is
  `tee`'s status and therefore always 0, so **the gate never fired** however
  blocked the machine was. There is no `set -o pipefail` in the file;
  `PIPESTATUS[0]` is now used.
- When `sarif-output` was set the argument list was rebuilt without `--json`,
  so the next step parsed a Rich table as JSON, threw, and reported the
  verdict as `UNKNOWN`. The usage documented in the README hit both bugs at
  once: it always reported UNKNOWN and always passed.
- Action inputs are passed through `env:` rather than interpolated into the
  shell, which is the difference between an input and an injection.

### Fixed - a security claim with nothing behind it

- `SECURITY.md` listed "loaded snapshots are validated against schemas" as a
  security property, and `schemas/README.md` named three schema files as the
  serialization source of truth. **The directory contained only a README.**
  The three schemas are now generated from the Pydantic models by
  `scripts/generate_schemas.py`, with a `--check` mode in CI so the generated
  files cannot drift from the models that produce them.
- `scripts/validate_schemas.py` globbed `*.json` over a directory holding one
  `.md` file, so its schema loop never executed. It fails closed now.

### Fixed

- A corrupt backup could fail to raise during restore: the handler caught a
  narrower set of exceptions than a damaged archive can produce. Now covers
  the tar, OS, EOF, zlib and JSON failures a truncated or tampered bundle
  actually raises.
- `scripts/branch-protection.json` listed three context names that could never
  match anything -- `Python (ubuntu-latest)` against a job template that emits
  `Python (ubuntu-latest, 3.11)`. Applying that file would have removed real
  protection. Regenerated with all 18 live contexts.
- Documentation references that 404 on GitHub: `docs/release.md` (absent),
  `docs/privacy.md` and `docs/plugins.md` (the files are `PRIVACY.md` and
  `PLUGINS.md`, and GitHub's renderer is case-sensitive), and the repository's
  only markdown image.

### Changed

- React 19 and the frontend majors, with an ESLint flat-config migration.
- The release workflow creates a GitHub Release with the wheel, sdist, SBOM
  and checksums. It previously built a wheel and went straight to a PyPI
  upload, so a tag produced no release at all -- and then failed at the
  upload, which is unconditional no longer.

### Note on PyPI

Not published. Publishing needs a Trusted Publisher registered for this
project on pypi.org, which is a form on the account that owns the name and
cannot be created from a repository. The release workflow skips the upload
with a notice naming exactly what to register, rather than failing the
release.

### Added - fifth pass: deployments wired
- Branch protection for `main`: force-push/deletion blocked, 18 required
  status checks (all CI matrix jobs + Frontend + Docs site +
  Dependency security scan + CodeQL analyses). Policy documented in
  CONTRIBUTING.md under "Branch protection".
- GitHub Pages publishing: `.github/workflows/docs.yml` builds the site with
  `mkdocs build --strict` and deploys via actions/deploy-pages on every push
  to main that touches docs; Pages enabled with build_type=workflow.
- Repository `pypi` environment created for the Trusted Publishing job in
  release.yml (one-time PyPI publisher registration remains a manual step).

### Added - fourth pass: CI/CD surface & docs site
- SARIF 2.1.0 renderer (`devrepro/reports/sarif.py`) wired into
  `devrepro scan --format sarif` and `devrepro report --format sarif`, so
  environment blockers appear in GitHub code scanning and on pull requests.
  States map BLOCKED/ERROR→error, WARN/UNKNOWN→warning, INFO/PASS→note;
  results carry stable rule IDs, detected/required versions, remediation
  hints and reproducible fingerprints. Output passes the privacy gate.
- `devrepro guard`: short-output pre-commit/CI gate (exit 2 on blockers).
- Official composite GitHub Action (`action/action.yml`) running preflight/
  doctor/guard with optional policy, SARIF output and verdict output;
  every nested action pinned by commit SHA. Guide: docs/ci-github-actions.md.
- Documentation site (mkdocs-material): mkdocs.yml + requirements-docs.txt,
  root-level canonical docs included via snippet wrappers so the site never
  drifts from the repo. Verified with `mkdocs build --strict`; docs job
  added to CI.
- Frontend unit tests (vitest + Testing Library + jsdom): UI primitives,
  Home page hero/CTA and the report loader's source-priority contract.
  `npm test` added to package.json and run in CI. 11 tests, all passing.

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
- Frontend source restructured out of numbered files (`api2.ts`, `pages3.tsx`, …)
  into domain modules: `api/{report,capabilities,console}.ts`,
  `components/ui.tsx` and `pages/{core,environment,platform,enterprise}.tsx`.
  No behavior change; lint/typecheck/build all pass.
- Coverage gate raised 60% → 70% (actual: 71%).
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