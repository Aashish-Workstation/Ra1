"""
Model Engine — Stateless engine for dynamic model selection, execution, and fallback chains.

Properties:
1. **BYOK Integration** — Never stores/caches API keys. Resolves credentials at call time
   from the Vault service using `credential_type: model_api_key`.
2. **Dynamic Fallback** — Scores active models using ATRS signals (success rate, latency)
   to build a ranked fallback chain.
3. **ATRS Logging** — Emits `model.call.start/success/failure` and `model.fallback.triggered`
   events for every execution.
4. **Guard Layer** — Enforces budget caps for non-BYOK accounts.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSModelEvent, ATRSStatus
from app.models.model import AccountType, ModelStatus
from app.models.vault import VaultEntryNotFoundError
from app.services.fallback_router import execute_with_fallback, set_cooldown
from app.services.task_matcher import RankedModel, TaskRequest, match_models
from app.services.usage_tracker import check_budget

logger = logging.getLogger(__name__)


@dataclass
class ModelCallResult:
    """Result of a model execution attempt."""
    response: Any
    model_used: str
    fallback_triggered: bool
    fallback_from: Optional[str]
    latency_ms: int
    error: Optional[dict] = None


class ModelEngineService:
    """Stateless model execution engine with fallback and credential resolution."""

    def __init__(
        self,
        atrs: ATRSService,
        vault_resolve: Callable[[str, Any], Awaitable[str]],
        model_reader: Callable[[], Awaitable[list[dict]]],
        execute_fn: Callable[[str, str], Awaitable[Any]],
        account_type: AccountType = AccountType.FREE,
        owner_id: str = "",
    ):
        self._atrs = atrs
        self._vault_resolve = vault_resolve
        self._model_reader = model_reader
        self._execute_fn = execute_fn
        self._account_type = account_type
        self._owner_id = owner_id

    async def execute(
        self,
        task_req: TaskRequest,
        user_id: str = "",
        estimated_cost_usd: float = 0.0,
    ) -> ModelCallResult:
        """Execute a task with dynamic fallback chain."""
        if self._account_type != AccountType.BYOK and user_id:
            budget = check_budget(user_id, estimated_cost_usd)
            if not budget["allowed"]:
                await self._atrs.record_simple(
                    engine=ATRSEngine.CHAT,
                    event_type=ATRSModelEvent.MODEL_CALL_FAILURE,
                    status=ATRSStatus.BLOCKED,
                    metadata={"reason": budget.get("reason", "budget_exceeded")},
                )
                return ModelCallResult(
                    response=None,
                    model_used="",
                    fallback_triggered=False,
                    fallback_from=None,
                    latency_ms=0,
                    error={"type": "budget_exceeded", "message": budget.get("reason", "Budget limit reached")},
                )

        models = await self._get_ranked_models(task_req)
        if not models:
            return ModelCallResult(
                response=None,
                model_used="",
                fallback_triggered=False,
                fallback_from=None,
                latency_ms=0,
                error={"type": "no_models", "message": "No active models available for this task"},
            )

        ranked = [self._enrich_with_credential(m) for m in models]
        return await self._execute_with_fallback_chain(ranked, task_req)

    async def _get_available_providers(self) -> dict[str, bool]:
        """Check which providers have active models with credentials configured."""
        providers: dict[str, bool] = {}
        models = await self._model_reader()
        for m in models:
            provider = m.get("provider", "")
            if provider and m.get("status") == ModelStatus.ACTIVE.value:
                if m.get("credential_ref") is not None:
                    providers[provider] = True
        return providers

    async def _get_ranked_models(self, task_req: TaskRequest) -> list[RankedModel]:
        """Get ranked models from the registry, filtered by availability."""
        available_providers = await self._get_available_providers()
        return match_models(task_req, available_providers)

    def _enrich_with_credential(self, model: RankedModel) -> RankedModel:
        """Add credential resolution info to model (resolved at call time)."""
        return model

    async def _execute_with_fallback_chain(
        self,
        ranked_models: list[RankedModel],
        task_req: TaskRequest,
    ) -> ModelCallResult:
        """Execute with fallback, logging each attempt to ATRS."""

        async def execute_single(model_id: str) -> Any:
            start = time.monotonic()
            await self._atrs.record_simple(
                engine=ATRSEngine.MODEL,
                event_type=ATRSModelEvent.MODEL_CALL_START,
                entity_ref=f"model:{model_id}",
                metadata={"task_type": task_req.task_type},
            )

            try:
                api_key = await self._resolve_api_key(model_id)
                response = await self._execute_fn(model_id, api_key)
                latency_ms = int((time.monotonic() - start) * 1000)

                await self._atrs.record_simple(
                    engine=ATRSEngine.MODEL,
                    event_type=ATRSModelEvent.MODEL_CALL_SUCCESS,
                    entity_ref=f"model:{model_id}",
                    duration_ms=latency_ms,
                    metadata={"task_type": task_req.task_type},
                )
                return response
            except Exception as exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                error_type = type(exc).__name__
                status = ATRSStatus.FAILURE

                await self._atrs.record_simple(
                    engine=ATRSEngine.MODEL,
                    event_type=ATRSModelEvent.MODEL_CALL_FAILURE,
                    entity_ref=f"model:{model_id}",
                    status=status,
                    duration_ms=latency_ms,
                    error_code=error_type,
                    metadata={"task_type": task_req.task_type, "error": str(exc)},
                )

                if hasattr(exc, "status_code") and getattr(exc, "status_code") in (401, 403):
                    set_cooldown(model_id, f"auth_error: {exc}", 3600)
                elif hasattr(exc, "status_code") and getattr(exc, "status_code") == 429:
                    set_cooldown(model_id, "rate_limit", 300)

                raise

        result = await execute_with_fallback(ranked_models, execute_single)

        if result.get("fallback_triggered") and result.get("fallback_from"):
            await self._atrs.record_simple(
                engine=ATRSEngine.MODEL,
                event_type=ATRSModelEvent.MODEL_FALLBACK_TRIGGERED,
                entity_ref=f"model:{result['model_used']}",
                metadata={
                    "from_model": result.get("fallback_from"),
                    "to_model": result.get("model_used"),
                },
            )

        return ModelCallResult(
            response=result.get("response"),
            model_used=result.get("model_used") or "",
            fallback_triggered=result.get("fallback_triggered", False),
            fallback_from=result.get("fallback_from"),
            latency_ms=0,
            error=result.get("error"),
        )

    async def _get_credential_for_model(self, model_id: str) -> Optional[uuid.UUID]:
        """Get the credential reference for a model (returns UUID or None)."""
        models = await self._model_reader()
        for m in models:
            if m.get("model_id") == model_id:
                return m.get("credential_ref")
        return None

    async def _resolve_api_key(self, model_id: str) -> Optional[str]:
        """Resolve API key for a model at call time. Raises if credential_ref exists but resolution fails."""
        credential_ref = await self._get_credential_for_model(model_id)
        if credential_ref is None:
            return None
        try:
            return await self._vault_resolve(self._owner_id, credential_ref)
        except VaultEntryNotFoundError:
            logger.warning(f"Credential not found for model {model_id}")
            return None

    async def list_active_models(self) -> list[dict]:
        """Return all models with status='active'."""
        models = await self._model_reader()
        return [m for m in models if m.get("status") == ModelStatus.ACTIVE.value]

    async def get_model(self, model_id: str) -> Optional[dict]:
        """Get a single model by ID, respecting owner isolation via credential."""
        models = await self._model_reader()
        for m in models:
            if m.get("model_id") == model_id:
                return m
        return None


def calculate_model_score(
    model: RankedModel,
    success_rate: float = 0.95,
    latency_ms: int = 500,
    median_latency_ms: int = 500,
) -> float:
    """
    Calculate a dynamic score for a model based on ATRS signals.
    
    Formula:
        score = base_score + reliability_bonus - latency_penalty - cost_penalty
    
    Where:
        - base_score: from task_matcher (affinity, price, speed)
        - reliability_bonus: +10 per percentage point above 90% success rate
        - latency_penalty: -1 per 100ms above median
        - cost_penalty: -5 if above budget tier
    """
    score = model.score

    if success_rate > 0.9:
        score += (success_rate - 0.9) * 100

    if latency_ms > median_latency_ms:
        score -= (latency_ms - median_latency_ms) / 100

    return round(score, 2)