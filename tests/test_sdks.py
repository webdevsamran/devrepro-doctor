"""Which SDKs are installed, not just which one answers first.

Two ecosystems install several side by side and select between them per
project, so the version the shell resolves is the wrong question. A machine
with .NET 9.0.101 and a `global.json` asking for 8.0.100 fails at
`dotnet build` with "A compatible .NET SDK was not found" -- while
`dotnet --version` prints 9.0.101 and every other check passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.core.models import FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.probes.base import ProbeContext
from devrepro.probes.sdks import SdkProbe, parse_dotnet_sdks, satisfies_global_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

NL = chr(10)

LIST_SDKS = (
    "6.0.428 [/usr/share/dotnet/sdk]"
    + NL
    + "8.0.404 [/usr/share/dotnet/sdk]"
    + NL
    + "9.0.101 [/usr/share/dotnet/sdk]"
    + NL
)


class ArgvRunner:
    def __init__(self, table: dict[str, CommandResult]) -> None:
        self.table = table
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        # Separators are normalised because the probe builds paths with
        # `pathlib`, which uses the *host's* separator. These tests drive a
        # synthetic Linux context from whatever machine runs them, so matching
        # on a literal `/opt/jdk17/bin/java` would pass on Linux and fail on
        # Windows for a reason that has nothing to do with the probe.
        joined = " ".join(argv).replace(chr(92), "/")
        for token, result in self.table.items():
            if token in joined:
                return result
        return CommandResult(argv, 127, "", "not found")


def probe(
    root: Path,
    table: dict[str, CommandResult] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> SdkProbe:
    ctx = ProbeContext(
        runner=ArgvRunner(table or {}),
        platform="linux",
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        project_dir=root,
        env=env if env is not None else {"PATH": "/usr/bin"},
    )
    return SdkProbe(ctx)


def ok(stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(("x",), 0, stdout, stderr)


def global_json(root: Path, body: str) -> Path:
    path = root / "global.json"
    path.write_text(body, encoding="utf-8")
    return path


def ids(root: Path, table: dict[str, CommandResult] | None = None) -> list[str]:
    return [f.rule_id for f in probe(root, table).run().findings]


# ------------------------------------------------------------------ parsing


def test_versions_are_read_and_paths_are_not() -> None:
    """`dotnet --list-sdks` prints an install path beside each version.

    On Windows that path is frequently under a user profile, and this data ends
    up in a scan report.
    """
    versions = parse_dotnet_sdks(LIST_SDKS)
    assert versions == ("6.0.428", "8.0.404", "9.0.101")
    assert not any("/" in version for version in versions)


def test_duplicate_versions_appear_once() -> None:
    doubled = LIST_SDKS + LIST_SDKS
    assert parse_dotnet_sdks(doubled) == ("6.0.428", "8.0.404", "9.0.101")


@pytest.mark.parametrize("text", ["", "no sdks found", "garbage"])
def test_unparseable_output_yields_nothing_rather_than_raising(text: str) -> None:
    assert parse_dotnet_sdks(text) == ()


# --------------------------------------------------------------- resolution


def test_an_exact_match_is_accepted() -> None:
    assert satisfies_global_json("8.0.404", ("8.0.404",), None) is True


def test_a_later_patch_in_the_same_feature_band_is_accepted() -> None:
    """.NET versions are `major.minor.feature+patch`; 8.0.1xx is one band."""
    assert satisfies_global_json("8.0.100", ("8.0.114",), None) is True


def test_a_different_feature_band_is_not_a_match_by_default() -> None:
    """8.0.100 and 8.0.404 are different bands, and an unset rollForward is exact."""
    assert satisfies_global_json("8.0.100", ("8.0.404",), None) is False


def test_a_newer_major_does_not_satisfy_a_pin_by_default() -> None:
    """The failure this whole probe exists for."""
    assert satisfies_global_json("8.0.100", ("9.0.101",), None) is False


def test_roll_forward_major_accepts_anything() -> None:
    assert satisfies_global_json("6.0.100", ("9.0.101",), "major") is True


def test_roll_forward_minor_accepts_something_newer() -> None:
    assert satisfies_global_json("8.0.100", ("8.1.200",), "minor") is True


def test_roll_forward_minor_does_not_accept_something_older() -> None:
    assert satisfies_global_json("8.0.400", ("8.0.100",), "minor") is False


def test_disable_is_as_strict_as_no_policy() -> None:
    assert satisfies_global_json("8.0.100", ("9.0.101",), "disable") is False


def test_an_unrecognised_policy_errs_toward_permissive() -> None:
    """A missing finding beats blocking a build that works.

    `rollForward` has eight documented policies; this models the three that
    decide the common cases. Guessing restrictively on the rest would report a
    machine as unable to build something it builds fine.
    """
    assert satisfies_global_json("8.0.100", ("9.0.101",), "someFuturePolicy") is True


def test_no_installed_sdks_satisfies_nothing() -> None:
    assert satisfies_global_json("8.0.100", (), "major") is False


# ------------------------------------------------------------------ findings


def test_a_pinned_sdk_that_is_not_installed_blocks(tmp_path: Path) -> None:
    global_json(tmp_path, '{"sdk": {"version": "8.0.100"}}')
    findings = probe(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)}).run().findings

    match = next(f for f in findings if f.rule_id == "dotnet/global-json-sdk-missing")
    assert match.state is FindingState.BLOCKED
    assert "9.0.101" in match.summary
    assert "compatible .NET SDK was not found" in (match.remediation_hint or "")


def test_a_satisfied_pin_is_recorded_as_a_pass(tmp_path: Path) -> None:
    global_json(tmp_path, '{"sdk": {"version": "9.0.101"}}')
    assert "dotnet/global-json-satisfied" in ids(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)})


def test_roll_forward_is_honoured_from_the_file(tmp_path: Path) -> None:
    global_json(tmp_path, '{"sdk": {"version": "6.0.100", "rollForward": "latestMajor"}}')
    assert "dotnet/global-json-satisfied" in ids(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)})


def test_no_global_json_means_nothing_to_say(tmp_path: Path) -> None:
    assert ids(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)}) == []


def test_a_global_json_without_an_sdk_pin_says_nothing(tmp_path: Path) -> None:
    global_json(tmp_path, '{"msbuild-sdks": {"x": "1.0"}}')
    assert ids(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)}) == []


def test_an_unparseable_global_json_is_left_to_the_detector(tmp_path: Path) -> None:
    """`detect_requirements` already reports it; two findings for one problem."""
    global_json(tmp_path, "{ not json")
    assert ids(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)}) == []


def test_a_pin_with_no_dotnet_installed_is_unknown_not_blocked(tmp_path: Path) -> None:
    """Whether the pinned SDK is present is genuinely unknown without dotnet."""
    global_json(tmp_path, '{"sdk": {"version": "8.0.100"}}')
    findings = probe(tmp_path, {}).run().findings

    match = next(f for f in findings if f.rule_id == "dotnet/sdk-list-unavailable")
    assert match.state is FindingState.UNKNOWN


# ---------------------------------------------------------------------- java


def test_java_home_disagreeing_with_path_is_reported(tmp_path: Path) -> None:
    """Maven uses JAVA_HOME; a shell script calling `java` uses PATH."""
    table = {
        "/opt/jdk17/bin/java -version": ok("", 'openjdk version "17.0.9" 2023-10-17'),
        "java -version": ok("", 'openjdk version "21.0.1" 2023-10-17'),
    }
    findings = (
        probe(tmp_path, table, env={"PATH": "/usr/bin", "JAVA_HOME": "/opt/jdk17"}).run().findings
    )

    match = next(f for f in findings if f.rule_id == "java/home-path-mismatch")
    assert match.state is FindingState.WARN
    assert "UnsupportedClassVersionError" in (match.remediation_hint or "")


def test_java_home_agreeing_with_path_says_nothing(tmp_path: Path) -> None:
    same = ok("", 'openjdk version "21.0.1" 2023-10-17')
    table = {"/opt/jdk21/bin/java -version": same, "java -version": same}
    found = probe(tmp_path, table, env={"PATH": "/usr/bin", "JAVA_HOME": "/opt/jdk21"}).run()
    assert "java/home-path-mismatch" not in [f.rule_id for f in found.findings]


def test_no_java_home_means_no_comparison(tmp_path: Path) -> None:
    result = probe(tmp_path, {"java -version": ok("", 'openjdk version "21"')}).run()
    assert result.data["java_home_set"] is False
    assert result.data["java_home_matches_path"] is None


def test_java_version_is_read_from_stderr(tmp_path: Path) -> None:
    """`java -version` writes to stderr, which is the usual reason it reads empty."""
    table = {
        "/opt/a/bin/java -version": ok("", 'openjdk version "17.0.9"'),
        "java -version": ok("", 'openjdk version "17.0.9"'),
    }
    result = probe(tmp_path, table, env={"PATH": "/usr/bin", "JAVA_HOME": "/opt/a"}).run()
    assert result.data["java_home_matches_path"] is True


# ------------------------------------------------------------------- shape


def test_no_path_reaches_the_probe_data(tmp_path: Path) -> None:
    global_json(tmp_path, '{"sdk": {"version": "9.0.101"}}')
    data = probe(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)}).run().data
    assert data["dotnet_sdks"] == ["6.0.428", "8.0.404", "9.0.101"]
    assert "/usr/share" not in repr(data)


def test_every_finding_carries_evidence(tmp_path: Path) -> None:
    global_json(tmp_path, '{"sdk": {"version": "8.0.100"}}')
    for finding in probe(tmp_path, {"dotnet --list-sdks": ok(LIST_SDKS)}).run().findings:
        assert finding.evidence, finding.rule_id
        assert finding.component, finding.rule_id
