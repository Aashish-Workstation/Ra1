"""
Tests for Safety Engine service.
"""

import pytest

from app.models.safety import SafetyOutcome
from app.services.safety_engine import SafetyEngineService


@pytest.fixture
def make_safety_engine(make_atrs):
    atrs_service, atrs_rows, outbox = make_atrs
    service = SafetyEngineService(atrs=atrs_service)
    return service, atrs_rows


@pytest.mark.asyncio
async def test_evaluate_clear_for_safe_input(make_safety_engine):
    service, atrs_rows = make_safety_engine
    result = await service.evaluate_input("Hello, how are you?")
    assert result.outcome == SafetyOutcome.CLEAR


@pytest.mark.asyncio
async def test_evaluate_blocks_credential_leak(make_safety_engine):
    service, atrs_rows = make_safety_engine
    result = await service.evaluate_input("api_key=secret123")
    assert result.outcome == SafetyOutcome.BLOCK_HARD
    assert result.category.value == "credential_leak"


@pytest.mark.asyncio
async def test_evaluate_blocks_password(make_safety_engine):
    service, atrs_rows = make_safety_engine
    result = await service.evaluate_input("password=mysecret")
    assert result.outcome == SafetyOutcome.BLOCK_HARD


@pytest.mark.asyncio
async def test_evaluate_blocks_private_key(make_safety_engine):
    service, atrs_rows = make_safety_engine
    result = await service.evaluate_input("private_key=abc123")
    assert result.outcome == SafetyOutcome.BLOCK_HARD


@pytest.mark.asyncio
async def test_evaluate_output_blocks_leak(make_safety_engine):
    service, atrs_rows = make_safety_engine
    result = await service.evaluate_output("Here is the secret: password=leaked")
    assert result.outcome == SafetyOutcome.BLOCK_HARD


@pytest.mark.asyncio
async def test_logs_safety_evaluated(make_safety_engine):
    service, atrs_rows = make_safety_engine
    await service.evaluate_input("safe text")
    event_types = [row["event_type"] for row in atrs_rows]
    assert "safety.evaluated" in event_types


@pytest.mark.asyncio
async def test_logs_safety_blocked(make_safety_engine):
    service, atrs_rows = make_safety_engine
    await service.evaluate_input("api_key=secret")
    event_types = [row["event_type"] for row in atrs_rows]
    assert "safety.blocked" in event_types


@pytest.mark.asyncio
async def test_detects_ssn_leak(make_safety_engine):
    service, atrs_rows = make_safety_engine
    result = await service.evaluate_input("SSN: 123-45-6789")
    assert result.outcome == SafetyOutcome.BLOCK_HARD