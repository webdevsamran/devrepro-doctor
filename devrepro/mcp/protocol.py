"""A minimal MCP server, by hand, over stdio.

`docs/MCP-EXPOSURE.md` decided this: read-only commands only, never `fix`,
`serve` or `server-*`, and three things that had to be true first. All three
are addressed here and each is a property worth stating rather than a detail:

1. **The verdict travels in the payload.** A process exit code does not survive
   the boundary -- MCP returns structured content, not a status -- and this
   project's most important signal is `BLOCKED = 2`, which as `EXIT-CODES.md`
   records means something else entirely in three sibling projects. Every
   result here carries `verdict` explicitly.
2. **The report is cached with an explicit refresh.** A scan is around five
   seconds. That is fine for a CLI and far too slow for a tool call a model
   makes several times while reasoning, so the first call scans and the rest
   read the cache until someone asks for a refresh.
3. **The root is configured, not argued.** Every path a tool accepts is
   resolved against a root fixed when the server starts, and a path that
   escapes it is refused. A model deciding which directory to inspect is
   exactly the authority this must not delegate.

No MCP SDK dependency. The protocol is JSON-RPC 2.0 with three methods that
matter, and this project's runtime dependencies are typer, rich and pydantic --
it already hand-reads YAML rather than adding a parser. A server that a user
must install a second package to run is a server most people will not run.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from devrepro.core.models import ScanReport

__all__ = [
    "PROTOCOL_VERSION",
    "READ_ONLY_TOOLS",
    "REFUSED_TOOLS",
    "McpError",
    "ReportCache",
    "ServerConfig",
    "handle_request",
    "tool_definitions",
]

#: The revision this server implements. Declared rather than negotiated: a
#: client asking for something else is told what it gets, which is better than
#: pretending to support a revision whose semantics have not been read.
PROTOCOL_VERSION = "2024-11-05"

#: Commands `MCP-EXPOSURE.md` refuses, and the reason. Kept as data so the
#: refusal is testable and so the server can explain itself rather than simply
#: not listing them -- a model that asks for `fix` should learn why the answer
#: is no, not conclude the server is incomplete.
REFUSED_TOOLS: dict[str, str] = {
    "fix": (
        "`fix` executes remediations behind an explicit `--yes`, and that gate "
        "exists so a person agrees before anything above LOW risk is applied. A "
        "tool call has no person in it: the model decides to make it. Exposing "
        "this would move the confirmation from a human to a model, which is "
        "the thing the gate was built to prevent."
    ),
    "serve": "Starts a long-lived HTTP server; a tool call must not leave a process behind.",
    "server-backup": "Moves data on disk.",
    "server-restore": "Moves data on disk.",
    "init": "Writes files into the repository.",
    "generate": "Writes files into the repository.",
}


class McpError(Exception):
    """A JSON-RPC error with a code, carried to the client as one."""

    def __init__(self, code: int, message: str, *, data: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# JSON-RPC reserved codes, plus one of ours.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
#: Outside the reserved range, as the specification requires for application
#: errors. Used when a path argument escapes the configured root.
CONFINEMENT_ERROR = -32000


@dataclass
class ServerConfig:
    """What the server was started with. None of it comes from a tool call."""

    root: Path
    #: How long a scan stays usable. Five seconds of scanning per tool call
    #: would dominate a conversation; a stale answer inside one is not a
    #: meaningful risk, and a `refresh` argument exists for when it is.
    cache_seconds: float = 300.0


@dataclass
class ReportCache:
    """The last scan, and when it was taken.

    Injectable clock and scanner so the caching policy can be tested without
    waiting five minutes or running a real scan.
    """

    scanner: Callable[[Path], ScanReport]
    clock: Callable[[], float] = time.monotonic
    cache_seconds: float = 300.0
    _report: ScanReport | None = field(default=None, init=False)
    _taken_at: float | None = field(default=None, init=False)
    scans: int = field(default=0, init=False)

    def get(self, root: Path, *, refresh: bool = False) -> tuple[ScanReport, bool]:
        """The report, and whether this call produced a fresh one."""
        now = self.clock()
        fresh_enough = (
            self._report is not None
            and self._taken_at is not None
            and (now - self._taken_at) < self.cache_seconds
        )
        if fresh_enough and not refresh and self._report is not None:
            return self._report, False

        self._report = self.scanner(root)
        self._taken_at = now
        self.scans += 1
        return self._report, True


def _verdict(report: ScanReport) -> tuple[str, int]:
    """The verdict and the exit code it *would* have been.

    Both, deliberately. The verdict is what crosses the boundary intact; the
    numeric code is included because a caller wiring this into something that
    also runs the CLI needs the two to line up, and `EXIT-CODES.md` records
    that code 2 means different things across the sibling projects.
    """
    from devrepro.cli.common import exit_for

    states = {f.state.value for f in report.findings}
    code = exit_for(states)
    name = {0: "READY", 1: "READY_WITH_WARNINGS", 2: "BLOCKED"}.get(code, "UNKNOWN")
    return name, int(code)


def resolve_within(root: Path, candidate: str | None) -> Path:
    """Resolve a path argument against the configured root, or refuse it.

    The check is on the *resolved* path, so `../../etc` and a symlink both fail
    for the same reason. `MCP-EXPOSURE.md` calls this out as a prerequisite:
    `check --project` takes a path, and the server needs a configured root
    rather than trusting an argument a model chose.
    """
    base = root.resolve()
    if not candidate:
        return base
    target = (
        (base / candidate).resolve()
        if not Path(candidate).is_absolute()
        else Path(candidate).resolve()
    )
    if target != base and base not in target.parents:
        raise McpError(
            CONFINEMENT_ERROR,
            f"path {candidate!r} is outside the configured root",
            data={
                "hint": "The server was started with a root and every path is resolved "
                "against it. Restart it with a different --root to inspect elsewhere."
            },
        )
    return target


# --------------------------------------------------------------------- tools


def tool_definitions() -> list[dict[str, Any]]:
    """The tool list, in MCP's shape.

    Descriptions are written for a model choosing between them, which means
    saying what question each answers rather than what it runs.
    """
    project_arg = {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Directory within the configured root. Defaults to the root.",
            },
            "refresh": {
                "type": "boolean",
                "description": "Re-scan instead of using the cached report.",
            },
        },
        "additionalProperties": False,
    }
    return [
        {
            "name": "doctor",
            "description": (
                "What is wrong with this machine, with evidence for each finding. "
                "Read-only: it inspects the machine and changes nothing."
            ),
            "inputSchema": project_arg,
        },
        {
            "name": "check",
            "description": (
                "Does this machine meet the project's declared requirements in "
                ".devrepro.toml? Returns a verdict and the findings behind it."
            ),
            "inputSchema": project_arg,
        },
        {
            "name": "info",
            "description": "What toolchains are installed here, and at which versions.",
            "inputSchema": project_arg,
        },
        {
            "name": "which",
            "description": (
                "Which binary a given command actually resolves to, every other "
                "candidate on PATH, and why that one wins."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "Command name, e.g. python."},
                    "refresh": {"type": "boolean"},
                },
                "required": ["tool"],
                "additionalProperties": False,
            },
        },
        {
            "name": "explain",
            "description": (
                "What a rule id means, why it matters, and how to fix it. Use this "
                "when a finding's id needs expanding for a human."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"rule_id": {"type": "string"}},
                "required": ["rule_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "agent_readiness",
            "description": (
                "Whether an automated contributor can work in this repository: do "
                "the commands its AGENTS.md declares resolve here, does the manifest "
                "match what CI enforces, and what could a session reach from here."
            ),
            "inputSchema": project_arg,
        },
    ]


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    """An MCP tool result.

    The JSON goes in a text block because that is what every current client
    renders, and `structuredContent` alongside it for those that read it. The
    verdict is inside the payload either way -- prerequisite 1.
    """
    text = json.dumps(payload, indent=2, default=str)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        # An MCP result may flag itself as an error without failing the call.
        # A blocked machine is a successful answer to the question asked.
        "isError": False,
    }


def _call_tool(
    name: str, arguments: dict[str, Any], config: ServerConfig, cache: ReportCache
) -> dict[str, Any]:
    if name in REFUSED_TOOLS:
        raise McpError(
            INVALID_PARAMS,
            f"{name} is deliberately not exposed",
            data={"reason": REFUSED_TOOLS[name]},
        )

    known = {tool["name"] for tool in tool_definitions()}
    if name not in known:
        raise McpError(METHOD_NOT_FOUND, f"unknown tool {name!r}")

    refresh = bool(arguments.get("refresh", False))

    if name == "explain":
        from devrepro.rules.catalog import explain_rule

        rule_id = str(arguments.get("rule_id") or "")
        doc = explain_rule(rule_id)
        if doc is None:
            raise McpError(INVALID_PARAMS, f"no such rule id: {rule_id!r}")
        return _content({"verdict": "READY", "exit_code": 0, "rule": doc.as_dict()})

    project = resolve_within(config.root, arguments.get("project"))
    report, was_fresh = cache.get(project, refresh=refresh)
    verdict, code = _verdict(report)

    base: dict[str, Any] = {
        "verdict": verdict,
        "exit_code": code,
        "from_cache": not was_fresh,
        "scanned_at": report.created_at.isoformat(),
    }

    if name == "doctor":
        base["findings"] = [f.model_dump(mode="json") for f in report.findings]
        base["score"] = report.score.model_dump(mode="json") if report.score else None
    elif name == "check":
        actionable = [f for f in report.findings if f.state.value not in {"PASS", "INFO"}]
        base["findings"] = [f.model_dump(mode="json") for f in actionable]
        base["policy_applied"] = report.policy_applied
    elif name == "info":
        base["platform"] = report.platform.model_dump(mode="json")
        base["tools"] = [
            {"name": t.name, "version": t.version, "active": t.is_active}
            for t in report.tools
            if t.is_active
        ]
    elif name == "which":
        wanted = str(arguments.get("tool") or "").strip()
        if not wanted:
            raise McpError(INVALID_PARAMS, "`tool` is required")
        matches = [t for t in report.tools if t.name == wanted]
        base["tool"] = wanted
        base["resolves_to"] = next(
            (t.exe_path for t in matches if t.is_active), matches[0].exe_path if matches else None
        )
        base["candidates"] = [
            {
                "path": t.exe_path,
                "version": t.version,
                "active": t.is_active,
                "install_source": t.install_source,
            }
            for t in matches
        ]
    elif name == "agent_readiness":
        from devrepro.agents.manifest import (
            check_declared_commands,
            ci_declared_commands,
            discover_manifests,
            manifest_vs_ci,
        )

        # `discover_manifests` parses each file's commands already, so this
        # reads them rather than re-parsing the text.
        manifests = discover_manifests(project)
        declared = [command for manifest in manifests for command in manifest.commands]
        checks = check_declared_commands(declared, root=project)
        base["manifests"] = [m.name for m in manifests]
        base["commands"] = [
            {"command": c.command.raw, "status": c.status, "detail": c.detail} for c in checks
        ]
        base["ci_gates_not_declared"] = manifest_vs_ci(declared, ci_declared_commands(project))

    return _content(base)


# ----------------------------------------------------------------- dispatch


def handle_request(
    request: dict[str, Any], config: ServerConfig, cache: ReportCache
) -> dict[str, Any] | None:
    """Handle one JSON-RPC request, or return None for a notification.

    A notification -- a request with no `id` -- gets no response at all. Sending
    one is a protocol violation that some clients treat as a fatal error, which
    is a tedious way to discover you have implemented JSON-RPC almost right.
    """
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        raise McpError(INVALID_REQUEST, "not a JSON-RPC 2.0 request")

    method = request.get("method")
    request_id = request.get("id")
    is_notification = "id" not in request

    try:
        result = _dispatch(str(method), request.get("params") or {}, config, cache)
    except McpError as exc:
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": exc.code, "message": exc.message, "data": exc.data},
        }

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _dispatch(
    method: str, params: dict[str, Any], config: ServerConfig, cache: ReportCache
) -> dict[str, Any]:
    from devrepro import __version__

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "devrepro-doctor", "version": __version__},
            "instructions": (
                "Read-only diagnostics for the machine this server runs on. Every "
                "result carries an explicit `verdict` field; there is no exit code "
                "to read. Reports are cached for a few minutes -- pass "
                "`refresh: true` when you need a fresh scan. Paths are confined to "
                "the root the server was started with."
            ),
        }
    if method in {"notifications/initialized", "initialized"}:
        return {}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_definitions()}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise McpError(INVALID_PARAMS, "`arguments` must be an object")
        return _call_tool(name, arguments, config, cache)

    raise McpError(METHOD_NOT_FOUND, f"unknown method {method!r}")


#: Names this server will answer to, for documentation and tests.
READ_ONLY_TOOLS = tuple(tool["name"] for tool in tool_definitions())
