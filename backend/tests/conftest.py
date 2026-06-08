"""
Test fixtures for the RA1 backend.

We avoid spinning up a real Postgres / ClickHouse for unit tests. Instead
we provide:

* ``FakePool`` — an in-memory asyncpg-shaped pool. Captures every SQL
  statement and its params, returns canned rows from per-table storage.

* ``fake_atrs_sink`` — a list that captures every row passed to the ATRS
  ClickHouse writer.

* ``make_atrs`` / ``make_vault`` — convenience builders that wire the
  fakes together into real ``ATRSService`` and ``VaultService`` instances.

* ``master_key`` — a 32-byte base64 master key for the vault.

Tests are run with ``pytest`` + ``pytest-asyncio`` (auto mode).
"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio  # noqa: F401  — ensures plugin loads

from app.core.atrs import ATRSService
from app.core.crypto import KEY_SIZE
from app.models.vault import (
    CredentialType,
    RefreshStatus,
    VaultEntry,
    VaultStatus,
)
from app.models.notification import NotificationRead, NotificationPriority, NotificationStatus
from app.models.memory import (
    KnowledgeLane,
    KnowledgeType,
    MemoryRecord,
    MemorySource,
)
from app.services.vault import (
    VaultLister,
    VaultRowReader,
    VaultRowWriter,
    VaultService,
    VaultUpdater,
)


# ── FakePool: in-memory asyncpg-shaped connection pool ──────────────────────


class FakePool:
    """Minimal in-memory pool with an asyncpg-like API."""

    def __init__(self) -> None:
        # {table_name: {pk_value: row_dict}}
        self.tables: dict[str, dict[Any, dict]] = {
            "vault_entries": {},
            "atrs_outbox":   {},
            "memory_records": {},
            "personas":      {},
            "knowledge_items": {},
            "notifications": {},
            "recommendations": {},
        }
        # History of every execute() call — useful for assertions in tests.
        self.history: list[dict] = []
        # Hook for tests: if set, execute() will raise this exception.
        self.raise_on_execute: Optional[BaseException] = None
        # Hook for tests: if set, execute() for matching table raises.
        self.raise_on_table: dict[str, BaseException] = {}

    # ── API surface used by the services ──────────────────────────────────

    async def execute(self, query: str, *args: Any) -> str:
        if self.raise_on_execute is not None:
            raise self.raise_on_execute

        sql_norm = " ".join(query.split()).lower()
        self.history.append({"query": sql_norm, "args": args})

        for table, exc in list(self.raise_on_table.items()):
            if sql_norm.startswith(f"insert into {table}"):
                raise exc

        if sql_norm.startswith("insert into vault_entries"):
            return self._insert_vault(args)
        if sql_norm.startswith("select") and "from vault_entries" in sql_norm:
            if "vault_id = $2" in sql_norm:
                return self._select_vault_by_owner_and_id(args)
            if "owner_id = $1" in sql_norm:
                return self._select_vault_by_owner(args)
        if sql_norm.startswith("update vault_entries"):
            return self._update_vault(args)
        if sql_norm.startswith("insert into atrs_outbox"):
            return self._insert_outbox(args)
        if "insert into ra1_analytics.audit_trace" in sql_norm:
            return "OK"
        if "insert into ra1_analytics.credential_access_events" in sql_norm:
            return "OK"
        if sql_norm.startswith("insert into memory_records"):
            return self._insert_memory(args)
        if sql_norm.startswith("select") and "from memory_records" in sql_norm:
            if "user_id = $1" in sql_norm and "habitat_id = $2" in sql_norm:
                return self._select_memory_by_scope(args)
        if sql_norm.startswith("update memory_records"):
            return self._update_memory(args)
        if sql_norm.startswith("insert into personas"):
            return self._insert_persona(args)
        if sql_norm.startswith("select") and "from personas" in sql_norm:
            return self._select_personas(args)
        if sql_norm.startswith("insert into knowledge_items"):
            return self._insert_knowledge(args)
        if sql_norm.startswith("select") and "from knowledge_items" in sql_norm:
            return self._select_knowledge(args)
        if sql_norm.startswith("insert into notifications"):
            return self._insert_notification(args)
        if sql_norm.startswith("select") and "from notifications" in sql_norm:
            return self._select_notifications(args)
        if sql_norm.startswith("update notifications"):
            return self._update_notification(args)
        if sql_norm.startswith("insert into recommendations"):
            return self._insert_recommendation(args)
        if sql_norm.startswith("select") and "from recommendations" in sql_norm:
            return self._select_recommendations(args)
        if sql_norm.startswith("update recommendations"):
            return self._update_recommendation(args)

        raise NotImplementedError(
            f"FakePool does not know how to handle: {sql_norm[:120]}"
        )

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        return []

    async def fetchrow(self, query: str, *args: Any) -> Optional[dict]:
        return None

    # ── Handlers (intentionally simple: they reverse-engineer the exact
    #    param order the services emit). If the service SQL changes, these
    #    need to change in lockstep. ──────────────────────────────────────

    def _insert_vault(self, args: tuple) -> str:
        row = {
            "vault_id":        str(args[0]),
            "owner_id":        args[1],
            "credential_type": args[2],
            "encrypted_value": args[3],
            "connector_ref":   args[4],
            "label":           args[5],
            "status":          args[6],
            "expires_at":      args[7],
            "refresh_token":   args[8],
            "refresh_status":  args[9],
            "last_used_at":    args[10],
            "created_at":      args[11],
            "updated_at":      args[12],
        }
        self.tables["vault_entries"][row["vault_id"]] = row
        return "INSERT 0 1"

    def _select_vault_by_owner_and_id(self, args: tuple) -> str:
        owner_id, vault_id = args[0], str(args[1])
        for vid, row in self.tables["vault_entries"].items():
            if row["owner_id"] == owner_id and vid == vault_id:
                # asyncpg returns 'INSERT 0 1' from execute; we simulate
                # the same for SELECT-by-id which the service uses.
                return "SELECT 1"
        return "SELECT 0"

    def _select_vault_by_owner(self, args: tuple) -> str:
        # Not used by these services in their current form — placeholder.
        return "SELECT 0"

    def _update_vault(self, args: tuple) -> str:
        # The service uses an UPDATE statement with a variable parameter
        # order depending on the fields. We rely on the trailing
        # (owner_id, vault_id) for routing.
        # The actual column-to-arg mapping is handled in ``_do_update``.
        return self._do_update(args)

    def _do_update(self, args: tuple) -> str:
        # Last two args are always (owner_id, vault_id).
        owner_id, vault_id = args[-2], str(args[-1])
        for vid, row in self.tables["vault_entries"].items():
            if row["owner_id"] == owner_id and vid == vault_id:
                # Apply known field updates by inspecting the args. The
                # service sends a fixed shape per update, so we map by
                # inspecting types.
                # Update 1: last_used_at (single datetime)
                # Update 2: encrypted_value, status, updated_at
                # Update 3: status, updated_at
                for a in args[:-2]:
                    if hasattr(a, "isoformat") and not isinstance(a, bool):
                        # Could be a datetime. Determine which slot.
                        if row.get("last_used_at") is None or isinstance(row.get("last_used_at"), type(a)):
                            row["last_used_at"] = a
                            break
                # Brute-force: rebuild by name using the known shapes below.
                return self._apply_named_update(row, args[:-2])
        return "UPDATE 0"

    def _apply_named_update(self, row: dict, fields: tuple) -> str:
        """Apply a fixed-shape update tuple to ``row`` in place.

        The vault service makes only three update shapes:

        1. ``(last_used_at,)``  — fire-and-forget after resolve
        2. ``(encrypted_value, status, updated_at)``  — rotate
        3. ``(status, updated_at)``  — revoke
        """
        n = len(fields)
        if n == 1:
            row["last_used_at"] = fields[0]
        elif n == 3 and isinstance(fields[0], str) and len(fields[0]) > 30:
            # encrypted_value, status, updated_at
            row["encrypted_value"] = fields[0]
            row["status"]         = fields[1]
            row["updated_at"]     = fields[2]
        elif n == 2:
            # status, updated_at
            row["status"]     = fields[0]
            row["updated_at"] = fields[1]
        return "UPDATE 1"

    def _insert_outbox(self, args: tuple) -> str:
        outbox_id = len(self.tables["atrs_outbox"]) + 1
        self.tables["atrs_outbox"][outbox_id] = {
            "outbox_id":  outbox_id,
            "payload":    args[0],
            "created_at": args[1] if len(args) > 1 else None,
        }
        return "INSERT 0 1"

    def _insert_memory(self, args: tuple) -> str:
        row = {
            "entity_id":    str(args[0]),
            "habitat_id":   str(args[1]),
            "user_id":      str(args[2]),
            "entity_type":  args[3],
            "attribute":    args[4],
            "value":        args[5],
            "knowledge_type": args[6],
            "confidence":   args[7],
            "source":       args[8],
            "provenance":   args[9],
            "ttl":          args[10],
            "lock_status":  args[11],
            "links":        args[12],
            "created_at":   args[13],
            "updated_at":   args[14],
        }
        self.tables["memory_records"][row["entity_id"]] = row
        return "INSERT 0 1"

    def _select_memory_by_scope(self, args: tuple) -> str:
        user_id, habitat_id = str(args[0]), str(args[1])
        return [
            _row_to_memory(r)
            for r in self.tables["memory_records"].values()
            if r["user_id"] == user_id and r["habitat_id"] == habitat_id
        ]

    def _update_memory(self, args: tuple) -> str:
        user_id, habitat_id, entity_id = str(args[-3]), str(args[-2]), str(args[-1])
        for eid, row in self.tables["memory_records"].items():
            if row["entity_id"] == entity_id and row["user_id"] == user_id and row["habitat_id"] == habitat_id:
                for key, val in args[-4].items():
                    row[key] = val
                row["updated_at"] = datetime.now(timezone.utc)
                return "UPDATE 1"
        return "UPDATE 0"

    def _insert_persona(self, args: tuple) -> str:
        row = {
            "persona_id": str(args[0]),
            "user_id": str(args[1]),
            "habitat_id": args[2],
            "name": args[3],
            "profession": args[4],
            "industry": args[5],
            "archetype_blend": args[6],
            "tone_rules": args[7],
            "rules": args[8],
            "scope": args[9],
            "created_at": args[10],
            "updated_at": args[11],
        }
        self.tables["personas"][row["persona_id"]] = row
        return "INSERT 0 1"

    def _select_personas(self, args: tuple) -> list:
        user_id = str(args[0])
        habitat_id = args[1]
        results = []
        for p in self.tables["personas"].values():
            if p["user_id"] == user_id:
                if habitat_id is None or p["habitat_id"] == habitat_id or p["habitat_id"] is None:
                    results.append(p)
        return results

    def _insert_knowledge(self, args: tuple) -> str:
        row = {
            "item_id": str(args[0]),
            "user_id": str(args[1]),
            "habitat_id": str(args[2]),
            "content_type": args[3],
            "content": args[4],
            "tags": args[5],
            "collections": args[6],
            "created_at": args[7],
            "updated_at": args[8],
        }
        self.tables["knowledge_items"][row["item_id"]] = row
        return "INSERT 0 1"

    def _select_knowledge(self, args: tuple) -> list:
        user_id = str(args[0])
        habitat_id = str(args[1])
        return [
            r for r in self.tables["knowledge_items"].values()
            if r["user_id"] == user_id and r["habitat_id"] == habitat_id
        ]

    def _insert_notification(self, args: tuple) -> str:
        row = {
            "notification_id": str(args[0]),
            "user_id": str(args[1]),
            "habitat_id": args[2],
            "priority": args[3] if isinstance(args[3], str) else args[3].value,
            "source_engine": args[4],
            "title": args[5],
            "message": args[6],
            "status": args[7] if isinstance(args[7], str) else args[7].value,
            "created_at": args[8],
        }
        self.tables["notifications"][row["notification_id"]] = row
        return "INSERT 0 1"

    def _select_notifications(self, args: tuple) -> list:
        user_id = str(args[0])
        return [
            _row_to_notification(r)
            for r in self.tables["notifications"].values()
            if r["user_id"] == user_id
        ]

    def _update_notification(self, args: tuple) -> str:
        fields = args[0]
        notification_id = str(args[1])
        for nid, row in self.tables["notifications"].items():
            if nid == notification_id:
                for key, val in fields.items():
                    row[key] = val.value if hasattr(val, "value") else str(val) if isinstance(val, NotificationStatus) else val
                return "UPDATE 1"
        return "UPDATE 0"

    def _insert_recommendation(self, args: tuple) -> str:
        row = {
            "recommendation_id": str(args[0]),
            "user_id": str(args[1]),
            "habitat_id": args[2],
            "domain": args[3],
            "suggestion_text": args[4],
            "trigger_context": args[5],
            "status": args[6],
            "created_at": args[7],
        }
        self.tables["recommendations"][row["recommendation_id"]] = row
        return "INSERT 0 1"

    def _select_recommendations(self, args: tuple) -> list:
        user_id = str(args[0])
        return [
            _row_to_recommendation(r)
            for r in self.tables["recommendations"].values()
            if r["user_id"] == user_id
        ]

    def _update_recommendation(self, args: tuple) -> str:
        fields = args[0]
        recommendation_id = str(args[1])
        for rid, row in self.tables["recommendations"].items():
            if rid == recommendation_id:
                for key, val in fields.items():
                    row[key] = val.value if hasattr(val, "value") else val
                return "UPDATE 1"
        return "UPDATE 0"


# ── Fixture: master key (32 random bytes, base64-encoded) ───────────────────


@pytest.fixture
def master_key_env() -> dict[str, str]:
    """A 32-byte base64-encoded master key, fresh per test."""
    raw = os.urandom(KEY_SIZE)
    return {"RA1_VAULT_MASTER_KEY": base64.b64encode(raw).decode("ascii")}


# ── Fixture: captured ATRS rows ─────────────────────────────────────────────


@pytest.fixture
def atrs_captured_rows() -> list[dict]:
    """List that the ATRS ClickHouse writer will append to."""
    return []


@pytest.fixture
def make_atrs(master_key_env: dict[str, str], atrs_captured_rows: list):
    """Build an ATRSService configured with in-memory sinks.

    Returns a tuple ``(service, captured_rows, outbox)`` where
    ``outbox`` is a list of rows written to the Postgres outbox fallback.
    """
    outbox: list[dict] = []

    async def ch_writer(row: dict) -> None:
        atrs_captured_rows.append(row)

    async def outbox_writer(row: dict) -> None:
        outbox.append(row)

    service = ATRSService(
        ch_writer=ch_writer,
        outbox_writer=outbox_writer,
        ch_enabled=True,
    )
    return service, atrs_captured_rows, outbox


# ── Fixture: Vault service backed by FakePool ───────────────────────────────


@pytest.fixture
def make_vault(master_key_env: dict[str, str], make_atrs):
    """Build a VaultService backed by a ``FakePool``.

    Returns ``(service, pool, atrs_rows, outbox)``.
    """
    pool = FakePool()
    atrs_service, atrs_rows, outbox = make_atrs

    # Adapter: turn the FakePool execute() into the row_writer/row_reader/
    # lister/updater interface the vault service expects.

    async def row_writer(row: VaultEntry) -> None:
        await pool.execute(
            """
            INSERT INTO vault_entries (
                vault_id, owner_id, credential_type, encrypted_value,
                connector_ref, label, status, expires_at, refresh_token_encrypted,
                refresh_status, last_used_at, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            """,
            str(row.vault_id), row.owner_id, row.credential_type.value,
            row.encrypted_value, row.connector_ref, row.label,
            row.status.value, row.expires_at, row.refresh_token,
            row.refresh_status.value, row.last_used_at,
            row.created_at, row.updated_at,
        )

    async def row_reader(owner_id: str, vault_id: uuid.UUID) -> Optional[VaultEntry]:
        await pool.execute(
            "SELECT 1 FROM vault_entries WHERE owner_id = $1 AND vault_id = $2",
            owner_id, str(vault_id),
        )
        raw_row = pool.tables["vault_entries"].get(str(vault_id))
        if raw_row is None or raw_row["owner_id"] != owner_id:
            return None
        return _row_to_entry(raw_row)

    async def lister(owner_id: str) -> list[VaultEntry]:
        return [
            _row_to_entry(r)
            for r in pool.tables["vault_entries"].values()
            if r["owner_id"] == owner_id
        ]

    async def updater(owner_id: str, vault_id: uuid.UUID, fields: dict) -> None:
        # Translate the dict into a positional UPDATE matching the
        # _apply_named_update logic in FakePool.
        if set(fields.keys()) == {"last_used_at"}:
            args = (fields["last_used_at"], owner_id, str(vault_id))
        elif set(fields.keys()) == {"encrypted_value", "status", "updated_at"}:
            args = (fields["encrypted_value"], fields["status"].value
                    if hasattr(fields["status"], "value") else fields["status"],
                    fields["updated_at"], owner_id, str(vault_id))
        elif set(fields.keys()) == {"status", "updated_at"}:
            args = (fields["status"].value
                    if hasattr(fields["status"], "value") else fields["status"],
                    fields["updated_at"], owner_id, str(vault_id))
        else:
            raise NotImplementedError(f"Unknown update shape: {fields.keys()}")
        await pool.execute(
            "UPDATE vault_entries SET ... WHERE owner_id = $N AND vault_id = $N+1",
            *args,
        )

    async def cred_log_writer(_row: dict) -> None:
        # Capture into a no-op list — assertions can introspect if needed.
        pass

    service = VaultService(
        row_writer=row_writer,
        row_reader=row_reader,
        lister=lister,
        updater=updater,
        atrs=atrs_service,
        credential_access_writer=cred_log_writer,
        env=master_key_env,
    )
    return service, pool, atrs_rows, outbox


# ── Fixture: Memory Engine service backed by FakePool ──────────────────────────


@pytest.fixture
def make_memory(make_atrs):
    """Build a MemoryEngineService backed by a ``FakePool``."""
    pool = FakePool()
    atrs_service, atrs_rows, outbox = make_atrs

    async def memory_writer(row: MemoryRecord) -> None:
        await pool.execute(
            """
            INSERT INTO memory_records (
                entity_id, habitat_id, user_id, entity_type, attribute,
                value, knowledge_type, confidence, source, provenance,
                ttl, lock_status, links, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            """,
            str(row.entity_id), str(row.habitat_id), str(row.user_id),
            row.entity_type, row.attribute, row.value,
            row.knowledge_type.value, row.confidence, row.source.value,
            row.provenance, row.ttl, row.lock_status, row.links,
            row.created_at, row.updated_at,
        )

    async def memory_reader(user_id: uuid.UUID, habitat_id: uuid.UUID, entity_id: uuid.UUID) -> Optional[MemoryRecord]:
        await pool.execute(
            "SELECT 1 FROM memory_records WHERE user_id = $1 AND habitat_id = $2 AND entity_id = $3",
            str(user_id), str(habitat_id), str(entity_id),
        )
        raw_row = pool.tables["memory_records"].get(str(entity_id))
        if raw_row is None:
            return None
        return _row_to_memory(raw_row)

    async def lister(user_id: uuid.UUID, habitat_id: uuid.UUID) -> list[MemoryRecord]:
        return [
            _row_to_memory(r)
            for r in pool.tables["memory_records"].values()
            if r["user_id"] == str(user_id) and r["habitat_id"] == str(habitat_id)
        ]

    async def updater(user_id: uuid.UUID, habitat_id: uuid.UUID, entity_id: uuid.UUID, fields: dict) -> None:
        await pool.execute(
            "UPDATE memory_records SET ... WHERE user_id = $1 AND habitat_id = $2 AND entity_id = $3",
            str(user_id), str(habitat_id), str(entity_id), **fields
        )

    async def conflict_writer(row: dict) -> None:
        pass

    from app.services.memory_engine import MemoryEngineService
    service = MemoryEngineService(
        row_writer=memory_writer,
        row_reader=memory_reader,
        lister=lister,
        updater=updater,
        atrs=atrs_service,
        conflict_writer=conflict_writer,
    )
    return service, pool, atrs_rows, outbox


# ── Helpers ──────────────────────────────────────────────────────────────────


def _row_to_entry(raw: dict) -> VaultEntry:
    return VaultEntry(
        vault_id=uuid.UUID(raw["vault_id"]),
        owner_id=raw["owner_id"],
        credential_type=CredentialType(raw["credential_type"]),
        encrypted_value=raw["encrypted_value"],
        connector_ref=raw["connector_ref"],
        label=raw["label"],
        status=VaultStatus(raw["status"]),
        expires_at=raw["expires_at"],
        refresh_token=raw["refresh_token"],
        refresh_status=RefreshStatus(raw["refresh_status"]),
        last_used_at=raw["last_used_at"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


def _row_to_memory(raw: dict) -> MemoryRecord:
    return MemoryRecord(
        entity_id=uuid.UUID(raw["entity_id"]),
        habitat_id=uuid.UUID(raw["habitat_id"]),
        user_id=uuid.UUID(raw["user_id"]),
        entity_type=raw["entity_type"],
        attribute=raw["attribute"],
        value=raw["value"],
        knowledge_type=KnowledgeType(raw["knowledge_type"]),
        confidence=raw["confidence"],
        source=MemorySource(raw["source"]),
        provenance=raw["provenance"],
        ttl=raw["ttl"],
        lock_status=raw["lock_status"],
        links=raw["links"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


# ── Helpers for Notification and Recommendation ───────────────────────────────


def _row_to_notification(raw: dict):
    from app.models.notification import NotificationRead, NotificationPriority, NotificationStatus
    return NotificationRead(
        notification_id=uuid.UUID(raw["notification_id"]),
        user_id=uuid.UUID(raw["user_id"]),
        habitat_id=uuid.UUID(raw["habitat_id"]) if raw.get("habitat_id") else None,
        priority=raw["priority"] if isinstance(raw["priority"], NotificationPriority) else NotificationPriority(raw["priority"]),
        source_engine=raw["source_engine"],
        title=raw["title"],
        message=raw["message"],
        status=raw["status"] if isinstance(raw["status"], NotificationStatus) else NotificationStatus(raw["status"]),
        created_at=raw["created_at"],
    )


def _row_to_recommendation(raw: dict):
    from app.models.recommender import RecommendationRead, RecommendationDomain, RecommendationStatus
    return RecommendationRead(
        recommendation_id=uuid.UUID(raw["recommendation_id"]),
        user_id=uuid.UUID(raw["user_id"]),
        habitat_id=uuid.UUID(raw["habitat_id"]) if raw.get("habitat_id") else None,
        domain=raw["domain"] if isinstance(raw["domain"], RecommendationDomain) else RecommendationDomain(raw["domain"]),
        suggestion_text=raw["suggestion_text"],
        trigger_context=raw["trigger_context"],
        status=raw["status"] if isinstance(raw["status"], RecommendationStatus) else RecommendationStatus(raw["status"]),
        created_at=raw["created_at"],
    )


# ── Fixture: Notification Engine service backed by FakePool ─────────────────────


@pytest.fixture
def make_notification(make_atrs):
    """Build a NotificationEngineService backed by a ``FakePool``."""
    pool = FakePool()
    atrs_service, atrs_rows, outbox = make_atrs

    async def notification_writer(row) -> None:
        if hasattr(row, "model_dump"):
            data = row.model_dump(mode='json')
        else:
            data = row
        await pool.execute(
            "INSERT INTO notifications (notification_id, user_id, habitat_id, priority, source_engine, title, message, status, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            str(data["notification_id"]), str(data["user_id"]), data.get("habitat_id"),
            data["priority"],
            data["source_engine"], data["title"], data["message"],
            data["status"],
            data["created_at"],
        )

    async def notification_reader(user_id: uuid.UUID) -> list:
        return [
            r for r in pool.tables["notifications"].values()
            if r["user_id"] == str(user_id)
        ]

    async def notification_updater(notification_id: uuid.UUID, fields: dict) -> None:
        await pool.execute(
            "UPDATE notifications SET ... WHERE notification_id = $1",
            fields,  # fields dict as first arg
            str(notification_id),  # notification_id as second arg
        )

    from app.services.notification_engine import NotificationEngineService
    service = NotificationEngineService(
        row_writer=notification_writer,
        row_reader=notification_reader,
        updater=notification_updater,
        atrs=atrs_service,
    )
    return service, pool, atrs_rows, outbox


# ── Fixture: Recommender Engine service backed by FakePool ─────────────────────


@pytest.fixture
def make_recommender(make_atrs):
    """Build a RecommenderEngineService backed by a ``FakePool``."""
    pool = FakePool()
    atrs_service, atrs_rows, outbox = make_atrs

    dismissed: set = set()

    async def recommendation_writer(row) -> None:
        if hasattr(row, "model_dump"):
            data = row.model_dump(mode='json')
        else:
            data = row
        await pool.execute(
            "INSERT INTO recommendations (recommendation_id, user_id, habitat_id, domain, suggestion_text, trigger_context, status, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            str(data["recommendation_id"]), str(data["user_id"]), data.get("habitat_id"),
            data["domain"],
            data["suggestion_text"], data["trigger_context"],
            data["status"],
            data["created_at"],
        )

    async def recommendation_reader(user_id: uuid.UUID) -> list:
        return [
            _row_to_recommendation(r)
            for r in pool.tables["recommendations"].values()
            if r["user_id"] == str(user_id)
        ]

    async def recommendation_updater(recommendation_id: uuid.UUID, fields: dict) -> None:
        await pool.execute(
            "UPDATE recommendations SET ... WHERE recommendation_id = $1",
            fields,
            str(recommendation_id),
        )

    async def atrs_reader(event_type: str, limit: int) -> list:
        return [
            {"entity_ref": f"model:{r.get('entity_ref', '').replace('model:', '')}", "status": "failure", "metadata": r.get("metadata", {})}
            for r in atrs_rows
            if r.get("event_type") == event_type
        ][:limit]

    from app.services.recommender_engine import RecommenderEngineService
    service = RecommenderEngineService(
        row_writer=recommendation_writer,
        row_reader=recommendation_reader,
        updater=recommendation_updater,
        atrs=atrs_service,
        atrs_reader=atrs_reader,
        dismissed_cache=dismissed,
    )
    return service, pool, atrs_rows, outbox, dismissed
