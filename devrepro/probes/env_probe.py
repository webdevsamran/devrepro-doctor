"""Environment variable audit probe.

Checks required env-var NAMES from policy/examples. Never prints values.
Flags suspicious-looking variables only by NAME pattern (e.g. names that
suggest credentials left empty), never by content.
"""

from __future__ import annotations

import re

from devrepro.core.models import Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["EnvAuditProbe"]

_SECRET_NAME_HINTS = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)


class EnvAuditProbe(Probe):
    id = "env/names"
    version = "1"

    def run(self) -> ProbeResult:
        required_names: list[str] = list(self.ctx.extra.get("required_env_names", []))
        findings = []
        missing = [n for n in required_names if n not in self.ctx.env]
        if required_names:
            ev = Evidence(source="env", excerpt=f"checked {len(required_names)} required NAMES")
            state = FindingState.BLOCKED if missing else FindingState.PASS
            findings.append(
                self.finding(
                    "env/required-names-present",
                    state,
                    f"{len(required_names) - len(missing)}/{len(required_names)} required environment "
                    "variable names are set (values never inspected).",
                    evidence=(ev,),
                    detected=", ".join(missing) if missing else None,
                    required=", ".join(required_names),
                    component="environment",
                    remediation_hint="Set the missing variables in your shell profile or .env loader. "
                    "DevRepro never reads or prints their values.",
                )
            )

        # INFO: count of credential-ish names present (names only!)
        cred_names = [k for k in self.ctx.env if _SECRET_NAME_HINTS.search(k)]
        if cred_names:
            findings.append(
                self.finding(
                    "env/credential-names-present",
                    FindingState.INFO,
                    f"{len(cred_names)} credential-like variable names exist in this session "
                    "(names only; values are never read or reported).",
                    evidence=(Evidence(source="env", excerpt="name-pattern scan only"),),
                    component="environment",
                )
            )

        return ProbeResult(self.id, findings=tuple(findings), data={"cred_name_count": len(cred_names)})