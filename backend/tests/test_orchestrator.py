"""
Tests for Orchestrator service.
"""

import pytest
import uuid

from app.models.orchestrator import OrchestratorResult
from app.models.gate import GateEvaluation, GateOutcome, QualityMetrics
from app.services.orchestrator import OrchestratorService


@pytest.fixture
def make_orchestrator(make_atrs):
    atrs_service, atrs_rows, outbox = make_atrs

    async def input_normalizer(text, attachments):
        return {"normalized_text": text}

    async def context_assembler(spec):
        from app.models.context import ContextPayload, WorkingContext, EpisodicContext, SemanticContext, PersonaState
        return ContextPayload(
            working=WorkingContext(thread_id=spec.session_id, messages=[], token_count=0),
            episodic=EpisodicContext(token_count=0),
            semantic=SemanticContext(query=spec.query, token_count=0),
            persona=PersonaState(),
            total_tokens=0,
        )

    async def model_executor(prompt, context):
        return "This is a response."

    async def safety_evaluator(text):
        from app.models.safety import SafetyEvaluation, SafetyOutcome
        return SafetyEvaluation(outcome=SafetyOutcome.CLEAR, reason="OK")

    async def output_synthesizer(text, spec):
        from app.models.output import OutputSynthesis, OutputChunk, OutputFormat
        return OutputSynthesis(
            chunks=[OutputChunk(chunk_type="main", content=text, format=OutputFormat.PROSE)],
            format=OutputFormat.PROSE,
            total_tokens=len(text) // 4,
        )

    async def memory_committer(data):
        pass

    async def gate_evaluator(text, context_provided, retry_count):
        return GateEvaluation(
            outcome=GateOutcome.PASS,
            metrics=QualityMetrics(),
            failed_dimensions=[],
        )

    service = OrchestratorService(
        atrs=atrs_service,
        input_normalizer=input_normalizer,
        context_assembler=context_assembler,
        model_executor=model_executor,
        safety_evaluator=safety_evaluator,
        output_synthesizer=output_synthesizer,
        memory_committer=memory_committer,
        gate_evaluator=gate_evaluator,
    )
    return service, atrs_rows


@pytest.mark.asyncio
async def test_process_returns_result(make_orchestrator):
    service, atrs_rows = make_orchestrator
    result = await service.process(user_id=uuid.uuid4(), text="Hello")
    assert isinstance(result, OrchestratorResult)


@pytest.mark.asyncio
async def test_process_success(make_orchestrator):
    service, atrs_rows = make_orchestrator
    result = await service.process(user_id=uuid.uuid4(), text="Hello")
    assert result.success is True


@pytest.mark.asyncio
async def test_process_returns_response(make_orchestrator):
    service, atrs_rows = make_orchestrator
    result = await service.process(user_id=uuid.uuid4(), text="Hello")
    assert result.response != ""


@pytest.mark.asyncio
async def test_process_logs_atrs_events(make_orchestrator):
    service, atrs_rows = make_orchestrator
    await service.process(user_id=uuid.uuid4(), text="Hello")
    event_types = [row["event_type"] for row in atrs_rows]
    assert "orchestrator.completed" in event_types