# Architecture

DevRepro Doctor is a Python library with a CLI front end and an optional
React dashboard. Everything is built around a small set of typed contracts.

## Data flow

```
                 ┌────────────┐
   machine ────▶ │ ProbeEngine│──▶ ProbeResult[] (findings + evidence)
                 └────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
  ToolchainIndex   PathAnalysis    ProjectRequirements
        │               │                │
        └───────┬───────┴────────┬───────┘
                ▼                ▼
         RuleEngine ◀──── Policy (.devrepro.toml)
                │
                ▼
          ScanReport ──▶ PrivacyGate (redact + secret-scan)
                │
   ┌────────────┼──────────────┬─────────────┐
   ▼            ▼              ▼             ▼
 terminal     JSON       Markdown/JUnit   HTML
                              │
                    Snapshot store (local history)
                              │
                       EnvironmentDiff (A vs B)
                              │
                     RemediationPlanner ──▶ plan (dry-run) ──▶ fix
```

## Module map

| Module | Responsibility |
|--------|----------------|
| `devrepro/core` | Typed models (`Probe`, `Finding`, `Evidence`, `ToolInstallation`, `ProjectRequirement`, `Snapshot`, `EnvironmentDiff`, `Remediation`, `Policy`, `ScanReport`), exit codes, errors. Zero side effects. |
| `devrepro/probes` | Probe interface + registry + engine. Each probe declares `id`, `version`, `platforms`, `dependencies`; returns findings/evidence. Engine isolates failures (timeout, exception ⇒ probe-level error finding, never a crashed scan). Probes receive a `CommandRunner` abstraction so tests inject recorded fixture output. |
| `devrepro/project` | Manifest/lockfile detectors. Infer only declared requirements; never invent exact versions. |
| `devrepro/rules` | Rule engine comparing machine state ↔ project requirements ↔ policy. States: PASS/INFO/WARN/ERROR/BLOCKED/UNKNOWN. Rule packs: python, node, dotnet, java, cpp, go, rust, containers, wsl, ai-gpu. |
| `devrepro/snapshots` | Schema-versioned, privacy-sanitized environment manifests; round-trip load/validate. |
| `devrepro/diff` | Snapshot A/B comparison with classification (same, version-drift, missing, extra, path-precedence, platform-expected, project-critical). |
| `devrepro/remediation` | Risk-tiered plans (SAFE/LOW/MEDIUM/HIGH) with preconditions, exact intended changes, rollback guidance. Dry-run by default; only SAFE/LOW automatable. |
| `devrepro/platforms` | Windows/Linux/macOS/WSL adapters (PATH semantics, profile locations, package managers). |
| `devrepro/plugins` | Entry-point loading for the five plugin groups; versioned plugin API. |
| `devrepro/privacy` | Redaction engine + secret scanner. Runs as a mandatory gate before any serialization. |
| `devrepro/reports` | Terminal (rich), JSON, Markdown, JUnit XML, standalone HTML renderers. |
| `devrepro/exporters` | Pluggable export layer behind report generation. |
| `devrepro/cli` | Typer app exposing all commands with `--json` and stable exit codes. The root app (`cli/app.py`) is a thin assembler; command implementations live in one domain module each under `cli/commands/` (diagnostics, project, environment, snapshots, remediation, reports, platform, service), registered onto a flat CLI surface. |
| `web/` | React 18 + TypeScript + Vite dashboard reading sanitized JSON exports or the localhost API. |

## Key design decisions

### 1. CommandRunner abstraction
Every probe that shells out does so through `core.runner.CommandRunner`.
Production uses a subprocess-backed runner; tests use fixture recorders.
This makes the entire suite deterministic and machine-independent.

### 2. Findings are evidence-first
A finding without evidence is rejected at model level. Evidence records the
command (or file) that produced it plus sanitized output excerpts.

### 3. Privacy gate is structural, not optional
`PrivacyGate.sanitize()` is invoked inside the serialization path itself —
there is no code path that writes machine data without passing through it.
The gate also scans outputs for probable secrets (token/key patterns) and
*blocks* export rather than leaking.

### 4. Stable exit codes
| Code | Meaning |
|------|---------|
| 0 | READY / success |
| 1 | READY_WITH_WARNINGS |
| 2 | BLOCKED |
| 3 | Internal error |

### 5. Schemas are versioned
`schemas/*.json` are generated from the Pydantic models. Snapshots embed
their schema version; loaders validate and refuse unknown future versions.

### 6. Plugin surface is versioned
Entry-point groups: `devrepro.probes`, `devrepro.rules`,
`devrepro.remediations`, `devrepro.project_detectors`, `devrepro.exporters`.
Plugin API version is reported by `devrepro plugins`; breaking changes bump
the documented version in docs/plugins.md.

## Non-goals

- Not a package installer or machine cleaner.
- No cloud sync, telemetry, or account system.
- Never disables TLS validation as a "fix".
- Never silently uninstalls tools, edits drivers/registry/system files, or
  deletes user data.