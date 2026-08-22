---
name: Probe / rule pack request
about: Request a new probe, toolchain detection, or rule pack
labels: enhancement, probes
---

**Toolchain / platform / stack**
e.g. "Bazel", "Nix", "CUDA 12 on WSL2".

**What should be detected**
Executables, versions, install sources, conflicts...

**What rules should compare against project requirements**
Manifests/lockfiles that declare this dependency.

**Evidence available on machines**
Commands whose output can serve as evidence (must be safe to run).

**Privacy notes**
Any risk of capturing secrets in evidence?