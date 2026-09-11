"""The documented exit codes must match the ones the code defines.

Every project in this family calls its exit codes a public contract -- CI
gates and onboarding scripts branch on them, so a code that changes meaning
breaks something silently, somewhere else. A *document* that disagrees with the
code is worse than no document, because wrappers get written from the document.

Checking this is cheap, so it is checked.
"""

from __future__ import annotations

import re
from pathlib import Path

from devrepro.core.exit_codes import ExitCode

_ROOT = Path(__file__).resolve().parent.parent
# Spelled exactly as git tracks it. This repo's file is EXIT-CODES.md and
# mkdocs.yml references that name; a lowercase path resolves on Windows and
# fails on Linux, which is how it reached CI green locally and red there.
_DOC = _ROOT / "docs" / "EXIT-CODES.md"


def _documented() -> dict[int, str]:
    rows = re.findall(
        r"^\|\s*`(\d+)`\s*\|\s*`([^`]+)`\s*\|", _DOC.read_text(encoding="utf-8"), re.M
    )
    return {int(code): name for code, name in rows}


def _defined() -> dict[int, str]:
    src = (_ROOT / "devrepro/core/exit_codes.py").read_text(encoding="utf-8")
    return {
        int(m.group(2)): m.group(1) for m in re.finditer(r"^\s{4}([A-Z_]+)\s*=\s*(\d+)", src, re.M)
    }


def test_every_defined_code_is_documented() -> None:
    documented, defined = _documented(), _defined()
    missing = sorted(set(defined) - set(documented))
    assert not missing, f"exit codes defined in code but absent from docs/exit-codes.md: {missing}"


def test_no_documented_code_is_invented() -> None:
    documented, defined = _documented(), _defined()
    extra = sorted(set(documented) - set(defined))
    assert not extra, f"docs/exit-codes.md documents codes the code does not define: {extra}"


def test_each_code_is_documented_with_its_real_name() -> None:
    documented, defined = _documented(), _defined()
    wrong = {
        code: (documented[code], defined[code])
        for code in sorted(set(documented) & set(defined))
        if documented[code] != defined[code]
    }
    assert not wrong, f"docs name codes differently from the code: {wrong}"


def test_the_cross_project_warning_is_present() -> None:
    """The collision is the reason this document exists.

    Only `0` means the same thing across the four sibling projects. In
    devrepro-doctor `1` means the machine is usable; elsewhere it means
    failure. A wrapper treating non-zero as failure blocks a successful run.
    """
    text = _DOC.read_text(encoding="utf-8")
    assert "If you use more than one of these tools" in text
    assert "devrepro-doctor" in text


def test_an_unexpected_crash_reports_internal_error_not_a_warning() -> None:
    """3 has to be reachable, or it is documentation for a state that cannot occur.

    An unhandled exception reached the interpreter, which exits 1 -- and 1 is
    READY_WITH_WARNINGS here. A crash announced itself to CI as a successful run
    with some notes, which is the `ci-diff` defect generalised: fixing that crash
    fixed one command, and nothing made a crash *say* it was a crash. `devrepro
    bundle` raising `AttributeError` and exiting 1 is how it came back.
    """
    import subprocess
    import sys

    crash = (
        "from devrepro.cli import app as m"
        + chr(10)
        + "def boom():"
        + chr(10)
        + "    raise RuntimeError('deliberate')"
        + chr(10)
        + "m.app = boom"
        + chr(10)
        + "m.main()"
        + chr(10)
    )
    finished = subprocess.run(  # noqa: S603 - the argument is this file's own literal
        [sys.executable, "-c", crash],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        timeout=120,
        check=False,
    )
    assert finished.returncode == ExitCode.INTERNAL_ERROR
    # Printed, not swallowed: a diagnostics tool that hides its own stack trace
    # is worse than one that crashes loudly.
    assert "deliberate" in finished.stderr
