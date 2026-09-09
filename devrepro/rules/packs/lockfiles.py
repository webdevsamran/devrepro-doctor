"""lockfiles rule pack: can this machine actually use the lock it was given?

Every other pack asks whether a runtime is present and new enough. This one
asks the question one layer down: a lockfile is written in a *format*, that
format has a floor, and a package manager below the floor does not report an
error -- npm 6 handed a `lockfileVersion: 3` file rewrites the whole tree, and
the diff shows up in someone else's pull request.

The facts come from `devrepro.project.lockfiles`, which reads files already on
disk and runs no package manager. A format whose floor is not publicly
documented carries no floor here, so it produces no finding at all: silence is
the correct output when the honest answer is "unknown".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.core.versioning import parse_spec, parse_version

if TYPE_CHECKING:
    from devrepro.project.lockfiles import LockfileFacts
    from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def _evidence(fact: LockfileFacts, excerpt: str) -> tuple[Evidence, ...]:
    return (Evidence(source="file", path=fact.path, excerpt=excerpt),)


def _format_findings(ctx: RuleContext, fact: LockfileFacts) -> list[Finding]:
    """Does the installed package manager understand this lockfile format?"""
    if not fact.minimum_tool:
        return []

    described = f"{fact.path} is format {fact.format_version}"
    evidence = _evidence(fact, fact.note or described)
    installed = ctx.active_tool(fact.tool)

    if installed is None:
        return [
            Finding(
                rule_id="lockfiles/manager-missing",
                state=FindingState.WARN,
                summary=(f"{fact.path} is a {fact.tool} lockfile, but {fact.tool} is not on PATH."),
                evidence=evidence,
                required=f"{fact.tool} {fact.minimum_tool}",
                component=fact.tool,
                remediation_hint=(
                    f"Install {fact.tool}, or remove the lockfile if the project has moved "
                    "to a different package manager."
                ),
                references=(f"lockfile {fact.path}",),
            )
        ]

    if not installed.version:
        # Present but unversioned is a third state, and collapsing it into
        # "missing" is how this pack first reported npm 11 as absent: on Windows
        # the extensionless `npm` shell script resolved ahead of `npm.cmd` and
        # answered no version. Saying so plainly beats guessing either way.
        return [
            Finding(
                rule_id="lockfiles/format-unknown",
                state=FindingState.UNKNOWN,
                summary=(
                    f"{fact.tool} is installed at {installed.exe_path}, but did not report a "
                    f"version, so support for {fact.path} could not be confirmed."
                ),
                evidence=evidence,
                required=fact.minimum_tool,
                component=fact.tool,
            )
        ]

    try:
        satisfied = parse_spec(fact.minimum_tool).satisfied_by(parse_version(installed.version))
    except ValueError:
        return [
            Finding(
                rule_id="lockfiles/format-unknown",
                state=FindingState.UNKNOWN,
                summary=(
                    f"Could not compare {fact.tool} {installed.version!r} against "
                    f"{fact.minimum_tool!r} for {fact.path}."
                ),
                evidence=evidence,
                detected=installed.version,
                required=fact.minimum_tool,
                component=fact.tool,
            )
        ]

    if satisfied:
        return [
            Finding(
                rule_id="lockfiles/format-supported",
                state=FindingState.PASS,
                summary=(
                    f"{fact.tool} {installed.version} can use {fact.path} "
                    f"(format {fact.format_version})."
                ),
                evidence=evidence,
                detected=installed.version,
                required=fact.minimum_tool,
                component=fact.tool,
            )
        ]

    return [
        Finding(
            rule_id="lockfiles/tool-too-old",
            state=FindingState.ERROR,
            summary=(
                f"{fact.tool} {installed.version} is below {fact.minimum_tool}, which "
                f"{fact.path} (format {fact.format_version}) requires."
            ),
            evidence=evidence,
            detected=installed.version,
            required=fact.minimum_tool,
            component=fact.tool,
            remediation_hint=(
                f"Upgrade {fact.tool} to {fact.minimum_tool}. Installing with the older "
                "version can rewrite the lockfile instead of failing, which lands the "
                "damage in a pull request rather than in this terminal."
            ),
            references=(f"lockfile {fact.path}", fact.note or ""),
        )
    ]


def _runtime_findings(ctx: RuleContext, fact: LockfileFacts) -> list[Finding]:
    """Does the machine's runtime fall inside the range the lockfile solved for?"""
    if fact.requires_runtime is None:
        return []
    runtime, spec = fact.requires_runtime

    installed = ctx.active_tool(runtime)
    if installed is None or not installed.version:
        # The runtime being absent is already the business of that ecosystem's
        # pack, which reports it with the right severity. Saying it twice here
        # would double-count one problem.
        return []

    try:
        satisfied = parse_spec(spec).satisfied_by(parse_version(installed.version))
    except ValueError:
        # Ranges like `^20` and `~=3.11` are ecosystem shorthand this project
        # does not parse. Reporting UNKNOWN is honest; guessing is not.
        return [
            Finding(
                rule_id="lockfiles/runtime-spec-unparseable",
                state=FindingState.UNKNOWN,
                summary=f"{fact.path} pins {runtime} {spec!r}, which could not be parsed.",
                evidence=_evidence(fact, f"{runtime} {spec}"),
                detected=installed.version,
                required=spec,
                component=runtime,
            )
        ]

    if satisfied:
        return []

    return [
        Finding(
            rule_id="lockfiles/runtime-mismatch",
            state=FindingState.ERROR,
            summary=(
                f"{fact.path} was locked for {runtime} {spec}, but {runtime} "
                f"{installed.version} is active."
            ),
            evidence=_evidence(fact, f"{runtime} {spec}"),
            detected=installed.version,
            required=spec,
            component=runtime,
            remediation_hint=(
                f"Switch to {runtime} {spec} for this project, or re-resolve the lockfile "
                f"on {runtime} {installed.version} and commit the result."
            ),
            references=(f"lockfile {fact.path}",),
        )
    ]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for fact in ctx.lockfiles:
        if fact.unreadable:
            findings.append(
                Finding(
                    rule_id="lockfiles/unreadable",
                    state=FindingState.UNKNOWN,
                    summary=f"{fact.path} {fact.note}.",
                    evidence=_evidence(fact, fact.note),
                    component=fact.tool,
                    remediation_hint=(
                        "A lockfile that cannot be parsed cannot be trusted to reproduce "
                        "anything; regenerate it with its package manager."
                    ),
                )
            )
            continue
        findings.extend(_format_findings(ctx, fact))
        findings.extend(_runtime_findings(ctx, fact))
    return findings
