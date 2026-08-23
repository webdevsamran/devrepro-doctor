"""Privacy engine tests incl. synthetic-secret regression suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from devrepro.privacy.gate import (
    PrivacyGate,
    assert_no_secrets,
    redact,
    scan_for_secrets,
)
from hypothesis import given
from hypothesis import strategies as st

SYNTHETIC_SECRETS = Path(__file__).parent / "fixtures" / "secrets" / "synthetic.txt"


def test_home_path_redacted() -> None:
    gate = PrivacyGate(home="/home/alice", username="alice")
    out = gate.redact("config at /home/alice/projects/app")
    assert "/home/alice" not in out
    assert "~" in out


def test_username_redacted() -> None:
    gate = PrivacyGate(home="/home/alice", username="alice")
    out = gate.redact("run as alice today")
    assert "alice" not in out
    assert "<user>" in out


def test_email_redacted() -> None:
    out = redact("contact dev.example+ci@gmail.com please")
    assert "@" not in out.replace("<email-redacted>", "")
    assert "dev.example" not in out


def test_windows_home_variants() -> None:
    gate = PrivacyGate(home="C:" + chr(92) + "Users" + chr(92) + "sam", username="sam")
    target = "installed at C:" + chr(92) + "Users" + chr(92) + "sam" + chr(92) + "tools"
    out = gate.redact(target)
    assert "sam" not in out and "Users" not in out


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0",
        "sk-proj-" + "x" * 30,
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
        "Authorization: Bearer abcdef1234567890abcdef",
        "-----BEGIN RSA PRIVATE KEY-----",
        "api_key = supersecretvalue123",
        "PASSWORD: hunter2hunter2",
    ],
)
def test_synthetic_secrets_detected(secret: str) -> None:
    assert scan_for_secrets(secret), f"missed: {secret[:20]}"


def test_assert_no_secrets_blocks() -> None:
    with pytest.raises(Exception):
        assert_no_secrets("token ghp_" + "z" * 30)


def test_clean_text_passes() -> None:
    assert_no_secrets("python 3.12.4 at /usr/bin/python; node v20.11.0")


def test_fixture_file_has_no_real_secrets_after_scan() -> None:
    text = SYNTHETIC_SECRETS.read_text(encoding="utf-8")
    kinds = scan_for_secrets(text)
    assert kinds, "fixture must contain detectable synthetic secrets"


@given(st.text(max_size=200))
def test_redaction_never_crashes(text: str) -> None:
    gate = PrivacyGate(home="/home/x", username="x")
    assert isinstance(gate.redact(text), str)
