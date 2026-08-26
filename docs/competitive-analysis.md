# Competitive Analysis

> Structured data: [`data/competitive-capabilities.json`](https://github.com/webdevsamran/devrepro-doctor/blob/main/data/competitive-capabilities.json).
> Gaps this project commits to closing: [PRODUCT_GAPS.md](product-gaps.md).

**Verification method.** Claims were compiled from each competitor's official
repository, documentation site and release notes (canonical links in the JSON).
Absence claims are only made where documented or structurally implied by the
project's stated scope; otherwise fields are `null`. Re-verify before quoting
externally. No proprietary code, assets or branding is copied from any project.

## Positioning statement

DevRepro Doctor is **not** an environment manager. It is the *project-aware
diagnostic and reproducibility layer* that sits **across** Nix, devenv, Devbox,
mise, asdf, direnv, Dev Containers and plain system toolchains:

```
Project Detectors + Machine Probes -> Normalized State -> Requirements/Policy
  -> Rule Engine -> Findings -> Snapshot/Diff -> Remediation Plan -> Report/UI
                                    (+ optional Agent -> Self-hosted Fleet Service)
```

## Landscape summary

| Project | License | What it does | What it does NOT do |
|---|---|---|---|
| Nix / Flakes | LGPL-2.1+ | Declarative, reproducible package/env management with rollbacks | Diagnose machines that don't use Nix; explain PATH/shadowing; sanitized sharing |
| devenv | Apache-2.0 | Friendlier Nix dev shells + services | Run without Nix; host-machine diagnosis |
| Devbox | Apache-2.0 | Nix-backed envs via simple JSON | Host-machine readiness; drift over time |
| mise | MIT | Fast polyglot tool version manager + tasks + env | Machine-wide view across other managers; snapshots/diffs/fleet |
| asdf | MIT | Plugin-based tool versioning (shims) | Windows-native support; cross-manager conflict explanation |
| direnv | MIT | Per-directory env vars via `.envrc` | Toolchain management; safe inspection of shell code |
| Dev Containers | CC/MIT | Standard containerized dev environment format | Validate that a given HOST can run the container stack |
| DevPod | Apache-2.0 | Disposable workspaces on many providers | Read-only host diagnostics; policy/baseline governance |
| Coder / cloud IDE platforms | AGPL+enterprise | Centralized remote workspace fleets | Diagnose developer laptops; zero-infra local-first value |
| `* doctor` utilities | various | Ecosystem-scoped health checks | Cross-ecosystem scope, stable machine-readable output, snapshots/diffs/policy |

## Strategic conclusions

1. **No one owns "why does this repo fail on THIS machine".** Environment
   managers assume their own layer works. Doctor-style tools are single-
   ecosystem. The diagnostic layer above all managers is unoccupied.
2. **Interoperability beats replacement.** Every serious competitor is
   open source with committed users. We must read their config formats,
   diagnose their installations, and generate reviewable drafts for them —
   never fight them.
3. **Windows/WSL depth is a moat.** Most competitors treat Windows as an
   afterthought (WSL-only at best). First-class Windows, WSL, Linux and macOS
   probe paths differentiate us immediately.
4. **Privacy-sanitized sharing is underserved.** Competitors share lockfiles;
   nobody shares *sanitized machine state* designed for human-to-human
   debugging ("works on my machine" triage).
5. **Fleet/governance is where commercial value lives** (Coder proves the
   pattern), but it must not cripple single-user local value. Community stays
   local-first; team/enterprise adds scale, collaboration, policy and audit.
6. **Scores must stay honest.** We report explainable reproducibility maturity
   factors; we never claim a score guarantees identical builds.

## Capability matrix (condensed)

Full per-competitor detail with evidence links lives in
[`data/competitive-capabilities.json`](https://github.com/webdevsamran/devrepro-doctor/blob/main/data/competitive-capabilities.json).

| Capability | Nix | devenv | Devbox | mise | asdf | direnv | DevContainers | DevPod | Coder | Doctors | **DevRepro** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Read-only machine diagnosis | – | – | – | – | – | – | partial | – | – | partial | ✅ |
| Cross-manager conflict detection | – | – | – | – | – | – | – | – | – | – | ✅ |
| PATH precedence explanation | – | – | – | – | – | – | – | – | – | – | ✅ |
| Sanitized snapshot export | – | – | – | – | – | – | – | – | – | – | ✅ |
| Semantic machine↔machine diff | – | – | – | – | – | – | – | – | – | – | ✅ |
| Drift timeline / root-cause hints | – | – | – | – | – | – | – | – | – | – | ✅ |
| Safe remediation planning | – | – | – | – | – | – | – | – | – | partial | ✅ |
| Env/config generation (reviewable) | – | – | – | – | – | – | – | – | – | – | ✅ |
| Fleet baselines & policy-as-code | – | – | – | – | – | – | – | – | ✅ | – | ✅ (self-hosted) |
| Reproducible builds | ✅ | ✅ | ✅ | – | – | – | partial | – | – | – | – (by design) |

Legend: ✅ first-class · partial · – absent/not applicable.

## Features deliberately NOT copied

- Package/build management (Nix store model, mise/asdf shims) — out of scope.
- Cloud workspace provisioning (Coder/DevPod) — different problem.
- Auto-executing generated environment files without review.
- Telemetry of any kind.