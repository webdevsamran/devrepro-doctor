"""Parse agent manifests and check what they declare against this machine."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from devrepro.probes.helpers import read_text_safe, resolve_all_on_path

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "AGENT_MANIFESTS",
    "AgentManifest",
    "CommandCheck",
    "DeclaredCommand",
    "check_declared_commands",
    "ci_declared_commands",
    "discover_manifests",
    "manifest_vs_ci",
    "parse_declared_commands",
]

#: Manifest filenames, in the order they are reported. `AGENTS.md` is the
#: cross-vendor convention; the rest are vendor-specific files that coexist
#: with it and routinely drift from it.
AGENT_MANIFESTS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".cursor/rules",
    ".github/copilot-instructions.md",
    ".windsurfrules",
    "GEMINI.md",
)

#: Fenced blocks whose contents are commands rather than prose or data. A
#: manifest full of ```json config blocks must not have its braces treated as
#: things to run.
_SHELL_FENCES = {"bash", "sh", "shell", "zsh", "console", "shell-session", "terminal", ""}

_FENCE = re.compile(r"^\s*```([A-Za-z0-9_-]*)\s*$")

#: Leading noise on a copied command line: a shell prompt, or a `$`/`>` marker.
_PROMPT = re.compile(r"^\s*(?:\$|>|#\s*\$)\s+")

#: Shell keywords that begin a construct rather than name a program.
_SHELL_KEYWORDS = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "do",
        "done",
        "case",
        "esac",
        "function",
        "return",
        "export",
        "source",
        "set",
        "unset",
        "alias",
        "local",
        "read",
        "shift",
        "trap",
        "eval",
        "exec",
        "continue",
        "break",
        "wait",
        "declare",
        "typeset",
    }
)

#: Builtins that always resolve, so their absence from PATH means nothing.
_SHELL_BUILTINS = frozenset({"cd", "echo", "true", "false", "test", "pwd", "exit", ":"})


@dataclass(frozen=True)
class DeclaredCommand:
    """One command a manifest tells an agent to run."""

    raw: str
    program: str
    manifest: str
    line: int

    @property
    def is_runnable(self) -> bool:
        """False for shell constructs that name no program."""
        return bool(self.program) and self.program not in _SHELL_KEYWORDS


@dataclass(frozen=True)
class AgentManifest:
    """An agent manifest found in a repository."""

    path: str
    commands: tuple[DeclaredCommand, ...] = ()

    @property
    def name(self) -> str:
        return Path(self.path).name


@dataclass(frozen=True)
class CommandCheck:
    """The verdict on one declared command, with the evidence behind it."""

    command: DeclaredCommand
    status: str
    detail: str
    resolved: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "shell-builtin"}


def discover_manifests(root: Path | str) -> list[AgentManifest]:
    """Find every agent manifest in ``root`` and parse the commands it declares."""
    root = Path(root)
    found: list[AgentManifest] = []
    for rel in AGENT_MANIFESTS:
        path = root / rel
        if not path.is_file():
            continue
        text = read_text_safe(path)
        if text is None:
            continue
        found.append(
            AgentManifest(
                path=rel.replace(os.sep, "/"),
                commands=tuple(parse_declared_commands(text, rel)),
            )
        )
    return found


def parse_declared_commands(text: str, manifest: str) -> list[DeclaredCommand]:
    """Extract commands from the shell blocks of a manifest.

    Only fenced blocks are considered, and only those whose language marks them
    as shell. Prose that happens to look like a command is not a declaration,
    and a ```json block is configuration, not instructions.
    """
    commands: list[DeclaredCommand] = []
    in_shell_block = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence is not None:
            language = fence.group(1).lower()
            # A closing fence carries no language; treat it as closing whatever
            # is open, and an opening fence as shell only if it says so.
            in_shell_block = (not in_shell_block) and language in _SHELL_FENCES
            continue
        if not in_shell_block:
            continue

        for part in _split_command_line(line):
            program = _program_of(part)
            if program:
                commands.append(
                    DeclaredCommand(raw=part, program=program, manifest=manifest, line=lineno)
                )
    return commands


def _split_command_line(line: str) -> list[str]:
    """One source line into the individual commands it runs.

    `cd web && npm ci && npm test` is three commands, and an agent hits each of
    them in turn. Comments and continuations are dropped.
    """
    stripped = _PROMPT.sub("", line).strip()
    if not stripped or stripped.startswith("#"):
        return []
    stripped = stripped.rstrip("\\").strip()
    # Strip a trailing comment, which is prose about the command, not part of it.
    if " #" in stripped:
        stripped = stripped.split(" #", 1)[0].strip()
    parts = re.split(r"&&|\|\||;", stripped)
    return [p.strip() for p in parts if p.strip()]


def _program_of(command: str) -> str:
    """argv[0] of a command, ignoring leading VAR=value assignments."""
    tokens = command.split()
    for token in tokens:
        if "=" in token and not token.startswith("-") and re.match(r"^[A-Za-z_]\w*=", token):
            continue  # environment prefix, e.g. CI=1 pytest
        return token.strip("\"'")
    return ""


def check_declared_commands(
    commands: Iterable[DeclaredCommand],
    *,
    root: Path | str | None = None,
    path_env: str | None = None,
) -> list[CommandCheck]:
    """Resolve each declared command's program without running anything.

    The distinction that matters, and that an agent cannot currently make on
    its own, is between a program that is absent and one that is installed but
    unreachable from this shell. `ruff` not being on PATH while `python -m ruff`
    works is a PATH problem with a different fix from `pip install ruff`.
    """
    checks: list[CommandCheck] = []
    seen: set[tuple[str, str]] = set()

    for command in commands:
        if not command.is_runnable:
            continue
        key = (command.program, command.manifest)
        if key in seen:
            continue
        seen.add(key)

        if _looks_like_path(command.program):
            checks.append(_check_path_program(command, root))
            continue

        if command.program in _SHELL_BUILTINS:
            checks.append(
                CommandCheck(
                    command=command,
                    status="shell-builtin",
                    detail=f"{command.program!r} is a shell builtin; always available.",
                )
            )
            continue

        matches = resolve_all_on_path(command.program, path_env=path_env)
        if matches:
            extra = ""
            if len(matches) > 1:
                extra = f" {len(matches)} installations found; the first wins."
            checks.append(
                CommandCheck(
                    command=command,
                    status="ok",
                    detail=f"{command.program!r} resolves on PATH.{extra}",
                    resolved=matches[0],
                )
            )
            continue

        module = _importable_module(command.program)
        if module is not None:
            checks.append(
                CommandCheck(
                    command=command,
                    status="not-on-path",
                    detail=(
                        f"{command.program!r} is installed but not on PATH in this "
                        f"shell. `python -m {module}` works, so this is a PATH "
                        "problem, not a missing dependency -- activate the "
                        "virtualenv or add the scripts directory to PATH."
                    ),
                )
            )
            continue

        checks.append(
            CommandCheck(
                command=command,
                status="missing",
                detail=(
                    f"{command.program!r} is not on PATH and is not importable as a "
                    "Python module. The agent will fail on this command."
                ),
            )
        )
    return checks


def _looks_like_path(program: str) -> bool:
    """`./scripts/build.sh` and `.venv/bin/activate` are files, not PATH lookups."""
    return "/" in program or "\\" in program


def _check_path_program(command: DeclaredCommand, root: Path | str | None) -> CommandCheck:
    """Resolve a path-shaped program against the repository, not PATH.

    A manifest's setup block routinely names a file that only exists once an
    earlier step has run -- `.venv/Scripts/activate` after `python -m venv`.
    Reporting that as a missing program would be noise, so its absence is
    reported as conditional rather than as a failure.
    """
    target = Path(root or ".") / command.program
    if target.exists():
        return CommandCheck(
            command=command,
            status="ok",
            detail=f"{command.program!r} exists in the repository.",
            resolved=str(target),
        )
    return CommandCheck(
        command=command,
        status="path-absent",
        detail=(
            f"{command.program!r} does not exist yet. This is often expected: a "
            "setup step usually creates it, so it only matters if an earlier "
            "command in the same block did not run."
        ),
    )


def _importable_module(program: str) -> str | None:
    """The module name behind a console script, when the script is missing.

    Console scripts and importable modules are installed together but reached
    differently: a user-site install puts the module on `sys.path` while the
    script directory stays off PATH. Only the module is checked, and it is
    never imported -- `find_spec` reads metadata.
    """
    if shutil.which(program):  # pragma: no cover - covered by resolve_all_on_path
        return None
    candidate = program.replace("-", "_")
    if not candidate.isidentifier():
        return None
    try:
        from importlib.util import find_spec

        return candidate if find_spec(candidate) is not None else None
    except (ImportError, ValueError, ModuleNotFoundError):
        return None


# ------------------------------------------------------------------ CI drift

_CI_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml")
_RUN_SCALAR = re.compile(r"^\s*(?:-\s*)?run:\s*(?!\|)(?!>)(\S.*?)\s*$")
_RUN_BLOCK = re.compile(r"^(\s*)(?:-\s*)?run:\s*[|>][-+]?\s*$")


def ci_declared_commands(root: Path | str) -> list[str]:
    """Commands the CI workflows actually run.

    A deliberately small YAML reader: it recognises `run:` in both scalar and
    block form, which is all this comparison needs, and avoids adding a YAML
    dependency to a package whose only runtime deps are typer, rich and
    pydantic.
    """
    root = Path(root)
    commands: list[str] = []
    for pattern in _CI_GLOBS:
        for workflow in sorted(root.glob(pattern)):
            text = read_text_safe(workflow)
            if text is None or not _gates_a_pull_request(text):
                continue
            commands.extend(_run_steps(text))
    return commands


def _gates_a_pull_request(text: str) -> bool:
    """Will this workflow run against a branch or pull request?

    A release workflow fires on a tag and runs `twine`, `gh release create` and
    similar. Those are not commands an agent should have been told about, and
    listing them as gaps would bury the ones that matter.
    """
    trigger = text.split("jobs:", 1)[0]
    if "pull_request" in trigger:
        return True
    return "push:" in trigger and "branches" in trigger


def _run_steps(text: str) -> list[str]:
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        scalar = _RUN_SCALAR.match(line)
        if scalar is not None:
            out.extend(_split_command_line(scalar.group(1)))
            i += 1
            continue
        block = _RUN_BLOCK.match(line)
        if block is not None:
            indent = len(block.group(1))
            i += 1
            while i < len(lines):
                body = lines[i]
                if body.strip() and (len(body) - len(body.lstrip())) <= indent:
                    break
                out.extend(_split_command_line(body))
                i += 1
            continue
        i += 1
    return out


def manifest_vs_ci(declared: Iterable[DeclaredCommand], ci: list[str]) -> list[str]:
    """CI commands no manifest mentions.

    An agent that runs everything the manifest lists, sees it pass and opens a
    pull request is still failed by whatever CI enforces and the manifest
    omits. That gap is invisible from inside the repository, and it is the
    common case: it holds for every repository checked while building this.

    Matching is on the program plus its first argument, so
    `python scripts/secret_scan.py` and `python scripts/check_docs.py` are
    different commands while incidental flag differences are not.
    """
    declared_keys = {_command_key(c.raw) for c in declared}
    missing: list[str] = []
    for command in ci:
        key = _command_key(command)
        if not key or key in declared_keys:
            continue
        if key in {_command_key(m) for m in missing}:
            continue
        missing.append(command)
    return missing


#: Ubiquitous shell utilities. A workflow step that pipes through `grep` or
#: writes a checksum with `sha256sum` is plumbing inside a larger script, not a
#: gate a manifest should have told an agent to run. Listing them would bury
#: the findings that matter under noise from every `run: |` block in the repo.
_PLUMBING = frozenset(
    {
        "awk",
        "basename",
        "cat",
        "chmod",
        "cp",
        "curl",
        "cut",
        "date",
        "diff",
        "dirname",
        "du",
        "env",
        "find",
        "grep",
        "head",
        "id",
        "jq",
        "ln",
        "ls",
        "mkdir",
        "mv",
        "printf",
        "rm",
        "sed",
        "seq",
        "sha256sum",
        "sleep",
        "sort",
        "tail",
        "tar",
        "tee",
        "touch",
        "tr",
        "uname",
        "uniq",
        "wc",
        "which",
        "xargs",
        "zip",
        "unzip",
    }
)


def _command_key(command: str) -> str:
    """Program plus first meaningful argument, for comparing two spellings.

    `python -m pip install ...` and `pip install ...` run the same tool, and a
    manifest that documents one should not be reported as omitting the other,
    so the `-m` form is normalised to the module it invokes.
    """
    raw = command.split()
    if len(raw) >= 3 and Path(raw[0]).stem in {"python", "python3", "py"} and raw[1] == "-m":
        raw = raw[2:]
    tokens = [t for t in raw if not t.startswith("-")]
    if not tokens:
        return ""

    program = tokens[0].strip("\"'").strip("()[]{};,")
    # A bare assignment, a fragment of a continued line, or a shell operator is
    # a piece of a script rather than a command. `run: |` blocks are full of
    # them, and splitting such a block per line yields plenty.
    if not program or "=" in program:
        return ""
    if not (program[0].isalnum() or program[0] in "./_"):
        return ""
    # A fragment carrying command substitution is the middle of a script line,
    # not a command with a name a manifest could have declared.
    if "$(" in command and not program[0].isalnum():
        return ""
    if program in _SHELL_BUILTINS or program in _SHELL_KEYWORDS or program in _PLUMBING:
        return ""

    if len(tokens) > 1:
        return f"{program} {tokens[1]}"
    return program
