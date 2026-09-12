# Packaging manifests

Templates. Every one carries `PLACEHOLDER` where a released artefact's URL and
SHA-256 belong, because there is no release yet -- see
[docs/INSTALL.md](../docs/INSTALL.md) for what is blocking that.

`PLACEHOLDER` rather than a plausible-looking URL on purpose. A manifest with an
invented URL looks finished, gets committed, and fails on the day somebody first
tries to install from it; one that says PLACEHOLDER cannot be mistaken for done.

`scripts/check_packaging.py` holds that line: it fails if a placeholder is
replaced by anything that is not a real release URL and a 64-character digest.

## Filling them, when there is a release

    python -m build
    python scripts/fill_packaging.py --version 0.2.0 --dist dist --out build/packaging

Every digest is computed from the artefact on disk. A checksum passed in as an
argument is a checksum nobody verified, and the whole reason these files are
templates is that a manifest which *looks* finished is worse than one that
obviously is not.

The output goes to a directory rather than over these files. What lives here is
the template this repository publishes; the filled manifests belong in the tap
and bucket repositories that serve them, and a real URL committed here would
make the checked-in files assert a release that may not exist yet.

**winget is not filled by that script.** Its manifest wants a signed Nullsoft
installer and this project builds a wheel and an sdist, so generating one would
mean inventing an `InstallerUrl`. The script says so and exits rather than
quietly writing two files when you asked for three.
