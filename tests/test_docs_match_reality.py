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
    """Count the routes the console registers.

    The navigation used to be a flat `NAV` array of 32 tuples inside App.tsx,
    parsed here by bracket-matching. It now lives in `web/src/nav.ts` as
    grouped `NavItem` objects, which is also what the router and the command
    palette read -- one source of truth rather than three.

    Each item declares exactly one `id:`, so counting those counts the routes.
    """
    source = _read("web/src/nav.ts")
    groups = source.split("export const NAV_GROUPS", 1)
    assert len(groups) == 2, "nav.ts no longer declares NAV_GROUPS"
    body = groups[1].split("export const ALL_ITEMS", 1)[0]
    return len(re.findall(r"^\s*\{ id: ", body, flags=re.MULTILINE))


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


def test_the_playwright_claim_matches_the_dependency_both_ways() -> None:
    """The claim and the dependency have to agree in whichever direction is wrong.

    This started one-directional, because the fault it was written for was a
    `PRODUCT_GAPS.md` that advertised Playwright smoke tests that had never
    existed. Playwright exists now, which makes the old assertion vacuous and
    the opposite drift the live risk: a gaps file that still records browser
    coverage as missing after it shipped is just as untrue, and is the version
    a contributor would act on by writing it a second time.
    """
    package_json = _read("web/package.json")
    has_playwright = "playwright" in package_json
    gaps = _read("PRODUCT_GAPS.md")

    claims_absent = "There is no frontend e2e coverage" in gaps
    claims_present = "Playwright smoke tests exist" in gaps

    assert not (claims_present and not has_playwright), (
        "PRODUCT_GAPS.md claims Playwright tests exist, but it is not a dependency"
    )
    assert not (claims_absent and has_playwright), (
        "PRODUCT_GAPS.md records e2e coverage as missing, but Playwright is a dependency "
        "and web/e2e/ has specs"
    )
    if has_playwright:
        assert (_ROOT / "web" / "e2e").is_dir(), (
            "Playwright is a dependency but there are no specs for it to run"
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


# ------------------------------------------------------ the README scan example


def _capture_module():
    """Import scripts/capture_readme_example.py by path.

    `scripts/` is not a package, so a plain import will not find it.
    """
    import importlib.util

    path = _ROOT / "scripts" / "capture_readme_example.py"
    spec = importlib.util.spec_from_file_location("capture_readme_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_scan_example_matches_the_renderer() -> None:
    """The block in the README is what the code renders, not prose.

    The README carried a hand-written scan under the caption "Real findings
    you'll see (examples from actual scans)". CI runs the same check; this
    keeps it failing in a local `pytest` run too.
    """
    capture = _capture_module()
    readme = _read("README.md")
    assert readme == capture.splice(readme), (
        "README example drifted from the renderer; run: python scripts/capture_readme_example.py"
    )


def test_readme_scan_example_names_only_real_rules() -> None:
    """Every rule id shown must be one some code path can emit.

    The README carried a hand-written block for months whose ids and layout the
    renderer could not produce; a reader who grepped for them found nothing.

    The check now asks `is_emittable_rule_id`, not set membership. Rule ids come
    in two shapes and only one is a literal: probes compose ids onto a runtime
    prefix, as in `f"{name}/multiple-installations"` and
    `f"{ecosystem}/manager-conflict"`. Those were absent from
    `emittable_rule_ids()`, so this test would have rejected a README that
    documented them correctly -- `python/multiple-installations` is emitted
    whenever duplicate Python installs are found, which is exactly the
    situation the example depicts.
    """
    capture = _capture_module()
    shown = [rule for _, rule, _ in capture.EXAMPLE_FINDINGS]
    assert shown, "the example lost its findings"
    unemittable = [r for r in shown if not capture.is_emittable_rule_id(r)]
    assert not unemittable, f"README example names rule ids no code emits: {unemittable}"


def test_the_rule_id_guard_recognises_composed_ids() -> None:
    """The guard must over-approximate, as its docstring claims.

    It previously recognised only literal ids and the single spelling
    `rule_id=f"{rule_prefix}/..."`, missing every id a probe builds from a tool
    name or ecosystem. A guard that rejects real ids is worse than none: it
    pushes the docs away from the truth.
    """
    capture = _capture_module()
    suffixes = capture.composed_rule_suffixes()
    assert "multiple-installations" in suffixes
    assert "manager-conflict" in suffixes

    assert capture.is_emittable_rule_id("python/multiple-installations")
    assert capture.is_emittable_rule_id("kubectl/multiple-installations")
    assert capture.is_emittable_rule_id("node/manager-conflict")
    # Still rejects what it exists to reject.
    assert not capture.is_emittable_rule_id("totally/made-up-rule")
    assert not capture.is_emittable_rule_id("python/nonsense-suffix")


def test_the_documented_layout_is_the_one_the_command_prints() -> None:
    """`devrepro doctor` must go through the same renderer the README does.

    The table used to be built inline in the command, so the README's layout
    could not be captured from anything -- and it wasn't: it showed an
    `Evidence:` / `Safe remediation:` block that no code produces.
    """
    diagnostics = _read("devrepro/cli/commands/diagnostics.py")
    assert "render_terminal_table" in diagnostics, (
        "devrepro doctor no longer uses the shared renderer, so the README "
        "example is no longer evidence of anything"
    )
    assert "Evidence:" not in _read("README.md")
