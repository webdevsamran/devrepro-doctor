"""Remediation commands: plan, fix, rules, plugins."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  (Typer resolves command annotations at runtime)

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none
from devrepro.core.errors import DevReproError
from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach remediation/plugin commands to the root app."""

    @app.command()
    def plan(
        policy_path: Path | None = PolicyOption,
        json_out: bool = JsonOption,
    ) -> None:
        """Dry-run remediation plan. Nothing is executed."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.remediation.planner import build_plan

        report = run_scan(policy=load_policy_or_none(policy_path))
        steps = build_plan(list(report.findings))
        payload = [s.model_dump(mode="json") for s in steps]
        if json_out:
            emit(payload, True)
        else:
            typer.echo(f"Remediation plan ({len(steps)} steps) — DRY RUN, nothing executed:")
            for s in steps:
                auto = "automatable" if s.automatable else "manual guidance only"
                typer.echo(f"  [{s.risk.value:<6}] {s.title} ({auto})")
                for c in s.changes:
                    typer.echo(f"      change: {c}")
                typer.echo(f"      rollback: {s.rollback}")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def fix(
        yes: bool = typer.Option(False, "--yes", help="Explicitly confirm execution."),
        json_out: bool = JsonOption,
    ) -> None:
        """Execute ONLY SAFE/LOW automatable remediations after confirmation."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.remediation.planner import build_plan, execute_plan

        report = run_scan()
        steps = build_plan(list(report.findings))
        try:
            results = execute_plan(steps, confirmed=yes, executor=lambda cmd: 0)
        except DevReproError as exc:
            typer.secho(f"refused: {exc.message}", fg=typer.colors.YELLOW, err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR) from exc
        emit(results, json_out)
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def rules(json_out: bool = JsonOption) -> None:
        """List available rule packs."""
        from devrepro.rules.base import PACK_NAMES

        emit({"packs": list(PACK_NAMES)}, json_out)
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def plugins(json_out: bool = JsonOption) -> None:
        """List installed plugins per entry-point group."""
        from devrepro.plugins.loader import API_VERSION, PLUGIN_GROUPS, list_plugins

        found = list_plugins()
        payload = {"api_version": API_VERSION, "groups": found}
        if json_out:
            emit(payload, True)
        else:
            typer.echo(f"Plugin API version: {API_VERSION}")
            for group in PLUGIN_GROUPS:
                entries = found.get(group, [])
                typer.echo(f"{group}: {len(entries)}")
                for e in entries:
                    typer.echo(f"  {e}")
        raise typer.Exit(ExitCode.READY)
