"""Unit + property tests for version parsing and range satisfaction."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from devrepro.core.versioning import parse_spec, parse_version, satisfies

MAJOR = st.integers(min_value=0, max_value=50)
MINOR = st.integers(min_value=0, max_value=50)


def ver(major: int, minor: int) -> str:
    return f"{major}.{minor}.0"


@given(MAJOR, MINOR, MAJOR, MINOR)
def test_range_bounds_property(lo_maj: int, lo_min: int, hi_maj: int, hi_min: int) -> None:
    lo = (lo_maj, lo_min)
    hi = (hi_maj, hi_min)
    if hi <= lo:
        return  # degenerate empty range
    spec = f">={ver(*lo)},<{ver(*hi)}"
    inside = ver(*((lo[0] + 1), lo[1])) if hi > (lo[0] + 1, lo[1]) else None
    assert satisfies(ver(*lo), spec)
    if inside:
        assert satisfies(inside, spec)
    assert not satisfies(ver(*hi), spec)


@given(MAJOR, MINOR)
def test_star_matches_everything(major: int, minor: int) -> None:
    assert satisfies(ver(major, minor), "*")


@given(MAJOR, MINOR)
def test_exact_match(major: int, minor: int) -> None:
    v = ver(major, minor)
    assert satisfies(v, v)
    assert not satisfies(v, "!=" + v)


def test_padding() -> None:
    assert satisfies("3.11", ">=3.11.0")
    assert satisfies("3.11.0", ">=3.11")


def test_prerelease_sorts_before_release() -> None:
    assert satisfies("1.0.0-rc.1", "<1.0.0")
    assert not satisfies("1.0.0", "<1.0.0")


def test_or_groups() -> None:
    spec = ">=20 || 18"
    assert satisfies("20.5.0", spec)
    assert satisfies("18.19.0", spec)
    assert not satisfies("19.0.0", spec)


def test_leading_v_accepted() -> None:
    assert satisfies("v18.19.0", ">=18")


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ("3.12.4", ">=3.11,<3.14", True),
        ("3.14.0", ">=3.11,<3.14", False),
        ("16.20.2", "<=16", True),
        ("20.1.0", ">=20", True),
        ("1.2.3", "=1.2.3", True),
        ("1.2.4", "=1.2.3", False),
    ],
)
def test_table(version: str, spec: str, expected: bool) -> None:
    assert satisfies(version, spec) is expected


def test_invalid_version_raises() -> None:
    with pytest.raises(ValueError):
        parse_version("not-a-version")
    with pytest.raises(ValueError):
        parse_spec(">=abc")