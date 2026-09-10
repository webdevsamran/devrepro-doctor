"""A hash chain over snapshot history, and the claim it must not overstate.

The history directory is a pile of files. Edit one, delete another, back-date a
third, and afterwards the directory looks exactly like a directory where none
of that happened. A chain makes each of those visible, because every record
commits to the one before it.

What it does not do is stop anybody. There is no secret, so an attacker with
write access recomputes the whole chain as easily as it was computed. The tests
below therefore cover two things in equal measure: that every tampering shape
is detected, and that the module says out loud what a local chain cannot do.
The second matters because a security feature that is believed to be stronger
than it is does net harm.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from devrepro.snapshots.chain import (
    CHAIN_FILENAME,
    GENESIS,
    ChainError,
    append_entry,
    entry_digest,
    head_digest,
    read_chain,
    verify_chain,
)

MODULE = Path(__file__).resolve().parent.parent / "devrepro" / "snapshots" / "chain.py"


def snapshot(directory: Path, name: str, body: str = "{}") -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def chained(directory: Path, count: int) -> list[Path]:
    paths = []
    for index in range(count):
        path = snapshot(directory, f"snap-{index}.json", json.dumps({"n": index}))
        append_entry(directory, path, recorded_at=f"2026010{index}T000000Z")
        paths.append(path)
    return paths


# ----------------------------------------------------------------- appending


def test_the_first_entry_follows_genesis(tmp_path: Path) -> None:
    """A literal rather than an empty string, so truncation cannot look like a fresh start."""
    entry = append_entry(tmp_path, snapshot(tmp_path, "a.json"), recorded_at="t")
    assert entry.prev == GENESIS
    assert entry.seq == 1


def test_each_entry_commits_to_the_one_before_it(tmp_path: Path) -> None:
    first, second = (
        append_entry(tmp_path, snapshot(tmp_path, f"{n}.json", n), recorded_at="t")
        for n in ("a", "b")
    )
    assert second.prev == first.digest_of_entry


def test_the_chain_file_is_appended_to_not_rewritten(tmp_path: Path) -> None:
    """A crash halfway through must leave a short chain, never a wrong one."""
    chained(tmp_path, 3)
    lines = (tmp_path / CHAIN_FILENAME).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["seq"] for line in lines] == [1, 2, 3]


def test_the_entry_digest_is_canonical(tmp_path: Path) -> None:
    """Same inputs, same digest -- otherwise a chain verifies only where it was made."""
    args = {
        "seq": 1,
        "recorded_at": "t",
        "filename": "a.json",
        "digest": "d",
        "prev": GENESIS,
    }
    assert entry_digest(**args) == entry_digest(**args)  # type: ignore[arg-type]


def test_the_head_of_an_empty_chain_is_genesis(tmp_path: Path) -> None:
    assert head_digest(read_chain(tmp_path)) == GENESIS


def test_a_missing_snapshot_cannot_be_appended(tmp_path: Path) -> None:
    with pytest.raises(ChainError, match="cannot read snapshot"):
        append_entry(tmp_path, tmp_path / "nope.json", recorded_at="t")


# --------------------------------------------------------------- verification


def test_an_untouched_chain_verifies(tmp_path: Path) -> None:
    chained(tmp_path, 3)
    result = verify_chain(tmp_path)
    assert result.ok
    assert result.checked == 3
    assert result.problems == ()


def test_an_empty_directory_verifies_trivially(tmp_path: Path) -> None:
    result = verify_chain(tmp_path)
    assert result.ok
    assert result.head == GENESIS


def test_an_edited_snapshot_is_caught(tmp_path: Path) -> None:
    """The everyday case: a file changed after it was recorded."""
    paths = chained(tmp_path, 3)
    paths[1].write_text('{"n": 99}', encoding="utf-8")

    result = verify_chain(tmp_path)

    assert not result.ok
    assert [p.kind for p in result.problems] == ["snapshot-altered"]
    assert result.problems[0].seq == 2


def test_a_deleted_snapshot_is_caught(tmp_path: Path) -> None:
    paths = chained(tmp_path, 3)
    paths[0].unlink()

    result = verify_chain(tmp_path)

    assert [p.kind for p in result.problems] == ["missing-snapshot"]


def test_a_removed_chain_entry_breaks_the_link(tmp_path: Path) -> None:
    """Deleting the record rather than the file -- and the link is what catches it."""
    chained(tmp_path, 3)
    path = tmp_path / CHAIN_FILENAME
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")

    result = verify_chain(tmp_path)

    kinds = {p.kind for p in result.problems}
    assert "sequence-gap" in kinds
    assert "broken-link" in kinds


def test_an_altered_chain_entry_is_caught(tmp_path: Path) -> None:
    """Rewriting a record without recomputing its digest."""
    chained(tmp_path, 2)
    path = tmp_path / CHAIN_FILENAME
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    record["recorded_at"] = "20991231T235959Z"
    path.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" + lines[1] + "\n",
        encoding="utf-8",
    )

    result = verify_chain(tmp_path)

    assert "entry-altered" in {p.kind for p in result.problems}


def test_a_file_that_was_never_chained_is_reported(tmp_path: Path) -> None:
    """Usually a hand-copied file, and always a record outside every guarantee here."""
    chained(tmp_path, 1)
    snapshot(tmp_path, "hand-placed.json", '{"n": 7}')

    result = verify_chain(tmp_path)

    problem = next(p for p in result.problems if p.kind == "unchained-snapshot")
    assert "hand-placed.json" in problem.detail
    assert problem.seq is None


def test_every_problem_is_reported_not_just_the_first(tmp_path: Path) -> None:
    """One edited file and a rebuilt directory call for different responses."""
    paths = chained(tmp_path, 3)
    paths[0].write_text('{"x": 1}', encoding="utf-8")
    paths[2].write_text('{"x": 2}', encoding="utf-8")

    result = verify_chain(tmp_path)

    assert len([p for p in result.problems if p.kind == "snapshot-altered"]) == 2


def test_a_malformed_chain_line_fails_loudly(tmp_path: Path) -> None:
    """Skipping it is how a chain silently becomes a shorter chain that verifies."""
    chained(tmp_path, 1)
    with (tmp_path / CHAIN_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write("not json\n")

    with pytest.raises(ChainError, match="line 2"):
        verify_chain(tmp_path)


def test_the_head_changes_when_anything_before_it_does(tmp_path: Path) -> None:
    """The property that makes anchoring one short value worth doing."""
    chained(tmp_path, 2)
    before = verify_chain(tmp_path).head

    third = snapshot(tmp_path, "snap-2.json", '{"n": 2}')
    append_entry(tmp_path, third, recorded_at="t")

    assert verify_chain(tmp_path).head != before


def test_the_recorded_digest_is_of_the_file_itself(tmp_path: Path) -> None:
    path = snapshot(tmp_path, "a.json", "contents")
    entry = append_entry(tmp_path, path, recorded_at="t")
    assert entry.digest == hashlib.sha256(b"contents").hexdigest()


# ------------------------------------------------------------------- honesty


def test_the_module_states_what_a_local_chain_cannot_do() -> None:
    """A security feature believed to be stronger than it is does net harm.

    Anyone with write access to the history directory can rebuild the chain
    from any point forward, because there is no secret involved. That has to be
    written down where somebody deciding whether to rely on it will read it.
    """
    # Whitespace-normalised: the sentence is line-wrapped in the source and a
    # substring match against the raw text would pass or fail on reflow.
    prose = " ".join(MODULE.read_text(encoding="utf-8").split())
    assert "can rewrite the entire chain" in prose
    assert "anchoring" in prose


# ------------------------------------------------------------- history store


def test_the_history_store_chains_what_it_saves(tmp_path: Path) -> None:
    from devrepro.core.models import PlatformInfo, Snapshot
    from devrepro.snapshots.history import HistoryStore

    store = HistoryStore(tmp_path)
    snap = Snapshot(
        devrepro_version="0.0.0",
        platform=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
    )
    store.save(snap)

    result = store.verify()

    assert result.ok
    assert result.checked == 1
