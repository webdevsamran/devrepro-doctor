"""Snapshot creation, validation and storage.

Snapshots are privacy-sanitized by construction: they are built from
already-redacted scan data and pass through the PrivacyGate before being
written. Loading validates against the embedded schema version.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from devrepro.core.errors import SnapshotError, SnapshotSchemaError
from devrepro.core.models import ScanReport, Snapshot

__all__ = ["snapshot_from_report", "save_snapshot", "load_snapshot", "SNAPSHOT_SUFFIX"]

SNAPSHOT_SUFFIX = ".devrepro-snapshot.json"
SUPPORTED_SCHEMA_VERSIONS = ("1.0",)


def snapshot_from_report(report: ScanReport) -> Snapshot:
    """Build a Snapshot from a completed (already sanitized) ScanReport."""
    return Snapshot(
        schema_version="1.0",
        created_at=datetime.now(timezone.utc),
        devrepro_version=report.devrepro_version,
        platform=report.platform,
        tools=report.tools,
        path_analysis=report.path_analysis,
        compilers=tuple(t for t in report.tools if t.name in ("gcc", "clang", "cl", "rustc", "javac")),
        requirements_fingerprint=report.requirements,
        containers=None,
        wsl=None,
        gpu=None,
        virtualenvs=(),
        score=report.score,
        privacy=dict(report.privacy),
    )


def save_snapshot(snapshot: Snapshot, path: Path) -> Path:
    """Serialize after a final secret-scan of the payload itself."""
    from devrepro.privacy.gate import assert_no_secrets

    payload = json.dumps(snapshot.model_dump(mode="json"), indent=2, default=str)
    assert_no_secrets(payload)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + chr(10), encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"could not write snapshot to {path}: {exc}") from exc
    return path


def load_snapshot(path: Path) -> Snapshot:
    """Load and validate an untrusted snapshot file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SnapshotSchemaError(f"snapshot is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SnapshotSchemaError("snapshot must be a JSON object")
    version = str(data.get("schema_version", "?"))
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SnapshotSchemaError(
            f"unsupported snapshot schema_version {version!r} "
            f"(supported: {SUPPORTED_SCHEMA_VERSIONS})"
        )
    try:
        return Snapshot.model_validate(data)
    except ValidationError:
        pass
    # Tolerate full ScanReport exports: coerce to a Snapshot by keeping the
    # shared fields and dropping report-only ones (findings, probe_errors...).
    if {"findings", "requirements", "policy_applied"} & set(data):
        try:
            coerced = {
                k: v for k, v in data.items()
                if k in {
                    "schema_version", "created_at", "devrepro_version", "platform",
                    "tools", "path_analysis", "compilers", "containers", "wsl",
                    "gpu", "virtualenvs", "score", "privacy",
                }
            }
            coerced.setdefault("devrepro_version", data.get("devrepro_version", "unknown"))
            return Snapshot.model_validate(coerced)
        except ValidationError as exc:
            raise SnapshotSchemaError(f"snapshot failed validation: {exc}") from exc
    raise SnapshotSchemaError("snapshot failed validation: unrecognized snapshot shape")


def default_history_dir() -> Path:
    base = Path.home() / ".devrepro-doctor" / "history"
    base.mkdir(parents=True, exist_ok=True)
    return base