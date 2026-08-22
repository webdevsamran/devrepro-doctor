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

## Rules for plugin authors

- Probes must be read-only and time-bounded (`timeout_seconds`).
- Never raise out of `run()`; return a `ProbeResult` with `error` set.
- Redact personal paths before placing them in `Evidence.excerpt`.