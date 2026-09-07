"""A badge must point at something that exists.

Badges are the first thing a reader sees and the easiest thing to leave
stale: a workflow gets renamed, a Python version is dropped, a coverage floor
moves, and the row keeps asserting the old answer. These derive every claim
from the repository itself, so the row cannot say something the repo does not.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_PYPROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

_SLUG = "devrepro-doctor"
_OWNER = "webdevsamran"


def _badges() -> str:
    assert "<!-- badges -->" in _README, "README lost its badge block"
    return _README.split("<!-- badges -->", 1)[1].split("<!-- /badges -->", 1)[0]


def test_every_workflow_badge_names_a_workflow_that_exists() -> None:
    """A badge for a deleted or renamed workflow renders as a broken image."""
    referenced = set(re.findall(r"/actions/workflows/([\w.-]+)/badge\.svg", _badges()))
    assert referenced, "expected at least one workflow badge"
    missing = sorted(w for w in referenced if not (_ROOT / ".github" / "workflows" / w).exists())
    assert not missing, f"badges point at workflows that do not exist: {missing}"


def test_badges_point_at_this_repository() -> None:
    for owner, slug in re.findall(r"github\.com/([\w-]+)/([\w.-]+)", _badges()):
        assert (owner, slug) == (_OWNER, _SLUG), f"badge points at {owner}/{slug}"
    # `[\w/]+/` would let `/` be consumed by either side of the boundary,
    # which is the ambiguity CodeQL flags as py/redos. Bounding the path
    # prefix to whole `/`-free segments removes it.
    shields = re.findall(r"img\.shields\.io/github/(?:\w+/){1,3}([\w-]+)/([\w.-]+)", _badges())
    for owner, slug in shields:
        assert (owner, slug.split("?")[0]) == (_OWNER, _SLUG), f"badge points at {owner}/{slug}"


def test_the_python_badge_matches_the_classifiers() -> None:
    """Claiming a version the package does not classify is a promise it breaks."""
    declared = [
        c.split("::")[-1].strip()
        for c in _PYPROJECT["project"].get("classifiers", [])
        if "Programming Language :: Python ::" in c and "." in c.split("::")[-1]
    ]
    match = re.search(r"badge/python-([^)\]]+)-blue", _badges())
    assert match, "no python badge found"
    shown = [v.strip() for v in match.group(1).replace("%20%7C%20", "|").split("|")]
    assert shown == declared, f"badge says {shown}; classifiers say {declared}"


def test_the_python_badge_matches_what_ci_tests() -> None:
    """The badge is a support claim, so CI has to actually run those versions."""
    tested: set[str] = set()
    for workflow in (_ROOT / ".github" / "workflows").glob("*.yml"):
        body = workflow.read_text(encoding="utf-8")
        tested |= set(re.findall(r'python[_-]?version["\']?:\s*["\'](\d+\.\d+)["\']', body))
        for block in re.findall(r"python[_-]?version:\s*\[(.*?)\]", body):
            tested |= set(re.findall(r"(\d+\.\d+)", block))
        for block in re.findall(r"^\s+python:\s*\[(.*?)\]", body, re.M):
            tested |= set(re.findall(r"(\d+\.\d+)", block))
    match = re.search(r"badge/python-([^)\]]+)-blue", _badges())
    shown = {v.strip() for v in match.group(1).replace("%20%7C%20", "|").split("|")}
    untested = sorted(shown - tested)
    assert not untested, (
        f"the badge claims Python {untested}, which no CI job runs. "
        "Either test those versions or stop claiming them."
    )


def test_the_coverage_floor_badge_matches_the_configured_floor() -> None:
    configured = _PYPROJECT["tool"]["coverage"]["report"]["fail_under"]
    match = re.search(r"coverage%20floor-(\d+)%25", _badges())
    assert match, "no coverage-floor badge found"
    assert int(match.group(1)) == configured, (
        f"badge says {match.group(1)}%; pyproject's fail_under is {configured}"
    )


def test_the_readme_has_an_architecture_diagram_of_real_packages() -> None:
    """Every box in the diagram must name a package that exists.

    A diagram of aspirational modules is the same defect as a fabricated
    example, drawn instead of typed.
    """
    assert "<!-- mermaid:architecture -->" in _README, "README lost its architecture diagram"
    block = _README.split("<!-- mermaid:architecture -->", 1)[1].split(
        "<!-- /mermaid:architecture -->", 1
    )[0]
    assert block.strip().startswith("```mermaid"), "the marked block is not a mermaid diagram"
    package = _ROOT / "devrepro"
    # A box labelled `runtime/` or `results/dataset/` names a directory.
    # Resolve the whole path, under the package first and then the repo
    # root, the way a reader following the label would.
    referenced = set(re.findall(r"\b((?:[a-z_]+/)+)(?:<br/>|\]|\s|-)", block))
    assert referenced, "the diagram names no packages at all, so it checks nothing"
    unknown = sorted(
        path for path in referenced if not (package / path).is_dir() and not (_ROOT / path).is_dir()
    )
    assert not unknown, f"the diagram names directories that do not exist: {unknown}"
