# JSON Schemas

Canonical machine-readable contracts for DevRepro Doctor artifacts.

- `snapshot.schema.json` — privacy-sanitized environment manifests
  (`devrepro snapshot`), schema version `1.0`.
- `scan-report.schema.json` — full scan reports (`devrepro scan --format json`),
  schema version `1.0`.
- `environment-diff.schema.json` — diff exports (`devrepro diff A B --format json`).

These files are the serialization source of truth; the Pydantic models in
`devrepro/core/models.py` are generated/kept in sync with them and validated in CI
(`python scripts/validate_schemas.py`). Consumers (CI gates, dashboards, the web UI)
should validate against these schemas rather than parsing ad hoc.