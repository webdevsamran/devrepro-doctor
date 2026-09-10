"""Whether the update bot can see the files that pin the toolchain.

The asymmetry is the finding. Dependabot has no `package-ecosystem` that reads
a version-manager pin at all, so a repository can have a thorough
`dependabot.yml` and a `.nvmrc` that nothing will ever bump -- and nothing in
the config hints at it. Renovate's `nvm`, `asdf` and `mise` managers do read
them, and are on by default until somebody sets `enabledManagers`, which turns
the default-on list into an allowlist.

Two things are easy to get wrong here and both are tested: treating an absent
`enabledManagers` as an empty one (which inverts the answer), and reporting a
gap when there is no bot at all (which is noise, not a finding).
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- pytest resolves fixture annotations

from devrepro.project.botpins import analyse_pins, parse_dependabot, parse_renovate

DEPENDABOT = """version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: "/"
    schedule:
      interval: monthly
"""


def repo(tmp_path: Path, *files: str, dependabot: str = "", renovate: str = "") -> Path:
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith("workflows"):
            path.mkdir(exist_ok=True)
        else:
            path.write_text("x", encoding="utf-8")
    if dependabot:
        (tmp_path / ".github").mkdir(exist_ok=True)
        (tmp_path / ".github" / "dependabot.yml").write_text(dependabot, encoding="utf-8")
    if renovate:
        (tmp_path / "renovate.json").write_text(renovate, encoding="utf-8")
    return tmp_path


# -------------------------------------------------------------------- parsing


def test_dependabot_ecosystems_are_read() -> None:
    assert parse_dependabot(DEPENDABOT) == ("pip", "github-actions")


def test_a_quoted_and_an_unquoted_ecosystem_read_the_same() -> None:
    assert parse_dependabot(DEPENDABOT)[0] == "pip"


def test_a_file_too_exotic_to_parse_yields_nothing_rather_than_a_guess() -> None:
    assert parse_dependabot("version: 2\nupdates: []\n") == ()


def test_an_absent_enabled_managers_is_not_an_empty_one() -> None:
    """The inversion that would report every pin as unwatched.

    Renovate runs every manager unless `enabledManagers` is set. Collapsing
    "unset" and "set to nothing" into an empty tuple gets the answer exactly
    backwards for the common case.
    """
    managers, restricts = parse_renovate('{"extends": ["config:base"]}')
    assert managers == ()
    assert restricts is False

    managers, restricts = parse_renovate('{"enabledManagers": ["npm"]}')
    assert managers == ("npm",)
    assert restricts is True


def test_a_renovate_config_with_comments_still_parses() -> None:
    """Renovate accepts JSON5; a strict parser would report a gap that is not there."""
    managers, restricts = parse_renovate('// our config\n{"enabledManagers": ["nvm"]}')
    assert managers == ("nvm",)
    assert restricts is True


def test_unparseable_renovate_config_reports_unknown() -> None:
    assert parse_renovate("{{{not json at all") == ((), False)


# ------------------------------------------------------------------- coverage


def test_no_bot_config_is_not_a_finding(tmp_path: Path) -> None:
    """Plenty of teams update toolchains another way; saying otherwise is noise."""
    coverage = analyse_pins(repo(tmp_path, ".nvmrc"))
    assert not coverage.configured
    assert coverage.uncovered == ()


def test_dependabot_cannot_watch_a_version_manager_pin(tmp_path: Path) -> None:
    """The headline case: a complete config, and a Node version nothing bumps."""
    coverage = analyse_pins(repo(tmp_path, ".nvmrc", dependabot=DEPENDABOT))

    assert [p.path for p in coverage.uncovered] == [".nvmrc"]
    assert coverage.configured


def test_dependabot_does_watch_action_pins(tmp_path: Path) -> None:
    coverage = analyse_pins(repo(tmp_path, ".github/workflows", dependabot=DEPENDABOT))
    assert [p.path for p in coverage.covered] == [".github/workflows"]


def test_dependabot_watches_a_dockerfile_only_when_docker_is_declared(tmp_path: Path) -> None:
    without = analyse_pins(repo(tmp_path, "Dockerfile", dependabot=DEPENDABOT))
    assert [p.path for p in without.uncovered] == ["Dockerfile"]

    with_docker = analyse_pins(
        repo(
            tmp_path,
            dependabot=DEPENDABOT + '  - package-ecosystem: "docker"\n    directory: "/"\n',
        )
    )
    assert "docker" in with_docker.bots[0].ecosystems


def test_renovate_covers_the_pins_dependabot_cannot(tmp_path: Path) -> None:
    coverage = analyse_pins(
        repo(tmp_path, ".nvmrc", ".tool-versions", renovate='{"extends": ["config:base"]}')
    )
    assert coverage.uncovered == ()
    assert {p.path for p in coverage.covered} == {".nvmrc", ".tool-versions"}


def test_enabled_managers_turns_the_default_on_list_into_an_allowlist(tmp_path: Path) -> None:
    """Setting it to watch npm silently stops it watching .nvmrc."""
    coverage = analyse_pins(repo(tmp_path, ".nvmrc", renovate='{"enabledManagers": ["npm"]}'))
    assert [p.path for p in coverage.uncovered] == [".nvmrc"]


def test_a_pin_with_no_manager_anywhere_is_uncovered_under_either_bot(tmp_path: Path) -> None:
    """`global.json` and `rust-toolchain.toml` have no manager in either tool."""
    coverage = analyse_pins(repo(tmp_path, "global.json", renovate='{"extends": ["config:base"]}'))
    assert [p.path for p in coverage.uncovered] == ["global.json"]


def test_a_pin_file_that_does_not_exist_is_not_reported(tmp_path: Path) -> None:
    coverage = analyse_pins(repo(tmp_path, dependabot=DEPENDABOT))
    assert coverage.pins == ()


def test_both_bots_are_read_when_both_are_present(tmp_path: Path) -> None:
    coverage = analyse_pins(
        repo(
            tmp_path,
            ".nvmrc",
            dependabot=DEPENDABOT,
            renovate='{"extends": ["config:base"]}',
        )
    )
    assert {b.kind for b in coverage.bots} == {"dependabot", "renovate"}
    assert coverage.uncovered == ()
