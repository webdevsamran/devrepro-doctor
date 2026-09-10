# Agent readiness

> `devrepro agent-check [PATH]` — can an AI coding agent actually work in this
> repository, on this machine?

Coding agents read a manifest — `AGENTS.md`, `CLAUDE.md`, `.cursorrules` — and
follow the commands it declares. Nothing checks those commands against the
machine the agent runs on, so an agent finds out the expensive way: it runs a
command, it fails, and it guesses.

This command answers two questions, and it answers them without running
anything.

## 1. Do the declared commands resolve here?

Each command's program is resolved against PATH, with one distinction that
matters more than it sounds:

| Status | Meaning |
|---|---|
| `ok` | The program resolves. Multiple installations are noted; the first wins. |
| `not-on-path` | **Installed, but unreachable from this shell.** |
| `missing` | Not on PATH and not importable. The agent will fail here. |
| `shell-builtin` | `cd`, `echo` and friends — always available. |
| `path-absent` | A path-shaped program (`.venv/bin/activate`) that does not exist yet. Usually created by an earlier setup step. |

`not-on-path` is the one an agent cannot work out for itself. If `ruff` is not
on PATH but `python -m ruff` works, the fix is to activate a virtualenv or fix
PATH — not `pip install ruff`. Both failures look identical from inside the
agent, and one of the two "fixes" is a no-op that wastes a whole turn.

## 2. Does the manifest match what CI enforces?

A manifest that lists a subset of the real gates is worse than no manifest. The
agent runs everything it was told to, sees green, opens a pull request, and is
failed by checks nobody mentioned.

`agent-check` reads the `run:` steps of every workflow that gates a branch or
pull request — release workflows are skipped, since a tag-triggered `twine
upload` is not something an agent should have been told to run — and reports
commands CI enforces that no manifest declares.

Shell plumbing is filtered out. A `run: |` block is full of `grep`, `sed` and
variable assignments; none of that is a gate, and listing it would bury the
findings that matter.

### Starting from a manifest that already agrees

```bash
devrepro generate agents-md            # print the draft
devrepro generate agents-md --write    # write it (refuses to overwrite)
```

The drift above is structural rather than careless: someone writes the manifest
once, from memory, and then CI grows a gate. Nothing connects the two, so
nothing notices. Three of three repositories examined during this project's
development had it, all in the same direction.

`generate agents-md` drafts the file from the workflows instead, using the same
reader `agent-check` uses to find drift — so a freshly generated manifest
scores 3/3 on this factor by construction, and any later gap is CI having moved,
which is the case worth reporting. A test asserts that round trip against this
repository's own workflows, so the generator and the checker cannot quietly
disagree about what counts as a gate.

Installation steps are separated from checks. Calling `pip install -e ".[dev]"`
a gate is wrong in a way an agent acts on: it reads a successful install as a
passing check, and has no way to learn that the install is the prerequisite for
everything after it.

What a generator cannot know is left as a marked TODO rather than filled with
plausible prose — the conventions section especially, which is the part an agent
most needs and the part no directory listing can supply. A confident paragraph
of invented house style is worse than an empty heading, because nobody edits
what looks finished.

## 3. Are the declared commands still real?

`npm` resolving says nothing about whether `npm run build` names a script this
project still defines. Someone renames it, and `AGENTS.md` keeps telling every
agent the old name. The program exists, so a PATH check passes it, and the
agent finds out by running it and reading an error.

Targets are read from `package.json` scripts, Makefile targets, `justfile`
recipes and `[project.scripts]` — sources that genuinely declare named entry
points. Nothing is guessed: a freshness check that invents targets produces
false confidence, which is worse than saying nothing.

Targets resolve **in the directory the command runs in**. `cd web && npm run
build` is checked against `web/package.json`, because that is where a monorepo
keeps it. `cd` scopes to its own line: each line of a manifest is meant to be
runnable on its own from the root, which is also how CI runs them.

## 4. Do the manifests agree with each other?

A repository carrying both `AGENTS.md` and `CLAUDE.md` has two documents that
drift independently, and an agent reads whichever one its vendor looks for.
Commands present in one and absent from another are reported.

## 5. Agent readiness score

A single number with every point explained, the same contract the
reproducibility score holds. Weighted by what costs an agent time: a command
that cannot run at all outranks one that is merely undocumented, because the
first ends the turn and the second only misleads.

| Factor | Points |
|---|---|
| A manifest exists | 3 |
| It declares runnable commands | 2 |
| Those commands resolve on this machine | 4 |
| Their targets still exist in the project | 3 |
| It covers every gate CI enforces | 3 |
| Multiple manifests agree | 2 |

Grades: `ready` ≥ 90%, `workable` ≥ 60%, `rough` ≥ 30%, `unprepared` below.

It measures whether an agent has accurate instructions and a machine that can
follow them. It says nothing about whether the agent will do good work, and a
number claiming otherwise would be exactly the unfounded score this project's
own documentation warns against.

## 6. What could an agent reach from here?

Reported by default; `--no-blast-radius` turns it off.

2026 produced real, attributable damage from agents operating in environments
nobody had checked: a production database and its backups deleted in nine
seconds, a platform's data wiped, a thirteen-hour outage after an agent chose
to delete and recreate an environment. The post-mortems name the same causes
each time — production and development blurred together, permissions too broad,
approval arriving too late.

Those are environment-verification questions, and they can be answered before
the agent's first action:

| Exposure | Why it is on the list |
|---|---|
| **Uncommitted work** | A reset, checkout or clean destroys work that exists nowhere else. |
| **Unpushed commits** | They exist only on this machine; a force-push loses them. |
| **Inherited credentials** | Every subprocess an agent starts gets them — a build script, a test, a package postinstall. |
| **Production target** | `NODE_ENV=production`, `AWS_PROFILE=prod-admin`, a `prod-` kubectl context. A command that is harmless against dev is not harmless here. |
| **Ambient credentials** | A logged-in `aws`, `gcloud` or `kubectl` needs no token in the environment. Nothing in the shell reveals the authority is there. |
| **Elevated privileges** | Running as root means mistakes are unbounded by file permissions. |

Two properties make this safe to run and safe to publish:

- **Credentials are named, never read.** The report lists `GITHUB_TOKEN`; it
  never touches its value. The whole briefing can be pasted into an issue or
  handed to the agent itself.
- **Nothing is mutated, including the git index.** The checks use read-only
  plumbing, and a test asserts no mutating git subcommand is ever invoked —
  an assessment of what an agent might destroy must not destroy anything.

This is not a safety guarantee, and does not try to be. It is a briefing, so a
person decides what to do rather than finding out afterwards.

## Exit codes

Follows the [project contract](EXIT-CODES.md):

| Code | When |
|---|---|
| `0` READY | Every declared command resolves, and nothing drifts. |
| `1` READY_WITH_WARNINGS | A program is installed but off PATH, or the manifest omits a CI gate. Work can proceed, just not as documented. |
| `2` BLOCKED | A declared command names a program that is not there. |

**No manifest at all is `0`, not an error.** Most repositories do not have one,
and treating their absence as a failure would make this useless as a gate.

## Running the declared commands

Off by default, and deliberately so. A manifest is an untrusted file in someone
else's repository, and its setup step is typically an installer that writes to
disk and fetches from the network. Running it by default would make this
project's read-only promise conditional on what a third-party file happened to
say.

```bash
devrepro agent-check . --run          # opt-in, prints each command first
devrepro agent-check . --run --timeout 300
```

`--run` executes only commands that resolve and contain no shell
metacharacters. Anything needing a pipe, redirect, glob or substitution is
reported as `skipped-needs-shell` rather than handed to a shell — this project
does not pass an untrusted string to one.

## Machine-readable output

```bash
devrepro agent-check . --json
```

```json
{
  "root": ".",
  "manifests": [{"path": "AGENTS.md", "commands": 21}],
  "checks": [
    {"command": "ruff check devrepro tests scripts", "program": "ruff",
     "manifest": "AGENTS.md", "line": 29, "status": "not-on-path",
     "detail": "'ruff' is installed but not on PATH in this shell...",
     "resolved": null}
  ],
  "undeclared_ci_commands": ["npm audit --audit-level=high"],
  "verdict": "READY_WITH_WARNINGS"
}
```

## Why this exists

Every repository this was tested against had the same defect. Three projects,
three `AGENTS.md` files, each a strict subset of what its own CI enforced —
including this one, whose manifest omitted `scripts/` from both ruff
invocations and left out five gates entirely, while stating in its own text
that CI wins and the file is the bug when they disagree.

That is not a criticism of those repositories. It is what happens to any
document that describes a process nothing checks.

## Gating a session before it starts

The incidents that made this a category share a shape: broad permissions, an
unverified environment, and human approval arriving after the fact. The gate is
the cheap half of the fix -- ask, before the session starts, whether the
declared commands run here and whether this shell can reach production.

```bash
devrepro agent-check . --gate --threshold 60
```

Exits `0` when it is a reasonable place to start and `2` (BLOCKED) when it is
not. The exit code is the interface: a hook that only prints a warning is a
hook people stop reading.

Two grounds, and they answer different questions. **Readiness** asks whether
the agent can get work done. **Blast radius** asks what it reaches if it goes
wrong. A clean, well-documented checkout with production credentials in the
environment scores well on the first and is the *worst* case for the second,
because everything about it invites confidence.

The threshold matters as much as the check. A gate that fires on every
repository is one that gets removed in week one -- the same reasoning that
produced `guard --scope changed`.

### Installing it

`--hook` prints the configuration; it never writes it. A hook is code that runs
on every session, and installing one on somebody's behalf is a larger
permission than any diagnostic needs.

```bash
devrepro agent-check . --hook claude-code   # JSON for settings.json
devrepro agent-check . --hook shell         # a wrapper script for any runner
```

The Claude Code hook is a `SessionStart` hook rather than `PreToolUse`: the
point is to answer before any work happens, and a per-tool hook would re-scan
the machine on every single tool call.

## The badge

```bash
devrepro agent-check . --badge > agent-ready.json
```

A [shields.io endpoint](https://shields.io/badges/endpoint-badge) payload,
which shields fetches when the badge renders -- so the number comes from a scan
rather than from whenever somebody last committed an SVG.

Colour follows the same grades the command prints, and green starts at 90%.
Green at 60% would be a choice to make a mediocre score look fine.

## What an unprepared repository costs

`agent-check --json` carries a `token_cost` estimate: roughly how many turns and
tokens an agent burns on gaps this tool already found -- a command that does not
run, a manifest that is confidently wrong, a CI gate nobody declared.

It is **an estimate from a stated model, not a measurement**. Every per-signal
cost is a named constant in `devrepro/agents/tokencost.py`, the assumed tokens
per turn travels in the payload, and the figure is rounded to the nearest 5,000
because a number like 43,712 implies a measurement nobody made.

No price is attached. Model pricing changes monthly and varies by provider and
tier; a stale dollar figure in a diagnostic tool would be worse than none.

## Sandbox parity

`devrepro ci-diff` compares toolchains. What is left is the *shape* of the box
an agent gets, which produces no version mismatch and no missing binary:

- **Memory.** Exit code `137` is `128 + SIGKILL` from the OOM killer, which
  writes nothing to the build log. It reads as a compiler crash.
- **Cores.** Tools that detect parallelism through `nproc` read the host's
  count and spawn that many workers into a smaller box. The build does not
  fail; it thrashes.
- **Network.** A sandbox with no network is right for an agent and wrong for a
  first dependency install, and both declarations routinely live in the same
  repository.

Read from engine metadata and from compose/devcontainer declarations. Nothing
is started to find out.
