"""Report commands: report (re-render) and export (all formats)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError

from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import ScanReport

#: Keys a snapshot carries and a scan report does not. Both files are JSON, both
#: come out of this tool, and `snapshot` is the better-known command -- so
#: handing a snapshot to `report` is the obvious mistake, and it is worth
#: recognising by name rather than reporting as malformed input.
_SNAPSHOT_ONLY_KEYS = frozenset({"compilers", "virtualenvs", "requirements_fingerprint"})


def _maybe_report(raw: str) -> ScanReport | None:
    """A scan report, or None if the text is something else.

    `export` accepts reports and snapshots alike and copies whatever it cannot
    render. It decided between them by looking for `"findings"` in the text,
    which a snapshot also contains -- so a snapshot took the report branch and
    failed validation exactly as `report` did.
    """
    try:
        return ScanReport.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None


def _load_report(input_file: Path) -> ScanReport:
    """Parse a saved scan report, or explain what the file actually is.

    `ScanReport` forbids extra fields, so a snapshot failed validation with
    three `extra_forbidden` errors and a link to the pydantic documentation --
    which tells the reader that `compilers` is not permitted, and nothing about
    which command produces the file they wanted.
    """
    try:
        payload = json.loads(input_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.secho(f"{input_file} is not readable JSON: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR) from exc

    try:
        return ScanReport.model_validate(payload)
    except ValidationError as exc:
        looks_like_snapshot = isinstance(payload, dict) and _SNAPSHOT_ONLY_KEYS & set(payload)
        if looks_like_snapshot:
            typer.secho(
                f"{input_file} is a snapshot, not a scan report. `report` re-renders the "
                "output of `devrepro scan -o report.json`; to compare snapshots use "
                "`devrepro diff a.json b.json`.",
                fg=typer.colors.RED,
                err=True,
            )
        else:
            first = exc.errors()[:3]
            detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in first)
            typer.secho(
                f"{input_file} is not a scan report ({detail}). Produce one with "
                "`devrepro scan -o report.json`.",
                fg=typer.colors.RED,
                err=True,
            )
        raise typer.Exit(ExitCode.USAGE_ERROR) from exc


def register(app: typer.Typer) -> None:
    """Attach report/export commands to the root app."""

    @app.command()
    def report(
        input_file: Path = typer.Argument(
            ..., exists=True, readable=True, help="A saved JSON scan report."
        ),
        fmt: str = typer.Option(
            "markdown",
            "--format",
            help="markdown|junit|html|json|sarif|cyclonedx",
        ),
        output: Path | None = typer.Option(None, "-o", "--output"),
    ) -> None:
        """Re-render a saved JSON report into another format.

        `cyclonedx` emits a bill of materials for the *environment* -- the
        toolchain a build ran on, not the dependencies it links against.
        Every SBOM tool answers the second question and none answers the
        first, which is the one a reproducibility argument turns on.
        """
        from devrepro.compliance.envbom import render_environment_bom
        from devrepro.reports.renderers import (
            render_html,
            render_json,
            render_junit,
            render_markdown,
        )
        from devrepro.reports.sarif import render_sarif

        data = _load_report(input_file)
        renderers = {
            "markdown": render_markdown,
            "junit": render_junit,
            "html": render_html,
            "json": render_json,
            "sarif": render_sarif,
            "cyclonedx": render_environment_bom,
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
        # Was `'"findings"' in raw`, which a snapshot also satisfies -- so
        # exporting a snapshot took the report branch and raised the same
        # `extra_forbidden` error `report` did. Parsing decides it now, and the
        # copy branch is the documented behaviour for anything else.
        data = _maybe_report(raw)
        if data is not None:
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
