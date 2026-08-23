# Interoperability: DevRepro Doctor and your existing environment managers

DevRepro Doctor is a **diagnostic and reproducibility layer**, not another
package manager or environment manager. It sits *across* the tools you already
use and explains what they do — it never replaces them as the source of truth.

## The three modes

| Mode | What DevRepro does | What stays authoritative |
|---|---|---|
| **Diagnose** (default) | Read-only probes, findings, snapshots, diffs, drift timelines | Your environment manager |
| **Generate** (`devrepro generate`) | Drafts config files from *detected* requirements | You, after review |
| **Defer** | Detects an environment manager and reports its state instead of second-guessing it | The manager, explicitly |

## Per-tool guidance

### Nix / Nix Flakes
- **Diagnose:** daemon mode, flakes support, trusted-user issues, channel/registry state.
- **Defer:** when a `flake.lock` exists, DevRepro treats the flake as the source of
  truth for tool versions and only reports whether the machine can *use* it.
- Never generates Nix expressions.

### devenv
- **Diagnose:** version, shell integration, process/service config validation.
- **Defer:** `devenv.lock` pins win over inferred requirements.

### Devbox
- **Diagnose:** project detection, lock analysis, package-resolution symptoms.
- **Defer:** `devbox.lock` is authoritative.

### mise / asdf
- **Diagnose:** tool-version policy parsing, active-version mismatch checks.
- **Generate:** `.mise.toml` / `.tool-versions` drafts from explicit requirements
  (`devrepro generate mise|asdf`) — always preview-first, never overwrite without
  `--overwrite`.
- If both a lockfile and a tool-version file exist, the lockfile wins.

### direnv
- **Diagnose:** `.envrc` presence/authorization/shell-hook status. Executed shell
  code is treated cautiously; contents are never printed.

### Dev Containers / DevPod
- **Diagnose:** spec discovery, local machine compatibility, runtime detection.
- **Generate:** `devcontainer.json` drafts marked *generated, review required*.

### Language managers (pyenv, nvm/fnm/Volta, rbenv, conda, …)
- **Diagnose:** which manager owns each toolchain (provenance), version mismatches,
  PATH shadowing between managers.
- **Defer:** the active manager's version selection is reported, not overridden.

## Rules of engagement

1. **Read-only by default.** Nothing on your machine changes without explicit
   confirmation, and remediation plans show exact commands before anything runs.
2. **Lockfiles beat manifests beat inference.** When sources disagree, DevRepro
   says so instead of silently picking one.
3. **Generated files require review.** Every generator output is previewed with a
   diff; existing files are never overwritten without `--overwrite`.
4. **No forced migration.** DevRepro never suggests abandoning a working
   environment manager; it explains conflicts so you can decide.
5. **Privacy holds everywhere.** Snapshots shared with teams or fleets are
   sanitized; secrets are redacted at the source.