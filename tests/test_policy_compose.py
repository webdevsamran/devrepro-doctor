"""Composing a paved road with a repository's own policy.

A platform team publishes rules; a repository has its own needs. Without
composition those live in one file, so a repository either restates the org's
rules -- and they drift the moment the org changes one -- or ignores them, and
the paved road exists only in a wiki page.

The mechanics of merging are the easy half. The half that decides whether
anyone trusts the result is attribution: "node >=22" is not actionable, and
"node >=22, required by the org paved road and not overridden here" tells you
whose rule you are failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.cli.app import app
from devrepro.core.errors import PolicyError
from devrepro.core.exit_codes import ExitCode
from devrepro.project.compose import MAX_POLICY_DEPTH, load_composed_policy
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
NL = chr(10)

ORG = """
[meta]
name = "org paved road"

[required_runtimes]
node = ">=22"
python = ">=3.12"

[required_tools]
git = ">=2.40"

[required_env_names]
names = ["HTTP_PROXY"]
"""

REPO = """
extends = "../org/.devrepro.toml"

[required_runtimes]
node = ">=20"

[required_env_names]
names = ["DATABASE_URL"]
"""


def layers(tmp_path: Path, *, repo: str = REPO, org: str = ORG) -> Path:
    (tmp_path / "org").mkdir()
    (tmp_path / "repo").mkdir()
    (tmp_path / "org" / ".devrepro.toml").write_text(org, encoding="utf-8")
    (tmp_path / "repo" / ".devrepro.toml").write_text(repo, encoding="utf-8")
    return tmp_path / "repo" / ".devrepro.toml"


# ------------------------------------------------------------------ merging


def test_the_nearer_layer_wins(tmp_path: Path) -> None:
    composed = load_composed_policy(layers(tmp_path))
    assert composed.policy.required_runtimes["node"] == ">=20"


def test_what_the_repository_does_not_mention_is_inherited(tmp_path: Path) -> None:
    composed = load_composed_policy(layers(tmp_path))
    assert composed.policy.required_runtimes["python"] == ">=3.12"
    assert composed.policy.required_tools["git"] == ">=2.40"


def test_ranges_are_not_intersected(tmp_path: Path) -> None:
    """Cleverer, and it would produce a requirement neither file contains.

    An intersection of `>=22` and `>=20` is a rule nobody wrote and nobody can
    then explain to the developer it blocks.
    """
    composed = load_composed_policy(layers(tmp_path))
    assert composed.policy.required_runtimes["node"] == ">=20"
    assert "," not in composed.policy.required_runtimes["node"]


def test_required_env_names_accumulate_rather_than_override(tmp_path: Path) -> None:
    """A list of names is additive by nature.

    Letting the nearer layer replace it would silently drop the org's
    requirement, and nothing in the repository's file says that is what it is
    doing.
    """
    composed = load_composed_policy(layers(tmp_path))
    assert set(composed.policy.required_env_names.names) == {"DATABASE_URL", "HTTP_PROXY"}


# -------------------------------------------------------------- attribution


def test_each_requirement_names_the_layer_it_came_from(tmp_path: Path) -> None:
    composed = load_composed_policy(layers(tmp_path))
    assert composed.source_of("required_runtimes.python") == "org paved road"
    assert composed.source_of("required_runtimes.node") == "this project"


def test_an_override_records_what_it_overrode(tmp_path: Path) -> None:
    composed = load_composed_policy(layers(tmp_path))
    override = next(p for p in composed.provenance if p.key == "required_runtimes.node")
    assert override.overrides == ("org paved road",)
    assert override.is_override


def test_an_inherited_requirement_is_not_an_override(tmp_path: Path) -> None:
    composed = load_composed_policy(layers(tmp_path))
    inherited = next(p for p in composed.provenance if p.key == "required_runtimes.python")
    assert inherited.overrides == ()
    assert not inherited.is_override


def test_a_layer_names_itself_when_it_says_so(tmp_path: Path) -> None:
    """A platform team naming its paved road beats a filename."""
    composed = load_composed_policy(layers(tmp_path))
    assert [layer.label for layer in composed.layers] == ["this project", "org paved road"]


def test_a_layer_without_a_name_falls_back_to_its_directory(tmp_path: Path) -> None:
    composed = load_composed_policy(
        layers(tmp_path, org=ORG.replace('name = "org paved road"', 'other = "x"'))
    )
    assert composed.layers[1].label == "org"


# ------------------------------------------------------------------ shape


def test_extends_resolves_relative_to_the_file_not_the_cwd(tmp_path: Path, monkeypatch) -> None:
    """Or a policy chain works from the repository root and breaks below it."""
    target = layers(tmp_path)
    monkeypatch.chdir(tmp_path / "org")
    composed = load_composed_policy(target)
    assert composed.policy.required_tools["git"] == ">=2.40"


def test_extends_may_name_a_directory(tmp_path: Path) -> None:
    composed = load_composed_policy(layers(tmp_path, repo=REPO.replace("/.devrepro.toml", "")))
    assert len(composed.layers) == 2


def test_a_policy_with_no_extends_is_a_single_layer(tmp_path: Path) -> None:
    path = tmp_path / ".devrepro.toml"
    path.write_text(ORG, encoding="utf-8")
    composed = load_composed_policy(path)
    assert len(composed.layers) == 1
    assert composed.overrides == ()


def test_two_parents_are_ordered_as_written(tmp_path: Path) -> None:
    """ "Listed first wins" is what a reader of the file expects."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / ".devrepro.toml").write_text(
        "[meta]" + NL + 'name = "a"' + NL + "[required_tools]" + NL + 'jq = ">=1"' + NL,
        encoding="utf-8",
    )
    (tmp_path / "b" / ".devrepro.toml").write_text(
        "[meta]" + NL + 'name = "b"' + NL + "[required_tools]" + NL + 'jq = ">=2"' + NL,
        encoding="utf-8",
    )
    root = tmp_path / ".devrepro.toml"
    root.write_text('extends = ["a", "b"]' + NL, encoding="utf-8")

    composed = load_composed_policy(root)

    assert composed.policy.required_tools["jq"] == ">=1"
    assert composed.source_of("required_tools.jq") == "a"


# ------------------------------------------------------------------ refusals


def test_a_url_is_refused(tmp_path: Path) -> None:
    """Loading a policy must not become a network operation."""
    path = tmp_path / ".devrepro.toml"
    path.write_text('extends = "https://example.invalid/paved-road.toml"' + NL, encoding="utf-8")

    with pytest.raises(PolicyError) as excinfo:
        load_composed_policy(path)

    assert "URL" in str(excinfo.value)


def test_a_missing_parent_names_where_it_looked(tmp_path: Path) -> None:
    path = tmp_path / ".devrepro.toml"
    path.write_text('extends = "../nope/.devrepro.toml"' + NL, encoding="utf-8")

    with pytest.raises(PolicyError) as excinfo:
        load_composed_policy(path)

    assert "does not exist" in str(excinfo.value)


def test_a_cycle_terminates(tmp_path: Path) -> None:
    """A loop must be an error message rather than a hang."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / ".devrepro.toml").write_text('extends = "../b"' + NL, encoding="utf-8")
    (tmp_path / "b" / ".devrepro.toml").write_text('extends = "../a"' + NL, encoding="utf-8")

    composed = load_composed_policy(tmp_path / "a" / ".devrepro.toml")

    # The first arrival is the nearest one; re-adding it would change
    # precedence, so a diamond and a cycle are both resolved by visiting once.
    assert [layer.depth for layer in composed.layers] == [0, 1]


def test_a_chain_deeper_than_the_limit_is_refused(tmp_path: Path) -> None:
    for index in range(MAX_POLICY_DEPTH + 2):
        directory = tmp_path / f"layer{index}"
        directory.mkdir()
        body = f'extends = "../layer{index + 1}"' + NL
        (directory / ".devrepro.toml").write_text(body, encoding="utf-8")
    # The last one has nowhere to point, which would be a missing-parent error;
    # give it a real body instead so the depth limit is what fires.
    (tmp_path / f"layer{MAX_POLICY_DEPTH + 1}" / ".devrepro.toml").write_text("", encoding="utf-8")

    with pytest.raises(PolicyError) as excinfo:
        load_composed_policy(tmp_path / "layer0" / ".devrepro.toml")

    assert "deeper than" in str(excinfo.value)


# ---------------------------------------------------------------------- CLI


def test_check_reports_the_layers_and_the_override(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["check", "--policy", str(layers(tmp_path)), "--project", str(tmp_path)]
    )
    assert "org paved road" in result.output
    assert "overrides" in result.output


def test_check_json_carries_the_requirement_sources(tmp_path: Path) -> None:
    import json

    result = runner.invoke(
        app,
        ["check", "--policy", str(layers(tmp_path)), "--project", str(tmp_path), "--json"],
    )
    payload = json.loads(result.output)
    sources = {row["key"]: row["from"] for row in payload["requirement_sources"]}
    assert sources["required_runtimes.python"] == "org paved road"
    assert sources["required_runtimes.node"] == "this project"


def test_check_does_not_print_a_python_dict_to_a_human(tmp_path: Path) -> None:
    """The fault this shares with `generate`, which was fixed there first.

    Someone who did not ask for `--json` wants to read the answer, not parse a
    quoted repr of the whole report on one line.
    """
    result = runner.invoke(
        app, ["check", "--policy", str(layers(tmp_path)), "--project", str(tmp_path)]
    )
    assert "{'policy':" not in result.output
    assert "'findings':" not in result.output
    assert "CHECK:" in result.output


def test_an_invalid_policy_is_a_usage_error_not_a_verdict(tmp_path: Path) -> None:
    path = tmp_path / ".devrepro.toml"
    path.write_text("this is not toml {{{", encoding="utf-8")
    result = runner.invoke(app, ["check", "--policy", str(path), "--project", str(tmp_path)])
    assert result.exit_code == ExitCode.USAGE_ERROR
