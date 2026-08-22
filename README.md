# DevRepro Doctor 🩺

**Cross-platform diagnostics, reproducibility auditing and safe repair planning for developer machines, project toolchains, SDKs, containers and build dependencies.**

Created, founded and led by **[@webdevsamran](https://github.com/webdevsamran)**.

---

## The problem

"Works on my machine" is not one bug — it's a *class* of bugs:

- Which developer tools/versions are installed — and which one actually runs?
- Are multiple conflicting versions of Python/Node/Java present?
- What does this project **actually require**, and what's missing or incompatible?
- Why does machine A build the project while machine B fails?
- Is Docker/WSL/container tooling healthy?
- Are PATH, SDK, compiler, proxy or certificate settings wrong?
- Is the GPU/AI development stack compatible with the project?

Most tools answer one of these. DevRepro Doctor answers all of them in a
single read-only scan — then tells you what can be fixed **safely**.

It is **not** another machine cleaner and **not** another environment
installer. It is:

> project-aware developer-environment diagnostics
> + reproducibility snapshots
> + machine-to-machine diffs
> + explainable safe remediation

## 60-second scan

```bash
pip install devrepro-doctor
devrepro doctor            # full read-only diagnostic scan
```

Real findings you'll see (examples from actual scans):

```
WARN  python/multiple-installations
      3 Python installations found; 'python' resolves to C:\...\python.exe (3.12.4)
      but pyenv shim takes precedence in your shell profile.
      Evidence: where python → 3 results; PATH precedence order captured.
      Safe remediation: review PATH ordering (dry-run plan available).

ERROR node/version-mismatch
      Project requires Node >=20 (engines field) but active Node is 18.19.0.
      Detected: v18.19.0 · Required: >=20.0.0
      Affected: package.json engines
      Remediation: install Node 20 via nvm/fnm/volta (plan: MEDIUM risk).

BLOCKED containers/docker-daemon-unreachable
      Docker CLI present (27.1.1) but daemon unreachable: connection refused.
      This blocks the project's docker-compose based test setup.
```

## Snapshots & diffs — the signature feature

```bash
devrepro snapshot -o my-machine.json     # privacy-sanitized manifest
# ... send to teammate / CI / support engineer ...
devrepro diff mine.json theirs.json      # why does it work there?
```

Diff classification: `same`, `version-drift`, `missing`, `extra`,
`path-precedence`, `platform-expected`, `project-critical`.
Output to terminal, JSON or standalone HTML.

## Privacy promise

- **Read-only by default.** Nothing on your system is modified without an
  explicit, confirmed remediation step.
- **No telemetry. No cloud upload. Ever.** `devrepro serve` binds to
  localhost only.
- **Redaction before serialization.** Usernames, home directories, tokens,
  API keys, SSH/cloud/registry credentials and private hosts are redacted;
  probable secrets block snapshot/report export entirely.
- Every report states exactly what was collected and its redaction status.
  See [docs/privacy.md](docs/privacy.md) for the complete inventory.

## Supported platforms & toolchains

| | Windows | Linux | macOS |
|---|---|---|---|
| Core diagnostics | ✅ | ✅ | ✅ |
| WSL doctor | ✅ | n/a | n/a |

Detected toolchains include: Git/GitHub CLI, Python (+pyenv/conda/uv),
Node (+nvm/fnm/volta), Java, .NET, Go, Rust, PHP, Ruby, C/C++ (MSVC/gcc/
clang), CMake/Ninja, Docker/Podman, kubectl, Terraform, cloud CLIs (AWS/
Azure/gcloud), WSL, Homebrew, apt/dnf/pacman, Chocolatey/winget/Scoop,
GPU/AI stacks (CUDA, ROCm, oneAPI, DirectML, Metal).

## Project policy example

Commit a `.devrepro.toml` so every contributor's machine is checked against
the same contract:

```toml
[supported_os]
windows = true
linux = true
macos = true

[required_runtimes]
python = ">=3.11,<3.14"
node = ">=20"

[required_tools]
git = "*"
docker = ">=24"

[known_bad_versions]
node = ["<=16"]          # EOL line

[containers]
require_devcontainer = true

[required_env_names]     # NAMES only — never values
names = ["DATABASE_URL", "API_TOKEN"]
```

```bash
devrepro check --policy .devrepro.toml
```

## UI

A production-quality React + TypeScript frontend ships under [`web/`](web/)
(Home, Machine Overview, Project Readiness, Toolchains, PATH Explorer,
Findings, Environment Diff, Snapshots, Rules, Remediation Plan, History,
Docs, Contributors, About). It reads sanitized JSON exports or the optional
localhost API served by `devrepro serve`.

![DevRepro Doctor dashboard](docs/images/dashboard.png)

## Commands

```
doctor   info   scan   project   path   which   snapshot   diff
preflight   plan   fix   rules   plugins   report   export
history   serve   self-test
```

All major commands support `--json` and stable exit codes (`0` ready,
`1` warnings, `2` blocked, `3` internal error) for use in onboarding
scripts and CI.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — module map and data flow
- [ROADMAP.md](ROADMAP.md) — where we're going
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to help
- [SECURITY.md](SECURITY.md) — reporting vulnerabilities
- [docs/plugins.md](docs/plugins.md) — plugin API reference

## Contributing

Issues labeled `good first issue` cover project detectors, platform probes,
toolchain detection, WSL, containers, GPU stacks, rule packs, safe
remediations and frontend visualizations. See CONTRIBUTING.md to get started.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Creator attribution:
[@webdevsamran](https://github.com/webdevsamran).