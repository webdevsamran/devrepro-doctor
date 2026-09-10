# Roadmap

Status legend: ✅ shipped · 🚧 in progress · 📋 planned

## 0.1 — Foundation (current)

- ✅ Typed core models + JSON schemas
- ✅ Probe engine with failure isolation
- ✅ OS/CPU/RAM/disk/shell/PATH/env probes
- ✅ Network/TLS/certificate basics
- ✅ Git, package managers, language runtimes, compilers, SDKs probes
- ✅ Containers, virtualization/WSL, GPU/AI, ports/services probes
- ✅ Toolchain detection with duplicates/install sources
- ✅ PATH analyzer (duplicates, dead paths, shadowing, Store aliases,
  virtualenv interference, profile inconsistencies)
- ✅ Project requirement detectors (Python/Node/.NET/Go/Rust/PHP/Ruby/
  Java/C-C++/containers/devcontainers/tool managers/CI)
- ✅ Rule engine + packs (python, node, dotnet, java, cpp, go, rust,
  containers, wsl, ai-gpu, lockfiles)
- ✅ Reproducibility completeness score (explained per point)
- ✅ Snapshots + environment diff (7 classifications, 3 output formats)
- ✅ Safe remediation planner (risk tiers, dry-run default, rollback)
- ✅ Shell/tool-manager analysis with redaction
- ✅ WSL diagnostics, container doctor, port scanner, network/TLS doctor,
  registry checks, GPU/AI stack detection
- ✅ Build preflight with stable exit codes
- ✅ `.devrepro.toml` policy + env-var-name audit
- ✅ Plugin entry points (5 groups, versioned API)
- ✅ Full CLI (55 commands, `--json` everywhere)
- ✅ Local sanitized history + drift view
- ✅ Reports: terminal/JSON/Markdown/JUnit/HTML
- ✅ React+TS+Vite frontend (35 pages), grouped sidebar, command palette, code-split routes
- ✅ Localhost-only server
- ✅ Privacy engine + synthetic-secret tests
- ✅ Fixture-driven tests + property-based tests
- ✅ CI matrix (Windows/Linux/macOS), CodeQL, Dependabot, SBOM

## What shipped since 0.2 was written

The 0.2 list below was written before the work in `CHANGELOG.md`. Rather than
silently editing it into agreement -- a roadmap that always claims to be on
plan is a roadmap nobody reads -- here is what actually landed, and the list
below stays as it was.

- ✅ Agent readiness end to end: `agent-check` with blast radius, a readiness
  score, a session `--gate`, hooks, a shields badge, and a token-cost estimate
- ✅ MCP server (`devrepro mcp`), read-only, with the three prerequisites
  `docs/MCP-EXPOSURE.md` set before it could ship
- ✅ Reproduction: `devrepro reproduce` into five formats plus three sandbox
  adapters, `devrepro bisect` with delta-debugging minimisation, and
  `repro-rate` recording how often any of it works
- ✅ Compliance evidence: in-toto attestations, CRA/SSDF/SLSA control mapping,
  a toolchain licence inventory, an offline advisory set, and hash-chained
  snapshot history
- ✅ Twelve rule packs, including framework introspection (Next.js, Django,
  Spring Boot) and build-cache health
- ✅ Fleet governance: onboarding analytics, policy simulation, team-scoped
  baselines, MDM scripts, chat payloads
- ✅ Editor and browser surfaces: VS Code, JetBrains External Tools, a browser
  badge that makes no network requests, and i18n scaffolding
- ✅ A published consumer contract (`devrepro contract`), GitHub annotations,
  toolchain-pin bot coverage, and a contract watcher

**And two corrections worth more than any of it.** A default scan was opening
TLS connections to three third-party hosts, against this project's headline
invariant -- found by `devrepro bench`, not by reading. And `--fg-subtle` failed
WCAG AA on the surfaces it was actually used on, in both themes, after a
previous fix had measured it against the page background only.

## 0.2 — Depth

- 📋 More rule packs: bazel, nix, android, ios, embedded toolchains
- 📋 Deeper container analysis: image layer drift, compose health
- 📋 Diff explanations via structured causal chains ("why builds fail here")
- 📋 Team mode: shareable anonymized snapshots with signed manifests
- 📋 VS Code extension surfacing findings inline

## 0.3 — Ecosystem

- 📋 Plugin marketplace documentation + template repo
- 📋 CI integrations (GitHub Actions summary output, GitLab CI)
- 📋 `devrepro guard` pre-commit hook blocking commits on new blockers
- 📋 Package manager distribution once real packages exist
  (PyPI first; Homebrew/winget/Scoop only after they exist)

## Always

- Keep default behavior read-only and privacy-safe.
- Never rewrite published git history; reconcile work into `main`.