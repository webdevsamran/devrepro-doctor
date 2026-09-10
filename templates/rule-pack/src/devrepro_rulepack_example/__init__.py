"""An example rule pack: is the company's mandated build tool present?

Written to be read rather than to be impressive. It shows the four things every
pack needs -- a prefix of its own, evidence on every finding, a remediation hint
that names a next step, and no side effects -- on a check that is genuinely
useful in the situation it describes.

The prefix is `acme/`. Pick your own and do not reuse a built-in one: a pack
emitting `python/missing` makes `devrepro explain` describe somebody else's
rule, and the user has no way to tell which pack produced the finding.

**What a pack receives.** `RuleContext` carries `platform_info`, `tools`,
`requirements`, `policy`, `path_analysis`, `containers`, `wsl`, `gpu`,
`active_manager`, `lockfiles` and an `extra` dict -- and deliberately **no
environment**. Probes read the environment and hand the engine conclusions; a
pack able to read raw variables would be a pack able to put values in a report,
which the privacy gate exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.core.versioning import satisfies

if TYPE_CHECKING:
    from devrepro.rules.base import RuleContext

__all__ = ["REQUIRED_TOOL", "REQUIRED_VERSION", "evaluate"]

#: What this company builds with, and the floor it supports. Constants rather
#: than literals in the body, so somebody adopting this pack changes two lines.
REQUIRED_TOOL = "git"
REQUIRED_VERSION = ">=2.45"


def evaluate(ctx: RuleContext) -> list[Finding]:
    """Return findings for this machine. Runs nothing, writes nothing.

    If you need to run a command, use `ctx.runner` where a probe gives you one
    -- a raw `subprocess` call bypasses the recording and the redaction, and
    `devrepro rules-test` refuses it statically.
    """
    findings: list[Finding] = []
    active = ctx.active_tool(REQUIRED_TOOL)

    if active is None or not active.version:
        findings.append(
            Finding(
                rule_id="acme/build-tool-missing",
                state=FindingState.BLOCKED,
                summary=(
                    f"{REQUIRED_TOOL} does not resolve on PATH, and every internal "
                    "build script starts with it."
                ),
                # Every finding needs at least one piece of evidence. One without
                # it is an assertion, and the model refuses to build it.
                evidence=(
                    Evidence(source="system", excerpt=f"{REQUIRED_TOOL} not found on PATH"),
                ),
                required=REQUIRED_VERSION,
                component=REQUIRED_TOOL,
                # A hint that names the next step. "Install the required tools"
                # is not one.
                remediation_hint=(
                    f"Install {REQUIRED_TOOL} {REQUIRED_VERSION}, or run the onboarding "
                    "script. `devrepro which " + REQUIRED_TOOL + "` first -- it is often "
                    "installed but shadowed, which looks identical from here."
                ),
            )
        )
        return findings

    if not satisfies(active.version, REQUIRED_VERSION):
        findings.append(
            Finding(
                rule_id="acme/build-tool-too-old",
                state=FindingState.WARN,
                summary=(
                    f"{REQUIRED_TOOL} {active.version} is below the {REQUIRED_VERSION} "
                    "this organisation supports."
                ),
                evidence=(
                    Evidence(source="system", excerpt=f"{REQUIRED_TOOL} {active.version}"),
                ),
                detected=active.version,
                required=REQUIRED_VERSION,
                component=REQUIRED_TOOL,
                remediation_hint=(
                    f"Upgrade {REQUIRED_TOOL}. Older versions work for most things, "
                    "which is why this is a warning rather than a block -- and why it "
                    "goes unnoticed until the one command that needs the newer one."
                ),
            )
        )
        return findings

    # A passing check reported explicitly, so a clean result is visible rather
    # than inferred from silence.
    findings.append(
        Finding(
            rule_id="acme/build-tool-ok",
            state=FindingState.PASS,
            summary=f"{REQUIRED_TOOL} {active.version} satisfies {REQUIRED_VERSION}.",
            evidence=(Evidence(source="system", excerpt=f"{REQUIRED_TOOL} {active.version}"),),
            detected=active.version,
            required=REQUIRED_VERSION,
            component=REQUIRED_TOOL,
        )
    )
    return findings
