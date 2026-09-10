# Changelog

All notable changes to DevRepro Doctor are documented here.
Format based on Keep a Changelog; versioning follows SemVer.

## [Unreleased]

A correctness pass, in the same spirit as 0.2.0: things the project claimed to
do, it now actually does. Every item below was found by running the tool, not
by reading it.

### Added - editor, browser and IDE surfaces, none of which needs a build

- **`extensions/vscode/`** — plain CommonJS with JSDoc, no dependencies, no
  compiler, no bundler, no pinned `vscode.d.ts`. Four moving parts avoided in a
  project whose selling point is that it does not accumulate them, and the
  folder loads directly with `--extensionDevelopmentPath`. It does **not** scan
  on startup: an extension that spawns processes while you open a file is one
  you disable in week two. Only findings whose evidence names a
  repository-relative path become squiggles — a stopped Docker daemon is not a
  property of any line of code, and absolute paths are refused because a
  diagnostic inside somebody's home directory is a username on screen during a
  screen-share. A non-zero exit is the contract working, not a failure.
- **`extensions/browser/`** — a readiness badge on GitHub that makes **no
  network requests at all**. The obvious implementation fetches a score for
  every repository you visit, which means an endpoint and a log of your browsing
  on somebody's server; this project exists to be the opposite of that shape, so
  you save badges locally from `agent-check --badge`. A test asserts the source
  contains no `fetch`, `XMLHttpRequest`, `WebSocket` or `sendBeacon`, because a
  privacy claim nothing enforces is one that decays. The badge is drawn beside
  the repository name, never injected into the README — that is somebody else's
  content.
- **`extensions/jetbrains/`** — External Tools XML rather than a plugin. A
  plugin is a Kotlin/Gradle project, a compatibility range, a Marketplace
  listing and a signing key, maintained by a project that ships no compiled
  artefacts anywhere else; this works in every JetBrains IDE today. No surface
  offers `devrepro fix`: a menu item that runs remediations is one click from
  running them by accident, and the `--yes` gate exists so a person agrees each
  time.
- **`web/src/i18n.ts`** — a catalogue, a lookup, locale resolution and plurals
  through `Intl.PluralRules`, with no library. It localises the **chrome, not
  the content**: findings come from the Python side, are generated per machine
  across 159 rule ids, and a half-translated diagnostic is worse than a
  consistent English one. Rule ids are never translated — an identifier that
  changes by locale is not an identifier.

### Changed - two catalogue items recorded as decisions

- **An interactive TUI** is deferred with a reason. Every cross-platform TUI
  toolkit is a dependency (`curses` is absent on Windows), and what one buys is
  triage — which the web console does today, offline, over a sanitized report.
  For somebody on SSH with no browser, `--json` piped into `jq` is the honest
  answer and needs nothing from us.
- **CDP runtime profiling** is not built. That is `react-doctor`'s territory,
  it does it well, and driving CDP means attaching a debugger to somebody's
  running process — the furthest thing from read-only in this project — to
  answer a question about application performance rather than about the machine.
  `docs/interop.md` links there instead.

### Added - a snapshot viewer, an export, a gallery and a tour

- **Snapshot viewer.** Somebody's build fails, a colleague asks for `devrepro
  snapshot`, and now there is a 200 KB JSON file in a chat thread nobody can
  read. Every tool that solves this solves it with an upload -- and a snapshot
  describes a developer's machine, so an upload is the one thing this project
  will not add. `FileReader` and `JSON.parse`, in the page, with no endpoint
  behind it, and the page says so where somebody about to paste a colleague's
  machine state will read it.
- **Markdown export**, because the reason to export a diagnostic is to paste it
  into an issue -- and an image of a table is a table nobody can search, quote or
  diff. Blockers first and capped, since a comment opening with forty INFO rows
  is one nobody scrolls past. Pipes in a summary are escaped rather than
  breaking the table.
- **PDF via the browser's own print dialogue**, driven by a print stylesheet.
  No library: a PDF renderer is several hundred kilobytes to reproduce, worse,
  something every browser already does. **PNG is deliberately not offered** --
  DOM-to-canvas needs a ~200 KB dependency, reproduces the layout approximately,
  and produces the least useful artefact of the three.
- **A component gallery route** instead of Storybook. Storybook is ~40 MB of
  devDependencies, its own build and a second place for the theme tokens to be
  defined, for a design system of about a dozen components -- and a component
  rendered in the real shell inherits the real tokens, so a story that looks
  right here *is* right. A Storybook story renders in an iframe with its own
  decorators, which is exactly where token drift hides.
- **Visual regression** on that one route, in both themes, on the existing
  Playwright suite. Baselines are per-platform and are **not** committed from a
  developer's machine: a Windows screenshot differs from a Linux one in font
  rasterisation alone, and committing one would fail every CI run on the other
  and teach everybody to ignore the suite. The test skips with a loud reason
  where no baseline exists, and the print-media assertion beside it never skips.
- **A tour that never launches itself.** Product tours are disliked for a
  consistent reason: they interrupt somebody who came to do something specific,
  on their first visit, when they have the least patience for it. This one sits
  in the navigation, reads in a minute, and names *where* each thing is rather
  than dragging you there.

### Fixed - `--fg-subtle` failed WCAG AA on the surfaces it is used on

An axe sweep of the new snapshot-viewer route caught `.subtle` at **3.88:1**.

This token has now been wrong twice for the same reason. It was `--grey-400`
(2.56:1 on white, below even the large-text bar); the fix moved it to
`--grey-500` and measured it **against the page background**, where it is
4.57:1 and passes. Subtle text is rarely on the page background -- it is inside
a card on `--surface-2` (3.88:1) and in an empty state on `--surface-3`
(3.47:1).

Dark mode had the identical bug and nobody had measured it: `--grey-400` is
6.68:1 on `--surface` and **4.21:1** on `--surface-3`.

The rule is not "clear AA on the background" but "clear AA on the deepest
surface the token can land on". `--grey-550` (light) and `--grey-450` (dark)
clear 4.5:1 on every surface in their theme, and both stay distinct from
`--fg-muted`, so the three-tier ramp survives instead of collapsing to two. The
measurements are in the stylesheet so the next person does not re-derive them.

### Added - what a rule-pack author needs, and honest install docs

- **`devrepro rules-test <module>`** checks a rule pack for the four things
  that make one wrong, each of which an author infers from reading the
  built-ins: a finding with no evidence (the model refuses to build one, so it
  arrives as an exception in somebody else's CI), a rule id under a built-in
  prefix (`devrepro explain` then describes somebody else's rule), side effects
  (checked **statically** -- a pack that only writes under some condition passes
  a runtime check on every machine except the one it fails on), and an uncaught
  exception (the engine turns it into `rulepack/<name>/failed`, so an author
  never sees their own crash). It says out loud that it is importing and running
  your module.
- **`templates/rule-pack/`** is a working pack to copy: a directory rather than
  a cookiecutter, because a template you can read start to finish teaches the
  contract better than a generator that hides it. Its own tests run in this
  project's CI, because a template nobody runs teaches the wrong contract -- the
  first version of this one read `ctx.env`, which `RuleContext` does not have.
- **`docs/PLUGINS.md`** now says what a pack actually receives. It never did,
  which is how the example came to read a field that does not exist. And why
  there is no environment in `RuleContext`: probes read variables and hand the
  engine conclusions, so a pack able to read raw values would be a pack able to
  put them in a report.
- **`docs/TROUBLESHOOTING.md`** maps symptoms to causes, ordered by how often a
  symptom sends people to the wrong place -- exit code 137 is the OOM killer and
  not a compiler crash; an expired certificate is usually a drifted clock; "no
  kernel image is available" is a compute-capability mismatch in a message that
  does not contain the words.
- **`docs/INSTALL.md`** documents every install path **and opens by saying none
  of them works yet**, because the name is unclaimed on PyPI. That beats what
  this project shipped for months: a README opening with a command that returns
  404. `uvx` leads, since a diagnostic is usually run once on a machine that is
  misbehaving and installing into the environment you are debugging changes the
  thing you are measuring.
- **`packaging/`** carries Homebrew, Scoop and winget templates with visible
  `PLACEHOLDER`s, and `scripts/check_packaging.py` fails a manifest that is
  halfway between template and real -- the state that looks finished and fails on
  the first install anybody attempts.
- **`docs/UPSTREAM-PLAYBOOK.md`** writes down how this project earns attention,
  including the test that separates it from spam: if the tool did not exist,
  would the comment still be worth posting?

### Changed

- A hosted rule-pack registry is recorded in `PRODUCT_GAPS.md` as **deferred
  with a reason**. Entry points already are the registration mechanism, and a
  registry would currently list zero packs -- worse than none, because it
  advertises an empty ecosystem.

### Added - fleet governance, and the line each feature stops at

Five of these are one step from something a person could reasonably object to,
so most of the work is where each stops.

- **Onboarding analytics** (`GET /api/v1/fleet/onboarding`). Time from
  enrolment to the first READY snapshot. **Aggregate only, with a floor**: a
  per-person onboarding time is a performance metric whatever the dashboard
  calls it, it is wrong for obvious reasons -- somebody spent their first week in
  orientation -- and once it exists somebody asks for it broken down by name.
  Nothing is reported below a cohort of five, and no machine, user or label
  appears in the payload. Machines that **never** became ready are counted
  separately: a metric computed only over successes hides the population it
  exists to find.
- **Policy simulation** (`POST /api/v1/fleet/simulate-policy`). A paved road is
  normally rolled out by editing a policy and finding out. This applies the
  proposed policy to each machine's last stored snapshot and reports who newly
  fails and **which requirement did it** -- the count says how bad, the cause
  says which line to soften. Snapshots with no tool data count as unevaluated
  rather than passing, because a simulation that quietly narrows its own
  denominator under-reports the blast radius.
- **Team-scoped baselines.** RBAC shipped org-wide, so any maintainer could
  approve any project's baseline -- a control that reads as present and is not.
  `project_members` scopes it; `admin` still crosses boundaries, because
  somebody has to fix a team whose maintainer left, and every crossing is
  audited. A project with no members stays open to any maintainer, so this
  arrives as a tightening rather than as an outage on upgrade.
- **`devrepro notify`** renders a Slack Block Kit or Teams Adaptive Card
  payload and posts nothing. A bot would need a token this project would have
  to hold, refresh and be trusted with, plus a workspace administrator's
  approval; a webhook URL is already the thing every CI system has a secret
  slot for. Native formats, because Markdown posted into either renders as
  something that looks broken.
- **`devrepro notify --mdm jamf|intune|kandji`** emits an extension-attribute
  or compliance script. Each reports **a verdict and a blocker count and
  nothing else**: your MDM already knows the machine, and putting a developer's
  local software inventory in front of that audience is the scope creep that
  gets a tool banned. An absent devrepro reports UNKNOWN, never compliant.
- **`devrepro monitor`** takes a snapshot when nothing is wrong, because nobody
  takes one on a Tuesday and the first snapshot anybody has is the one after the
  build broke -- exactly one, and one snapshot diffs against nothing. No daemon,
  no network. `--schedule` prints a scheduler entry with its removal
  instructions rather than installing one. A clock that moved backwards takes a
  snapshot instead of stalling until it catches up.
- **A real fleet heatmap** replaces `3.11 ×4 · 3.12 ×2`, which was a sentence --
  so finding the diverged tool meant reading every row, and seeing divergence at
  a glance is the entire value of a fleet view. Colour encodes **share**, not
  count, so a team of four and a team of four hundred look the same when equally
  divided. Never colour alone: every cell carries its count as text and a full
  comparison in its title.
- **Release artefacts are signed**, and build provenance is attested from the
  job that produced them. SHA256SUMS proves the files match a list published by
  whoever published the files; a keyless Sigstore signature answers who built
  them, with no key to rotate. Every signature lands in a public transparency
  log -- for public artefacts that is not a cost, and it is the same trade
  `devrepro attest` refuses to make on a *user's* behalf.

### Fixed - the p90 excluded the tail

`_percentile` used `round` where nearest-rank needs `ceil`. With six values
`round(0.9 * 6) - 1` lands on index four -- the fifth of six -- so the one
machine that took three weeks never reached the p90 at all. A tail metric that
systematically excludes the tail is quietly wrong in the flattering direction
and reads as a healthy fleet forever.

`scripts/check_action_pins.py` also stopped conflating two answers: GitHub being
unreachable and no tag pointing at a SHA both produced an empty list, so an
offline run reported every claim as checked and unconfirmed.

### Added - reproduction: a container somebody else can run, and the search tools

`docs/REPRODUCTION.md`. The README opens by promising to answer "Docker works
there but not here", and a diff only tells a maintainer what is different -- a
reproduction tells them they are looking at the right thing.

- **`devrepro reproduce`** drafts a recipe and runs nothing. The verb is
  `reproduce`, not `generate`: `generate` already means "draft a config from
  what I detected", and one verb doing both would leave them sharing a set of
  flags that half apply.
- **The assertion is what makes it a reproduction.** A recipe that sets up an
  environment and stops is a Dockerfile; this one ends by running the thing that
  failed, so when somebody fixes the cause **the recipe stops working** -- which
  is the signal anybody actually wants. The failing command is a `CMD`, not a
  `RUN`: a `RUN` that fails aborts the build, and an aborted build looks exactly
  like a broken recipe.
- **What it cannot carry is named, not omitted.** A container engine in the
  original (reproducing needs a mounted socket, which is a privilege escalation
  rather than a build step), a GPU, a non-Linux host -- and the one found by
  running it, `no-install-step`: with no lockfile the container has a runtime and
  none of the project's dependencies, so the command dies with "not found". That
  is the most expensive kind of wrong reproduction, because it looks like a
  successful one.
- **Five formats from one recipe** -- Dockerfile, `repro.sh`, compose,
  devcontainer, Nix flake -- so a Dockerfile and a flake describing the same
  failure cannot drift apart. `repro.sh` prints the interpretation rather than
  leaving it to an exit code, because the counter-intuitive part is that
  **success is failure**: a recipe that exits zero has reproduced nothing.
- **Sandbox adapters** for E2B, Daytona and container-use: configuration files,
  not API clients. Three integrations would mean three credential stores and
  three release cadences inside a tool whose value proposition is that it
  contacts nothing.
- **`--check`** regenerates and compares, so a committed recipe that quietly
  stopped describing the project fails a CI job rather than a maintainer six
  months later. The first version of it reported every file stale the instant
  after writing them -- the header carries a scan timestamp -- so the comparison
  now ignores the timestamp lines: a recipe is stale when what it *describes*
  changed, not when it was regenerated.

- **`devrepro bisect`** is `git bisect` for a machine. Everybody's instinct is
  to read a forty-line environment diff and pick the suspicious-looking line,
  which works for a runtime version and fails completely for a locale or a PATH
  order. It applies nothing -- that would mean editing a PATH or installing a
  version on somebody's machine -- and proposes candidates for you to apply and
  answer. Two sanity checks run first, because skipping them is how a bisect
  returns a confident wrong answer: a baseline that already fails, and a diff
  that does not contain the cause, are both reported as inconclusive.
- **`--minimise`** runs delta debugging instead, answering the question
  bisection structurally cannot: when two changes are each harmless and break
  things only together, a bisect names one of them and is wrong in a way that
  reads as right. Bounded, because every verdict is a person running a build,
  and when the bound bites it says the result may not be minimal.

- **`devrepro repro-rate`** records how often reproductions actually work.
  Every tool in this space claims to reproduce environments and none publishes a
  rate, because the number is going to be disappointing. Publishing it anyway
  beats implying 100% and letting each user discover otherwise separately.
  `different-failure` counts as **not** reproduced -- that single choice is what
  keeps the number honest, and counting it as success is how vendor benchmarks
  reach 95%. No rate below ten attempts. Local only; nothing is uploaded and
  there is no aggregate anywhere.

### Added - stopping an agent session before it starts, and pricing the gaps

- **`agent-check --gate`** exits BLOCKED when this is not a reasonable place to
  begin. Two independent grounds, answering different questions: readiness asks
  whether the agent can get work done, blast radius asks what it reaches if it
  goes wrong. A clean, well-documented checkout with production credentials in
  the environment scores well on the first and is the **worst** case for the
  second, because everything about it invites confidence. A threshold rather
  than any-finding, for the same reason `guard --scope changed` exists: a gate
  that fires on every repository is one removed in week one.
- **`agent-check --hook claude-code|shell`** prints the configuration and never
  writes it. A hook is code that runs on every session, and installing one on
  somebody's behalf is a larger permission than a diagnostic needs. The Claude
  Code hook is `SessionStart`, not `PreToolUse` -- a per-tool hook would re-scan
  the machine on every single tool call.
- **`agent-check --badge`** emits a shields.io *endpoint* payload rather than a
  static SVG, so the number comes from a scan instead of from whenever somebody
  last committed an image. Green starts at 90%; green at 60% would be a choice
  to make a mediocre score look fine.
- **`token_cost`** in the JSON report: roughly what this repository's gaps cost
  an agent in wasted turns. An estimate from a stated model, not a measurement --
  every per-signal cost is a named constant, the assumed tokens-per-turn travels
  in the payload, and the figure rounds to the nearest 5,000 because 43,712
  implies a measurement nobody made. **No price is attached**: model pricing
  changes monthly, and a stale dollar figure would be worse than none.
- **`sandbox/memory-parity`, `sandbox/cpu-parity`, `sandbox/network-parity`.**
  `ci-diff` compares toolchains; this compares the shape of the box. Exit code
  `137` is `128 + SIGKILL` from the OOM killer, which writes nothing to the
  build log and reads as a compiler crash. Build tools that detect parallelism
  through `nproc` read the *host's* core count and spawn that many workers into
  a smaller container -- the build does not fail, it thrashes. And a sandbox with
  no network is right for an agent and wrong for a first dependency install,
  with both declarations routinely in the same repository. Compose's `2g`
  (10^9) and `2gb` (2^30) are parsed as the different numbers they are.

### Added - four things somebody already wrote down and nobody re-reads

- **`<tool>/cache-credential-committed`.** `nx.json` takes an
  `nxCloudAccessToken`, `.bazelrc` takes `--remote_header=Authorization=...`,
  and both get committed without a second thought because they read like
  configuration rather than like secrets. A read-write build-cache credential is
  a supply-chain secret: whoever holds it writes cache entries that every
  developer and every CI run then treats as trusted build output. The finding
  reports **the field's presence and never its value** -- that is the whole of
  what anybody needs to act. `buildtools/detected` reports which orchestrator is
  in use and whether it has a remote cache at all, because a team that believes
  it has a shared cache and does not is wrong about why CI is slow.
- **`editor/style-conflict`.** `.editorconfig` says two spaces, prettier says
  four, and the result is forty lines of whitespace on a two-line change that a
  reviewer blames on the author. Both tools are behaving exactly as configured,
  which is why nobody finds the cause. Only the three settings both sides
  genuinely model are compared, and **no defaults are filled in**: a project
  that never configured a width has not disagreed with anything, and reporting
  prettier's default 80 as a conflict would put an opinion in its mouth.
- **`kubectl/context-not-local`.** The current context is global to your user,
  survives reboots, and appears in no normal prompt. Every regretted `kubectl
  delete` was typed into a shell whose context the person believed was something
  else -- the same blast-radius question `agent-check` already asks about
  writable paths. Read from the kubeconfig, never from a cluster: `cluster-info`
  would be an authenticated request to a production cluster from a diagnostic
  command. The production guess is name-based and says so.
- **`shell/slow-startup`.** Four or more subshell-spawning initialisations in a
  profile -- pyenv, nvm, direnv, conda -- is one to three seconds on every new
  terminal, every git hook that spawns a login shell and every `bash -lc` in CI.
  Nobody attributes it; a shell that takes two seconds reads as a slow machine.
  Counted, not timed, because timing a shell start means running the user's own
  configuration.

### Added - `devrepro onboard`

A setup script for what **this** machine is missing. Onboarding documents rot
because they describe a machine nobody has: they list every dependency,
including the eleven a new starter already had, and the one that matters is on
line 40. This emits the difference between policy and scan, which on most
machines is two lines.

Nothing is executed. Commands that pipe a remote script into a shell are
printed **commented out** -- that is a decision, and a generated file should not
make it on somebody's behalf -- and where no install command is known the tool
is named rather than guessed at, because a wrong command in a setup script is
worse than an absent one.

### Fixed - three call sites told a machine with Python 3.14 to install Python

Found by running `devrepro onboard` against this repository. Every consumer of
the tool list had copied the same comprehension:

    {t.name: t.version for t in report.tools if t.is_active}

A machine routinely reports the same tool more than once with only one readable
version -- on Windows, `python` resolves to both a real interpreter and the App
Execution Alias, a stub that exits without printing anything, and both are
marked active. Last-one-wins mapped `python` to `None`, and `None` reads
downstream as "not installed".

`onboard` printed an install command for a tool that was present. `advisories`
skipped the version comparison for a tool it had data about. `attest` recorded a
null version in a document meant to be signed.

`ScanReport.active_versions()` does the resolution once: a readable version wins
over an unreadable duplicate, and the name is still present with `None` when
nothing readable exists, because "installed, version unknown" is a real answer
this project reports elsewhere.

### Fixed - a default scan was opening connections to three third-party hosts

`devrepro bench` put `network/tls` at 11.4 of 37.5 sequential seconds while
running **zero subprocess commands**, which for a probe means it is blocking
in-process. It was: a TLS handshake to `github.com`, `registry.npmjs.org` and
`pypi.org`, plus an HTTPS request to read a `Date` header for the clock-skew
check -- on every `doctor`, `scan`, `preflight`, `guard` and `snapshot`.

`devrepro/network/diagnostics.py` gates every one of those on
`allow_network=True`, and `devrepro network` passes the flag correctly. The
probe went around both.

Nothing about the machine was transmitted -- these were reachability handshakes,
not uploads -- but three third-party hosts, and any corporate proxy in the path,
could see that the machine had connected. That is a disclosure, and this
project's headline invariant says nothing leaves the machine unless the user
asks. `docs/PRIVACY.md` said so too, and `devrepro contract`, added earlier in
this same release, publishes it as a guarantee.

- Endpoint reachability and TLS now need `--allow-network`, on `devrepro
  doctor` as well as `devrepro network`. Without it a scan opens no sockets.
- Proxy configuration is still reported in every scan: that is read from
  environment variables and `git config`, with credentials redacted, and needs
  no connection.
- The skip is reported as `network/checks-skipped` rather than left silent -- a
  scan that says nothing about network health reads as one that found it fine.
- `docs/PRIVACY.md` gains a "What is sent, and when" section that states the
  correction rather than quietly moving on, plus a table of what each opt-in
  flag reveals to whom.

Scan wall-clock: 17.5s to 8s.

### Added - three host facts that make builds slow or wrong

- **`host/slow-filesystem`.** A WSL shell working under `/mnt/c`, or a project
  on an SMB or NFS mount, pays a millisecond per file operation instead of a
  microsecond. A dependency install performs hundreds of thousands of them, and
  no profiler points at it because nothing is failing -- it reads as a slow
  build tool. This classifies the mount rather than benchmarking it: a number
  nobody can act on is worth less than "your tree is on /mnt/c", which names the
  cause and the fix at once.
- **`host/antivirus-scans-build-dirs`.** On Windows, Defender's real-time
  protection inspects every file a build opens, synchronously. The finding
  reports which of the project's dependency and output directories are not
  excluded -- including in a workspace one level down -- and carries the exact
  command. It is stated as a **trade, not a recommendation**: excluding a source
  tree whose install scripts execute code you did not read is a genuine
  reduction in protection, and whether it is worth it is not this tool's call.
  Nothing is changed; `Set-MpPreference` appears nowhere, and a test parses the
  module to prove it.
- **`host/clock-unsynchronised`.** Clock skew was already detected, and skew is
  the symptom. This asks whether anything is correcting the clock at all,
  because a machine with no time source is not skewed *yet*. When it drifts, the
  first symptom is usually a TLS error blaming a certificate that is fine.

Two faults in that probe were found by running it rather than reading it:
`w32tm` reports a stopped Windows Time service by *failing*, so a probe reading
only successful output stayed silent on exactly the machines the check exists
for; and a workspace keeps its `node_modules` one directory down, so a
root-only search missed the largest directory in this repository.

### Added - the CUDA triple, instead of a presence check

`gpu/cuda-driver-too-old`, `gpu/cuda-compatible`, `gpu/cuda-toolkit-absent` and
`gpu/mixed-architectures`. Nothing about a broken CUDA setup is discovered by
checking whether a GPU exists -- the GPU exists. What fails is the relationship
between the driver's runtime ceiling, the installed toolkit and the framework
build, and the error names none of the three.

- The driver ceiling is **read from `nvidia-smi`**, not looked up in a bundled
  table that would be wrong within a release. The old probe collected that
  number into a note and discarded it.
- Minor-version compatibility is honoured: CUDA 12.4 on a driver reporting 12.2
  is fine, and a naive `toolkit <= ceiling` check reports a working machine as
  broken -- after which somebody upgrades a driver that was not the problem.
- Devices are enumerated, because two cards with different compute capabilities
  produce `no kernel image is available for execution on the device` at runtime,
  on whichever device the scheduler happened to pick.
- Which CUDA a framework wheel was built for is deliberately **not** checked:
  finding out means importing torch, which takes seconds and can initialise a
  context on a device somebody else is training on. The hint names the one-line
  command instead.

### Added - the surfaces other software consumes

- **`devrepro contract`** publishes what a caller may rely on, as data rather
  than prose: exit codes with their real meanings, the JSON fields that never
  move, and -- as importantly -- the list of things deliberately not promised.
  `check_report()` is importable, so a consumer's own test suite asserts against
  it instead of against a document somebody read once. A wrapper built on
  terminal output or on a finding count has built on sand, and this says so
  before a red build does.
- **`guard --format annotations`** emits GitHub workflow commands. SARIF is the
  better format and needs Advanced Security to upload from a private repository,
  which most teams do not have, so the existing SARIF path works in the demo and
  does nothing where it was needed. Annotations cost nothing and work on every
  plan. **Only findings whose evidence names a repository-relative path are
  anchored to a line** -- a stopped Docker daemon is not a property of your
  source, and pinning it to line 1 of something is how a team learns to ignore
  every annotation in the run. The ten-per-level cap is announced rather than
  applied silently.
- **`guard --format check-run`** builds a Check Run payload to POST. Built,
  never sent; the unanchored findings go into `output.text` rather than being
  given invented line numbers to satisfy the API.
- **`devrepro pins`** reports whether the update bot can see the files that pin
  your toolchain. Dependabot has no `package-ecosystem` that reads `.nvmrc` or
  `.tool-versions` at all, so a repository can have a thorough `dependabot.yml`
  and a Node version nothing will ever bump. Renovate does read them -- until
  `enabledManagers` is set, which turns the default-on list into an allowlist.
  No bot configured is reported as nothing to check, not as a gap.
- **`devrepro watch`** re-checks when the environment contract changes, and not
  otherwise. Polling rather than a notification library: the watched set is
  dozens of files, and the three platforms have three mechanisms with three
  failure modes -- one of which, the Linux inotify watch limit, this project
  diagnoses as a problem elsewhere. Debounced, because one editor save is
  routinely a truncate, a write and a rename.
- **Merge queues** are documented in `docs/ci-github-actions.md`.
  `GITHUB_BASE_REF` is empty for `merge_group` events, so a guard that uses it
  compares against nothing and passes everything; the base is
  `github.event.merge_group.base_ref`, and `fetch-depth: 0` matters just as much.

### Changed

- `PRODUCT_GAPS.md` records attributed CI-footprint reporting as **cut**, not
  deferred. The honest number is a fraction of one job, and presenting it as a
  headline turns a diagnostic tool into a dashboard about itself. `devrepro
  bench` already answers the version of the question that matters.
- `ExitCode` gained a `MEANINGS` mapping. Python keeps only a class docstring,
  so `ExitCode.BLOCKED.__doc__` returns the same text for every member -- reading
  it at runtime would have shipped a contract document giving all five codes the
  same meaning.

### Added - evidence somebody outside the team can actually use

Three commands, `docs/COMPLIANCE.md`, and one rule pack. All offline.

- **`devrepro attest`** emits an in-toto Statement v1 about an environment --
  the shape cosign, Sigstore and the SLSA verifiers already read. `sign-snapshot`
  signs with an HMAC, which proves to *you* that *your own* file did not change
  and is worth nothing to anybody else, because verifying the signature requires
  holding the key that could have forged it. Three kinds: `environment`,
  `reproduction` (binding an artefact to the environment attestation it came out
  of) and SLSA `provenance`, declared as level 1 rather than claimed as more.
  It **prints the cosign command instead of running it** -- Sigstore signing
  opens an OIDC flow and writes a permanent public transparency-log entry, and
  there is no honest way to ask for that from inside a diagnostic command.
- **`devrepro evidence`** maps a scan onto CRA, NIST SSDF and SLSA control
  names. Most controls come back `out-of-scope` **with the reason in the
  exported file**, because a compliance export that reports green across a whole
  framework hands somebody a document that is wrong. `evidenced` means the facts
  an assessor asked for are present -- not that the control is satisfied, which
  needs a person who knows what the product is.
- **`devrepro evidence --licenses`** inventories the *toolchain's* licenses,
  which no SBOM tool does because the compiler is in no lockfile. Every row
  carries an obligation beside the SPDX identifier: compiling with GCC does not
  put your output under the GPL, and a table that shows the identifier without
  the Runtime Library Exception has told a legal team something false.
- **`devrepro advisories`** checks installed tool versions against an offline
  advisory set, and the `advisories` rule pack runs it in every scan. `fixed` is
  a list because backports are how these actually ship: a fix released as 2.45.1,
  2.44.1 and 2.43.4 means 2.44.0 is affected and 2.44.1 is not, which comparing
  against the highest number gets exactly backwards. The bundled set is a seed,
  not a feed -- small, every entry carrying a URL you can open. An external
  bundle must be signed (`DEVREPRO_ADVISORY_KEY`), because the interesting attack
  on that file is not adding a false entry but quietly removing a true one.
  Warnings only, never a block.
- **`devrepro history --verify`** checks a hash chain over stored snapshots:
  each entry commits to its snapshot's digest and to the entry before it, so an
  edit, a deletion or a reordering is visible. It says plainly what it cannot do
  -- there is no secret, so anybody with write access can rebuild the chain --
  and prints the one digest worth recording somewhere else.

### Fixed

- `devrepro rules` printed a Python dict to a human. The same fault was fixed in
  `check` and `generate` earlier; it survived here because a one-key dict reads
  almost like a sentence.

### Added - an MCP server, with the three prerequisites its own design doc set

- `devrepro mcp --root <path>` speaks newline-delimited JSON-RPC 2.0 on stdin
  and stdout. `docs/MCP-EXPOSURE.md` had been an assessment with three
  conditions; all three are met rather than deferred.
- **The verdict travels in the payload.** A process exit code does not cross
  this boundary, and `BLOCKED = 2` means something else entirely in three
  sibling projects. Every result carries `verdict` and the `exit_code` it would
  have been, so a caller wiring this alongside the CLI sees the two agree.
- **Reports are cached with an explicit refresh.** Five seconds per tool call
  would dominate a conversation with a model that asks several times while
  reasoning. Each result says whether it came from the cache and when it was
  taken; `refresh: true` forces a new scan.
- **The root is configured, not argued.** Every path is resolved against
  `--root` before the check, so `..` and a symlink fail identically. Which
  directory to inspect is authority this does not delegate to a model.
- `fix`, `serve`, `server-backup`, `server-restore`, `init` and `generate` are
  refused **with their reasons**, not merely absent. A model that asks for
  `fix` and gets "no such tool" concludes the server is incomplete and works
  around it; one that gets the paragraph about the `--yes` gate learns
  something true about the boundary.
- No SDK dependency. The protocol is JSON-RPC with three methods that matter,
  and a server you must install a second package to run is one most people will
  not run. A notification gets no response at all -- answering one is a
  protocol violation some clients treat as fatal -- and neither malformed JSON
  nor a crashing tool call ends the session.
- The "agent skill installer" is now a documented decision not to build: one
  protocol beats five vendor manifest formats to keep in step.

### Added - whether the build caches are earning their place

- A compiler cache with a 15% hit rate is not saving time, it is spending it:
  every miss pays a lookup, a write and an eviction on top of the compile it
  did not avoid. The usual cause is a cache smaller than the working set, so it
  evicts what it is about to need again -- and the symptom people report is
  "builds got slower after we turned caching on", which nobody attributes to
  the cache. `ccache` and `sccache` both publish the numbers; nothing read
  them.
- The new `caches/health` probe reads both, in both `ccache` layouts -- version
  3 prints separate counters with no totals and version 4 prints totals with
  percentages, and a parser written against one returns nothing on the other,
  which reads as "this cache is fine". A cache at its size ceiling is reported
  alongside the rate, because the ceiling is the cause and the rate the
  symptom.
- A cache with fewer than fifty calls gets no verdict. A fresh cache is 0% by
  arithmetic, and reporting that would train people to ignore the finding that
  matters.
- Disk headroom joins it: below 5 GB is a warning, below 1 GB a blocker. "No
  space left on device" arrives mid-build from a step unrelated to the cause.
- **Nothing walks a cache directory.** A Gradle cache is routinely tens of
  gigabytes and sizing one per scan would undo the performance work outright,
  so the inventory is presence-only and each entry carries the command that
  measures it. A test asserts the module contains no directory walk at all.
- Only *relocated* caches produce a finding. A cache where it belongs is not
  news; one redirected by an environment variable onto a network share or a
  nightly-cleaned directory is a common cause of "builds are slow on this
  machine only", with nothing in the build output to explain it.

### Fixed - the probe pool was sized 8 while the probe count reached 18

- Ten probes queued behind the first eight, so a scan that had been 4.2s became
  8.3s while every individual probe stayed exactly as fast as before.
  `devrepro bench --parallel` found it in one command, which is what it is for.
  The pool is now sized to the probe count, bounded at 24.
- `git/checkout` issued a `git config --get` per key -- twelve subprocesses,
  each costing more in startup than the read itself, on a probe measured at
  2.4s. One `git config --list --show-scope` answers all of them: 17 calls
  became 4, and 2.4s became 1.75s.
- `--show-scope` rather than `--show-origin`, which would name the path of the
  user's global config and therefore their username. `--null` would have been
  the robust separator, but `SubprocessRunner` strips NUL bytes deliberately --
  Windows tools emitting UTF-16LE leave NUL padding that would otherwise land
  in evidence excerpts -- so the line format is parsed instead, with
  continuation lines folded into the value they belong to.
- A scan is 5.6s again, against 4.7s before four probes were added this
  session.

### Added - which SDKs are installed, not just which one answers first

- `dotnet --version` and `java -version` report the one the shell resolves,
  which is the wrong question for two ecosystems that install several side by
  side and select between them per project.
- **`global.json` pins an exact .NET SDK.** With `rollForward` unset the pin is
  exact to the feature band, so a machine carrying 9.0.101 and a repository
  asking for 8.0.100 fails at `dotnet build` with "A compatible .NET SDK was
  not found" -- while `dotnet --version` prints 9.0.101 and every other check
  passes. The new `sdk/installed` probe compares the pin against
  `dotnet --list-sdks` and honours `rollForward`.
- The resolution model is deliberately partial and deliberately permissive
  where it is unsure. `rollForward` has eight documented policies; three decide
  the common cases and an unrecognised one is treated as "something newer will
  do", because a missing finding is a better failure than blocking a build that
  works.
- **`JAVA_HOME` and the `java` on PATH are separate settings.** Maven and
  Gradle use the first, a shell script calling `java` uses the second, and when
  they disagree the build compiles against one JDK and runs on another -- an
  `UnsupportedClassVersionError` that names neither. Compared by *version*
  rather than by path, because one being a symlink to the other is the normal
  case.
- Only versions are recorded. `dotnet --list-sdks` prints an install path
  beside each version, and on Windows that path is frequently under a user
  profile.

### Added - policy inheritance, and which layer said what

- A platform team publishes a paved road; a repository has its own needs. In
  one file, the repository either restates the org's rules -- and they drift
  the moment the org changes one -- or ignores them, and the paved road exists
  only in a wiki page.
- `extends = "../platform/paved-road.toml"` composes them, nearest layer
  winning. `devrepro check` reports which layer each requirement came from and
  what this repository overrode, because "node >=22" is not actionable and
  "node >=22, required by the org paved road" tells you whose rule you are
  failing and who to argue with.
- Ranges are never intersected. Merging `>=22` and `>=20` into something
  cleverer would produce a requirement neither file contains, which nobody
  could then explain to the developer it blocks. Required environment *names*
  are the one exception and accumulate, because a list of names is additive by
  nature and silently dropping the org's entry is not something a repository's
  file says it is doing.
- `extends` takes local paths only, resolved relative to the file rather than
  the working directory. A URL would make loading a policy a network operation,
  and a chain resolved against the cwd works from the repository root and
  breaks one directory down. Cycles and over-deep chains are errors, not hangs.
- Attribution is restricted to findings the policy actually caused.
  `python/version-mismatch` is the paved road's rule;
  `python/multiple-installations` is a fact about PATH that would be reported
  with no policy at all, and telling someone their platform team forbade having
  two Pythons is the kind of wrong that stops people reading a report.

### Fixed - `devrepro check` printed a Python dict to a human

- The human path handed `emit` the payload dictionary, which echoes a repr:
  the entire report, quoted, on one line. The identical fault was fixed in
  `generate` earlier for the identical reason -- someone who did not ask for
  `--json` wants to read the answer, not parse it. `check` now prints the
  policy layers, the findings that are actionable, and a verdict.

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