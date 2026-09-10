# Installing

> **Read this first.** `pip install devrepro-doctor` does not work yet, and
> neither does anything else on this page. The name is unclaimed on PyPI, so
> every install path here is a *template waiting on one form submission* — see
> [What is blocking all of this](#what-is-blocking-all-of-this).
>
> Documenting them anyway, with that said plainly at the top, beats the
> alternative this project shipped for months: a README opening with an install
> command that returns 404.

Until then, from a checkout:

```bash
git clone https://github.com/webdevsamran/devrepro-doctor
cd devrepro-doctor
pip install -e .
devrepro doctor
```

---

## What is blocking all of this

Publishing needs a **PyPI Trusted Publisher** registered against the account
that owns the name. It is a form on pypi.org that only the account owner can
submit, and it cannot be automated from a repository:

| Field | Value |
|---|---|
| Owner | `webdevsamran` |
| Repository | `devrepro-doctor` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Then set the repository variable `PUBLISH_ENABLED=true` and re-tag.

The release workflow is already guarded on that variable, deliberately: without
the guard a tagged release fails at the publish step even though everything
else succeeded, and a red release is indistinguishable from a broken one.

Everything downstream — Homebrew, Scoop, winget, `uvx` — needs a published
artefact with a stable URL and a checksum. None of them can be prepared any
further than the templates below.

---

## Once PyPI is live

### pip / pipx / uv

```bash
pip install devrepro-doctor          # into the current environment
pipx install devrepro-doctor         # isolated, on PATH
uv tool install devrepro-doctor      # same, faster
uvx devrepro-doctor doctor           # run once without installing
```

`uvx` is the one worth putting first in the README. This is a diagnostic tool:
the most common use is *once, on a machine that is misbehaving*, and asking
somebody to install something into a Python environment they are currently
debugging is asking them to change the thing they are measuring.

### Homebrew (macOS, Linux)

The formula is a template in `packaging/homebrew/devrepro-doctor.rb`, with
`PLACEHOLDER` where the release URL and SHA-256 go. The release workflow can
fill it once there is a release to fill it from.

```bash
brew install webdevsamran/tap/devrepro-doctor
```

A tap rather than homebrew-core: core requires a notability threshold this
project does not meet, and submitting anyway wastes a maintainer's time.

### Scoop (Windows)

`packaging/scoop/devrepro-doctor.json`, same placeholders.

```powershell
scoop bucket add webdevsamran https://github.com/webdevsamran/scoop-bucket
scoop install devrepro-doctor
```

### winget (Windows)

`packaging/winget/manifest.yaml`. winget's community repository requires a
signed installer and a manifest review, which is a real submission process
rather than a file to publish — so this one is a template *and* a to-do.

---

## What is deliberately not offered

**`curl … | sh`.** This project spends its time telling people that piping a
URL into a shell is a decision they should make deliberately — the reproduction
recipes print such commands commented out for exactly that reason. Offering one
as the headline install would be advice this project does not follow.

If you want the equivalent, `uvx devrepro-doctor doctor` runs it once without
installing anything, and you can read what it is before you run it.

**An npm wrapper.** The name is unclaimed on npm too, and a wrapper package
that shells out to a Python tool is a second thing to keep in version, a second
place for the version to be wrong, and a second supply-chain surface. If enough
Node-only teams ask, that changes; nobody has yet.
