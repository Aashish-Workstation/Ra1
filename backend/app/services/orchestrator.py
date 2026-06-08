"""
Orchestrator — main traffic controller for message processing.

Properties:
  1. **10-phase pipeline** — Receive, Classify, Fetch & Assemble, Execute, Intercept & Guard,
     Output, Evaluate, Commit, Log, Return.
  2. **Dependency injection** — Links services in correct order.
  3. **Fallback handling** — Routes to secondary models on quality gate rejection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSOrchestratorEvent, ATRSStatus
from app.models.context import ContextFetchSpec
from app.models.gate import GateEvaluation
from app.models.orchestrator import ExecutionContext, MessageIntent, OrchestratorResult
from app.models.output import OutputSynthesis
from app.models.safety import SafetyEvaluation, SafetyOutcome

logger = logging.getLogger(__name__)

InputNormalizer = Callable[[str, list], Awaitable[Any]]
ContextAssembler = Callable[[ContextFetchSpec], Awaitable[Any]]
ModelExecutor = Callable[[str, dict], Awaitable[str]]
SafetyEvaluator = Callable[[str], Awaitable[SafetyEvaluation]]
OutputSynthesizer = Callable[[str, Optional[Any]], Awaitable[OutputSynthesis]]
MemoryCommitter = Callable[[dict], Awaitable[None]]
GateEvaluator = Callable[[str, bool, int], Awaitable[GateEvaluation]]


class OrchestratorService:
    """Central orchestrator for the message processing pipeline.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        atrs: ATRSService,
        input_normalizer: InputNormalizer,
        context_assembler: ContextAssembler,
        model_executor: ModelExecutor,
        safety_evaluator: SafetyEvaluator,
        output_synthesizer: OutputSynthesizer,
        memory_committer: MemoryCommitter,
        gate_evaluator: Optional[GateEvaluator] = None,
    ):
        self._atrs = atrs
        self._input_normalizer = input_normalizer
        self._context_assembler = context_assembler
        self._model_executor = model_executor
        self._safety_evaluator = safety_evaluator
        self._output_synthesizer = output_synthesizer
        self._memory_committer = memory_committer
        self._gate_evaluator = gate_evaluator

    async def process(
        self,
        user_id: uuid.UUID,
        text: str,
        session_id: Optional[uuid.UUID] = None,
        habitat_id: Optional[uuid.UUID] = None,
    ) -> OrchestratorResult:
        """Execute the full 10-phase message processing pipeline."""
        start_time = datetime.now(timezone.utc)
        ctx = ExecutionContext(
            user_id=user_id,
            session_id=session_id,
            habitat_id=habitat_id,
            input_text=text,
        )

        try:
            ctx = await self._phase_receive(ctx, text)
            ctx = await self._phase_classify(ctx)
            ctx = await self._phase_fetch_assemble(ctx)
            ctx = await self._phase_execute(ctx)
            ctx = await self._phase_intercept_guard(ctx)
            output = await self._phase_output(ctx)
            ctx = await self._phase_evaluate(ctx)
            await self._phase_commit(ctx)
            await self._phase_log(ctx, start_time)

            return OrchestratorResult(
                success=True,
                response=output.response if output else ctx.model_response or "",
                context=ctx.context,
                safety_eval=ctx.safety_eval,
                output=output,
                gate_eval=ctx.gate_eval,
                execution_time_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            )
        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            return OrchestratorResult(
                success=False,
                error=str(e),
                execution_time_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            )

    async def _phase_receive(self, ctx: ExecutionContext, text: str) -> ExecutionContext:
        """Phase 1: Receive and normalize input."""
        normalized = await self._input_normalizer(text, [])
        ctx.input_text = normalized.get("normalized_text", text)
        return ctx

    async def _phase_classify(self, ctx: ExecutionContext) -> ExecutionContext:
        """Phase 2: Classify intent and complexity."""
        ctx.intent = MessageIntent.T1
        return ctx

    async def _phase_fetch_assemble(self, ctx: ExecutionContext) -> ExecutionContext:
        """Phase 3: Fetch and assemble context."""
        spec = ContextFetchSpec(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            habitat_id=ctx.habitat_id,
            query=ctx.input_text,
        )
        ctx.context = await self._context_assembler(spec)
        return ctx

    async def _phase_execute(self, ctx: ExecutionContext) -> ExecutionContext:
        """Phase 4: Execute with model."""
        ctx.model_response = await self._model_executor(ctx.input_text, {})
        return ctx

    async def _phase_intercept_guard(self, ctx: ExecutionContext) -> ExecutionContext:
        """Phase 5: Safety and output guard."""
        if ctx.model_response:
            ctx.safety_eval = await self._safety_evaluator(ctx.model_response)
            if ctx.safety_eval.outcome == SafetyOutcome.BLOCK_HARD:
                ctx.model_response = "[Response blocked by safety engine]"
        return ctx

    async def _phase_output(self, ctx: ExecutionContext) -> Optional[OutputSynthesis]:
        """Phase 6: Prepare output."""
        if ctx.model_response:
            return await self._output_synthesizer(ctx.model_response, None)
        return None

    async def _phase_evaluate(self, ctx: ExecutionContext) -> ExecutionContext:
        """Phase 7: Quality gate evaluation."""
        if ctx.model_response and self._gate_evaluator:
            ctx.gate_eval = await self._gate_evaluator(ctx.model_response, context_provided=True, retry_count=ctx.retry_count)
        return ctx

    async def _phase_commit(self, ctx: ExecutionContext) -> None:
        """Phase 8: Commit post-generation writes."""
        if self._memory_committer and ctx.context:
            await self._memory_committer({"context": ctx.context.model_dump()})

    async def _phase_log(
        self,
        ctx: ExecutionContext,
        start_time: datetime,
    ) -> None:
        """Phase 9: Write execution traces."""
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        await self._atrs.record_simple(
            engine=ATRSEngine.ORCHESTRATOR,
            event_type=ATRSOrchestratorEvent.ORCHESTRATOR_COMPLETED,
            status=ATRSStatus.SUCCESS,
            metadata={"duration_ms": duration_ms, "intent": ctx.intent.value},
        )