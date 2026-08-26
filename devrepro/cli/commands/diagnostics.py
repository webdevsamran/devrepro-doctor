"""Core diagnostic commands: check, doctor, info, scan, path, which, preflight."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from devrepro import __version__
from devrepro.cli.common import (
    JsonOption,
    PolicyOption,
    emit,
    exit_for,
    load_policy_or_none,
)
from devrepro.core.errors import DevReproError
from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import FindingState


def register(app: typer.Typer) -> None:
    """Attach diagnostic commands to the root app."""

    @app.command("check")
    def check_cmd(
        policy_path: Path = typer.Option(
            Path(".devrepro.toml"), "--policy", help="Path to .devrepro.toml policy."
        ),
        project_dir: Path | None = typer.Option(None, "--project", help="Project root."),
        json_out: bool = JsonOption,
    ) -> None:
        """Validate a .devrepro.toml policy and check the machine against it.

        Stable exit codes: 0 READY, 1 READY_WITH_WARNINGS, 2 BLOCKED,
        4 invalid policy (see devrepro.core.exit_codes).
        """
        from devrepro.cli.pipeline import run_scan
        from devrepro.project.policy import load_policy

        try:
            policy = load_policy(policy_path)
        except Exception as exc:
            if json_out:
                typer.echo(json.dumps({"error": f"invalid policy: {exc}"}, indent=2))
            else:
                typer.secho(f"Invalid policy {policy_path}: {exc}", fg="red")
            raise SystemExit(ExitCode.USAGE_ERROR) from exc

        report = run_scan(project_dir=project_dir, policy=policy)
        findings = list(report.findings)
        states = {f.state.value for f in findings}
        payload = {
            "policy": str(policy_path),
            "verdict": (
                "BLOCKED"
                if ("BLOCKED" in states or "ERROR" in states)
                else "READY_WITH_WARNINGS"
                if (states - {"PASS", "INFO"})
                else "READY"
            ),
            "findings": [f.model_dump(mode="json") for f in findings],
            "privacy": report.privacy,
        }
        emit(payload, json_out)
        raise SystemExit(exit_for(states))

    @app.command()
    def doctor(
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
        project_dir: Path | None = typer.Option(None, "--project", help="Project root."),
    ) -> None:
        """Full read-only diagnostic scan of machine + project."""
        from devrepro.cli.pipeline import run_scan

        try:
            report = run_scan(project_dir=project_dir, policy=load_policy_or_none(policy_path))
        except DevReproError as exc:
            typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
            raise typer.Exit(exc.exit_code.value) from exc
        if json_out:
            from devrepro.reports.renderers import render_json

            typer.echo(render_json(report))
        else:
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(title=f"DevRepro Doctor v{__version__} — {report.platform.os_name}")
            table.add_column("State")
            table.add_column("Rule")
            table.add_column("Summary")
            for f in sorted(
                report.findings,
                key=lambda x: ["BLOCKED", "ERROR", "WARN", "UNKNOWN", "INFO", "PASS"].index(
                    x.state.value
                ),
            ):
                color = {
                    "BLOCKED": "red",
                    "ERROR": "red",
                    "WARN": "yellow",
                    "UNKNOWN": "grey50",
                    "INFO": "blue",
                    "PASS": "green",
                }[f.state.value]
                table.add_row(f"[{color}]{f.state.value}[/{color}]", f.rule_id, f.summary[:100])
            console.print(table)
            if report.score:
                console.print(
                    f"Reproducibility completeness: {report.score.total}/{report.score.possible} "
                    f"({report.score.percent}%) — declaration completeness only; not a guarantee."
                )
            console.print("[grey50]Read-only scan. No data left this machine.[/grey50]")
        raise typer.Exit(exit_for({f.state.value for f in report.findings}))

    @app.command()
    def info(json_out: bool = JsonOption) -> None:
        """Quick machine summary (OS, shell, key tool versions)."""
        from devrepro.core.runner import SubprocessRunner
        from devrepro.probes.base import ProbeContext, ProbeEngine
        from devrepro.probes.registry import build_default_probes

        ctx = ProbeContext.capture(SubprocessRunner())
        wanted = {"system/os", "system/shell", "system/resources"}
        probes = [p for p in build_default_probes(ctx) if p.id in wanted]
        results = ProbeEngine(probes).run_all()
        data = {pid: getattr(r, "data", {}) for pid, r in results.items()}
        if json_out:
            emit(data, True)
        else:
            for pid, d in data.items():
                typer.echo(f"{pid}: {d}")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def scan(
        json_out: bool = JsonOption,
        output: Path | None = typer.Option(None, "-o", "--output", help="Write report to file."),
        fmt: str = typer.Option("json", "--format", help="json|markdown|junit|html|sarif"),
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Run a scan and emit a report artifact (default format: json)."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.reports.renderers import (
            render_html,
            render_json,
            render_junit,
            render_markdown,
        )
        from devrepro.reports.sarif import render_sarif

        report = run_scan(policy=load_policy_or_none(policy_path))
        renderers = {
            "json": lambda: render_json(report),
            "markdown": lambda: render_markdown(report),
            "junit": lambda: render_junit(report),
            "html": lambda: render_html(report),
            "sarif": lambda: render_sarif(report),
        }
        renderer = renderers.get(fmt)
        if renderer is None:
            typer.secho(
                f"unknown format {fmt!r}; choose json|markdown|junit|html|sarif",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)
        content = renderer()
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
            emit(str(output), json_out)
        else:
            typer.echo(content)
        raise typer.Exit(exit_for({f.state.value for f in report.findings}))

    @app.command()
    def guard(
        policy_path: Path | None = PolicyOption,
        json_out: bool = JsonOption,
    ) -> None:
        """Pre-commit/CI gate: exit 2 when the machine has blockers, else 0.

        Designed for `devrepro guard` in a git pre-commit hook or CI job;
        output stays short so hook logs stay readable.
        """
        from devrepro.cli.pipeline import run_scan

        report = run_scan(policy=load_policy_or_none(policy_path))
        blockers = [
            f.rule_id
            for f in report.findings
            if f.state in (FindingState.ERROR, FindingState.BLOCKED)
        ]
        if json_out:
            emit({"verdict": "BLOCKED" if blockers else "READY", "blockers": blockers}, True)
        elif blockers:
            typer.secho(f"GUARD: blocked by {len(blockers)} finding(s):", fg="red")
            for rid in blockers:
                typer.echo(f"  - {rid}")
            typer.echo("Run `devrepro doctor` for full details and remediation plans.")
        else:
            typer.echo("GUARD: ok")
        raise typer.Exit(ExitCode.BLOCKED if blockers else ExitCode.READY)

    @app.command()
    def preflight(
        policy_path: Path | None = PolicyOption,
        json_out: bool = JsonOption,
    ) -> None:
        """CI/onboarding gate: READY / READY_WITH_WARNINGS / BLOCKED + exit code."""
        from devrepro.cli.pipeline import run_scan

        report = run_scan(policy=load_policy_or_none(policy_path))
        worst = report.worst_state().value
        verdict = {
            "PASS": "READY",
            "INFO": "READY",
            "WARN": "READY_WITH_WARNINGS",
            "UNKNOWN": "READY_WITH_WARNINGS",
            "ERROR": "BLOCKED",
            "BLOCKED": "BLOCKED",
        }.get(worst, "READY_WITH_WARNINGS")
        blockers = [
            f.rule_id
            for f in report.findings
            if f.state in (FindingState.ERROR, FindingState.BLOCKED)
        ]
        payload = {"verdict": verdict, "blockers": blockers}
        if json_out:
            emit(payload, True)
        else:
            typer.echo(f"PREFLIGHT: {verdict}")
            for b in blockers:
                typer.echo(f"  blocker: {b}")
        raise typer.Exit(
            {
                "READY": ExitCode.READY,
                "READY_WITH_WARNINGS": ExitCode.READY_WITH_WARNINGS,
                "BLOCKED": ExitCode.BLOCKED,
            }[verdict]
        )

    def path_cmd() -> None:
        """Analyze PATH: duplicates, dead entries, shadowing, precedence."""
        import os

        from devrepro.platforms.base import build_path_analysis
        from devrepro.probes.base import current_platform

        analysis = build_path_analysis(os.environ.get("PATH", ""), current_platform())
        typer.echo(f"PATH entries: {len(analysis.entries)}")
        for e in analysis.entries:
            mark = "" if e.exists else "  [dead]"
            typer.echo(f"  #{e.index:>2} {e.raw}{mark}")
        if analysis.duplicates:
            typer.secho(f"Duplicates: {len(analysis.duplicates)}", fg=typer.colors.YELLOW)
        if analysis.dead_entries:
            typer.secho(f"Dead entries: {len(analysis.dead_entries)}", fg=typer.colors.YELLOW)
        if analysis.shadowed_executables:
            typer.echo(f"Shadowed executables: {len(analysis.shadowed_executables)}")
            for name, winner, loser in analysis.shadowed_executables[:10]:
                typer.echo(f"  {name}: {winner} wins over {loser}")
        raise typer.Exit(
            ExitCode.READY_WITH_WARNINGS
            if (analysis.duplicates or analysis.dead_entries)
            else ExitCode.READY
        )

    app.command(name="path")(path_cmd)

    @app.command()
    def which(
        name: str = typer.Argument(..., help="Executable name, e.g. python"),
        all_matches: bool = typer.Option(True, "--all/--first"),
        json_out: bool = JsonOption,
    ) -> None:
        """Explain which executable wins PATH resolution — and why."""
        from devrepro.probes.helpers import resolve_all_on_path

        matches = resolve_all_on_path(name)
        payload = {"name": name, "matches": matches}
        if json_out:
            emit(payload, True)
            raise typer.Exit(ExitCode.READY if matches else ExitCode.BLOCKED)
        if not matches:
            typer.secho(f"'{name}' not found on PATH.", fg=typer.colors.RED)
            raise typer.Exit(ExitCode.BLOCKED)
        typer.echo(f"'{name}' resolves to: {matches[0]}")
        typer.echo(
            "Why it wins: its directory appears earliest in PATH (earlier entries take precedence)."
        )
        if all_matches and len(matches) > 1:
            typer.echo("Shadowed installations:")
            for m in matches[1:]:
                typer.echo(f"  - {m}")
        raise typer.Exit(ExitCode.READY)
