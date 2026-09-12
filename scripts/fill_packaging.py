"""Turn the packaging templates into real manifests, from real artefacts.

`packaging/` holds templates because there is no release yet, and
`check_packaging.py` keeps them either wholly templated or wholly real --
halfway is the state that looks finished and fails on the day somebody installs
from it. What was missing is the step between: something that does the filling
from artefacts that exist, rather than leaving a person to paste four URLs and
four digests by hand at the exact moment they are least likely to check.

Every value comes from a file on disk. The digests are computed, never passed
in, so a manifest cannot claim a checksum that does not belong to the artefact
it points at.

    python -m build                       # produces dist/
    python scripts/fill_packaging.py --version 0.2.0 --dist dist --out build/packaging

The output goes to a directory, not over `packaging/`. Those templates are what
this repository publishes; the filled manifests belong in the tap and bucket
repositories that serve them, and committing a real URL here would make the
checked-in files assert a release that may not exist.

**winget is deliberately not filled.** Its manifest wants a signed Nullsoft
installer, and this project builds a wheel and an sdist. Generating one anyway
would mean inventing an `InstallerUrl`, which is the failure this whole
arrangement exists to prevent. The template says the same thing in its own
comment, and this script exits telling you rather than quietly writing three
files when you asked for four.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"

DEFAULT_BASE_URL = "https://github.com/webdevsamran/devrepro-doctor/releases/download"

PLACEHOLDER = re.compile(r"PLACEHOLDER_[A-Z0-9_]+")

#: Manifests this script can fill completely. `winget/manifest.yaml` is absent
#: on purpose -- see the module docstring.
FILLABLE = ("homebrew/devrepro-doctor.rb", "scoop/devrepro-doctor.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_artifact(dist: Path, suffix: str, version: str) -> Path:
    """The one artefact of this kind for this version, or a clear error.

    Matching on the version as well as the suffix because a `dist/` directory
    accumulates: building 0.2.0 into a directory that still holds 0.1.9 and
    picking the first match would publish a manifest pointing at the wrong
    release, with a checksum that verifies.
    """
    matches = sorted(p for p in dist.glob(f"*{suffix}") if version in p.name)
    if not matches:
        raise SystemExit(
            f"no {suffix} for version {version} in {dist}. "
            "Run `python -m build` first, and check the version matches."
        )
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise SystemExit(f"more than one {suffix} for {version} in {dist}: {names}")
    return matches[0]


def substitutions(version: str, sdist: Path, wheel: Path, base_url: str) -> dict[str, str]:
    tag_url = f"{base_url.rstrip('/')}/v{version}"
    return {
        "PLACEHOLDER_VERSION": version,
        "PLACEHOLDER_SDIST_URL": f"{tag_url}/{sdist.name}",
        "PLACEHOLDER_SDIST_SHA256": sha256(sdist),
        "PLACEHOLDER_WHEEL_URL": f"{tag_url}/{wheel.name}",
        "PLACEHOLDER_WHEEL_SHA256": sha256(wheel),
        "PLACEHOLDER_WHEEL_NAME": wheel.name,
        # Scoop's autoupdate substitutes `$version` itself, so this one stays a
        # pattern rather than becoming a fixed URL.
        "PLACEHOLDER_WHEEL_URL_PATTERN": (
            f"{base_url.rstrip('/')}/v$version/{wheel.name.replace(version, '$version')}"
        ),
    }


def fill(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token not in values:
            raise SystemExit(
                f"{token} has no value. Either this script is out of step with the "
                f"template, or the template gained a field nothing produces."
            )
        return values[token]

    return PLACEHOLDER.sub(replace, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version, e.g. 0.2.0")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist", help="Directory of artefacts")
    parser.add_argument("--out", type=Path, required=True, help="Where to write filled manifests")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args(argv)

    if not args.dist.is_dir():
        print(f"no such directory: {args.dist}; run `python -m build` first", file=sys.stderr)
        return 1

    sdist = find_artifact(args.dist, ".tar.gz", args.version)
    wheel = find_artifact(args.dist, ".whl", args.version)
    values = substitutions(args.version, sdist, wheel, args.base_url)

    args.out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for relative in FILLABLE:
        source = PACKAGING / relative
        if not source.is_file():
            print(f"missing template: {source}", file=sys.stderr)
            return 1
        filled = fill(source.read_text(encoding="utf-8"), values)
        leftover = sorted(set(PLACEHOLDER.findall(filled)))
        if leftover:
            print(f"{relative} still contains {leftover}", file=sys.stderr)
            return 1
        target = args.out / Path(relative).name
        target.write_text(filled, encoding="utf-8")
        written.append(target)

    print(f"sdist  {sdist.name}  {values['PLACEHOLDER_SDIST_SHA256']}")
    print(f"wheel  {wheel.name}  {values['PLACEHOLDER_WHEEL_SHA256']}")
    for path in written:
        print(f"wrote  {path}")
    print(
        "\nwinget/manifest.yaml was not filled: it wants a signed Nullsoft installer, "
        "and this project builds a wheel and an sdist. Inventing an InstallerUrl is "
        "the failure `check_packaging.py` exists to prevent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
