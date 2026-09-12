"""Remediation commands: plan, fix, rules, plugins."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  (Typer resolves command annotations at runtime)

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none, secho
from devrepro.core.errors import DevReproError
from devrepro.core.exit_codes import ExitCode

#: How long a single remediation command may run before it is abandoned.
#: Generous, because these are installs and configuration writes rather than
#: version probes -- and bounded, because a wedged command inside `--yes`
#: leaves the machine half-changed with no way back to the prompt.
REMEDIATION_TIMEOUT_SECONDS = 300.0


def _run_remediation_command(command: tuple[str, ...]) -> int:
    """Actually run one remediation command, and say so while doing it.

    This used to be `lambda cmd: 0` -- a function that reported success for
    every command without running any of them. No planned step carries commands
    today, so it was unreachable, which is the only reason it survived. It is
    still the worst possible thing to leave in place: the first time somebody
    wires a command to a step, `devrepro fix --yes` would report `executed` for
    a command that never ran, on a path where the user has explicitly asked for
    execution and will not check.

    Printed before it runs, not after. If a command hangs or takes the machine
    down with it, the last line on screen has to be the one that says what was
    running.
    """
    from devrepro.core.runner import SubprocessRunner

    typer.secho(f"  $ {' '.join(command)}", fg=typer.colors.CYAN, err=True)
    result = SubprocessRunner().run(list(command), timeout=REMEDIATION_TIMEOUT_SECONDS)
    if result.not_found:
        typer.secho(f"    {command[0]}: not found on PATH", fg=typer.colors.YELLOW, err=True)
    elif result.timed_out:
        typer.secho(
            f"    timed out after {REMEDIATION_TIMEOUT_SECONDS:.0f}s",
            fg=typer.colors.YELLOW,
            err=True,
        )
    elif result.returncode != 0 and result.stderr.strip():
        # The command's own words. A remediation that failed is a thing the
        # person has to act on, and "rc=1" does not tell them what to do.
        typer.secho(
            f"    {result.stderr.strip().splitlines()[0]}", fg=typer.colors.YELLOW, err=True
        )
    return result.returncode


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
            results = execute_plan(steps, confirmed=yes, executor=_run_remediation_command)
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
            if json_out:
                emit({"packs": list(PACK_NAMES)}, True)
            else:
                # A Python dict repr is not a human interface. The same fault
                # was fixed in `check` and `generate`; it survived here because
                # a one-key dict reads almost like a sentence.
                typer.echo(f"{len(PACK_NAMES)} rule packs:")
                for name in PACK_NAMES:
                    typer.echo(f"  {name}")
                typer.echo("")
                typer.echo("`devrepro rules --catalog` for every documented rule id.")
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

    @app.command("rules-test")
    def rules_test(
        module: str = typer.Argument(..., help="Import path of the pack module, e.g. mypack.rules"),
        attribute: str = typer.Option(
            "evaluate", "--attribute", help="Callable inside the module to run."
        ),
        json_out: bool = JsonOption,
    ) -> None:
        """Check a rule pack for the four things that make one wrong.

        Findings with no evidence, ids that collide with a built-in prefix,
        packs that mutate the machine, and packs that raise -- the engine turns
        the last into a `rulepack/<name>/failed` finding, which is right for a
        user and means an author never sees their own crash.

        **This imports and runs your module**, which is executing code. It takes
        an explicit import path rather than discovering installed packs and
        running them all, so it is always clear whose code is about to run.
        """
        import importlib

        from devrepro.core.models import PlatformInfo
        from devrepro.plugins.testkit import check_pack
        from devrepro.rules.base import PACK_NAMES, RuleContext

        secho(f"Importing {module} -- this executes it.", fg="yellow", err=True)
        try:
            loaded = importlib.import_module(module)
        except ImportError as exc:
            secho(f"cannot import {module}: {exc}", fg="red", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR) from exc

        evaluate = getattr(loaded, attribute, None)
        if not callable(evaluate):
            secho(f"{module} has no callable {attribute!r}", fg="red", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR)

        # A minimal context: empty rather than invented. A harness that supplied
        # a plausible machine would test the pack against a fiction, and the
        # interesting bugs in a rule pack are all about unusual state.
        ctx = RuleContext(
            platform_info=PlatformInfo(os_name="Linux", os_version="0", arch="x86_64")
        )
        # The reserved-prefix check is for third-party packs. Run against a
        # built-in it would flag the pack for using its own name, which is
        # confusing rather than useful -- the harness is here to help authors,
        # and its first output should not be a false positive.
        reserved = () if module.startswith("devrepro.") else PACK_NAMES
        report = check_pack(evaluate, ctx, reserved_prefixes=reserved)

        if json_out:
            emit(report.as_dict(), True)
        elif report.ok:
            typer.echo(f"ok     {report.findings_produced} finding(s), no problems")
        else:
            for problem in report.problems:
                secho("  " + problem.describe(), fg="red")
            typer.echo("")
            typer.echo("See docs/PLUGINS.md for what each of these does to a user.")
        raise typer.Exit(ExitCode.READY if report.ok else ExitCode.READY_WITH_WARNINGS)

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
