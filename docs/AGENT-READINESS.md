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
