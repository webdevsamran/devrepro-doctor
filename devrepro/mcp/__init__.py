"""MCP exposure: read-only diagnostics behind the Model Context Protocol.

`docs/MCP-EXPOSURE.md` is the decision this implements, including what it
refuses to expose and why.
"""

from devrepro.mcp.protocol import (
    PROTOCOL_VERSION,
    READ_ONLY_TOOLS,
    REFUSED_TOOLS,
    McpError,
    ReportCache,
    ServerConfig,
    handle_request,
    tool_definitions,
)
from devrepro.mcp.stdio import serve_stdio

__all__ = [
    "PROTOCOL_VERSION",
    "READ_ONLY_TOOLS",
    "REFUSED_TOOLS",
    "McpError",
    "ReportCache",
    "ServerConfig",
    "handle_request",
    "serve_stdio",
    "tool_definitions",
]
