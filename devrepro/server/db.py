"""Self-hosted server storage: SQLite schema and data access.

Modular monolith design: one SQLite file per deployment; PostgreSQL can be
swapped in later for multi-user scale without changing call sites.

Tables cover the team/enterprise model:
organizations -> projects -> machines -> snapshots,
users/service_accounts with RBAC roles, baselines, policy documents,
immutable audit events, policy exceptions, webhooks and retention settings.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["ServerDB", "hash_token"]

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK(role IN ('admin','maintainer','viewer')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','maintainer','viewer','agent')),
    token_hash TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS enrollment_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    expires_at TEXT,
    used_by_machine INTEGER REFERENCES machines(id),
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(org_id, name)
);
CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    project_id INTEGER REFERENCES projects(id),
    machine_key TEXT NOT NULL,
    os_name TEXT NOT NULL,
    arch TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    enrolled_at TEXT NOT NULL,
    last_seen_at TEXT,
    UNIQUE(org_id, machine_key)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    snapshot_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    privacy_state TEXT NOT NULL DEFAULT 'sanitized',
    checksum TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(machine_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    baseline_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    approved_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, baseline_id)
);
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    document TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(org_id, name)
);
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    rule_id TEXT NOT NULL,
    justification TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    reviewed_by TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','approved','rejected','expired')),
    expires_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retention_policies (
    org_id INTEGER PRIMARY KEY REFERENCES organizations(id),
    snapshot_days INTEGER NOT NULL DEFAULT 90,
    audit_days INTEGER NOT NULL DEFAULT 365
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def hash_token(token: str) -> str:
    """Hash an enrollment/service token for at-rest storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ServerDB:
    """SQLite-backed store for the self-hosted fleet service."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    @contextmanager
    def tx(self):  # type: ignore[no-untyped-def]
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---- organizations / users -------------------------------------------

    def create_organization(self, name: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO organizations(name, created_at) VALUES(?,?)", (name, _now())
            )
            return int(cur.lastrowid)

    def create_user(self, org_id: int, name: str, email: str, role: str) -> int:
        if role not in ("admin", "maintainer", "viewer"):
            raise ValueError(f"invalid role {role!r}")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO users(org_id,name,email,role,created_at) VALUES(?,?,?,?,?)",
                (org_id, name, email, role, _now()),
            )
            return int(cur.lastrowid)

    def get_user_role(self, email: str) -> str | None:
        row = self._conn.execute("SELECT role FROM users WHERE email=?", (email,)).fetchone()
        return str(row["role"]) if row else None

    # ---- service accounts & enrollment ------------------------------------

    def create_service_account(self, org_id: int, name: str, role: str) -> tuple[int, str]:
        """Create a service account; returns (id, plaintext-token-shown-once)."""
        if role not in ("admin", "maintainer", "viewer", "agent"):
            raise ValueError(f"invalid role {role!r}")
        token = "ddsa_" + secrets.token_urlsafe(32)
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO service_accounts(org_id,name,role,token_hash,created_at)"
                " VALUES(?,?,?,?,?)",
                (org_id, name, role, hash_token(token), _now()),
            )
            return int(cur.lastrowid), token

    def authenticate_service_token(self, token: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM service_accounts WHERE token_hash=? AND revoked_at IS NULL",
            (hash_token(token),),
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "org_id": row["org_id"], "name": row["name"], "role": row["role"]}

    def revoke_service_account(self, account_id: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE service_accounts SET revoked_at=? WHERE id=?", (_now(), account_id))

    def create_enrollment_token(self, org_id: int, label: str, ttl_days: int = 30) -> str:
        from datetime import timedelta

        token = "dden_" + secrets.token_urlsafe(32)
        expires = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat()
        with self.tx() as c:
            c.execute(
                "INSERT INTO enrollment_tokens(org_id,token_hash,label,expires_at,created_at)"
                " VALUES(?,?,?,?,?)",
                (org_id, hash_token(token), label, expires, _now()),
            )
        return token

    def redeem_enrollment_token(self, token: str, machine_key: str) -> int | None:
        """Redeem a token for a new machine identity; single-use."""
        row = self._conn.execute(
            "SELECT * FROM enrollment_tokens WHERE token_hash=? AND revoked_at IS NULL"
            " AND used_by_machine IS NULL",
            (hash_token(token),),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] and row["expires_at"] < _now():
            return None
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO machines(org_id,machine_key,os_name,arch,enrolled_at)"
                " VALUES(?,?,?,?,?)",
                (row["org_id"], machine_key, "unknown", "unknown", _now()),
            )
            machine_id = int(cur.lastrowid)
            c.execute(
                "UPDATE enrollment_tokens SET used_by_machine=? WHERE id=?",
                (machine_id, row["id"]),
            )
        return machine_id

    # ---- projects / machines / snapshots ----------------------------------

    def upsert_project(self, org_id: int, name: str, fingerprint: str) -> int:
        with self.tx() as c:
            row = c.execute(
                "SELECT id FROM projects WHERE org_id=? AND name=?", (org_id, name)
            ).fetchone()
            if row:
                c.execute("UPDATE projects SET fingerprint=? WHERE id=?", (fingerprint, row["id"]))
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO projects(org_id,name,fingerprint,created_at) VALUES(?,?,?,?)",
                (org_id, name, fingerprint, _now()),
            )
            return int(cur.lastrowid)

    def register_machine(self, org_id: int, machine_key: str, os_name: str, arch: str) -> int:
        with self.tx() as c:
            row = c.execute(
                "SELECT id FROM machines WHERE org_id=? AND machine_key=?",
                (org_id, machine_key),
            ).fetchone()
            if row:
                c.execute(
                    "UPDATE machines SET os_name=?, arch=?, last_seen_at=? WHERE id=?",
                    (os_name, arch, _now(), row["id"]),
                )
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO machines(org_id,machine_key,os_name,arch,enrolled_at,last_seen_at)"
                " VALUES(?,?,?,?,?,?)",
                (org_id, machine_key, os_name, arch, _now(), _now()),
            )
            return int(cur.lastrowid)

    def store_snapshot(self, machine_id: int, snap: dict[str, object]) -> bool:
        """Store a sanitized snapshot; idempotent per (machine, snapshot_id)."""
        import hashlib as _hl

        raw = json.dumps(snap, sort_keys=True, default=str).encode("utf-8")
        sid = str(snap.get("snapshot_id") or snap.get("id") or "")
        if not sid:
            raise ValueError("snapshot payload missing snapshot_id")
        checksum = _hl.sha256(raw).hexdigest()
        try:
            with self.tx() as c:
                c.execute(
                    "INSERT INTO snapshots(machine_id,snapshot_id,payload,checksum,received_at)"
                    " VALUES(?,?,?,?,?)",
                    (machine_id, sid, json.dumps(snap, default=str), checksum, _now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_snapshots(self, org_id: int, limit: int = 100) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT s.snapshot_id, s.received_at, s.checksum, m.machine_key,"
            " m.os_name, m.arch FROM snapshots s JOIN machines m ON m.id=s.machine_id"
            " WHERE m.org_id=? ORDER BY s.received_at DESC LIMIT ?",
            (org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- baselines ---------------------------------------------------------

    def approve_baseline(self, project_id: int, baseline: dict[str, object], approver: str) -> str:
        bid = str(baseline.get("baseline_id") or "")
        user = self._conn.execute("SELECT id FROM users WHERE email=?", (approver,)).fetchone()
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO baselines(project_id,baseline_id,payload,approved_by,"
                "created_at) VALUES(?,?,?,?,?)",
                (
                    project_id,
                    bid,
                    json.dumps(baseline, default=str),
                    user["id"] if user else None,
                    _now(),
                ),
            )
        return bid

    def latest_baseline(self, project_id: int) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT payload FROM baselines WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    # ---- policy-as-code -----------------------------------------------------

    def set_policy(self, org_id: int, name: str, document: dict[str, object]) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO policies(org_id,name,document,version,active,created_at)"
                " VALUES(?,?,?,1,1,?)",
                (org_id, name, json.dumps(document, default=str), _now()),
            )
            return int(cur.lastrowid)

    def active_policy(self, org_id: int, name: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT document FROM policies WHERE org_id=? AND name=? AND active=1"
            " ORDER BY version DESC LIMIT 1",
            (org_id, name),
        ).fetchone()
        return json.loads(row["document"]) if row else None

    # ---- audit -------------------------------------------------------------

    def audit(self, org_id: int, actor: str, action: str, target: str, **detail: object) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO audit_events(org_id,actor,action,target,detail,occurred_at)"
                " VALUES(?,?,?,?,?,?)",
                (org_id, actor, action, target, json.dumps(detail, default=str), _now()),
            )

    def audit_log(self, org_id: int, limit: int = 200) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT actor,action,target,detail,occurred_at FROM audit_events"
            " WHERE org_id=? ORDER BY seq DESC LIMIT ?",
            (org_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"])
            out.append(d)
        return out

    # ---- exceptions ----------------------------------------------------------

    def request_exception(
        self, org_id: int, rule_id: str, justification: str, requester: str, days: int
    ) -> int:
        from datetime import timedelta

        expires = (datetime.now(UTC) + timedelta(days=days)).isoformat()
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO exceptions(org_id,rule_id,justification,requested_by,status,"
                "expires_at,created_at) VALUES(?,?,?,?,'pending',?,?)",
                (org_id, rule_id, justification, requester, expires, _now()),
            )
            return int(cur.lastrowid)

    def review_exception(self, exception_id: int, reviewer: str, approve: bool) -> bool:
        status = "approved" if approve else "rejected"
        with self.tx() as c:
            cur = c.execute(
                "UPDATE exceptions SET status=?, reviewed_by=? WHERE id=? AND status='pending'",
                (status, reviewer, exception_id),
            )
            return bool(cur.rowcount)

    def active_exceptions(self, org_id: int) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT rule_id,expires_at FROM exceptions WHERE org_id=? AND status='approved'"
            " AND (expires_at IS NULL OR expires_at > ?)",
            (org_id, _now()),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- webhooks ------------------------------------------------------------

    def add_webhook(self, org_id: int, url: str, secret: str, events: list[str]) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO webhooks(org_id,url,secret,events,created_at) VALUES(?,?,?,?,?)",
                (org_id, url, secret, json.dumps(events), _now()),
            )
            return int(cur.lastrowid)

    def webhooks_for(self, org_id: int, event: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT id,url,secret,events FROM webhooks WHERE org_id=? AND active=1",
            (org_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "url": r["url"],
                "secret": r["secret"],
                "events": json.loads(r["events"]),
            }
            for r in rows
            if event in json.loads(r["events"]) or "*" in json.loads(r["events"])
        ]

    # ---- retention ------------------------------------------------------------

    def set_retention(self, org_id: int, snapshot_days: int, audit_days: int) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO retention_policies(org_id,snapshot_days,audit_days)"
                " VALUES(?,?,?)",
                (org_id, snapshot_days, audit_days),
            )

    def apply_retention(self, org_id: int) -> dict[str, int]:
        from datetime import timedelta

        row = self._conn.execute(
            "SELECT snapshot_days,audit_days FROM retention_policies WHERE org_id=?",
            (org_id,),
        ).fetchone()
        snap_days = int(row["snapshot_days"]) if row else 90
        audit_days = int(row["audit_days"]) if row else 365
        snap_cutoff = (datetime.now(UTC) - timedelta(days=snap_days)).isoformat()
        audit_cutoff = (datetime.now(UTC) - timedelta(days=audit_days)).isoformat()
        with self.tx() as c:
            cur_snap = c.execute(
                "DELETE FROM snapshots WHERE received_at < ? AND machine_id IN"
                " (SELECT id FROM machines WHERE org_id=?)",
                (snap_cutoff, org_id),
            )
            cur_audit = c.execute(
                "DELETE FROM audit_events WHERE org_id=? AND occurred_at < ?",
                (org_id, audit_cutoff),
            )
        return {"snapshots_deleted": cur_snap.rowcount, "audit_deleted": cur_audit.rowcount}

    # ---- health -----------------------------------------------------------------

    def health(self) -> dict[str, object]:
        try:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM organizations").fetchone()
            return {
                "status": "ok",
                "storage": "sqlite",
                "schema_version": SCHEMA_VERSION,
                "organizations": row["n"],
            }
        except sqlite3.Error as exc:
            return {"status": "degraded", "error": str(exc)}

    def close(self) -> None:
        self._conn.close()
