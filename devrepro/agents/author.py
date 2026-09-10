"""Draft an `AGENTS.md` that cannot already be wrong.

Every `AGENTS.md` this project has examined drifts from the CI that actually
gates the repository, and always in the same direction: the file lists a subset,
so an agent runs everything it was told to, sees green, and is failed by the
pull request for reasons the file never mentioned. Three of three repositories
on this machine had it.

The reason is structural rather than careless. Someone writes the file once,
from memory, and then CI grows a gate. Nothing connects the two, so nothing
notices.

So this drafts the file *from* the workflow rather than from memory. The
commands come from `ci_declared_commands` -- the same function
`devrepro agent-check` uses to find drift -- which means a freshly generated
file scores 3/3 on `matches-ci` by construction, and any later drift is CI
having moved, which is the case worth reporting.

Two things it deliberately does not do:

* **Invent project conventions.** A generated file says what is verifiable --
  the gates, the detected toolchains, the layout -- and leaves the reasoning an
  agent actually needs to a section marked for a human to write. A confident
  paragraph of invented house style is worse than an empty heading, because
  nobody edits what looks finished.
* **Overwrite.** It returns a draft. `write_generated` refuses to clobber
  without `--overwrite`, like every other generator here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from devrepro.agents.manifest import ci_declared_commands

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ProjectShape",
    "detect_project_shape",
    "generate_agents_md",
    "split_setup_and_gates",
]

NL = chr(10)

#: Files that identify an ecosystem, and what to call it.
_ECOSYSTEM_MARKERS: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", "Python"),
    ("setup.py", "Python"),
    ("requirements.txt", "Python"),
    ("package.json", "Node"),
    ("go.mod", "Go"),
    ("Cargo.toml", "Rust"),
    ("composer.json", "PHP"),
    ("Gemfile", "Ruby"),
    ("pom.xml", "Java"),
    ("build.gradle", "Java"),
    ("build.gradle.kts", "Java"),
    ("CMakeLists.txt", "C/C++"),
)

#: Prefixes that mark a step as *setup* rather than verification. Listing
#: `pip install -e ".[dev]"` under "checks that gate a pull request" is wrong in
#: a way that matters: an agent reading it as a check has no idea it is the
#: thing that has to happen first, and one reading the whole list as gates will
#: report a successful install as a passing gate.
_SETUP_PREFIXES: tuple[str, ...] = (
    "pip install",
    "python -m pip",
    "uv pip install",
    "uv sync",
    "poetry install",
    "npm ci",
    "npm install",
    "npm i ",
    "yarn install",
    "pnpm install",
    "bundle install",
    "go mod download",
    "cargo fetch",
    "apt-get",
    "sudo apt",
    "npx playwright install",
    "playwright install",
)

#: Directories worth naming in a layout section. Anything else is noise to an
#: agent that can run `ls` for itself.
_NOTABLE_DIRS: tuple[str, ...] = (
    "src",
    "lib",
    "app",
    "tests",
    "test",
    "docs",
    "scripts",
    "web",
    "frontend",
    "backend",
    "packages",
    "services",
    "examples",
)


class ProjectShape:
    """What can be said about a repository without guessing."""

    def __init__(
        self,
        *,
        name: str,
        ecosystems: tuple[str, ...] = (),
        gates: tuple[str, ...] = (),
        directories: tuple[str, ...] = (),
        has_precommit: bool = False,
        existing_manifests: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.ecosystems = ecosystems
        self.gates = gates
        self.directories = directories
        self.has_precommit = has_precommit
        self.existing_manifests = existing_manifests

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"ProjectShape(name={self.name!r}, gates={len(self.gates)})"


def detect_project_shape(root: Path | str) -> ProjectShape:
    """Read a repository's shape from what is on disk.

    Nothing is executed and nothing is inferred beyond what a file's presence
    directly states. A repository with a `pyproject.toml` is a Python project;
    whether it is a library or a service is not something a directory listing
    knows, so it is not claimed.
    """
    root = Path(root)

    ecosystems: list[str] = []
    for marker, label in _ECOSYSTEM_MARKERS:
        if (root / marker).is_file() and label not in ecosystems:
            ecosystems.append(label)
    # A nested frontend is common enough to be worth one level of looking.
    if "Node" not in ecosystems and any(p.is_file() for p in root.glob("*/package.json")):
        ecosystems.append("Node")

    directories = tuple(
        name for name in _NOTABLE_DIRS if (root / name).is_dir() and not name.startswith(".")
    )

    manifests = tuple(
        name
        for name in ("AGENTS.md", "CLAUDE.md", ".cursorrules", ".github/copilot-instructions.md")
        if (root / name).is_file()
    )

    return ProjectShape(
        name=root.resolve().name,
        ecosystems=tuple(ecosystems),
        gates=tuple(_dedupe(ci_declared_commands(root))),
        directories=directories,
        has_precommit=(root / ".pre-commit-config.yaml").is_file(),
        existing_manifests=manifests,
    )


def split_setup_and_gates(commands: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate "install this first" from "this must pass".

    A workflow's `run:` steps are both, in order, and calling all of them gates
    is inaccurate in a way an agent acts on: it will treat a successful
    `pip install` as a passing check, and it has no way to know that the
    install is the prerequisite for everything after it.
    """
    setup: list[str] = []
    gates: list[str] = []
    for command in commands:
        normalised = " ".join(command.split()).lower()
        (setup if normalised.startswith(_SETUP_PREFIXES) else gates).append(command)
    return tuple(setup), tuple(gates)


def _dedupe(commands: Iterable[str]) -> list[str]:
    """Preserve order, drop repeats.

    A matrix job repeats the same command once per leg, and a generated file
    listing `pytest` four times reads as a mistake even though the workflow
    really does run it four times.
    """
    seen: set[str] = set()
    out: list[str] = []
    for command in commands:
        key = " ".join(command.split())
        if key and key not in seen:
            seen.add(key)
            out.append(command.strip())
    return out


def generate_agents_md(shape: ProjectShape) -> str:
    """Render a reviewable `AGENTS.md` draft.

    The gate list is the point. Everything else is scaffolding around it,
    including the explicit invitation to write the parts a generator cannot
    know -- left as headings with a marker rather than as invented prose,
    because a paragraph that looks finished never gets edited.
    """
    lines: list[str] = [
        f"# {shape.name}",
        "",
        "Instructions for an automated contributor.",
        "",
        "> Drafted by `devrepro generate agents-md` from this repository's CI",
        "> workflows. **If a command below disagrees with the workflow, the",
        "> workflow wins and this file is the bug.** Re-run",
        "> `devrepro agent-check .` after changing either.",
        "",
    ]

    if shape.ecosystems:
        lines += [
            "## What this is",
            "",
            f"A {' + '.join(shape.ecosystems)} project.",
            "",
            "<!-- TODO(human): one paragraph on what it does and who uses it. A",
            "     generator cannot know this, and an agent reads it first. -->",
            "",
        ]

    setup, gates = split_setup_and_gates(shape.gates)

    if setup:
        lines += [
            "## Setup",
            "",
            "```bash",
            *setup,
            "```",
            "",
        ]

    lines += ["## Checks that gate a pull request", ""]
    if gates:
        lines += [
            "Every one of these runs in CI. Run them all before proposing a",
            "change; a subset is how a green local run still fails the pull",
            "request.",
            "",
            "```bash",
            *gates,
            "```",
            "",
            f"That is {len(gates)} command(s), read from the workflows that",
            "trigger on pull requests. Release-only steps are deliberately",
            "excluded: an agent should not be running `twine` or `gh release`.",
            "",
        ]
    else:
        lines += [
            "<!-- TODO(human): no pull-request workflow was found, so this",
            "     section could not be generated. List the commands that must",
            "     pass, and keep them identical to whatever gates merges. -->",
            "",
        ]

    if shape.has_precommit:
        lines += [
            "A `.pre-commit-config.yaml` exists. `pre-commit run --all-files`",
            "covers the hooks in it, which may be a subset of the list above.",
            "",
        ]

    if shape.directories:
        lines += [
            "## Layout",
            "",
            *(f"- `{name}/`" for name in shape.directories),
            "",
        ]

    lines += [
        "## Conventions",
        "",
        "<!-- TODO(human): the rules that are not obvious from the code -- what",
        "     to name things, what never to touch, which patterns were chosen",
        "     deliberately and which are accidents nobody has cleaned up. This",
        "     is the section an agent most needs and the one a generator is",
        "     least able to write, so it is left empty on purpose rather than",
        "     filled with plausible guesses. -->",
        "",
        "## Before you finish",
        "",
        "- Run every command in the gate list above.",
        "- `devrepro agent-check .` reports whether this file still matches CI,",
        "  whether every declared command resolves on this machine, and what a",
        "  session here could reach.",
        "",
    ]

    if len(shape.existing_manifests) > 1:
        others = ", ".join(f"`{m}`" for m in shape.existing_manifests if m != "AGENTS.md")
        lines += [
            "## Other instruction files",
            "",
            f"This repository also has {others}. Keep them consistent:",
            "`devrepro agent-check .` reports where they disagree, and an agent",
            "reading one of them will not see the others.",
            "",
        ]

    return NL.join(lines).rstrip() + NL
