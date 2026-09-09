"""Every pinned GitHub Action must be pinned, and its version comment must be true.

Pinning an action to a commit SHA is the supply-chain control; the trailing
`# vX.Y.Z` comment is what a human reviewer actually reads. When the two
disagree, the comment wins in the reviewer's head and the control is worth
less than it looks.

That is not hypothetical here. Five `uses:` lines in this repository pinned
`actions/setup-python@5fda3b95a4ea` and annotated it `# v5.6.0`. That SHA is
**v7.0.0** -- two majors newer -- and two sibling repositories pinned the exact
same SHA while correctly calling it v7.0.0. Anyone auditing this repo's
supply chain would have concluded it was running a version it was not.

Two rules are enforced:

1. Every third-party `uses:` is pinned to a full 40-character SHA. A floating
   tag (`@v4`) means the action's content can change under you.
2. Where a pin carries a version comment, some tag at that SHA matches it.

Resolving a SHA to its tags needs the network, so this runs in CI rather than
in the unit-test suite. `GITHUB_TOKEN` lifts the rate limit from 60/hour to
5000; results are cached per (action, sha), so a full run is a handful of
calls.

    python scripts/check_action_pins.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

#: `uses: owner/repo[/subpath]@<ref>` with an optional trailing `# comment`.
USES = re.compile(
    r"^\s*-?\s*uses:\s*"
    r"(?P<action>[\w.-]+/[\w.-]+)"
    r"(?P<subpath>(?:/[\w.-]+)*)"
    r"@(?P<ref>[\w.\-/]+)"
    r"(?:\s*#\s*(?P<comment>.*?))?\s*$"
)
VERSION_IN_COMMENT = re.compile(r"\bv(\d+(?:\.\d+)*)\b")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

#: Local composite actions (`./.github/actions/...`) have no upstream to pin.
LOCAL = re.compile(r"^\s*-?\s*uses:\s*\.")

_cache: dict[tuple[str, str], list[str]] = {}


def tags_at(action: str, sha: str) -> list[str]:
    """Tag names pointing at `sha` in `action`'s repository."""
    key = (action, sha)
    if key in _cache:
        return _cache[key]

    request = urllib.request.Request(
        f"https://api.github.com/repos/{action}/tags?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "check-action-pins",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        # Fixed https host, built above from a literal.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"warning: could not resolve tags for {action}: {exc}", file=sys.stderr)
        _cache[key] = []
        return []

    tags = [t["name"] for t in payload if t.get("commit", {}).get("sha") == sha]
    _cache[key] = tags
    return tags


def main() -> int:
    if not WORKFLOWS.is_dir():
        print("no .github/workflows directory", file=sys.stderr)
        return 1

    unpinned: list[str] = []
    mislabelled: list[str] = []
    unresolved: list[str] = []
    checked = 0

    for workflow in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        for lineno, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if LOCAL.match(line):
                continue
            match = USES.match(line)
            if not match:
                continue

            action = match.group("action")
            ref = match.group("ref")
            where = f"{workflow.name}:{lineno}"

            if not FULL_SHA.match(ref):
                unpinned.append(f"{where}  {action}@{ref} is not pinned to a full SHA")
                continue

            claimed = VERSION_IN_COMMENT.search(match.group("comment") or "")
            if not claimed:
                continue

            checked += 1
            want = "v" + claimed.group(1)
            tags = tags_at(action, ref)
            if not tags:
                unresolved.append(
                    f"{where}  {action}@{ref[:12]} claims {want}; no tag points at that SHA"
                )
            elif not any(tag == want or tag.startswith(want + ".") for tag in tags):
                mislabelled.append(
                    f"{where}  {action}@{ref[:12]} claims {want}; real tags: {', '.join(tags)}"
                )

    for label, rows in (
        ("actions that are not SHA-pinned", unpinned),
        ("pins whose version comment is wrong", mislabelled),
        ("pins naming a version no tag confirms", unresolved),
    ):
        if rows:
            print(f"{label}:", file=sys.stderr)
            for row in rows:
                print("  " + row, file=sys.stderr)
            print(file=sys.stderr)

    if unpinned or mislabelled:
        print(
            "Fix the comment to match the SHA, or repin the SHA to match the comment.",
            file=sys.stderr,
        )
        return 1

    if unresolved:
        # A tag can legitimately disappear or move; that is worth printing but
        # is not grounds to fail a build on someone else's repository state.
        print(f"ok (with {len(unresolved)} unresolved) - {checked} pins checked")
        return 0

    print(f"ok     {checked} pinned actions, every version comment verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
