"""SARIF 2.1.0 renderer for GitHub code scanning integration.

Maps DevRepro findings onto the SARIF result model so environment blockers,
errors and warnings appear directly in GitHub's Security tab and on pull
requests via upload/upload-artifact + github/codeql-action's ``upload-sarif``
(or any SARIF consumer).

Mapping:
  BLOCKED, ERROR -> error    WARN, UNKNOWN -> warning    INFO, PASS -> note

Every serialization passes through the privacy gate before returning.
"""

from __future__ import annotations

import hashlib
import json

from devrepro import __version__
from devrepro.core.models import FindingState, ScanReport
from devrepro.privacy.gate import assert_no_secrets

__all__ = ["render_sarif"]

_TOOL_URI = "https://github.com/webdevsamran/devrepro-doctor"

_LEVEL_FOR_STATE: dict[FindingState, str] = {
    FindingState.BLOCKED: "error",
    FindingState.ERROR: "error",
    FindingState.WARN: "warning",
    FindingState.UNKNOWN: "warning",
    FindingState.INFO: "note",
    FindingState.PASS: "note",
}


def render_sarif(report: ScanReport) -> str:
    """Serialize a scan report as a SARIF 2.1.0 JSON log."""
    # One rule entry per distinct rule_id keeps results compact and gives
    # consumers stable metadata to group by.
    rule_ids = sorted({f.rule_id for f in report.findings})
    rules = [
        {
            "id": rid,
            "shortDescription": {"text": f"Developer-environment check: {rid}"},
            "helpUri": _TOOL_URI,
        }
        for rid in rule_ids
    ]
    rule_index = {rid: i for i, rid in enumerate(rule_ids)}

    results = []
    for f in sorted(
        report.findings,
        key=lambda x: (rule_index[x.rule_id], x.summary),
    ):
        props: dict[str, object] = {
            "state": f.state.value,
            "devrepro-rule-id": f.rule_id,
        }
        if f.detected is not None:
            props["detected"] = f.detected
        if f.required is not None:
            props["required"] = f.required
        if f.component is not None:
            props["component"] = f.component
        if f.remediation_hint is not None:
            props["remediation-hint"] = f.remediation_hint
        evidence_excerpt = f.evidence[0].excerpt if f.evidence else None
        if evidence_excerpt:
            props["evidence-excerpt"] = evidence_excerpt
        fingerprint = hashlib.sha256(
            f"{report.platform.os_name}|{f.rule_id}|{f.summary}".encode()
        ).hexdigest()
        result: dict[str, object] = {
            "ruleId": f.rule_id,
            "ruleIndex": rule_index[f.rule_id],
            "level": _LEVEL_FOR_STATE[f.state],
            "message": {"text": f.summary},
            "partialFingerprints": {"devreproFinding/v1": fingerprint},
            "properties": props,
        }
        results.append(result)

    payload = json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "DevRepro Doctor",
                            "version": __version__,
                            "informationUri": _TOOL_URI,
                            "rules": rules,
                        }
                    },
                    "results": results,
                    "automationDetails": {
                        "description": {
                            "text": (
                                "Project-aware developer-environment diagnostics "
                                "(read-only scan; privacy-redacted)."
                            )
                        }
                    },
                }
            ],
        },
        indent=2,
        default=str,
    )
    assert_no_secrets(payload)
    return payload
