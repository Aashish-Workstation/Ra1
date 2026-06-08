"""
Unit tests for the Search Engine.

Verifies:
  1. Unified search executes cross-queries across memory and knowledge
  2. Relevance threshold filtering works correctly
  3. ATRS logging for search events
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from app.models.memory import MemoryRecord, MemoryRecordRead, KnowledgeType, MemorySource
from app.models.knowledge import KnowledgeItem, KnowledgeItemRead, ContentType
from app.models.atrs import ATRSStatus, ATRSKnowledgeEvent
from app.services.search_engine import SearchEngineService, DEFAULT_RELEVANCE_THRESHOLD


def make_memory_record(entity_id: uuid.UUID, content: dict, confidence: float) -> MemoryRecordRead:
    now = datetime.now(timezone.utc)
    return MemoryRecordRead(
        entity_id=entity_id,
        habitat_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        entity_type="test",
        attribute="content",
        value=content,
        knowledge_type=KnowledgeType.FACT,
        confidence=confidence,
        source=MemorySource.USER,
        provenance="test",
        ttl=None,
        lock_status=False,
        links={},
        created_at=now,
        updated_at=now,
    )


def make_knowledge_item(item_id: uuid.UUID, content: dict, tags: list = None) -> KnowledgeItemRead:
    now = datetime.now(timezone.utc)
    return KnowledgeItemRead(
        item_id=item_id,
        user_id=uuid.uuid4(),
        habitat_id=uuid.uuid4(),
        content_type=ContentType.DOCUMENT,
        content=content,
        tags=tags or [],
        collections=[],
        created_at=now,
        updated_at=now,
    )


def test_search_cross_domain(make_search_engine):
    engine, memory_records, knowledge_items, atrs_rows = make_search_engine
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()

    mem = make_memory_record(uuid.uuid4(), {"text": "python programming"}, 0.9)
    memory_records.append(mem)

    item = make_knowledge_item(uuid.uuid4(), {"text": "java tutorial"}, ["java", "programming"])
    knowledge_items.append(item)

    results = _run_async(engine.search("programming", user_id, habitat_id, domains=["memory", "knowledge"]))
    assert len(results) >= 1


def test_search_threshold_filtering(make_search_engine):
    engine, memory_records, knowledge_items, atrs_rows = make_search_engine
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()

    mem = make_memory_record(uuid.uuid4(), {"text": "unique_term_xyz"}, 0.1)
    memory_records.append(mem)

    results = _run_async(engine.search("unique_term_xyz", user_id, habitat_id, threshold=0.5))
    low_results = [r for r in results if r.score >= 0.5]
    assert len(low_results) == 0


def test_search_knowledge_domain_only(make_search_engine):
    engine, memory_records, knowledge_items, atrs_rows = make_search_engine
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()

    item = make_knowledge_item(uuid.uuid4(), {"text": "python guide"}, ["python"])
    knowledge_items.append(item)

    results = _run_async(engine.search("python", user_id, habitat_id, domains=["knowledge"]))
    assert any(r.content_type == ContentType.DOCUMENT for r in results)


def test_search_memory_domain_only(make_search_engine):
    engine, memory_records, knowledge_items, atrs_rows = make_search_engine
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()

    mem = make_memory_record(uuid.uuid4(), {"text": "rust programming"}, 0.8)
    memory_records.append(mem)

    results = _run_async(engine.search("rust", user_id, habitat_id, domains=["memory"]))
    assert any(r.content_type == "structured" for r in results)


def test_search_atrs_logging(make_search_engine):
    engine, memory_records, knowledge_items, atrs_rows = make_search_engine
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()

    _run_async(engine.search("test query", user_id, habitat_id))
    received = [r for r in atrs_rows if r.get("event_type") == ATRSKnowledgeEvent.SEARCH_RECEIVED.value]
    returned = [r for r in atrs_rows if r.get("event_type") == ATRSKnowledgeEvent.SEARCH_RESULTS_RETURNED.value]
    assert len(received) >= 1
    assert len(returned) >= 1


def test_search_empty_query(make_search_engine):
    engine, memory_records, knowledge_items, atrs_rows = make_search_engine
    user_id = uuid.uuid4()
    habitat_id = uuid.uuid4()

    results = _run_async(engine.search("", user_id, habitat_id))
    assert isinstance(results, list)


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


@pytest.fixture
def make_search_engine():
    memory_records: list = []
    knowledge_items: list = []
    atrs_rows: list = []

    async def memory_lister(user_id: uuid.UUID, habitat_id: uuid.UUID):
        return memory_records

    async def knowledge_lister(user_id: uuid.UUID, habitat_id: uuid.UUID):
        return knowledge_items

    async def atrs_writer(row: dict):
        atrs_rows.append(row)

    engine = SearchEngineService(
        memory_lister=memory_lister,
        knowledge_lister=knowledge_lister,
        atrs=None,
    )
    return engine, memory_records, knowledge_items, atrs_rows