"""advisories rule pack: does the toolchain itself have published advisories?

Every other pack asks whether a tool is present and matches what the project
declared. This one asks whether the tool that *is* installed is one somebody
published an advisory against -- a question the dependency scanners never ask,
because a compiler appears in no lockfile.

The data comes from `devrepro.compliance.advisories`, which is offline by
design and deliberately small. Two consequences shape what this pack emits:

**Everything is a WARN.** The version-matching rule in `is_affected` errs
toward reporting when a branch has no listed fix, and a check that is
deliberately wrong in the loud direction has no business blocking anybody's
build.

**Silence is reported, once.** A tool the bundle has no data for produced no
answer, which is not the same as a clean one -- and the whole failure mode of
offline advisory data is being read as coverage. So an INFO finding names what
the bundle covers and when it was reviewed, and it is emitted whether or not
anything matched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from devrepro.compliance.advisories import affected_tools, bundled_bundle
from devrepro.core.models import Evidence, Finding, FindingState

if TYPE_CHECKING:
    from devrepro.compliance.advisories import AdvisoryBundle
    from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext, bundle: AdvisoryBundle | None = None) -> list[Finding]:
    """Compare active tool versions against the advisory set.

    `bundle` is a parameter so a test can supply its own set rather than
    asserting against whatever the shipped seed happens to contain today -- the
    seed is data that changes, and a test pinned to it would fail on every
    review of it.
    """
    active = bundle or bundled_bundle()
    installed = {t.name: t.version for t in ctx.tools if t.is_active}
    hits = affected_tools(installed, active)

    findings: list[Finding] = [
        Finding(
            rule_id="advisories/coverage",
            state=FindingState.INFO,
            summary=(
                f"Toolchain advisory data: {active.source}, reviewed "
                f"{active.published}, covering "
                f"{', '.join(active.covers) if active.covers else 'nothing'}."
            ),
            evidence=(
                Evidence(
                    source="system",
                    excerpt=(
                        f"{len(active.advisories)} advisories loaded; "
                        f"{len(installed)} active tools checked"
                    ),
                ),
            ),
            remediation_hint=(
                "Tools outside that list got no answer rather than a clean one. "
                "Replace the set with `devrepro advisories --db <bundle.json>`."
            ),
            references=("https://webdevsamran.github.io/devrepro-doctor/COMPLIANCE/",),
        )
    ]

    for name, version, advisory in hits:
        findings.append(
            Finding(
                rule_id=f"{name}/known-advisory",
                state=FindingState.WARN,
                summary=f"{name} {version} is covered by {advisory.id}: {advisory.summary}",
                evidence=(
                    Evidence(
                        source="system",
                        excerpt=f"{name} {version}; fixed in {', '.join(advisory.fixed)}",
                    ),
                ),
                detected=version,
                required=" or ".join(advisory.fixed),
                component=name,
                remediation_hint=(
                    f"Upgrade {name} to {advisory.fixed[0]} or later on its branch. "
                    "This compares versions offline and does not check whether your "
                    "distribution backported the fix, which many do."
                ),
                references=(advisory.reference,),
            )
        )
    return findings
