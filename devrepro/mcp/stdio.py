"""The stdio transport: newline-delimited JSON-RPC on stdin and stdout.

Kept apart from `protocol.py` so the dispatch logic can be tested by handing it
dictionaries. A transport that can only be exercised by spawning a process is a
transport whose error paths never get tested.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, TextIO

from devrepro.mcp.protocol import (
    PARSE_ERROR,
    McpError,
    ReportCache,
    ServerConfig,
    handle_request,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from devrepro.core.models import ScanReport

__all__ = ["serve_stdio"]


def _default_scanner(root: Path) -> ScanReport:
    from devrepro.cli.pipeline import run_scan

    return run_scan(project_dir=root)


def serve_stdio(
    root: Path,
    *,
    cache_seconds: float = 300.0,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    scanner: Callable[[Path], ScanReport] | None = None,
) -> int:
    """Read requests until stdin closes. Returns a process exit code.

    Everything the server will ever do is decided here, from arguments the
    person starting it supplied. Nothing a tool call contains can widen it.
    """
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    config = ServerConfig(root=root.resolve(), cache_seconds=cache_seconds)
    cache = ReportCache(
        scanner=scanner or _default_scanner,
        cache_seconds=cache_seconds,
    )

    for line in source:
        text = line.strip()
        if not text:
            continue
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            # A parse error has no id to answer to, which JSON-RPC covers: the
            # id is null and the client correlates it to whatever it just sent.
            _write(
                sink,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": PARSE_ERROR, "message": f"invalid JSON: {exc.msg}"},
                },
            )
            continue

        try:
            response = handle_request(request, config, cache)
        except McpError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": exc.code, "message": exc.message, "data": exc.data},
            }
        except Exception as exc:  # a crash must not take the server down
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {
                    "code": -32603,
                    "message": f"internal error: {type(exc).__name__}: {exc}",
                },
            }

        if response is not None:
            _write(sink, response)

    return 0


def _write(sink: TextIO, payload: dict[str, object]) -> None:
    sink.write(json.dumps(payload, default=str) + chr(10))
    sink.flush()
