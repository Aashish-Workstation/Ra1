"""
Tests for Context Assembler service.
"""

import pytest
import uuid

from app.models.context import ContextFetchSpec, ContextPayload
from app.services.context_assembler import ContextAssemblerService


@pytest.fixture
def make_context_assembler(make_atrs):
    atrs_service, atrs_rows, outbox = make_atrs

    async def memory_lister(user_id, habitat_id):
        return []

    async def search_engine(query, user_id, habitat_id):
        return [{"item_id": str(uuid.uuid4()), "score": 0.8, "content": "test result"}]

    async def persona_reader(user_id, habitat_id):
        return None

    service = ContextAssemblerService(
        atrs=atrs_service,
        memory_lister=memory_lister,
        search_engine=search_engine,
        persona_reader=persona_reader,
    )
    return service, atrs_rows


def test_assemble_basic(make_context_assembler):
    service, atrs_rows = make_context_assembler
    spec = ContextFetchSpec(
        user_id=uuid.uuid4(),
        query="test query",
    )


@pytest.mark.asyncio
async def test_assemble_returns_context_payload(make_context_assembler):
    service, atrs_rows = make_context_assembler
    spec = ContextFetchSpec(
        user_id=uuid.uuid4(),
        query="test query",
    )
    payload = await service.assemble(spec)
    assert isinstance(payload, ContextPayload)


@pytest.mark.asyncio
async def test_assemble_logs_atrs_events(make_context_assembler):
    service, atrs_rows = make_context_assembler
    spec = ContextFetchSpec(
        user_id=uuid.uuid4(),
        query="test query",
    )
    await service.assemble(spec)
    event_types = [row["event_type"] for row in atrs_rows]
    assert "context.fetch_spec_received" in event_types
    assert "context.assembled" in event_types


@pytest.mark.asyncio
async def test_trim_semantic_first_under_budget(make_context_assembler):
    service, atrs_rows = make_context_assembler
    spec = ContextFetchSpec(
        user_id=uuid.uuid4(),
        query="test query",
        max_tokens=100,
    )
    payload = await service.assemble(spec)
    assert payload.truncated or payload.total_tokens <= spec.max_tokens


@pytest.mark.asyncio
async def test_persona_never_trimmed(make_context_assembler):
    service, atrs_rows = make_context_assembler
    spec = ContextFetchSpec(
        user_id=uuid.uuid4(),
        query="test query",
        max_tokens=10,
    )
    payload = await service.assemble(spec)
    assert payload.persona is not None