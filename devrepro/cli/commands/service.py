"""Service commands: serve, self-test, server-backup, server-restore."""

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

    @app.command("server-backup")
    def server_backup_cmd(
        db_path: Path = typer.Argument(..., exists=True, readable=True, help="Path to fleet.db."),
        output: Path | None = typer.Option(None, "-o", "--output", help="Archive path."),
        json_out: bool = JsonOption,
    ) -> None:
        """Back up the self-hosted server database (checksummed archive)."""
        from devrepro.server.backup import backup_database

        result = backup_database(db_path, output)
        emit(
            {
                "archive": str(result.path),
                "members": result.members,
                "sha256": result.sha256,
            },
            json_out,
        )
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
            typer.echo(f"restore refused: {exc}", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR) from exc
        emit({"restored": str(restored)}, json_out)
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
