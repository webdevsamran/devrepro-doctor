"""Version parsing and range satisfaction.

Implements a pragmatic subset of version-range semantics used across
ecosystems (npm engines, python requires, tool constraints):

    "*"            any version
    ">=1.2"        at least 1.2
    "<3.14"        below 3.14
    "!=1.2.3"      exclude exact version
    "=1.2.3"       exact version
    ">=3.11,<3.14" conjunction of clauses
    ">=20 || 18"   alternative clauses (OR groups)

Versions are compared numerically per dot-separated component; missing
components are zero (1.2 == 1.2.0). A trailing non-numeric suffix
(e.g. ``18.19.0-rc.1``, ``3.12.4+cpu``) is treated as a pre/build tag:
the numeric part compares normally and the tag sorts *before* the
release (PEP 440 / semver pre-release convention).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["SpecClause", "SpecSet", "Version", "parse_version", "satisfies", "spec_satisfied_by"]

_VERSION_RE = re.compile(
    r"^v?(?P<nums>\d+(?:\.\d+)*)"
    r"[.\-+]?(?P<tag>[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)

_CLAUSE_RE = re.compile(r"^(?P<op>\*|>=|<=|!=|==|=|>|<)?\s*(?P<ver>.+)$")


class Version:
    """A parsed version with total ordering."""

    __slots__ = ("nums", "raw", "tag")

    def __init__(self, raw: str) -> None:
        text = raw.strip()
        m = _VERSION_RE.match(text)
        if not m:
            raise ValueError(f"invalid version: {raw!r}")
        self.raw = text
        self.nums: tuple[int, ...] = tuple(int(p) for p in m.group("nums").split("."))
        self.tag: str | None = m.group("tag")

    def _key(self) -> tuple[tuple[int, ...], int, tuple[int, ...]]:
        # tag sorts before release (pre-release convention); empty tag = release
        tag_key = () if self.tag is None else tuple(ord(c) for c in self.tag)
        return (self.nums, 0 if self.tag is None else 1, tag_key)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() <= other._key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() > other._key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() >= other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Version({self.raw!r})"

    def __str__(self) -> str:
        return self.raw


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def _cmp_versions(a: Version, b: Version) -> int:
    an, bn = _pad(a.nums, b.nums)
    if an < bn:
        return -1
    if an > bn:
        return 1
    # equal numerics: pre-release < release
    at, _bt = (1, ()) if a.tag is None else (0, tuple(ord(c) for c in a.tag))
    bt2 = (1, ()) if b.tag is None else (0, tuple(ord(c) for c in b.tag))
    if at != bt2[0]:
        return -1 if at < bt2[0] else 1
    if at == 1:
        return 0
    if a.tag is None or b.tag is None:  # pragma: no cover - guarded above
        return 0
    if a.tag < b.tag:
        return -1
    if a.tag > b.tag:
        return 1
    return 0


@dataclass(frozen=True)
class SpecClause:
    """A single comparison clause, e.g. ``>=3.11``."""

    op: str  # one of *, >=, <=, !=, ==, =, >, <
    version: Version

    def satisfied_by(self, candidate: Version) -> bool:
        if self.op == "*":
            return True
        c = _cmp_versions(candidate, self.version)
        return {
            ">=": c >= 0,
            "<=": c <= 0,
            ">": c > 0,
            "<": c < 0,
            "!=": c != 0,
            "==": c == 0,
            "=": c == 0,
        }[self.op]


@dataclass(frozen=True)
class SpecSet:
    """A version specification: AND of clauses, OR of groups.

    ``">=3.11,<3.14 || >=3.15"`` means (>=3.11 AND <3.14) OR (>=3.15).
    """

    groups: tuple[tuple[SpecClause, ...], ...]

    def satisfied_by(self, candidate: Version) -> bool:
        return any(all(clause.satisfied_by(candidate) for clause in group) for group in self.groups)

    def __str__(self) -> str:
        return " || ".join(",".join(f"{c.op}{c.version}" for c in group) for group in self.groups)


def parse_version(raw: str) -> Version:
    """Parse a version string, raising ``ValueError`` on garbage."""
    return Version(raw)


def _partial_clauses(op: str, ver_text: str) -> list[SpecClause]:
    """npm-style semantics for partial versions like ``16``, ``16.2``.

    ``<=16`` means ``<17``; bare ``18`` means ``>=18,<19``.
    """
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", ver_text)
    if not m:
        return [SpecClause(op or "==", Version(ver_text))]
    major = int(m.group(1))
    minor = m.group(2)
    patch = m.group(3)
    partial = minor is None or patch is None
    if not partial:
        return [SpecClause(op or "==", Version(ver_text))]
    if op in ("<", "<="):
        # bump only for a single-component bound ("<=16" -> "<17");
        # multi-component bounds ("<3.14") stay literal
        if minor is None:
            return [SpecClause("<", Version(f"{major + 1}.0.0"))]
        return [SpecClause(op, Version(ver_text))]
    if op in (">", ">="):
        return [SpecClause(">=", Version(f"{major}.{minor or 0}.0"))]
    if op in ("", "*", "==", "="):
        return [
            SpecClause(">=", Version(f"{major}.{minor or 0}.0")),
            SpecClause("<", Version(f"{major + 1}.0.0")),
        ]
    return [SpecClause(op, Version(ver_text))]


def parse_spec(spec: str) -> SpecSet:
    """Parse a range expression into a :class:`SpecSet`."""
    groups: list[tuple[SpecClause, ...]] = []
    for raw_group in spec.split("||"):
        clauses: list[SpecClause] = []
        for raw_clause in raw_group.split(","):
            text = raw_clause.strip()
            if not text:
                continue
            if text == "*":
                clauses.append(SpecClause("*", Version("0")))
                continue
            m = _CLAUSE_RE.match(text)
            if not m or not m.group("ver"):
                raise ValueError(f"invalid version clause: {text!r}")
            op = m.group("op") or ""
            clauses.extend(_partial_clauses(op, m.group("ver")))
        if clauses:
            groups.append(tuple(clauses))
    if not groups:
        groups.append((SpecClause("*", Version("0")),))
    return SpecSet(tuple(groups))


def satisfies(version: str, spec: str) -> bool:
    """Convenience: does ``version`` satisfy ``spec``?

    The wildcard spec ``*`` (also "" / "any") is satisfied by any version,
    even one we cannot fully parse (e.g. ``2.55.0.windows.3``).
    """
    if spec.strip() in ("*", "", "any"):
        return True
    return parse_spec(spec).satisfied_by(parse_version(version))


def spec_satisfied_by(spec: str, version: str) -> bool:
    """Alias kept for readability at call sites."""
    return satisfies(version, spec)
