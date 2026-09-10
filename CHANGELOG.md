# Changelog

All notable changes to DevRepro Doctor are documented here.
Format based on Keep a Changelog; versioning follows SemVer.

## [Unreleased]

A correctness pass, in the same spirit as 0.2.0: things the project claimed to
do, it now actually does. Every item below was found by running the tool, not
by reading it.

### Added - a CycloneDX bill of materials for the environment

- `devrepro scan --format cyclonedx` (and `report --format cyclonedx`) emits a
  BOM describing the *toolchain a build ran on*, not the dependencies it links
  against. Every SBOM tool answers the second question; none answers the first,
  and the first is what turns a reproducible build into an unreproducible one.
  Two machines with byte-identical lockfiles diverge on glibc 2.17 vs 2.39, and
  a dependency SBOM records neither.
- CycloneDX 1.6 rather than a bespoke format, because an evidence file nobody's
  tooling can read is not evidence. The Cyber Resilience Act's SBOM obligations
  arrive in December 2027.
- **Paths never appear.** An executable path names a user's home directory on
  every platform, and a BOM is an artefact people attach to compliance tickets
  and hand to auditors outside their company. The provenance is kept instead --
  installed by the OS package manager, by rustup, by a version manager -- and
  the document says in its own metadata why the path is absent, so someone
  looking for it finds the reason rather than a gap. The host is called `host`
  for the same reason: a hostname is frequently a person's name.
- One component per tool, not per resolved path. Three Pythons on PATH is a
  fact about PATH; the count is kept as a property, because "there were three
  and this is the one that won" is what a reproducibility argument turns on.
- Deterministic, serial number included. A random UUID would be conventional
  and would make every regeneration a diff, which defeats an artefact whose
  purpose is being compared -- across machines, or across time.
- The provenance table's first draft invented its own vocabulary
  (`system-package-manager`, `version-manager`), none of which the toolchain
  probe emits, so every component described itself as "provenance could not be
  determined" while the report beside it knew perfectly well. A test now holds
  the table against the probe's own marker list.
- `docs/ENVIRONMENT-BOM.md` explains the format, and what is deliberately left
  out of it.

### Added - `generate agents-md`: a manifest that starts out agreeing with CI

- Every `AGENTS.md` this project has examined drifts from the workflow that
  gates its repository, always in the same direction: the file lists a subset,
  so an agent runs everything it was told to, sees green, and is failed by the
  pull request for reasons the file never mentioned. Three of three
  repositories on this machine had it.
- The cause is structural rather than careless. Someone writes the file once,
  from memory, and then CI grows a gate; nothing connects the two, so nothing
  notices. `devrepro generate agents-md` drafts the file *from* the workflows
  using the same reader `agent-check` uses to find drift, so a freshly
  generated manifest scores 3/3 on `matches-ci` by construction and any later
  gap is CI having moved -- which is the case worth reporting.
- A test asserts that round trip against this repository's own workflows, not
  only a synthetic fixture: matrices, `working-directory` and a second workflow
  file are exactly where a line-based YAML reader goes wrong, and if the
  generator and the checker ever disagree about what counts as a gate, it
  fails.
- Installation steps are separated from checks. Calling `pip install -e
  ".[dev]"` a gate is wrong in a way an agent acts on -- it reads a successful
  install as a passing check, and has no way to learn that the install is the
  prerequisite for everything after it.
- What a generator cannot know is left as a marked TODO rather than filled with
  plausible prose. The conventions section especially: it is the part an agent
  most needs and the part no directory listing can supply, and a confident
  paragraph of invented house style is worse than an empty heading, because
  nobody edits what looks finished.
- Repeated matrix commands appear once. A twelve-leg matrix really does run
  `pytest` twelve times, and a file that says so twelve times reads as a
  mistake.

### Added - whether a prebuilt binary can actually load here

- Package managers choose which compiled artefact to download from three facts
  about the machine -- its architecture, its C library, and that library's
  version -- and every way of getting one wrong produces a failure about
  something else entirely.
- The new `abi/compat` probe reports all three, and six documented rules:
  - **`abi/translated-process`** -- an x86_64 interpreter under Rosetta on
    Apple silicon. Nothing fails, which is the problem: every wheel and native
    addon installed from here is the x86_64 build, they stay that way for
    anything that loads them, builds take roughly ten times as long, and the
    machine reports itself as arm64 throughout.
  - **`abi/interpreter-arch-mismatch`** and **`abi/runtime-arch-mismatch`** --
    prebuilt artefacts are chosen by the *interpreter's* architecture, not the
    machine's, which is how a `node_modules` becomes non-portable between two
    machines that look identical.
  - **`abi/musl-libc`** -- a manylinux wheel is linked against glibc and cannot
    load on Alpine. pip does not say so; it skips the wheel and builds from
    source, needing a compiler a slim image deliberately lacks, and the error
    names a missing header.
  - **`abi/glibc-below-common-wheel-tag`** -- below the `manylinux_2_28` floor,
    wheels are skipped silently and `pip install numpy` becomes a
    fifteen-minute compile. The finding names the tags the machine *can*
    install, because that is the actionable part.
- Architecture names are normalised before any comparison. Python reports
  `AMD64`, uname `x86_64`, node `x64`; comparing any two raw would report every
  Windows machine as mismatched with itself. An unrecognised name compares as
  *unknown* rather than as a difference.
- The first `ldd` parser reported **musl 86** on every Alpine machine: musl's
  banner is `musl libc (x86_64)` with the version on the *next* line, so a
  pattern looking for digits after the flavour name found the `86` in
  `x86_64`. The two formats now have separate patterns, and the test that
  caught it uses a recorded banner.

### Changed - the Rules view is a searchable catalogue, not a pack tally

- It listed the rule *packs* that appeared in the current report -- a handful
  of cards with a count on each. That answers "what did this scan touch", which
  the Findings page answers better, and it cannot answer the question someone
  arrives with: what does `containers/cgroup-v1` mean and what do I do about it.
- All 118 documented ids are now searchable by id, meaning, consequence and
  fix, filterable by pack, and linkable -- `#/rules?rule=git/shallow-clone`
  opens that rule. Each detail panel offers the matching `devrepro explain`
  command for a terminal.
- The catalogue is generated from `devrepro/rules/catalog.py` by
  `scripts/generate_rule_docs.py`, which already wrote `docs/RULES.md` and
  already had a `--check` gate in CI. One source, two renderings, one gate --
  the alternative is a second catalogue that quietly stops being true.
- Composed ids are marked. Their prefix is a runtime value, so
  `uv/multiple-installations` is documented under a representative prefix, and
  a reader who does not know that searches for the exact string, fails, and
  concludes the catalogue is incomplete. Findings from the current report are
  counted against the representative entry for the same reason.

### Fixed - a failed report load blanked every route, including the ones that do not need one

- The shell replaced the entire console with "Could not load report" -- the
  docs, the contributors list, the rule catalogue, the diff viewer that reads a
  file you hand it. Someone whose first action is to open the tool before
  running a scan was told the whole thing was unavailable.
- The error now belongs to the routes that actually depend on a report. The
  catalogue renders without one and labels its cross-reference column "No scan
  loaded" rather than showing zeroes, because "this rule did not fire" and "no
  scan has run" are different facts.

### Added - `devrepro bench`: where a scan spends its time

- This project lost the speed argument once already. A scan took 26 seconds, of
  which 16 were resolving PATH, and `docs/MCP-EXPOSURE.md` names exactly that
  cost as a reason not to expose a scan to an agent. The fix was one line;
  finding it took an afternoon, because nothing in the tool could say which
  part was slow.
- `devrepro bench` times each probe separately and counts the subprocess calls
  it makes. The count is what explains a slow probe -- process startup
  dominates, so twelve calls and one call differ by more than the work inside
  them. `--scan` times a whole scan by phase instead, and `--json` emits the
  same numbers for a regression report.
- Sequential by default, because that is the measurement that can be
  attributed. `--parallel` reports the wall time a user actually waits for and
  leaves the per-probe figures at **zero**: eight probes sharing a thread pool
  produce overlapping wall times that sum to more than the elapsed time, and
  printing them would look like a measurement. On this machine the two numbers
  are 20s sequential and 4.2s parallel, which is the parallelism earning its
  keep rather than a contradiction.
- Not a gate. A threshold that fails a shared CI runner on a bad afternoon is a
  threshold people delete; `tests/test_performance.py` still guards the one
  algorithmic shape that actually regressed.
- Two ways the measurement could lie are pinned by tests. The first version of
  the counting runner assigned `ctx.runner` inside a `try` -- and `ProbeContext`
  is frozen, "read-only by contract", so the swap silently did nothing and
  every probe reported no subprocess calls at all. The test for it now asserts
  from inside the probe, so it fails for that reason rather than for any other
  way a count could come out wrong.

### Added - checkout readiness: the ways git leaves a working tree incomplete

- `git_health` was reachable only through `devrepro git-health`. Nothing it
  found reached `doctor`, `guard`, a snapshot or a SARIF upload, so a clone that
  cannot possibly build was invisible to every gate this project ships. A new
  `git/checkout` probe puts it in the scan.
- The theme is that git fails quietly, and every case below produces a build
  failure that names something other than the cause:
  - **LFS declared, LFS absent.** Git writes pointer files -- a few lines of
    text where a binary should be -- reports the tree clean, and leaves the
    failure to whatever opens them. The error says the image is corrupt.
    BLOCKED.
  - **LFS installed but not initialised** is a separate finding on purpose:
    identical symptom, different fix, and being told to install something
    already installed is how someone concludes the tool is wrong.
  - **Uninitialised submodules** are empty directories, not errors, so the
    build fails on a missing header.
  - **Sparse checkout** leaves `git status` clean while the directory the build
    wants is simply absent. Reported as INFO, since it is usually deliberate.
  - **Shallow clone** breaks `git describe`, `git blame` and any diff against a
    base ref -- including the one `guard --scope changed` uses.
  - **Partial clone** fetches objects on demand, which on an offline machine
    reads as repository corruption.
- Credential helpers are checked for *reachability*. A helper configured but
  not installed makes every authenticated fetch prompt; in CI that is a hang and
  then a timeout, with nothing naming the helper. Helpers git ships in its exec
  directory are not mistaken for missing, and a helper defined as a shell
  fragment is recorded as `custom` rather than verbatim -- the fragment is the
  user's text and may name internal hosts.
- Nothing here runs a credential helper, and a test asserts it: several block on
  stdin, and a diagnostic that hangs waiting for a password prompt is worse than
  one that says nothing. `git config --show-origin` is likewise avoided, because
  it would put the path of the user's global config -- which contains their
  name -- into the report; asking each scope separately costs two subprocess
  calls and keeps identity out entirely.
- `git_health` now takes an injectable runner. It built its own, so every
  branch was reachable only on a machine that happened to be in the right state
  -- which is why none of them had tests.

### Fixed - a CI matrix is a set of versions, not a wildcard

- `${{ matrix.python-version }}` is a template rather than a version, and the
  workflow parser normalised every template to `"*"`. So this repository's own
  matrix -- three operating systems by four Python versions -- reached the
  local-vs-CI check as "CI declares anything", and the check that exists to
  explain "CI passes, my machine fails" said nothing about the twelve legs most
  likely to explain it.
- `parse_workflow_matrices` reads the axes out of a workflow, so a reference
  resolves to the versions it stands for. Both YAML sequence styles are
  handled, along with `include:` legs that add versions outside the
  cross-product -- a Python tested only there is still a Python CI tests.
  `runs-on: ${{ matrix.os }}` resolves too, so the platform hint on a finding
  names the runners rather than the template.
- A reference the parser cannot resolve -- an axis built by `fromJSON`, or one
  defined in a reusable workflow -- stays a wildcard. "This is templated and we
  could not read it" is not the same claim as "this accepts any version", and
  guessing would make the tool confidently wrong on exactly the workflows it
  understands least.
- `devrepro ci-diff .` on this repository now reports the four Pythons instead
  of `*`, and a test holds that against the real workflow, so narrowing the
  matrix shows up in a diff rather than as a silently weaker check.
- Along the way: `_unquote` stripped quotes before whitespace. Splitting
  `["3.11", "3.12"]` on commas produces ` "3.12"`, whose first character is a
  space, so only the trailing quote came off and the value became `"3.12`.
  Every caller passing the right-hand side of a `split(":", 1)` had the same
  latent fault.
- `AGENTS.md` now declares the `npm run e2e` gate. The tool caught this itself:
  adding a CI job put the repository back into the drift state its own
  `agent-check` exists to find, and `matches-ci` dropped to 0/3 until the
  manifest was updated.

### Added - what is actually behind `docker`, and what shape it is in

- The container probe answered one question -- is a daemon responding -- which
  is the least useful container question there is, because a dead daemon
  announces itself the moment you try to use it. `devrepro/containers/engine.py`
  now reads the parts of `docker info`, `docker context inspect` and
  `docker system df` that decide whether a build works: which engine is
  answering, what architecture it runs, its cgroup version, storage driver,
  buildx availability, and how much of its disk is reclaimable.
- Docker Desktop, Colima, Rancher Desktop, OrbStack, Podman's machine and a
  plain Linux daemon all answer the same CLI and differ on bind-mount
  behaviour, file-sharing performance and how much memory the VM was given.
  Naming the backend turns "a daemon is not running" -- which is not actionable
  -- into "Docker Desktop is not running", which is. `docker context inspect`
  answers whether or not the daemon is up, so this works precisely when the
  daemon does not.
- **The endpoint is classified, never stored.** A Colima socket is
  `unix:///Users/<name>/.colima/default/docker.sock`, so keeping it would put a
  username into every snapshot for the sake of a string nobody reads. Only the
  scheme (`unix`, `npipe`, `tcp`, `ssh`) is kept, and a test asserts the path
  never reaches the serialized state.
- Six new rules, all documented in `devrepro explain`:
  `containers/arch-emulated`, `/cgroup-v1`, `/storage-driver-legacy`,
  `/disk-reclaimable`, `/multiple-runtimes` and `/buildkit-unavailable`.
  Architecture names are normalised first -- Python reports `AMD64` where
  docker reports `x86_64`, and comparing them raw would have labelled every
  Windows machine as emulating itself.
- Nothing is pruned, created or removed. `docker system df` reports reclaimable
  space and this reports it back; `docker system prune` stays a command you run
  yourself, because pruning deletes data and which data is expendable is not
  something a diagnostic can know.
- Snapshot diffs gained seven container axes, so "Docker works there but not
  here" is answerable when both daemons are up and the build still behaves
  differently. Backend, architecture, cgroup version and rootless mode are
  project-critical; versions and storage driver are drift.

### Changed - the Containers view shows this machine instead of a fixture

- It fetched `/api/containers-wsl`, an endpoint the server does not implement,
  and fell back to invented values on every load. A diagnostics tool showing a
  plausible green container panel that describes nobody's machine is worse than
  showing nothing. It now reads the scan report, which has carried container,
  WSL and GPU state since the pipeline stopped discarding it.
- The frontend types gained `ContainerState`, `WslState` and `GpuStack`; their
  absence is why the view had nothing real to render in the first place.
- `.kv` (a definition list for labelled facts) and `.grid-pair` join the design
  system. `.grid-2` is `auto-fit` and becomes three or four columns on a wide
  screen, which is right for stat cards and wrong for label/value pairs -- it
  squeezed a version string into three lines.

### Fixed - the browser suite was auditing one error page thirty-two times

- No report loads in the preview build -- `/api/report` has no proxy there and
  `./report.json` does not exist -- so every route rendered "Could not load
  report". The route suite asserted that *a* heading was visible, and the error
  state has a heading, so all thirty-two passed while checking the same screen.
  axe was auditing that screen thirty-two times too.
- The suites now intercept the report fetch and serve a fixture whose shape is
  real (generated by `devrepro scan`, then trimmed) and whose values describe
  nobody. Each route additionally asserts it is *not* the error page, so the
  fixture cannot silently stop being served. The error state keeps exactly one
  test, which is what it deserved.
- That surfaced a real contrast failure: `.state-error h2` used `--sev-error`,
  which is tuned to read as a colour on a chart, and measures 4.0:1 on the page
  background at 18.8px/650 -- under AA, and not large-text either, since large
  needs bold at that size. The most important heading in the app when it
  appears was the least readable one. It now uses `--sev-error-ink`.
- Vitest's default glob matched `*.spec.ts` anywhere and swept up the Playwright
  suites, failing three files on every run. The two runners share a filename
  convention and nothing else, so vitest is now scoped to `src/`.

### Added - `guard --format markdown`, and CI templates beyond GitHub

- `devrepro guard --format markdown` renders the same verdict as a
  pull-request comment and prints it to stdout. It posts nothing: what happens
  to the text is the workflow's decision, which keeps the no-telemetry
  guarantee something you can check by reading the command rather than
  something you have to trust.
- The body opens with a stable marker,
  `<!-- devrepro-doctor: environment-contract guard -->`, so a job can find its
  own previous comment and edit it. A bot that appends on every push turns a
  useful signal into fifteen near-identical comments people collapse and stop
  reading.
- Table cells are escaped. A remediation hint can contain a shell pipeline and
  a PATH contains pipes on Windows; an unescaped one splits the row into extra
  columns, and a reader who sees a mangled table concludes the tool is broken
  rather than that their machine is.
- `--json` becomes a shorthand for `--format json` rather than a competing
  flag, because scripts already pass it.
- `docs/ci-other-platforms.md` covers GitLab CI, Jenkins, Azure Pipelines and
  Bitbucket, plus the merge-request comment recipe for GitLab's Notes API. Each
  example distinguishes exit `1` from `2` and from `3`: a pipeline that treats
  "non-zero" as "blocked" reports a mistyped flag as an unusable runner.
- `docs/ci-github-actions.md` gains the equivalent GitHub workflow and a
  pointer to the new page.

### Added - browser-driven coverage of every route, and the faults it found

- `PRODUCT_GAPS.md` recorded the absence of this as gap 5, and an earlier
  version of that file claimed Playwright smoke tests existed when they never
  had. `web/e2e/` now holds three suites -- every route renders without a
  console error, every route passes axe-core, and the palette, theme and mobile
  sheet behave -- run across a desktop and a phone viewport against the
  production build, in a new `Frontend e2e + accessibility` CI job.
- The point is not duplicate coverage. jsdom never lays anything out, so the
  vitest suite could not see any of the following, all of which were real and
  all of which were found the day the browser suite was added:
  - **Every route scrolled sideways on a phone.** The topbar is a grid item, a
    grid item defaults to `min-width: auto`, and its min-content width -- 407px
    -- became the floor for the whole single-column mobile layout. The mobile
    rule also re-showed `.sidebar-label`, which labels the sidebar links *and*
    the topbar's "Jump to…" button, putting the widest item back on the
    smallest screen.
  - **The sidebar group headings failed WCAG AA on every route.** The token
    behind them, `--fg-subtle`, was 2.56:1 on white -- under even the 3:1
    large-text bar, so it could not legitimately be used for any text at all.
    Both text tiers moved one step, which keeps three distinct levels and puts
    the weakest at 4.57:1.
  - **Severity badges failed at 4.02:1 and 4.42:1.** Text on a soft tint of its
    own hue loses contrast against it. Fills are unchanged -- a swatch is not
    text -- and a darker `-ink` pair now carries the label.
  - **The brand link had no accessible name** below 68rem, where its text is
    hidden and its mark is decorative.
  - **Scrollable regions could not be reached by keyboard.** A long executable
    path turned an ordinary card into a scroll container; paths now wrap, and a
    card becomes a tab stop only when it measures as actually scrollable, so
    the fix does not add thirty empty stops to the tab order.
  - **The filter chip count was below AA twice** -- first at `opacity: 0.75`,
    then at an 80% mix toward the surface. Its size already carries the
    hierarchy, so it inherits the chip's colour.
- axe runs with reduced motion forced. It computes the *effective* foreground,
  so measuring during a card's fade-in reported 2.84:1 for a value that passes,
  and a gate that fails at random gets switched off.
- `test_docs_match_reality` now checks the Playwright claim in both directions.
  The original fault was a gaps file advertising tests that did not exist; the
  live risk is the opposite drift, and a gaps file that still calls browser
  coverage missing is the version a contributor would act on.

### Fixed - a test that passed only while the working tree was clean

- `test_a_clean_tree_passes_without_scanning` invoked `guard --scope changed`
  against this checkout, so it failed the moment anyone edited a lockfile --
  exactly when they would be running it. It now builds a temporary repository,
  and a second test covers the other half: that the fast path does not swallow
  a real contract change.

### Changed - the environment diff is a diff viewer now

- It was a six-column table keyed by array index, rendering every entry flat --
  including the fifteen classified `same`. That is a data dump: the question
  someone arrives with is "what differs that matters to this project", and the
  answer was buried.
- The engine already decided that a version difference is drift, a PATH order
  change is precedence, and a missing declared tool is project-critical, so the
  classification is now the structure: grouped, ordered most-alarming-first,
  with project-critical rows leading their group and `same` and
  `platform-expected` off by default but still counted in their chips.
- Filters, search and the project-critical toggle live in the URL. A diff is
  something you send to someone, and a link that reopens the filtered view
  beats a screenshot with a paragraph of explanation. "Copy as Markdown" emits
  the visible rows for a pull request, with pipes escaped so a PATH value
  cannot break the table.
- Files are read in the browser and never uploaded, which the drop zone says.
- Nothing is recomputed in TypeScript. A second implementation of the
  classification would drift from the Python one and the two would eventually
  disagree in front of a user.

### Fixed - three layout and accessibility faults the rebuild exposed

- `display: flex` on a `<th>` stops it being a table-cell, so the browser wrapped
  it in an anonymous cell and column widths stopped lining up with the header.
  The flex moved to an inner element.
- `.table tbody tr:last-child td` reset the border on `td` only, so a row-header
  cell kept a line the rest of its row had dropped. It now covers `th` too.
- The chip pattern hides its real checkbox at `opacity: 0`, so the browser drew
  the focus ring on something invisible and keyboard users got no indicator at
  all -- on the severity filter as well as the new one. The ring is now hoisted
  onto the label, via `:has(input:focus-visible)` so a mouse click does not
  leave one behind.

### Added - lockfiles are a requirement on the machine, not just a checkmark

- Lockfile handling was presence-only: `detectors.py` recorded that one exists
  and scored a point for it. But a lockfile is written in a *format version*,
  and a format version is a demand on the machine. npm 6 handed a
  `lockfileVersion: 3` file does not fail -- it rewrites the entire tree in the
  old format, and the damage arrives as an unreviewable diff in someone else's
  pull request. cargo before 1.78 cannot open a `version = 4` `Cargo.lock` at
  all. yarn 1 cannot install from a Berry lock.
- `devrepro/project/lockfiles.py` parses thirteen lockfile formats for exactly
  two things: the format version with the tool floor it implies, and any
  runtime pin the file records (`requires-python`, `engines.node`,
  `RUBY VERSION`, composer's `platform.php`). Nothing about the dependency
  graph: package contents are the project's business, package format is the
  machine's.
- A floor is asserted only where one is actually published. `Cargo.lock` v4 →
  cargo 1.78 is documented and stable, so it is claimed; uv's lock revisions
  are not, so the version is reported and no requirement inferred. `bun.lockb`
  is binary and is not decoded -- guessing at offsets is how a diagnostic tool
  becomes confidently wrong.
- The new `lockfiles` rule pack turns those facts into findings:
  `lockfiles/tool-too-old`, `/manager-missing`, `/format-supported`,
  `/format-unknown`, `/runtime-mismatch`, `/runtime-spec-unparseable` and
  `/unreadable`, all documented in `devrepro explain` and `docs/RULES.md`.
- Every parser is tolerant. A truncated or conflict-marked lockfile produces a
  finding carrying the reason, never a traceback; a test writes an empty file
  for each of the thirteen formats to hold that.

### Fixed - on Windows the "active" npm was the one that cannot run

- `resolve_all_on_path` tried the bare command name before the PATHEXT
  variants, and `is_active` is `precedence == 0`. Node ships `npm` -- a shell
  script Windows never executes -- beside `npm.cmd` in the same directory, so
  the unrunnable half was reported as the active installation, with no version.
  Every npm/npx/yarn/pnpm-style pair was affected, and it surfaced only because
  the new lockfile pack announced that npm 11.17.0 was not installed on a
  machine where it plainly was.
- Windows shells resolve a bare command through PATHEXT and never run an
  extensionless file, so the PATHEXT variants now come first and the bare name
  last. The shell script is still listed -- it is a genuine duplicate worth
  reporting -- it just no longer claims precedence 0.
- `tests/test_rule_catalog.py` matched version-helper names as bare substrings,
  which classified the new pack as version-checking on the strength of a
  private function called `_runtime_findings`. It now matches call sites, so
  the catalogue cannot be made to advertise ids a pack has no way to emit.

### Added - `guard --scope changed`, and the pre-commit hook it makes possible

- `devrepro guard` described itself as designed for a pre-commit hook and then
  gated on every finding anywhere, so a stopped Docker daemon blocked a commit
  touching only Python source. That is a gate people delete in week one, and
  it is why `PRODUCT_GAPS.md` recorded the hook as unshippable rather than
  wiring one up.
- Scoping to "changed files" the way a linter does is meaningless for a tool
  that scans a machine, because a machine has no per-file technical debt. What
  changes is the **environment contract**: the lockfiles, manifests, toolchain
  pins, CI workflows, container definitions and policy that declare what a
  machine has to provide. `devrepro/project/contract.py` classifies a path into
  one of those kinds, and `--scope changed` exits READY without scanning at all
  when nothing in the contract moved -- 0.6s on this repository, against 4.4s
  for a full scan.
- The kind of change also decides *where* to look: changing `pyproject.toml`
  makes the Python rules relevant and leaves Docker alone, so a stopped daemon
  no longer blocks a Python commit. A `.devrepro.toml` change re-opens
  everything, because the policy is the declaration of what the machine must
  provide.
- `.pre-commit-config.yaml` now runs that gate on this repository, and
  `devrepro init` generates the same hook instead of the `check`-based one it
  emitted while `guard` was still unsafe for the job.

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

### Fixed - the findings list gave React duplicate keys

Rule ids are not unique within a report. A single scan emits
`env/credential-names-present` twice, and `node/missing` covers both node and
git because the composed prefix is the pack rather than the component. The list
was keyed by rule id, so React reused one element for both -- which
misassociates component state, and an open evidence drawer belongs to the wrong
finding.

The regression test for this initially watched `console.error` for React's
duplicate-key warning, and passed happily with the bug reintroduced: React
deduplicates its warnings. It now asserts on the key function directly, and
fails as it should.

### Changed - findings triage

- **Filters live in the URL.** Severity, search and grouping are search params,
  so a triage view can be linked to. "Look at this" is most of what anyone does
  with a findings list, and a link that reopens someone else's filters beats
  describing them.
- Group by severity, component or rule prefix; sorted most-severe-first.
- Severity chips carry counts, including for severities currently filtered out,
  so the shape of the report is visible without changing the filter.
- **Copy as Markdown** renders the visible findings as a table for an issue.

### Added - package sources and per-runtime certificate trust

Two failures that look like network problems and are configuration problems.

A registry override -- `.npmrc` at a proxy, `pip.conf` at an internal mirror --
means two developers running the same install command fetch from different
places. The lockfile matches, the versions match, and the bytes need not. Both
project and user scope are reported, because a user-scoped override is
invisible to everyone else and is the one that explains a machine-specific
difference.

A TLS trust store is worse, because every runtime keeps its own: Node reads
`NODE_EXTRA_CA_CERTS`, Python `REQUESTS_CA_BUNDLE`, Go `SSL_CERT_FILE`, git
`GIT_SSL_CAINFO`. Behind an intercepting proxy, configuring one means
`npm install` works and `pip install` fails on the same machine, with an error
that blames the certificate rather than the missing variable. The half-
configured state is the finding.

A bundle variable pointing at a file that does not exist is reported as an
error, because the runtime silently falls back to its default store while
whoever set it believes the corporate CA is trusted.

Nothing connects to anything -- this is configuration read from disk and
environment. A registry URL carrying an inline token is reported with the
credential stripped, since `.npmrc` routinely contains one and a diagnostic
report exists to be pasted into an issue.

### Fixed - a scan took 26 seconds; it now takes 4

Sixteen of those seconds were spent resolving PATH, and the cause was
algorithmic rather than incidental. `resolve_all_on_path` tested each candidate
filename against the filesystem: a 45-entry PATH times 14 PATHEXT variants is
630 filesystem calls per tool, and with forty tool specs that is roughly thirty
thousand -- almost all for paths that do not exist. Worse, it called
`Path.resolve()`, the expensive part, *before* checking existence.

Listing each directory once turns the work from directories-times-candidates
into directories. The same 28 tool installations, the same 28 findings and the
same score come back **25 times faster** on the resolution path, and the whole
scan is 5-6x quicker.

Version probing is concurrent now as well -- those subprocess calls are
independent and I/O-bound -- with ordering preserved exactly, because
`precedence` and `is_active` are derived from it.

The test suite went from over ten minutes to eighty-three seconds, which
matters twelve times over on the CI matrix. `tests/test_performance.py` guards
the algorithm rather than the wall clock, with thresholds loose enough to
survive a shared runner.

This also changes the second prerequisite in `docs/MCP-EXPOSURE.md`, which
named scan cost as a reason not to expose scans to an agent.

### Added - manifest freshness, manifest agreement, and a readiness score

`npm` resolving says nothing about whether `npm run build` names a script the
project still defines. Someone renames it and `AGENTS.md` keeps naming the old
one; the program exists, so a PATH check passes it, and the agent finds out by
running it.

- Targets are read from `package.json` scripts, Makefile targets, `justfile`
  recipes and `[project.scripts]` -- sources that genuinely declare named entry
  points. Nothing is inferred: a freshness check that invents targets produces
  false confidence.
- Targets resolve **in the directory the command runs in**. `cd web && npm run
  build` is checked against `web/package.json`, which is where a monorepo keeps
  it. `cd` scopes to its own line, because each line of a manifest is meant to
  be runnable from the root and CI runs them that way -- carrying the directory
  across lines turned a second `cd web` into `web/web`.
- A repository with both `AGENTS.md` and `CLAUDE.md` has two documents that
  drift apart, and an agent reads whichever its vendor looks for. Commands
  present in one and absent from another are now reported.
- **Agent readiness score**, out of 17, with every point explained -- the same
  contract the reproducibility score holds. Weighted by what costs an agent
  time: a command that cannot run outranks one that is merely undocumented,
  because the first ends the turn and the second only misleads. This repository
  scores 13/17, losing four because `pip-audit` is not installed on this
  machine.

The score deliberately measures whether an agent has accurate instructions and
a machine that can follow them, and nothing about whether it will do good work.

### Added - detection of version managers that are installed but bypassed

A version manager works by putting its shims early on PATH, so the whole
mechanism depends on ordering -- and ordering is what silently changes when an
installer prepends itself or an IDE launches with a different PATH from your
terminal.

When that happens the manager is still installed, still configured, and still
reports the version it intends: `pyenv version` says 3.12 while
`python --version` says 3.9. Neither tool is wrong about what it was asked, so
nothing anywhere reports a problem, and the project's pin is quietly not in
effect.

`{tool}/shim-bypassed` names the winning path, the shim it precedes, and the
manager being bypassed. Eleven managers are recognised: pyenv, asdf, mise,
rbenv, nodenv, volta, nvm, fnm, conda, rustup and SDKMAN.

A manager that simply does not provide a tool is not reported -- rustup owning
`.cargo/bin` says nothing about `python`, and a check that flagged every manager
against every tool would be noise, which gets switched off.

The analysis is platform-parameterised, so a Windows PATH layout is tested from
a Linux CI leg. That immediately caught a marker of mine that could never match:
`normalize_path` runs `os.path.normpath`, which strips a trailing separator, so
the `.fnm/` marker would never have fired against a real entry.

### Fixed - `generate mise` emitted a file that could not be parsed

Run against this repository it produced:

```toml
[tools]
ci:python = ""3.12""
tomli = "2.0; python_version < '3.11'"
mkdocs-material = "9.7.7,<9.8"
```

Four problems in a handful of lines. A CI-derived value already carried its own
quotes, so the generator's quoting doubled them and the document is not valid
TOML at all. `ci:` entries record what a workflow declares and are not tools.
Library dependencies are not things a version manager installs. A PEP 508
environment marker is not a version.

A generator whose output does not parse is worse than no generator: the reader
trusts it, commits it, and finds out later. Output is now restricted to runtimes
mise and asdf actually manage, with versions normalised to something they
accept, and a test parses the result with a real TOML reader.

Two smaller output bugs fixed alongside it: the preview printed a Python dict
repr above the content it described, and the footer passed Rich markup to
`typer.echo`, which does no markup rendering, so `[grey50]` tags printed
literally.

### Added - deterministic image pinning and devcontainer features

- `generate devcontainer --pin` resolves the base image tag to an immutable
  `sha256` digest. Without it the file now carries a comment saying the tag is
  mutable, because a reproducibility artefact that silently changes is worse
  than one that admits what it cannot promise.
- Pinning goes through the local docker CLI rather than an HTTP call: the
  user's registry credentials, mirrors and proxy settings already live there.
  It is opt-in for the same reason `network --allow-network` is.
- The generated devcontainer now installs the runtimes the project declares,
  carrying the declared version through. A devcontainer that installs nothing
  the project needs is one the reader has to finish by hand.

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