"""DevRepro Doctor CLI.

All major commands support --json and stable exit codes:
  0 READY · 1 READY_WITH_WARNINGS · 2 BLOCKED · 3 INTERNAL_ERROR · 4 USAGE
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from devrepro import __version__
from devrepro.core.errors import DevReproError
from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import FindingState

app = typer.Typer(
    name="devrepro",
    help="Project-aware developer-environment diagnostics, reproducibility "
    "snapshots, machine-to-machine diffs and explainable safe remediation.",
    no_args_is_help=True,
    add_completion=False,
)

JsonOption = typer.Option(False, "--json", help="Emit machine-readable JSON.")
PolicyOption = typer.Option(None, "--policy", help="Path to .devrepro.toml policy.")


def _load_policy(path: Optional[Path]):
    if path is None:
        return None
    from devrepro.project.policy import load_policy

    return load_policy(path)


def _emit(data: object, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(data)


def _exit_for(findings_states: set[str]) -> int:
    if "BLOCKED" in findings_states or "ERROR" in findings_states:
        return ExitCode.BLOCKED
    if "WARN" in findings_states or "UNKNOWN" in findings_states:
        return ExitCode.READY_WITH_WARNINGS
    return ExitCode.READY


@app.command("check")
def check_cmd(
    policy_path: Path = typer.Option(
        Path(".devrepro.toml"), "--policy", help="Path to .devrepro.toml policy."
    ),
    project_dir: Optional[Path] = typer.Option(None, "--project", help="Project root."),
    json_out: bool = JsonOption,
) -> None:
    """Validate a .devrepro.toml policy and check the machine against it.

    Stable exit codes: 0 READY, 1 READY_WITH_WARNINGS, 2 BLOCKED,
    4 invalid policy (see devrepro.core.exit_codes).
    """
    from devrepro.core.exit_codes import ExitCode
    from devrepro.project.policy import load_policy

    try:
        policy = load_policy(policy_path)
    except Exception as exc:  # noqa: BLE001 - user-facing validation error
        if json_out:
            typer.echo(json.dumps({"error": f"invalid policy: {exc}"}, indent=2))
        else:
            typer.secho(f"Invalid policy {policy_path}: {exc}", fg=typer.RED)
        raise SystemExit(ExitCode.USAGE_ERROR) from exc

    from devrepro.cli.pipeline import run_scan

    report = run_scan(project_dir=project_dir, policy=policy)
    findings = list(report.findings)
    states = {f.state.value for f in findings}
    payload = {
        "policy": str(policy_path),
        "verdict": (
            "BLOCKED" if ("BLOCKED" in states or "ERROR" in states)
            else "READY_WITH_WARNINGS" if (states - {"PASS", "INFO"})
            else "READY"
        ),
        "findings": [f.model_dump(mode="json") for f in findings],
        "privacy": report.privacy,
    }
    _emit(payload, json_out)
    raise SystemExit(_exit_for(states))


@app.command()
def doctor(
    json_out: bool = JsonOption,
    policy_path: Optional[Path] = PolicyOption,
    project_dir: Optional[Path] = typer.Option(None, "--project", help="Project root."),
) -> None:
    """Full read-only diagnostic scan of machine + project."""
    from devrepro.cli.pipeline import run_scan

    try:
        report = run_scan(project_dir=project_dir, policy=_load_policy(policy_path))
    except DevReproError as exc:
        typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(exc.exit_code.value)
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
            key=lambda x: ["BLOCKED", "ERROR", "WARN", "UNKNOWN", "INFO", "PASS"].index(x.state.value),
        ):
            color = {
                "BLOCKED": "red", "ERROR": "red", "WARN": "yellow",
                "UNKNOWN": "grey50", "INFO": "blue", "PASS": "green",
            }[f.state.value]
            table.add_row(f"[{color}]{f.state.value}[/{color}]", f.rule_id, f.summary[:100])
        console.print(table)
        if report.score:
            console.print(
                f"Reproducibility completeness: {report.score.total}/{report.score.possible} "
                f"({report.score.percent}%) — declaration completeness only; not a guarantee."
            )
        console.print("[grey50]Read-only scan. No data left this machine.[/grey50]")
    raise typer.Exit(_exit_for({f.state.value for f in report.findings}))


@app.command()
def info(json_out: bool = JsonOption) -> None:
    """Quick machine summary (OS, shell, key tool versions)."""
    from devrepro.probes.base import ProbeContext
    from devrepro.probes.registry import build_default_probes
    from devrepro.core.runner import SubprocessRunner

    ctx = ProbeContext.capture(SubprocessRunner())
    engine_results = {}
    from devrepro.probes.base import ProbeEngine

    wanted = {"system/os", "system/shell", "system/resources"}
    probes = [p for p in build_default_probes(ctx) if p.id in wanted]
    results = ProbeEngine(probes).run_all()
    data = {pid: getattr(r, "data", {}) for pid, r in results.items()}
    if json_out:
        _emit(data, True)
    else:
        for pid, d in data.items():
            typer.echo(f"{pid}: {d}")
    raise typer.Exit(ExitCode.READY)


@app.command()
def scan(
    json_out: bool = JsonOption,
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Write report to file."),
    fmt: str = typer.Option("json", "--format", help="json|markdown|junit|html"),
    policy_path: Optional[Path] = PolicyOption,
) -> None:
    """Run a scan and emit a report artifact (default format: json)."""
    from devrepro.cli.pipeline import run_scan

    report = run_scan(policy=_load_policy(policy_path))
    renderers = {
        "json": lambda: __import__("devrepro.reports.renderers", fromlist=["render_json"]).render_json(report),
        "markdown": lambda: __import__("devrepro.reports.renderers", fromlist=["render_markdown"]).render_markdown(report),
        "junit": lambda: __import__("devrepro.reports.renderers", fromlist=["render_junit"]).render_junit(report),
        "html": lambda: __import__("devrepro.reports.renderers", fromlist=["render_html"]).render_html(report),
    }
    renderer = renderers.get(fmt)
    if renderer is None:
        typer.secho(f"unknown format {fmt!r}; choose json|markdown|junit|html",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    content = renderer()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        _emit(str(output), json_out)
    else:
        typer.echo(content)
    raise typer.Exit(_exit_for({f.state.value for f in report.findings}))


@app.command()
def project(
    path: Path = typer.Argument(Path("."), help="Project root."),
    json_out: bool = JsonOption,
) -> None:
    """Show what this project declares (requirements, lockfiles, CI)."""
    from devrepro.project.detectors import detect_project_kind, detect_requirements

    kinds = detect_project_kind(path)
    reqs = detect_requirements(path)
    payload = {
        "kinds": kinds,
        "requirements": [r.model_dump(mode="json") for r in reqs],
    }
    if json_out:
        _emit(payload, True)
    else:
        typer.echo(f"Ecosystems: {', '.join(kinds) or 'none detected'}")
        for r in reqs:
            note = f" ({r.note})" if r.note else ""
            typer.echo(f"  [{r.ecosystem}] {r.name} {r.spec!r} <- {r.source_file}{note}")
    raise typer.Exit(ExitCode.READY)


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
        _emit(payload, True)
        raise typer.Exit(ExitCode.READY if matches else ExitCode.BLOCKED)
    if not matches:
        typer.secho(f"'{name}' not found on PATH.", fg=typer.colors.RED)
        raise typer.Exit(ExitCode.BLOCKED)
    typer.echo(f"'{name}' resolves to: {matches[0]}")
    typer.echo("Why it wins: its directory appears earliest in PATH "
               "(earlier entries take precedence).")
    if all_matches and len(matches) > 1:
        typer.echo("Shadowed installations:")
        for m in matches[1:]:
            typer.echo(f"  - {m}")
    raise typer.Exit(ExitCode.READY)


@app.command()
def snapshot(
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
    save_history: bool = typer.Option(True, "--history/--no-history"),
    json_out: bool = JsonOption,
    policy_path: Optional[Path] = PolicyOption,
) -> None:
    """Create a privacy-sanitized environment snapshot."""
    from devrepro.cli.pipeline import run_scan
    from devrepro.snapshots.store import snapshot_from_report

    report = run_scan(policy=_load_policy(policy_path))
    snap = snapshot_from_report(report)
    target = output or Path.cwd() / f"{snap.snapshot_id}.devrepro-snapshot.json"
    from devrepro.snapshots.store import save_snapshot

    saved = save_snapshot(snap, target)
    if save_history:
        from devrepro.snapshots.history import HistoryStore

        HistoryStore().save(snap)
    _emit(str(saved), json_out)
    raise typer.Exit(ExitCode.READY)


@app.command()
def diff(
    a: Path = typer.Argument(..., exists=True, readable=True),
    b: Path = typer.Argument(..., exists=True, readable=True),
    fmt: str = typer.Option("terminal", "--format", help="terminal|json|markdown|html"),
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
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
        _emit(str(output), json_out)
    else:
        typer.echo(content)
    has_critical = any(e.project_critical for e in result.entries)
    raise typer.Exit(ExitCode.BLOCKED if has_critical else ExitCode.READY)


@app.command()
def preflight(
    policy_path: Optional[Path] = PolicyOption,
    json_out: bool = JsonOption,
) -> None:
    """CI/onboarding gate: READY / READY_WITH_WARNINGS / BLOCKED + exit code."""
    from devrepro.cli.pipeline import run_scan

    report = run_scan(policy=_load_policy(policy_path))
    worst = report.worst_state().value
    verdict = {
        "PASS": "READY", "INFO": "READY",
        "WARN": "READY_WITH_WARNINGS", "UNKNOWN": "READY_WITH_WARNINGS",
        "ERROR": "BLOCKED", "BLOCKED": "BLOCKED",
    }.get(worst, "READY_WITH_WARNINGS")
    blockers = [
        f.rule_id for f in report.findings
        if f.state in (FindingState.ERROR, FindingState.BLOCKED)
    ]
    payload = {"verdict": verdict, "blockers": blockers}
    if json_out:
        _emit(payload, True)
    else:
        typer.echo(f"PREFLIGHT: {verdict}")
        for b in blockers:
            typer.echo(f"  blocker: {b}")
    raise typer.Exit({
        "READY": ExitCode.READY,
        "READY_WITH_WARNINGS": ExitCode.READY_WITH_WARNINGS,
        "BLOCKED": ExitCode.BLOCKED,
    }[verdict])


@app.command()
def plan(
    policy_path: Optional[Path] = PolicyOption,
    json_out: bool = JsonOption,
) -> None:
    """Dry-run remediation plan. Nothing is executed."""
    from devrepro.cli.pipeline import run_scan
    from devrepro.remediation.planner import build_plan

    report = run_scan(policy=_load_policy(policy_path))
    steps = build_plan(list(report.findings))
    payload = [s.model_dump(mode="json") for s in steps]
    if json_out:
        _emit(payload, True)
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
        raise typer.Exit(ExitCode.USAGE_ERROR)
    _emit(results, json_out)
    raise typer.Exit(ExitCode.READY)


@app.command()
def rules(json_out: bool = JsonOption) -> None:
    """List available rule packs."""
    from devrepro.rules.base import PACK_NAMES

    _emit({"packs": list(PACK_NAMES)}, json_out)
    raise typer.Exit(ExitCode.READY)


@app.command()
def plugins(json_out: bool = JsonOption) -> None:
    """List installed plugins per entry-point group."""
    from devrepro.plugins.loader import PLUGIN_GROUPS, API_VERSION, list_plugins

    found = list_plugins()
    payload = {"api_version": API_VERSION, "groups": found}
    if json_out:
        _emit(payload, True)
    else:
        typer.echo(f"Plugin API version: {API_VERSION}")
        for group in PLUGIN_GROUPS:
            entries = found.get(group, [])
            typer.echo(f"{group}: {len(entries)}")
            for e in entries:
                typer.echo(f"  {e}")
    raise typer.Exit(ExitCode.READY)


@app.command()
def report(
    input_file: Path = typer.Argument(..., exists=True, readable=True,
                                     help="A saved JSON scan report."),
    fmt: str = typer.Option("markdown", "--format", help="markdown|junit|html|json"),
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
) -> None:
    """Re-render a saved JSON report into another format."""
    from devrepro.core.models import ScanReport
    from devrepro.reports.renderers import (
        render_html, render_junit, render_json, render_markdown,
    )

    data = ScanReport.model_validate(json.loads(input_file.read_text(encoding="utf-8")))
    renderers = {"markdown": render_markdown, "junit": render_junit,
                 "html": render_html, "json": render_json}
    renderer = renderers.get(fmt)
    if renderer is None:
        typer.secho(f"unknown format {fmt!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    content = renderer(data)
    if output is not None:
        output.write_text(content, encoding="utf-8")
        typer.echo(str(output))
    else:
        typer.echo(content)
    raise typer.Exit(ExitCode.READY)


@app.command()
def export(
    input_file: Path = typer.Argument(..., exists=True, readable=True),
    out_dir: Path = typer.Option(Path("./devrepro-export"), "--out-dir"),
) -> None:
    """Export a report/snapshot to all formats in a directory."""
    from devrepro.exporters.base import FileExporter
    from devrepro.reports.renderers import (
        render_html, render_junit, render_json, render_markdown,
    )

    from devrepro.core.models import ScanReport

    raw = input_file.read_text(encoding="utf-8")
    exporter = FileExporter(out_dir)
    locations = []
    if '"findings"' in raw:
        data = ScanReport.model_validate(json.loads(raw))
        for fmt, fn in (("json", render_json), ("md", render_markdown),
                        ("junit.xml", render_junit), ("html", render_html)):
            locations.append(exporter.export(fn(data), filename=f"report.{fmt}"))
    else:
        locations.append(exporter.export(raw, filename=input_file.name))
    for loc in locations:
        typer.echo(loc)
    raise typer.Exit(ExitCode.READY)


@app.command()
def history(
    json_out: bool = JsonOption,
) -> None:
    """Show local sanitized history and drift since the previous snapshot."""
    from devrepro.snapshots.history import HistoryStore, compute_drift

    store = HistoryStore()
    snaps = store.latest(2)
    if len(snaps) < 2:
        _emit({"message": "Need at least two stored snapshots; run `devrepro snapshot` twice."},
              json_out)
        raise typer.Exit(ExitCode.READY)
    drift = compute_drift(snaps[0], snaps[1])
    payload = [d.as_dict() for d in drift]
    if json_out:
        _emit(payload, True)
    else:
        typer.echo(f"Drift across last {len(snaps)} snapshots:")
        for d in drift:
            typer.echo(f"  [{d.kind}] {d.name}: {d.detail}")
    raise typer.Exit(ExitCode.READY)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address. localhost by default."),
    port: int = typer.Option(8642, help="Port."),
) -> None:
    """Serve sanitized scan/report data + frontend on localhost ONLY."""
    from devrepro.cli.server import serve as _serve

    _serve(host=host, port=port)
    raise typer.Exit(ExitCode.READY)


@app.command()
def self_test(json_out: bool = JsonOption) -> None:
    """Verify the probe/rule/privacy machinery works on this install."""
    checks: dict[str, str] = {}

    def check(name: str, fn) -> None:
        try:
            fn()
            checks[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks[name] = f"fail: {type(exc).__name__}: {exc}"

    check("versioning", lambda: _selftest_versioning())
    check("privacy-redaction", lambda: _selftest_privacy())
    check("models-roundtrip", lambda: _selftest_models())
    ok = all(v == "ok" for v in checks.values())
    _emit(checks, json_out)
    raise typer.Exit(ExitCode.READY if ok else ExitCode.INTERNAL_ERROR)


def _selftest_versioning() -> None:
    from devrepro.core.versioning import satisfies

    assert satisfies("3.12.4", ">=3.11,<3.14")
    assert not satisfies("3.14.0", ">=3.11,<3.14")
    assert satisfies("20.1.0", ">=20")


def _selftest_privacy() -> None:
    from devrepro.privacy.gate import PrivacyGate, assert_no_secrets, scan_for_secrets

    gate = PrivacyGate(home=Path("/home/testuser"), username="testuser")
    red = gate.redact("/home/testuser/project by testuser")
    assert "/home/testuser" not in red and "testuser" not in red
    assert scan_for_secrets("token ghp_" + "a" * 30)
    try:
        assert_no_secrets("AKIA" + "B" * 16)
    except Exception:
        pass
    else:
        raise AssertionError("secret scanner missed AWS key")


def _selftest_models() -> None:
    from devrepro.core.models import (
        Evidence, Finding, FindingState, PlatformInfo, ScanReport,
    )

    f = Finding(
        rule_id="t/x", state=FindingState.INFO, summary="s",
        evidence=(Evidence(source="system", excerpt="e"),),
    )
    r = ScanReport(devrepro_version=__version__,
                   platform=PlatformInfo(os_name="Test", os_version="1", arch="x"))
    ScanReport.model_validate(json.loads(json.dumps(r.model_dump(mode="json"), default=str)))
    assert f.rule_id == "t/x"


def main() -> None:
    try:
        app()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            sys.exit(code)
        sys.exit(int(bool(code)))


if __name__ == "__main__":
    main()