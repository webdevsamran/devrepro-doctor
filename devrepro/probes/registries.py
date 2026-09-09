"""Registry and certificate-trust probe.

Where packages come from, and which runtimes trust the certificate in front of
them. Both are configuration read from disk and environment; nothing here
connects to anything.
"""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["RegistryProbe"]


class RegistryProbe(Probe):
    id = "network/registries"
    version = "1"

    def run(self) -> ProbeResult:
        from devrepro.network.registries import (
            detect_registries,
            detect_trust_stores,
            ecosystems_without_custom_trust,
        )

        root = self.ctx.project_dir or Path.cwd()
        env = dict(self.ctx.env)
        findings = []

        registries = detect_registries(root)
        overridden = [r for r in registries if not r.is_default]
        if overridden:
            findings.append(
                self.finding(
                    "network/registry-override",
                    FindingState.INFO,
                    f"{len(overridden)} package source(s) point somewhere other than "
                    "the public registry.",
                    evidence=(
                        Evidence(
                            source="file",
                            excerpt="; ".join(
                                f"{r.ecosystem} ({r.scope}) -> {r.url}" for r in overridden[:5]
                            ),
                        ),
                    ),
                    detected=", ".join(sorted({r.ecosystem for r in overridden})),
                    component="registry",
                    remediation_hint="Not a problem in itself -- mirrors are normal. It "
                    "matters when one machine has the override and another does not, "
                    "because the same install command then fetches different bytes. "
                    "A user-scoped override is invisible to the rest of the team.",
                )
            )

        stores = detect_trust_stores(env)
        missing = ecosystems_without_custom_trust(env)
        broken = [s for s in stores if not s.exists]

        if broken:
            findings.append(
                self.finding(
                    "network/ca-bundle-missing",
                    FindingState.ERROR,
                    f"{len(broken)} CA bundle variable(s) point at a file that does not exist.",
                    evidence=(
                        Evidence(
                            source="env",
                            excerpt="; ".join(f"{s.variable}={s.path}" for s in broken),
                        ),
                    ),
                    detected=", ".join(s.variable for s in broken),
                    component="tls",
                    remediation_hint="The runtime falls back to its default trust store "
                    "and the override silently does nothing. Fix the path or unset "
                    "the variable.",
                )
            )

        if stores and missing:
            findings.append(
                self.finding(
                    "network/trust-store-partial",
                    FindingState.WARN,
                    f"A custom CA is configured for some runtimes but not {len(missing)} other(s).",
                    evidence=(
                        Evidence(
                            source="env",
                            excerpt=(
                                "configured: "
                                + ", ".join(sorted({s.ecosystem for s in stores}))
                                + "; not configured: "
                                + ", ".join(missing)
                            ),
                        ),
                    ),
                    detected=", ".join(missing),
                    component="tls",
                    remediation_hint="Each ecosystem reads its own variable, so fixing "
                    "one fixes only one. Behind an intercepting proxy the unconfigured "
                    "ones fail with certificate errors that name the certificate "
                    "rather than the missing setting.",
                )
            )

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={
                "registries": [
                    {
                        "ecosystem": r.ecosystem,
                        "scope": r.scope,
                        "url": r.url,
                        "is_default": r.is_default,
                    }
                    for r in registries
                ],
                "trust_stores": [
                    {"ecosystem": s.ecosystem, "variable": s.variable, "exists": s.exists}
                    for s in stores
                ],
            },
        )
