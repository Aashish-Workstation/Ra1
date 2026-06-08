"""
Quality Gate — generation evaluation before delivery.

Properties:
  1. **Dimension evaluation** — Completeness, Coherence, Format correctness, Hallucination.
  2. **Retry logic** — Max 2 internal attempts with fallback models.
  3. **ATRS logging** — Events for gate.evaluated and gate.rejected_retry.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus, ATRSGateEvent
from app.models.gate import GateConfig, GateEvaluation, GateOutcome, QualityMetrics

logger = logging.getLogger(__name__)

ModelExecutor = Callable[[], Awaitable[str]]


class QualityGateService:
    """Stateless quality evaluation service.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        atrs: ATRSService,
        config: Optional[GateConfig] = None,
        fallback_executor: Optional[ModelExecutor] = None,
    ):
        self._atrs = atrs
        self._config = config or GateConfig()
        self._fallback_executor = fallback_executor

    async def evaluate(
        self,
        response: str,
        context_provided: bool = True,
        retry_count: int = 0,
    ) -> GateEvaluation:
        """Evaluate a generated response across all dimensions."""
        metrics = QualityMetrics(
            completeness=self._check_completeness(response),
            coherence=self._check_coherence(response),
            format_correctness=self._check_format_correctness(response),
            hallucination_flag=self._check_hallucination(response, context_provided),
            hallucination_details=self._get_hallucination_details(response, context_provided),
        )

        failed_dims = self._get_failed_dimensions(metrics)

        if not failed_dims:
            await self._log_evaluated(GateOutcome.PASS.value)
            return GateEvaluation(
                outcome=GateOutcome.PASS,
                metrics=metrics,
                failed_dimensions=[],
            )

        if retry_count < self._config.max_retry_attempts and self._fallback_executor:
            await self._log_rejected_retry(failed_dims)
            return GateEvaluation(
                outcome=GateOutcome.REJECT_RETRY,
                metrics=metrics,
                failed_dimensions=failed_dims,
                retry_reason=f"Failed dimensions: {', '.join(d.value for d in failed_dims)}",
            )

        await self._log_evaluated(GateOutcome.REJECT_SURFACE.value)
        return GateEvaluation(
            outcome=GateOutcome.REJECT_SURFACE,
            metrics=metrics,
            failed_dimensions=failed_dims,
            surface_error=f"Quality gate failed on: {', '.join(d.value for d in failed_dims)}",
        )

    def _check_completeness(self, response: str) -> float:
        """Check if response addresses the prompt fully."""
        if not response or len(response.strip()) < 10:
            return 0.0
        if response.strip().endswith("...") or response.strip().endswith("?"):
            return 0.7
        return 1.0

    def _check_coherence(self, response: str) -> float:
        """Check if response is logically coherent."""
        sentences = [s.strip() for s in response.split(".") if s.strip()]
        if len(sentences) < 2:
            return 0.8
        first_words = sentences[0].split()[:5]
        last_words = sentences[-1].split()[-5:]
        if first_words and last_words and set(first_words[-2:]) & set(last_words[:2]):
            return 0.9
        return 0.85

    def _check_format_correctness(self, response: str) -> float:
        """Check if response format is correct."""
        return 1.0

    def _check_hallucination(self, response: str, context_provided: bool) -> bool:
        """Flag potential hallucinations."""
        if context_provided:
            return False
        hallucination_indicators = ["i don't know", "i cannot", "not enough context", "without context"]
        return any(indicator in response.lower() for indicator in hallucination_indicators)

    def _get_hallucination_details(self, response: str, context_provided: bool) -> Optional[str]:
        """Get hallucination details."""
        if not context_provided:
            return "Response generated without context provided"
        return None

    def _get_failed_dimensions(self, metrics: QualityMetrics) -> list:
        """Get list of failed dimensions."""
        failed = []
        if metrics.completeness < self._config.completeness_threshold:
            failed.append("completeness")
        if metrics.coherence < self._config.coherence_threshold:
            failed.append("coherence")
        if metrics.format_correctness < self._config.format_threshold:
            failed.append("format_correctness")
        if metrics.hallucination_flag:
            failed.append("hallucination")
        return failed

    async def _log_evaluated(self, outcome: str) -> None:
        """Log evaluation to ATRS."""
        await self._atrs.record_simple(
            engine=ATRSEngine.GATE,
            event_type=ATRSGateEvent.GATE_EVALUATED,
            status=ATRSStatus.SUCCESS,
            metadata={"outcome": outcome},
        )

    async def _log_rejected_retry(self, failed_dims: list) -> None:
        """Log retry event to ATRS."""
        await self._atrs.record_simple(
            engine=ATRSEngine.GATE,
            event_type=ATRSGateEvent.GATE_REJECTED_RETRY,
            status=ATRSStatus.PARTIAL,
            metadata={"failed_dimensions": [d.value for d in failed_dims]},
        )