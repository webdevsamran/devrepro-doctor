# Plugin API (v1)

DevRepro Doctor is extensible via Python entry points. The plugin API is
versioned: `devrepro.plugins.loader.API_VERSION` is currently `"1"`. Breaking
changes bump the major version and are announced in `CHANGELOG.md`.

## Entry-point groups

| Group | Contract |
| --- | --- |
| `devrepro.probes` | A class with `id`, `version`, `platforms`, `run(ctx) -> ProbeResult` |
| `devrepro.rules` | A callable `(RuleContext) -> Iterable[Finding]` |
| `devrepro.remediations` | A callable `(list[Finding]) -> list[Remediation]` |
| `devrepro.project_detectors` | A callable `(Path) -> list[ProjectRequirement]` |
| `devrepro.exporters` | A class with `export(content: str, filename: str) -> str` |

## Example

```toml
# your plugin's pyproject.toml
[project.entry-points."devrepro.probes"]
myprobe = "myprobe.probe:MyProbe"
```

## Testing your plugin

1. Build a `RecordingRunner` (`devrepro.core.runner`) with canned
   `CommandResult`s — never depend on the developer's real machine.
2. Assert your probe returns `ProbeResult` with at least one `Finding`
   carrying `Evidence` (findings without evidence are invalid).
3. Run your plugin against `devrepro self-test` in CI to catch API drift.

## What a rule pack receives

`RuleContext` carries, and only carries:

| Field | What it is |
|---|---|
| `platform_info` | OS name, version, architecture, kernel, shell, WSL flag |
| `tools` | Every detected installation, with version, install source and whether it is the one that resolves |
| `requirements` | What the project's manifests declare |
| `policy` | The loaded `.devrepro.toml`, if any |
| `path_analysis` | PATH entries, duplicates, dead entries, shadowing |
| `containers`, `wsl`, `gpu` | Structured platform state |
| `active_manager` | The version manager active in this shell, if one is |
| `lockfiles` | Parsed lockfile facts |
| `extra` | Whatever the pipeline put there |

`ctx.active_tool(name)` is the shortcut for "the installation that actually
wins", which is almost always what a rule wants.

**There is deliberately no environment.** Probes read environment variables and
hand the engine *conclusions*; a pack able to read raw values would be a pack
able to put them in a report, which the privacy gate exists to prevent.

## Checking your pack

```bash
devrepro rules-test my_pack
```

Four checks, and each is something an author infers wrong from reading the
built-ins:

- **A finding with no evidence.** The model refuses to build one, so it arrives
  as an exception at scan time, in somebody else's CI.
- **A rule id under a built-in prefix.** `devrepro explain` then describes
  somebody else's rule, and the user cannot tell which pack produced the
  finding.
- **Side effects.** Checked *statically*: a pack that only writes under some
  condition passes a runtime check on every machine except the one it fails on.
- **An uncaught exception.** The engine turns it into a
  `rulepack/<name>/failed` finding, which is right for a user and means you
  never see your own crash.

`rules-test` imports and runs your module, which is executing code. It takes an
explicit import path rather than discovering installed packs, so it is always
clear whose code is about to run.

`templates/rule-pack/` is a working pack to copy — a directory rather than a
cookiecutter, because a template you can read start to finish teaches the
contract better than a generator that hides it.

## Rules for plugin authors

- Probes must be read-only and time-bounded (`timeout_seconds`).
- Never raise out of `run()`; return a `ProbeResult` with `error` set.
- Redact personal paths before placing them in `Evidence.excerpt`.