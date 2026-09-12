# DevRepro Doctor 🩺

**Find out why this repository will not build on *this* machine.**

Project-aware developer-environment diagnostics, reproducibility snapshots,
machine-to-machine diffs, AI-agent readiness checks and explainable safe
remediation — for Windows, Linux, macOS and WSL.

"Works on my machine" is not one bug, it is a *class* of bugs: a PATH order
nobody can see, a toolchain version that satisfies every declared range and
still breaks, a Docker CLI whose daemon is unreachable, a CI pin that no local
machine matches. DevRepro Doctor answers all of them in a single **read-only**
scan, explains each with evidence, and tells you what can be fixed **safely**.

It also answers a newer question: **can an AI coding agent work in this
repository at all?** `devrepro agent-check` resolves the commands your
`AGENTS.md`, `CLAUDE.md` and `.cursorrules` declare, reports the CI gates no
manifest mentions, and shows the blast radius of a session before one starts.

```bash
pip install git+https://github.com/webdevsamran/devrepro-doctor
devrepro doctor            # full read-only diagnostic scan
```

> **Not on PyPI yet.** `pip install devrepro-doctor` does not work: the name is
> unregistered, so publishing is pending a PyPI Trusted Publisher for this
> repository. Install from git until then; the command above is what CI uses.

<div class="grid cards" markdown>

- :material-stethoscope: **Diagnose**  
  Read-only probes across toolchains, PATH, containers, WSL, GPU/AI stacks,
  network/TLS and more — with evidence for every finding.

- :material-camera: **Snapshot & diff**  
  Privacy-sanitized environment manifests; semantic machine-to-machine diffs
  explain *why* it works there but fails here.

- :material-shield-check: **Privacy by construction**  
  Redaction before serialization; secret-scan blocks exports. No telemetry,
  ever.

- :material-wrench: **Explainable repair**  
  Risk-tiered remediation plans with preconditions, exact changes and
  rollback guidance. Dry-run by default.

- :material-robot: **Agent readiness**  
  Whether an automated contributor can work here: declared commands that do
  not resolve, CI gates no manifest mentions, and what a session could reach.

- :material-shield-lock: **Compliance evidence**  
  in-toto attestations, CRA / EO 14028 / SSDF control mapping and a CycloneDX
  BOM for the *toolchain* rather than the dependencies.

</div>

## Where to go next

- [Install](INSTALL.md) — every channel and its real status
- [Agent readiness](AGENT-READINESS.md) — the check no other tool performs
- [Troubleshooting](TROUBLESHOOTING.md) — start from the symptom
- [Rule catalogue](RULES.md) — every rule id, what it means and how to fix it
- [Architecture](architecture.md) — module map and data flow
- [GitHub Actions & SARIF](ci-github-actions.md) — gate CI and surface findings on PRs
- [Interoperability](interop.md) — how we relate to Nix, mise, Devbox, devenv…
- [Roadmap](roadmap.md) — where we're going

--8<-- "README.md"
