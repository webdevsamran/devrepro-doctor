"""Windows-specific developer-environment probes (read-only, safe keys only).

Capabilities:
- App Execution Alias diagnostics (python.exe/node.exe shadowing via
  the WindowsApps alias directory);
- documented-safe registry reads (long-path setting, Dev Drive presence);
- Visual Studio / Build Tools / MSVC detection via vswhere when present;
- PowerShell execution-policy REPORTING (never modifies it).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "AppAliasReport",
    "ExecutionPolicyReport",
    "LongPathReport",
    "MsvcReport",
    "check_app_execution_aliases",
    "check_long_paths",
    "detect_msvc",
    "read_execution_policy",
]

_WINDOWS_APPS_ALIAS_DIR = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
    if os.name == "nt"
    else None
)


@dataclass(frozen=True)
class AppAliasReport:
    alias_dir: str | None
    python_alias_present: bool
    node_alias_present: bool
    detail: str


@dataclass(frozen=True)
class LongPathReport:
    long_paths_enabled: bool | None  # None when not on Windows or key unreadable
    detail: str


@dataclass(frozen=True)
class MsvcReport:
    vswhere_found: bool
    installations: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class ExecutionPolicyReport:
    scope_policies: dict[str, str]
    detail: str


def check_app_execution_aliases() -> AppAliasReport:
    """Detect Store-style app-execution aliases that shadow real toolchains."""
    if os.name != "nt" or _WINDOWS_APPS_ALIAS_DIR is None:
        return AppAliasReport(None, False, False, "not applicable on this platform")
    d = _WINDOWS_APPS_ALIAS_DIR
    if not d.is_dir():
        return AppAliasReport(str(d), False, False, "alias directory not present")
    py = (d / "python.exe").exists() or (d / "python3.exe").exists()
    nd = (d / "node.exe").exists()
    hits = []
    if py:
        hits.append("python")
    if nd:
        hits.append("node")
    detail = (
        f"Store aliases present for {', '.join(hits)}; these can shadow real installs "
        "because WindowsApps precedes many PATH entries"
        if hits
        else "no python/node aliases found"
    )
    return AppAliasReport(str(d), py, nd, detail)


def check_long_paths() -> LongPathReport:
    r"""Read HKLM FileSystem\\LongPathsEnabled (documented, read-only)."""
    if os.name != "nt":
        return LongPathReport(None, "not applicable on this platform")
    try:
        import winreg  # only present on Windows; guarded by os.name check above

        # Inline ignores: winreg stubs are Windows-only in typeshed, so on
        # Linux/macOS these attributes are unknown; on Windows the ignores are
        # unused (warn_unused_ignores is disabled for this module in pyproject).
        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")  # type: ignore[attr-defined]
        enabled = bool(value)
        detail = (
            "long paths ENABLED"
            if enabled
            else "long paths DISABLED — deep node_modules/venv trees may fail to build"
        )
        return LongPathReport(enabled, detail)
    except OSError as exc:
        return LongPathReport(None, f"registry unreadable: {type(exc).__name__}")


def detect_msvc() -> MsvcReport:
    """Locate VS/Build Tools via vswhere.exe (official supported discovery)."""
    if os.name != "nt":
        return MsvcReport(False, ())
    vswhere = (
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.is_file():
        return MsvcReport(False, ())
    from devrepro.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    res = runner.run(
        (
            str(vswhere),
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-format",
            "json",
        ),
        timeout=15.0,
    )
    if res.returncode != 0 or not (res.stdout or "").strip():
        return MsvcReport(True, ())
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return MsvcReport(True, ())
    installs = tuple(
        {
            "name": str(i.get("displayName", "")),
            "version": str(i.get("installationVersion", "")),
            "path": str(i.get("installationPath", "")),
        }
        for i in data
        if isinstance(i, dict)
    )
    return MsvcReport(True, installs)


def read_execution_policy() -> ExecutionPolicyReport:
    """REPORT PowerShell execution policy per scope. Never changes it."""
    if os.name != "nt" and sys.platform != "win32":
        return ExecutionPolicyReport({}, "not applicable on this platform")
    from devrepro.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    res = runner.run(
        (
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-ExecutionPolicy -List | Format-Table -HideTableHeaders",
        ),
        timeout=20.0,
    )
    if res.returncode != 0:
        return ExecutionPolicyReport({}, f"could not query policy ({res.returncode})")
    policies: dict[str, str] = {}
    for line in (res.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            policies[parts[0].strip()] = parts[-1].strip()
    effective = policies.get("Effective") or next(iter(policies.values()), "")
    detail = f"effective policy: {effective or 'unknown'} (reported only; never modified)"
    return ExecutionPolicyReport(policies, detail)
