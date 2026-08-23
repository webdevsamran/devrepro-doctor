"""Optional local history of sanitized snapshots + drift detection.

Storage is local-only (``~/.devrepro-doctor/history``), never cloud.
Drift is computed between the newest stored snapshot and the previous one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from devrepro.core.models import DiffClassification, Snapshot
from devrepro.diff.engine import diff_snapshots
from devrepro.snapshots.store import SNAPSHOT_SUFFIX, load_snapshot

__all__ = ["DriftItem", "HistoryStore", "compute_drift"]


class HistoryStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or (Path.home() / ".devrepro-doctor" / "history")
        self.dir.mkdir(parents=True, exist_ok=True)

    def list_snapshots(self) -> list[Path]:
        return sorted(self.dir.glob("*" + SNAPSHOT_SUFFIX), key=lambda p: p.stat().st_mtime)

    def save(self, snapshot: Snapshot) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.dir / f"{stamp}-{snapshot.snapshot_id}{SNAPSHOT_SUFFIX}"
        from devrepro.snapshots.store import save_snapshot

        return save_snapshot(snapshot, path)

    def latest(self, n: int = 2) -> list[Snapshot]:
        out: list[Snapshot] = []
        for path in reversed(self.list_snapshots()[-n:]):
            try:
                out.append(load_snapshot(path))
            except Exception:
                continue
        return out


class DriftItem:
    __slots__ = ("detail", "kind", "name")

    def __init__(self, name: str, kind: str, detail: str) -> None:
        self.name = name
        self.kind = kind
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind, "detail": self.detail}


def compute_drift(previous: Snapshot, current: Snapshot) -> list[DriftItem]:
    """Human-readable drift between two stored snapshots."""
    diff = diff_snapshots(previous, current)
    items: list[DriftItem] = []
    for e in diff.entries:
        if e.classification == DiffClassification.SAME:
            continue
        kind = e.classification.value
        if e.component == "tool" and e.classification == DiffClassification.VERSION_DRIFT:
            kind = "runtime-changed"
        elif e.component == "container":
            kind = "docker-state-changed"
        elif e.component == "path":
            kind = "path-precedence-changed"
        elif e.classification == DiffClassification.MISSING:
            kind = "tool-missing"
        items.append(DriftItem(e.name, kind, e.detail or ""))
    return items


def _unused_json_guard() -> None:  # pragma: no cover
    json.dumps({})
