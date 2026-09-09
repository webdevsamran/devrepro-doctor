"""Lockfiles as a requirement on the machine, not just a presence signal.

`detectors.py` recorded that a lockfile exists. That is a reproducibility
signal and nothing more. A lockfile also states a *format version*, and a
format version is a demand on the machine: npm 6 handed a `lockfileVersion: 3`
file does not fail, it rewrites the tree; cargo 1.52 cannot open a
`version = 4` `Cargo.lock`; yarn 1 cannot install from a Berry lock.

The tests below pin two properties above all: that a floor is asserted only
where one is actually published, and that an unreadable lockfile produces a
finding rather than a traceback.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from devrepro.core.models import FindingState, PlatformInfo, ToolInstallation
from devrepro.project.lockfiles import (
    LOCKFILE_PARSERS,
    LockfileFacts,
    collect_lockfile_facts,
    parse_lockfile,
)
from devrepro.rules.base import PACK_NAMES, RuleContext
from devrepro.rules.packs.lockfiles import evaluate

if TYPE_CHECKING:
    from pathlib import Path

NL = chr(10)


def _platform() -> PlatformInfo:
    return PlatformInfo(os_name="Linux", os_version="1", arch="x86_64")


def _ctx(facts: list[LockfileFacts], tools: list[ToolInstallation]) -> RuleContext:
    return RuleContext(
        platform_info=_platform(),
        tools=tuple(tools),
        lockfiles=tuple(facts),
    )


def _tool(name: str, version: str | None, *, path: str = "/usr/bin/x") -> ToolInstallation:
    return ToolInstallation(name=name, version=version, exe_path=path, is_active=True)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ parsing


def test_npm_v3_requires_npm_7(tmp_path: Path) -> None:
    """The headline case: npm 6 rewrites a v3 lock instead of refusing it."""
    path = _write(
        tmp_path,
        "package-lock.json",
        json.dumps({"lockfileVersion": 3, "packages": {"": {"name": "x"}, "node_modules/a": {}}}),
    )
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.tool == "npm"
    assert facts.format_version == "3"
    assert facts.minimum_tool == ">=7"
    assert facts.entries == 1


def test_npm_v1_does_not_demand_a_modern_npm(tmp_path: Path) -> None:
    path = _write(tmp_path, "package-lock.json", json.dumps({"lockfileVersion": 1}))
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.minimum_tool == ">=5"


def test_npm_engines_are_read_from_the_root_package(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "package-lock.json",
        json.dumps(
            {"lockfileVersion": 3, "packages": {"": {"engines": {"node": ">=20"}}}},
        ),
    )
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.requires_runtime == ("node", ">=20")


def test_a_malformed_lockfile_is_a_finding_not_a_traceback(tmp_path: Path) -> None:
    path = _write(tmp_path, "package-lock.json", "{ this is not json")
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.unreadable
    assert "not valid JSON" in facts.note


def test_cargo_v4_requires_a_modern_cargo(tmp_path: Path) -> None:
    path = _write(tmp_path, "Cargo.lock", "version = 4" + NL + "[[package]]" + NL + 'name = "a"')
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.minimum_tool == ">=1.78"
    assert facts.entries == 1


def test_a_cargo_lock_without_a_version_asserts_no_floor(tmp_path: Path) -> None:
    """v1/v2 are implicit and every current cargo reads them."""
    path = _write(tmp_path, "Cargo.lock", "[[package]]" + NL + 'name = "a"')
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.minimum_tool is None
    assert "implicit" in (facts.format_version or "")


def test_poetry_lock_reports_its_python_range(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "poetry.lock",
        "[metadata]" + NL + 'lock-version = "2.0"' + NL + 'python-versions = ">=3.9,<4.0"' + NL,
    )
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.minimum_tool == ">=1.5"
    assert facts.requires_runtime == ("python", ">=3.9,<4.0")


def test_uv_lock_reports_requires_python_but_asserts_no_tool_floor(tmp_path: Path) -> None:
    """uv's lock revisions move quickly and are not a published floor.

    Reporting the format version without inventing a uv requirement is the
    honest half of the answer, and the half this module is willing to give.
    """
    path = _write(tmp_path, "uv.lock", "version = 1" + NL + 'requires-python = ">=3.11"' + NL)
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.format_version == "1"
    assert facts.minimum_tool is None
    assert facts.requires_runtime == ("python", ">=3.11")


def test_yarn_berry_is_distinguished_from_classic(tmp_path: Path) -> None:
    berry = _write(
        tmp_path,
        "yarn.lock",
        "__metadata:" + NL + "  version: 8" + NL + "  cacheKey: 10c0" + NL,
    )
    facts = parse_lockfile(berry)
    assert facts is not None
    assert facts.minimum_tool == ">=2"
    assert facts.format_version == "berry/8"


def test_yarn_classic_asserts_only_yarn_1(tmp_path: Path) -> None:
    classic = _write(tmp_path, "yarn.lock", "# yarn lockfile v1" + NL + NL + "a@^1:" + NL)
    facts = parse_lockfile(classic)
    assert facts is not None
    assert facts.format_version == "classic"
    assert facts.minimum_tool == ">=1"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [("'9.0'", ">=9"), ("'6.0'", ">=8"), ("'5.4'", ">=7"), ("'4.0'", None)],
)
def test_pnpm_lockfile_versions(tmp_path: Path, declared: str, expected: str | None) -> None:
    path = _write(tmp_path, "pnpm-lock.yaml", f"lockfileVersion: {declared}" + NL)
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.minimum_tool == expected


def test_gemfile_lock_reports_the_bundler_that_wrote_it(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "Gemfile.lock",
        "RUBY VERSION" + NL + "   ruby 3.2.2p53" + NL + NL + "BUNDLED WITH" + NL + "   2.5.6" + NL,
    )
    facts = parse_lockfile(path)
    assert facts is not None
    assert facts.produced_by == "2.5.6"
    assert facts.requires_runtime == ("ruby", "==3.2.2p53")


def test_bun_binary_lock_is_not_decoded(tmp_path: Path) -> None:
    """Guessing at a binary layout is how a diagnostic tool becomes wrong."""
    (tmp_path / "bun.lockb").write_bytes(b"\x00\x01binary")
    facts = parse_lockfile(tmp_path / "bun.lockb")
    assert facts is not None
    assert facts.format_version == "binary"
    assert facts.minimum_tool is None


def test_an_unknown_filename_is_not_a_lockfile(tmp_path: Path) -> None:
    assert parse_lockfile(_write(tmp_path, "README.md", "hi")) is None


def test_every_parser_survives_an_empty_file(tmp_path: Path) -> None:
    """Truncated lockfiles are common; none of them may raise."""
    for name in LOCKFILE_PARSERS:
        path = _write(tmp_path, name, "")
        facts = parse_lockfile(path)
        assert facts is not None, name


# ---------------------------------------------------------------- discovery


def test_nested_lockfiles_are_found_with_repo_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    _write(tmp_path / "web", "package-lock.json", json.dumps({"lockfileVersion": 3}))
    _write(tmp_path, "uv.lock", "version = 1" + NL)

    facts = collect_lockfile_facts(tmp_path)
    assert [f.path for f in facts] == ["uv.lock", "web/package-lock.json"]


def test_node_modules_is_not_walked(tmp_path: Path) -> None:
    """Every installed package carries a lockfile; none of them is the project's."""
    nested = tmp_path / "node_modules" / "left-pad"
    nested.mkdir(parents=True)
    _write(nested, "package-lock.json", json.dumps({"lockfileVersion": 1}))
    assert collect_lockfile_facts(tmp_path) == []


# --------------------------------------------------------------- rule pack


def test_the_pack_is_registered() -> None:
    assert "lockfiles" in PACK_NAMES


def test_an_old_npm_against_a_v3_lock_is_an_error() -> None:
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            format_version="3",
            minimum_tool=">=7",
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("npm", "6.14.18")]))
    assert [f.rule_id for f in findings] == ["lockfiles/tool-too-old"]
    assert findings[0].state is FindingState.ERROR
    assert findings[0].detected == "6.14.18"


def test_a_current_npm_against_a_v3_lock_passes() -> None:
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            format_version="3",
            minimum_tool=">=7",
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("npm", "11.17.0")]))
    assert [f.rule_id for f in findings] == ["lockfiles/format-supported"]
    assert findings[0].state is FindingState.PASS


def test_an_installed_but_unversioned_manager_is_not_reported_as_missing() -> None:
    """The regression that shipped for about ten minutes.

    On Windows the extensionless `npm` shell script resolved ahead of `npm.cmd`
    and answered no version, so the pack announced that npm 11 was not on PATH.
    Present-but-unversioned is a third state and has to read like one.
    """
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            format_version="3",
            minimum_tool=">=7",
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("npm", None, path="C:/nodejs/npm")]))
    assert [f.rule_id for f in findings] == ["lockfiles/format-unknown"]
    assert findings[0].state is FindingState.UNKNOWN
    assert "C:/nodejs/npm" in findings[0].summary


def test_a_missing_manager_is_a_warning_not_a_blocker() -> None:
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            format_version="3",
            minimum_tool=">=7",
        )
    ]
    findings = evaluate(_ctx(facts, []))
    assert [f.rule_id for f in findings] == ["lockfiles/manager-missing"]
    assert findings[0].state is FindingState.WARN


def test_a_format_with_no_published_floor_produces_no_format_finding() -> None:
    """Silence is the right output when the honest answer is 'unknown'."""
    facts = [
        LockfileFacts(path="uv.lock", ecosystem="python", tool="uv", format_version="1"),
    ]
    assert evaluate(_ctx(facts, [_tool("uv", "0.4.0")])) == []


def test_a_runtime_outside_the_locked_range_is_an_error() -> None:
    facts = [
        LockfileFacts(
            path="uv.lock",
            ecosystem="python",
            tool="uv",
            requires_runtime=("python", ">=3.11,<3.13"),
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("python", "3.14.0")]))
    assert [f.rule_id for f in findings] == ["lockfiles/runtime-mismatch"]
    assert findings[0].required == ">=3.11,<3.13"


def test_a_runtime_inside_the_locked_range_is_silent() -> None:
    facts = [
        LockfileFacts(
            path="uv.lock",
            ecosystem="python",
            tool="uv",
            requires_runtime=("python", ">=3.11,<3.13"),
        )
    ]
    assert evaluate(_ctx(facts, [_tool("python", "3.12.4")])) == []


def test_a_missing_runtime_is_left_to_its_own_pack() -> None:
    """One problem, one finding: the python pack already reports an absent python."""
    facts = [
        LockfileFacts(
            path="uv.lock",
            ecosystem="python",
            tool="uv",
            requires_runtime=("python", ">=3.11"),
        )
    ]
    assert evaluate(_ctx(facts, [])) == []


def test_an_unparseable_runtime_spec_reports_unknown_rather_than_guessing() -> None:
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            requires_runtime=("node", "^20 || ^22"),
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("node", "18.0.0")]))
    assert [f.rule_id for f in findings] == ["lockfiles/runtime-spec-unparseable"]
    assert findings[0].state is FindingState.UNKNOWN


def test_an_unreadable_lockfile_reaches_the_report() -> None:
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            note="is not valid JSON: Expecting value (line 1)",
            unreadable=True,
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("npm", "11.0.0")]))
    assert [f.rule_id for f in findings] == ["lockfiles/unreadable"]


def test_every_finding_carries_evidence() -> None:
    """The project's own invariant: a finding without evidence is invalid."""
    facts = [
        LockfileFacts(
            path="package-lock.json",
            ecosystem="node",
            tool="npm",
            format_version="3",
            minimum_tool=">=7",
            requires_runtime=("node", ">=22"),
        )
    ]
    findings = evaluate(_ctx(facts, [_tool("npm", "6.0.0"), _tool("node", "18.0.0")]))
    assert len(findings) == 2
    for finding in findings:
        assert finding.evidence
        assert finding.evidence[0].path == "package-lock.json"
