"""When the editor and the formatter disagree, and CI settles it badly.

`.editorconfig` tells the editor to indent with two spaces. Prettier is
configured for four. Somebody edits a file, their editor does what
`.editorconfig` says, the pre-commit formatter rewrites it, and the diff is
forty lines of whitespace on a two-line change. Nobody notices the cause,
because both tools are behaving exactly as configured -- and the person who
notices the symptom is a reviewer, not the person who caused it.

The `end_of_line` variant is worse because it interacts with git. A repository
with `end_of_line = lf` and a developer with `core.autocrlf = true` produces
files that look modified the instant they are checked out, and the usual
response is to disable `.editorconfig` support rather than to find the pair.

This compares declarations only. No file is reformatted, nothing runs, and the
comparison is between what each tool has been *told* -- which is where the
disagreement lives.

Deliberately narrow. Only the three settings that both sides genuinely model
are compared: indent style, indent width, and line length. `.editorconfig` has
many more, and inventing a mapping from `insert_final_newline` onto four
different formatters' notions of the same idea would produce findings that are
technically correct and useless.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "COMPARED_SETTINGS",
    "FormatterConfig",
    "StyleConflict",
    "compare_styles",
    "read_editorconfig",
    "read_prettier",
    "read_ruff",
]

#: The settings both sides model the same way. Everything else in
#: `.editorconfig` is deliberately not compared -- see the module docstring.
COMPARED_SETTINGS: tuple[str, ...] = ("indent_style", "indent_size", "max_line_length")


@dataclass(frozen=True)
class FormatterConfig:
    """One tool's declared style, normalised onto the shared vocabulary."""

    tool: str
    source: str
    indent_style: str | None = None
    indent_size: int | None = None
    max_line_length: int | None = None

    def get(self, setting: str) -> object:
        return getattr(self, setting, None)


_SECTION = re.compile(r"^\s*\[(?P<glob>.+)\]\s*$")
_SETTING = re.compile(r"^\s*(?P<key>[A-Za-z_]+)\s*=\s*(?P<value>.+?)\s*$")


def read_editorconfig(path: Path) -> FormatterConfig | None:
    """The `[*]` section of an `.editorconfig`.

    Only the catch-all section. A per-glob override is a deliberate exception
    and comparing it against a formatter's global setting would report a
    conflict where somebody has already thought about it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    in_star = False
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        section = _SECTION.match(line)
        if section:
            in_star = section.group("glob").strip() == "*"
            continue
        if not in_star:
            continue
        setting = _SETTING.match(line)
        if setting:
            values[setting.group("key").lower()] = setting.group("value").strip().strip("\"'")

    if not values:
        return None
    return FormatterConfig(
        tool="editorconfig",
        source=".editorconfig",
        indent_style=values.get("indent_style"),
        indent_size=_as_int(values.get("indent_size")),
        max_line_length=_as_int(values.get("max_line_length")),
    )


def _as_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        # `indent_size = tab` is legal and is not a width.
        return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_prettier(root: Path) -> FormatterConfig | None:
    """Prettier's declared style, from a config file or `package.json`.

    Prettier's defaults are deliberately **not** filled in. A project that has
    not configured a width has not disagreed with anything; reporting its
    default 80 as a conflict with `.editorconfig` would be inventing an opinion
    on the project's behalf.
    """
    for name in (".prettierrc", ".prettierrc.json", "prettier.config.json"):
        payload = _load_json(root / name)
        if payload:
            return _prettier_from(payload, name)

    package = _load_json(root / "package.json")
    prettier = package.get("prettier")
    if isinstance(prettier, dict):
        return _prettier_from(prettier, "package.json")
    return None


def _prettier_from(payload: dict[str, Any], source: str) -> FormatterConfig:
    use_tabs = payload.get("useTabs")
    return FormatterConfig(
        tool="prettier",
        source=source,
        indent_style=("tab" if use_tabs else "space") if use_tabs is not None else None,
        indent_size=payload.get("tabWidth") if isinstance(payload.get("tabWidth"), int) else None,
        max_line_length=(
            payload.get("printWidth") if isinstance(payload.get("printWidth"), int) else None
        ),
    )


def read_ruff(root: Path) -> FormatterConfig | None:
    """Ruff's declared style, from `ruff.toml` or `pyproject.toml`."""
    for name in ("ruff.toml", ".ruff.toml"):
        path = root / name
        if path.is_file():
            try:
                payload = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            return _ruff_from(payload, name)

    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    tool = payload.get("tool")
    ruff = tool.get("ruff") if isinstance(tool, dict) else None
    if not isinstance(ruff, dict):
        return None
    return _ruff_from(ruff, "pyproject.toml")


def _ruff_from(payload: dict[str, Any], source: str) -> FormatterConfig:
    formatting = payload.get("format")
    style = None
    if isinstance(formatting, dict):
        indent = formatting.get("indent-style")
        if isinstance(indent, str):
            style = "tab" if indent == "tab" else "space"
    return FormatterConfig(
        tool="ruff",
        source=source,
        indent_style=style,
        indent_size=(
            payload.get("indent-width") if isinstance(payload.get("indent-width"), int) else None
        ),
        max_line_length=(
            payload.get("line-length") if isinstance(payload.get("line-length"), int) else None
        ),
    )


@dataclass(frozen=True)
class StyleConflict:
    """Two tools told to do different things with the same file."""

    setting: str
    left: FormatterConfig
    right: FormatterConfig
    left_value: object
    right_value: object

    def describe(self) -> str:
        return (
            f"{self.setting}: {self.left.source} says {self.left_value!r}, "
            f"{self.right.source} says {self.right_value!r}"
        )


def compare_styles(configs: tuple[FormatterConfig | None, ...]) -> tuple[StyleConflict, ...]:
    """Every setting where two configured tools disagree.

    A value of `None` is "not configured" and never conflicts with anything.
    That distinction is the whole reason the readers above refuse to fill in
    defaults: a tool's default is what it does in the absence of an opinion,
    and reporting it as a disagreement puts words in the project's mouth.
    """
    present = [c for c in configs if c is not None]
    conflicts: list[StyleConflict] = []
    for setting in COMPARED_SETTINGS:
        seen: list[tuple[FormatterConfig, object]] = [
            (config, config.get(setting)) for config in present if config.get(setting) is not None
        ]
        for index, (left, left_value) in enumerate(seen):
            for right, right_value in seen[index + 1 :]:
                if left_value != right_value:
                    conflicts.append(StyleConflict(setting, left, right, left_value, right_value))
    return tuple(conflicts)
