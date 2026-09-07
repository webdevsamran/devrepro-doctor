# Release process

Referenced from `CONTRIBUTING.md`. Everything here is what
`.github/workflows/release.yml` actually does — if the two disagree, the
workflow is authoritative and this file is the bug.

## What triggers a release

A pushed tag matching `v*`. Nothing else. There is no manual publish step and
no way to release from a branch.

```bash
# 1. Version must agree in all four places before tagging
grep '^version' pyproject.toml          # source of truth
grep 'version' CITATION.cff
head -20 CHANGELOG.md                   # promote [Unreleased] to the new version
devrepro --version

# 2. Tag and push
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

## What the workflow produces

| Job | Output |
| --- | --- |
| `build` | sdist + wheel via `python -m build`, checked with `twine check`, uploaded as the `dist` artifact |
| `sbom` | SPDX JSON SBOM via `anchore/sbom-action`, published as `devrepro-doctor-sbom.spdx.json` |
| `publish` | Uploads to PyPI through Trusted Publishing (OIDC, `id-token: write`, environment `pypi`) |

Provenance comes from `pypa/gh-action-pypi-publish`, which attests the
artifacts it uploads. There is **no separate checksum step** — if you need
`.sha256` files alongside the release assets, that is not currently produced.

## Prerequisite: Trusted Publishing

The `publish` job authenticates with PyPI via OIDC rather than a stored token.
That requires a Trusted Publisher registered on pypi.org for this project
(owner `webdevsamran`, repository `devrepro-doctor`, workflow `release.yml`,
environment `pypi`). This is configured in the PyPI web interface and cannot
be set from this repository. **Until it exists, the publish job fails at the
upload step** while build and SBOM still succeed.

## After tagging

Check the run, then confirm the package is installable by its real name from
a clean environment — a green workflow is not by itself evidence that the
release is usable:

```bash
python -m venv /tmp/verify && /tmp/verify/bin/pip install devrepro-doctor
/tmp/verify/bin/devrepro --version
```
