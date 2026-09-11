"""Tests for wave-9 capabilities: signing, vault, onboarding bundle, metrics."""

from __future__ import annotations

import json
import tarfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from datetime import UTC, datetime

from devrepro.core.models import (
    Evidence,
    Finding,
    FindingState,
    PlatformInfo,
    ScanReport,
    ToolInstallation,
)
from devrepro.exporters.bundle import build_onboarding_bundle, build_setup_steps
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


def _report_dict() -> dict:
    """The sanitized report, dumped from the real model.

    The fixture here used to be hand-written -- `{"os": {"name": ...}}`, a
    `tools` mapping keyed by name with a `found` flag, and `state: "blocker"` --
    and none of those shapes exists. It had been written to match the code
    rather than the scanner, so the tests agreed with the exporter while both
    disagreed with every report the tool produces, and `devrepro bundle` raised
    `AttributeError` on the first real one it saw.

    Dumping a `ScanReport` is what makes that unrepeatable: a field renamed in
    the model breaks this test, which is the point of having it.
    """
    return json.loads(
        json.dumps(
            ScanReport(
                schema_version="1.0",
                devrepro_version="0.0.0",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                platform=PlatformInfo(os_name="Windows", os_version="10", arch="AMD64"),
                tools=(
                    # Windows reports `python` twice: a real interpreter and an
                    # App Execution Alias that resolves to nothing. The active
                    # one is the version a teammate has to match.
                    ToolInstallation(name="python", version=None, is_active=False),
                    ToolInstallation(name="python", version="3.12.1", is_active=True),
                    ToolInstallation(name="node", version="24.19.0", is_active=True),
                    ToolInstallation(name="perl", version=None, is_active=True),
                ),
                findings=(
                    Finding(
                        rule_id="containers/docker-daemon-pipe-missing",
                        state=FindingState.BLOCKED,
                        summary="daemon unreachable",
                        evidence=(Evidence(source="system", excerpt="pipe missing"),),
                    ),
                ),
                requirements=(),
                probe_errors=(),
            ).model_dump(mode="json"),
            default=str,
        )
    )


_REPORT = _report_dict()


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
    assert report["platform"]["os_name"] == "Windows"
    assert "node" in steps and "preflight" in steps


def test_setup_steps_name_the_blocker_that_is_actually_there() -> None:
    """`state` is `BLOCKED`. The comparison was against `"blocker"`.

    So this file had never reported a blocker in its life -- it told every
    reader "No open blockers were recorded in the sanitized report", on
    machines that had them. A crash stops; a setup guide that says the coast is
    clear gets believed.
    """
    from devrepro.exporters.bundle import build_setup_steps

    joined = " ".join(build_setup_steps(_REPORT))
    assert "containers/docker-daemon-pipe-missing" in joined
    assert "No open blockers" not in joined


def test_setup_steps_match_the_version_that_actually_ran() -> None:
    """Two installations of `python`, one of them an App Execution Alias.

    The alias has no version. Matching it would tell a teammate to install a
    Python that is already there.
    """
    joined = " ".join(build_setup_steps(_REPORT))
    assert "python 3.12.1" in joined
    assert "node 24.19.0" in joined


def test_a_tool_with_no_version_is_called_out_rather_than_dropped() -> None:
    joined = " ".join(build_setup_steps(_REPORT))
    assert "perl" in joined


def test_setup_steps_name_the_operating_system_and_not_its_dictionary() -> None:
    """`str(report.get("platform", ""))` pasted the whole platform mapping in as
    the name of an operating system."""
    first = build_setup_steps(_REPORT)[0]
    assert "Windows" in first
    assert "os_version" not in first
