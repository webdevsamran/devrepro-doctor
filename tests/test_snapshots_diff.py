"""Snapshot round-trip, diff classification and history drift."""

from __future__ import annotations

import json

from devrepro.core.models import (
    DiffClassification,
    PlatformInfo,
    Snapshot,
    ToolInstallation,
)
from devrepro.diff.engine import diff_snapshots
from devrepro.snapshots.store import load_snapshot, save_snapshot
from devrepro.snapshots.history import compute_drift


def _snap(sid: str, pyver: str, extra_tool: bool = False) -> Snapshot:
    tools = [ToolInstallation(name="python", version=pyver, exe_path="/usr/bin/python")]
    if extra_tool:
        tools.append(ToolInstallation(name="docker", version="24.0.7", exe_path="/usr/bin/docker"))
    snap = Snapshot(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="Linux", os_version="6.5", arch="x86_64"),
        tools=tuple(tools),
    )
    object.__setattr__(snap, "_label", sid)
    return snap


def test_roundtrip(tmp_path) -> None:
    s = _snap("t1", "3.12.4")
    p = save_snapshot(s, tmp_path / "s.json")
    loaded = load_snapshot(p)
    assert loaded.snapshot_id == s.snapshot_id
    assert loaded.tools[0].version == "3.12.4"


def test_version_drift_classified() -> None:
    d = diff_snapshots(_snap("a", "3.11.8"), _snap("b", "3.12.4"))
    entry = next(e for e in d.entries if e.name == "python")
    assert entry.classification == DiffClassification.VERSION_DRIFT


def test_missing_tool_classified() -> None:
    d = diff_snapshots(_snap("a", "3.12.4"), _snap("b", "3.12.4", extra_tool=True))
    docker = next(e for e in d.entries if e.name == "docker")
    assert docker.classification == DiffClassification.MISSING


def test_same_snapshot_all_same() -> None:
    d = diff_snapshots(_snap("a", "3.12.4"), _snap("b", "3.12.4"))
    assert all(e.classification == DiffClassification.SAME for e in d.entries)


def test_diff_json_serializable() -> None:
    d = diff_snapshots(_snap("a", "3.11"), _snap("b", "3.12"))
    payload = json.dumps(d.model_dump(mode="json"), default=str)
    assert "version-drift" in payload


def test_drift_kinds() -> None:
    items = compute_drift(_snap("prev", "3.11.8"), _snap("cur", "3.12.4"))
    kinds = {i.kind for i in items}
    assert "runtime-changed" in kinds