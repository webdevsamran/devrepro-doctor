"""Remediation commands: plan, fix, rules, plugins."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  (Typer resolves command annotations at runtime)

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none, secho
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
                # "automatable" has to mean "this will actually run something".
                # A step flagged automatable but carrying no commands was
                # displayed identically to one that executes, which is the
                # promise `devrepro fix` could not keep.
                if s.automatable and s.commands:
                    auto = "automatable"
                elif s.automatable:
                    auto = "automatable in principle - no command wired yet"
                else:
                    auto = "manual guidance only"
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
        """Execute ONLY SAFE/LOW automatable remediations after confirmation.

        Requires an explicit --yes. Steps are reported individually: `executed`,
        `skipped-manual` (guidance only), `skipped-preconditions`, or
        `no-commands` for a step planned as automatable that has no command
        wired to it yet. Run `devrepro plan` first to review every step.
        """
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
    def rules(
        catalog: bool = typer.Option(
            False, "--catalog", help="List every documented rule id, not just the packs."
        ),
        json_out: bool = JsonOption,
    ) -> None:
        """List available rule packs, or the full rule catalogue."""
        from devrepro.rules.base import PACK_NAMES

        if not catalog:
            emit({"packs": list(PACK_NAMES)}, json_out)
            raise typer.Exit(ExitCode.READY)

        from devrepro.rules.catalog import all_rule_docs

        docs = all_rule_docs()
        if json_out:
            emit({"rules": [d.as_dict() for d in docs]}, True)
        else:
            typer.echo(f"{len(docs)} documented rule ids:")
            for doc in docs:
                typer.echo(f"  {doc.rule_id:<42} {doc.title}")
            typer.echo("")
            typer.echo("`devrepro explain <rule-id>` for the long form.")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def explain(
        rule_id: str = typer.Argument(..., help="Rule id, e.g. node/version-mismatch."),
        json_out: bool = JsonOption,
    ) -> None:
        """Explain a rule id: what it means, why it matters, how to fix it.

        A finding gives you an id and one line, which is the right amount for a
        table and not enough to act on. This is the long form.

        Composed ids resolve by their suffix, so `bun/multiple-installations`
        is explained even though no code writes that exact string -- the prefix
        is whichever tool was found twice.
        """
        from devrepro.rules.catalog import explain_rule

        doc = explain_rule(rule_id)
        if doc is None:
            secho(f"No documentation for rule id {rule_id!r}.", fg="yellow", err=True)
            typer.echo("Run `devrepro rules --catalog` to see every documented id.", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR)

        if json_out:
            emit(doc.as_dict(), True)
        else:
            secho(doc.rule_id, fg="cyan")
            typer.echo(doc.title)
            typer.echo("")
            typer.echo(f"What it means   {doc.means}")
            typer.echo("")
            typer.echo(f"Why it matters  {doc.matters}")
            typer.echo("")
            typer.echo(f"How to fix it   {doc.fix}")
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
