"""Agent commands: agent-check."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from devrepro.cli.common import JsonOption, emit, secho
from devrepro.core.exit_codes import ExitCode

if TYPE_CHECKING:
    from devrepro.agents import (
        AgentManifest,
        AgentReadiness,
        BlastRadius,
        CommandCheck,
        ManifestDisagreement,
        StaleCommand,
    )

#: Characters that mean the shell would do work the runner cannot: pipes,
#: redirection, globbing, substitution. Such a command is never executed by
#: --run, because running it safely would need a shell, and this project does
#: not hand a shell an untrusted string.
_SHELL_METACHARACTERS = ("|", ">", "<", "*", "$", "`", "(", ")", "{", "}")

_STATUS_COLOUR = {
    "ok": "green",
    "shell-builtin": "green",
    "not-on-path": "yellow",
    "path-absent": "yellow",
    "missing": "red",
}


def register(app: typer.Typer) -> None:
    """Attach agent commands to the root app."""

    @app.command("agent-check")
    def agent_check_cmd(
        path: Path = typer.Argument(Path(), help="Repository root to check."),
        run: bool = typer.Option(
            False,
            "--run",
            help="OPT-IN: execute each resolvable declared command. Off by default.",
        ),
        timeout: float = typer.Option(120.0, help="Per-command timeout for --run, seconds."),
        blast_radius: bool = typer.Option(
            True,
            "--blast-radius/--no-blast-radius",
            help="Report what an agent starting here could reach.",
        ),
        as_json: bool = JsonOption,
    ) -> None:
        """Check whether an AI coding agent can work in this repository.

        Reads AGENTS.md / CLAUDE.md / .cursorrules, resolves every command they
        declare against this machine, and compares them with what CI actually
        enforces on a pull request.

        Read-only by default: commands are resolved, not executed. A manifest is
        an untrusted file and its setup step usually installs software, so
        running one needs --run, which reports each command before it runs.
        """
        from devrepro.agents import (
            assess_blast_radius,
            check_declared_commands,
            ci_declared_commands,
            compare_manifests,
            discover_manifests,
            manifest_vs_ci,
            score_readiness,
            stale_commands,
        )

        manifests = discover_manifests(path)
        declared = [c for m in manifests for c in m.commands]
        checks = check_declared_commands(declared, root=path)
        drift = manifest_vs_ci(declared, ci_declared_commands(path))
        stale = stale_commands(declared, path)
        disagreements = compare_manifests(manifests)
        readiness = score_readiness(
            manifests=manifests,
            checks=checks,
            drift=drift,
            stale=stale,
            disagreements=disagreements,
        )

        radius = assess_blast_radius(path) if blast_radius else None

        executed: list[dict[str, object]] = []
        if run:
            executed = _execute(checks, timeout=timeout, cwd=path, as_json=as_json)

        payload: dict[str, object] = {
            "root": str(path),
            "manifests": [{"path": m.path, "commands": len(m.commands)} for m in manifests],
            "checks": [
                {
                    "command": c.command.raw,
                    "program": c.command.program,
                    "manifest": c.command.manifest,
                    "line": c.command.line,
                    "status": c.status,
                    "detail": c.detail,
                    "resolved": c.resolved,
                }
                for c in checks
            ],
            "undeclared_ci_commands": drift,
            "stale_commands": [
                {
                    "command": st.raw,
                    "runner": st.runner,
                    "target": st.target,
                    "manifest": st.manifest,
                    "line": st.line,
                    "available": list(st.available),
                }
                for st in stale
            ],
            "manifest_disagreements": [
                {
                    "command": d.command,
                    "present_in": list(d.present_in),
                    "absent_from": list(d.absent_from),
                }
                for d in disagreements
            ],
            "readiness": {
                "total": readiness.total,
                "possible": readiness.possible,
                "percent": readiness.percent,
                "grade": readiness.grade,
                "factors": [
                    {
                        "name": f.name,
                        "earned": f.earned,
                        "possible": f.possible,
                        "explanation": f.explanation,
                    }
                    for f in readiness.factors
                ],
            },
            "verdict": _verdict(manifests, checks),
        }
        if radius is not None:
            payload["blast_radius"] = {
                "highest_severity": radius.highest_severity,
                "uncommitted_files": radius.uncommitted_files,
                "unpushed_commits": radius.unpushed_commits,
                "credential_names": list(radius.credential_names),
                "exposures": [
                    {
                        "kind": e.kind,
                        "severity": e.severity,
                        "summary": e.summary,
                        "detail": e.detail,
                        "evidence": e.evidence,
                    }
                    for e in radius.exposures
                ],
            }
        if run:
            payload["executed"] = executed

        if as_json:
            emit(payload, True)
        else:
            _render(
                manifests,
                checks,
                drift,
                executed,
                run=run,
                radius=radius,
                stale=stale,
                disagreements=disagreements,
                readiness=readiness,
            )

        raise typer.Exit(_exit_code(manifests, checks, drift))


def _verdict(manifests: list[AgentManifest], checks: list[CommandCheck]) -> str:
    if not manifests:
        return "NO_MANIFEST"
    if any(c.status == "missing" for c in checks):
        return "BLOCKED"
    if any(c.status in {"not-on-path", "path-absent"} for c in checks):
        return "READY_WITH_WARNINGS"
    return "READY"


def _exit_code(manifests: list[AgentManifest], checks: list[CommandCheck], drift: list[str]) -> int:
    """Map the verdict onto the published contract.

    A missing program blocks: the agent will fail on that command. A manifest
    that drifts from CI, or a program that is merely unreachable from this
    shell, is a warning -- the work can proceed, but not as documented.

    No manifest at all is READY, not an error. Most repositories do not have
    one yet, and reporting their absence as a failure would make this command
    useless as a gate.
    """
    verdict = _verdict(manifests, checks)
    if verdict == "BLOCKED":
        return ExitCode.BLOCKED
    if verdict == "READY_WITH_WARNINGS" or drift:
        return ExitCode.READY_WITH_WARNINGS
    return ExitCode.READY


def _execute(
    checks: list[CommandCheck], *, timeout: float, cwd: Path, as_json: bool
) -> list[dict[str, object]]:
    """Run each resolvable declared command, showing it first.

    Only commands that resolve and contain no shell metacharacters are run.
    Anything needing a shell is skipped rather than handed to one.
    """
    from devrepro.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    results: list[dict[str, object]] = []
    for check in checks:
        raw = check.command.raw
        if not check.ok:
            results.append({"command": raw, "status": "skipped-unresolved"})
            continue
        if any(ch in raw for ch in _SHELL_METACHARACTERS):
            results.append({"command": raw, "status": "skipped-needs-shell"})
            continue
        if not as_json:
            typer.secho(f"  running: {raw}", fg="cyan")
        outcome = runner.run(tuple(raw.split()), timeout=timeout, cwd=str(cwd))
        results.append(
            {
                "command": raw,
                "status": "passed" if outcome.ok else "failed",
                "returncode": outcome.returncode,
                "timed_out": outcome.timed_out,
            }
        )
    return results


_SEVERITY_COLOUR = {"high": "red", "medium": "yellow", "info": "cyan"}


def _render_blast_radius(radius: BlastRadius) -> None:
    """Print the briefing.

    Ordered high severity first: the reader is about to hand this machine to
    something autonomous, and the thing most worth knowing should not be third.
    """
    typer.echo("")
    if not radius.exposures:
        secho("Blast radius: nothing notable reachable from here.", fg="green")
        return

    secho(
        f"Blast radius ({radius.highest_severity}):",
        fg=_SEVERITY_COLOUR.get(radius.highest_severity, "white"),
    )
    order = {"high": 0, "medium": 1, "info": 2}
    for exposure in sorted(radius.exposures, key=lambda e: order.get(e.severity, 3)):
        secho(
            f"  [{exposure.severity:<6}] {exposure.summary}",
            fg=_SEVERITY_COLOUR.get(exposure.severity),
        )
        typer.echo(f"        {exposure.detail}")
        if exposure.evidence:
            typer.echo(f"        evidence: {exposure.evidence}")


def _render(
    manifests: list[AgentManifest],
    checks: list[CommandCheck],
    drift: list[str],
    executed: list[dict[str, object]],
    *,
    run: bool,
    radius: BlastRadius | None = None,
    stale: list[StaleCommand] | None = None,
    disagreements: list[ManifestDisagreement] | None = None,
    readiness: AgentReadiness | None = None,
) -> None:
    if not manifests:
        typer.secho(
            "No agent manifest found (AGENTS.md, CLAUDE.md, .cursorrules).",
            fg="yellow",
        )
        typer.echo("An agent working here has no declared setup, build or test commands.")
        if radius is not None:
            _render_blast_radius(radius)
        return

    found = ", ".join(m.path for m in manifests)
    typer.echo(f"Agent manifests: {found}")
    typer.echo("")

    for check in checks:
        colour = _STATUS_COLOUR.get(check.status, "white")
        typer.secho(f"  [{check.status:<14}] {check.command.raw}", fg=colour)
        if not check.ok:
            typer.echo(f"        {check.detail}")

    if drift:
        typer.echo("")
        typer.secho(f"{len(drift)} command(s) CI enforces that no manifest declares:", fg="yellow")
        for command in drift:
            typer.echo(f"  - {command}")
        typer.echo(
            "    An agent that runs everything the manifest lists can still be failed by these."
        )

    if stale:
        typer.echo("")
        secho(f"{len(stale)} declared command(s) name a target that no longer exists:", fg="red")
        for stale_command in stale:
            typer.echo(f"  - {stale_command.summary}")
        typer.echo("    The program resolves, so nothing catches these until an agent runs them.")

    if disagreements:
        typer.echo("")
        secho(f"{len(disagreements)} command(s) differ between manifests:", fg="yellow")
        for disagreement in disagreements:
            typer.echo(
                f"  - {disagreement.command}: in {', '.join(disagreement.present_in)}; "
                f"absent from {', '.join(disagreement.absent_from)}"
            )

    if readiness is not None:
        typer.echo("")
        typer.echo(
            f"Agent readiness: {readiness.total}/{readiness.possible} "
            f"({readiness.percent}%, {readiness.grade})"
        )
        for factor in readiness.factors:
            mark = "+" if factor.earned == factor.possible else "-"
            typer.echo(
                f"  [{mark}] {factor.earned}/{factor.possible} {factor.name}: {factor.explanation}"
            )

    if radius is not None:
        _render_blast_radius(radius)

    if run:
        typer.echo("")
        typer.echo("Execution:")
        for result in executed:
            status = str(result["status"])
            colour = {"passed": "green", "failed": "red"}.get(status, "yellow")
            typer.secho(f"  [{status:<18}] {result['command']}", fg=colour)
