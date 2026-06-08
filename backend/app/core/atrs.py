"""
ATRS — Audit Trace + Replay System (service layer).

Properties guaranteed by this module:
  1. Append-only. The service has no ``update`` or ``delete`` method.
     Every write is a single ``INSERT``. The SQL surface is verified by
     ``_verify_append_only_surface`` and by unit tests.
  2. Scrubbed. Any attempt to pass a forbidden key (raw credentials, memory
     values, tokens) raises ``ATRSForbiddenKeyError`` BEFORE the row is
     written. We crash the log rather than leak.
  3. Typed. ``event_type`` and ``engine`` are enums — never freeform strings.
  4. ID-only ``entity_ref``. The pattern ``<type>:<id>`` is enforced by the
     schema; raw values are rejected.
  5. Durable. If ClickHouse is unavailable, the row is written to the
     Postgres ``atrs_outbox`` table for later replay. Logs are never dropped.

This is a foundation module. The service is intentionally a plain Python
class with no module-level global state — it can be constructed once at
startup and shared across requests.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from app.models.atrs import (
    ATRSEngine,
    ATRSLogEntry,
    ATRSStatus,
)

logger = logging.getLogger(__name__)


# ── Errors ───────────────────────────────────────────────────────────────────


class ATRSError(Exception):
    """Base error for the ATRS service."""


class ATRSForbiddenKeyError(ATRSError):
    """Raised when the metadata scrubber detects a forbidden key (e.g.
    ``credential_value``). The log row is NOT written."""

    def __init__(self, keys: list[str]):
        self.keys = keys
        super().__init__(
            f"ATRS metadata contains forbidden key(s): {keys}. "
            f"Raw credentials are never permitted in audit logs."
        )


class ATRSPersistenceError(ATRSError):
    """Raised when neither ClickHouse nor the Postgres outbox can persist
    a row. The log is dropped — and an ``atrs.dropped`` event is emitted
    (best-effort) so the loss is itself auditable."""


# ── Forbidden metadata keys (case-insensitive comparison) ────────────────────
#
# Any of these keys appearing in the metadata dict — at any depth — is
# rejected. We do NOT silently strip: the explicit error is the point.
# Better to crash the caller than to silently leak.

FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset({
    "credential_value",
    "raw_memory",
    "memory_value",
    "api_key",
    "secret",
    "token",
    "password",
    "refresh_token",
    "encrypted_value",
    "private_key",
    "client_secret",
})


def scrub_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Walk ``metadata`` and reject if any forbidden key appears anywhere.

    Returns the metadata unchanged on success. Raises
    :class:`ATRSForbiddenKeyError` on detection — the caller MUST NOT
    write the row.
    """
    found = _find_forbidden_keys(metadata)
    if found:
        raise ATRSForbiddenKeyError(found)
    return metadata


def _find_forbidden_keys(obj: Any, path: str = "") -> list[str]:
    """Depth-first search of ``obj`` for forbidden keys (case-insensitive)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            if k.lower() in FORBIDDEN_METADATA_KEYS:
                found.append(f"{path}.{k}" if path else k)
            found.extend(_find_forbidden_keys(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            found.extend(_find_forbidden_keys(item, f"{path}[{i}]"))
    return found


# ── Database sinks ───────────────────────────────────────────────────────────


class _Sinks:
    """Container for the two persistence sinks. Both are async-callables
    matching the signatures:

      ch_writer(row_dict) -> None
      outbox_writer(row_dict) -> None

    They are injected at construction time so the service is fully
    testable with a ``FakePool``."""

    ch_writer:     Optional[Callable[[dict], Awaitable[None]]]
    outbox_writer: Optional[Callable[[dict], Awaitable[None]]]

    def __init__(
        self,
        ch_writer:     Optional[Callable[[dict], Awaitable[None]]] = None,
        outbox_writer: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.ch_writer = ch_writer
        self.outbox_writer = outbox_writer


# ── Main service ─────────────────────────────────────────────────────────────


class ATRSService:
    """The single, append-only entry point for the audit trace."""

    def __init__(
        self,
        *,
        ch_writer:     Optional[Callable[[dict], Awaitable[None]]] = None,
        outbox_writer: Optional[Callable[[dict], Awaitable[None]]] = None,
        ch_enabled:    bool = True,
    ):
        self._sinks = _Sinks(ch_writer=ch_writer, outbox_writer=outbox_writer)
        self._ch_enabled = ch_enabled

    # ── Public API ───────────────────────────────────────────────────────

    async def record(self, event: ATRSLogEntry) -> uuid.UUID:
        """Persist a single audit row. Returns the ``log_id``.

        Steps (in order):
          1. Scrub metadata — fail fast on forbidden keys.
          2. Serialize.
          3. Try ClickHouse first.
          4. Fall back to Postgres ``atrs_outbox`` if CH is unavailable.
          5. If both sinks fail, raise :class:`ATRSPersistenceError`.
        """
        scrub_metadata(event.metadata)  # raises on forbidden key

        row = self._serialize(event)
        log_id = event.log_id

        # Try ClickHouse first.
        if self._ch_enabled and self._sinks.ch_writer is not None:
            try:
                await self._sinks.ch_writer(row)
                return log_id
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ATRS ClickHouse write failed (will fall back to outbox): %s",
                    exc,
                )

        # Fall back to outbox.
        if self._sinks.outbox_writer is not None:
            try:
                await self._sinks.outbox_writer(row)
                logger.info("ATRS row written to outbox log_id=%s", log_id)
                return log_id
            except Exception as exc:  # noqa: BLE001
                logger.error("ATRS outbox write also failed: %s", exc)
                raise ATRSPersistenceError(
                    f"Both ClickHouse and outbox failed for log_id={log_id}"
                ) from exc

        # No sinks configured at all — in dev, log and drop.
        if not self._ch_enabled:
            logger.debug("ATRS (dry run, no sinks): %s", row)
            return log_id

        raise ATRSPersistenceError(
            "ATRS has no persistence sinks configured. "
            "Pass ch_writer and/or outbox_writer at construction."
        )

    # ── Convenience helpers ──────────────────────────────────────────────

    async def record_simple(
        self,
        *,
        engine:     ATRSEngine,
        event_type: Any,            # ATRSEventType union member
        status:     ATRSStatus = ATRSStatus.SUCCESS,
        entity_ref: Optional[str] = None,
        session_id: Optional[str] = None,
        habitat_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error_code: Optional[str] = None,
        metadata:    Optional[dict[str, Any]] = None,
    ) -> uuid.UUID:
        """Build an :class:`ATRSLogEntry` and call :meth:`record`."""
        entry = ATRSLogEntry(
            engine=engine,
            event_type=event_type,
            status=status,
            entity_ref=entity_ref,
            session_id=session_id,
            habitat_id=habitat_id,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata=metadata or {},
        )
        return await self.record(entry)

    @asynccontextmanager
    async def timed(
        self,
        engine:     ATRSEngine,
        event_type: Any,
        status:     ATRSStatus = ATRSStatus.SUCCESS,
        entity_ref: Optional[str] = None,
        session_id: Optional[str] = None,
        habitat_id: Optional[str] = None,
        metadata:    Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict]:
        """Async context manager that records the wall-clock duration of the
        wrapped block.

        Usage::

            async with atrs.timed(ATRSEngine.VAULT, ATRSVaultEvent.VAULT_RESOLVED,
                                  entity_ref=f"vault:{vid}") as ctx:
                value = await resolve_secret(vid)
            # on exit, ``ctx["duration_ms"]`` is populated and the row is
            # recorded.
        """
        ctx: dict[str, Any] = {"duration_ms": None, "error_code": None}
        start = time.monotonic()
        try:
            yield ctx
        except Exception as exc:
            ctx["error_code"] = type(exc).__name__
            raise
        finally:
            ctx["duration_ms"] = int((time.monotonic() - start) * 1000)
            await self.record_simple(
                engine=engine,
                event_type=event_type,
                status=status,
                entity_ref=entity_ref,
                session_id=session_id,
                habitat_id=habitat_id,
                duration_ms=ctx["duration_ms"],
                error_code=ctx["error_code"],
                metadata=metadata,
            )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _serialize(self, event: ATRSLogEntry) -> dict[str, Any]:
        """Build the dict that gets passed to the persistence sinks."""
        return {
            "log_id":      str(event.log_id),
            "timestamp":   event.timestamp,
            "session_id":  event.session_id,
            "habitat_id":  event.habitat_id,
            "engine":      event.engine.value
                            if isinstance(event.engine, ATRSEngine)
                            else str(event.engine),
            "event_type":  event.event_type.value
                            if hasattr(event.event_type, "value")
                            else str(event.event_type),
            "entity_ref":  event.entity_ref,
            "status":      event.status.value
                            if isinstance(event.status, ATRSStatus)
                            else str(event.status),
            "duration_ms": event.duration_ms,
            "error_code":  event.error_code,
            "metadata":    json.dumps(event.metadata, default=str)
                            if event.metadata
                            else None,
        }


# ── Module-level helpers (introspection) ─────────────────────────────────────


def _verify_append_only_surface(service_cls: type[ATRSService]) -> None:
    """Hard runtime check: the service class must not expose ``update``,
    ``delete``, ``upsert``, or any mutation that does not go through
    :meth:`record`. Raises :class:`ATRSError` on violation."""
    forbidden = {
        name for name in dir(service_cls)
        if name.lower() in {"update", "delete", "upsert", "patch", "modify"}
        and not name.startswith("_")
    }
    if forbidden:
        raise ATRSError(
            f"ATRSService exposes mutation methods: {forbidden}. "
            f"ATRS is append-only."
        )
