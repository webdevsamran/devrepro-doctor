"""Localhost-only server for sanitized scan/report data + frontend.

Binds to 127.0.0.1 by default and refuses non-loopback bind addresses.
No telemetry, no cloud upload, ever.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import socket
from pathlib import Path

from devrepro.core.errors import DevReproError

__all__ = ["serve"]


class ServeError(DevReproError):
    pass


def _assert_loopback(host: str) -> None:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        if host not in ("localhost",):
            raise ServeError(
                f"refusing to bind to {host!r}: only loopback addresses are allowed."
            ) from None
        return
    if not addr.is_loopback:
        raise ServeError(
            f"refusing to bind to {host}: DevRepro serves sensitive diagnostics on localhost only."
        )


def build_api_payload() -> dict[str, object]:
    """Run a fresh read-only scan and return the sanitized report JSON."""
    from devrepro.cli.pipeline import run_scan

    report = run_scan()
    payload: dict[str, object] = json.loads(json.dumps(report.model_dump(mode="json"), default=str))
    return payload


def serve(*, host: str = "127.0.0.1", port: int = 8642) -> None:
    """Serve the API + (if built) the web frontend on loopback."""
    _assert_loopback(host)

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    try:
        from fastapi import FastAPI  # type: ignore[import-not-found]
        from fastapi.responses import JSONResponse  # type: ignore[import-not-found]
        from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        fastapi_app = FastAPI(title="DevRepro Doctor (local)", version="1")

        @fastapi_app.get("/api/report")  # type: ignore[untyped-decorator]
        def api_report() -> JSONResponse:
            return JSONResponse(build_api_payload())

        @fastapi_app.get("/api/health")  # type: ignore[untyped-decorator]
        def api_health() -> dict[str, str]:
            return {"status": "ok", "privacy": "localhost-only"}

        if web_dist.is_dir():
            fastapi_app.mount("/", StaticFiles(directory=str(web_dist), html=True))

        import uvicorn  # type: ignore[import-not-found,unused-ignore]

        uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")
        return

    # Fallback: dependency-free stdlib server.
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/health"):
                body = json.dumps({"status": "ok"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/api/report"):
                body = json.dumps(build_api_payload()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif web_dist.is_dir():
                rel = self.path.lstrip("/") or "index.html"
                target = web_dist / rel
                if not target.is_file():
                    target = web_dist / "index.html"
                if target.is_file():
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "text/html" if target.suffix == ".html" else "application/octet-stream",
                    )
                    self.end_headers()
                    self.wfile.write(target.read_bytes())
                else:
                    self.send_error(404)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:  # silence
            pass

    with HTTPServer((host, port), Handler) as httpd:
        print(f"DevRepro Doctor serving on http://{host}:{port} (localhost only)")
        print("Press Ctrl+C to stop.")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()


def _unused_socket_guard() -> None:  # pragma: no cover
    socket.setdefaulttimeout(None)
