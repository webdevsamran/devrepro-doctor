"""Mapping what this tool can prove onto the control names auditors use.

The Cyber Resilience Act's reporting obligations started on 11 September 2026
and its SBOM obligations arrive in December 2027, so "can you evidence your
build environment" stopped being a hypothetical question. The trouble with
answering it is vocabulary: a security questionnaire asks about *Annex I Part I
(2)(a)*, and this tool emits `python/version-mismatch`. Both describe the same
world and neither name appears in the other's document.

So this module is a translation table, and it is deliberately a small one.

**Most controls are out of scope, and saying so is the point.** A compliance
feature that reports green across a whole framework is worse than absent: it
gives somebody a document to attach to a ticket, and the document is wrong.
devrepro sees one machine's build environment. It cannot speak to secure
design, to whether vulnerabilities were disclosed on time, or to anything about
the shipped product. Every control here is either evidenced by something in a
scan report or marked `out-of-scope` with a reason, and the export carries
both.

The distinction the statuses draw is between *evidence* and *conformance*.
`evidenced` means this report contains the facts an assessor asked for. It does
not mean the control is satisfied -- that judgement needs a person who knows
what the product is, and no scan can make it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from devrepro.core.models import ScanReport

__all__ = [
    "CONTROLS",
    "Control",
    "ControlEvidence",
    "EvidenceStatus",
    "build_evidence_pack",
    "controls_for_framework",
    "frameworks",
]

EvidenceStatus = Literal["evidenced", "partial", "not-evidenced", "out-of-scope"]


@dataclass(frozen=True)
class Control:
    """One named requirement, and what a scan can say about it."""

    id: str
    framework: str
    title: str
    #: What this tool contributes. Phrased as a fact it can produce, not as a
    #: claim about the control being met.
    evidence: str
    #: The report attribute the evidence is drawn from, or `None` when the
    #: control is out of scope for a machine scan.
    source: str | None = None
    #: Present only for out-of-scope controls: why a machine scan cannot speak
    #: to it. An unexplained gap reads as an oversight.
    out_of_scope_because: str | None = None


#: The mapping. Each framework is represented by the controls a build
#: environment can actually evidence, plus the neighbouring ones people expect
#: to see and which this tool must decline.
CONTROLS: tuple[Control, ...] = (
    # ---------------------------------------------------------------- CRA
    Control(
        id="CRA/AnnexI.II.1",
        framework="cra",
        title="Identify and document components, including an SBOM",
        evidence=(
            "A CycloneDX bill of materials for the build environment: every "
            "interpreter, compiler, package manager and container engine that "
            "resolved on this machine, with versions and install provenance."
        ),
        source="tools",
    ),
    Control(
        id="CRA/AnnexI.I.2.a",
        framework="cra",
        title="Products are made available without known exploitable vulnerabilities",
        evidence=(
            "Installed toolchain versions checked against the bundled advisory "
            "set, so a compiler or runtime with a known advisory is named "
            "rather than assumed current."
        ),
        source="findings",
    ),
    Control(
        id="CRA/AnnexI.I.2.d",
        framework="cra",
        title="Protect against unauthorised access by appropriate control mechanisms",
        evidence=(
            "What a process running here could reach: writable roots, "
            "credential-shaped environment variable names, and whether this "
            "shell is production-adjacent. Names only; no values are read."
        ),
        source="findings",
    ),
    Control(
        id="CRA/AnnexI.I.2.f",
        framework="cra",
        title="Protect the integrity of stored, transmitted or processed data",
        evidence=(
            "TLS trust configuration per language runtime, any interception "
            "proxy in the chain, and registry overrides that would redirect a "
            "dependency fetch."
        ),
        source="findings",
    ),
    Control(
        id="CRA/AnnexI.II.3",
        framework="cra",
        title="Apply and distribute security updates without delay",
        evidence="",
        out_of_scope_because=(
            "A release process, not a machine state. Nothing in a scan of one "
            "developer's environment shows whether patches reached users."
        ),
    ),
    Control(
        id="CRA/Art.14",
        framework="cra",
        title="Report actively exploited vulnerabilities and severe incidents",
        evidence="",
        out_of_scope_because=(
            "An obligation on the manufacturer toward CSIRTs and ENISA. This "
            "tool has no channel to either, and by design sends nothing "
            "anywhere."
        ),
    ),
    # -------------------------------------------------- NIST SSDF (EO 14028)
    Control(
        id="SSDF/PO.3.1",
        framework="ssdf",
        title="Specify which tools are to be included in each toolchain",
        evidence=(
            "The declared environment contract -- policy, lockfiles, "
            "manifests, version-manager pins and CI workflow toolchains -- "
            "extracted from the repository rather than described by hand."
        ),
        source="requirements",
    ),
    Control(
        id="SSDF/PO.3.2",
        framework="ssdf",
        title="Follow recommended security practices to deploy and maintain tools",
        evidence=(
            "Per-tool installation provenance and PATH resolution, including "
            "shadowed installations where the tool that runs is not the tool "
            "the project declared."
        ),
        source="path_analysis",
    ),
    Control(
        id="SSDF/PO.5.1",
        framework="ssdf",
        title="Separate and protect each environment involved in development",
        evidence=(
            "Container and WSL topology, engine endpoint kind, rootless mode, "
            "and whether this shell carries production-adjacent context."
        ),
        source="containers",
    ),
    Control(
        id="SSDF/PS.1.1",
        framework="ssdf",
        title="Store all forms of code based on the principle of least privilege",
        evidence="",
        out_of_scope_because=(
            "A property of the source repository host's access control, which "
            "this tool never contacts."
        ),
    ),
    Control(
        id="SSDF/PS.2.1",
        framework="ssdf",
        title="Make verification information available to software acquirers",
        evidence=(
            "An in-toto attestation of the build environment, digest-bound to "
            "the snapshot it describes and ready for a Sigstore signature."
        ),
        source="attestation",
    ),
    Control(
        id="SSDF/PS.3.1",
        framework="ssdf",
        title="Securely archive the necessary files to be retained",
        evidence=(
            "Hash-chained snapshot history: each record commits to the one "
            "before it, so a deleted or edited entry is detectable."
        ),
        source="history",
    ),
    Control(
        id="SSDF/PW.4.1",
        framework="ssdf",
        title="Acquire well-secured software components from commercial sources",
        evidence=(
            "Lockfile presence and coverage across every workspace, plus "
            "registry and mirror configuration that determines where "
            "components are actually fetched from."
        ),
        source="requirements",
    ),
    Control(
        id="SSDF/RV.1.1",
        framework="ssdf",
        title="Gather information from acquirers and public sources on vulnerabilities",
        evidence="",
        out_of_scope_because=(
            "Requires an intake channel and monitoring of external feeds. This "
            "tool works offline and receives nothing."
        ),
    ),
    # ------------------------------------------------------------- SLSA v1.0
    Control(
        id="SLSA/Provenance",
        framework="slsa",
        title="Build platform generates provenance describing how the artifact was produced",
        evidence=(
            "SLSA Provenance v1 for a reproduction container, naming the "
            "recipe, the base image digest and the environment it was drawn "
            "from. Level 1: it records what happened, and is not itself "
            "tamper-resistant."
        ),
        source="attestation",
    ),
    Control(
        id="SLSA/Build.L2",
        framework="slsa",
        title="Provenance is signed by a hosted build platform",
        evidence="",
        out_of_scope_because=(
            "Level 2 requires a build service the developer does not control. "
            "Provenance written on the machine that ran the build cannot "
            "satisfy it, and claiming otherwise would be the whole point of "
            "the level, defeated."
        ),
    ),
)


def frameworks() -> tuple[str, ...]:
    """Framework identifiers, in the order they first appear."""
    seen: list[str] = []
    for control in CONTROLS:
        if control.framework not in seen:
            seen.append(control.framework)
    return tuple(seen)


def controls_for_framework(framework: str) -> tuple[Control, ...]:
    return tuple(c for c in CONTROLS if c.framework == framework)


@dataclass(frozen=True)
class ControlEvidence:
    """A control, and what this particular report has to say about it."""

    control: Control
    status: EvidenceStatus
    detail: str

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.control.id,
            "framework": self.control.framework,
            "title": self.control.title,
            "status": self.status,
            "detail": self.detail,
        }
        if self.control.evidence:
            payload["evidence"] = self.control.evidence
        if self.control.out_of_scope_because:
            payload["outOfScopeBecause"] = self.control.out_of_scope_because
        return payload


def _availability(report: ScanReport, source: str | None) -> tuple[EvidenceStatus, str]:
    """Whether this report actually carries the evidence a control names.

    A control whose source came back empty is `not-evidenced`, not `evidenced`
    with nothing behind it. The distinction is the reason to run this at all:
    an evidence pack that reports the same thing regardless of what the scan
    found is a template, not evidence.
    """
    if source is None:
        return "out-of-scope", "A machine scan cannot speak to this control."

    if source == "attestation":
        return (
            "evidenced",
            "`devrepro attest` produces the statement; it is not part of the report.",
        )
    if source == "history":
        return (
            "evidenced",
            "`devrepro history --verify` checks the chain over stored snapshots.",
        )

    value = getattr(report, source, None)
    if source == "findings":
        count = len(report.findings)
        if count == 0:
            return "not-evidenced", "The scan produced no findings for this area."
        return "evidenced", f"{count} finding(s) in this report."
    if not value:
        return "not-evidenced", f"This report carries no `{source}` data."
    if isinstance(value, tuple):
        return "evidenced", f"{len(value)} record(s) in this report."
    return "evidenced", "Present in this report."


def build_evidence_pack(
    report: ScanReport,
    *,
    framework: str | None = None,
) -> dict[str, Any]:
    """An evidence pack: controls, status, and an explicit scope statement.

    The scope statement is not decoration. This document exists to be handed to
    somebody who did not run the scan, and the single most likely way it does
    harm is by being read as a conformance report. So it says what it is, in
    the file, above the table.
    """
    selected = CONTROLS if framework is None else controls_for_framework(framework)
    entries: list[ControlEvidence] = []
    for control in selected:
        status, detail = _availability(report, control.source)
        entries.append(ControlEvidence(control, status, detail))

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1

    return {
        "schema_version": "1.0",
        "generated_by": f"devrepro {report.devrepro_version}",
        "generated_at": report.created_at.isoformat(),
        "scope": (
            "Evidence about one machine's build environment. This is not a "
            "conformance assessment: `evidenced` means the facts an assessor "
            "asked for are present in this report, not that the control is "
            "satisfied. Controls marked out-of-scope cannot be judged from a "
            "machine scan, and the reason is given for each."
        ),
        "frameworks": sorted({c.framework for c in selected}),
        "summary": dict(sorted(counts.items())),
        "controls": [entry.as_dict() for entry in entries],
    }
