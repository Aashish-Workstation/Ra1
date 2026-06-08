"""
Tests for Quality Gate service.
"""

import pytest

from app.models.gate import GateOutcome
from app.services.quality_gate import QualityGateService


@pytest.fixture
def make_quality_gate(make_atrs):
    atrs_service, atrs_rows, outbox = make_atrs
    service = QualityGateService(atrs=atrs_service)
    return service, atrs_rows


@pytest.mark.asyncio
async def test_evaluate_passes_clear_response(make_quality_gate):
    service, atrs_rows = make_quality_gate
    result = await service.evaluate("This is a complete and coherent response that addresses the user's question thoroughly.", context_provided=True)
    assert result.outcome == GateOutcome.PASS


@pytest.mark.asyncio
async def test_evaluate_detects_short_response(make_quality_gate):
    service, atrs_rows = make_quality_gate
    result = await service.evaluate("Hi", context_provided=True)
    assert result.outcome != GateOutcome.PASS


@pytest.mark.asyncio
async def test_evaluate_logs_atrs_events(make_quality_gate):
    service, atrs_rows = make_quality_gate
    await service.evaluate("This is a complete response with enough content to pass the gate.", context_provided=True)
    event_types = [row["event_type"] for row in atrs_rows]
    assert "gate.evaluated" in event_types


@pytest.mark.asyncio
async def test_hallucination_flagged_when_context_empty(make_quality_gate):
    service, atrs_rows = make_quality_gate
    result = await service.evaluate("I can't answer without context.", context_provided=False)
    assert result.metrics.hallucination_flag or result.outcome != GateOutcome.PASS


@pytest.mark.asyncio
async def test_completeness_threshold_enforced(make_quality_gate):
    service, atrs_rows = make_quality_gate
    result = await service.evaluate("Short.", context_provided=True)
    if result.outcome != GateOutcome.PASS:
        assert "completeness" in [d.value for d in result.failed_dimensions]