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
  containers, wsl, ai-gpu)
- ✅ Reproducibility completeness score (explained per point)
- ✅ Snapshots + environment diff (7 classifications, 3 output formats)
- ✅ Safe remediation planner (risk tiers, dry-run default, rollback)
- ✅ Shell/tool-manager analysis with redaction
- ✅ WSL diagnostics, container doctor, port scanner, network/TLS doctor,
  registry checks, GPU/AI stack detection
- ✅ Build preflight with stable exit codes
- ✅ `.devrepro.toml` policy + env-var-name audit
- ✅ Plugin entry points (5 groups, versioned API)
- ✅ Full CLI (18 commands, --json everywhere)
- ✅ Local sanitized history + drift view
- ✅ Reports: terminal/JSON/Markdown/JUnit/HTML
- ✅ React+TS+Vite frontend (14 pages)
- ✅ Localhost-only server
- ✅ Privacy engine + synthetic-secret tests
- ✅ Fixture-driven tests + property-based tests
- ✅ CI matrix (Windows/Linux/macOS), CodeQL, Dependabot, SBOM

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