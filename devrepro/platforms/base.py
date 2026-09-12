"""Platform adapters: PATH semantics, shadowing analysis and the
"why does this executable win" explanation used by `devrepro which --all`.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
from pathlib import Path
from typing import TYPE_CHECKING

from devrepro.core.models import PathAnalysis, PathEntry, ToolInstallation

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "build_path_analysis",
    "explain_resolution",
    "normalize_path",
    "parent_dir",
    "path_separator",
    "profile_locations",
    "split_path",
]


#: The platform string this process is running on, in the same vocabulary the
#: rest of this module uses. Only for deciding whether a reported path can be
#: resolved against a real filesystem.
_HOST_PLATFORM = "windows" if os.name == "nt" else "linux"


def path_separator(platform: str) -> str:
    return ";" if platform == "windows" else ":"


def split_path(raw: str, platform: str) -> list[str]:
    return [p for p in raw.split(path_separator(platform)) if p.strip()]


def parent_dir(path: str, platform: str) -> str:
    """The containing directory of a path belonging to *platform*.

    `Path(path).parent` uses the flavour of the host, so on Windows
    `/usr/bin/python` came back separated by backslashes -- a string that
    then matched no entry in the Linux PATH it came from, and every shim
    index resolved to -1.

    The `normalize_path` bug above hid this one: that function was also
    host-flavoured, so both sides were mangled identically and compared
    equal. Fixing one exposed the other, which is the usual way the second
    of two compensating errors gets found.
    """
    return ntpath.dirname(path) if platform == "windows" else posixpath.dirname(path)


def normalize_path(entry: str, platform: str) -> str:
    r"""Normalise a PATH entry using *that platform's* rules, not the host's.

    This took a `platform` argument and then called `os.path`, which is the
    path module of whatever machine happened to be running -- so the argument
    described the answer without affecting it.

    The consequences run in both directions, and both matter because this
    project's whole premise is reading one machine's report on another:

    * A Windows PATH analysed on Linux kept its backslashes, because
      `posixpath` does not treat them as separators. `manager_for_path` then
      failed to recognise `.pyenv\\shims`, so the fleet console and every
      snapshot diff rendered on a Linux server silently stopped attributing
      shims to their version manager.
    * A Linux PATH analysed on Windows was **lower-cased** by
      `ntpath.normcase`, so `/opt/Tools` and `/opt/tools` -- two different
      directories on a case-sensitive filesystem -- were reported as duplicate
      PATH entries.

    Selecting the module from the argument makes the result a pure function of
    (entry, platform) on any host, which is what every caller already assumed.
    """
    # Written out rather than selected into a variable: mypy infers the union
    # of two modules as `Any`, and `--strict` is right to object to a function
    # that promises `str` and returns whatever a module attribute gave back.
    if platform == "windows":
        return ntpath.normcase(ntpath.normpath(entry))
    return posixpath.normcase(posixpath.normpath(entry))


def build_path_analysis(
    raw_path: str,
    platform: str,
    *,
    origin_for: Callable[[int], str] | None = None,
) -> PathAnalysis:
    """Full PATH analysis including duplicate/dead/shadowing detection."""
    parts = split_path(raw_path, platform)
    entries: list[PathEntry] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    dead: list[str] = []

    for i, part in enumerate(parts):
        norm = normalize_path(part, platform)
        exists = Path(part).is_dir()
        origin = origin_for(i) if origin_for else "unknown"
        entries.append(PathEntry(raw=part, normalized=norm, exists=exists, origin=origin, index=i))
        if norm in seen:
            duplicates.append(part)
        else:
            seen[norm] = i
        if not exists:
            dead.append(part)

    shadowed = _find_shadowed(parts, platform)
    store_aliases = [
        e.raw for e in entries if platform == "windows" and "windowsapps" in e.normalized.lower()
    ]
    manager_markers = (".pyenv", ".nvm", ".volta", ".fnm", "conda", "mise", "asdf", ".cargo")
    interference = [
        e.raw for e in entries if any(m in e.normalized.lower() for m in manager_markers)
    ]
    return PathAnalysis(
        entries=tuple(entries),
        duplicates=tuple(duplicates),
        dead_entries=tuple(dead),
        shadowed_executables=tuple(shadowed),
        store_aliases=tuple(store_aliases),
        tool_manager_interference=tuple(interference),
    )


def _find_shadowed(parts: list[str], platform: str) -> list[tuple[str, str, str]]:
    """Find executable names that appear in more than one PATH directory;
    the earlier directory wins. Returns (name, winner, loser).
    """
    by_name: dict[str, list[str]] = {}
    exts = (
        [e.strip().lower() for e in os.environ.get("PATHEXT", "").split(";") if e.strip()]
        if platform == "windows"
        else [""]
    )
    for d in parts:
        try:
            if not Path(d).is_dir():
                continue
            children = list(Path(d).iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name.lower()
            stem = name
            for ext in exts:
                if ext and name.endswith(ext):
                    stem = name[: -len(ext)]
                    break
            by_name.setdefault(stem, []).append(str(child))
    out: list[tuple[str, str, str]] = []
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1:
            out.append((name, paths[0], paths[-1]))
    return out


def explain_resolution(
    name: str,
    installs: list[ToolInstallation],
    raw_path: str,
    platform: str,
) -> str:
    """Explain why a given executable wins PATH resolution for `name`."""
    matches = [i for i in installs if i.name == name]
    if not matches:
        return f"'{name}' was not found on PATH."
    active = next((i for i in matches if i.is_active), matches[0])
    lines = [f"'{name}' resolves to: {active.exe_path}"]
    if active.version:
        lines.append(f"  version: {active.version}")
    if active.install_source:
        lines.append(f"  install source: {active.install_source}")
    entries = split_path(raw_path, platform)
    if active.exe_path:
        # Same correction as `normalize_path`: this compares a reported
        # executable path against a reported PATH, and both belong to the
        # machine the report came from rather than to the one rendering it.
        # `Path(...).resolve()` stays host-based on purpose -- it is only
        # reached for a path that exists here, and resolving symlinks needs a
        # real filesystem.
        module = ntpath if platform == "windows" else posixpath
        exe_raw = active.exe_path
        exe_norm = module.normcase(
            str(Path(exe_raw).resolve()) if platform == _HOST_PLATFORM else module.normpath(exe_raw)
        )
        for idx, directory in enumerate(entries):
            dir_norm = module.normcase(module.normpath(directory))
            if exe_norm.startswith(dir_norm + module.sep) or exe_norm.startswith(dir_norm + "/"):
                lines.append(
                    f"  wins because its directory is entry #{idx} in PATH "
                    "(earlier entries take precedence)."
                )
                break
    others = [i for i in matches if i is not active]
    if others:
        lines.append(f"  {len(others)} other installation(s) are shadowed:")
        for o in others[:5]:
            v = f" ({o.version})" if o.version else ""
            lines.append(f"    - {o.exe_path}{v}")
    return chr(10).join(lines)


def profile_locations(platform: str) -> dict[str, str]:
    """Shell profile locations per platform (for docs/UI display)."""
    home = Path.home()
    if platform == "windows":
        return {
            "powershell": str(
                home / "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1"
            ),
            "pwsh": str(home / "Documents/PowerShell/Microsoft.PowerShell_profile.ps1"),
        }
    shell = os.environ.get("SHELL", "")
    keys: tuple[str, ...]
    if "zsh" in shell:
        keys = ("zshrc", "zprofile", "zshenv")
    elif "fish" in shell:
        keys = ("fish_config",)
    else:
        keys = ("bashrc", "bash_profile", "profile")
    mapping = {
        "bashrc": ".bashrc",
        "bash_profile": ".bash_profile",
        "profile": ".profile",
        "zshrc": ".zshrc",
        "zprofile": ".zprofile",
        "zshenv": ".zshenv",
        "fish_config": ".config/fish/config.fish",
    }
    return {k: str(home / mapping[k]) for k in keys}
