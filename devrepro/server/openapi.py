"""Deterministic OpenAPI 3.1 description of the fleet API.

The spec is generated from a static route table (single source of truth)
and cross-checked against the live Flask url_map in tests, so documentation
drift fails CI instead of silently misleading integrators.
"""

from __future__ import annotations

from typing import Any

__all__ = ["API_ROUTES", "build_openapi_spec"]

OpenApiDict = dict[str, Any]

_API_PREFIX = "/api/v1"

# method, path, operationId, summary, auth, request/ref, response
RouteSpec = tuple[str, str, str, str, bool]

API_ROUTES: tuple[RouteSpec, ...] = (
    ("GET", "/healthz", "healthLiveness", "Liveness probe", False),
    ("GET", f"{_API_PREFIX}/health", "healthReadiness", "Readiness details", False),
    ("POST", "/api/v1/enroll", "enrollMachine", "Enroll a machine with a one-time token", False),
    (
        "POST",
        f"{_API_PREFIX}/snapshots",
        "publishSnapshot",
        "Publish a sanitized snapshot (sanitized-only fields accepted)",
        True,
    ),
    ("GET", f"{_API_PREFIX}/machines", "listMachines", "List enrolled machines", True),
    ("GET", f"{_API_PREFIX}/snapshots", "listSnapshots", "List published snapshots", True),
    ("POST", f"{_API_PREFIX}/baselines", "approveBaseline", "Approve a project baseline", True),
    (
        "GET",
        f"{_API_PREFIX}/baselines/{{project_id}}",
        "getBaseline",
        "Fetch the latest approved baseline for a project",
        True,
    ),
    (
        "PUT",
        f"{_API_PREFIX}/policies/{{name}}",
        "setPolicy",
        "Store a policy-as-code document",
        True,
    ),
    (
        "GET",
        f"{_API_PREFIX}/policies/{{name}}",
        "getPolicy",
        "Fetch the active policy document",
        True,
    ),
    ("POST", f"{_API_PREFIX}/exceptions", "requestException", "Request a policy exception", True),
    (
        "POST",
        f"{_API_PREFIX}/exceptions/{{eid}}/review",
        "reviewException",
        "Approve or reject an exception",
        True,
    ),
    ("GET", f"{_API_PREFIX}/audit", "queryAuditLog", "Query the immutable audit log", True),
    ("PUT", f"{_API_PREFIX}/retention", "setRetention", "Configure retention windows", True),
    ("POST", f"{_API_PREFIX}/retention/apply", "applyRetention", "Apply retention now", True),
    (
        "POST",
        f"{_API_PREFIX}/webhooks",
        "createWebhook",
        "Register a signed webhook endpoint",
        True,
    ),
    (
        "GET",
        f"{_API_PREFIX}/openapi.json",
        "getOpenApiSpec",
        "This OpenAPI document",
        False,
    ),
    ("GET", "/metrics", "prometheusMetrics", "Prometheus-compatible counters", False),
)


def _error_response() -> OpenApiDict:
    return {
        "description": "Error envelope",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"error": {"type": "string"}},
                    "required": ["error"],
                }
            }
        },
    }


def build_openapi_spec(
    *, title: str = "DevRepro Doctor Fleet API", version: str = "1.0.0"
) -> OpenApiDict:
    """Build the OpenAPI document deterministically (no reflection)."""
    paths: OpenApiDict = {}
    security_schemes: OpenApiDict = {}
    for method, path, op_id, summary, needs_auth in API_ROUTES:
        item = paths.setdefault(path, {})
        op: OpenApiDict = {
            "operationId": op_id,
            "summary": summary,
            "responses": {
                "200": {"description": "Success"},
                "400": _error_response(),
                "401": _error_response(),
                "413": _error_response(),
            },
        }
        if needs_auth:
            op["security"] = [{"bearerAuth": []}]
            security_schemes["bearerAuth"] = {
                "type": "http",
                "scheme": "bearer",
                "description": "Service-account token or OIDC-derived identity",
            }
        item[method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version,
            "description": (
                "Versioned fleet API for self-hosted DevRepro Doctor servers. "
                "All snapshot payloads are sanitized; secret-classified fields "
                "are rejected at ingestion."
            ),
        },
        "servers": [{"url": "/", "description": "this server"}],
        "paths": paths,
        **({"components": {"securitySchemes": security_schemes}} if security_schemes else {}),
    }
