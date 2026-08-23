"""Exporter plugin layer.

Exporters turn a rendered artifact into a destination (file, stdout).
Third-party exporters register under entry point group ``devrepro.exporters``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

__all__ = ["Exporter", "FileExporter", "StdoutExporter"]


class Exporter(Protocol):
    """Plugin API v1."""

    name: str

    def export(self, content: str, *, filename: str | None = None) -> str:
        """Write ``content`` somewhere; return a human-readable location."""
        ...


class FileExporter:
    name = "file"

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory

    def export(self, content: str, *, filename: str | None = None) -> str:
        target = (self.directory or Path.cwd()) / (filename or "devrepro-report.txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)


class StdoutExporter:
    name = "stdout"

    def export(self, content: str, *, filename: str | None = None) -> str:
        sys.stdout.write(content)
        sys.stdout.write(chr(10))
        return "<stdout>"
