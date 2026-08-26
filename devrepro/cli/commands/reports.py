"""Report commands: report (re-render) and export (all formats)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach report/export commands to the root app."""

    @app.command()
    def report(
        input_file: Path = typer.Argument(
            ..., exists=True, readable=True, help="A saved JSON scan report."
        ),
        fmt: str = typer.Option("markdown", "--format", help="markdown|junit|html|json|sarif"),
        output: Path | None = typer.Option(None, "-o", "--output"),
    ) -> None:
        """Re-render a saved JSON report into another format."""
        from devrepro.core.models import ScanReport
        from devrepro.reports.renderers import (
            render_html,
            render_json,
            render_junit,
            render_markdown,
        )
        from devrepro.reports.sarif import render_sarif

        data = ScanReport.model_validate(json.loads(input_file.read_text(encoding="utf-8")))
        renderers = {
            "markdown": render_markdown,
            "junit": render_junit,
            "html": render_html,
            "json": render_json,
            "sarif": render_sarif,
        }
        renderer = renderers.get(fmt)
        if renderer is None:
            typer.secho(f"unknown format {fmt!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR)
        content = renderer(data)
        if output is not None:
            output.write_text(content, encoding="utf-8")
            typer.echo(str(output))
        else:
            typer.echo(content)
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def export(
        input_file: Path = typer.Argument(..., exists=True, readable=True),
        out_dir: Path = typer.Option(Path("./devrepro-export"), "--out-dir"),
    ) -> None:
        """Export a report/snapshot to all formats in a directory."""
        from devrepro.core.models import ScanReport
        from devrepro.exporters.base import FileExporter
        from devrepro.reports.renderers import (
            render_html,
            render_json,
            render_junit,
            render_markdown,
        )

        raw = input_file.read_text(encoding="utf-8")
        exporter = FileExporter(out_dir)
        locations = []
        if '"findings"' in raw:
            data = ScanReport.model_validate(json.loads(raw))
            for fmt, fn in (
                ("json", render_json),
                ("md", render_markdown),
                ("junit.xml", render_junit),
                ("html", render_html),
            ):
                locations.append(exporter.export(fn(data), filename=f"report.{fmt}"))
        else:
            locations.append(exporter.export(raw, filename=input_file.name))
        for loc in locations:
            typer.echo(loc)
        raise typer.Exit(ExitCode.READY)
