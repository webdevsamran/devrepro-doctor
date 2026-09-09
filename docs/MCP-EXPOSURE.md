# Should devrepro-doctor expose an MCP server?

**Verdict: yes — the strongest case of the four sibling projects — for the
read-only commands only, and never for `fix`.**

This is an assessment, not a feature. Nothing here ships today.

## Why this project fits better than the others

*"Why won't this build on my machine?"* is a question agents get asked
constantly and answer badly, because the honest answer requires looking at the
machine. This tool looks at the machine and reports evidence.

Two properties it already has make the fit unusually good:

- **Read-only is the design, not a mode.** The scanning path does not modify
  anything; that is the project's stated promise, not a flag. An MCP tool built
  on it inherits that.
- **Output is already sanitized.** `devrepro/privacy/` redacts before anything
  is serialized, and `tests/test_privacy.py` holds it there. An MCP server
  hands its output to a model, which may forward it anywhere; a diagnostics
  tool without that gate would be a genuinely bad thing to expose.

The second point is the one worth dwelling on. Most machine-inspection tools
are unsafe to put behind an agent precisely because their output is full of
paths, usernames, tokens and environment variables. This one already treats
that as a correctness property.

## What would be exposed

| Tool | Answers |
|---|---|
| `doctor` | What is wrong with this machine, with evidence |
| `check` | Does this machine meet this project's declared requirements? |
| `info` | What is installed, and which versions? |
| `which` / `path` | Which binary actually resolves, and why that one? |
| `preflight` | Is this machine ready before a long build? |
| `diff` | Why does it work there and not here? |
| `snapshot` | Produce a sanitized manifest to hand to someone else |
| `rules` | What is checked, and what does each finding mean? |

Every one already supports `--json`, so the MCP result schema is the existing
`ScanReport`.

## What must never be exposed

**`fix`.** It executes remediations, gated on an explicit `--yes`. That gate
exists because the project's rule is that nothing above LOW risk is applied
without a human agreeing. An MCP tool call has no human in it: the model
decides to call it. Exposing `fix` would move the confirmation from a person to
a model, which is precisely the thing the gate was built to prevent.

`serve`, `server-backup` and `server-restore` are out for the same reason as
elsewhere: they start processes or move data.

## What has to be true first

1. **Exit codes do not survive the translation.** MCP returns structured
   content, not a process status, and this project's most important signal is
   `BLOCKED = 2` — which, as [EXIT-CODES.md](EXIT-CODES.md) records, means
   something entirely different in the sibling projects. The tool result would
   need to carry the verdict explicitly rather than relying on a convention
   that does not cross the boundary.
2. **Scan cost.** Largely addressed. A scan took 26 seconds on the
   development machine and now takes about 4. Sixteen of those seconds went on
   resolving PATH by testing every candidate filename against the filesystem --
   a 45-entry PATH times 14 PATHEXT variants, per tool -- and calling
   `Path.resolve()` before checking whether the path existed. Listing each
   directory once is 25 times faster and returns identical results.

   Four seconds is still slow for an interactive tool call, so a cached report
   with an explicit refresh remains the right design. It is no longer the
   blocker it was.
3. **Confinement.** `check --project` takes a path. Same concern as anywhere
   else: the server needs a configured root rather than trusting an argument.
