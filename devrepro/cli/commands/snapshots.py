"""Snapshot commands: snapshot, diff, history, drift, sign/verify, bundle."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none
from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach snapshot commands to the root app."""

    @app.command()
    def snapshot(
        output: Path | None = typer.Option(None, "-o", "--output"),
        save_history: bool = typer.Option(True, "--history/--no-history"),
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Create a privacy-sanitized environment snapshot."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.snapshots.store import save_snapshot, snapshot_from_report

        report = run_scan(policy=load_policy_or_none(policy_path))
        snap = snapshot_from_report(report)
        target = output or Path.cwd() / f"{snap.snapshot_id}.devrepro-snapshot.json"
        saved = save_snapshot(snap, target)
        if save_history:
            from devrepro.snapshots.history import HistoryStore

            HistoryStore().save(snap)
        emit(str(saved), json_out)
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def diff(
        a: Path = typer.Argument(..., exists=True, readable=True),
        b: Path = typer.Argument(..., exists=True, readable=True),
        fmt: str = typer.Option("terminal", "--format", help="terminal|json|markdown|html"),
        output: Path | None = typer.Option(None, "-o", "--output"),
        json_out: bool = JsonOption,
    ) -> None:
        """Diff two snapshots to explain 'works on my machine'."""
        from devrepro.diff.engine import diff_snapshots
        from devrepro.snapshots.store import load_snapshot

        snap_a, snap_b = load_snapshot(a), load_snapshot(b)
        result = diff_snapshots(snap_a, snap_b)
        if fmt == "json":
            from devrepro.reports.renderers import render_diff_json

            content = render_diff_json(result)
        elif fmt == "markdown":
            from devrepro.reports.renderers import render_diff_markdown

            content = render_diff_markdown(result)
        elif fmt == "html":
            from devrepro.reports.renderers import render_diff_html

            content = render_diff_html(result)
        else:
            counts = result.counts()
            lines = [
                f"Diff {result.a_snapshot_id} -> {result.b_snapshot_id}",
                "Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
                "",
            ]
            for e in result.entries:
                crit = " [CRITICAL]" if e.project_critical else ""
                lines.append(
                    f"  [{e.classification.value:<16}] {e.component}/{e.name}: "
                    f"A={e.a_value or '-'} B={e.b_value or '-'}{crit}"
                )
            content = chr(10).join(lines)
        if output is not None:
            output.write_text(content, encoding="utf-8")
            emit(str(output), json_out)
        else:
            typer.echo(content)
        has_critical = any(e.project_critical for e in result.entries)
        raise typer.Exit(ExitCode.BLOCKED if has_critical else ExitCode.READY)

    @app.command()
    def history(
        json_out: bool = JsonOption,
    ) -> None:
        """Show local sanitized history and drift since the previous snapshot."""
        from devrepro.snapshots.history import HistoryStore, compute_drift

        store = HistoryStore()
        snaps = store.latest(2)
        if len(snaps) < 2:
            emit(
                {"message": "Need at least two stored snapshots; run `devrepro snapshot` twice."},
                json_out,
            )
            raise typer.Exit(ExitCode.READY)
        drift = compute_drift(snaps[0], snaps[1])
        payload = [d.as_dict() for d in drift]
        if json_out:
            emit(payload, True)
        else:
            typer.echo(f"Drift across last {len(snaps)} snapshots:")
            for d in drift:
                typer.echo(f"  [{d.kind}] {d.name}: {d.detail}")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def drift(
        json_out: bool = JsonOption,
    ) -> None:
        """Drift timeline + root-cause hints across stored snapshot history."""
        from devrepro.drift.timeline import build_timeline
        from devrepro.snapshots.history import HistoryStore

        snaps = HistoryStore().latest(10)
        if len(snaps) < 2:
            emit(
                {"message": "Need at least two stored snapshots; run `devrepro snapshot` twice."},
                json_out,
            )
            raise typer.Exit(ExitCode.READY)
        payloads = []
        for s in snaps:
            try:
                payloads.append(s.model_dump(mode="json"))
            except AttributeError:
                payloads.append(dict(s))
        timeline = build_timeline(payloads)
        events = [
            {
                "at_index": e.at_index,
                "component": e.component,
                "name": e.name,
                "kind": e.kind,
                "before": e.before,
                "after": e.after,
            }
            for e in timeline.events
        ]
        if json_out:
            emit({"snapshot_ids": list(timeline.snapshot_ids), "events": events}, True)
        else:
            typer.echo(f"Snapshots: {len(snaps)}; drift events: {len(events)}")
            for e in events[-20:]:
                typer.echo(
                    f"  #{e['at_index']} [{e['kind']}] {e['component']}/{e['name']}: "
                    f"{e['before'] or '-'} -> {e['after'] or '-'}"
                )
        raise typer.Exit(ExitCode.READY)

    @app.command("sign-snapshot")
    def sign_snapshot_cmd(
        snapshot_path: Path = typer.Argument(..., exists=True, readable=True),
        key_id: str = typer.Option("", "--key-id"),
    ) -> None:
        """Write a detached HMAC signature next to a snapshot file.

        The signing key is read from $DEVREPRO_SIGNING_KEY and never printed.
        """
        from devrepro.snapshots.signing import key_from_env, sign_file

        sig = sign_file(snapshot_path, key_from_env(), key_id=key_id)
        typer.echo(f"signature written: {sig}")
        raise typer.Exit(ExitCode.READY)

    @app.command("verify-snapshot")
    def verify_snapshot_cmd(
        snapshot_path: Path = typer.Argument(..., exists=True, readable=True),
    ) -> None:
        """Verify a snapshot against its sidecar .sig file ($DEVREPRO_SIGNING_KEY)."""
        from devrepro.snapshots.signing import SigningError, key_from_env, verify_file

        try:
            ok = verify_file(snapshot_path, key_from_env())
        except SigningError as exc:
            typer.echo(f"verification failed: {exc}", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR) from exc
        if ok:
            typer.echo("VERIFIED")
            raise typer.Exit(ExitCode.READY)
        typer.echo("SIGNATURE MISMATCH", err=True)
        raise typer.Exit(ExitCode.BLOCKED)

    @app.command("bundle")
    def bundle_cmd(
        output: Path = typer.Option(Path("devrepro-onboarding-bundle.tar.gz"), "-o", "--output"),
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Export an onboarding bundle (sanitized report + requirements + setup steps)."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.exporters.bundle import build_onboarding_bundle

        report = run_scan(policy=load_policy_or_none(policy_path))
        data = json.loads(json.dumps(report.model_dump(mode="json"), default=str))
        requirements: dict[str, object] = {}
        try:
            from devrepro.project.detectors import detect_requirements

            requirements = {
                "requirements": [
                    {"name": r.name, "kind": r.kind.value, "spec": r.spec, "ecosystem": r.ecosystem}
                    for r in detect_requirements(Path())
                ]
            }
        except Exception:
            requirements = {}
        out = build_onboarding_bundle(
            data, output, requirements=requirements, project_name=str(Path().resolve().name)
        )
        emit({"bundle": str(out), "members": 4}, json_out)
        raise typer.Exit(ExitCode.READY)
