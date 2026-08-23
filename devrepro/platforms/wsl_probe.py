"""WSL diagnostics: distro inventory, kernel, interop, PATH contamination.

Capabilities:
- enumerate WSL distributions with running state and versions;
- default-distro and kernel reporting via ``wsl --status``;
- Windows<->WSL PATH contamination detection (Windows paths injected into
  WSL PATH produce duplicate executables);
- filesystem-location performance guidance (project on /mnt/c vs native ext4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from devrepro.core.runner import SubprocessRunner

__all__ = [
    "WslDistro",
    "WslInventory",
    "detect_path_contamination",
    "filesystem_location_guidance",
    "wsl_inventory",
]


@dataclass(frozen=True)
class WslDistro:
    name: str
    state: str  # Running | Stopped | Installing...
    version: int  # 1 or 2


@dataclass(frozen=True)
class WslInventory:
    available: bool
    default_version: int | None
    kernel: str | None
    distros: tuple[WslDistro, ...]
    detail: str


def _run_wsl(runner: SubprocessRunner, *args: str) -> str | None:
    res = runner.run(("wsl.exe", *args), timeout=20.0)
    if res.returncode != 0:
        return None
    # wsl.exe emits UTF-16LE on some locales; decode defensively
    out = res.stdout or ""
    if "\x00" in out:
        out = out.replace("\x00", "")
    return out.strip() or None


def wsl_inventory(runner: SubprocessRunner | None = None) -> WslInventory:
    """Enumerate WSL distros and status. Returns unavailable when absent."""
    runner = runner or SubprocessRunner()
    listing = _run_wsl(runner, "-l", "-v")
    if listing is None:
        return WslInventory(False, None, None, (), "WSL not installed or not runnable")
    distros: list[WslDistro] = []
    for line in listing.splitlines()[1:]:  # skip header row
        parts = line.split()
        if len(parts) >= 3:
            try:
                version = int(parts[-1])
            except ValueError:
                continue
            distros.append(WslDistro(name=" ".join(parts[:-2]), state=parts[-2], version=version))
    status = _run_wsl(runner, "--status") or ""
    m_ver = re.search(r"Default Version:\s*(\d)", status)
    m_kernel = re.search(r"Kernel version:\s*(.+)", status)
    detail = (
        f"{len(distros)} distribution(s); default WSL version "
        f"{m_ver.group(1) if m_ver else 'unknown'}"
    )
    return WslInventory(
        available=True,
        default_version=int(m_ver.group(1)) if m_ver else None,
        kernel=m_kernel.group(1).strip() if m_kernel else None,
        distros=tuple(distros),
        detail=detail,
    )


def detect_path_contamination(wsl_path_entries: list[str]) -> tuple[str, ...]:
    """Find Windows-style paths inside a WSL PATH (interop contamination).

    ``wsl_path_entries`` is a WSL-side PATH split on ':'; entries like
    ``/mnt/c/Windows/system32`` are interop-injected and can shadow Linux
    toolchains with .exe-less Windows binaries.
    """
    windows_markers = ("/mnt/c/", "/mnt/d/", "/mnt/e/", "/mnt/wsl/", "windows", "windowsapps")
    contaminated = []
    for entry in wsl_path_entries:
        low = entry.lower()
        if any(m in low for m in windows_markers):
            contaminated.append(entry)
    return tuple(contaminated)


def filesystem_location_guidance(project_path: Path | str) -> dict[str, str]:
    """Performance guidance based on where the project lives (WSL context).

    On WSL2, projects under /mnt/* (drvfs) suffer ~10-50x slower file I/O
    than the native ext4 filesystem — the single most common WSL perf trap.
    """
    p = Path(project_path)
    posix = p.as_posix().lower()
    guidance: dict[str, str] = {}
    if "/mnt/" in posix:
        guidance["location_class"] = "windows-mounted (drvfs)"
        guidance["severity"] = "warn"
        guidance["recommendation"] = (
            "project lives on a Windows drive mounted in WSL (/mnt/*); file I/O is "
            "dramatically slower. Move the checkout to the Linux home directory "
            "(e.g. ~/projects) for builds, tests and package installs."
        )
    elif posix.startswith("/home/") or posix.startswith("/root"):
        guidance["location_class"] = "native-linux"
        guidance["severity"] = "ok"
        guidance["recommendation"] = (
            "project is on the native Linux filesystem; good I/O performance"
        )
    elif posix.startswith(("/tmp", "/var")):  # noqa: S108 - diagnostic classification, not file use
        guidance["location_class"] = "native-linux-temporary"
        guidance["severity"] = "info"
        guidance["recommendation"] = (
            "temporary location; fine for builds but not for durable checkouts"
        )
    else:
        guidance["location_class"] = "unknown"
        guidance["severity"] = "info"
        guidance["recommendation"] = "could not classify filesystem location"
    return guidance
