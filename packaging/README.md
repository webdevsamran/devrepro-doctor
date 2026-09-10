# Packaging manifests

Templates. Every one carries `PLACEHOLDER` where a released artefact's URL and
SHA-256 belong, because there is no release yet -- see
[docs/INSTALL.md](../docs/INSTALL.md) for what is blocking that.

`PLACEHOLDER` rather than a plausible-looking URL on purpose. A manifest with an
invented URL looks finished, gets committed, and fails on the day somebody first
tries to install from it; one that says PLACEHOLDER cannot be mistaken for done.

`scripts/check_packaging.py` holds that line: it fails if a placeholder is
replaced by anything that is not a real release URL and a 64-character digest.
