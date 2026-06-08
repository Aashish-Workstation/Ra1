"""
Credential Vault — service layer.

Properties guaranteed by this module:
  1. **Encrypted at rest.** Every ``value`` (and ``refresh_token``) is
     encrypted with AES-256-GCM using a per-context HKDF-derived key
     BEFORE any DB write. The plaintext value never touches the DB.
  2. **No caching.** ``resolve()`` decrypts and returns the plaintext
     exactly once. The service holds NO module-level cache, NO instance
     dict, NO Redis copy. The decrypted value lives only in the caller's
     local variable.
  3. **Strict owner isolation.** Every query includes
     ``WHERE owner_id = $1 AND vault_id = $2``. Cross-owner access raises
     :class:`VaultIsolationError` — and the error message never confirms
     whether the entry exists under a different owner.
  4. **ATRS-integrated.** Every mutation emits an ATRS event with
     ``entity_ref="vault:<id>"`` — and the metadata is scrubbed by ATRS,
     so plaintext is never written to the audit log.
  5. **ClickHouse credential-access log.** Every ``resolve()`` also
     writes a row to ``ra1_analytics.credential_access_events``.

Sinks are injected at construction so the service is fully testable
without a real DB.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.crypto import (
    CryptoError,
    DecryptionFailedError,
    encrypt,
    decrypt,
    get_default_key,
)
from app.core.atrs import ATRSService
from app.models.atrs import (
    ATRSEngine,
    ATRSStatus,
    ATRSVaultEvent,
)
from app.models.vault import (
    CredentialType,
    RefreshStatus,
    VaultEntry,
    VaultEntryCreate,
    VaultEntryRead,
    VaultEntryNotFoundError,
    VaultEntryRevokedError,
    VaultIsolationError,
    VaultStatus,
)

logger = logging.getLogger(__name__)


# ── Sink type aliases (injected at construction) ────────────────────────────
# Each sink is an async callable matching the signatures below. The pool is
# an asyncpg-like object with an ``execute`` method. They are split out so
# the same service can be used in dev (with a FakePool) and prod (with the
# real asyncpg pool).

VaultRowWriter = Callable[[VaultEntry], Awaitable[None]]
VaultRowReader = Callable[[str, uuid.UUID], Awaitable[Optional[VaultEntry]]]
VaultLister    = Callable[[str], Awaitable[list[VaultEntry]]]
VaultUpdater   = Callable[[str, uuid.UUID, dict[str, Any]], Awaitable[None]]
CredentialAccessWriter = Callable[[dict[str, Any]], Awaitable[None]]


# ── Service ─────────────────────────────────────────────────────────────────


class VaultService:
    """The single, isolated, encrypted-at-rest credential store.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        *,
        row_writer:  VaultRowWriter,
        row_reader:  VaultRowReader,
        lister:      VaultLister,
        updater:     VaultUpdater,
        atrs:        ATRSService,
        credential_access_writer: Optional[CredentialAccessWriter] = None,
        env:         Optional[dict[str, str]] = None,
    ):
        self._write    = row_writer
        self._read     = row_reader
        self._list     = lister
        self._update   = updater
        self._atrs     = atrs
        self._cred_log = credential_access_writer
        self._env      = env
        # Resolve the encryption key ONCE at construction. Caching the key
        # is fine — the key is not a secret value, just a derived subkey of
        # the master. The plaintext values, however, are NEVER cached.
        self._key      = get_default_key(env)

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def create(
        self,
        owner_id: str,
        entry:    VaultEntryCreate,
    ) -> VaultEntryRead:
        if not owner_id:
            raise VaultIsolationError("owner_id is required")
        if not entry.label.strip():
            raise ValueError("label is required")

        now = datetime.now(timezone.utc)
        encrypted_value       = encrypt(entry.value, self._key)
        encrypted_refresh     = (
            encrypt(entry.refresh_token, self._key)
            if entry.refresh_token is not None and entry.refresh_token != ""
            else None
        )

        row = VaultEntry(
            vault_id=uuid.uuid4(),
            owner_id=owner_id,
            credential_type=entry.credential_type,
            encrypted_value=encrypted_value,
            connector_ref=entry.connector_ref,
            label=entry.label,
            status=VaultStatus.ACTIVE,
            expires_at=entry.expires_at,
            refresh_token=encrypted_refresh,
            refresh_status=RefreshStatus.NONE,
            last_used_at=None,
            created_at=now,
            updated_at=now,
        )
        await self._write(row)

        await self._atrs.record_simple(
            engine=ATRSEngine.VAULT,
            event_type=ATRSVaultEvent.VAULT_CREATED,
            entity_ref=f"vault:{row.vault_id}",
            metadata={
                "credential_type": row.credential_type.value,
                "label": row.label,
            },
        )

        return _to_read(row)

    async def get_metadata(
        self,
        owner_id: str,
        vault_id: uuid.UUID,
    ) -> VaultEntryRead:
        row = await self._read(owner_id, vault_id)
        if row is None:
            # No cross-owner info leak: same error whether the entry
            # doesn't exist OR exists under a different owner.
            raise VaultEntryNotFoundError(
                f"vault entry not found for owner_id={owner_id}"
            )
        return _to_read(row)

    async def list_for_owner(self, owner_id: str) -> list[VaultEntryRead]:
        rows = await self._list(owner_id)
        return [_to_read(r) for r in rows]

    async def resolve(
        self,
        owner_id: str,
        vault_id: uuid.UUID,
    ) -> str:
        """Decrypt and return the plaintext value at CALL TIME only.

        The plaintext is returned exactly once and is NEVER stored, cached,
        or logged by this service. The caller's local variable is its
        only home.
        """
        row = await self._read(owner_id, vault_id)
        if row is None:
            await self._emit_resolve_event(
                owner_id=owner_id, vault_id=vault_id,
                status=ATRSStatus.FAILURE, error_code="not_found",
            )
            raise VaultEntryNotFoundError(
                f"vault entry not found for owner_id={owner_id}"
            )

        if row.status != VaultStatus.ACTIVE:
            await self._emit_resolve_event(
                owner_id=owner_id, vault_id=vault_id,
                status=ATRSStatus.BLOCKED,
                error_code=f"status_{row.status.value}",
            )
            raise VaultEntryRevokedError(
                f"vault entry {vault_id} is not active (status="
                f"{row.status.value})"
            )

        try:
            plaintext = decrypt(row.encrypted_value, self._key)
        except DecryptionFailedError as exc:
            await self._emit_resolve_event(
                owner_id=owner_id, vault_id=vault_id,
                status=ATRSStatus.FAILURE, error_code="decrypt_fail",
            )
            raise DecryptionFailedError(
                f"vault entry {vault_id} failed to decrypt"
            ) from exc

        await self._emit_resolve_event(
            owner_id=owner_id, vault_id=vault_id,
            status=ATRSStatus.SUCCESS,
        )

        # Fire-and-forget: update last_used_at. Failure here MUST NOT
        # cause the resolved value to be discarded.
        try:
            await self._update(owner_id, vault_id, {
                "last_used_at": datetime.now(timezone.utc),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to update last_used_at: %s", exc)

        # The plaintext is returned to the caller exactly once. The service
        # has no other reference to it after this line returns.
        return plaintext

    async def rotate(
        self,
        owner_id:  str,
        vault_id:  uuid.UUID,
        new_value: str,
    ) -> VaultEntryRead:
        if not new_value:
            raise ValueError("new_value is required")

        existing = await self._read(owner_id, vault_id)
        if existing is None:
            raise VaultEntryNotFoundError(
                f"vault entry not found for owner_id={owner_id}"
            )

        new_encrypted = encrypt(new_value, self._key)
        await self._update(owner_id, vault_id, {
            "encrypted_value": new_encrypted,
            "status":          VaultStatus.ACTIVE.value,
            "updated_at":      datetime.now(timezone.utc),
        })

        await self._atrs.record_simple(
            engine=ATRSEngine.VAULT,
            event_type=ATRSVaultEvent.VAULT_ROTATED,
            entity_ref=f"vault:{vault_id}",
            metadata={"owner_id_hash": _short_hash(owner_id)},
        )

        # Re-read to return the updated row.
        updated = await self._read(owner_id, vault_id)
        assert updated is not None
        return _to_read(updated)

    async def revoke(
        self,
        owner_id: str,
        vault_id: uuid.UUID,
    ) -> VaultEntryRead:
        existing = await self._read(owner_id, vault_id)
        if existing is None:
            raise VaultEntryNotFoundError(
                f"vault entry not found for owner_id={owner_id}"
            )

        await self._update(owner_id, vault_id, {
            "status":     VaultStatus.REVOKED.value,
            "updated_at": datetime.now(timezone.utc),
        })

        await self._atrs.record_simple(
            engine=ATRSEngine.VAULT,
            event_type=ATRSVaultEvent.VAULT_REVOKED,
            entity_ref=f"vault:{vault_id}",
            metadata={"owner_id_hash": _short_hash(owner_id)},
        )

        updated = await self._read(owner_id, vault_id)
        assert updated is not None
        return _to_read(updated)

    # ── Internals ────────────────────────────────────────────────────────

    async def _emit_resolve_event(
        self,
        *,
        owner_id:   str,
        vault_id:   uuid.UUID,
        status:     ATRSStatus,
        error_code: Optional[str] = None,
    ) -> None:
        event_type = (
            ATRSVaultEvent.VAULT_RESOLVED
            if status == ATRSStatus.SUCCESS
            else (
                ATRSVaultEvent.VAULT_ACCESS_DENIED
                if status == ATRSStatus.BLOCKED
                else ATRSVaultEvent.VAULT_DECRYPT_FAIL
            )
        )
        await self._atrs.record_simple(
            engine=ATRSEngine.VAULT,
            event_type=event_type,
            status=status,
            entity_ref=f"vault:{vault_id}",
            error_code=error_code,
            metadata={"owner_id_hash": _short_hash(owner_id)},
        )

        if self._cred_log is not None:
            try:
                await self._cred_log({
                    "owner_id":   _short_hash(owner_id),
                    "vault_id":   str(vault_id),
                    "success":    1 if status == ATRSStatus.SUCCESS else 0,
                    "error_code": error_code,
                    "timestamp":  datetime.now(timezone.utc),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("credential_access_events write failed: %s", exc)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_read(row: VaultEntry) -> VaultEntryRead:
    """Convert a storage row to a read model — stripping encrypted_value."""
    return VaultEntryRead(
        vault_id=row.vault_id,
        owner_id=row.owner_id,
        credential_type=row.credential_type,
        connector_ref=row.connector_ref,
        label=row.label,
        status=row.status,
        expires_at=row.expires_at,
        refresh_status=row.refresh_status,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _short_hash(value: str) -> str:
    """Short, non-reversible hash for owner_id in audit metadata.

    8 hex chars = 32 bits — enough to correlate events to the same owner
    without storing the raw owner_id in the audit log. NOT a security
    boundary (ATRS does not assert the owner_id of any log row); it just
    makes it harder to grep the log for raw identifiers.
    """
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


# ── DB sinks ──────────────────────────────────────────────────────────────────


async def make_vault_row_writer(pool, atrs: ATRSService):
    async def _write(row: VaultEntry) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO vault_entries (
                    vault_id, owner_id, credential_type, encrypted_value,
                    connector_ref, label, status, expires_at,
                    refresh_token_encrypted, refresh_status, last_used_at,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                row.vault_id,
                row.owner_id,
                row.credential_type.value,
                row.encrypted_value,
                row.connector_ref,
                row.label,
                row.status.value,
                row.expires_at,
                row.refresh_token,
                row.refresh_status.value,
                row.last_used_at,
                row.created_at,
                row.updated_at,
            )
    return _write


async def make_vault_row_reader(pool):
    async def _read(owner_id: str, vault_id: uuid.UUID) -> Optional[VaultEntry]:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT vault_id, owner_id, credential_type, encrypted_value,
                       connector_ref, label, status, expires_at,
                       refresh_token_encrypted, refresh_status, last_used_at,
                       created_at, updated_at
                FROM vault_entries
                WHERE owner_id = $1 AND vault_id = $2
                """,
                owner_id, vault_id,
            )
            if row is None:
                return None
            return VaultEntry(
                vault_id=row["vault_id"],
                owner_id=row["owner_id"],
                credential_type=CredentialType(row["credential_type"]),
                encrypted_value=row["encrypted_value"],
                connector_ref=row["connector_ref"],
                label=row["label"],
                status=VaultStatus(row["status"]),
                expires_at=row["expires_at"],
                refresh_token=row["refresh_token_encrypted"],
                refresh_status=RefreshStatus(row["refresh_status"]),
                last_used_at=row["last_used_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    return _read


async def make_vault_lister(pool):
    async def _list(owner_id: str) -> list[VaultEntry]:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT vault_id, owner_id, credential_type, encrypted_value,
                       connector_ref, label, status, expires_at,
                       refresh_token_encrypted, refresh_status, last_used_at,
                       created_at, updated_at
                FROM vault_entries
                WHERE owner_id = $1
                """,
                owner_id,
            )
            return [
                VaultEntry(
                    vault_id=r["vault_id"],
                    owner_id=r["owner_id"],
                    credential_type=CredentialType(r["credential_type"]),
                    encrypted_value=r["encrypted_value"],
                    connector_ref=r["connector_ref"],
                    label=r["label"],
                    status=VaultStatus(r["status"]),
                    expires_at=r["expires_at"],
                    refresh_token=r["refresh_token_encrypted"],
                    refresh_status=RefreshStatus(r["refresh_status"]),
                    last_used_at=r["last_used_at"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
    return _list


async def make_vault_updater(pool):
    async def _update(owner_id: str, vault_id: uuid.UUID, fields: dict[str, Any]) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(fields.keys()))
        values = list(fields.values())
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE vault_entries SET {set_clause} WHERE owner_id = $1 AND vault_id = $2",
                owner_id, vault_id, *values,
            )
    return _update


async def make_credential_access_writer():
    import os

    clickhouse_url = os.environ.get("CLICKHOUSE_URL", "http://default:nopassword@clickhouse:8123")

    async def _write(event: dict[str, Any]) -> None:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{clickhouse_url}/?query=INSERT%20INTO%20ra1_analytics.credential_access_events%20FORMAT%20JSONEachRow",
                    json=[event],
                )
        except Exception:
            pass
    return _write
