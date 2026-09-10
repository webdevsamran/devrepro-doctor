"""Whether the compiler and the interpreter themselves have known advisories.

Every scanner in circulation checks the dependency tree. Almost none check the
things that *built* it. A project can have a perfectly clean `npm audit` and be
compiled by a `git` old enough that cloning a repository executes code from it,
because the toolchain is not in any lockfile and so is in nobody's scan.

Three constraints shaped this, and each one cost a feature somebody would
expect:

**It is offline.** No feed, no API key, no request at scan time. That is the
project's rule, and it is also the only way this works in the environments that
need it most -- an air-gapped build host is precisely where nobody has looked
at the toolchain in two years.

**It is a seed, not a feed.** The bundled set is small and every entry carries
a reference URL, because an advisory database that cannot be checked is a
rumour. Shipping a large bundled set would mean shipping a stale one; the
mechanism for replacing it is the feature, and `load_bundle` reads an external
file so an organisation can distribute its own on a USB stick.

**A replacement must be signed.** A file that decides which of your tools are
called dangerous is worth tampering with -- adding no entries is a silent
downgrade, and removing one is invisible. External bundles are verified against
`DEVREPRO_ADVISORY_KEY` and refused otherwise, unless the caller says
`trust_unsigned=True` in as many words.

The matching rule and its failure mode are both stated in `is_affected`. It
errs toward reporting, which is the right direction for a warning and the wrong
one for a gate -- so nothing here blocks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from devrepro.core.versioning import Version, parse_version
from devrepro.snapshots.signing import SigningError, verify_bytes

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BUNDLED_ADVISORIES",
    "BUNDLE_SCHEMA_VERSION",
    "Advisory",
    "AdvisoryBundle",
    "AdvisoryError",
    "affected_tools",
    "bundled_bundle",
    "is_affected",
    "load_bundle",
    "parse_bundle",
]

BUNDLE_SCHEMA_VERSION = "1.0"


class AdvisoryError(Exception):
    """Raised when an advisory bundle is unreadable, unsigned or malformed."""


@dataclass(frozen=True)
class Advisory:
    """One published advisory against a build tool.

    `fixed` holds one version per maintained branch, because that is how these
    are actually released: a fix lands on 2.45, 2.44 and 2.43 on the same day
    and a single "fixed in" number describes none of them correctly.
    """

    id: str
    tool: str
    summary: str
    fixed: tuple[str, ...]
    reference: str
    severity: str = "unknown"
    introduced: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "tool": self.tool,
            "summary": self.summary,
            "fixed": list(self.fixed),
            "reference": self.reference,
            "severity": self.severity,
        }
        if self.introduced:
            payload["introduced"] = self.introduced
        return payload


@dataclass(frozen=True)
class AdvisoryBundle:
    """A dated set of advisories, and where it came from.

    `published` is not decoration: an offline database's most important
    property is its age, and a result computed from an eighteen-month-old
    bundle should say so next to the result rather than in a footnote.
    """

    published: str
    source: str
    advisories: tuple[Advisory, ...] = ()
    signed: bool = False
    schema_version: str = BUNDLE_SCHEMA_VERSION
    #: Tools the bundle claims coverage for. A tool absent from this list got
    #: no answer, which is different from getting a clean one -- and the
    #: difference is the thing people misread.
    covers: tuple[str, ...] = field(default_factory=tuple)

    def for_tool(self, tool: str) -> tuple[Advisory, ...]:
        return tuple(a for a in self.advisories if a.tool == tool)


#: The bundled seed. Deliberately short. Every entry names a public advisory
#: with a URL a reader can open, and nothing is here that could not be checked
#: in under a minute.
BUNDLED_ADVISORIES: tuple[Advisory, ...] = (
    Advisory(
        id="CVE-2022-24765",
        tool="git",
        summary=(
            "A repository owned by another user could supply configuration "
            "from a parent directory, running its commands as you. The fix "
            "introduced safe.directory."
        ),
        fixed=("2.35.2",),
        reference="https://github.com/git/git/security/advisories/GHSA-jrp8-9fh7-2xff",
        severity="high",
    ),
    Advisory(
        id="CVE-2024-32002",
        tool="git",
        summary=(
            "Recursive clone of a repository with a specially named submodule "
            "could write into .git/ and execute a hook during the clone."
        ),
        fixed=("2.45.1", "2.44.1", "2.43.4", "2.42.2", "2.41.1", "2.40.2", "2.39.4"),
        reference="https://github.com/git/git/security/advisories/GHSA-8h77-4q3w-gfgv",
        severity="critical",
    ),
    Advisory(
        id="CVE-2022-3602",
        tool="openssl",
        summary=(
            "Buffer overrun in punycode decoding during X.509 name "
            "constraint checking, reachable after certificate verification."
        ),
        fixed=("3.0.7",),
        introduced="3.0.0",
        reference="https://www.openssl.org/news/secadv/20221101.txt",
        severity="high",
    ),
    Advisory(
        id="CVE-2023-24329",
        tool="python",
        summary=(
            "urllib.parse could be made to ignore a blocklist by prefixing a "
            "URL with whitespace, defeating scheme filtering built on it."
        ),
        fixed=("3.11.4", "3.10.12", "3.9.17", "3.8.17"),
        reference="https://nvd.nist.gov/vuln/detail/CVE-2023-24329",
        severity="medium",
    ),
)

#: The date the bundled set was last reviewed. Hard-coded rather than derived
#: from the release, because a rebuild is not a review.
BUNDLED_PUBLISHED = "2026-09-10"


def bundled_bundle() -> AdvisoryBundle:
    """The advisory set that ships with this package."""
    return AdvisoryBundle(
        published=BUNDLED_PUBLISHED,
        source="bundled",
        advisories=BUNDLED_ADVISORIES,
        signed=True,
        covers=tuple(sorted({a.tool for a in BUNDLED_ADVISORIES})),
    )


def parse_bundle(payload: dict[str, Any], *, source: str, signed: bool) -> AdvisoryBundle:
    """Build a bundle from parsed JSON, rejecting anything malformed.

    Strict rather than lenient. A tolerant parser here silently drops entries,
    and a dropped entry is an advisory that stops being reported without
    anybody noticing -- the exact failure this feature exists to prevent.
    """
    schema = str(payload.get("schema_version") or "")
    if schema != BUNDLE_SCHEMA_VERSION:
        raise AdvisoryError(
            f"advisory bundle schema {schema or 'missing'!r}; this build reads "
            f"{BUNDLE_SCHEMA_VERSION!r}"
        )

    raw_entries = payload.get("advisories")
    if not isinstance(raw_entries, list):
        raise AdvisoryError("advisory bundle has no `advisories` list")

    advisories: list[Advisory] = []
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise AdvisoryError(f"advisory #{index} is not an object")
        try:
            fixed = tuple(str(v) for v in entry["fixed"])
            advisories.append(
                Advisory(
                    id=str(entry["id"]),
                    tool=str(entry["tool"]),
                    summary=str(entry["summary"]),
                    fixed=fixed,
                    reference=str(entry["reference"]),
                    severity=str(entry.get("severity", "unknown")),
                    introduced=(
                        str(entry["introduced"]) if entry.get("introduced") is not None else None
                    ),
                )
            )
        except (KeyError, TypeError) as exc:
            raise AdvisoryError(f"advisory #{index} is missing {exc}") from exc

    covers = payload.get("covers")
    return AdvisoryBundle(
        published=str(payload.get("published") or "unknown"),
        source=source,
        advisories=tuple(advisories),
        signed=signed,
        covers=(
            tuple(str(t) for t in covers)
            if isinstance(covers, list)
            else tuple(sorted({a.tool for a in advisories}))
        ),
    )


def load_bundle(
    path: Path | None = None,
    *,
    key: bytes | None = None,
    trust_unsigned: bool = False,
) -> AdvisoryBundle:
    """Load the bundled set, or an external one after verifying its signature.

    An external bundle needs a sidecar `.sig` produced by `devrepro
    sign-snapshot`'s scheme over the same bytes, and a key in
    `DEVREPRO_ADVISORY_KEY`. The refusal is deliberate: this file decides which
    of your tools get called dangerous, and the interesting attack on it is not
    adding a false entry but quietly removing a true one, which no amount of
    reading the output would reveal.
    """
    if path is None:
        return bundled_bundle()

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AdvisoryError(f"cannot read advisory bundle: {exc}") from exc

    signed = False
    sig_path = path.with_suffix(path.suffix + ".sig")
    if sig_path.is_file():
        if key is None:
            raise AdvisoryError(
                "advisory bundle is signed but no key was supplied; export DEVREPRO_ADVISORY_KEY"
            )
        try:
            signed = verify_bytes(raw, key, sig_path.read_text(encoding="utf-8"))
        except (SigningError, OSError) as exc:
            raise AdvisoryError(f"cannot verify advisory bundle: {exc}") from exc
        if not signed:
            raise AdvisoryError(f"advisory bundle signature does not match: {path.name}")
    elif not trust_unsigned:
        raise AdvisoryError(
            f"advisory bundle {path.name} has no {sig_path.name} beside it; sign it "
            "or pass --trust-unsigned to accept it anyway"
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdvisoryError(f"advisory bundle is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdvisoryError("advisory bundle must be a JSON object")

    return parse_bundle(payload, source=str(path.name), signed=signed)


def _branch(version: Version) -> tuple[int, ...]:
    return tuple(version.nums[:2])


def is_affected(version: str, advisory: Advisory) -> bool:
    """Whether `version` falls before the fix that applies to its branch.

    Branch first: a fix released as 2.45.1, 2.44.1 and 2.43.4 means 2.44.0 is
    affected and 2.44.1 is not, and a single comparison against the highest
    number gets that backwards. So the version's own major.minor is looked up,
    and only if that branch has no listed fix does it fall back to comparing
    against the highest one.

    **The failure mode, stated:** a version on a branch old enough that it
    never received the fix compares against the highest fix and is reported
    affected. That is usually right -- an unpatched branch is unpatched -- and
    it is the safe direction for a warning. It is the wrong direction for a
    gate, which is why nothing built on this blocks.
    """
    try:
        parsed = parse_version(version)
        fixes = [parse_version(f) for f in advisory.fixed]
    except (ValueError, TypeError):
        # `parse_version` raises on anything it does not recognise, and tools
        # report all sorts of things -- "unknown", a git describe string, a
        # localised error. None of that should end a scan, and none of it is
        # evidence of an advisory either.
        return False
    if not fixes:
        return False

    if advisory.introduced:
        introduced = parse_version(advisory.introduced)
        if parsed < introduced:
            return False

    same_branch = [f for f in fixes if _branch(f) == _branch(parsed)]
    if same_branch:
        return parsed < max(same_branch)
    return parsed < max(fixes)


def affected_tools(
    tools: dict[str, str | None],
    bundle: AdvisoryBundle,
) -> tuple[tuple[str, str, Advisory], ...]:
    """Every (tool, version, advisory) triple this bundle has something to say about.

    Tools with no version are skipped rather than guessed at. "Installed, and I
    could not tell you which one" is a real answer elsewhere in this project;
    it is not an input to a version comparison.
    """
    hits: list[tuple[str, str, Advisory]] = []
    for name, version in sorted(tools.items()):
        if not version:
            continue
        for advisory in bundle.for_tool(name):
            if is_affected(version, advisory):
                hits.append((name, version, advisory))
    return tuple(hits)
