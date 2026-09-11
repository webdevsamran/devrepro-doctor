"""The initial route's transfer size, held to a budget rather than admired.

The dashboard plan set this gate: **the initial route under 100 KB gzip**. It
has been under it the whole time, which is exactly why it needed a script --
a number nobody measures is a claim, and this project's entire argument is that
claims decay silently.

What the budget covers is the part a first-time visitor waits for: the HTML, the
entry chunk, the stylesheet the document links, and any chunk Vite told the
browser to preload because the entry imports it eagerly. Lazy route chunks are
not in it, on purpose -- they are the reason the entry is small, and counting
them would make code splitting look like a cost.

That preload rule is the whole guard. Deleting one `lazy()` does not change the
entry chunk's own size much; it changes which chunks Vite emits a
`modulepreload` for, and those land in the initial payload. So the regression
this catches is the realistic one -- somebody imports a page directly to fix a
flicker, everything still works, and the first paint quietly gains 30 KB.

Level 9, because that is what a CDN serves and what every "gzipped size" badge
means. Brotli would be smaller; measuring the pessimistic transport is the safe
direction for a budget.

    python scripts/check_bundle_size.py
    python scripts/check_bundle_size.py --budget 120   # KB, for a deliberate raise
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"

#: The plan's figure, in bytes. Raising it is a decision, not a fix: the `npm
#: run build` output names the chunk that grew, and `--budget` exists so the
#: raise happens in a commit message somebody can read.
DEFAULT_BUDGET_KB = 100

#: Assets the document itself pulls before it can paint. `modulepreload` is the
#: one that matters -- Vite emits it for chunks the entry imports eagerly, so it
#: is how an un-lazied route shows up here at all.
_SCRIPT = re.compile(r"<script[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_LINK = re.compile(r"<link\b([^>]*)>", re.IGNORECASE)
_REL = re.compile(r"\brel=[\"']([^\"']+)[\"']", re.IGNORECASE)
_HREF = re.compile(r"\bhref=[\"']([^\"']+)[\"']", re.IGNORECASE)

#: `rel` values that block or preload the first paint. `prefetch` is absent
#: deliberately: it is explicitly the browser's idle-time work, so counting it
#: would punish a hint whose entire purpose is to cost nothing up front.
BLOCKING_REL = {"stylesheet", "modulepreload", "preload"}


def entry_assets(html: str) -> list[str]:
    """Every asset path the document references before it can render.

    Returned in document order and de-duplicated, because a path listed as both
    a preload and a stylesheet is still downloaded once.
    """
    found: list[str] = []
    for match in _SCRIPT.finditer(html):
        found.append(match.group(1))
    for match in _LINK.finditer(html):
        attributes = match.group(1)
        rel = _REL.search(attributes)
        href = _HREF.search(attributes)
        if not rel or not href:
            continue
        if rel.group(1).strip().lower() in BLOCKING_REL:
            found.append(href.group(1))

    seen: set[str] = set()
    ordered: list[str] = []
    for path in found:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def gzipped(data: bytes) -> int:
    """Bytes on the wire. `mtime=0` so the same input always measures the same."""
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def measure(dist: Path) -> tuple[list[tuple[str, int, int]], list[str]]:
    """Size every asset of the initial route. Returns (measured, problems)."""
    index = dist / "index.html"
    if not index.is_file():
        # Displayed relative to the repository when it is inside it, and whole
        # otherwise: `--dist` accepts any directory, and `relative_to` raises
        # rather than falling back for one that is elsewhere.
        try:
            shown = index.relative_to(ROOT).as_posix()
        except ValueError:
            shown = str(index)
        return [], [f"no {shown} -- run `npm run build` in web/ first"]

    html = index.read_text(encoding="utf-8")
    measured: list[tuple[str, int, int]] = [
        ("index.html", gzipped(html.encode("utf-8")), len(html.encode("utf-8")))
    ]
    problems: list[str] = []

    for reference in entry_assets(html):
        if reference.startswith(("http://", "https://", "//", "data:")):
            # Served by somebody else, so not this budget's to spend -- but a
            # build that reaches off-origin for a render-blocking asset is worth
            # saying out loud rather than passing silently.
            problems.append(f"index.html loads {reference} from another origin before first paint")
            continue
        asset = dist / reference.lstrip("/")
        if not asset.is_file():
            problems.append(f"index.html references {reference}, which the build did not emit")
            continue
        raw = asset.read_bytes()
        measured.append((reference.lstrip("/"), gzipped(raw), len(raw)))

    return measured, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_KB, help="KB gzip")
    parser.add_argument("--dist", type=Path, default=DIST)
    args = parser.parse_args(argv)

    measured, problems = measure(args.dist)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if not measured:
        return 1

    total = sum(size for _, size, _ in measured)
    budget = args.budget * 1024

    print(f"Initial route, gzip -9 ({len(measured)} files):")
    for name, size, raw in sorted(measured, key=lambda row: -row[1]):
        print(f"  {size / 1024:7.1f} KB gz   {raw / 1024:7.1f} KB raw   {name}")

    lazy = [
        path
        for path in sorted((args.dist / "assets").glob("*"))
        if path.is_file()
        and path.relative_to(args.dist).as_posix() not in {n for n, _, _ in measured}
    ]
    if lazy:
        deferred = sum(gzipped(path.read_bytes()) for path in lazy)
        print(f"  ({len(lazy)} further chunks, {deferred / 1024:.1f} KB gz, loaded per route)")

    print()
    if problems:
        print(f"FAIL  {len(problems)} problem(s) above", file=sys.stderr)
        return 1
    if total > budget:
        over = (total - budget) / 1024
        biggest = max(measured, key=lambda row: row[1])
        print(
            f"FAIL  {total / 1024:.1f} KB gz exceeds the {args.budget} KB "
            f"budget by {over:.1f} KB.\n"
            f"      Largest: {biggest[0]} at {biggest[1] / 1024:.1f} KB. If a route stopped being\n"
            f"      lazy, that is the fix; if the budget is genuinely wrong, raise it on purpose.",
            file=sys.stderr,
        )
        return 1

    headroom = (budget - total) / 1024
    print(f"OK    {total / 1024:.1f} KB gz of a {args.budget} KB budget ({headroom:.1f} KB spare).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
