"""
Unit tests for the Memory Engine.

Verifies:
  1. KAC blocks edits to locked records
  2. Confidence score changes promote records across lanes
  3. Conflicting facts trigger conflict detection and ATRS logging
"""

from __future__ import annotations

import uuid
import pytest

from app.models.memory import (
    KnowledgeLane,
    KnowledgeType,
    MemoryConflict,
    MemoryRecordCreate,
    MemorySource,
    confidence_to_lane,
)
from app.models.atrs import ATRSEngine, ATRSStatus, ATRSMemoryEvent


def test_confidence_to_lane():
    assert confidence_to_lane(0.95) == KnowledgeLane.SUPER
    assert confidence_to_lane(0.94) == KnowledgeLane.LONG
    assert confidence_to_lane(0.70) == KnowledgeLane.LONG
    assert confidence_to_lane(0.69) == KnowledgeLane.SHORT
    assert confidence_to_lane(0.50) == KnowledgeLane.SHORT
    assert confidence_to_lane(0.49) == KnowledgeLane.TEMP
    assert confidence_to_lane(0.0) == KnowledgeLane.TEMP


def test_kac_blocks_edits_to_locked_records(make_memory):
    memory, pool, atrs_rows, _outbox = make_memory
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()
    asyncio_run = _run_async

    rd = asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_id,
        entity_type="user_preference",
        attribute="timezone",
        value={"tz": "UTC"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.9,
        source=MemorySource.USER,
        provenance="test-session",
    )))
    entity_id = rd.entity_id

    asyncio_run(memory.lock_record(user_id, habitat_id, entity_id))
    locked = pool.tables["memory_records"][str(entity_id)]
    assert locked["lock_status"] == True

    with pytest.raises(ValueError, match="locked"):
        asyncio_run(memory.propose(MemoryRecordCreate(
            habitat_id=habitat_id,
            user_id=user_id,
            entity_type="user_preference",
            attribute="timezone",
            value={"tz": "America/New_York"},
            knowledge_type=KnowledgeType.FACT,
            confidence=0.9,
            source=MemorySource.AGENT,
            provenance="test-session-2",
        )))

    rejected_events = [r for r in atrs_rows if r.get("event_type") == ATRSMemoryEvent.MEMORY_WRITE_REJECTED.value]
    assert len(rejected_events) >= 1


def test_confidence_promotion_across_lanes(make_memory):
    memory, pool, atrs_rows, _outbox = make_memory
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()
    asyncio_run = _run_async

    rd = asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_id,
        entity_type="user_preference",
        attribute="name",
        value={"first": "Test"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.4,
        source=MemorySource.AGENT,
        provenance="test-session",
    )))
    assert confidence_to_lane(rd.confidence) == KnowledgeLane.TEMP

    rd2 = asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_id,
        entity_type="user_preference",
        attribute="name",
        value={"first": "Test", "last": "User"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.6,
        source=MemorySource.USER,
        provenance="test-session-2",
    )))
    assert confidence_to_lane(rd2.confidence) == KnowledgeLane.LONG

    committed_events = [r for r in atrs_rows if r.get("event_type") == ATRSMemoryEvent.MEMORY_WRITE_COMMITTED.value]
    assert len(committed_events) >= 2


def test_conflicting_facts_trigger_detection(make_memory):
    memory, pool, atrs_rows, _outbox = make_memory
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()
    asyncio_run = _run_async

    rd = asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_id,
        entity_type="user_preference",
        attribute="language",
        value={"lang": "en"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.8,
        source=MemorySource.USER,
        provenance="test-session",
    )))
    assert rd.confidence == 0.8

    rd2, conflict = asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_id,
        entity_type="user_preference",
        attribute="language",
        value={"lang": "es"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.7,
        source=MemorySource.AGENT,
        provenance="test-session-2",
    )))

    assert conflict is not None
    assert isinstance(conflict, MemoryConflict)
    assert conflict.entity_type == "user_preference"
    assert conflict.attribute == "language"

    conflict_events = [r for r in atrs_rows if r.get("event_type") == ATRSMemoryEvent.MEMORY_CONFLICT_DETECTED.value]
    assert len(conflict_events) >= 1


def test_read_returns_scoped_view(make_memory):
    memory, pool, atrs_rows, _outbox = make_memory
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    habitat_id = uuid.uuid4()
    asyncio_run = _run_async

    asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_a,
        entity_type="preference",
        attribute="theme",
        value={"mode": "dark"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.9,
        source=MemorySource.USER,
        provenance="session-a",
    )))

    records_b = asyncio_run(memory.list_for_scope(user_b, habitat_id))
    assert records_b == []

    records_a = asyncio_run(memory.list_for_scope(user_a, habitat_id))
    assert len(records_a) == 1
    assert records_a[0].value == {"mode": "dark"}


def test_lock_status_prevents_modification(make_memory):
    memory, pool, atrs_rows, _outbox = make_memory
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()
    asyncio_run = _run_async

    rd = asyncio_run(memory.propose(MemoryRecordCreate(
        habitat_id=habitat_id,
        user_id=user_id,
        entity_type="fact",
        attribute="question",
        value={"answer": "42"},
        knowledge_type=KnowledgeType.FACT,
        confidence=0.9,
        source=MemorySource.USER,
        provenance="test",
    )))

    asyncio_run(memory.lock_record(user_id, habitat_id, rd.entity_id))

    with pytest.raises(ValueError):
        asyncio_run(memory.propose(MemoryRecordCreate(
            habitat_id=habitat_id,
            user_id=user_id,
            entity_type="fact",
            attribute="question",
            value={"answer": "100"},
            knowledge_type=KnowledgeType.FACT,
            confidence=0.9,
            source=MemorySource.AGENT,
            provenance="test-2",
        )))


# ── helpers ─────────────────────────────────────────────────────────────────


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)