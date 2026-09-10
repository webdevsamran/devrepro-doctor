"""Commands for the things that consume this tool: contract, watch, pins.

Three surfaces aimed at other software rather than at a person reading a
terminal. `contract` is what a wrapper asserts against, `watch` is what a
developer leaves running, `pins` is what tells you the update bot is not
watching half your toolchain.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none, secho
from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach integration commands to the root app."""

    @app.command()
    def contract(
        json_out: bool = JsonOption,
    ) -> None:
        """What another program may rely on, and what it may not.

        Exit codes, the JSON fields that never move, and -- as importantly --
        the list of things that are deliberately not promised. A wrapper built
        on terminal output or on a finding count has built on sand, and this
        says so before somebody finds out from a red build.
        """
        from devrepro.core.contract import contract_document

        document = contract_document()
        if json_out:
            emit(document, True)
        else:
            typer.echo(f"devrepro contract v{document['contract_version']}")
            typer.echo("")
            typer.echo("Exit codes:")
            for row in document["exit_codes"]:
                typer.echo(f"  {row['code']}  {row['name']:<20} {row['meaning']}")
            typer.echo("")
            typer.echo("Guaranteed:")
            for line in document["guaranteed"]:
                typer.echo(f"  - {line}")
            typer.echo("")
            typer.echo("NOT guaranteed - do not build on these:")
            for line in document["not_guaranteed"]:
                typer.echo(f"  - {line}")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def pins(
        path: Path = typer.Option(Path(), "--path", help="Repository root."),
        json_out: bool = JsonOption,
    ) -> None:
        """Whether the update bot is watching the files that pin your toolchain.

        Dependabot has no ecosystem that reads `.nvmrc` or `.tool-versions` at
        all, so a repository can have a complete `dependabot.yml` and a Node
        version nothing will ever bump. Renovate does cover them -- unless
        `enabledManagers` is set, which turns the default-on list into an
        allowlist.
        """
        from devrepro.project.botpins import analyse_pins

        coverage = analyse_pins(path)
        payload = {
            "bots": [
                {
                    "kind": bot.kind,
                    "path": bot.path,
                    "ecosystems": list(bot.ecosystems),
                    "enabled_managers": list(bot.enabled_managers),
                    "restricts_managers": bot.restricts_managers,
                }
                for bot in coverage.bots
            ],
            "covered": [{"path": p.path, "kind": p.kind} for p in coverage.covered],
            "uncovered": [{"path": p.path, "kind": p.kind} for p in coverage.uncovered],
        }

        if json_out:
            emit(payload, True)
            raise typer.Exit(ExitCode.READY)

        if not coverage.configured:
            typer.echo("No Dependabot or Renovate configuration found.")
            typer.echo(
                "That is not a finding: plenty of teams update toolchains another way. "
                "This command has nothing to check against."
            )
            raise typer.Exit(ExitCode.READY)

        for bot in coverage.bots:
            detail = (
                ", ".join(bot.ecosystems)
                if bot.kind == "dependabot"
                else (
                    "enabledManagers: " + ", ".join(bot.enabled_managers)
                    if bot.restricts_managers
                    else "all managers (enabledManagers unset)"
                )
            )
            typer.echo(f"{bot.kind} ({bot.path}): {detail or 'nothing declared'}")
        typer.echo("")

        for pin in coverage.covered:
            typer.echo(f"  [watched]   {pin.path} ({pin.kind})")
        for pin in coverage.uncovered:
            secho(f"  [unwatched] {pin.path} ({pin.kind})", fg="yellow")

        if coverage.uncovered:
            typer.echo("")
            typer.echo(
                "An unwatched pin never gets a bump pull request. Dependabot has no "
                "ecosystem for version-manager pins; Renovate's nvm, asdf and mise "
                "managers do read them."
            )
        raise typer.Exit(ExitCode.READY_WITH_WARNINGS if coverage.uncovered else ExitCode.READY)

    @app.command()
    def watch(
        path: Path = typer.Option(Path(), "--path", help="Repository root."),
        interval: float = typer.Option(1.0, "--interval", help="Seconds between polls."),
        quiet_period: float = typer.Option(
            1.5, "--quiet-period", help="Seconds of stillness before re-checking."
        ),
        once: bool = typer.Option(False, "--once", help="List what would be watched and exit."),
        json_out: bool = JsonOption,
    ) -> None:
        """Re-check when the environment contract changes, and not otherwise.

        Watches lockfiles, manifests, toolchain pins, CI workflows, container
        definitions and policy -- the same set `guard --scope changed` gates
        on. Editing a function body changes nothing about what the machine must
        provide, and a scan triggered by it is five seconds of nothing.

        Runs until interrupted.
        """
        from devrepro.cli.pipeline import run_scan
        from devrepro.core.models import FindingState
        from devrepro.watch import Change, watched_paths
        from devrepro.watch import watch as watch_loop

        targets = watched_paths(path)
        if once:
            payload = [p.relative_to(path).as_posix() for p in targets]
            if json_out:
                emit({"watching": payload}, True)
            else:
                typer.echo(f"Watching {len(payload)} environment-contract file(s):")
                for name in payload:
                    typer.echo(f"  {name}")
            raise typer.Exit(ExitCode.READY)

        typer.echo(f"Watching {len(targets)} environment-contract file(s). Ctrl-C to stop.")

        def recheck(change: Change) -> None:
            typer.echo("")
            typer.echo(f"[{time.strftime('%H:%M:%S')}] {change.describe()}")
            report = run_scan()
            blocking = [
                f.rule_id
                for f in report.findings
                if f.state in (FindingState.ERROR, FindingState.BLOCKED)
            ]
            if blocking:
                secho(f"  BLOCKED by {len(blocking)} finding(s):", fg="red")
                for rule_id in blocking:
                    typer.echo(f"    - {rule_id}")
            else:
                secho("  ok", fg="green")

        try:
            watch_loop(
                path,
                recheck,
                interval=interval,
                quiet_period=quiet_period,
                clock=time.monotonic,
                sleeper=time.sleep,
            )
        except KeyboardInterrupt:
            typer.echo("")
            typer.echo("Stopped.")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def onboard(
        policy_path: Path | None = PolicyOption,
        output: Path | None = typer.Option(None, "-o", "--output"),
        json_out: bool = JsonOption,
    ) -> None:
        """A setup script for what THIS machine is missing. Nothing is executed.

        Onboarding documents rot because they describe a machine nobody has:
        they list every dependency, including the eleven a new starter already
        had, and the one that matters is on line 40. This emits the difference
        between what the policy requires and what the scan found, which on most
        machines is two lines.

        The script is output, not an action. Commands that pipe a remote script
        into a shell are printed commented out, because that is a decision and
        a generated file should not make it on somebody's behalf.
        """
        from devrepro.cli.pipeline import run_scan
        from devrepro.generators.onboarding import (
            missing_requirements,
            render_onboarding_script,
        )
        from devrepro.probes.base import current_platform

        policy = load_policy_or_none(policy_path)
        if policy is None:
            secho(
                "onboard needs a policy: it emits the gap between what the project "
                "requires and what this machine has, and without a policy there is no "
                "first half. Run `devrepro init` to scaffold a .devrepro.toml.",
                fg="red",
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)

        report = run_scan(policy=policy)
        script = render_onboarding_script(
            report,
            policy,
            platform=current_platform(),
            generated_at=report.created_at.isoformat(),
        )

        if output is not None:
            output.write_text(script, encoding="utf-8")

        if json_out:
            emit(
                {
                    "missing": [
                        {"name": m.name, "required": m.required, "detected": m.detected}
                        for m in missing_requirements(report, policy)
                    ],
                    "script": script,
                },
                True,
            )
        else:
            typer.echo(script if output is None else f"wrote {output}")
        raise typer.Exit(ExitCode.READY)
