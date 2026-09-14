"""Tests for renderers, score, exporters, plugins and CLI commands.

All inputs are synthetic; nothing here touches the real machine beyond
read-only PATH lookups.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from devrepro.cli.app import app
from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import (
    DiffClassification,
    EnvironmentDiff,
    Evidence,
    Finding,
    FindingState,
    PlatformInfo,
    ScanReport,
)
from devrepro.exporters.base import FileExporter
from devrepro.plugins.loader import list_plugins
from devrepro.reports.renderers import (
    render_diff_html,
    render_diff_json,
    render_diff_markdown,
    render_html,
    render_json,
    render_junit,
    render_markdown,
)
from devrepro.rules.score import compute_score
from typer.testing import CliRunner

runner = CliRunner()


def _report() -> ScanReport:
    return ScanReport(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="TestOS", os_version="1.0", arch="x86_64"),
        findings=(
            Finding(
                rule_id="python/version-ok",
                state=FindingState.PASS,
                summary="python 3.12 satisfies >=3.11.",
                evidence=(
                    Evidence(source="command", command=("python", "--version"), excerpt="ok"),
                ),
                detected="3.12",
                required=">=3.11",
                component="python",
            ),
            Finding(
                rule_id="docker/daemon-down",
                state=FindingState.BLOCKED,
                summary="Docker daemon unreachable.",
                evidence=(Evidence(source="command", command=("docker", "info"), excerpt="err"),),
                component="docker",
                remediation_hint="Start Docker Desktop.",
            ),
        ),
        probe_errors=("virt/wsl: unsupported on this platform",),
    )


def _diff() -> EnvironmentDiff:
    return EnvironmentDiff(
        a_snapshot_id="aaaa",
        b_snapshot_id="bbbb",
        entries=(
            _entry(DiffClassification.VERSION_DRIFT, "tool", "node", "20.1", "22.0"),
            _entry(DiffClassification.MISSING, "tool", "go", None, "1.21"),
        ),
    )


def _entry(cls: DiffClassification, comp: str, name: str, a: str | None, b: str | None):
    from devrepro.core.models import DiffEntry

    return DiffEntry(component=comp, name=name, classification=cls, a_value=a, b_value=b)


# ------------------------------------------------------------------ renderers


def test_render_json_roundtrip() -> None:
    payload = json.loads(render_json(_report()))
    assert payload["platform"]["os_name"] == "TestOS"
    assert len(payload["findings"]) == 2
    assert payload["privacy"]["redacted"] is True


def test_render_markdown_contains_sections() -> None:
    md = render_markdown(_report())
    assert "# DevRepro Doctor report" in md
    assert "`python/version-ok`" in md
    assert "**Remediation:** Start Docker Desktop." in md
    assert "Probe errors" in md


def test_render_junit_is_valid_xml() -> None:
    root = ET.fromstring(render_junit(_report()))  # noqa: S314 - trusted local XML
    assert root.tag == "testsuite"
    cases = root.findall("testcase")
    assert len(cases) == 2
    failures = root.findall(".//failure")
    assert len(failures) == 1


def test_render_html_escapes_and_includes_badges() -> None:
    html = render_html(_report())
    assert "class='badge BLOCKED'" in html
    assert "DevRepro Doctor" in html


def test_diff_renderers() -> None:
    d = _diff()
    dj = json.loads(render_diff_json(d))
    assert dj["a_snapshot_id"] == "aaaa"
    dm = render_diff_markdown(d)
    assert "| tool | node | version-drift |" in dm
    dh = render_diff_html(d)
    assert "<table>" in dh and "version-drift" in dh


# --------------------------------------------------------------------- score


def test_compute_score_explains_points(tmp_path: Path) -> None:
    nl = chr(10)
    toml = nl.join(["[project]", 'name = "x"', 'requires-python = ">=3.11"', ""])
    (tmp_path / "pyproject.toml").write_text(toml, encoding="utf-8")
    score = compute_score(tmp_path, [])
    assert score.possible > 0
    assert all(p.explanation for p in score.points)
    assert score.total <= score.possible


# ----------------------------------------------------------------- exporters


def test_file_exporter_writes_files(tmp_path: Path) -> None:
    exporter = FileExporter(tmp_path / "out")
    loc = exporter.export("hello", filename="report.md")
    assert Path(loc).is_file()
    assert Path(loc).read_text(encoding="utf-8") == "hello"


# ------------------------------------------------------------------- plugins


def test_list_plugins_returns_groups() -> None:
    found = list_plugins()
    assert isinstance(found, dict)
    assert "devrepro.probes" in found


# ----------------------------------------------------------------------- CLI


def test_cli_rules_json() -> None:
    result = runner.invoke(app, ["rules", "--json"])
    assert result.exit_code == 0
    packs = json.loads(result.output)["packs"]
    assert "python" in packs and "ai-gpu" in packs


def test_cli_self_test() -> None:
    result = runner.invoke(app, ["self-test", "--json"])
    assert result.exit_code == 0
    checks = json.loads(result.output)
    assert set(checks.values()) == {"ok"}


def test_cli_project_on_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures" / "manifests" / "python-project"
    result = runner.invoke(app, ["project", str(fixture), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any(r["ecosystem"] == "python" for r in data["requirements"])


def test_cli_report_renders_markdown(tmp_path: Path) -> None:
    src = tmp_path / "report.json"
    src.write_text(render_json(_report()), encoding="utf-8")
    out = tmp_path / "out.md"
    result = runner.invoke(app, ["report", str(src), "--format", "markdown", "-o", str(out)])
    assert result.exit_code == 0
    assert out.is_file()
    assert "DevRepro Doctor report" in out.read_text(encoding="utf-8")


def test_cli_export_all_formats(tmp_path: Path) -> None:
    src = tmp_path / "report.json"
    src.write_text(render_json(_report()), encoding="utf-8")
    out_dir = tmp_path / "exported"
    result = runner.invoke(app, ["export", str(src), "--out-dir", str(out_dir)])
    assert result.exit_code == 0
    names = {p.name for p in out_dir.iterdir()}
    assert {"report.json", "report.md", "report.junit.xml", "report.html"} <= names


@pytest.mark.parametrize(
    ("fmt", "marker"),
    [("json", '"findings"'), ("markdown", "# DevRepro"), ("html", "<!doctype html>")],
)
def test_cli_scan_formats(tmp_path: Path, fmt: str, marker: str) -> None:
    out = tmp_path / f"scan.{fmt}"
    result = runner.invoke(app, ["scan", "--format", fmt, "-o", str(out)])
    # scan runs real read-only probes; exit code reflects findings, not failure
    assert result.exit_code in (0, 1, 2)
    if out.is_file():
        assert marker in out.read_text(encoding="utf-8")


def _snapshot_json() -> str:
    """A snapshot, which is the file people hand `report` by mistake.

    Both are JSON, both come out of this tool, and `snapshot` is the
    better-known command. `ScanReport` forbids extra fields, so this used to
    fail with three `extra_forbidden` errors and a link to the pydantic
    documentation -- which explains that `compilers` is not permitted, and says
    nothing about which command produces the file the reader wanted.
    """
    payload = json.loads(render_json(_report()))
    payload["compilers"] = []
    payload["virtualenvs"] = []
    payload["requirements_fingerprint"] = []
    return json.dumps(payload)


def test_report_on_a_snapshot_names_the_file_and_the_right_command(tmp_path: Path) -> None:
    src = tmp_path / "a.json"
    src.write_text(_snapshot_json(), encoding="utf-8")

    result = runner.invoke(app, ["report", str(src)])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "is a snapshot, not a scan report" in result.output
    assert "devrepro scan -o report.json" in result.output
    assert "pydantic" not in result.output


def test_report_on_something_that_is_not_json_at_all(tmp_path: Path) -> None:
    src = tmp_path / "notes.json"
    src.write_text("not json", encoding="utf-8")

    result = runner.invoke(app, ["report", str(src)])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "not readable JSON" in result.output


def test_report_on_json_that_is_neither_says_what_is_wrong(tmp_path: Path) -> None:
    src = tmp_path / "other.json"
    src.write_text('{"hello": "world"}', encoding="utf-8")

    result = runner.invoke(app, ["report", str(src)])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "is not a scan report" in result.output


def test_export_copies_a_snapshot_rather_than_failing_to_render_it(tmp_path: Path) -> None:
    """`export` accepts reports and snapshots alike, by its own docstring.

    It chose between them with `'"findings"' in raw`, which a snapshot also
    satisfies -- so a snapshot took the report branch and raised the same
    validation error.
    """
    src = tmp_path / "a.json"
    src.write_text(_snapshot_json(), encoding="utf-8")
    out_dir = tmp_path / "exported"

    result = runner.invoke(app, ["export", str(src), "--out-dir", str(out_dir)])

    assert result.exit_code == ExitCode.READY
    assert (out_dir / "a.json").is_file()


def test_sign_snapshot_without_a_key_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`verify-snapshot` has always handled this; `sign-snapshot` did not.

    Running the pair in sequence answered the same missing environment variable
    twice in two different languages: one sentence naming the variable, and one
    traceback through typer's internals ending in that same sentence.
    """
    monkeypatch.delenv("DEVREPRO_SIGNING_KEY", raising=False)
    src = tmp_path / "a.json"
    src.write_text(render_json(_report()), encoding="utf-8")

    result = runner.invoke(app, ["sign-snapshot", str(src)])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "DEVREPRO_SIGNING_KEY" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


# ------------------------------------------------- markdown table escaping ---


def test_a_windows_path_before_a_pipe_does_not_break_the_table() -> None:
    r"""The defect `_cell`'s own docstring described and did not prevent.

    It escaped the pipe and not the backslash, so `C:\tools\|shadowed` became
    `C:\tools\|shadowed` -- an escaped backslash followed by a live pipe. The
    cell split anyway, on exactly the value the escaping was added for. The
    same bug existed three times in the TypeScript console, where CodeQL
    flagged it; this copy was never flagged, and `report --format markdown` is
    the output people paste into an issue.
    """
    from devrepro.reports.renderers import _cell

    backslash = chr(92)
    escaped = _cell(f"C:{backslash}tools{backslash}|shadowed")

    # Every pipe in the output is escaped: preceded by an odd number of
    # backslashes. That is the property the table actually depends on.
    for index, character in enumerate(escaped):
        if character != "|":
            continue
        run = 0
        back = index - 1
        while back >= 0 and escaped[back] == backslash:
            run += 1
            back -= 1
        assert run % 2 == 1, f"bare pipe at {index} in {escaped!r}"


def test_unescaping_a_cell_returns_what_went_in() -> None:
    """Escaping has to be reversible, or the reader is shown something else."""
    import re

    from devrepro.reports.renderers import _cell

    backslash = chr(92)
    original = f"C:{backslash}Users{backslash}dev{backslash}bin | shadowed"
    # Undo one level of escaping, the way a Markdown renderer does: a backslash
    # followed by any character becomes that character.
    unescaped = re.sub(r"\\(.)", r"\1", _cell(original))
    assert unescaped == original


def test_a_cell_folds_every_newline_form() -> None:
    """A row ends at a line break, so a multi-line summary ended the table.

    `\r\n` as well as `\n`: a manifest read on Windows carries carriage
    returns, and replacing only the newline left a stray `\r` in the cell.
    """
    from devrepro.reports.renderers import _cell

    assert _cell("one" + chr(10) + "two") == "one two"
    assert _cell("one" + chr(13) + chr(10) + "two") == "one two"
    assert _cell("one" + chr(13) + "two") == "one two"
    assert chr(13) not in _cell("one" + chr(13) + chr(10) + "two")


def test_a_plain_cell_is_untouched() -> None:
    from devrepro.reports.renderers import _cell

    assert _cell("node 18.19.0 does not satisfy >=20") == "node 18.19.0 does not satisfy >=20"
