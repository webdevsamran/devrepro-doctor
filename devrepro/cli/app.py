"""DevRepro Doctor CLI.

All major commands support --json and stable exit codes:
  0 READY · 1 READY_WITH_WARNINGS · 2 BLOCKED · 3 INTERNAL_ERROR · 4 USAGE
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from devrepro import __version__
from devrepro.core.errors import DevReproError
from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import FindingState, Policy

if TYPE_CHECKING:
    from collections.abc import Callable

app = typer.Typer(
    name="devrepro",
    help="Project-aware developer-environment diagnostics, reproducibility "
    "snapshots, machine-to-machine diffs and explainable safe remediation.",
    no_args_is_help=True,
    add_completion=False,
)

JsonOption = typer.Option(False, "--json", help="Emit machine-readable JSON.")
PolicyOption = typer.Option(None, "--policy", help="Path to .devrepro.toml policy.")


def _load_policy(path: Path | None) -> Policy | None:
    """Load a .devrepro.toml policy; None when no path given."""
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
    project_dir: Path | None = typer.Option(None, "--project", help="Project root."),
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
    except Exception as exc:
        if json_out:
            typer.echo(json.dumps({"error": f"invalid policy: {exc}"}, indent=2))
        else:
            typer.secho(f"Invalid policy {policy_path}: {exc}", fg="red")
        raise SystemExit(ExitCode.USAGE_ERROR) from exc

    from devrepro.cli.pipeline import run_scan

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
    _emit(payload, json_out)
    raise SystemExit(_exit_for(states))


@app.command()
def doctor(
    json_out: bool = JsonOption,
    policy_path: Path | None = PolicyOption,
    project_dir: Path | None = typer.Option(None, "--project", help="Project root."),
) -> None:
    """Full read-only diagnostic scan of machine + project."""
    from devrepro.cli.pipeline import run_scan

    try:
        report = run_scan(project_dir=project_dir, policy=_load_policy(policy_path))
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
    raise typer.Exit(_exit_for({f.state.value for f in report.findings}))


@app.command()
def info(json_out: bool = JsonOption) -> None:
    """Quick machine summary (OS, shell, key tool versions)."""
    from devrepro.core.runner import SubprocessRunner
    from devrepro.probes.base import ProbeContext
    from devrepro.probes.registry import build_default_probes

    ctx = ProbeContext.capture(SubprocessRunner())
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
    output: Path | None = typer.Option(None, "-o", "--output", help="Write report to file."),
    fmt: str = typer.Option("json", "--format", help="json|markdown|junit|html"),
    policy_path: Path | None = PolicyOption,
) -> None:
    """Run a scan and emit a report artifact (default format: json)."""
    from devrepro.cli.pipeline import run_scan

    report = run_scan(policy=_load_policy(policy_path))
    renderers = {
        "json": lambda: __import__(
            "devrepro.reports.renderers", fromlist=["render_json"]
        ).render_json(report),
        "markdown": lambda: __import__(
            "devrepro.reports.renderers", fromlist=["render_markdown"]
        ).render_markdown(report),
        "junit": lambda: __import__(
            "devrepro.reports.renderers", fromlist=["render_junit"]
        ).render_junit(report),
        "html": lambda: __import__(
            "devrepro.reports.renderers", fromlist=["render_html"]
        ).render_html(report),
    }
    renderer = renderers.get(fmt)
    if renderer is None:
        typer.secho(
            f"unknown format {fmt!r}; choose json|markdown|junit|html",
            fg=typer.colors.RED,
            err=True,
        )
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
    path: Path = typer.Argument(Path(), help="Project root."),
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
    typer.echo(
        "Why it wins: its directory appears earliest in PATH (earlier entries take precedence)."
    )
    if all_matches and len(matches) > 1:
        typer.echo("Shadowed installations:")
        for m in matches[1:]:
            typer.echo(f"  - {m}")
    raise typer.Exit(ExitCode.READY)


@app.command()
def snapshot(
    output: Path | None = typer.Option(None, "-o", "--output"),
    save_history: bool = typer.Option(True, "--history/--no-history"),
    json_out: bool = JsonOption,
    policy_path: Path | None = PolicyOption,
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
        _emit(str(output), json_out)
    else:
        typer.echo(content)
    has_critical = any(e.project_critical for e in result.entries)
    raise typer.Exit(ExitCode.BLOCKED if has_critical else ExitCode.READY)


@app.command()
def preflight(
    policy_path: Path | None = PolicyOption,
    json_out: bool = JsonOption,
) -> None:
    """CI/onboarding gate: READY / READY_WITH_WARNINGS / BLOCKED + exit code."""
    from devrepro.cli.pipeline import run_scan

    report = run_scan(policy=_load_policy(policy_path))
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
        f.rule_id for f in report.findings if f.state in (FindingState.ERROR, FindingState.BLOCKED)
    ]
    payload = {"verdict": verdict, "blockers": blockers}
    if json_out:
        _emit(payload, True)
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


@app.command()
def plan(
    policy_path: Path | None = PolicyOption,
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
        raise typer.Exit(ExitCode.USAGE_ERROR) from exc
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
    from devrepro.plugins.loader import API_VERSION, PLUGIN_GROUPS, list_plugins

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
    input_file: Path = typer.Argument(
        ..., exists=True, readable=True, help="A saved JSON scan report."
    ),
    fmt: str = typer.Option("markdown", "--format", help="markdown|junit|html|json"),
    output: Path | None = typer.Option(None, "-o", "--output"),
) -> None:
    """Re-render a saved JSON report into another format."""
    from devrepro.core.models import ScanReport
    from devrepro.reports.renderers import (
        render_html,
        render_json,
        render_junit,
        render_markdown,
    )

    data = ScanReport.model_validate(json.loads(input_file.read_text(encoding="utf-8")))
    renderers = {
        "markdown": render_markdown,
        "junit": render_junit,
        "html": render_html,
        "json": render_json,
    }
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
    from devrepro.core.models import ScanReport
    from devrepro.exporters.base import FileExporter
    from devrepro.reports.renderers import (
        render_html,
        render_json,
        render_junit,
        render_markdown,
    )

    raw = input_file.read_text(encoding="utf-8")
    exporter = FileExporter(out_dir)
    locations = []
    if '"findings"' in raw:
        data = ScanReport.model_validate(json.loads(raw))
        for fmt, fn in (
            ("json", render_json),
            ("md", render_markdown),
            ("junit.xml", render_junit),
            ("html", render_html),
        ):
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
        _emit(
            {"message": "Need at least two stored snapshots; run `devrepro snapshot` twice."},
            json_out,
        )
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
def monorepo(
    path: Path = typer.Argument(Path(), help="Repository root."),
    json_out: bool = JsonOption,
) -> None:
    """Monorepo discovery, nested-project conflicts, languages, lockfiles."""
    from devrepro.project.monorepo import analyze_monorepo

    report = analyze_monorepo(path)
    payload = {
        "root": report.root,
        "is_monorepo": report.is_monorepo,
        "workspace_markers": list(report.workspace_markers),
        "projects": [
            {"path": p.path, "ecosystem": p.ecosystem, "depth": p.depth} for p in report.projects
        ],
        "conflicts": [
            {
                "tool": c.tool,
                "parent_path": c.parent_path,
                "parent_spec": c.parent_spec,
                "child_path": c.child_path,
                "child_spec": c.child_spec,
                "detail": c.detail,
            }
            for c in report.conflicts
        ],
        "inventory": {
            "languages": report.inventory.languages,
            "manifest_languages": list(report.inventory.manifest_languages),
        },
        "lockfiles": {
            "covered": list(report.lockfiles.covered),
            "uncovered": list(report.lockfiles.uncovered),
        },
    }
    if json_out:
        _emit(payload, True)
    else:
        markers = ", ".join(report.workspace_markers) or "no markers"
        typer.echo(f"Monorepo: {report.is_monorepo} ({markers})")
        typer.echo(f"Projects: {len(report.projects)}")
        for c in report.conflicts:
            typer.secho(
                f"  CONFLICT {c.tool}: {c.parent_path} wants {c.parent_spec}; "
                f"{c.child_path} wants {c.child_spec}",
                fg=typer.colors.RED,
            )
        if report.lockfiles.uncovered:
            typer.secho(
                f"No lockfile for: {', '.join(report.lockfiles.uncovered)}",
                fg=typer.colors.YELLOW,
            )
    raise typer.Exit(ExitCode.BLOCKED if report.conflicts else ExitCode.READY)


@app.command("ci-diff")
def ci_diff_cmd(
    path: Path = typer.Argument(Path(), help="Repository root."),
    json_out: bool = JsonOption,
) -> None:
    """Compare CI-declared toolchains with the local machine."""
    from devrepro.project.ci_parsers import collect_ci_toolchains, local_vs_ci_diff

    ci = collect_ci_toolchains(path)
    local_versions = _local_tool_versions()
    rows = local_vs_ci_diff(ci, local_versions)
    if json_out:
        _emit(
            {
                "ci_toolchains": [
                    {"tool": t.tool, "spec": t.spec, "source_file": t.source_file} for t in ci
                ],
                "rows": rows,
            },
            True,
        )
    else:
        typer.echo(f"CI toolchains found: {len(ci)}")
        for r in rows:
            mark = {
                "match": "+",
                "mismatch": "!",
                "unknown-local": "?",
                "wildcard": "~",
                "ci-absent": "-",
            }[r["status"]]
            color = {
                "match": "green",
                "mismatch": "red",
                "unknown-local": "yellow",
                "wildcard": "yellow",
                "ci-absent": "grey50",
            }[r["status"]]
            typer.secho(
                f"  [{mark}] {r['tool']}: CI={r['ci_spec']} local={r['local_version']}"
                f" — {r['detail']}",
                fg=color,
            )
    bad = any(r["status"] == "mismatch" for r in rows)
    raise typer.Exit(ExitCode.READY_WITH_WARNINGS if bad else ExitCode.READY)


def _local_tool_versions() -> dict[str, str]:
    """Best-effort active versions of common tools (never raises)."""
    from devrepro.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    out: dict[str, str] = {}
    probes = {
        "python": ("python", ("--version",)),
        "node": ("node", ("--version",)),
        "go": ("go", ("version",)),
        "dotnet": ("dotnet", ("--version",)),
        "java": ("java", ("-version",)),
        "ruby": ("ruby", ("--version",)),
        "php": ("php", ("--version",)),
    }
    for name, (exe, args) in probes.items():
        try:
            res = runner.run((exe, *args), timeout=5.0)
            text = (res.stdout or "") + (res.stderr or "")
            first = text.strip().splitlines()[0] if text.strip() else ""
            # extract a version-looking token
            import re as _re

            m = _re.search(r"(\d+\.\d+(\.\d+)?)", first)
            if m and res.returncode == 0:
                out[name] = m.group(1)
        except Exception:
            pass
    # fall back to installed Python distributions for library-style names
    from contextlib import suppress
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    for name in ("pydantic", "typer", "rich", "tomli", "httpx", "pytest"):
        if name not in out:
            with suppress(PackageNotFoundError):
                out[name] = dist_version(name)
    return out


@app.command()
def generate(
    what: str = typer.Argument(..., help="devrepro-toml | mise | asdf | devcontainer"),
    path: Path = typer.Argument(Path(), help="Project root."),
    write: bool = typer.Option(False, "--write", help="Write after review (refuses to overwrite)."),
    force_overwrite: bool = typer.Option(False, "--overwrite", help="Explicitly allow overwrite."),
    json_out: bool = JsonOption,
) -> None:
    """Generate reviewable environment-config drafts from detected requirements."""
    from devrepro.generators import (
        generate_devcontainer,
        generate_devrepro_toml,
        generate_tool_versions,
        write_generated,
    )
    from devrepro.project.detectors import detect_requirements

    reqs = detect_requirements(path)
    requirements = {r.name: r.spec for r in reqs if r.spec not in ("*", "")}
    env_names = tuple(sorted({r.name for r in reqs if r.kind.value == "env-name"}))
    builders: dict[str, Callable[[], str]] = {
        "devrepro-toml": lambda: generate_devrepro_toml(requirements, env_names),
        "mise": lambda: generate_tool_versions(requirements, style="mise"),
        "asdf": lambda: generate_tool_versions(requirements, style="asdf"),
        "devcontainer": generate_devcontainer,
    }
    builder = builders.get(what)
    if builder is None:
        typer.secho(f"unknown target {what!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    content = builder()
    filenames = {
        "devrepro-toml": ".devrepro.toml",
        "mise": ".mise.toml",
        "asdf": ".tool-versions",
        "devcontainer": ".devcontainer/devcontainer.json",
    }
    target = path / filenames[what]
    if not write:
        _emit({"target": str(target), "content": content, "written": False}, json_out)
        if not json_out:
            typer.echo(content)
            typer.echo(
                "[grey50]Preview only. Re-run with --write to create "
                "(existing files are never overwritten without --overwrite).[/grey50]"
            )
        raise typer.Exit(ExitCode.READY)
    result = write_generated(target, content, allow_overwrite=force_overwrite)
    _emit(
        {
            "target": result.path,
            "written": True,
            "requires_review": result.requires_review,
            "diff": result.diff or None,
        },
        json_out,
    )
    if not json_out:
        if result.diff:
            typer.echo(result.diff)
        typer.echo(f"wrote {result.path}")
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
        _emit(
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
        _emit({"snapshot_ids": list(timeline.snapshot_ids), "events": events}, True)
    else:
        typer.echo(f"Snapshots: {len(snaps)}; drift events: {len(events)}")
        for e in events[-20:]:
            typer.echo(
                f"  #{e['at_index']} [{e['kind']}] {e['component']}/{e['name']}: "
                f"{e['before'] or '-'} -> {e['after'] or '-'}"
            )
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
    _emit(checks, json_out)
    raise typer.Exit(ExitCode.READY if ok else ExitCode.INTERNAL_ERROR)


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


@app.command("env")
def env_cmd(
    path: Path = typer.Argument(Path(), help="Project root."),
    as_json: bool = JsonOption,
) -> None:
    """Trace env-var declarations, policy gaps and dotenv safety (names only)."""
    from devrepro.envvars.analysis import verify_env_policy

    report = verify_env_policy(path)
    payload = {
        "origins": [
            {
                "name": o.name,
                "source": o.source_file,
                "kind": o.kind,
                "has_value": o.has_value_in_file,
            }
            for o in report.origins
        ],
        "missing_required": list(report.missing_required),
        "forbidden_present": list(report.forbidden_present),
        "duplicated": {k: list(v) for k, v in report.duplicated.items()},
        "dotenv_findings": [
            {"path": f.path, "severity": f.severity, "detail": f.detail}
            for f in report.dotenv_findings
        ],
        "ok": report.ok,
    }
    _emit(payload, as_json)
    raise typer.Exit(ExitCode.READY if report.ok else ExitCode.READY_WITH_WARNINGS)


@app.command("ports")
def ports_cmd(
    path: Path = typer.Argument(Path(), help="Project root."),
    probe: bool = typer.Option(False, "--probe", help="TCP-probe declared services."),
    as_json: bool = JsonOption,
) -> None:
    """Declared ports, conflict detection and optional service probes."""
    from devrepro.services.ports import (
        check_port_conflicts,
        collect_port_declarations,
        infer_required_services,
        probe_services,
    )

    decls = collect_port_declarations(path)
    statuses = check_port_conflicts(decls)
    payload: dict[str, object] = {
        "declared_ports": [
            {"port": d.port, "source": d.source_file, "service": d.service} for d in decls
        ],
        "conflicts": [
            {"port": s.port, "free": s.free, "service": s.service} for s in statuses if not s.free
        ],
        "inferred_services": {
            name: {"host": h, "port": p} for name, (h, p) in infer_required_services(path).items()
        },
    }
    if probe:
        results = probe_services(infer_required_services(path))
        payload["probes"] = [
            {
                "service": r.service,
                "host": r.host,
                "port": r.port,
                "reachable": r.reachable,
                "detail": r.detail,
            }
            for r in results
        ]
    _emit(payload, as_json)
    blocked = any(not s.free for s in statuses)
    raise typer.Exit(ExitCode.BLOCKED if blocked else ExitCode.READY)


@app.command("git-health")
def git_health_cmd(as_json: bool = JsonOption) -> None:
    """Read-only Git config/LFS/submodule/worktree health (credential-safe)."""
    from devrepro.git.health import git_health

    report = git_health(Path())
    payload = {
        "is_repo": report.is_repo,
        "linked_worktree": report.is_linked_worktree,
        "config": dict(report.config),
        "signing_configured": report.signing_configured,
        "credential_helper_present": report.credential_helper_present,
        "credential_helper_name": report.credential_helper_name,
        "lfs_available": report.lfs_available,
        "lfs_version": report.lfs_version,
        "submodules": [
            {"path": s.path, "initialized": s.initialized, "dirty": s.dirty}
            for s in report.submodules
        ],
        "notes": list(report.notes),
    }
    _emit(payload, as_json)
    raise typer.Exit(ExitCode.READY if report.is_repo else ExitCode.BLOCKED)


@app.command("network")
def network_cmd(
    allow_network: bool = typer.Option(
        False, "--allow-network", help="OPT-IN: perform live DNS/TLS/registry checks."
    ),
    host: str = typer.Option(None, "--host", help="Extra host to TLS-check."),
    registries: bool = typer.Option(
        False, "--registries", help="Check package-registry reachability."
    ),
    as_json: bool = JsonOption,
) -> None:
    """Proxy chain, clock sanity; opt-in TLS/DNS/registry diagnostics."""
    from devrepro.network.diagnostics import (
        WELL_KNOWN_REGISTRIES,
        check_clock,
        check_registry,
        check_tls,
        collect_proxy_settings,
    )

    proxy = collect_proxy_settings()
    clock = check_clock(allow_network=allow_network)
    payload: dict[str, object] = {
        "network_checks_opt_in": allow_network,
        "proxy": {
            "env": proxy.env_proxies,
            "git_proxy": proxy.git_proxy,
            "npm_proxy_present": proxy.npm_proxy,
            "pip_proxy_present": proxy.pip_proxy,
        },
        "clock": {
            "utc_now": clock.utc_now,
            "skew_seconds": clock.skew_seconds,
            "plausible": clock.plausible,
            "detail": clock.detail,
        },
    }
    if allow_network:
        tls_targets = [host] if host else []
        payload["tls"] = [
            {"host": t.host, "ok": t.ok, "classification": t.classification, "detail": t.detail}
            for t in (check_tls(h) for h in tls_targets)
        ] or None
        if registries:
            payload["registries"] = [
                {"name": n, "reachable": c.reachable, "detail": c.status_or_error}
                for n in sorted(WELL_KNOWN_REGISTRIES)
                for c in [check_registry(n)]
            ]
    _emit(payload, as_json)
    raise typer.Exit(ExitCode.READY if clock.plausible else ExitCode.READY_WITH_WARNINGS)


@app.command("profile")
def profile_cmd(
    path: Path = typer.Argument(Path(), help="Project root."),
    as_json: bool = JsonOption,
) -> None:
    """Readiness profile + explainable reproducibility maturity score."""
    from devrepro.project.profiles import detect_profile, score_maturity

    prof = detect_profile(path)
    score = score_maturity(path)
    payload = {
        "profile": prof.profile,
        "confidence": round(prof.confidence, 2),
        "signals": list(prof.signals),
        "maturity": {
            "total": score.total,
            "possible": score.possible,
            "percent": score.percent,
            "factors": [
                {"name": f.name, "earned": f.earned, "weight": f.weight, "detail": f.detail}
                for f in score.factors
            ],
            "explanation": score.explanation(),
        },
    }
    _emit(payload, as_json)
    raise typer.Exit(ExitCode.READY)


@app.command("baseline")
def baseline_cmd(
    action: str = typer.Argument(..., help="create | diff"),
    baseline_path: Path = typer.Option(
        Path(".devrepro-baseline.json"), "--file", help="Baseline manifest path."
    ),
    as_json: bool = JsonOption,
) -> None:
    """Create a project baseline or diff this machine against it."""
    from devrepro.snapshots.baseline import diff_against_baseline, load_baseline, new_baseline

    if action == "create":
        from devrepro.project.detectors import detect_requirements
        from devrepro.snapshots.baseline import save_baseline

        reqs = detect_requirements(Path())
        # runtime pins only; lockfile markers, wildcards and CI-only pins
        # (ci:*) are excluded — CI toolchains are not dev-machine requirements
        tools = {
            r.name: r.spec
            for r in reqs
            if r.kind.value == "runtime"
            and r.spec not in ("*", "")
            and not r.name.startswith("ci:")
        }
        env_names_t = tuple(sorted({r.name for r in reqs if r.ecosystem == "env"}))
        b = new_baseline(str(Path().resolve().name), tools, env_names_t)
        save_baseline(b, baseline_path)
        _emit({"created": str(baseline_path), "baseline_id": b.baseline_id, **b.as_dict()}, as_json)
        raise typer.Exit(ExitCode.READY)
    if action == "diff":
        b = load_baseline(baseline_path)
        import os

        machine_tools = _local_tool_versions()
        env_names: set[str] = {name for name in b.required_env_names if name in os.environ}
        docker_ok = False
        try:
            from devrepro.core.runner import SubprocessRunner

            res = SubprocessRunner().run(("docker", "info"), timeout=10.0)
            docker_ok = res.returncode == 0
        except Exception:
            docker_ok = False
        diff = diff_against_baseline(b, machine_tools, env_names, docker_ok)
        _emit(diff.as_dict(), as_json)
        raise typer.Exit(ExitCode.BLOCKED if diff.blockers else ExitCode.READY)
    typer.echo(f"unknown baseline action: {action!r} (use create|diff)", err=True)
    raise typer.Exit(ExitCode.USAGE_ERROR)


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
