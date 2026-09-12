"""Service commands: serve, self-test, bench, mcp, server-backup, server-restore."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from devrepro import __version__
from devrepro.cli.common import JsonOption, emit
from devrepro.core.exit_codes import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable


def register(app: typer.Typer) -> None:
    """Attach service commands to the root app."""

    @app.command()
    def serve(
        host: str = typer.Option("127.0.0.1", help="Bind address. localhost by default."),
        port: int = typer.Option(8642, help="Port."),
    ) -> None:
        """Serve sanitized scan/report data + frontend on localhost ONLY."""
        from devrepro.cli.server import serve as _serve

        _serve(host=host, port=port)
        raise typer.Exit(ExitCode.READY)

    @app.command("self-test")
    def self_test(json_out: bool = JsonOption) -> None:
        """Verify the probe/rule/privacy machinery works on this install."""
        checks: dict[str, str] = {}

        def check(name: str, fn: Callable[[], None]) -> None:
            try:
                fn()
                checks[name] = "ok"
            except Exception as exc:
                checks[name] = f"fail: {type(exc).__name__}: {exc}"

        check("versioning", _selftest_versioning)
        check("privacy-redaction", _selftest_privacy)
        check("models-roundtrip", _selftest_models)
        ok = all(v == "ok" for v in checks.values())
        emit(checks, json_out)
        raise typer.Exit(ExitCode.READY if ok else ExitCode.INTERNAL_ERROR)

    @app.command()
    def bench(
        json_out: bool = JsonOption,
        parallel: bool = typer.Option(
            False,
            "--parallel",
            help="Measure what a user waits for, instead of what each probe costs.",
        ),
        scan: bool = typer.Option(
            False, "--scan", help="Time a whole scan by phase instead of probe by probe."
        ),
        path: Path = typer.Option(Path(), "--path", help="Project directory to scan."),
    ) -> None:
        """Measure where a scan spends its time, probe by probe.

        This project has already lost the speed argument once: a scan took 26
        seconds, of which 16 were resolving PATH, and finding that took an
        afternoon because nothing in the tool could say which part was slow.

        Sequential by default, which is the measurement that can be attributed:
        run in parallel, eight probes share a thread pool and their wall times
        overlap, so no single number is a probe's actual cost. `--parallel`
        reports the wall time a user actually waits for and leaves the
        per-probe figures at zero rather than printing plausible ones that are
        wrong.

        Read-only, like every other default here -- it runs the same probes a
        scan runs, and reports nothing a scan would not.
        """
        from devrepro.bench import bench_probes, bench_scan
        from devrepro.core.runner import SubprocessRunner
        from devrepro.probes.base import ProbeContext
        from devrepro.probes.registry import build_default_probes

        if scan:
            report = bench_scan(path)
        else:
            ctx = ProbeContext.capture(SubprocessRunner(), project_dir=path)
            report = bench_probes(build_default_probes(ctx), parallel=parallel)

        if json_out:
            emit(report.as_dict(), True)
            raise typer.Exit(ExitCode.READY)

        if report.probes:
            typer.echo(f"{'probe':<26} {'time':>9} {'cmds':>6} {'findings':>9}")
            typer.echo("-" * 53)
            for timing in sorted(report.probes, key=lambda t: t.seconds, reverse=True):
                commands = "-" if timing.commands is None else str(timing.commands)
                typer.echo(
                    f"{timing.probe_id:<26} {timing.milliseconds:>7.0f}ms "
                    f"{commands:>6} {timing.findings:>9}"
                )
                if timing.error:
                    typer.echo(f"{'':<26} {timing.error}")

        for phase in report.phases:
            typer.echo(f"{phase.name:<26} {phase.seconds * 1000:>7.0f}ms")

        typer.echo("-" * 53)
        typer.echo(f"{'total (wall clock)':<26} {report.total_seconds * 1000:>7.0f}ms")
        slowest = report.slowest
        if slowest and slowest.seconds > 0:
            share = slowest.seconds / report.total_seconds * 100 if report.total_seconds else 0
            typer.echo(f"slowest: {slowest.probe_id} ({share:.0f}% of the run)")
        for note in report.notes:
            typer.echo(note)

        raise typer.Exit(ExitCode.READY)

    @app.command()
    def mcp(
        root: Path = typer.Option(
            Path(),
            "--root",
            help="Directory the server may inspect. Every path argument is confined to it.",
        ),
        cache_seconds: float = typer.Option(
            300.0,
            "--cache-seconds",
            help="How long a scan stays usable before a tool call re-scans.",
        ),
    ) -> None:
        """Serve read-only diagnostics over MCP on stdin/stdout.

        `docs/MCP-EXPOSURE.md` is the decision this implements. Read-only
        commands only; `fix`, `serve` and `server-*` are refused by name, with
        the reason returned to the caller rather than simply being absent --
        a model that asks for `fix` should learn why the answer is no.

        Three properties that decision made prerequisites:

        Every result carries an explicit `verdict`. A process exit code does
        not cross this boundary, and `BLOCKED = 2` means something different in
        three sibling projects.

        Reports are cached, because a five-second scan per tool call would
        dominate a conversation. `refresh: true` on any call forces a new one.

        Paths are confined to `--root`, resolved before the check so `..` and a
        symlink fail the same way. Which directory to inspect is authority this
        does not delegate to a model.

        It speaks newline-delimited JSON-RPC on stdin and stdout, so it is
        configured as a stdio server:

            devrepro mcp --root /path/to/project
        """
        from devrepro.mcp import serve_stdio

        raise typer.Exit(serve_stdio(root, cache_seconds=cache_seconds))

    @app.command("server-backup")
    def server_backup_cmd(
        db_path: Path = typer.Argument(..., exists=True, readable=True, help="Path to fleet.db."),
        output: Path | None = typer.Option(None, "-o", "--output", help="Archive path."),
        json_out: bool = JsonOption,
    ) -> None:
        """Back up the self-hosted server database (checksummed archive)."""
        from devrepro.server.backup import backup_database

        result = backup_database(db_path, output)
        payload = {
            "archive": str(result.path),
            "members": result.members,
            "sha256": result.sha256,
        }
        if json_out:
            emit(payload, True)
        else:
            # A Python dict repr is not a human interface. The same fault was
            # fixed in `check`, `generate` and `rules`; it survived here because
            # nothing invoked this command, and an operator reading it is
            # usually restoring a fleet database under time pressure.
            typer.echo(f"archive:  {result.path}")
            typer.echo(f"members:  {result.members}")
            typer.echo(f"sha256:   {result.sha256}")
            typer.echo("")
            typer.echo(f"Restore with: devrepro server-restore {result.path} <target>")
        raise typer.Exit(ExitCode.READY)

    @app.command("server-restore")
    def server_restore_cmd(
        archive: Path = typer.Argument(..., exists=True, readable=True),
        target: Path = typer.Argument(..., help="Target path for the restored database."),
        overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing DB."),
        json_out: bool = JsonOption,
    ) -> None:
        """Restore a server backup after verifying every manifest checksum."""
        from devrepro.server.backup import RestoreError, restore_database

        try:
            restored = restore_database(archive, target, overwrite=overwrite)
        except RestoreError as exc:
            message = str(exc)
            if "refusing to overwrite" in message:
                # The library cannot know what this CLI calls the flag.
                message += "; pass --overwrite to replace it"
            typer.echo(f"restore refused: {message}", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR) from exc
        if json_out:
            emit({"restored": str(restored)}, True)
        else:
            typer.echo(f"restored: {restored}")
        raise typer.Exit(ExitCode.READY)


def _selftest_versioning() -> None:
    from devrepro.core.versioning import satisfies

    assert satisfies("3.12.4", ">=3.11,<3.14")  # noqa: S101
    assert not satisfies("3.14.0", ">=3.11,<3.14")  # noqa: S101
    assert satisfies("20.1.0", ">=20")  # noqa: S101


def _selftest_privacy() -> None:
    from devrepro.privacy.gate import PrivacyGate, assert_no_secrets, scan_for_secrets

    gate = PrivacyGate(home=Path("/home/testuser"), username="testuser")
    red = gate.redact("/home/testuser/project by testuser")
    assert "/home/testuser" not in red and "testuser" not in red  # noqa: S101
    assert scan_for_secrets("token ghp_" + "a" * 30)  # noqa: S101
    try:
        assert_no_secrets("AKIA" + "B" * 16)
    except Exception:
        pass
    else:
        raise AssertionError("secret scanner missed AWS key")


def _selftest_models() -> None:
    from devrepro.core.models import (
        Evidence,
        Finding,
        FindingState,
        PlatformInfo,
        ScanReport,
    )

    f = Finding(
        rule_id="t/x",
        state=FindingState.INFO,
        summary="s",
        evidence=(Evidence(source="system", excerpt="e"),),
    )
    r = ScanReport(
        devrepro_version=__version__,
        platform=PlatformInfo(os_name="Test", os_version="1", arch="x"),
    )
    ScanReport.model_validate(json.loads(json.dumps(r.model_dump(mode="json"), default=str)))
    assert f.rule_id == "t/x"  # noqa: S101
