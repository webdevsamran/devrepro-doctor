"""frameworks rule pack: what a framework needs that its manifest never says.

The other packs compare a declared range against an installed version. This one
asks a question one layer down: the manifest is internally consistent, every
declared range is satisfied, and the build still fails -- because `next@15`
requires Node 18.18 and nothing in `package.json` says so.

Three frameworks, deeply, rather than ten shallowly. Each earns its place by
imposing a requirement on the *machine* that appears in no manifest, and by
failing with a message that names something other than the cause: a syntax
error rather than a Node version, a class-version number rather than a JDK, a
compiler error rather than a missing client library.

Nothing is invoked. `next info`, `manage.py check` and `gradlew --version` all
start a runtime, and two of them execute the project's own configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.core.versioning import satisfies

if TYPE_CHECKING:
    from devrepro.project.frameworks import FrameworkRequirement
    from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def evaluate(
    ctx: RuleContext,
    requirements: tuple[FrameworkRequirement, ...] | None = None,
    native: tuple[tuple[str, str, str, str], ...] = (),
) -> list[Finding]:
    """Compare framework-imposed floors against what this machine resolves.

    `requirements` is a parameter because the detection reads the project and
    the comparison reads the machine, and keeping them apart is what lets each
    be tested without the other. The pipeline passes what it found.
    """
    # `ctx.extra` is `dict[str, object]` on purpose -- it is the escape hatch the
    # pipeline uses to hand a pack whatever it has -- so the shape is checked
    # here, where the value is finally used, rather than assumed.
    from_extra = ctx.extra.get("framework_requirements")
    declared: tuple[FrameworkRequirement, ...] = (
        tuple(requirements)
        if requirements is not None
        else (tuple(from_extra) if isinstance(from_extra, tuple | list) else ())
    )
    findings: list[Finding] = []

    for requirement in declared:
        active = ctx.active_tool(requirement.tool)
        evidence = (
            Evidence(
                source="file",
                path=requirement.source,
                excerpt=f"{requirement.framework} {requirement.version}",
            ),
        )

        if active is None or not active.version:
            findings.append(
                Finding(
                    rule_id=f"{requirement.framework}/runtime-missing",
                    state=FindingState.BLOCKED,
                    summary=(
                        f"{requirement.framework} {requirement.version} needs "
                        f"{requirement.tool} {requirement.required}, and {requirement.tool} "
                        "does not resolve on PATH."
                    ),
                    evidence=evidence,
                    required=requirement.required,
                    component=requirement.tool,
                    remediation_hint=requirement.detail,
                )
            )
            continue

        try:
            ok = satisfies(active.version, requirement.required)
        except (ValueError, TypeError):
            # An unparseable version is not evidence of a mismatch. Reported
            # elsewhere as an unreadable version; inventing a failure here would
            # tell somebody to reinstall a working runtime.
            continue

        if ok:
            findings.append(
                Finding(
                    rule_id=f"{requirement.framework}/runtime-ok",
                    state=FindingState.PASS,
                    summary=(
                        f"{requirement.tool} {active.version} satisfies what "
                        f"{requirement.framework} {requirement.version} requires "
                        f"({requirement.required})."
                    ),
                    evidence=evidence,
                    detected=active.version,
                    required=requirement.required,
                    component=requirement.tool,
                )
            )
            continue

        findings.append(
            Finding(
                rule_id=f"{requirement.framework}/runtime-too-old",
                state=FindingState.BLOCKED,
                summary=(
                    f"{requirement.framework} {requirement.version} requires "
                    f"{requirement.tool} {requirement.required}; this machine has "
                    f"{active.version}."
                ),
                evidence=evidence,
                detected=active.version,
                required=requirement.required,
                component=requirement.tool,
                remediation_hint=requirement.detail,
            )
        )

    native_from_extra = ctx.extra.get("native_dependencies")
    native_declared: tuple[tuple[str, str, str, str], ...] = (
        native
        if native
        else (tuple(native_from_extra) if isinstance(native_from_extra, tuple | list) else ())
    )
    for name, source, needs, why in native_declared:
        findings.append(
            Finding(
                rule_id=f"{name}/needs-toolchain",
                state=FindingState.INFO,
                summary=(f"{name} needs {needs} to install from source on this machine."),
                evidence=(Evidence(source="file", path=source, excerpt=name),),
                component="native",
                remediation_hint=(
                    why + " Reported as information rather than a problem: a machine with "
                    "a working toolchain, or one where a prebuilt binary matches, "
                    "installs it without noticing."
                ),
            )
        )

    return findings
