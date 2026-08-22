"""PATH probe: collect entries with liveness/origin; detect duplicates,
dead entries, Windows Store aliases and tool-manager interference.

The heavy *analysis* (shadowing, precedence explanation) lives in
``devrepro.platforms`` adapters + ``devrepro.cli.commands.path_cmd`` so it
can be reused by `devrepro path` without a full scan.
"""

from __future__ import annotations

import os
from pathlib import Path

from devrepro.core.models import (
    Evidence,
    FindingState,
    PathAnalysis,
    PathEntry,
)
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["PathProbe"]

_STORE_ALIAS_MARKERS = ("WindowsApps", "Microsoft\\WindowsApps")


class PathProbe(Probe):
    id = "path/entries"
    version = "1"

    def run(self) -> ProbeResult:
        raw_path = self.ctx.env.get("PATH", "")
        sep = ";" if self.ctx.platform == "windows" else ":"
        parts = [p for p in raw_path.split(sep) if p.strip()]

        entries: list[PathEntry] = []
        seen_norm: dict[str, int] = {}
        duplicates: list[str] = []
        dead: list[str] = []

        for i, part in enumerate(parts):
            norm = os.path.normcase(os.path.normpath(part))
            exists = Path(part).is_dir()
            origin = self._origin(i)
            entries.append(
                PathEntry(raw=part, normalized=norm, exists=exists, origin=origin, index=i)
            )
            if norm in seen_norm:
                duplicates.append(part)
            else:
                seen_norm[norm] = i
            if not exists:
                dead.append(part)

        store_aliases = [
            e.raw for e in entries
            if any(marker.lower() in e.normalized.lower() for marker in _STORE_ALIAS_MARKERS)
        ]
        tool_manager_markers = (
            ".pyenv", ".nvm", ".volta", ".fnm", "conda", "mise", "asdf", ".cargo/bin",
        )
        interference = [
            e.raw for e in entries
            if any(m in e.normalized.lower() for m in tool_manager_markers)
        ]

        analysis = PathAnalysis(
            entries=tuple(entries),
            duplicates=tuple(duplicates),
            dead_entries=tuple(dead),
            store_aliases=tuple(store_aliases),
            tool_manager_interference=tuple(interference),
        )

        findings = []
        ev_dup = Evidence(source="env", excerpt="PATH duplicate entries detected")
        if duplicates:
            findings.append(
                self.finding(
                    "path/duplicates",
                    FindingState.WARN,
                    f"{len(duplicates)} duplicate PATH entr{'y' if len(duplicates) == 1 else 'ies'} detected.",
                    evidence=(ev_dup,),
                    detected=", ".join(duplicates[:5]),
                    component="path",
                    remediation_hint="Remove later duplicate entries from user/system PATH "
                    "(SAFE: removing redundant duplicates does not change resolution).",
                )
            )
        ev_dead = Evidence(source="env", excerpt="PATH entries pointing to missing directories")
        if dead:
            findings.append(
                self.finding(
                    "path/dead-entries",
                    FindingState.WARN,
                    f"{len(dead)} PATH entries point to directories that do not exist.",
                    evidence=(ev_dead,),
                    detected=", ".join(dead[:5]),
                    component="path",
                    remediation_hint="Dead PATH entries slow every process start; remove them (LOW risk).",
                )
            )
        if store_aliases:
            findings.append(
                self.finding(
                    "path/store-aliases",
                    FindingState.INFO,
                    "Windows Store app-execution aliases are on PATH; they can shadow real installs.",
                    evidence=(Evidence(source="env", excerpt="WindowsApps alias directory on PATH"),),
                    detected=", ".join(store_aliases[:3]),
                    component="path",
                )
            )

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={"analysis": analysis.model_dump(mode="json")},
        )

    def _origin(self, index: int) -> str:
        """Best-effort origin classification. Machine PATH order is
        typically inherited(system) then user-appended."""
        if self.ctx.platform == "windows":
            return "inherited"
        return "profile" if index > 0 else "inherited"