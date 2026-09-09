# Changelog

All notable changes to DevRepro Doctor are documented here.
Format based on Keep a Changelog; versioning follows SemVer.

## [Unreleased]

A correctness pass, in the same spirit as 0.2.0: things the project claimed to
do, it now actually does. Every item below was found by running the tool, not
by reading it.

### Fixed - `devrepro ci-diff` crashed in its default mode

- `cli/commands/project.py` mapped the `ci-absent` status to the colour
  `grey50`, which is a Rich name click does not accept. Any tool installed
  locally but not pinned in CI -- four of them in this repository -- raised
  `TypeError: Unknown color 'grey50'` partway through the output. `--json`
  took a different branch, which is why it was never noticed. Both the mark
  and colour lookups now use a default, so a status added later degrades
  instead of crashing.

### Fixed - a mistyped argument reported the machine as BLOCKED

- Click exits with `UsageError.exit_code`, which defaults to `2`, and `2` is
  BLOCKED in this project's published contract. A CI job that misspelled an
  argument was told the machine was unusable. `ExitCode.USAGE_ERROR` (4)
  existed for exactly this and eight call sites already used it, but the
  argument parser never reached them. `cli/app.py` now retargets the class
  attribute for both the public `click` package and the copy typer vendors as
  `typer._click` -- they are different class objects, so patching only the
  public one had no effect.

### Fixed - `RecordingRunner` raised on every call, so no probe had a test

- `core/runner.py` used `dataclasses.field(default_factory=list)` inside a
  class that is not a dataclass, leaving `self.calls` as a `Field` object;
  every `run()` raised `AttributeError`. It is a public SDK export and
  `docs/PLUGINS.md` tells plugin authors to use it.
- Consequently `tests/fixtures/recordings/` -- captures for ubuntu, fedora,
  macos, windows, wsl and docker -- was loaded by nothing, and no test
  imported a probe class. `tests/test_probes_recorded.py` now drives
  `PathProbe` and `ContainerProbe` through those recordings, and
  `tests/conftest.py` exposes `recorded_path()` / `recorded_docker_failures()`.
- Two `classification` labels in `recordings/docker/failures.json` did not
  match what `_classify_daemon_error` returns; nothing had ever checked them.

### Fixed - snapshots could not carry container, WSL or GPU state

- `run_scan()` built and validated all three and then dropped them:
  `ScanReport` had no fields for them, so `snapshot_from_report` hardcoded
  `None` and the container branch in `diff/engine.py` could never fire. The
  probes had been collecting the state all along, and
  `ScanReport.privacy.collected` advertised it.
- `ScanReport` now carries them, snapshots propagate them, and the diff engine
  gained Docker CLI, WSL and GPU comparisons. "Docker works there but not
  here" is answerable for the first time.

### Fixed - the reproducibility score ignored lockfiles below the root

- `_lockfiles()` looked only at the project root, so `devrepro doctor` reported
  "Lockfiles found: none" for this repository while `devrepro monorepo` found
  `web/` and its `package-lock.json`. Two commands disagreed about the same
  tree. Discovery is now depth-bounded and shares `SKIP_DIRS` with the
  monorepo analyzer; this repo's score moved from 3/9 to 4/9.

### Fixed - `devrepro fix` silently dropped steps it called automatable

- `execute_plan` appended one result per command, so a step flagged automatable
  that carries no commands produced no result at all: `devrepro plan` listed
  three steps and `devrepro fix --yes` reported one. Such steps now report
  `no-commands` with guidance, and `devrepro plan` distinguishes "automatable"
  from "automatable in principle - no command wired yet".

### Fixed - non-ASCII output crashed the CLI on a default Windows console

- A `U+2192` in one remediation hint was enough to end `devrepro check` in a
  `UnicodeEncodeError` from inside the codecs module, because the Windows
  console encoding is a legacy codepage. Windows being first class is one of
  this project's stated advantages, so the entry point now makes stdout and
  stderr non-fatal for unencodable characters (encoding preserved, only the
  error handler changed) and the hint is ASCII.

### Fixed - the README rule-id guard rejected real rule ids

- `emittable_rule_ids()` described itself as an over-approximation and was the
  opposite. It recognised literal ids and the single spelling
  `rule_id=f"{rule_prefix}/..."`, missing every id a probe composes from a tool
  name or ecosystem -- `f"{name}/multiple-installations"` and
  `f"{ecosystem}/manager-conflict"`. A real scan emits nine of the former.
  `is_emittable_rule_id()` now accepts any prefix in front of a known composed
  suffix, and `AGENTS.md` no longer claims `python/multiple-installations` is
  emitted by nothing.

### Fixed - documentation that did not match the code

- `AGENTS.md` listed a strict subset of the checks CI runs: it omitted
  `scripts/` from both ruff invocations and left out `generate_schemas.py
  --check`, `secret_scan.py`, `check_action_pins.py`,
  `generate_landscape.py --check` and `capture_readme_example.py --check`.
  Its own rule is that CI wins and the file is the bug.
- `PRODUCT_GAPS.md` claimed case-sensitivity diagnostics under "Where we are
  ahead"; no such check exists anywhere. It is now recorded as an open gap.
- `README.md` and `docs/index.md` opened with `pip install devrepro-doctor`,
  which returns 404 -- the name is unregistered. They now show the git install
  and say plainly that PyPI publication is pending.
- `action/action.yml` defaulted to that same uninstallable package, so every
  copy-paste of the published Action failed at the install step. It now
  defaults to installing from this repository.

### Added - blast-radius briefing in `agent-check`

What could an agent reach from here, answered before it starts: uncommitted
work, unpushed commits, credential-shaped variables its subprocesses inherit,
whether this shell points at production, cloud CLIs already logged in, and
whether the process is running as root.

- **Credentials are named, never read.** A test asserts a real-shaped token
  placed in the environment never appears anywhere in the report, so the
  briefing is safe to paste into an issue or hand to the agent itself.
- **Nothing is mutated, including the git index.** A test asserts no mutating
  git subcommand is ever invoked; an assessment of what an agent might destroy
  must not destroy anything.
- The first version wrote its own credential-name pattern and flagged nine
  variables on this machine, of which one was a credential --
  `CLAUDE_CODE_HOST_SESSION_ID` is an identifier. The pattern now lives once,
  in `devrepro/privacy/`, shared with the env probe and the env-var analysis
  which had been carrying near-identical copies of it.

### Added - filesystem and locale hygiene checks

The problems that do not look like environment problems, and all detected
read-only:

- **Case sensitivity**, without writing anything. The usual technique is to
  create `foo` and stat `FOO`; a scan does not write, so an existing entry's
  name is re-cased and the two paths compared with `samefile`. That distinction
  is the whole check: a case-sensitive directory really can hold both `README`
  and `readme`, and asking only "does the re-cased name exist?" would call that
  case-insensitive -- exactly backwards.
- **Reserved filenames.** A repository containing `aux.js` cannot be checked
  out on Windows at all, and git reports a failure that names neither the file
  nor the reason. Reported on every platform, because the person who can still
  fix it cheaply is the one about to commit it.
- **Symlink privilege**, read from the documented Developer Mode registry value
  rather than by attempting to create one. Git does not fail when it cannot
  make a symlink; it writes a plain file containing the target, so the working
  tree differs from the commit while `git status` says clean.
- **Locale**, because a non-UTF-8 preferred encoding is why a build that
  handles an accented filename on one machine raises UnicodeDecodeError on
  another. This machine reports cp1252 -- the same setting that ended
  `devrepro check` in a UnicodeEncodeError earlier in this changelog.

`PRODUCT_GAPS.md` claimed case-sensitivity diagnostics under "Where we are
ahead" for some time before any existed. It is now true, so the entry moves
from the gap list to the capability list.

### Added - `devrepro explain` and a real rule catalogue

A finding gives you a rule id and one line. That is right for a table and not
enough to act on, so `devrepro/rules/catalog.py` carries the long form: what
each rule means, why it matters, and how to fix it.

- `devrepro explain <rule-id>` prints one entry; `devrepro rules --catalog`
  lists them all; `docs/RULES.md` publishes them, generated by
  `scripts/generate_rule_docs.py` with a `--check` drift gate in CI.
- Composed ids resolve by suffix, so `kubectl/multiple-installations` is
  explained even though no code writes that string -- the prefix is whichever
  tool was found twice.
- Hand-written rather than scraped. A regex over the source also finds
  `application/json` and `actions/setup-node`, and a catalogue that documents
  MIME types as diagnostics is worse than none.
- The id set is not a cross product. Crossing every pack with every suffix
  advertised `ai-gpu/version-mismatch` and `wsl/missing`, which nothing emits:
  those packs never call the version helpers. Each family now carries its own
  prefix domain, held against the pack sources by a test.
- `test_every_rule_a_scan_emits_can_be_explained` runs a real scan and asserts
  every id it produces has an entry. It immediately found four: the docker
  classifier has five outcomes and only one was documented.

### Added - `devrepro init`

Scaffolds the policy, a pre-commit hook and a CI job from what the project
already declares, so the starting point describes reality rather than an
aspiration nobody meets. Prints everything and writes nothing without
`--write`, and never overwrites without `--overwrite`.

The generated hook runs `check`, not `guard`, and fires only on
environment-contract files -- lockfiles, manifests, workflows, `.devrepro.toml`.
`guard` gates on whole-machine state, so a hook built on it blocks every commit
while Docker happens to be stopped, and gets deleted in week one.

### Added - `--quiet`, `--fix-plan`, and NO_COLOR

- `--quiet` on `doctor`, `guard` and `preflight`: the exit code becomes the
  whole interface, which is what a shell script wants.
- `doctor --fix-plan` prints the remediation plan as a commented shell script,
  with anything above LOW risk left commented out. Nothing is executed: the
  script is output, not an action.
- Colour follows the `NO_COLOR` convention, yields to `FORCE_COLOR`, and turns
  itself off when stdout is not a terminal, so a redirected report no longer
  arrives full of escape sequences.

### Fixed - `AGENTS.md` now matches CI exactly

`devrepro agent-check .` reports **zero** undeclared CI gates for this
repository -- verified by the command this project added rather than by hand.
The remaining BLOCKED verdict is honest and about the machine: `pip-audit` is
not installed here.

### Changed - the web console is a dashboard now

- **Navigation.** Thirty-two links lived in one flat wrapping row in the header;
  at that count a flat list stops being navigation. They are now six groups in
  a collapsible sidebar, with a ⌘K command palette, breadcrumbs and a real
  router. `web/src/nav.ts` is the single source of truth the sidebar, the
  router and the palette all read -- previously the list, the render chain and
  a Python doc test each had their own copy.
- **Code splitting.** The old shell imported every page eagerly and rendered a
  thirty-two branch `{page === 'x' && ...}` chain, so every visitor downloaded
  every view to look at one. Routes are lazy: four page chunks load on demand
  and the initial route is ~84 kB gzipped.
- **Design system.** 86 lines of CSS became a layered token system: a full
  light and dark palette, a severity ramp used by badges, rows and charts
  alike, spacing/radius/elevation scales, and three motion durations behind one
  easing. `--surface-2` is defined -- it was referenced with a hard-coded `#333`
  fallback and never declared, so meter tracks and timeline rails rendered dark
  grey in light mode.
- **Theme.** Light / dark / system, persisted, and honouring a later change to
  the OS setting. It was a boolean in component state that could not express
  "follow the system" and forgot the choice on reload.
- **Charts.** Score radial, stacked severity bar, meters and sparklines, drawn
  in SVG against theme tokens rather than pulled from a charting library, so
  they follow light/dark for free and add nothing to the bundle. Each is
  `role="img"` with the number in its label.
- **Responsive.** Sidebar collapses to icons on tablet and becomes a bottom
  sheet on mobile. Grid items and cards are pinned to `min-width: 0` and wide
  content scrolls inside its own card, so one long version string can no longer
  widen the page.
- **Motion and micro-interactions.** Route entry, button press depth, animated
  arcs and meters, count-ups, skeletons shaped like the page they precede, copy
  buttons that confirm. All of it collapses under `prefers-reduced-motion`.

### Fixed - the reproducibility score rendered as "(undefined%)"

- The console showed `4/9 (undefined%)` above a table whose Point and Why
  columns were blank. `ScorePoint` declared `name` and `why`; the model has
  `criterion` and `explanation`. `Score` declared a `percent` the payload does
  not carry, because `percent` is a Python property and Pydantic does not
  serialize those.
- Making it a `computed_field` looked like the fix and is not: every report
  round-trips through `_sanitize_report`, which dumps, redacts and
  re-validates, and a computed field is output-only, so `extra="forbid"`
  rejected it and every scan raised. That round-trip is what makes the privacy
  gate a guarantee, so the console derives the percentage instead and the model
  records why.

### Fixed - the console offered an install command that returns 404

- The Home page printed `pip install devrepro-doctor`, with a copy button.

### Added - `devrepro agent-check`

Can an AI coding agent actually work in this repository, on this machine?

- Reads `AGENTS.md`, `CLAUDE.md`, `.cursorrules` and the other manifest
  conventions, and resolves every command they declare. The status that matters
  is `not-on-path`: a program that is installed but unreachable from this shell
  needs a PATH fix, not an install, and those two failures are indistinguishable
  from inside an agent. On this machine `ruff`, `mypy`, `pytest` and `mkdocs`
  are all in that state.
- Compares the manifest against what CI actually enforces on a pull request,
  and reports gates no manifest declares. Release workflows are skipped, and
  shell plumbing inside `run: |` blocks is filtered out so the findings that
  matter are not buried.
- Read-only by default. A manifest is an untrusted file whose setup step is
  usually an installer, so executing what it declares requires `--run`, which
  prints each command first and refuses anything needing a shell. A test pins
  that nothing runs without the flag.
- Exit codes follow the published contract: BLOCKED when a declared program is
  absent, READY_WITH_WARNINGS for drift or an off-PATH program, READY when a
  repository has no manifest at all -- most do not, and that is not a failure.
- Documented in `docs/AGENT-READINESS.md`.

Every repository this was tested against had the same defect: a manifest
listing a strict subset of its own CI gates. Three of three, including this one.

### Added

- `tests/test_cli_surface.py` -- every registered command is invoked, not just
  its helpers. `--help` for all 37, a bare invocation for the read-only
  subset, and the usage-error contract. This is the gap the two crashes above
  lived in: 28 of 37 commands had no CLI-level test, and `local_vs_ci_diff`
  had three tests including one producing the exact status that crashed the
  command, because they called the function and never the command.
- `.devrepro.toml` -- the project now declares its own policy.
- A test asserting `PACK_NAMES` matches what `load_builtin_packs` registers;
  `devrepro rules` prints the former while the engine runs the latter, and
  nothing checked that they agreed.

### Known gaps recorded rather than papered over

- `devrepro guard` gates on whole-machine state, so adding it to
  `.pre-commit-config.yaml` blocks every commit while Docker Desktop is
  stopped -- even with docker marked optional in the policy. The hook is
  deliberately not wired until `guard` can scope to what a commit changes.
- The docker classifier has no branch for a client/server API version
  mismatch; it falls through to the generic `daemon-error`.

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