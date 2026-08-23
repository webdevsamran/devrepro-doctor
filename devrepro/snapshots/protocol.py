"""Snapshot protocol v2: versions, provenance, field classification, migration.

Protocol v2 adds to v1 snapshots:
- explicit ``protocol_version`` and per-probe ``probe_versions``;
- ``policy_version`` of the applied .devrepro.toml contract;
- ``project_fingerprint`` (content hash of declared requirements);
- ``provenance`` (producer, host-class, redaction state);
- a field-classification registry (public / machine-sensitive / secret-forbidden)
  that the privacy gate enforces before serialization;
- forward-compatible migration from v1 payloads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "FIELD_CLASSES",
    "PROTOCOL_VERSION",
    "FieldClass",
    "classify_payload",
    "migrate_snapshot",
    "project_fingerprint",
]

PROTOCOL_VERSION = "2.0"


class FieldClass(StrEnum):
    PUBLIC = "public"
    MACHINE_SENSITIVE = "machine-sensitive"
    SECRET_FORBIDDEN = "secret-forbidden"  # noqa: S105 - classification name, not a credential


# Top-level snapshot fields -> classification. secret-forbidden fields must
# never appear in any exported artifact; machine-sensitive fields are kept
# locally but redacted/normalized in shared exports.
FIELD_CLASSES: dict[str, FieldClass] = {
    "schema_version": FieldClass.PUBLIC,
    "protocol_version": FieldClass.PUBLIC,
    "created_at": FieldClass.PUBLIC,
    "devrepro_version": FieldClass.PUBLIC,
    "platform": FieldClass.MACHINE_SENSITIVE,
    "tools": FieldClass.MACHINE_SENSITIVE,
    "path_analysis": FieldClass.MACHINE_SENSITIVE,
    "compilers": FieldClass.MACHINE_SENSITIVE,
    "requirements_fingerprint": FieldClass.PUBLIC,
    "containers": FieldClass.MACHINE_SENSITIVE,
    "wsl": FieldClass.MACHINE_SENSITIVE,
    "gpu": FieldClass.MACHINE_SENSITIVE,
    "virtualenvs": FieldClass.MACHINE_SENSITIVE,
    "score": FieldClass.PUBLIC,
    "privacy": FieldClass.PUBLIC,
    # forbidden anywhere near an export:
    "env_values": FieldClass.SECRET_FORBIDDEN,
    "credentials": FieldClass.SECRET_FORBIDDEN,
    "tokens": FieldClass.SECRET_FORBIDDEN,
}


@dataclass(frozen=True)
class Provenance:
    """Where a snapshot came from; no personal data."""

    producer: str = "devrepro-doctor"
    producer_version: str = ""
    scan_mode: str = "local"  # local | agent | remote
    redacted: bool = True
    policy_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "producer": self.producer,
            "producer_version": self.producer_version,
            "scan_mode": self.scan_mode,
            "redacted": self.redacted,
            "policy_version": self.policy_version,
        }


def project_fingerprint(requirements: list[dict[str, Any]]) -> str:
    """Deterministic fingerprint over declared requirements (names+specs only)."""
    canon = sorted(
        json.dumps(
            {"eco": r.get("ecosystem"), "name": r.get("name"), "spec": r.get("spec")},
            sort_keys=True,
        )
        for r in requirements
    )
    payload = json.dumps(canon, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def classify_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Return {field: class} for every top-level key present."""
    out: dict[str, str] = {}
    for key in payload:
        fc = FIELD_CLASSES.get(key)
        out[key] = fc.value if fc else "unclassified"
    return out


def migrate_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v1 snapshot payload to the current protocol version.

    v1 -> v2 changes:
    - add ``protocol_version``;
    - add empty ``provenance`` block when absent;
    - add ``project_fingerprint`` derived from requirements when absent.
    Unknown future versions raise ValueError (forward reader responsibility).
    """
    version = str(payload.get("schema_version", "1.0"))
    if version.startswith("2."):
        return payload
    if not version.startswith("1."):
        msg = f"unsupported snapshot schema_version: {version}"
        raise ValueError(msg)
    migrated = dict(payload)
    migrated["schema_version"] = PROTOCOL_VERSION
    migrated.setdefault("protocol_version", PROTOCOL_VERSION)
    if "provenance" not in migrated:
        producer_version = str(migrated.get("devrepro_version", ""))
        migrated["provenance"] = Provenance(producer_version=producer_version).as_dict()
    if "project_fingerprint" not in migrated:
        reqs = migrated.get("requirements_fingerprint") or []
        if isinstance(reqs, list) and reqs and isinstance(reqs[0], dict):
            migrated["project_fingerprint"] = project_fingerprint(reqs)
    return migrated


def load_snapshot_any_version(raw: bytes | str) -> dict[str, Any]:
    """Read a snapshot of any known protocol version, migrating as needed."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        msg = "snapshot payload must be a JSON object"
        raise TypeError(msg)
    return migrate_snapshot(data)
