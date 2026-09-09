"""Render the landscape table in docs/competitive-analysis.md from committed data.

The table states its own method -- "fetched via the GitHub API" -- but was
typed by hand, so it could disagree with the data it cited. In api-verity-lab
it did, in the worst cell available: a competitor was listed as "repo gone
(404)" when the repository is archived and public with 1,534 stars. The 404
came from the fetcher asking for the wrong org name, and the null it recorded
was transcribed into the published table as a finding.

So the table is generated, not written. `--check` fails when the committed
markdown differs from what the data renders, which is what stops it drifting
again.

    python scripts/generate_landscape.py            # rewrite the table
    python scripts/generate_landscape.py --check    # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "competitive-analysis.md"
DATA = ROOT / "data" / "competitor-meta.json"

OPEN = "<!-- landscape:generated -->"
CLOSE = "<!-- /landscape:generated -->"

NOTE = (
    "Rows are generated from `data/competitor-meta.json` by "
    "`scripts/fetch_competitor_meta.py`, which reads the GitHub API. "
    "Star counts and dates are facts about the repositories on the fetch date, "
    "not judgements. Nothing here claims a project lacks a feature: where a "
    "capability was not verified it is absent from this table rather than "
    "asserted as missing."
)


def render() -> str:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    date = data["fetched_utc"][:10]

    rows = [
        "| Project | License | Stars | Last push | Latest release | Status |",
        "|---|---|---|---|---|---|",
    ]
    for entry in sorted(data["repos"].values(), key=lambda r: r.get("stars") or 0, reverse=True):
        release = entry.get("latest_release") or {}
        tag = release.get("tag")
        published = (release.get("published_at") or "")[:10]
        release_cell = f"{tag} ({published})" if tag else "—"
        stars = f"{entry['stars']:,}" if entry.get("stars") is not None else "—"
        name = entry["repo"]
        rows.append(
            f"| [{name}](https://github.com/{name}) | {entry.get('license_spdx') or '—'} "
            f"| {stars} | {(entry.get('pushed_at') or '')[:10]} | {release_cell} "
            f"| {'**archived**' if entry.get('archived') else 'active'} |"
        )

    return (
        f"{OPEN}\n## Landscape snapshot (fetched {date})\n\n"
        + "\n".join(rows)
        + f"\n\n{NOTE}\n{CLOSE}"
    )


def splice(text: str) -> str:
    if OPEN not in text or CLOSE not in text:
        raise SystemExit(f"{DOC.name} is missing the {OPEN} / {CLOSE} markers.")
    head, rest = text.split(OPEN, 1)
    _, tail = rest.split(CLOSE, 1)
    return head + render() + tail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = DOC.read_text(encoding="utf-8")
    updated = splice(current)

    if args.check:
        if current == updated:
            data = json.loads(DATA.read_text(encoding="utf-8"))
            print(
                f"ok     landscape table matches competitor-meta.json "
                f"({len(data['repos'])} projects, fetched {data['fetched_utc'][:10]})"
            )
            return 0
        print(
            "The landscape table no longer matches competitor-meta.json.\n"
            "Run: python scripts/generate_landscape.py",
            file=sys.stderr,
        )
        import difflib

        for line in list(
            difflib.unified_diff(
                current.splitlines(),
                updated.splitlines(),
                fromfile="committed",
                tofile="rendered",
                lineterm="",
            )
        )[:40]:
            print(line, file=sys.stderr)
        return 1

    DOC.write_text(updated, encoding="utf-8", newline="\n")
    print("wrote  docs/competitive-analysis.md (table rendered from committed data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
