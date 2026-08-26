"""Server backup and restore with integrity verification.

Exports the SQLite fleet database to a timestamped ``.tar.gz`` archive
containing the database file plus a SHA-256 manifest. Restore refuses to
touch the target unless every checksum in the manifest verifies first, so
a corrupted or truncated archive can never replace a working database.

Backups contain whatever snapshots organizations published; treat the
archive as sensitive (machine metadata, never secret values).
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["BackupResult", "RestoreError", "backup_database", "restore_database"]

BACKUP_FORMAT = "devrepro-server-backup"
BACKUP_VERSION = 1


@dataclass(frozen=True)
class BackupResult:
    path: Path
    members: int
    sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def backup_database(db_path: Path, out_path: Path | None = None) -> BackupResult:
    """Archive *db_path* (plus -wal/-shm siblings if present) with a manifest."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise RestoreError(f"database not found: {db_path.name}")
    if out_path is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = db_path.parent / f"devrepro-backup-{stamp}.tar.gz"

    members: dict[str, bytes] = {}
    for suffix in ("", "-wal", "-shm"):
        candidate = db_path.with_name(db_path.name + suffix)
        if candidate.is_file():
            members[db_path.name + suffix] = candidate.read_bytes()

    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "members": {name: _sha256(blob) for name, blob in sorted(members.items())},
    }

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, blob in sorted(members.items()):
            info = tarfile.TarInfo(name=name)
            info.size = len(blob)
            tf.addfile(info, io.BytesIO(blob))
        manifest_blob = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_blob)
        tf.addfile(info, io.BytesIO(manifest_blob))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())
    return BackupResult(out_path, len(members), _sha256(buf.getvalue()))


class RestoreError(Exception):
    """Raised when a backup cannot be verified or applied safely."""


def restore_database(archive: Path, target_db: Path, *, overwrite: bool = False) -> Path:
    """Verify *archive* checksums, then place its database at *target_db*.

    Refuses to overwrite an existing database unless ``overwrite`` is set;
    refuses any archive whose manifest does not verify byte-for-byte.
    """
    archive = Path(archive)
    target_db = Path(target_db)
    if not archive.is_file():
        raise RestoreError(f"archive not found: {archive}")
    if target_db.exists() and not overwrite:
        raise RestoreError(f"refusing to overwrite existing {target_db}; pass overwrite=True")

    try:
        with tarfile.open(archive, "r:gz") as tf:
            names = tf.getnames()
            if "manifest.json" not in names:
                raise RestoreError("archive has no manifest.json")
            extracted = {
                name: tf.extractfile(name).read()  # type: ignore[union-attr]
                for name in names
                if name != "manifest.json" and tf.extractfile(name) is not None
            }
            import json as _json

            mfile = tf.extractfile("manifest.json")
            assert mfile is not None  # noqa: S101 - guarded by membership check above
            manifest = _json.loads(mfile.read())
    except tarfile.TarError as exc:
        raise RestoreError(f"unreadable archive: {exc}") from exc

    declared = manifest.get("members")
    if not isinstance(declared, dict):
        raise RestoreError("manifest lacks member checksums")

    # Verify BEFORE writing anything.
    for name, digest in sorted(declared.items()):
        blob = extracted.get(name)
        if blob is None:
            raise RestoreError(f"manifest declares missing member '{name}'")
        if _sha256(blob) != digest:
            raise RestoreError(f"checksum mismatch for '{name}'; archive is corrupt")

    if manifest.get("format") != BACKUP_FORMAT:
        raise RestoreError(f"not a {BACKUP_FORMAT!r} archive")

    main_name = target_db.name
    if main_name not in extracted:
        raise RestoreError(f"archive contains no database file named '{main_name}'")

    target_db.parent.mkdir(parents=True, exist_ok=True)
    for name, blob in extracted.items():
        target_db.with_name(name).write_bytes(blob)
    return target_db
