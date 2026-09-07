"""Claims in the docs that a machine can check.

ROADMAP said 18 CLI commands (there are 37) and 14 frontend pages (there are
32); PRODUCT_GAPS claimed Playwright smoke tests that never existed; and
scripts/branch-protection.json listed contexts like `Python (ubuntu-latest)`
that no CI job can ever report, which would leave every pull request waiting
on a check that never arrives. These pin the checkable ones.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _cli_command_count() -> int:
    from devrepro.cli.app import app

    names = {c.name or c.callback.__name__.replace("_", "-") for c in app.registered_commands}
    return len(names)


def _frontend_page_count() -> int:
    """Count entries in App.tsx's NAV array.

    The array closes on a line that is exactly "]" -- splitting on the first
    "]" instead would stop inside the first entry.
    """
    lines = _read("web/src/App.tsx").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("const NAV = ["))
    end = next(
        i for i, line in enumerate(lines[start + 1 :], start + 1) if line.rstrip().startswith("]")
    )
    return sum(1 for line in lines[start + 1 : end] if line.lstrip().startswith("["))


def test_roadmap_cli_command_count_is_current() -> None:
    claimed = int(re.search(r"Full CLI \((\d+) commands", _read("ROADMAP.md")).group(1))
    assert claimed == _cli_command_count(), (
        f"ROADMAP claims {claimed} CLI commands; the CLI registers {_cli_command_count()}"
    )


def test_roadmap_frontend_page_count_is_current() -> None:
    claimed = int(re.search(r"frontend \((\d+) pages\)", _read("ROADMAP.md")).group(1))
    assert claimed == _frontend_page_count(), (
        f"ROADMAP claims {claimed} pages; App.tsx registers {_frontend_page_count()}"
    )


def test_docs_do_not_claim_playwright_that_does_not_exist() -> None:
    package_json = _read("web/package.json")
    has_playwright = "playwright" in package_json
    gaps = _read("PRODUCT_GAPS.md")
    claims_it_exists = "Playwright smoke tests exist" in gaps
    assert not (claims_it_exists and not has_playwright), (
        "PRODUCT_GAPS.md claims Playwright tests exist, but it is not a dependency"
    )


def test_branch_protection_contexts_match_real_job_names() -> None:
    """Every required context must be something a workflow can actually report."""
    contexts = set(
        json.loads(_read("scripts/branch-protection.json"))["required_status_checks"]["contexts"]
    )
    reportable: set[str] = set()
    for workflow in (_ROOT / ".github" / "workflows").glob("*.yml"):
        body = workflow.read_text(encoding="utf-8")
        for name in re.findall(r"^\s{4}name:\s*(.+?)\s*$", body, re.M):
            if "${{" not in name:
                reportable.add(name)
        # Matrix job names expand once per combination.
        if "Python (${{ matrix.os }}, ${{ matrix.python-version }})" in body:
            oses = re.search(r"os:\s*\[(.*?)\]", body).group(1).replace(" ", "").split(",")
            pys = re.findall(
                r'"(\d+\.\d+)"', re.search(r"python-version:\s*\[(.*?)\]", body).group(1)
            )
            reportable |= {f"Python ({o}, {p})" for o in oses for p in pys}
        # Unnamed matrix jobs report as "<job-id> (<matrix value>)".
        if "codeql" in workflow.name:
            langs = re.search(r"language:\s*\[(.*?)\]", body)
            if langs:
                reportable |= {f"analyze ({lang.strip()})" for lang in langs.group(1).split(",")}
                reportable.add("CodeQL")  # posted by the code-scanning app
    unreportable = sorted(contexts - reportable)
    assert not unreportable, (
        "branch-protection.json requires checks nothing can report "
        f"(PRs would hang forever): {unreportable}"
    )
