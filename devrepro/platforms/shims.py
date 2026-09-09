"""Which version manager actually wins, and where it is being bypassed.

A version manager works by putting a directory of shims early on PATH. Every
`python` call then goes through pyenv, every `node` through nvm, and the
project's pinned version is honoured. The whole mechanism depends on ordering,
and ordering is the thing that silently changes: an installer prepends itself,
a shell profile appends in the wrong order, an IDE launches with a PATH that is
not the one from your terminal.

When that happens the manager is still installed, still configured, still
reports the right version when asked directly -- and is bypassed. `pyenv
version` says 3.12 while `python --version` says 3.9, and nothing anywhere
reports a problem.

`devrepro envmanagers` answers a different question: does what the project
*declares* match what is active. This answers whether the manager is in the
resolution path at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devrepro.platforms.base import normalize_path, path_separator

__all__ = [
    "SHIM_MARKERS",
    "ShimAnalysis",
    "ShimShadow",
    "analyse_shims",
    "manager_for_path",
]

#: Path fragments that identify a version manager's shim or bin directory.
#: Matched against the normalised, lower-cased path, so both separators work.
SHIM_MARKERS: dict[str, tuple[str, ...]] = {
    "pyenv": (".pyenv/shims", ".pyenv\\shims", "pyenv-win/shims"),
    "asdf": (".asdf/shims", ".asdf\\shims"),
    "mise": ("mise/shims", "mise\\shims", ".local/share/mise/shims"),
    "rbenv": (".rbenv/shims", ".rbenv\\shims"),
    "nodenv": (".nodenv/shims", ".nodenv\\shims"),
    "volta": (".volta/bin", ".volta\\bin"),
    "nvm": (".nvm/versions", ".nvm\\versions", "nvm4w", "appdata/roaming/nvm"),
    # No trailing separator: `normalize_path` runs `os.path.normpath`, which
    # strips it, so a marker ending in one can never match a real PATH entry.
    "fnm": ("fnm_multishells", "/.fnm", r"\.fnm"),
    "conda": ("conda/envs", "anaconda3", "miniconda3", "miniforge3"),
    "rustup": (".cargo/bin", ".cargo\\bin"),
    "sdkman": (".sdkman/candidates",),
}


@dataclass(frozen=True)
class ShimShadow:
    """A version manager that is installed but not in the resolution path."""

    tool: str
    manager: str
    winning_path: str
    winning_index: int
    shim_path: str
    shim_index: int

    @property
    def summary(self) -> str:
        return (
            f"{self.tool!r} resolves to {self.winning_path} before the "
            f"{self.manager} shim at {self.shim_path}"
        )


@dataclass(frozen=True)
class ShimAnalysis:
    """Which managers are on PATH, and which are being bypassed."""

    managers_on_path: dict[str, int]
    shadowed: tuple[ShimShadow, ...] = ()

    @property
    def has_conflict(self) -> bool:
        return bool(self.shadowed)


def manager_for_path(entry: str, platform: str = "linux") -> str | None:
    """The version manager owning a PATH entry, if any."""
    needle = normalize_path(entry, platform).replace("\\", "/").lower()
    for manager, markers in SHIM_MARKERS.items():
        for marker in markers:
            if marker.replace("\\", "/").lower() in needle:
                return manager
    return None


def analyse_shims(
    path_env: str,
    resolutions: dict[str, list[str]],
    *,
    platform: str = "linux",
) -> ShimAnalysis:
    """Find version managers that are installed but bypassed.

    ``resolutions`` maps a tool name to every path it resolves to, in PATH
    precedence order -- exactly what ``probes.helpers.resolve_all_on_path``
    returns.

    A manager is reported as shadowed only when its shim for *that tool*
    genuinely exists further down the list. A manager that simply does not
    provide the tool is not a conflict, and reporting it as one would make the
    check noise.
    """
    sep = path_separator(platform)
    entries = [e for e in path_env.split(sep) if e.strip()]

    managers_on_path: dict[str, int] = {}
    for index, entry in enumerate(entries):
        manager = manager_for_path(entry, platform)
        if manager is not None and manager not in managers_on_path:
            managers_on_path[manager] = index

    shadowed: list[ShimShadow] = []
    for tool, candidates in sorted(resolutions.items()):
        if len(candidates) < 2:
            continue
        winner = candidates[0]
        winner_manager = manager_for_path(str(Path(winner).parent), platform)
        if winner_manager is not None:
            continue  # a manager already wins; nothing is being bypassed

        for other in candidates[1:]:
            other_dir = str(Path(other).parent)
            manager = manager_for_path(other_dir, platform)
            if manager is None:
                continue
            shadowed.append(
                ShimShadow(
                    tool=tool,
                    manager=manager,
                    winning_path=winner,
                    winning_index=_index_of(entries, str(Path(winner).parent), platform),
                    shim_path=other,
                    shim_index=_index_of(entries, other_dir, platform),
                )
            )
            break  # one report per tool is enough to act on

    return ShimAnalysis(managers_on_path=managers_on_path, shadowed=tuple(shadowed))


def _index_of(entries: list[str], directory: str, platform: str) -> int:
    target = normalize_path(directory, platform)
    for index, entry in enumerate(entries):
        if normalize_path(entry, platform) == target:
            return index
    return -1
