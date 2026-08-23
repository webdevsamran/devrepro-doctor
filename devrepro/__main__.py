"""Allow ``python -m devrepro`` to invoke the CLI."""

from __future__ import annotations

from devrepro.cli.app import app

if __name__ == "__main__":
    raise SystemExit(app())
