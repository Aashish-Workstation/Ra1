"""
AES-256-GCM encryption helpers for the RA1 Credential Vault.

Design choices
--------------
* AES-256 in GCM mode (authenticated encryption, confidentiality + integrity).
* 96-bit random nonce per encryption (NIST SP 800-38D recommended).
* 128-bit authentication tag (default for GCM).
* Master key is 32 bytes, base64-encoded in env: ``RA1_VAULT_MASTER_KEY``.
* HKDF-SHA256 is used to derive the per-context key (so we can rotate the
  master key without re-encrypting every record, and so a single key can be
  safely reused for distinct purposes if needed in the future).

On-disk format
--------------
A single base64 string holding the concatenation:
    [ 12-byte nonce ][ ciphertext + 16-byte GCM tag ]
"""

from __future__ import annotations

import base64
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

# ── Constants ────────────────────────────────────────────────────────────────

NONCE_SIZE:   Final[int] = 12   # bytes — 96 bits, recommended for GCM
TAG_SIZE:     Final[int] = 16   # bytes — 128 bits, GCM default
KEY_SIZE:     Final[int] = 32   # bytes — 256 bits

# Application-specific info string for HKDF. Changing this invalidates all
# previously encrypted data — only change it on a planned key migration.
_HKDF_INFO: Final[bytes] = b"ra1-vault/v1"

ENV_MASTER_KEY: Final[str] = "RA1_VAULT_MASTER_KEY"

# Placeholder key used ONLY when the master key is missing and the caller
# explicitly opts in (used in unit tests). Never enable in production.
_DEV_FALLBACK_KEY: Final[bytes] = b"\x00" * KEY_SIZE


# ── Errors ───────────────────────────────────────────────────────────────────


class CryptoError(Exception):
    """Base error for the crypto module."""


class MasterKeyMissingError(CryptoError):
    """Raised when ``RA1_VAULT_MASTER_KEY`` is not set and no override given."""


class DecryptionFailedError(CryptoError):
    """Raised when decryption fails (tampered ciphertext, wrong key, or bad
    encoding). Never include the underlying error message — that may leak
    information about the key/ciphertext in logs."""


# ── Key handling ─────────────────────────────────────────────────────────────


def _load_master_key(env: dict[str, str] | None = None) -> bytes:
    """Read and decode the master key from the environment.

    Accepts a custom ``env`` mapping for unit tests; defaults to ``os.environ``.
    """
    env_map = env if env is not None else os.environ
    raw = env_map.get(ENV_MASTER_KEY)
    if not raw:
        raise MasterKeyMissingError(
            f"{ENV_MASTER_KEY} is not set. Generate one with: "
            f"`openssl rand -base64 32` and put it in .env."
        )
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 — b64decode raises binascii.Error
        raise CryptoError(f"{ENV_MASTER_KEY} is not valid base64") from exc
    if len(decoded) != KEY_SIZE:
        raise CryptoError(
            f"{ENV_MASTER_KEY} must decode to exactly {KEY_SIZE} bytes "
            f"(got {len(decoded)})."
        )
    return decoded


def derive_key(master_key: bytes, context: str = "default") -> bytes:
    """Derive a 32-byte subkey from the master key using HKDF-SHA256.

    Different ``context`` strings yield cryptographically independent keys.
    """
    if len(master_key) != KEY_SIZE:
        raise CryptoError(f"master_key must be {KEY_SIZE} bytes")
    info = _HKDF_INFO + b":" + context.encode("utf-8")
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=None,
        info=info,
    )
    return kdf.derive(master_key)


# ── Encrypt / decrypt ───────────────────────────────────────────────────────


def encrypt(plaintext: str, key: bytes, *, associated_data: bytes | None = None) -> str:
    """Encrypt ``plaintext`` (str) under ``key`` and return a base64 string."""
    if not isinstance(plaintext, str):
        raise CryptoError("plaintext must be a str")
    if len(key) != KEY_SIZE:
        raise CryptoError(f"key must be {KEY_SIZE} bytes")

    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(ciphertext_b64: str, key: bytes, *, associated_data: bytes | None = None) -> str:
    """Decrypt a base64 string produced by :func:`encrypt`."""
    if not isinstance(ciphertext_b64, str):
        raise CryptoError("ciphertext_b64 must be a str")
    if len(key) != KEY_SIZE:
        raise CryptoError(f"key must be {KEY_SIZE} bytes")

    try:
        raw = base64.b64decode(ciphertext_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise DecryptionFailedError("invalid base64 ciphertext") from exc

    if len(raw) < NONCE_SIZE + TAG_SIZE:
        raise DecryptionFailedError("ciphertext too short")

    nonce, ct = raw[:NONCE_SIZE], raw[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ct, associated_data)
    except Exception as exc:  # noqa: BLE001 — InvalidTag etc.
        # Never expose the underlying exception to callers — it can leak
        # details about the key/tag mismatch.
        raise DecryptionFailedError("decryption failed") from exc
    return plaintext_bytes.decode("utf-8")


# ── Convenience: high-level helper used by the vault service ────────────────


def get_default_key(env: dict[str, str] | None = None) -> bytes:
    """Return the derived default-context key from the environment master key."""
    return derive_key(_load_master_key(env))


def encrypt_for_vault(plaintext: str, env: dict[str, str] | None = None) -> str:
    """Encrypt a vault value using the default derived key."""
    return encrypt(plaintext, get_default_key(env))


def decrypt_for_vault(ciphertext_b64: str, env: dict[str, str] | None = None) -> str:
    """Decrypt a vault value using the default derived key."""
    return decrypt(ciphertext_b64, get_default_key(env))
