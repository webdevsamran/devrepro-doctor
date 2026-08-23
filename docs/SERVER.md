# Self-hosted fleet service

The optional team/enterprise layer: a Flask + SQLite modular monolith that
collects **sanitized** snapshots from enrolled machines and serves fleet
dashboards, baselines, policy, audit and retention.

Local-first remains the default — nothing here is required for single-user use.

## Quick start (Python API)

```python
from devrepro.server import ServerDB, create_app

db = ServerDB("fleet.db")
org = db.create_organization("acme")
_, admin_token = db.create_service_account(org, "bootstrap", "admin")

app = create_app(db)
app.run(host="127.0.0.1", port=8643)  # bind responsibly behind TLS in production
```

## Concepts

| Object | Purpose |
|---|---|
| Organization | Tenant boundary; all queries are org-scoped |
| Service accounts | Bearer tokens (`ddsa_…`) with roles: `admin`, `maintainer`, `viewer`, `agent` |
| Enrollment tokens | Single-use `dden_…` tokens that mint machine identities |
| Machines | Enrolled endpoints identified by `machine_key` |
| Snapshots | Sanitized-only payloads; anything not marked sanitized is rejected with HTTP 422 |
| Baselines | Approved per-project environment expectations |
| Policies | Versioned JSON documents (policy-as-code) |
| Exceptions | Time-boxed rule exceptions with justification + reviewer |
| Audit events | Immutable append-only trail of sensitive actions |
| Webhooks | HMAC-SHA256-signed deliveries (`X-DevRepro-Signature`) |
| Retention | Per-org snapshot/audit age limits |

## RBAC matrix

| Endpoint | viewer | maintainer | admin |
|---|---|---|---|
| GET machines/snapshots/baselines/policies | ✅ | ✅ | ✅ |
| POST baselines / request exceptions | ❌ | ✅ | ✅ |
| PUT policies / review exceptions / webhooks / retention | ❌ | ❌ | ✅ |
| GET audit log | ❌ | ❌ | ✅ |

Agents authenticate with their machine identity for snapshot publication only.

## API surface (v1)

```
GET    /healthz
POST   /api/v1/enroll                     # enrollment token -> machine id
POST   /api/v1/snapshots                  # agent publishes sanitized snapshot
GET    /api/v1/machines                   # viewer+
GET    /api/v1/snapshots                  # viewer+
POST   /api/v1/baselines                  # maintainer+
GET    /api/v1/baselines/{project_id}     # viewer+
PUT    /api/v1/policies/{name}            # admin
GET    /api/v1/policies/{name}            # viewer+
POST   /api/v1/exceptions                 # maintainer+
POST   /api/v1/exceptions/{id}/review     # admin
GET    /api/v1/audit                      # admin
PUT    /api/v1/retention                  # admin
POST   /api/v1/retention/apply            # admin
POST   /api/v1/webhooks                   # admin (secret shown once)
```

## Security properties

- Only snapshots whose privacy state is `sanitized` are accepted.
- Tokens are stored as SHA-256 hashes; plaintext is shown exactly once.
- Request bodies capped at 8 MiB.
- Webhook URLs must be HTTPS (localhost allowed for development).
- Multi-tenant isolation is enforced in every query and covered by tests.

## Fleet analytics

`devrepro.server.fleet` provides pure functions over stored snapshots:
readiness distribution, OS/architecture segmentation, tool-version heatmaps and
per-machine baseline compliance. These power the frontend Fleet Dashboard page.

## Scaling path

SQLite ships by default. For multi-user scale, swap the storage layer for
PostgreSQL behind the same call sites (tracked in PRODUCT_GAPS.md).