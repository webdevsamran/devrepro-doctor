"""A watcher narrow enough that people leave it running.

Two design decisions carry the weight, and both are the sort that only show up
under test.

**It watches the environment contract, not the tree.** Editing a function body
changes nothing about what the machine must provide, and a scan triggered by it
is five seconds of nothing. A watcher that fires on every save is a watcher
people turn off in an afternoon.

**It debounces.** One save from an editor is routinely a truncate, a write and
a rename. Without a quiet period that is three scans for one edit, and at least
one of them reads a half-written file.

The loop takes its clock, its sleep and its poll count as arguments, so these
tests drive it to completion rather than racing it. A test of a watcher that
does not control time is a test that hangs or flakes.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- pytest resolves fixture annotations

from devrepro.watch import Change, fingerprint, watch, watched_paths


class FakeClock:
    """Time that only moves when the loop sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def touch(path: Path, body: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------------ what is watched


def test_contract_files_are_watched(tmp_path: Path) -> None:
    touch(tmp_path / "package.json")
    touch(tmp_path / ".nvmrc")
    touch(tmp_path / "pyproject.toml")

    names = {p.name for p in watched_paths(tmp_path)}

    assert names == {"package.json", ".nvmrc", "pyproject.toml"}


def test_source_files_are_not_watched(tmp_path: Path) -> None:
    """The whole reason this is usable. A function body is not a contract."""
    touch(tmp_path / "main.py")
    touch(tmp_path / "src" / "index.ts")
    touch(tmp_path / "README.md")

    assert watched_paths(tmp_path) == ()


def test_a_workspace_manifest_below_the_root_is_watched(tmp_path: Path) -> None:
    touch(tmp_path / "web" / "package.json")
    assert [p.name for p in watched_paths(tmp_path)] == ["package.json"]


def test_dependency_directories_are_never_descended(tmp_path: Path) -> None:
    """Every package.json in node_modules belongs to a dependency, not to you.

    Walking it would also cost more than the scan the walk exists to trigger.
    """
    touch(tmp_path / "node_modules" / "left-pad" / "package.json")
    touch(tmp_path / ".git" / "config")
    touch(tmp_path / ".venv" / "pyvenv.cfg")

    assert watched_paths(tmp_path) == ()


def test_the_walk_is_depth_bounded(tmp_path: Path) -> None:
    """Contract files live at a root or one workspace down, never nine deep."""
    touch(tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "package.json")
    assert watched_paths(tmp_path) == ()


# ------------------------------------------------------------- fingerprinting


def test_a_fingerprint_records_size_as_well_as_time(tmp_path: Path) -> None:
    """Several network filesystems have one-second mtime granularity.

    An edit made inside that second is invisible to mtime alone, and size comes
    from the same `stat` call, so it costs nothing to check both.
    """
    path = touch(tmp_path / "package.json", "one")
    first = fingerprint([path], tmp_path)

    path.write_text("a much longer body", encoding="utf-8")
    second = fingerprint([path], tmp_path)

    assert first["package.json"][1] != second["package.json"][1]


def test_a_file_deleted_mid_walk_does_not_raise(tmp_path: Path) -> None:
    missing = tmp_path / "gone.json"
    assert fingerprint([missing], tmp_path) == {}


# --------------------------------------------------------------------- the loop


def test_an_unchanged_tree_never_fires(tmp_path: Path) -> None:
    touch(tmp_path / "package.json")
    clock = FakeClock()
    fired: list[Change] = []

    count = watch(
        tmp_path,
        fired.append,
        clock=clock,
        sleeper=clock.sleep,
        max_polls=10,
    )

    assert count == 0
    assert fired == []


def test_a_change_fires_once_after_the_tree_settles(tmp_path: Path) -> None:
    path = touch(tmp_path / "package.json", "one")
    clock = FakeClock()
    fired: list[Change] = []

    def sleeper(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now == 1.0:  # exactly one edit, on the first poll
            path.write_text("two", encoding="utf-8")

    count = watch(
        tmp_path,
        fired.append,
        clock=clock,
        sleeper=sleeper,
        max_polls=6,
    )

    assert count == 1
    assert fired[0].modified == ("package.json",)


def test_a_burst_of_writes_produces_one_scan(tmp_path: Path) -> None:
    """A single editor save is a truncate, a write and a rename.

    Without the quiet period that is three scans for one edit, and at least one
    of them reads a half-written file.
    """
    path = touch(tmp_path / "package.json", "one")
    clock = FakeClock()
    fired: list[Change] = []

    def sleeper(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now <= 3.0:  # three consecutive polls all see movement
            path.write_text("x" * int(clock.now * 10), encoding="utf-8")

    count = watch(
        tmp_path,
        fired.append,
        interval=1.0,
        quiet_period=1.5,
        clock=clock,
        sleeper=sleeper,
        max_polls=10,
    )

    assert count == 1


def test_a_new_contract_file_is_itself_a_change(tmp_path: Path) -> None:
    """A cached file list would never see a lockfile that did not exist yet."""
    touch(tmp_path / "package.json")
    clock = FakeClock()
    fired: list[Change] = []

    def sleeper(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now == 1.0:
            touch(tmp_path / "package-lock.json")

    watch(tmp_path, fired.append, clock=clock, sleeper=sleeper, max_polls=6)

    assert fired[0].added == ("package-lock.json",)


def test_a_removed_contract_file_is_a_change(tmp_path: Path) -> None:
    path = touch(tmp_path / "package-lock.json")
    clock = FakeClock()
    fired: list[Change] = []

    def sleeper(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now == 1.0:
            path.unlink()

    watch(tmp_path, fired.append, clock=clock, sleeper=sleeper, max_polls=6)

    assert fired[0].removed == ("package-lock.json",)


def test_two_separate_edits_fire_twice(tmp_path: Path) -> None:
    """Debouncing collapses a burst, not the whole session."""
    path = touch(tmp_path / "package.json", "one")
    clock = FakeClock()
    fired: list[Change] = []

    def sleeper(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now in (1.0, 6.0):
            path.write_text("x" * int(clock.now), encoding="utf-8")

    count = watch(
        tmp_path,
        fired.append,
        interval=1.0,
        quiet_period=1.5,
        clock=clock,
        sleeper=sleeper,
        max_polls=12,
    )

    assert count == 2


def test_a_change_describes_itself_for_the_log() -> None:
    change = Change(added=("a.json",), modified=("b.json",), removed=("c.json",))
    described = change.describe()
    assert "added: a.json" in described
    assert "changed: b.json" in described
    assert "removed: c.json" in described


def test_an_empty_change_is_falsy() -> None:
    assert not Change()
    assert Change(added=("x",))
