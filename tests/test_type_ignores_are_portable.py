"""`mypy --strict` must reach the same verdict on every machine.

An import guarded by `try: ... except ImportError` is optional by construction:
mypy sees it as missing on a machine without the package and as perfectly typed
on one with it. A bare `# type: ignore[import-not-found]` is therefore correct
on exactly one of those machines and an `unused-ignore` error on the other.

This was live. `devrepro/cli/server.py` carried five such comments for the
FastAPI extra. `mypy devrepro` passed for months, then failed the moment
something pulled `fastapi` into the environment -- with five errors in a file
nobody had touched. The `uvicorn` import three lines below already had the
right pattern, which is how the shape of the fix was obvious and how easy it
was to miss in the first place.

The project's own README calls this class of problem "works on my machine".
A type-check that depends on which optional packages happen to be installed is
exactly that, in the gate meant to prevent it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

#: Error codes mypy only raises when a module is *absent* (or untyped), so the
#: ignore is unused whenever it is present. `unused-ignore` must accompany them.
_CONDITIONAL_CODES = ("import-not-found", "import-untyped", "untyped-decorator")

_IGNORE = re.compile(r"#\s*type:\s*ignore\[([^\]]+)\]")


def _sources() -> list[Path]:
    return [
        path
        for path in sorted((_ROOT / "devrepro").rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def test_there_are_sources_to_check() -> None:
    """A scan that finds nothing passes the test below without checking anything."""
    assert len(_sources()) > 50


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_conditional_type_ignores_also_carry_unused_ignore(path: Path) -> None:
    offenders: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = _IGNORE.search(line)
        if not match:
            continue
        codes = {code.strip() for code in match.group(1).split(",")}
        if codes & set(_CONDITIONAL_CODES) and "unused-ignore" not in codes:
            relative = path.relative_to(_ROOT).as_posix()
            offenders.append(f"{relative}:{number}: {line.strip()}")

    assert offenders == [], (
        "These ignores are correct only on a machine where the module is absent. "
        "Add `unused-ignore` so mypy agrees on every machine and every CI leg:"
        + chr(10)
        + chr(10).join("  " + o for o in offenders)
    )
