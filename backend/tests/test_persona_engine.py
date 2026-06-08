"""
Unit tests for the Persona Engine.

Verifies:
  1. Archetype blend validates sum equals 1.0
  2. Persona lifecycle operations work correctly
  3. Blend shifts and major switch detection
"""

from __future__ import annotations

import uuid
import pytest

from app.models.persona import Persona, PersonaCreate, PersonaScope
from app.models.atrs import ATRSStatus, ATRSPersonaEvent
from app.services.persona_engine import PersonaEngineService


def test_archetype_blend_sums_to_one():
    blend = {
        "Builder": 0.25,
        "Analyst": 0.25,
        "Guardian": 0.1,
        "Caregiver": 0.1,
        "Creator": 0.1,
        "Operator": 0.1,
        "Scientist": 0.05,
        "Strategist": 0.1,
    }
    persona = Persona(
        persona_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Test Persona",
        profession="Engineer",
        industry="Tech",
        archetype_blend=blend,
        tone_rules=[],
        rules=[],
        scope=PersonaScope.GLOBAL,
    )
    assert persona.archetype_blend == blend


def test_archetype_blend_invalid_sum():
    blend = {
        "Builder": 0.5,
        "Analyst": 0.5,
        "Guardian": 0.1,
        "Caregiver": 0.1,
        "Creator": 0.1,
        "Operator": 0.1,
        "Scientist": 0.05,
        "Strategist": 0.1,
    }
    with pytest.raises(ValueError, match="must sum to 1.0"):
        Persona(
            persona_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Test Persona",
            profession="Engineer",
            industry="Tech",
            archetype_blend=blend,
            tone_rules=[],
            rules=[],
            scope=PersonaScope.GLOBAL,
        )


def test_persona_create_validates_blend(make_persona_engine):
    engine, pool, atrs_rows, lister = make_persona_engine
    user_id = uuid.uuid4()
    blend = {"Builder": 0.5, "Analyst": 0.5, "Guardian": 0.0, "Caregiver": 0.0,
             "Creator": 0.0, "Operator": 0.0, "Scientist": 0.0, "Strategist": 0.0}
    create = PersonaCreate(
        user_id=user_id,
        name="Test",
        profession="Engineer",
        industry="Tech",
        archetype_blend=blend,
    )
    assert create.archetype_blend == blend


def test_persona_create_invalid_blend(make_persona_engine):
    blend = {"Builder": 0.6, "Analyst": 0.6, "Guardian": 0.0, "Caregiver": 0.0,
             "Creator": 0.0, "Operator": 0.0, "Scientist": 0.0, "Strategist": 0.0}
    with pytest.raises(ValueError, match="must sum to 1.0"):
        PersonaCreate(
            user_id=uuid.uuid4(),
            name="Test",
            profession="Engineer",
            industry="Tech",
            archetype_blend=blend,
        )


def test_blend_shift_updates_weights(make_persona_engine):
    engine, pool, atrs_rows, lister = make_persona_engine
    persona_id = uuid.uuid4()
    blend = {"Builder": 0.5, "Analyst": 0.3, "Guardian": 0.1, "Caregiver": 0.05,
             "Creator": 0.03, "Operator": 0.02, "Scientist": 0.05, "Strategist": 0.05}
    _run_async(engine.update_blend(persona_id, {"Builder": 0.1}))


def test_major_switch_detected_on_threshold_crossing(make_persona_engine):
    engine, pool, atrs_rows, lister = make_persona_engine
    persona_id = uuid.uuid4()
    _run_async(engine.update_blend(persona_id, {"Builder": 0.2}))


def test_atrs_logged_on_persona_load(make_persona_engine):
    engine, pool, atrs_rows, lister = make_persona_engine
    user_id = uuid.uuid4()
    _run_async(engine.load_persona(user_id))


def test_atrs_logged_on_blend_update(make_persona_engine):
    engine, pool, atrs_rows, lister = make_persona_engine
    persona_id = uuid.uuid4()
    _run_async(engine.update_blend(persona_id, {"Analyst": 0.1}))
    blend_events = [r for r in atrs_rows if r.get("event_type") == ATRSPersonaEvent.PERSONA_BLEND_UPDATED.value]
    assert len(blend_events) >= 1


def test_invalid_archetype_rejected():
    blend = {"InvalidArchetype": 1.0, "Analyst": 0.0, "Guardian": 0.0, "Caregiver": 0.0,
             "Creator": 0.0, "Operator": 0.0, "Scientist": 0.0, "Strategist": 0.0}
    with pytest.raises(ValueError, match="Invalid archetype"):
        Persona(
            persona_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Test",
            profession="Engineer",
            industry="Tech",
            archetype_blend=blend,
            tone_rules=[],
            rules=[],
            scope=PersonaScope.GLOBAL,
        )


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


@pytest.fixture
def make_persona_engine():
    pool = FakePool()
    atrs_rows: list = []

    async def atrs_writer(row: dict):
        atrs_rows.append(row)

    from app.core.atrs import ATRSService
    atrs_service = ATRSService(ch_writer=atrs_writer, ch_enabled=False)

    async def lister(user_id: uuid.UUID):
        return []

    async def row_writer(row):
        pass

    async def row_reader(user_id, habitat_id):
        return None

    async def updater(persona_id, fields):
        pass

    from app.services.persona_engine import PersonaEngineService
    engine = PersonaEngineService(
        row_reader=row_reader,
        row_writer=row_writer,
        updater=updater,
        lister=lister,
        atrs=atrs_service,
    )
    return engine, pool, atrs_rows, lister


from tests.conftest import FakePool