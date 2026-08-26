"""Linux developer-environment depth diagnostics.

Capabilities (all read-only):
- distro + package-manager normalization across Debian/Ubuntu, Fedora/RHEL,
  Arch and common derivatives (``/etc/os-release`` evidence);
- compiler/libc/kernel metadata with project-impact classification;
- ``ulimit`` / file-descriptor and process-limit checks for projects that
  declare high concurrency;
- inotify watch limits relevant to large frontend/monorepo workspaces;
- CPU governor/power-mode reporting for performance-sensitive development.

Every filesystem read goes through the injected ``reader`` and every command
through the injected ``CommandRunner`` so behaviour is deterministic in tests
and safe on non-Linux hosts (functions return ``None``/empty results).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

__all__ = [
    "CpuGovernorInfo",
    "DistroInfo",
    "FdLimits",
    "InotifyInfo",
    "ToolchainMetadata",
    "cpu_governor",
    "distro_info",
    "fd_limits",
    "inotify_limits",
    "toolchain_metadata",
]

if TYPE_CHECKING:
    from devrepro.core.runner import SubprocessRunner

FileReader = Callable[[str], str | None]

_OS_RELEASE_FAMILY = {
    "debian": "debian",
    "ubuntu": "debian",
    "linuxmint": "debian",
    "pop": "debian",
    "elementary": "debian",
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "rocky": "fedora",
    "alma": "fedora",
    "almalinux": "fedora",
    "amzn": "fedora",
    "arch": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "opensuse": "suse",
    "sles": "suse",
    "alpine": "alpine",
}

_PACKAGE_MANAGERS = {
    "debian": ("apt",),
    "fedora": ("dnf", "yum"),
    "arch": ("pacman",),
    "suse": ("zypper",),
    "alpine": ("apk",),
}


@dataclass(frozen=True)
class DistroInfo:
    """Normalized distribution identity."""

    name: str
    version: str
    family: str  # debian | fedora | arch | suse | alpine | unknown
    package_managers: tuple[str, ...]
    available: bool


def _parse_os_release(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def distro_info(reader: FileReader) -> DistroInfo:
    """Read ``/etc/os-release`` and normalize to a family + package managers."""
    text = reader("/etc/os-release")
    if text is None:
        return DistroInfo("", "", "unknown", (), False)
    fields = _parse_os_release(text)
    distro_id = fields.get("ID", "").lower()
    like_ids = [p.strip().lower() for p in fields.get("ID_LIKE", "").split()]
    family = "unknown"
    for candidate in [distro_id, *like_ids]:
        if candidate in _OS_RELEASE_FAMILY:
            family = _OS_RELEASE_FAMILY[candidate]
            break
    return DistroInfo(
        name=fields.get("NAME", distro_id),
        version=fields.get("VERSION_ID", ""),
        family=family,
        package_managers=_PACKAGE_MANAGERS.get(family, ()),
        available=True,
    )


@dataclass(frozen=True)
class ToolchainMetadata:
    """Compiler/libc/kernel facts used by project-impact rules."""

    kernel: str
    libc: str | None  # e.g. "glibc 2.39" or "musl 1.2.5"
    gcc_version: str | None
    clang_version: str | None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _run(runner: SubprocessRunner, *argv: str) -> str | None:
    try:
        res = runner.run(argv, timeout=15.0)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    out = (res.stdout or "").strip()
    return out or None


def _libc_from_ldd(runner: SubprocessRunner) -> str | None:
    out = _run(runner, "ldd", "--version")
    if not out:
        return None
    first = out.splitlines()[0]
    m = re.search(r"(glibc|GNU libc|musl)[^\d]*([\d.]+)", first, re.IGNORECASE)
    if not m:
        return first[:120]
    name = "musl" if "musl" in m.group(1).lower() else "glibc"
    return f"{name} {m.group(2)}"


def toolchain_metadata(reader: FileReader, runner: SubprocessRunner) -> ToolchainMetadata:
    """Collect kernel/libc/compiler metadata; all parts may be unavailable."""
    kernel = (reader("/proc/sys/kernel/osrelease") or "").strip()
    notes: list[str] = []
    gcc = _run(runner, "gcc", "--version")
    gcc_version = gcc.splitlines()[0].split()[-1] if gcc else None
    clang = _run(runner, "clang", "--version")
    clang_version = (
        clang.split(" version ")[1].split()[0] if clang and " version " in clang else None
    )
    libc = _libc_from_ldd(runner)
    if not libc:
        # musl-based systems often need direct detection
        if reader("/etc/alpine-release") is not None:
            notes.append("alpine/musl detected via /etc/alpine-release")
            libc = "musl"
        else:
            notes.append("libc could not be identified")
    return ToolchainMetadata(
        kernel=kernel,
        libc=libc,
        gcc_version=gcc_version,
        clang_version=clang_version,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class FdLimits:
    soft: int | None
    hard: int | None
    source: str  # "resource" | "ulimit" | "unavailable"


def fd_limits(reader: FileReader) -> FdLimits:
    """Read per-process fd limits from ``/proc/self/limits``."""
    text = reader("/proc/self/limits")
    if text is None:
        return FdLimits(None, None, "unavailable")
    for line in text.splitlines():
        if "open files" in line.lower():
            parts = line.split()
            try:
                soft_s, hard_s = parts[3], parts[4]
            except IndexError:
                break
            soft = None if soft_s == "unlimited" else int(soft_s)
            hard = None if hard_s == "unlimited" else int(hard_s)
            return FdLimits(soft, hard, "resource")
    return FdLimits(None, None, "unavailable")


@dataclass(frozen=True)
class InotifyInfo:
    max_user_watches: int | None
    max_user_instances: int | None
    guidance: str | None


def inotify_limits(reader: FileReader) -> InotifyInfo:
    """Report inotify watch limits; low values break large monorepo watchers."""
    watches_raw = reader("/proc/sys/fs/inotify/max_user_watches")
    instances_raw = reader("/proc/sys/fs/inotify/max_user_instances")
    watches = int(watches_raw.strip()) if watches_raw and watches_raw.strip().isdigit() else None
    instances = (
        int(instances_raw.strip()) if instances_raw and instances_raw.strip().isdigit() else None
    )
    guidance: str | None = None
    if watches is not None and watches < 524288:
        guidance = (
            f"max_user_watches={watches} is below the 524288 commonly required by "
            "large monorepos/frontend dev servers; raise it with sysctl "
            "(fs.inotify.max_user_watches)"
        )
    elif watches is None:
        guidance = "inotify settings unreadable (non-Linux host or restricted /proc)"
    return InotifyInfo(watches, instances, guidance)


@dataclass(frozen=True)
class CpuGovernorInfo:
    governor: str | None
    available: bool
    note: str | None = None


def cpu_governor(reader: FileReader) -> CpuGovernorInfo:
    """Report the cpufreq scaling governor when performance matters."""
    raw = reader("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if raw is None:
        return CpuGovernorInfo(None, False, "no cpufreq governor visible (VM or default config)")
    return CpuGovernorInfo(raw.strip(), True)
