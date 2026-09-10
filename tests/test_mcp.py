"""MCP exposure, and the three things `MCP-EXPOSURE.md` made prerequisites.

That document is the specification: read-only commands only, never `fix`,
`serve` or `server-*`, and three properties that had to be true before any of
it shipped. Each has a test here, because each is a property of the boundary
rather than of any one tool, and a boundary is where the invariants either hold
or quietly stop holding.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from devrepro.core.models import Evidence, Finding, FindingState, PlatformInfo, ScanReport
from devrepro.mcp import serve_stdio
from devrepro.mcp.protocol import (
    CONFINEMENT_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    REFUSED_TOOLS,
    McpError,
    ReportCache,
    ServerConfig,
    handle_request,
    resolve_within,
    tool_definitions,
)

if TYPE_CHECKING:
    from pathlib import Path

NL = chr(10)


def report(findings: tuple[Finding, ...] = ()) -> ScanReport:
    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.0.0",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        platform=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        findings=tuple(findings),
        tools=(),
        requirements=(),
        probe_errors=(),
    )


def finding(state: FindingState, rule_id: str = "x/y") -> Finding:
    return Finding(
        rule_id=rule_id,
        state=state,
        summary="something",
        evidence=(Evidence(source="system", excerpt="x"),),
    )


class CountingScanner:
    def __init__(self, result: ScanReport | None = None) -> None:
        self.result = result or report()
        self.calls = 0

    def __call__(self, root: Path) -> ScanReport:
        self.calls += 1
        return self.result


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def call(name: str, arguments: dict | None = None, *, root: Path, scanner=None, cache=None):
    config = ServerConfig(root=root)
    cache = cache or ReportCache(scanner=scanner or CountingScanner())
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    return handle_request(request, config, cache)


# ------------------------------------------- prerequisite 1: the verdict


def test_every_tool_result_carries_a_verdict(tmp_path: Path) -> None:
    """An exit code does not survive the boundary.

    MCP returns structured content, not a process status, and this project's
    most important signal is `BLOCKED = 2` -- which `EXIT-CODES.md` records as
    meaning something else entirely in three sibling projects.
    """
    scanner = CountingScanner(report([finding(FindingState.BLOCKED)]))
    response = call("doctor", root=tmp_path, scanner=scanner)

    payload = response["result"]["structuredContent"]
    assert payload["verdict"] == "BLOCKED"
    assert payload["exit_code"] == 2


@pytest.mark.parametrize(
    ("state", "verdict"),
    [
        (FindingState.PASS, "READY"),
        (FindingState.WARN, "READY_WITH_WARNINGS"),
        (FindingState.ERROR, "BLOCKED"),
        (FindingState.BLOCKED, "BLOCKED"),
    ],
)
def test_the_verdict_matches_the_exit_code_contract(
    tmp_path: Path, state: FindingState, verdict: str
) -> None:
    scanner = CountingScanner(report([finding(state)]))
    payload = call("doctor", root=tmp_path, scanner=scanner)["result"]["structuredContent"]
    assert payload["verdict"] == verdict


def test_a_blocked_machine_is_a_successful_call(tmp_path: Path) -> None:
    """`isError` means the tool failed, not that the answer was bad news."""
    scanner = CountingScanner(report([finding(FindingState.BLOCKED)]))
    assert call("doctor", root=tmp_path, scanner=scanner)["result"]["isError"] is False


# --------------------------------------------- prerequisite 2: the cache


def test_the_second_call_does_not_re_scan(tmp_path: Path) -> None:
    """A five-second scan per tool call would dominate a conversation."""
    scanner = CountingScanner()
    cache = ReportCache(scanner=scanner, clock=FakeClock())

    call("doctor", root=tmp_path, cache=cache)
    second = call("info", root=tmp_path, cache=cache)

    assert scanner.calls == 1
    assert second["result"]["structuredContent"]["from_cache"] is True


def test_refresh_forces_a_new_scan(tmp_path: Path) -> None:
    scanner = CountingScanner()
    cache = ReportCache(scanner=scanner, clock=FakeClock())

    call("doctor", root=tmp_path, cache=cache)
    second = call("doctor", {"refresh": True}, root=tmp_path, cache=cache)

    assert scanner.calls == 2
    assert second["result"]["structuredContent"]["from_cache"] is False


def test_the_cache_expires(tmp_path: Path) -> None:
    scanner = CountingScanner()
    clock = FakeClock()
    cache = ReportCache(scanner=scanner, clock=clock, cache_seconds=60.0)

    call("doctor", root=tmp_path, cache=cache)
    clock.now = 61.0
    call("doctor", root=tmp_path, cache=cache)

    assert scanner.calls == 2


def test_the_result_says_whether_it_was_cached(tmp_path: Path) -> None:
    """A caller reasoning about staleness needs to know, not guess."""
    cache = ReportCache(scanner=CountingScanner(), clock=FakeClock())
    first = call("doctor", root=tmp_path, cache=cache)["result"]["structuredContent"]
    assert first["from_cache"] is False
    assert "scanned_at" in first


# ---------------------------------------- prerequisite 3: confinement


def test_a_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    """Which directory to inspect is authority this must not delegate."""
    response = call("doctor", {"project": "../.."}, root=tmp_path)
    assert response["error"]["code"] == CONFINEMENT_ERROR


def test_an_absolute_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    other = tmp_path.parent / "somewhere-else"
    other.mkdir(exist_ok=True)
    response = call("doctor", {"project": str(other)}, root=tmp_path)
    assert response["error"]["code"] == CONFINEMENT_ERROR


def test_a_path_inside_the_root_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "packages" / "api").mkdir(parents=True)
    resolved = resolve_within(tmp_path, "packages/api")
    assert resolved == (tmp_path / "packages" / "api").resolve()


def test_the_check_is_on_the_resolved_path(tmp_path: Path) -> None:
    """So `a/../../..` fails for the same reason `../../..` does."""
    (tmp_path / "a").mkdir()
    with pytest.raises(McpError):
        resolve_within(tmp_path, "a/../../../etc")


def test_no_argument_means_the_root(tmp_path: Path) -> None:
    assert resolve_within(tmp_path, None) == tmp_path.resolve()


# ------------------------------------------------------------- refusals


@pytest.mark.parametrize("name", sorted(REFUSED_TOOLS))
def test_refused_tools_are_refused_with_a_reason(tmp_path: Path, name: str) -> None:
    """A model that asks for `fix` should learn why, not conclude it is missing."""
    response = call(name, root=tmp_path)
    assert response["error"]["code"] == INVALID_PARAMS
    assert response["error"]["data"]["reason"]


def test_fix_is_refused_and_the_reason_names_the_gate(tmp_path: Path) -> None:
    response = call("fix", root=tmp_path)
    reason = response["error"]["data"]["reason"]
    assert "--yes" in reason
    assert "no person in it" in reason


def test_no_refused_tool_appears_in_the_listing() -> None:
    listed = {tool["name"] for tool in tool_definitions()}
    assert listed.isdisjoint(REFUSED_TOOLS)


def test_an_unknown_tool_is_a_method_error(tmp_path: Path) -> None:
    assert call("nonsense", root=tmp_path)["error"]["code"] == METHOD_NOT_FOUND


# -------------------------------------------------------------- protocol


def test_initialize_declares_the_protocol_version(tmp_path: Path) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ServerConfig(root=tmp_path),
        ReportCache(scanner=CountingScanner()),
    )
    result = response["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "devrepro-doctor"
    assert "verdict" in result["instructions"]


def test_a_notification_gets_no_response(tmp_path: Path) -> None:
    """Answering one is a protocol violation some clients treat as fatal."""
    response = handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ServerConfig(root=tmp_path),
        ReportCache(scanner=CountingScanner()),
    )
    assert response is None


def test_a_notification_that_errors_still_gets_no_response(tmp_path: Path) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "method": "nonsense/method"},
        ServerConfig(root=tmp_path),
        ReportCache(scanner=CountingScanner()),
    )
    assert response is None


def test_every_tool_has_a_schema_and_a_description() -> None:
    for tool in tool_definitions():
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"
        # `additionalProperties: false` so a client sending a stray argument
        # learns about it rather than having it silently ignored.
        assert tool["inputSchema"]["additionalProperties"] is False


def test_explain_answers_from_the_rule_catalogue(tmp_path: Path) -> None:
    payload = call("explain", {"rule_id": "containers/cgroup-v1"}, root=tmp_path)["result"][
        "structuredContent"
    ]
    assert payload["rule"]["rule_id"] == "containers/cgroup-v1"
    assert payload["rule"]["fix"]


def test_explain_on_an_unknown_id_is_an_error(tmp_path: Path) -> None:
    assert call("explain", {"rule_id": "no/such"}, root=tmp_path)["error"]["code"] == INVALID_PARAMS


def test_which_reports_every_candidate(tmp_path: Path) -> None:
    from devrepro.core.models import ToolInstallation

    scan = report()
    scan = scan.model_copy(
        update={
            "tools": (
                ToolInstallation(
                    name="python", version="3.12.4", exe_path="/a/python", is_active=True
                ),
                ToolInstallation(
                    name="python", version="3.11.9", exe_path="/b/python", is_active=False
                ),
            )
        }
    )
    payload = call("which", {"tool": "python"}, root=tmp_path, scanner=CountingScanner(scan))[
        "result"
    ]["structuredContent"]

    assert payload["resolves_to"] == "/a/python"
    assert len(payload["candidates"]) == 2


# -------------------------------------------------------------- transport


def drive(requests: list[dict], root: Path, scanner=None) -> list[dict]:
    stdin = io.StringIO(NL.join(json.dumps(r) for r in requests))
    stdout = io.StringIO()
    serve_stdio(root, stdin=stdin, stdout=stdout, scanner=scanner or CountingScanner())
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_the_transport_answers_a_session(tmp_path: Path) -> None:
    responses = drive(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "info"}},
        ],
        tmp_path,
    )

    # Three requests, one notification: three responses.
    assert [r["id"] for r in responses] == [1, 2, 3]
    assert len(responses[1]["result"]["tools"]) >= 5


def test_malformed_json_does_not_end_the_session(tmp_path: Path) -> None:
    """A client that sends one bad line keeps its server."""
    stdin = io.StringIO("not json" + NL + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}))
    stdout = io.StringIO()
    serve_stdio(tmp_path, stdin=stdin, stdout=stdout, scanner=CountingScanner())

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == PARSE_ERROR
    assert lines[1]["id"] == 7


def test_a_crash_in_one_call_does_not_end_the_session(tmp_path: Path) -> None:
    def explode(root: Path) -> ScanReport:
        raise RuntimeError("deliberate")

    responses = drive(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "info"}},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ],
        tmp_path,
        scanner=explode,
    )

    assert "deliberate" in responses[0]["error"]["message"]
    assert responses[1]["id"] == 2


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    stdin = io.StringIO(NL + NL + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + NL)
    stdout = io.StringIO()
    serve_stdio(tmp_path, stdin=stdin, stdout=stdout, scanner=CountingScanner())
    assert len(stdout.getvalue().strip().splitlines()) == 1
