"""Drafting an `AGENTS.md` that starts out agreeing with CI.

Every `AGENTS.md` this project has examined drifts from the workflow that
gates its repository, always in the same direction: the file lists a subset, so
an agent runs everything it was told to, sees green, and is failed by the pull
request for reasons the file never mentioned. Three of three repositories on
this machine had it.

The load-bearing test here is the round trip -- generate a file, then run the
same drift check `devrepro agent-check` runs, and assert it finds nothing. If
the generator and the checker ever disagree about what a gate is, that fails,
which is the only way to keep this from becoming another file that starts out
wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.agents.author import (
    detect_project_shape,
    generate_agents_md,
    split_setup_and_gates,
)
from devrepro.agents.manifest import (
    ci_declared_commands,
    manifest_vs_ci,
    parse_declared_commands,
)

if TYPE_CHECKING:
    from pathlib import Path

NL = chr(10)

WORKFLOW = """
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: mypy src
      - run: pytest -q
  frontend:
    runs-on: ubuntu-latest
    steps:
      - run: npm ci
      - run: npm run lint
      - run: npm test
"""

RELEASE_WORKFLOW = """
name: Release
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: python -m build
      - run: twine upload dist/*
"""


def project(tmp_path: Path, *, workflow: str = WORKFLOW, **files: str) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(workflow, encoding="utf-8")
    for name, content in files.items():
        path = tmp_path / name.replace("__", ".")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------- the shape


def test_ecosystems_come_from_files_that_are_there(tmp_path: Path) -> None:
    root = project(tmp_path, pyproject__toml="[project]", package__json="{}")
    shape = detect_project_shape(root)
    assert set(shape.ecosystems) == {"Python", "Node"}


def test_a_nested_frontend_counts_as_node(tmp_path: Path) -> None:
    """A `web/package.json` beside a Python root is the common shape here."""
    root = project(tmp_path, pyproject__toml="[project]")
    (root / "web").mkdir()
    (root / "web" / "package.json").write_text("{}", encoding="utf-8")
    assert "Node" in detect_project_shape(root).ecosystems


def test_notable_directories_are_listed_and_others_are_not(tmp_path: Path) -> None:
    root = project(tmp_path)
    for name in ("tests", "docs", "node_modules", ".venv"):
        (root / name).mkdir()
    shape = detect_project_shape(root)
    assert "tests" in shape.directories
    assert "docs" in shape.directories
    assert "node_modules" not in shape.directories


def test_repeated_matrix_commands_appear_once(tmp_path: Path) -> None:
    """A twelve-leg matrix runs `pytest` twelve times.

    A generated file listing it twelve times reads as a mistake even though the
    workflow really does.
    """
    workflow = WORKFLOW + WORKFLOW.split("jobs:", 1)[1].replace("test:", "test2:")
    shape = detect_project_shape(project(tmp_path, workflow=workflow))
    assert shape.gates.count("pytest -q") == 1


def test_release_only_steps_are_excluded(tmp_path: Path) -> None:
    """An agent should not be running `twine upload`."""
    root = project(tmp_path)
    (root / ".github" / "workflows" / "release.yml").write_text(RELEASE_WORKFLOW, encoding="utf-8")
    gates = detect_project_shape(root).gates
    assert not any("twine" in gate for gate in gates)


# ------------------------------------------------------- setup vs gates


@pytest.mark.parametrize(
    "command",
    [
        'pip install -e ".[dev]"',
        "python -m pip install --upgrade pip",
        "npm ci",
        "uv sync",
        "npx playwright install --with-deps chromium",
    ],
)
def test_installation_is_setup_not_a_gate(command: str) -> None:
    """Calling an install a gate is wrong in a way an agent acts on.

    It will treat a successful `pip install` as a passing check, and it has no
    way to learn that the install is the prerequisite for everything after it.
    """
    setup, gates = split_setup_and_gates([command])
    assert setup == (command,)
    assert gates == ()


@pytest.mark.parametrize("command", ["pytest -q", "ruff check src", "npm run lint"])
def test_verification_is_a_gate(command: str) -> None:
    setup, gates = split_setup_and_gates([command])
    assert gates == (command,)
    assert setup == ()


def test_both_sections_appear_when_both_exist(tmp_path: Path) -> None:
    rendered = generate_agents_md(detect_project_shape(project(tmp_path)))
    assert "## Setup" in rendered
    assert "## Checks that gate a pull request" in rendered
    assert rendered.index("## Setup") < rendered.index("## Checks that gate")


# ------------------------------------------------------------ the round trip


def test_a_generated_file_agrees_with_the_workflow_it_came_from(tmp_path: Path) -> None:
    """The property the whole feature exists for.

    Generate, then run the same drift check `devrepro agent-check` runs. If the
    generator and the checker ever disagree about what counts as a gate, this
    fails -- which is the only thing keeping this from producing another file
    that starts out wrong.
    """
    root = project(tmp_path)
    rendered = generate_agents_md(detect_project_shape(root))
    (root / "AGENTS.md").write_text(rendered, encoding="utf-8")

    declared = parse_declared_commands(rendered, "AGENTS.md")
    missing = manifest_vs_ci(declared, ci_declared_commands(root))

    assert missing == [], f"the generated file already omits {missing}"


def test_the_round_trip_holds_for_this_repository() -> None:
    """The same check against a real workflow, with jobs and a matrix.

    The synthetic fixture above cannot exercise a matrix, `working-directory`,
    or a second workflow file, and those are exactly where a line-based YAML
    reader goes wrong.
    """
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent
    rendered = generate_agents_md(detect_project_shape(root))

    declared = parse_declared_commands(rendered, "AGENTS.md")
    missing = manifest_vs_ci(declared, ci_declared_commands(root))

    assert missing == [], f"a freshly generated file would already omit {missing}"


# ----------------------------------------------------------------- content


def test_the_draft_says_the_workflow_wins(tmp_path: Path) -> None:
    """The rule that makes the file falsifiable rather than decorative.

    Matched against whitespace-collapsed text: the sentence is wrapped across
    lines in a blockquote, so a contiguous-substring assertion would be testing
    the line width rather than the claim.
    """
    rendered = generate_agents_md(detect_project_shape(project(tmp_path)))
    # Strip the blockquote markers too: the sentence spans wrapped lines, each
    # of which starts `> `, so collapsing whitespace alone leaves them in the
    # middle of it.
    prose = " ".join(line.lstrip("> ") for line in rendered.splitlines())
    assert "the workflow wins and this file is the bug" in " ".join(prose.split())


def test_conventions_are_left_for_a_human_rather_than_invented(tmp_path: Path) -> None:
    """A confident paragraph of invented house style is worse than a gap.

    Nobody edits what looks finished, and an agent cannot tell a generated
    guess from a considered rule.
    """
    rendered = generate_agents_md(detect_project_shape(project(tmp_path)))
    assert "## Conventions" in rendered
    conventions = rendered.split("## Conventions", 1)[1].split("##", 1)[0]
    assert "TODO(human)" in conventions
    # Nothing between the heading and the marker that reads as finished prose.
    assert conventions.strip().startswith("<!--")


def test_a_repository_with_no_pull_request_workflow_says_so(tmp_path: Path) -> None:
    root = project(tmp_path, workflow=RELEASE_WORKFLOW)
    rendered = generate_agents_md(detect_project_shape(root))
    assert "no pull-request workflow was found" in rendered


def test_other_instruction_files_are_named_when_they_exist(tmp_path: Path) -> None:
    """An agent reading one of them will not see the others."""
    root = project(tmp_path)
    (root / "AGENTS.md").write_text("x", encoding="utf-8")
    (root / "CLAUDE.md").write_text("y", encoding="utf-8")

    rendered = generate_agents_md(detect_project_shape(root))

    assert "CLAUDE.md" in rendered
    assert "agent-check" in rendered


def test_a_lone_manifest_gets_no_consistency_section(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "AGENTS.md").write_text("x", encoding="utf-8")
    assert "## Other instruction files" not in generate_agents_md(detect_project_shape(root))


def test_the_precommit_config_is_mentioned_only_when_present(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert "pre-commit run" not in generate_agents_md(detect_project_shape(root))
    (root / ".pre-commit-config.yaml").write_text("repos: []", encoding="utf-8")
    assert "pre-commit run" in generate_agents_md(detect_project_shape(root))


def test_the_draft_ends_with_a_single_newline(tmp_path: Path) -> None:
    rendered = generate_agents_md(detect_project_shape(project(tmp_path)))
    assert rendered.endswith(NL)
    assert not rendered.endswith(NL + NL)
