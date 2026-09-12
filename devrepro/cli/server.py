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
from urllib.parse import unquote

from devrepro.core.errors import DevReproError

__all__ = ["serve", "static_response"]


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


#: Extension -> media type, written out rather than looked up.
#:
#: `mimetypes.guess_type` reads the Windows registry, where `.js` is whatever
#: the last program to claim it left behind, and it returns `None` for `.map`
#: on this machine today. A console that boots or does not depending on a
#: registry key is not a console anybody can support, so the table is here.
CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
    ".webmanifest": "application/manifest+json",
}

#: What a path with no known extension gets. Never `text/html` -- guessing HTML
#: for an unknown file is how a 404 becomes a blank page with a 200.
FALLBACK_CONTENT_TYPE = "application/octet-stream"

NOT_FOUND = (404, "text/plain; charset=utf-8", b"not found\n")


def static_response(web_dist: Path, request_path: str) -> tuple[int, str, bytes]:
    """Resolve one GET against the built console.

    Pulled out of the request handler because it had three defects and no test
    could have found any of them from outside a running server.

    **Everything but `.html` was served as `application/octet-stream`**, and a
    browser refuses to execute a module script with that type. So the console
    rendered an empty page under this server -- the one `devrepro serve` starts
    whenever the optional FastAPI extra is absent, which is the dependency-free
    default this project advertises, and the command its own error state tells
    people to run.

    **Any missing path fell back to `index.html` with a 200.** A mistyped asset
    URL returned HTML pretending to be JavaScript. Now only extensionless paths
    fall back -- those are client-side routes; a request for a file that is not
    there is a 404, which is what says so.

    **`self.path` was joined to the directory unresolved**, so `..` walked out
    of it. Browsers normalise that away before sending, but this server does not
    only talk to browsers, and it serves from a machine whose whole selling
    point is that its diagnostics stay on it.
    """
    if not web_dist.is_dir():
        return NOT_FOUND

    # A query string or fragment is not part of the file name. Without this,
    # `/assets/index.js?v=2` missed the file and fell through to the HTML.
    path = request_path.split("?", 1)[0].split("#", 1)[0]
    relative = unquote(path).lstrip("/")

    if not relative or relative.endswith("/"):
        relative += "index.html"

    root = web_dist.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        # Outside the served directory. 404 rather than 403: a different answer
        # for "exists but forbidden" tells a prober the file is there.
        return NOT_FOUND

    if not target.is_file():
        # A client-side route (`/findings`, `/`) has no extension and is served
        # the shell. Anything that looks like a file is missing, and says so.
        if Path(relative).suffix:
            return NOT_FOUND
        target = root / "index.html"
        if not target.is_file():
            return NOT_FOUND

    content_type = CONTENT_TYPES.get(target.suffix.lower(), FALLBACK_CONTENT_TYPE)
    return 200, content_type, target.read_bytes()


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
    # Every ignore in this block carries `unused-ignore` as well, because
    # these imports are optional: mypy sees them as missing on a machine
    # without the extra and as perfectly typed on one with it. Without the
    # second code, `mypy --strict` passes or fails depending on what happens
    # to be installed -- which is the class of problem this project exists
    # to diagnose, and it was live in this file.
    try:
        from fastapi import FastAPI  # type: ignore[import-not-found,unused-ignore]
        from fastapi.responses import JSONResponse  # type: ignore[import-not-found,unused-ignore]
        from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        pass
    else:
        fastapi_app = FastAPI(title="DevRepro Doctor (local)", version="1")

        @fastapi_app.get("/api/report")  # type: ignore[untyped-decorator,unused-ignore]
        def api_report() -> JSONResponse:
            return JSONResponse(build_api_payload())

        @fastapi_app.get("/api/health")  # type: ignore[untyped-decorator,unused-ignore]
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
            else:
                status, content_type, body = static_response(web_dist, self.path)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                # The console is served from disk to one machine; a cached
                # stale bundle after a rebuild looks exactly like a bug in the
                # tool, and there is nothing to gain by caching a localhost read.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:  # silence
            pass

    with HTTPServer((host, port), Handler) as httpd:
        print(f"DevRepro Doctor serving on http://{host}:{port} (localhost only)")
        print("Press Ctrl+C to stop.")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()


def _unused_socket_guard() -> None:  # pragma: no cover
    socket.setdefaulttimeout(None)
