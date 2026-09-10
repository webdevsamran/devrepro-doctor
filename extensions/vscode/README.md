# DevRepro Doctor for VS Code

Runs `devrepro` and puts the result where you already are.

```bash
code --extensionDevelopmentPath=extensions/vscode
```

No `npm install` first — there are no dependencies and no build step.

## Commands

| Command | What it does |
|---|---|
| `DevRepro: Scan this machine` | `devrepro doctor --json`, rendered as diagnostics and an output channel |
| `DevRepro: Explain a rule id` | The long form of any finding, in a Markdown preview |
| `DevRepro: Check agent readiness` | `devrepro agent-check`, with the per-factor breakdown |

## Three decisions worth knowing

**It does not scan on startup.** A scan takes seconds and spawns processes, and
an extension that does that while you are opening a file is one you disable in
week two. `devrepro.scanOnStartup` exists and defaults to off.

**Only file-anchored findings become squiggles.** Most of what this tool reports
is about the *machine* — a stopped Docker daemon is not a property of any line
of code, and anchoring it to line 1 of something is how diagnostics become noise
people learn to ignore. Machine findings go to the output channel and the status
bar, with a line saying how many there were and why they are not in the editor.

**It shells out and parses JSON.** No language server, no daemon. `devrepro`
already publishes a stable `--json` contract — run `devrepro contract` to see
it — so this extension has nothing of its own to keep in step.

A non-zero exit is part of that contract, not a failure: `1` means warnings and
`2` means blocked. An extension that treated those as errors would show a
notification every time it worked correctly.
