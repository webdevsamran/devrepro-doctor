"""A hash chain over the snapshot history, and an honest account of its limits.

The history directory is a pile of files with timestamps in their names. That
is fine for reading drift and useless as evidence: a file can be edited, an
inconvenient one deleted, and a flattering one back-dated, and nothing about
the directory afterwards looks different from a directory where none of that
happened. "Here is my environment history" is a claim, and the pile supports
it only for people who already trust you.

A chain fixes the part that can be fixed. Each entry commits to the digest of
the snapshot file *and* to the digest of the entry before it, so changing any
record changes every record after it. Deleting one breaks the link at that
point. Reordering breaks it too. None of that requires a key, a server or a
network.

**What it does not do, stated plainly, because this is the part people get
wrong.** An attacker who can write to the history directory can rewrite the
entire chain from any point forward -- there is no secret involved, so
recomputing it is as easy as computing it. A local hash chain is
*tamper-evident against everyone who does not think to recompute it*, which
includes accidents, sync conflicts, careless cleanup scripts and the
overwhelming majority of real cases, and does not include a deliberate,
informed adversary with write access.

What upgrades it is anchoring: the chain head is a single short digest, and
publishing that anywhere the attacker cannot reach -- a commit message, a
ticket, a chat message, a signature -- fixes history up to that point for good.
`head_digest` exists to make that a one-line habit, and the CLI prints it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "CHAIN_FILENAME",
    "GENESIS",
    "ChainEntry",
    "ChainError",
    "ChainProblem",
    "ChainVerification",
    "append_entry",
    "entry_digest",
    "head_digest",
    "read_chain",
    "verify_chain",
]

CHAIN_FILENAME = "chain.jsonl"

#: The `prev` value of the first entry. A literal rather than an empty string
#: so a truncated file cannot masquerade as a fresh chain.
GENESIS = "genesis"

_SCHEMA = "devrepro-chain-v1"


class ChainError(Exception):
    """Raised when the chain file cannot be read or appended to."""


@dataclass(frozen=True)
class ChainEntry:
    """One link: which snapshot, its digest, and what came before it."""

    seq: int
    recorded_at: str
    filename: str
    digest: str
    prev: str
    digest_of_entry: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "seq": self.seq,
            "recorded_at": self.recorded_at,
            "filename": self.filename,
            "digest": self.digest,
            "prev": self.prev,
            "entry_digest": self.digest_of_entry,
        }


def entry_digest(*, seq: int, recorded_at: str, filename: str, digest: str, prev: str) -> str:
    """The digest of a link's contents.

    Serialised with sorted keys and no whitespace so the bytes hashed here do
    not depend on how the file happened to be written. A canonical form is the
    difference between a chain that verifies on another machine and one that
    verifies only where it was made.
    """
    payload = json.dumps(
        {
            "digest": digest,
            "filename": filename,
            "prev": prev,
            "recorded_at": recorded_at,
            "schema": _SCHEMA,
            "seq": seq,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_chain(directory: Path) -> tuple[ChainEntry, ...]:
    """Every link recorded in a history directory, in file order.

    A malformed line raises rather than being skipped. Skipping is how a chain
    silently becomes a shorter chain that still verifies, which is precisely
    the outcome the file exists to prevent.
    """
    path = directory / CHAIN_FILENAME
    if not path.is_file():
        return ()
    entries: list[ChainEntry] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChainError(f"cannot read {CHAIN_FILENAME}: {exc}") from exc

    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            entries.append(
                ChainEntry(
                    seq=int(record["seq"]),
                    recorded_at=str(record["recorded_at"]),
                    filename=str(record["filename"]),
                    digest=str(record["digest"]),
                    prev=str(record["prev"]),
                    digest_of_entry=str(record["entry_digest"]),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ChainError(f"{CHAIN_FILENAME} line {number} is malformed: {exc}") from exc
    return tuple(entries)


def head_digest(entries: Iterable[ChainEntry]) -> str:
    """The digest to write down somewhere this directory cannot reach.

    One value fixes the whole history: anchoring it externally converts a chain
    anyone could rewrite into one that can only be extended.
    """
    last = GENESIS
    for entry in entries:
        last = entry.digest_of_entry
    return last


def append_entry(directory: Path, snapshot_path: Path, *, recorded_at: str) -> ChainEntry:
    """Record a snapshot in the chain and return the new link.

    Appends rather than rewrites. An append-only file is the one shape where a
    crash halfway through leaves a chain that is short rather than a chain that
    is wrong.
    """
    try:
        data = snapshot_path.read_bytes()
    except OSError as exc:
        raise ChainError(f"cannot read snapshot: {exc}") from exc

    existing = read_chain(directory)
    prev = head_digest(existing)
    seq = len(existing) + 1
    digest = hashlib.sha256(data).hexdigest()
    entry = ChainEntry(
        seq=seq,
        recorded_at=recorded_at,
        filename=snapshot_path.name,
        digest=digest,
        prev=prev,
        digest_of_entry=entry_digest(
            seq=seq,
            recorded_at=recorded_at,
            filename=snapshot_path.name,
            digest=digest,
            prev=prev,
        ),
    )
    line = json.dumps(entry.as_dict(), sort_keys=True, separators=(",", ":"))
    try:
        with (directory / CHAIN_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        raise ChainError(f"cannot append to {CHAIN_FILENAME}: {exc}") from exc
    return entry


@dataclass(frozen=True)
class ChainProblem:
    """Something wrong with the chain, named precisely enough to act on."""

    kind: str
    seq: int | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "seq": self.seq, "detail": self.detail}


@dataclass(frozen=True)
class ChainVerification:
    """The verdict, the head to anchor, and every problem found.

    Every problem, not the first one. Stopping at the first break hides whether
    a directory has one edited file or has been rebuilt wholesale, and those
    call for different responses.
    """

    ok: bool
    checked: int
    head: str
    problems: tuple[ChainProblem, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "head": self.head,
            "problems": [p.as_dict() for p in self.problems],
        }


def verify_chain(directory: Path, *, snapshot_suffix: str = ".json") -> ChainVerification:
    """Check every link, every file digest, and what the chain does not mention.

    The last of those matters more than it looks. A snapshot file sitting in
    the history directory with no chain entry is not evidence of tampering --
    it is usually a file copied in by hand -- but it is a record that reads as
    history and is not covered by any of this, so it is reported.
    """
    entries = read_chain(directory)
    problems: list[ChainProblem] = []
    expected_prev = GENESIS

    for index, entry in enumerate(entries, start=1):
        if entry.seq != index:
            problems.append(
                ChainProblem(
                    "sequence-gap",
                    entry.seq,
                    f"entry {index} in the file claims sequence {entry.seq}; a record was "
                    "removed or reordered",
                )
            )
        if entry.prev != expected_prev:
            problems.append(
                ChainProblem(
                    "broken-link",
                    entry.seq,
                    "this entry does not follow the one before it; the history was edited "
                    "at or before this point",
                )
            )
        recomputed = entry_digest(
            seq=entry.seq,
            recorded_at=entry.recorded_at,
            filename=entry.filename,
            digest=entry.digest,
            prev=entry.prev,
        )
        if recomputed != entry.digest_of_entry:
            problems.append(
                ChainProblem(
                    "entry-altered",
                    entry.seq,
                    "the recorded entry digest does not match the entry's own contents",
                )
            )

        target = directory / entry.filename
        if not target.is_file():
            problems.append(
                ChainProblem("missing-snapshot", entry.seq, f"{entry.filename} is gone")
            )
        else:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != entry.digest:
                problems.append(
                    ChainProblem(
                        "snapshot-altered",
                        entry.seq,
                        f"{entry.filename} does not match the digest recorded for it",
                    )
                )
        expected_prev = entry.digest_of_entry

    recorded = {entry.filename for entry in entries}
    for path in sorted(directory.glob("*" + snapshot_suffix)):
        if path.name == CHAIN_FILENAME or path.name in recorded:
            continue
        problems.append(
            ChainProblem(
                "unchained-snapshot",
                None,
                f"{path.name} is in the history directory but not in the chain",
            )
        )

    return ChainVerification(
        ok=not problems,
        checked=len(entries),
        head=head_digest(entries),
        problems=tuple(problems),
    )
