"""Detached snapshot signing and verification (HMAC-SHA256).

Signatures are written as sidecar ``*.sig`` files containing::

    devrepro-sig-v1
    algorithm: hmac-sha256
    key-id: <optional label>
    signature: <hex digest>

This is deliberately dependency-free so every installation can sign and
verify snapshots without extra tooling. For stronger non-secret key models,
use an external signer (cosign/minisign) over the same artifact bytes; the
signature format here only needs the raw file bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "SIGNATURE_PREFIX",
    "SigningError",
    "key_from_env",
    "read_signature",
    "sign_bytes",
    "sign_file",
    "verify_bytes",
    "verify_file",
]

SIGNATURE_PREFIX = "devrepro-sig-v1"


class SigningError(Exception):
    """Raised when signing/verification inputs are invalid."""


def key_from_env(env_var: str = "DEVREPRO_SIGNING_KEY") -> bytes:
    """Load a signing key from an environment variable (never logged)."""
    value = os.environ.get(env_var, "")
    if not value:
        raise SigningError(f"signing key not set; export {env_var} (never commit it)")
    return value.encode("utf-8")


def sign_bytes(data: bytes, key: bytes, key_id: str = "") -> str:
    """Return the detached signature document for *data*."""
    if not key:
        raise SigningError("empty signing key")
    digest = hmac.new(key, data, hashlib.sha256).hexdigest()
    lines = [SIGNATURE_PREFIX, "algorithm: hmac-sha256"]
    if key_id:
        lines.append(f"key-id: {key_id}")
    lines.append(f"signature: {digest}")
    return "\n".join(lines) + "\n"


def verify_bytes(data: bytes, key: bytes, signature_doc: str) -> bool:
    """Constant-time verification of *data* against a signature document."""
    expected = None
    for line in signature_doc.splitlines():
        if line.startswith("signature:"):
            expected = line.split(":", 1)[1].strip().lower()
            break
    if not expected:
        return False
    actual = hmac.new(key, data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected)


def sign_file(path: Path, key: bytes, key_id: str = "") -> Path:
    """Write a detached ``<path>.sig`` next to *path* and return its location."""
    sig_path = path.with_name(path.name + ".sig")
    sig_path.write_text(sign_bytes(path.read_bytes(), key, key_id), encoding="utf-8")
    return sig_path


def read_signature(path: Path) -> str:
    """Read the sidecar signature for *path*."""
    sig_path = path.with_name(path.name + ".sig")
    if not sig_path.is_file():
        raise SigningError(f"missing signature file: {sig_path.name}")
    return sig_path.read_text(encoding="utf-8")


def verify_file(path: Path, key: bytes) -> bool:
    """Verify *path* against its sidecar ``.sig`` file."""
    return verify_bytes(path.read_bytes(), key, read_signature(path))
