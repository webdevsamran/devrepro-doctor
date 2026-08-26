"""Tests for wave-9 capabilities: signing, vault, onboarding bundle, metrics."""

from __future__ import annotations

import json
import tarfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from devrepro.exporters.bundle import build_onboarding_bundle
from devrepro.snapshots.signing import (
    SigningError,
    key_from_env,
    sign_bytes,
    sign_file,
    verify_bytes,
    verify_file,
)
from devrepro.snapshots.vault import (
    VaultError,
    decrypt_bytes,
    encrypt_bytes,
    is_encrypted,
)

# ---------------------------------------------------------------- signing ----


def test_sign_verify_roundtrip() -> None:
    data = b'{"snapshot_id": "abc"}'
    doc = sign_bytes(data, b"k" * 32, key_id="ci")
    assert "devrepro-sig-v1" in doc
    assert "hmac-sha256" in doc
    assert verify_bytes(data, b"k" * 32, doc)


def test_verify_rejects_tampered_data() -> None:
    doc = sign_bytes(b"original", b"k" * 32)
    assert not verify_bytes(b"tampered", b"k" * 32, doc)


def test_verify_rejects_wrong_key() -> None:
    doc = sign_bytes(b"data", b"k1" * 16)
    assert not verify_bytes(b"data", b"k2" * 16, doc)


def test_sign_file_writes_sidecar(tmp_path: Path) -> None:
    f = tmp_path / "snap.json"
    f.write_text("{}", encoding="utf-8")
    sig = sign_file(f, b"k" * 32)
    assert sig.name == "snap.json.sig"
    assert sig.is_file()
    assert verify_file(f, b"k" * 32)


def test_empty_key_rejected() -> None:
    with pytest.raises(SigningError):
        sign_bytes(b"x", b"")


def test_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVREPRO_SIGNING_KEY", raising=False)
    with pytest.raises(SigningError):
        key_from_env()
    monkeypatch.setenv("DEVREPRO_SIGNING_KEY", "secret")
    assert key_from_env() == b"secret"


def test_missing_signature_file(tmp_path: Path) -> None:
    from devrepro.snapshots.signing import read_signature

    f = tmp_path / "x.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(SigningError):
        read_signature(f)


# ------------------------------------------------------------------ vault ----


def test_vault_roundtrip_when_available() -> None:
    cryptography = pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    blob = encrypt_bytes(b'{"a": 1}', key)
    assert blob.startswith(b"devrepro-vault-v1:")
    assert decrypt_bytes(blob, key) == b'{"a": 1}'
    _ = cryptography


def test_vault_not_encrypted_marker(tmp_path: Path) -> None:
    f = tmp_path / "plain.json"
    f.write_text("{}", encoding="utf-8")
    assert not is_encrypted(f)


def test_decrypt_rejects_non_vault_blob() -> None:
    with pytest.raises(VaultError):
        decrypt_bytes(b"plain text", b"k")


# ----------------------------------------------------------------- bundle ----

_REPORT = {
    "os": {"name": "windows"},
    "tools": {
        "python": {"found": True, "version": "3.12"},
        "node": {"found": False},
    },
    "findings": [{"rule_id": "R001", "state": "blocker"}],
}


def test_bundle_contains_members_and_checksums(tmp_path: Path) -> None:
    out = build_onboarding_bundle(_REPORT, tmp_path / "bundle.tar.gz", project_name="demo")
    assert out.is_file()
    with tarfile.open(out, "r:gz") as tf:
        names = set(tf.getnames())
        assert {"report.json", "requirements.json", "setup-steps.md", "manifest.json"} <= names
        manifest = json.load(tf.extractfile("manifest.json"))  # type: ignore[arg-type]
        report = json.load(tf.extractfile("report.json"))  # type: ignore[arg-type]
        steps = tf.extractfile("setup-steps.md").read().decode()  # type: ignore[union-attr]
    assert manifest["format"] == "devrepro-onboarding-bundle"
    assert manifest["members"]["report.json"]
    assert report["os"]["name"] == "windows"
    assert "node" in steps and "preflight" in steps


def test_setup_steps_cover_missing_tools_and_blockers() -> None:
    from devrepro.exporters.bundle import build_setup_steps

    steps = build_setup_steps(_REPORT)
    joined = " ".join(steps)
    assert "node" in joined
    assert "R001" in joined
