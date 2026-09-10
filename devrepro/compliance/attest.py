"""Turning a snapshot into evidence somebody else can verify.

`devrepro snapshot` already produces a sanitized record of a machine, and
`sign-snapshot` already signs one with an HMAC. That is enough for *you* to
detect that *your own* file changed, and no use at all to anybody else: HMAC is
a shared secret, so verifying a signature requires holding the key that could
have produced it. An auditor who can forge the evidence has not verified it.

The gap is a format. An attestation is a signed statement of the form "this
predicate is true about this subject", and in-toto's Statement is the one the
rest of the supply-chain world already reads -- cosign, Sigstore, GitHub's
attestation API and the SLSA verifiers all consume it. Emitting that shape
makes signing somebody else's solved problem rather than this project's
bespoke one.

**Nothing here signs.** The module builds the payload and prints the command
that would sign it. Signing with Sigstore opens a browser for an OIDC flow and
writes an entry to a public transparency log -- a network side effect, and a
permanent, public one -- which is exactly the class of action this project
makes the user ask for by name. The generated command is the honest boundary:
everything up to the irreversible step, and then the user's own decision.

The subject is a digest, and the digest is of the snapshot file. Attesting to a
*machine* would be attesting to something with no stable identity; attesting to
a file that describes a machine at a moment is a claim that can be checked.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from devrepro.compliance.envbom import purl_for

if TYPE_CHECKING:
    from pathlib import Path

    from devrepro.core.models import ScanReport

__all__ = [
    "ENVIRONMENT_PREDICATE_TYPE",
    "REPRODUCTION_PREDICATE_TYPE",
    "SLSA_PREDICATE_TYPE",
    "STATEMENT_TYPE",
    "Subject",
    "build_environment_statement",
    "build_reproduction_statement",
    "build_slsa_provenance",
    "cosign_command",
    "render_statement",
    "subject_for_bytes",
    "subject_for_file",
    "verify_subject",
]

#: in-toto Statement v1. Version 0.1 used `https://in-toto.io/Statement/v0.1`
#: and spelled the field `predicate_type`; v1 renamed it to `predicateType` and
#: is what current cosign and the SLSA v1 verifiers expect.
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"

#: This project's own predicate. A custom predicate type is the correct move
#: for a claim nobody has standardised -- the alternative is to reuse a
#: standard one, which produces evidence that verifies and means the wrong
#: thing.
ENVIRONMENT_PREDICATE_TYPE = "https://devrepro.dev/attestation/environment/v1"

#: "This artefact was produced in an environment matching this snapshot."
REPRODUCTION_PREDICATE_TYPE = "https://devrepro.dev/attestation/reproduction/v1"

#: SLSA Provenance v1, for a container this tool wrote the recipe for.
SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"

#: The digest algorithm in-toto names for SHA-256 subjects.
_DIGEST_KEY = "sha256"


class Subject(dict[str, Any]):
    """An in-toto subject: a name, and the digest of what it names.

    A plain dict subclass because that is what it serialises to, and wrapping
    it in a dataclass would mean writing a converter whose only job is to
    produce this dict again.
    """

    @property
    def digest(self) -> str:
        digests: dict[str, str] = self["digest"]
        return digests[_DIGEST_KEY]

    @property
    def name(self) -> str:
        name: str = self["name"]
        return name


def subject_for_bytes(name: str, data: bytes) -> Subject:
    """A subject for content held in memory."""
    return Subject(name=name, digest={_DIGEST_KEY: hashlib.sha256(data).hexdigest()})


def subject_for_file(path: Path) -> Subject:
    """A subject for a file on disk, named by its basename.

    The basename rather than the path, for the same reason paths are absent
    from the environment BOM: a full path names a user's home directory, and an
    attestation is a document that leaves the machine by design.
    """
    return subject_for_bytes(path.name, path.read_bytes())


def verify_subject(subject: dict[str, Any], data: bytes) -> bool:
    """Whether `data` is what the subject claims to describe.

    The check a verifier needs and the one people skip. A signature proves the
    statement was not altered; it says nothing about whether the file sitting
    next to it is the file the statement is about.
    """
    digests = subject.get("digest") or {}
    expected = digests.get(_DIGEST_KEY)
    if not isinstance(expected, str) or not expected:
        return False
    return hashlib.sha256(data).hexdigest() == expected


def _tool_entries(report: ScanReport) -> list[dict[str, Any]]:
    """The active toolchain, in the shape the predicate records it.

    Only the tools that actually resolve: an attestation listing every
    installation on the machine describes the machine, and what a build cares
    about is the one that wins.
    """
    entries: list[dict[str, Any]] = []
    for tool in report.tools:
        if not tool.is_active:
            continue
        entry: dict[str, Any] = {"name": tool.name, "version": tool.version}
        purl = purl_for(tool.name, tool.version)
        if purl:
            entry["purl"] = purl
        if tool.install_source:
            entry["installSource"] = tool.install_source
        entries.append(entry)
    return sorted(entries, key=lambda item: (item["name"], item.get("version") or ""))


def _verdict_counts(report: ScanReport) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in report.findings:
        counts[finding.state.value] = counts.get(finding.state.value, 0) + 1
    return dict(sorted(counts.items()))


def build_environment_statement(
    report: ScanReport,
    subject: dict[str, Any],
    *,
    builder_id: str = "https://github.com/webdevsamran/devrepro-doctor",
) -> dict[str, Any]:
    """An in-toto statement describing the environment a snapshot recorded.

    The predicate deliberately carries the score and the finding counts as well
    as the toolchain. A list of versions is a fact; whether the machine holding
    them was in a state this project considers ready is the claim a reader
    actually wants, and it cannot be recomputed from the versions after the
    fact.
    """
    predicate: dict[str, Any] = {
        "builder": {"id": builder_id},
        "devreproVersion": report.devrepro_version,
        "scannedAt": report.created_at.isoformat(),
        "platform": {
            "os": report.platform.os_name,
            "version": report.platform.os_version,
            "arch": report.platform.arch,
            "wsl": report.platform.is_wsl,
        },
        "toolchain": _tool_entries(report),
        "findings": _verdict_counts(report),
        "policyApplied": report.policy_applied,
    }
    if report.score is not None:
        predicate["reproducibilityScore"] = {
            "earned": report.score.total,
            "possible": report.score.possible,
        }
    return {
        "_type": STATEMENT_TYPE,
        "subject": [dict(subject)],
        "predicateType": ENVIRONMENT_PREDICATE_TYPE,
        "predicate": predicate,
    }


def build_reproduction_statement(
    report: ScanReport,
    subject: dict[str, Any],
    *,
    environment_digest: str,
    reproduced: bool,
    steps: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Bind an artefact to the environment it came out of.

    Two digests, and the relationship between them is the whole point: the
    subject is the thing produced, and `environmentDigest` names the
    environment attestation it was produced in. A verifier holding both can
    check the pair without trusting either document's prose.
    """
    return {
        "_type": STATEMENT_TYPE,
        "subject": [dict(subject)],
        "predicateType": REPRODUCTION_PREDICATE_TYPE,
        "predicate": {
            "environmentDigest": {_DIGEST_KEY: environment_digest},
            "reproduced": reproduced,
            "reproducedAt": report.created_at.isoformat(),
            "platform": {
                "os": report.platform.os_name,
                "arch": report.platform.arch,
            },
            "steps": list(steps),
        },
    }


def build_slsa_provenance(
    subject: dict[str, Any],
    *,
    builder_id: str,
    build_type: str = "https://devrepro.dev/buildtype/reproduction/v1",
    started_at: str,
    finished_at: str | None = None,
    external_parameters: dict[str, Any] | None = None,
    resolved_dependencies: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """SLSA Provenance v1 for a container this tool wrote the recipe for.

    Deliberately conservative about what it claims. SLSA's build levels are
    about how far the *builder* is trusted, and a provenance document written
    by the same machine that ran the build is level 1 -- it says what happened,
    not that nothing could have tampered with it. Emitting one anyway is worth
    it: level 1 is the entry requirement for most consumers, and this document
    is the thing a hosted builder later replaces rather than invents.
    """
    run_details: dict[str, Any] = {
        "builder": {"id": builder_id},
        "metadata": {"startedOn": started_at},
    }
    if finished_at:
        run_details["metadata"]["finishedOn"] = finished_at
    return {
        "_type": STATEMENT_TYPE,
        "subject": [dict(subject)],
        "predicateType": SLSA_PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": build_type,
                "externalParameters": external_parameters or {},
                "resolvedDependencies": [dict(dep) for dep in resolved_dependencies],
            },
            "runDetails": run_details,
        },
    }


def cosign_command(statement_path: Path | str, subject_path: Path | str) -> tuple[str, ...]:
    """The command that signs an attestation, for the user to run.

    Printed rather than executed. `cosign attest-blob` performs an interactive
    OIDC flow and writes an entry to a public transparency log; both are
    network side effects and the second is permanent and public. This project's
    rule is that side effects are asked for by name, and there is no meaningful
    way to ask for "publish an immutable record of this machine's identity"
    from inside a diagnostic command.
    """
    return (
        "cosign",
        "attest-blob",
        "--predicate",
        str(statement_path),
        "--type",
        ENVIRONMENT_PREDICATE_TYPE,
        "--output-attestation",
        f"{statement_path}.att",
        str(subject_path),
    )


def render_statement(statement: dict[str, Any], *, indent: int = 2) -> str:
    """Serialise a statement.

    `sort_keys` stays off: in-toto's field order is conventional (`_type`,
    `subject`, `predicateType`, `predicate`) and sorting would put `_type`
    last, which reads as broken to anybody who has seen one before.
    """
    return json.dumps(statement, indent=indent) + "\n"
