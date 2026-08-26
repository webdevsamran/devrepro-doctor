# DevRepro Doctor 🩺

**Project-aware developer-environment diagnostics, reproducibility
snapshots, machine-to-machine diffs and explainable safe remediation.**

"Works on my machine" is not one bug — it's a *class* of bugs.
DevRepro Doctor answers all of them in a single read-only scan, then tells
you what can be fixed **safely**.

```bash
pip install devrepro-doctor
devrepro doctor            # full read-only diagnostic scan
```

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

</div>

## Where to go next

- [Architecture](architecture.md) — module map and data flow
- [GitHub Actions & SARIF](ci-github-actions.md) — gate CI and surface findings on PRs
- [Interoperability](interop.md) — how we relate to Nix, mise, Devbox, devenv…
- [Roadmap](roadmap.md) — where we're going

--8<-- "../README.md"
