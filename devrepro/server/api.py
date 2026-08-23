"""Self-hosted fleet service: HTTP API over ServerDB.

Flask-based modular monolith. Auth via service-account bearer tokens and
machine enrollment tokens. RBAC enforced per endpoint:
  admin      -> everything incl. user/policy management
  maintainer -> snapshots, baselines, exceptions review, webhooks
  viewer     -> read-only fleet data
  agent      -> publish own machine snapshots only

Endpoints are versioned under /api/v1. Health/readiness at /healthz.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast

from flask import Flask, Response, g, jsonify, request

if TYPE_CHECKING:
    from devrepro.server.db import ServerDB

__all__ = ["create_app"]

ROLE_RANK = {"viewer": 1, "maintainer": 2, "admin": 3}

F = TypeVar("F", bound=Callable[..., Any])


def _err(status: int, message: str) -> tuple[Response, int]:
    return jsonify({"error": message}), status


def create_app(db: ServerDB) -> Flask:
    app = Flask("devrepro-server")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MiB body cap

    def require_role(min_role: str) -> Callable[[F], F]:
        def deco(fn: F) -> F:
            @wraps(fn)
            def wrapper(*args: object, **kwargs: object) -> Any:
                auth = request.headers.get("Authorization", "")
                token = auth.removeprefix("Bearer ").strip()
                if not token:
                    return _err(401, "missing bearer token")
                ident = db.authenticate_service_token(token)
                if not ident:
                    return _err(403, "invalid or revoked token")
                g.identity = ident
                if ROLE_RANK.get(str(ident["role"]), 0) < ROLE_RANK[min_role]:
                    return _err(403, f"requires role {min_role}")
                return fn(*args, **kwargs)

            return cast("F", wrapper)

        return deco

    # ---- health ------------------------------------------------------------

    @app.get("/healthz")
    @app.get("/api/v1/health")
    def health() -> Response:
        return jsonify(db.health())

    # ---- enrollment (agent bootstrap; no bearer yet) -------------------------

    @app.post("/api/v1/enroll")
    def enroll() -> Response | tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        token = str(body.get("enrollment_token", ""))
        machine_key = str(body.get("machine_key", "")).strip()
        os_name = str(body.get("os_name", "unknown"))
        arch = str(body.get("arch", "unknown"))
        if not token or not machine_key:
            return _err(400, "enrollment_token and machine_key required")
        machine_id = db.redeem_enrollment_token(token, machine_key)
        if machine_id is None:
            return _err(403, "invalid, used or expired enrollment token")
        db.register_machine(
            int(body.get("org_id", 0)) or _org_for_machine(machine_id), machine_key, os_name, arch
        )
        db.audit(
            _org_for_machine(machine_id),
            f"machine:{machine_key}",
            "machine.enroll",
            str(machine_id),
        )
        return jsonify({"machine_id": machine_id})

    def _org_for_machine(machine_id: int) -> int:
        row = db._conn.execute("SELECT org_id FROM machines WHERE id=?", (machine_id,)).fetchone()
        return int(row["org_id"]) if row else 0

    # ---- machines / snapshots -------------------------------------------------

    @app.post("/api/v1/snapshots")
    def publish_snapshot() -> Response | tuple[Response, int]:
        """Agent endpoint: machine publishes its own sanitized snapshots."""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _err(400, "JSON body required")
        machine_key = str(body.get("machine_key", "")).strip()
        if not machine_key:
            return _err(400, "machine_key required")
        row = db._conn.execute(
            "SELECT * FROM machines WHERE machine_key=?", (machine_key,)
        ).fetchone()
        if not row:
            return _err(403, "unknown machine; enroll first")
        snap = body.get("snapshot")
        if not isinstance(snap, dict):
            return _err(400, "snapshot object required")
        privacy = str(snap.get("privacy_state") or snap.get("privacy") or "sanitized")
        if privacy != "sanitized":
            return _err(422, "only sanitized snapshots may be published to the fleet")
        stored = db.store_snapshot(int(row["id"]), snap)
        db.audit(
            int(row["org_id"]),
            f"machine:{machine_key}",
            "snapshot.publish",
            str(snap.get("snapshot_id")),
            stored=stored,
        )
        for hook in db.webhooks_for(int(row["org_id"]), "snapshot.published"):
            _fire_webhook(
                hook, {"event": "snapshot.published", "snapshot_id": snap.get("snapshot_id")}
            )
        return jsonify({"stored": stored})

    @app.get("/api/v1/machines")
    @require_role("viewer")
    def list_machines() -> Response:
        rows = db._conn.execute(
            "SELECT m.id, m.machine_key, m.os_name, m.arch, m.label, m.last_seen_at,"
            " p.name AS project FROM machines m LEFT JOIN projects p ON p.id=m.project_id"
            " WHERE m.org_id=? ORDER BY m.last_seen_at DESC",
            (g.identity["org_id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/v1/snapshots")
    @require_role("viewer")
    def list_snapshots() -> Response:
        return jsonify(db.list_snapshots(int(g.identity["org_id"])))

    # ---- baselines ---------------------------------------------------------------

    @app.post("/api/v1/baselines")
    @require_role("maintainer")
    def approve_baseline() -> Response | tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        project_id = int(body.get("project_id", 0))
        baseline = body.get("baseline")
        approver = str(g.identity["name"])
        if not project_id or not isinstance(baseline, dict):
            return _err(400, "project_id and baseline required")
        bid = db.approve_baseline(project_id, baseline, approver)
        db.audit(int(g.identity["org_id"]), approver, "baseline.approve", bid)
        return jsonify({"baseline_id": bid})

    @app.get("/api/v1/baselines/<int:project_id>")
    @require_role("viewer")
    def get_baseline(project_id: int) -> Response | tuple[Response, int]:
        b = db.latest_baseline(project_id)
        return (jsonify(b), 200) if b else _err(404, "no baseline")

    # ---- policy-as-code -------------------------------------------------------------

    @app.put("/api/v1/policies/<name>")
    @require_role("admin")
    def put_policy(name: str) -> Response | tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _err(400, "policy document must be a JSON object")
        pid = db.set_policy(int(g.identity["org_id"]), name, body)
        db.audit(int(g.identity["org_id"]), str(g.identity["name"]), "policy.set", name)
        return jsonify({"policy_id": pid})

    @app.get("/api/v1/policies/<name>")
    @require_role("viewer")
    def get_policy(name: str) -> Response | tuple[Response, int]:
        doc = db.active_policy(int(g.identity["org_id"]), name)
        return (jsonify(doc), 200) if doc else _err(404, "no active policy")

    # ---- exceptions -------------------------------------------------------------------

    @app.post("/api/v1/exceptions")
    @require_role("maintainer")
    def request_exception() -> Response | tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        rule_id = str(body.get("rule_id", ""))
        justification = str(body.get("justification", ""))
        days = min(max(int(body.get("days", 30)), 1), 365)
        if not rule_id or len(justification) < 10:
            return _err(400, "rule_id and justification (>=10 chars) required")
        eid = db.request_exception(
            int(g.identity["org_id"]), rule_id, justification, str(g.identity["name"]), days
        )
        db.audit(int(g.identity["org_id"]), str(g.identity["name"]), "exception.request", rule_id)
        return jsonify({"exception_id": eid}), 201

    @app.post("/api/v1/exceptions/<int:eid>/review")
    @require_role("admin")
    def review_exception(eid: int) -> Response | tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        approve = bool(body.get("approve"))
        ok = db.review_exception(eid, str(g.identity["name"]), approve)
        if not ok:
            return _err(409, "not pending or already reviewed")
        db.audit(
            int(g.identity["org_id"]),
            str(g.identity["name"]),
            "exception.review",
            str(eid),
            approved=approve,
        )
        return jsonify({"status": "approved" if approve else "rejected"})

    # ---- audit ------------------------------------------------------------------------------

    @app.get("/api/v1/audit")
    @require_role("admin")
    def audit_log() -> Response:
        return jsonify(db.audit_log(int(g.identity["org_id"])))

    # ---- retention -----------------------------------------------------------------------------

    @app.put("/api/v1/retention")
    @require_role("admin")
    def put_retention() -> Response:
        body = request.get_json(silent=True) or {}
        db.set_retention(
            int(g.identity["org_id"]),
            int(body.get("snapshot_days", 90)),
            int(body.get("audit_days", 365)),
        )
        db.audit(int(g.identity["org_id"]), str(g.identity["name"]), "retention.set", "org")
        return jsonify({"ok": True})

    @app.post("/api/v1/retention/apply")
    @require_role("admin")
    def apply_retention() -> Response:
        result = db.apply_retention(int(g.identity["org_id"]))
        db.audit(
            int(g.identity["org_id"]), str(g.identity["name"]), "retention.apply", "org", **result
        )
        return jsonify(result)

    # ---- webhooks ---------------------------------------------------------------------------

    @app.post("/api/v1/webhooks")
    @require_role("admin")
    def add_webhook() -> Response | tuple[Response, int]:
        import secrets as _secrets

        body = request.get_json(silent=True) or {}
        url = str(body.get("url", ""))
        events = list(body.get("events", ["*"]))
        if not url.startswith(("https://", "http://localhost")):
            return _err(400, "webhook URL must be https (or localhost for dev)")
        secret = "ddwh_" + _secrets.token_urlsafe(32)
        wid = db.add_webhook(int(g.identity["org_id"]), url, secret, events)
        db.audit(int(g.identity["org_id"]), str(g.identity["name"]), "webhook.add", url)
        return jsonify({"id": wid, "secret": secret}), 201  # secret shown once

    @app.errorhandler(413)
    def too_large(_e: object) -> tuple[Response, int]:
        return _err(413, "request body too large")

    return app


def _fire_webhook(hook: dict[str, object], payload: dict[str, object]) -> None:
    """Signed webhook delivery (HMAC-SHA256). Failures never break the API."""
    import urllib.error
    import urllib.request

    body = json.dumps(payload, default=str).encode("utf-8")
    sig = hmac.new(str(hook["secret"]).encode("utf-8"), body, hashlib.sha256).hexdigest()
    # scheme is validated at registration time (https or localhost only)
    req = urllib.request.Request(  # noqa: S310
        str(hook["url"]),
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-DevRepro-Signature": f"sha256={sig}",
            "User-Agent": "devrepro-doctor-webhook/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310
            resp.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        pass  # delivery is best-effort; retries belong to a background worker
