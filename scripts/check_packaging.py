"""Packaging manifests are either honest templates or real, never in between.

Every manifest in `packaging/` needs a released artefact's URL and checksum,
and there is no release yet. The failure mode this guards is specific: somebody
fills in one field to test something, commits it, and now the manifest looks
finished while pointing at a URL that does not resolve. It fails on the day
somebody first tries to install from it, which is the worst day for it to fail.

So a manifest is valid in exactly two states:

* every placeholder still present -- an obvious template, and
* every placeholder replaced, with a real https URL and a 64-character digest.

Halfway is the error.

    python scripts/check_packaging.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"

PLACEHOLDER = re.compile(r"PLACEHOLDER_[A-Z0-9_]+")
#: A published artefact URL. `https` and a host, because a `file://` or a bare
#: path in a published manifest installs from somewhere only the packager has.
REAL_URL = re.compile(r'"?https://[^\s"\'<>]+')
SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def main() -> int:
    if not PACKAGING.is_dir():
        print("no packaging/ directory", file=sys.stderr)
        return 1

    problems: list[str] = []
    checked = 0

    for path in sorted(PACKAGING.rglob("*")):
        if not path.is_file() or path.name == "README.md":
            continue
        checked += 1
        text = path.read_text(encoding="utf-8")
        placeholders = set(PLACEHOLDER.findall(text))
        name = path.relative_to(ROOT).as_posix()

        if not placeholders:
            # Claims to be filled in: hold it to that.
            if not REAL_URL.search(text):
                problems.append(f"{name}: no placeholders left, but no https URL either")
            if "SHA256" in text.upper() and not SHA256.search(text):
                problems.append(f"{name}: names a checksum field with no 64-hex digest")
            continue

        # Still a template. Every URL and digest field must still be one.
        for line in text.splitlines():
            lowered = line.lower()
            if ("url" in lowered or "sha256" in lowered or "hash" in lowered) and not (
                PLACEHOLDER.search(line)
                # The project's own homepage is not an artefact URL.
                or "github.com/webdevsamran/devrepro-doctor" in line
            ):
                problems.append(f"{name}: half-filled -- {line.strip()[:70]}")

    if problems:
        print("packaging manifests in an in-between state:", file=sys.stderr)
        for row in problems:
            print("  " + row, file=sys.stderr)
        print(
            "A manifest is either an obvious template or fully real. Halfway looks "
            "finished and fails on the first install.",
            file=sys.stderr,
        )
        return 1

    print(f"ok     {checked} packaging manifest(s), consistently templated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
