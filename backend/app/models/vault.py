"""
Credential Vault — Pydantic schemas + enums.

Three model kinds:
  * ``VaultEntry``       — full storage model (includes encrypted_value).
  * ``VaultEntryCreate`` — input from API/service callers. Accepts plaintext;
                          the service encrypts before persisting.
  * ``VaultEntryRead``   — output to API/service callers. NEVER exposes the
                          encrypted value.

Owner isolation is enforced in code (every query joins on owner_id) AND in
the schema (UNIQUE constraint on (owner_id, label) in SQL).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class CredentialType(str, Enum):
    OAUTH_TOKEN     = "oauth_token"
    API_KEY         = "api_key"
    MODEL_API_KEY   = "model_api_key"
    WEBHOOK_SECRET  = "webhook_secret"
    SERVICE_ACCOUNT = "service_account"
    CUSTOM          = "custom"


class VaultStatus(str, Enum):
    ACTIVE  = "active"
    ROTATED = "rotated"
    REVOKED = "revoked"
    EXPIRED = "expired"


class RefreshStatus(str, Enum):
    NONE    = "none"
    PENDING = "pending"
    SUCCESS = "success"
    FAILED  = "failed"


# ── Storage model ────────────────────────────────────────────────────────────


class VaultEntry(BaseModel):
    """Full row as stored in ``vault_entries``. ``encrypted_value`` is a
    base64-encoded AES-256-GCM ciphertext (nonce || ct || tag)."""
    model_config = ConfigDict(extra="forbid")

    vault_id:                uuid.UUID
    owner_id:                str
    credential_type:         CredentialType
    encrypted_value:         str
    connector_ref:           Optional[str] = None
    label:                   str
    status:                  VaultStatus          = VaultStatus.ACTIVE
    expires_at:              Optional[datetime]   = None
    refresh_token:           Optional[str]        = None  # stored as encrypted
    refresh_status:          RefreshStatus        = RefreshStatus.NONE
    last_used_at:            Optional[datetime]   = None
    created_at:              datetime            = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at:              datetime            = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Input model (plaintext allowed here) ─────────────────────────────────────


class VaultEntryCreate(BaseModel):
    """Input for creating a new vault entry. The service encrypts
    ``value`` (and ``refresh_token``) before persisting."""
    model_config = ConfigDict(extra="forbid")

    credential_type:  CredentialType
    label:            str             = Field(min_length=1, max_length=255)
    value:            str             = Field(min_length=1)
    connector_ref:    Optional[str]   = None
    expires_at:       Optional[datetime] = None
    refresh_token:    Optional[str]   = None


# ── Output model (never exposes encrypted_value) ────────────────────────────


class VaultEntryRead(BaseModel):
    """Output of all read operations. ``encrypted_value`` is intentionally
    absent — the encrypted blob is an internal detail."""
    model_config = ConfigDict(extra="forbid")

    vault_id:        uuid.UUID
    owner_id:        str
    credential_type: CredentialType
    connector_ref:   Optional[str]
    label:           str
    status:          VaultStatus
    expires_at:      Optional[datetime]
    refresh_status:  RefreshStatus
    last_used_at:    Optional[datetime]
    created_at:      datetime
    updated_at:      datetime


# ── Errors raised by the service layer ───────────────────────────────────────


class VaultIsolationError(Exception):
    """Raised when a vault operation is attempted on an entry that does not
    belong to the supplied owner_id. The error message NEVER reveals whether
    the entry exists under a different owner."""


class VaultEntryNotFoundError(Exception):
    """Raised when ``get_metadata`` / ``resolve`` / etc. cannot find a row
    matching (owner_id, vault_id)."""


class VaultEntryRevokedError(Exception):
    """Raised when a resolve is attempted on an entry whose status is not
    ACTIVE (e.g. REVOKED, EXPIRED)."""
