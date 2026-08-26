"""Encryption-at-rest for local snapshots that cannot be safely redacted.

Uses Fernet (AES-128-CBC + HMAC, authenticated) from the optional
``cryptography`` package. Install with::

    pip install "devrepro-doctor[secure]"

Encrypted artifacts carry a ``devrepro-vault-v1`` header line so readers can
distinguish them from plaintext JSON without attempting decryption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "VAULT_HEADER",
    "VaultError",
    "decrypt_file",
    "encrypt_bytes",
    "encrypt_file",
    "is_encrypted",
    "key_from_env",
]

VAULT_HEADER = b"devrepro-vault-v1:"


class VaultError(Exception):
    """Raised when encryption-at-rest is requested but unavailable/misconfigured."""


def _fernet() -> type[Any]:  # pragma: no cover - thin import shim
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise VaultError(
            "encryption-at-rest requires the 'cryptography' package; "
            'install with pip install "devrepro-doctor[secure]"'
        ) from exc
    # cryptography ships no inline stubs; without them the import is Any.
    return cast("type[Any]", Fernet)


def key_from_env(env_var: str = "DEVREPRO_VAULT_KEY") -> bytes:
    """Load a Fernet key (urlsafe base64 32 bytes) from the environment."""
    import os

    value = os.environ.get(env_var, "")
    if not value:
        raise VaultError(f"vault key not set; export {env_var} (never commit it)")
    return value.encode("utf-8")


def is_encrypted(path: Path) -> bool:
    """Return True when *path* starts with the vault header."""
    try:
        with path.open("rb") as fh:
            return fh.read(len(VAULT_HEADER)) == VAULT_HEADER
    except OSError:
        return False


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Encrypt *data* and prefix the vault header."""
    fernet_cls = _fernet()
    token: bytes = fernet_cls(key).encrypt(data)
    return VAULT_HEADER + token


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    """Decrypt a header-prefixed vault blob."""
    if not blob.startswith(VAULT_HEADER):
        raise VaultError("not an encrypted devrepro vault artifact")
    fernet_cls = _fernet()
    token = blob[len(VAULT_HEADER) :]
    plain: bytes = fernet_cls(key).decrypt(token)
    return plain


def encrypt_file(path: Path, key: bytes) -> Path:
    """Encrypt *path* in place (writes ``<path>.vault`` and removes plaintext)."""
    encrypted_path = path.with_name(path.name + ".vault")
    encrypted_path.write_bytes(encrypt_bytes(path.read_bytes(), key))
    path.unlink()
    return encrypted_path


def decrypt_file(vault_path: Path, key: bytes, keep_vault: bool = True) -> Path:
    """Decrypt ``*.vault`` back to its original name.

    The encrypted artifact is kept by default so destructive mistakes are
    recoverable; pass ``keep_vault=False`` to remove it after success.
    """
    target = vault_path.with_name(
        vault_path.name[: -len(".vault")] if vault_path.name.endswith(".vault") else vault_path.name
    )
    target.write_bytes(decrypt_bytes(vault_path.read_bytes(), key))
    if not keep_vault:
        vault_path.unlink()
    return target
