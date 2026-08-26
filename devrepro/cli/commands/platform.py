"""Platform-depth command: platform-depth (Linux/macOS deep probes)."""

from __future__ import annotations

import typer

from devrepro.cli.common import JsonOption, emit
from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach platform-depth commands to the root app."""

    @app.command("platform-depth")
    def platform_depth_cmd(as_json: bool = JsonOption) -> None:
        """Linux/macOS platform depth: distro family, limits, inotify, governor,
        Xcode/CLT, Rosetta, Homebrew prefix conflicts (read-only).
        """
        import platform as _plat

        from devrepro.core.runner import SubprocessRunner
        from devrepro.platforms.linux_probe import (
            cpu_governor,
            distro_info,
            fd_limits,
            inotify_limits,
            toolchain_metadata,
        )
        from devrepro.platforms.macos_probe import (
            brew_prefix_conflict,
            clt_inventory,
            rosetta_status,
            sdk_inventory,
        )

        system = _plat.system().lower()
        runner = SubprocessRunner()

        def _read(path: str) -> str | None:
            try:
                import pathlib

                f = pathlib.Path(path)
                return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else None
            except OSError:
                return None

        payload: dict[str, object] = {"host_system": system}
        if system == "linux":
            distro = distro_info(_read)
            meta = toolchain_metadata(_read, runner)
            fds = fd_limits(_read)
            ino = inotify_limits(_read)
            gov = cpu_governor(_read)
            payload.update(
                {
                    "distro": {
                        "name": distro.name,
                        "version": distro.version,
                        "family": distro.family,
                        "package_managers": list(distro.package_managers),
                    },
                    "toolchain": {
                        "kernel": meta.kernel,
                        "libc": meta.libc,
                        "gcc": meta.gcc_version,
                        "clang": meta.clang_version,
                        "notes": list(meta.notes),
                    },
                    "fd_limits": {"soft": fds.soft, "hard": fds.hard},
                    "inotify": {
                        "max_user_watches": ino.max_user_watches,
                        "max_user_instances": ino.max_user_instances,
                        "guidance": ino.guidance,
                    },
                    "cpu_governor": {
                        "governor": gov.governor,
                        "available": gov.available,
                        "note": gov.note,
                    },
                }
            )
        elif system == "darwin":
            machine = _plat.machine()
            clt = clt_inventory(runner)
            sdk = sdk_inventory(runner)
            ros = rosetta_status(runner)
            brew = brew_prefix_conflict(runner, machine)
            payload.update(
                {
                    "machine_arch": machine,
                    "developer_dir": clt.developer_dir,
                    "clt_version": clt.clt_version,
                    "xcode_version": clt.xcode_version,
                    "sdk_path": sdk.sdk_path,
                    "sdk_version": sdk.sdk_version,
                    "rosetta": {
                        "translated": ros.translated,
                        "note": ros.note,
                    },
                    "homebrew": {
                        "prefix": brew.prefix,
                        "expected_prefix": brew.arch_expected_prefix,
                        "conflict": brew.conflict,
                        "note": brew.note,
                    },
                }
            )
        else:
            payload["note"] = (
                "Linux/macOS depth probes do not apply on this host; Windows depth "
                "lives in the WSL/virtualization and registry probes."
            )

        emit(payload, as_json)
        raise typer.Exit(ExitCode.READY)
