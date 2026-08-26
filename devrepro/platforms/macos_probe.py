"""macOS developer-environment depth diagnostics.

Capabilities (all read-only):
- Xcode / Command Line Tools detection with active developer directory;
- SDK path and version reporting via ``xcrun``;
- Apple Silicon vs Rosetta translation detection for running processes;
- Homebrew prefix vs CPU architecture conflict detection (the classic
  ``/usr/local`` on arm64 or ``/opt/homebrew`` under Rosetta trap);
- quarantine-attribute presence check for a given executable path.

All commands run through the injected ``CommandRunner`` and all filesystem
reads through the injected ``reader`` so tests are deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

__all__ = [
    "BrewPrefixInfo",
    "CltInfo",
    "QuarantineInfo",
    "RosettaInfo",
    "SdkInfo",
    "brew_prefix_conflict",
    "clt_inventory",
    "quarantine_check",
    "rosetta_status",
    "sdk_inventory",
]

if TYPE_CHECKING:
    from devrepro.core.runner import SubprocessRunner

FileReader = Callable[[str], str | None]


def _run(runner: SubprocessRunner, *argv: str) -> str | None:
    try:
        res = runner.run(argv, timeout=15.0)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    out = (res.stdout or "").strip()
    return out or None


@dataclass(frozen=True)
class CltInfo:
    """Command Line Tools / Xcode inventory."""

    developer_dir: str | None
    clt_version: str | None
    xcode_version: str | None
    available: bool


def clt_inventory(runner: SubprocessRunner) -> CltInfo:
    """Detect the active developer directory and toolchain versions."""
    dev_dir = _run(runner, "xcode-select", "-p")
    if dev_dir is None:
        return CltInfo(None, None, None, False)
    pkg = _run(runner, "pkgutil", "--pkg-info", "com.apple.pkg.CLTools_Executables")
    clt_version: str | None = None
    if pkg:
        m = re.search(r"version:\s*(\S+)", pkg)
        if m:
            clt_version = m.group(1)
    xcode_version: str | None = None
    if dev_dir.endswith(".app"):
        xb = _run(runner, "xcodebuild", "-version")
        if xb:
            xcode_version = xb.splitlines()[0].replace("Xcode ", "")
            if clt_version is None:
                m = re.search(r"Build version (\S+)", xb)
                clt_version = m.group(1) if m else None
    return CltInfo(dev_dir, clt_version, xcode_version, True)


@dataclass(frozen=True)
class SdkInfo:
    sdk_path: str | None
    sdk_version: str | None


def sdk_inventory(runner: SubprocessRunner) -> SdkInfo:
    """Report the default macOS SDK path/version when xcrun exists."""
    path = _run(runner, "xcrun", "--show-sdk-path")
    version = _run(runner, "xcrun", "--show-sdk-version")
    return SdkInfo(path, version)


@dataclass(frozen=True)
class RosettaInfo:
    machine: str | None  # e.g. arm64
    translated: bool | None  # True when this process runs under Rosetta
    note: str | None = None


def rosetta_status(runner: SubprocessRunner) -> RosettaInfo:
    """Detect whether the current process is translated by Rosetta."""
    machine_out = _run(runner, "uname", "-m")
    machine = machine_out.split()[0] if machine_out else None
    # sysctl returns 1 when the current process is running under translation
    sysctl_out = _run(runner, "sysctl", "-n", "sysctl.proc_translated")
    if sysctl_out == "1":
        return RosettaInfo(machine, True, "current process runs under Rosetta translation")
    if sysctl_out == "0":
        return RosettaInfo(machine, False)
    if machine == "arm64":
        return RosettaInfo(machine, False, "arm64 native; translation status unknown")
    return RosettaInfo(machine, None, "translation status could not be determined")


@dataclass(frozen=True)
class BrewPrefixInfo:
    prefix: str | None
    arch_expected_prefix: str | None
    conflict: bool
    note: str | None = None


def brew_prefix_conflict(
    runner: SubprocessRunner,
    machine_arch: str | None,
) -> BrewPrefixInfo:
    """Flag Homebrew installs whose prefix does not match the CPU architecture.

    Apple Silicon expects ``/opt/homebrew``; Intel (and Rosetta shells)
    historically use ``/usr/local``. A mismatched prefix produces binaries
    built for the wrong architecture and subtle link failures.
    """
    prefix = _run(runner, "brew", "--prefix")
    expected = "/opt/homebrew" if machine_arch == "arm64" else "/usr/local"
    if prefix is None:
        return BrewPrefixInfo(None, expected, False, "Homebrew not found on PATH")
    conflict = prefix.rstrip("/") != expected and not (
        machine_arch == "arm64" and prefix.rstrip("/") == "/homebrew"
    )
    note = (
        (
            f"Homebrew prefix {prefix} does not match the expected {expected} for "
            f"{machine_arch or 'unknown'} architecture; mixed-arch installs cause "
            "native-extension build failures"
        )
        if conflict
        else None
    )
    return BrewPrefixInfo(prefix, expected, conflict, note)


@dataclass(frozen=True)
class QuarantineInfo:
    path: str
    quarantined: bool | None
    note: str | None = None


def quarantine_check(runner: SubprocessRunner, target: str) -> QuarantineInfo:
    """Check for the macOS quarantine xattr on *target* (path only, no content)."""
    res = _run(runner, "xattr", target)
    if res is None:
        # xattr exits non-zero both for missing attribute and missing file;
        # disambiguate by asking for the specific attribute.
        specific = _run(runner, "xattr", "-p", "com.apple.quarantine", target)
        quarantined = specific is not None
        return QuarantineInfo(
            target, quarantined, None if quarantined else "no quarantine attribute"
        )
    quarantined = "com.apple.quarantine" in res.splitlines()
    return QuarantineInfo(target, quarantined, None if quarantined else "no quarantine attribute")
