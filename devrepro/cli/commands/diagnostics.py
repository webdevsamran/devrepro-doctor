"""Core diagnostic commands: check, doctor, info, scan, path, which, preflight."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from devrepro.cli.common import (
    JsonOption,
    PolicyOption,
    QuietOption,
    emit,
    exit_for,
    load_policy_or_none,
    secho,
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
        fix_plan: bool = typer.Option(
            False,
            "--fix-plan",
            help="Print a commented shell script of the remediations, without running any.",
        ),
        quiet: bool = QuietOption,
    ) -> None:
        """Full read-only diagnostic scan of machine + project.

        `--fix-plan` prints the remediations as a shell script you can read,
        edit and run yourself. Nothing is executed: the script is output, not
        an action, which keeps the decision with the person who has to live
        with the consequences.
        """
        from devrepro.cli.pipeline import run_scan

        try:
            report = run_scan(project_dir=project_dir, policy=load_policy_or_none(policy_path))
        except DevReproError as exc:
            typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
            raise typer.Exit(exc.exit_code.value) from exc
        if fix_plan:
            typer.echo(_render_fix_plan(report))
            raise typer.Exit(exit_for({f.state.value for f in report.findings}))
        if quiet:
            pass
        elif json_out:
            from devrepro.reports.renderers import render_json

            typer.echo(render_json(report))
        else:
            from rich.console import Console

            from devrepro.reports.renderers import render_terminal_table

            console = Console()
            console.print(render_terminal_table(report))
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
        fmt: str = typer.Option(
            "json", "--format", help="json|markdown|junit|html|sarif|cyclonedx"
        ),
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Run a scan and emit a report artifact (default format: json)."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.compliance.envbom import render_environment_bom
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
            # The environment BOM: the toolchain a build ran on, not the
            # dependencies it links against.
            "cyclonedx": lambda: render_environment_bom(report),
        }
        renderer = renderers.get(fmt)
        if renderer is None:
            typer.secho(
                f"unknown format {fmt!r}; choose json|markdown|junit|html|sarif|cyclonedx",
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
        # Keyword-only: these are all flags, never positional.
        *,
        policy_path: Path | None = PolicyOption,
        json_out: bool = JsonOption,
        quiet: bool = QuietOption,
        scope: str = typer.Option(
            "machine",
            "--scope",
            help="machine (default) | changed: only gate when the environment contract changed.",
        ),
        base: str | None = typer.Option(
            None,
            "--base",
            help="Compare against this ref instead of the working tree, e.g. origin/main.",
        ),
        path: Path = typer.Option(Path(), "--path", help="Repository root."),
        output_format: str = typer.Option(
            "text",
            "--format",
            help="text (default) | json | markdown. markdown is written for a "
            "pull-request comment.",
        ),
    ) -> None:
        """Pre-commit/CI gate: exit 2 when the machine has blockers, else 0.

        Output stays short so hook logs stay readable, and `--quiet` drops it
        entirely so a passing hook prints nothing.

        `--scope machine` gates on everything found anywhere, which is right
        for a CI job on a fresh runner and wrong for a commit hook: a stopped
        Docker daemon then blocks a commit that touches only source, and the
        hook gets deleted within a week.

        `--scope changed` gates only when the commit alters the **environment
        contract** -- a lockfile, manifest, toolchain pin, CI workflow,
        container definition or policy. Scoping to changed files the way a
        linter does would be meaningless here, because a machine has no
        per-file technical debt; what changes is what the machine is being
        asked to provide. When nothing in the contract moved, the gate exits 0
        without scanning at all, which is also what makes it fast enough for a
        hook.

        `--format markdown` renders the same verdict as a pull-request comment,
        carrying a stable HTML marker so a CI job can edit its own previous
        comment instead of appending a new one on every push. It prints to
        stdout and posts nothing: what to do with the text is the workflow's
        decision, not this tool's.
        """
        from devrepro.cli.pipeline import run_scan
        from devrepro.project.contract import contract_changes
        from devrepro.reports.renderers import render_guard_comment

        # `--json` predates `--format` and stays a shorthand for it rather than
        # a competing flag: scripts already pass it, and two ways to ask for
        # the same thing is better than breaking them.
        resolved = "json" if json_out else output_format
        if resolved not in {"text", "json", "markdown"}:
            secho(
                f"unknown format {output_format!r}; expected 'text', 'json' or 'markdown'.",
                fg="red",
                err=True,
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)

        changes = []
        if scope == "changed":
            changes = contract_changes(path, base=base)
            if not changes:
                if not quiet:
                    if resolved == "json":
                        emit(
                            {
                                "verdict": "READY",
                                "scope": "changed",
                                "contract_changes": [],
                                "blockers": [],
                                "detail": "No environment-contract file changed; "
                                "nothing to re-check.",
                            },
                            True,
                        )
                    elif resolved == "markdown":
                        typer.echo(
                            render_guard_comment(
                                scope=scope, changes=[], blocking=[], scanned=False
                            ),
                            nl=False,
                        )
                    else:
                        typer.echo("GUARD: ok (no environment-contract change)")
                raise typer.Exit(ExitCode.READY)
        elif scope != "machine":
            secho(f"unknown scope {scope!r}; expected 'machine' or 'changed'.", fg="red", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR)

        report = run_scan(policy=load_policy_or_none(policy_path))
        blocking = [
            f for f in report.findings if f.state in (FindingState.ERROR, FindingState.BLOCKED)
        ]

        if scope == "changed":
            # Narrow to findings the change could plausibly be about. Changing a
            # Python manifest should not be blocked by a stopped Docker daemon:
            # scoping decided whether to look, this decides where.
            from devrepro.project.contract import relevant_rule_prefixes

            prefixes = relevant_rule_prefixes(changes)
            if prefixes is not None:
                blocking = [f for f in blocking if f.rule_id.split("/", 1)[0] in prefixes]

        blockers = [f.rule_id for f in blocking]
        if quiet:
            pass
        elif resolved == "markdown":
            typer.echo(
                render_guard_comment(scope=scope, changes=changes, blocking=blocking, scanned=True),
                nl=False,
            )
        elif resolved == "json":
            emit(
                {
                    "verdict": "BLOCKED" if blockers else "READY",
                    "scope": scope,
                    "contract_changes": [{"path": c.path, "kind": c.kind} for c in changes],
                    "blockers": blockers,
                },
                True,
            )
        else:
            if changes:
                typer.echo(f"GUARD: {len(changes)} environment-contract change(s):")
                for change in changes:
                    typer.echo(f"  [{change.kind}] {change.path}")
            if blockers:
                secho(f"GUARD: blocked by {len(blockers)} finding(s):", fg="red")
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
        quiet: bool = QuietOption,
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
        if quiet:
            pass
        elif json_out:
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


def _render_fix_plan(report: object) -> str:
    """A shell script of the remediation plan, as text.

    Every step is commented with the finding that motivated it and its risk
    tier, and anything above LOW is left commented out. A plan that pastes
    cleanly and runs a HIGH-risk change without the reader noticing would be
    worse than no plan.
    """
    from devrepro.remediation.planner import AUTOMATABLE_RISKS, build_plan

    steps = build_plan(list(report.findings))  # type: ignore[attr-defined]
    nl = chr(10)
    lines = [
        "#!/usr/bin/env bash",
        "# Generated by `devrepro doctor --fix-plan`. REVIEW BEFORE RUNNING.",
        "#",
        "# devrepro did not run any of this. Steps above LOW risk are left",
        "# commented out deliberately -- uncomment one only when you have read it",
        "# and accept what it changes.",
        "set -euo pipefail",
        "",
    ]
    if not steps:
        lines.append("# Nothing to remediate: no finding proposed an action.")
        return nl.join(lines)

    for step in steps:
        lines.append(f"# [{step.risk.value}] {step.title}")
        for change in step.changes:
            lines.append(f"#   change:   {change}")
        lines.append(f"#   rollback: {step.rollback}")
        if step.finding_ids:
            lines.append(f"#   because:  {', '.join(step.finding_ids)}")
        safe = step.risk in AUTOMATABLE_RISKS
        if not step.commands:
            lines.append("#   (no command available; apply the change described above by hand)")
        else:
            for command in step.commands:
                rendered = " ".join(command)
                lines.append(rendered if safe else f"# {rendered}")
        lines.append("")
    return nl.join(lines)
