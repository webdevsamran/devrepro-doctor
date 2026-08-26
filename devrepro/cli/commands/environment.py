"""Environment commands: env, ports, git-health, network, envmanagers."""

from __future__ import annotations

from pathlib import Path

import typer

from devrepro.cli.common import JsonOption, emit
from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach environment commands to the root app."""

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
        emit(payload, as_json)
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
                {"port": s.port, "free": s.free, "service": s.service}
                for s in statuses
                if not s.free
            ],
            "inferred_services": {
                name: {"host": h, "port": p}
                for name, (h, p) in infer_required_services(path).items()
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
        emit(payload, as_json)
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
        emit(payload, as_json)
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
        emit(payload, as_json)
        raise typer.Exit(ExitCode.READY if clock.plausible else ExitCode.READY_WITH_WARNINGS)

    @app.command("envmanagers")
    def envmanagers_cmd(
        path: Path = typer.Argument(Path(), help="Project root."),
        as_json: bool = JsonOption,
    ) -> None:
        """Diagnose Nix/devenv/Devbox/mise/asdf/direnv declarations vs active tools.

        DevRepro does not replace these managers; it checks that their pins are
        complete (lockfiles committed) and that the active toolchain matches.
        """
        from shutil import which

        from devrepro.core.runner import SubprocessRunner
        from devrepro.envmanagers.diagnostics import inventory_project, pinned_vs_active

        inv = inventory_project(path)

        # Resolve active versions only for tools the project actually pins.
        runner = SubprocessRunner()
        active: dict[str, str] = {}
        binary_names = {"nodejs": "node", "golang": "go"}
        for pin in inv.pins:
            if pin.name in active:
                continue
            binary = binary_names.get(pin.name, pin.name)
            if which(binary) is None:
                continue
            try:
                res = runner.run((binary, "--version"), timeout=10.0)
            except Exception:
                continue
            if res.returncode == 0 and res.stdout.strip():
                first = res.stdout.strip().splitlines()[0]
                version = first.split()[-1].lstrip("v")
                active[pin.name] = version

        comparisons = pinned_vs_active(inv.pins, active)
        payload = {
            "managers": [
                {"manager": m.manager, "files": list(m.files), "locked": m.locked}
                for m in inv.managers
            ],
            "pins": [
                {"name": p.name, "version": p.version, "source": p.source_file} for p in inv.pins
            ],
            "active_versions": active,
            "findings": [
                {"manager": f.manager, "severity": f.severity, "message": f.message}
                for f in [*inv.findings, *comparisons]
            ],
        }
        emit(payload, as_json)
        has_warn = any(f.severity == "warn" for f in [*inv.findings, *comparisons])
        raise typer.Exit(ExitCode.READY_WITH_WARNINGS if has_warn else ExitCode.READY)
