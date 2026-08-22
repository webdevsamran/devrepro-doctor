"""PATH analyzer tests incl. property-based normalization."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from devrepro.platforms.base import build_path_analysis

SAFE_CHARS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/._-", min_size=1, max_size=20)


@given(st.lists(SAFE_CHARS, min_size=1, max_size=10))
def test_normalization_preserves_count(entries: list[str]) -> None:
    raw = ":".join(entries)
    a = build_path_analysis(raw, "linux")
    assert len(a.entries) == len(entries)


def test_duplicates_detected() -> None:
    a = build_path_analysis("/usr/bin:/usr/local/bin:/usr/bin", "linux")
    assert "/usr/bin" in a.duplicates


def test_dead_entries() -> None:
    a = build_path_analysis("/nonexistent-xyz-123:/usr/bin", "linux")
    assert "/nonexistent-xyz-123" in a.dead_entries


def test_shadowing_order(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    d1 = tmp_path / "first"
    d2 = tmp_path / "second"
    d1.mkdir()
    d2.mkdir()
    (d1 / "python").write_text("")
    (d2 / "python").write_text("")
    a = build_path_analysis("second:first", "linux")
    assert any(name == "python" for name, _, _ in a.shadowed_executables)


def test_windows_store_alias_flagged() -> None:
    raw = "C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + "AppData" + chr(92) \
        + "Local" + chr(92) + "Microsoft" + chr(92) + "WindowsApps"
    a = build_path_analysis(raw, "windows")
    assert a.store_aliases
