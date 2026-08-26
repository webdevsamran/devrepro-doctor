"""Self-hosted server tests: RBAC, enrollment, snapshots, policy, audit,
exceptions, retention and multi-tenant authorization isolation."""

from __future__ import annotations

import pytest
from devrepro.server.api import create_app
from devrepro.server.db import ServerDB


@pytest.fixture()
def db(tmp_path):  # type: ignore[no-untyped-def]
    return ServerDB(tmp_path / "fleet.db")


@pytest.fixture()
def client(db):  # type: ignore[no-untyped-def]
    app = create_app(db)
    app.testing = True
    return app.test_client()


def _setup_org(db) -> dict[str, str]:  # type: ignore[no-untyped-def]
    org = db.create_organization("acme")
    _admin_id, admin_tok = db.create_service_account(org, "admin-sa", "admin")
    _maint_id, maint_tok = db.create_service_account(org, "maint-sa", "maintainer")
    _view_id, view_tok = db.create_service_account(org, "view-sa", "viewer")
    return {
        "org": str(org),
        "admin": admin_tok,
        "maintainer": maint_tok,
        "viewer": view_tok,
    }


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# ---------- metrics ----------


def test_metrics_prometheus_format(db, client) -> None:  # type: ignore[no-untyped-def]
    org = db.create_organization("metrics-org")
    db.create_service_account(org, "sa", "admin")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "devrepro_machines_enrolled" in body
    assert "devrepro_snapshots_published" in body
    assert "# TYPE devrepro_organizations_total gauge" in body


# ---------- health & auth ----------


def test_health(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_missing_token_rejected(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/machines").status_code == 401
    assert (
        client.get("/api/v1/machines", headers={"Authorization": "Bearer nope"}).status_code == 403
    )


# ---------- RBAC ----------


def test_rbac_viewer_cannot_set_policy(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    r = client.put(
        "/api/v1/policies/tool-versions",
        headers=_auth(ids["viewer"]),
        json={"min_python": "3.11"},
    )
    assert r.status_code == 403


def test_rbac_admin_sets_and_reads_policy(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    r = client.put(
        "/api/v1/policies/tool-versions",
        headers=_auth(ids["admin"]),
        json={"min_python": "3.11", "forbidden": ["python<3.9"]},
    )
    assert r.status_code == 200
    got = client.get("/api/v1/policies/tool-versions", headers=_auth(ids["viewer"])).get_json()
    assert got["min_python"] == "3.11"


# ---------- enrollment & snapshot publication ----------


def test_enrollment_single_use_and_snapshot_flow(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    tok = db.create_enrollment_token(int(ids["org"]), "laptop-lab")
    r = client.post("/api/v1/enroll", json={"enrollment_token": tok, "machine_key": "mk-1"})
    assert r.status_code == 200
    machine_id = r.get_json()["machine_id"]
    # second redemption must fail (single-use)
    r2 = client.post("/api/v1/enroll", json={"enrollment_token": tok, "machine_key": "mk-2"})
    assert r2.status_code == 403

    snap = {
        "snapshot_id": "snap-001",
        "privacy_state": "sanitized",
        "tools": {"python": "3.12.1"},
    }
    pub = client.post(
        "/api/v1/snapshots",
        json={"machine_key": "mk-1", "snapshot": snap},
    )
    assert pub.status_code == 200
    assert pub.get_json()["stored"] is True
    # idempotent republication is accepted but not duplicated
    pub2 = client.post("/api/v1/snapshots", json={"machine_key": "mk-1", "snapshot": snap})
    assert pub2.get_json()["stored"] is False

    snaps = client.get("/api/v1/snapshots", headers=_auth(ids["viewer"])).get_json()
    assert len(snaps) == 1
    assert snaps[0]["snapshot_id"] == "snap-001"
    assert snaps[0]["machine_key"] == "mk-1"
    assert machine_id >= 1


def test_unsanitized_snapshot_rejected(db, client) -> None:  # type: ignore[no-untyped-def]
    _setup_org(db)
    tok = db.create_enrollment_token(1, "t2")
    client.post("/api/v1/enroll", json={"enrollment_token": tok, "machine_key": "mk-x"})
    r = client.post(
        "/api/v1/snapshots",
        json={
            "machine_key": "mk-x",
            "snapshot": {"snapshot_id": "s", "privacy_state": "full"},
        },
    )
    assert r.status_code == 422


# ---------- baselines ----------


def test_baseline_approve_requires_maintainer(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    pid = db.upsert_project(int(ids["org"]), "webapp", "fp-123")
    baseline = {"baseline_id": "b-1", "tools": {"python": ">=3.11"}}
    r = client.post(
        "/api/v1/baselines",
        headers=_auth(ids["maintainer"]),
        json={"project_id": pid, "baseline": baseline},
    )
    assert r.status_code == 200
    got = client.get(f"/api/v1/baselines/{pid}", headers=_auth(ids["viewer"]))
    assert got.get_json()["baseline_id"] == "b-1"


# ---------- exceptions workflow ----------


def test_exception_request_review_expiry(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    req = client.post(
        "/api/v1/exceptions",
        headers=_auth(ids["maintainer"]),
        json={
            "rule_id": "py/old-python",
            "justification": "legacy vendor app needs 3.8",
            "days": 14,
        },
    )
    assert req.status_code == 201
    eid = req.get_json()["exception_id"]
    # viewer cannot review
    rv = client.post(
        f"/api/v1/exceptions/{eid}/review", headers=_auth(ids["viewer"]), json={"approve": True}
    )
    assert rv.status_code == 403
    ok = client.post(
        f"/api/v1/exceptions/{eid}/review", headers=_auth(ids["admin"]), json={"approve": True}
    )
    assert ok.get_json()["status"] == "approved"
    active = db.active_exceptions(int(ids["org"]))
    assert any(e["rule_id"] == "py/old-python" for e in active)


# ---------- audit trail ----------


def test_audit_records_sensitive_actions(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    client.put("/api/v1/policies/x", headers=_auth(ids["admin"]), json={"a": 1})
    log = client.get("/api/v1/audit", headers=_auth(ids["admin"])).get_json()
    actions = [e["action"] for e in log]
    assert "policy.set" in actions
    # viewer cannot read audit
    assert client.get("/api/v1/audit", headers=_auth(ids["viewer"])).status_code == 403


# ---------- retention ----------


def test_retention_deletes_old_snapshots(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    tok = db.create_enrollment_token(int(ids["org"]), "m")
    client.post("/api/v1/enroll", json={"enrollment_token": tok, "machine_key": "mk-r"})
    client.post(
        "/api/v1/snapshots",
        json={
            "machine_key": "mk-r",
            "snapshot": {"snapshot_id": "old", "privacy_state": "sanitized"},
        },
    )
    client.put(
        "/api/v1/retention", headers=_auth(ids["admin"]), json={"snapshot_days": 0, "audit_days": 0}
    )
    res = client.post("/api/v1/retention/apply", headers=_auth(ids["admin"])).get_json()
    assert res["snapshots_deleted"] >= 1
    assert client.get("/api/v1/snapshots", headers=_auth(ids["viewer"])).get_json() == []


# ---------- multi-tenant isolation ----------


def test_cross_tenant_isolation(db, client) -> None:  # type: ignore[no-untyped-def]
    org_a = db.create_organization("tenant-a")
    org_b = db.create_organization("tenant-b")
    _, tok_b = db.create_service_account(org_b, "sa-b", "admin")
    db.upsert_project(org_a, "secret-project", "fp-a")
    # tenant B cannot see tenant A machines/snapshots
    machines = client.get("/api/v1/machines", headers=_auth(tok_b)).get_json()
    assert machines == []
    # tenant B cannot read tenant A policy
    assert client.get("/api/v1/policies/x", headers=_auth(tok_b)).status_code == 404


# ---------- webhooks ----------


def test_webhook_registration_returns_secret_once(db, client) -> None:  # type: ignore[no-untyped-def]
    ids = _setup_org(db)
    r = client.post(
        "/api/v1/webhooks",
        headers=_auth(ids["admin"]),
        json={"url": "https://hooks.example.com/dd", "events": ["snapshot.published"]},
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["secret"].startswith("ddwh_")
    # insecure remote http rejected
    bad = client.post(
        "/api/v1/webhooks",
        headers=_auth(ids["admin"]),
        json={"url": "http://insecure.example.com/hook"},
    )
    assert bad.status_code == 400
