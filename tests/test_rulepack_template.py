"""The template has to work, or it teaches the wrong contract.

`templates/rule-pack/` exists so an author can copy a working pack instead of
inferring the contract from the built-ins. A template that has never been run is
worse than none: the first version of this one read `ctx.env`, which
`RuleContext` does not have -- exactly the mistake it exists to prevent, shipped
as the example.

So the template is exercised here, in this project's own suite, on every run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "rule-pack"


@pytest.fixture()
def example_pack() -> object:
    """Import the template's pack, without installing it."""
    src = str(TEMPLATE / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import devrepro_rulepack_example

    return devrepro_rulepack_example


def test_the_template_exists_where_the_docs_say() -> None:
    assert (TEMPLATE / "pyproject.toml").is_file()
    assert (TEMPLATE / "README.md").is_file()


def test_the_example_pack_passes_the_harness_it_documents(example_pack: object) -> None:
    """The check `devrepro rules-test` runs, run against the template itself."""
    from devrepro.core.models import PlatformInfo, ToolInstallation
    from devrepro.plugins.testkit import check_pack
    from devrepro.rules.base import PACK_NAMES, RuleContext

    ctx = RuleContext(
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        tools=(ToolInstallation(name="git", version="2.47.0", is_active=True),),
    )

    report = check_pack(example_pack.evaluate, ctx, reserved_prefixes=PACK_NAMES)

    assert report.ok, [p.describe() for p in report.problems]


def test_the_example_uses_a_prefix_of_its_own(example_pack: object) -> None:
    """A pack under a built-in prefix makes `explain` describe somebody else's rule."""
    from devrepro.core.models import PlatformInfo
    from devrepro.rules.base import PACK_NAMES, RuleContext

    ctx = RuleContext(platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"))
    for finding in example_pack.evaluate(ctx):
        assert finding.rule_id.split("/", 1)[0] not in PACK_NAMES


def test_the_entry_point_group_matches_the_loader() -> None:
    """A pack registered under the wrong group installs cleanly and never runs."""
    import tomllib

    payload = tomllib.loads((TEMPLATE / "pyproject.toml").read_text(encoding="utf-8"))
    groups = payload["project"]["entry-points"]
    assert "devrepro.rules" in groups

    from devrepro.plugins.loader import list_plugins

    assert "devrepro.rules" in list_plugins()
