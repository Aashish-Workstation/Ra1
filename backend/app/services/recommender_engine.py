"""
Recommender Engine — service layer.

Properties:
1. **Observer-style suggestions.** Analyzes ATRS logs and system metrics.
2. **Model domain.** Triggers on model.call.failure patterns.
3. **Persona domain.** Suggests blend modifications based on archetype balances.
4. **Dismissal enforcement.** Dismissed recommendations are never surfaced again.
5. **ATRS logging.** Emits recommendation.fired, recommendation.accepted, recommendation.dismissed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Set

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSRecommenderEvent, ATRSStatus
from app.models.recommender import (
    Recommendation,
    RecommendationCreate,
    RecommendationDomain,
    RecommendationRead,
    RecommendationStatus,
)

logger = logging.getLogger(__name__)

RecommendationRowWriter = Callable[[Recommendation], Awaitable[None]]
RecommendationRowReader = Callable[[uuid.UUID], Awaitable[list[Recommendation]]]
RecommendationUpdater = Callable[[uuid.UUID, dict[str, Any]], Awaitable[None]]
ATRSReader = Callable[[str, int], Awaitable[list[dict]]]


class RecommenderEngineService:
    """Service for proactive architectural optimization suggestions."""

    MODEL_FAILURE_THRESHOLD = 0.10

    def __init__(
        self,
        row_writer: RecommendationRowWriter,
        row_reader: RecommendationRowReader,
        updater: RecommendationUpdater,
        atrs: ATRSService,
        atrs_reader: Optional[ATRSReader] = None,
        dismissed_cache: Optional[Set[uuid.UUID]] = None,
    ):
        self._write = row_writer
        self._read = row_reader
        self._update = updater
        self._atrs = atrs
        self._atrs_reader = atrs_reader
        self._dismissed: Set[uuid.UUID] = dismissed_cache or set()

    async def create(self, recommendation: RecommendationCreate) -> RecommendationRead:
        now = datetime.now(timezone.utc)
        row = Recommendation(
            recommendation_id=uuid.uuid4(),
            user_id=recommendation.user_id,
            habitat_id=recommendation.habitat_id,
            domain=recommendation.domain,
            suggestion_text=recommendation.suggestion_text,
            trigger_context=recommendation.trigger_context,
            status=RecommendationStatus.ACTIVE,
            created_at=now,
        )
        await self._atrs.record_simple(
            engine=ATRSEngine.RECOMMENDER,
            event_type=ATRSRecommenderEvent.RECOMMENDATION_FIRED,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"recommendation:{row.recommendation_id}",
            metadata={
                "domain": row.domain.value,
            },
        )
        await self._write(row)
        return _to_read(row)

    async def list_for_user(self, user_id: uuid.UUID) -> list[RecommendationRead]:
        rows = await self._read(user_id)
        return [
            _to_read(r) for r in rows
            if r.recommendation_id not in self._dismissed
            and r.status == RecommendationStatus.ACTIVE
        ]

    async def accept(self, recommendation_id: uuid.UUID, user_id: uuid.UUID) -> RecommendationRead:
        await self._update(recommendation_id, {
            "status": RecommendationStatus.ACCEPTED,
            "updated_at": datetime.now(timezone.utc),
        })
        await self._atrs.record_simple(
            engine=ATRSEngine.RECOMMENDER,
            event_type=ATRSRecommenderEvent.RECOMMENDATION_ACCEPTED,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"recommendation:{recommendation_id}",
        )
        return await self._get_read(recommendation_id, user_id)

    async def dismiss(self, recommendation_id: uuid.UUID, user_id: uuid.UUID) -> RecommendationRead:
        self._dismissed.add(recommendation_id)
        await self._update(recommendation_id, {
            "status": RecommendationStatus.DISMISSED,
            "updated_at": datetime.now(timezone.utc),
        })
        await self._atrs.record_simple(
            engine=ATRSEngine.RECOMMENDER,
            event_type=ATRSRecommenderEvent.RECOMMENDATION_DISMISSED,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"recommendation:{recommendation_id}",
        )
        return await self._get_read(recommendation_id, user_id)

    async def analyze_model_failures(self, user_id: uuid.UUID) -> Optional[RecommendationRead]:
        if self._atrs_reader is None:
            return None
        rows = await self._atrs_reader("model.call.failure", 100)
        if not rows:
            return None
        failures = [r for r in rows if r.get("status") == "failure"]
        if len(failures) / max(len(rows), 1) < self.MODEL_FAILURE_THRESHOLD:
            return None
        model_ids = set(r.get("entity_ref", "").replace("model:", "") for r in failures if r.get("entity_ref"))
        if not model_ids:
            return None
        suggestion = f"Model failure rate exceeds {self.MODEL_FAILURE_THRESHOLD*100}% threshold. Consider switching from {list(model_ids)[0]} to a more reliable model or adjusting cost/reliability settings."
        return await self.create(RecommendationCreate(
            user_id=user_id,
            domain=RecommendationDomain.MODEL,
            suggestion_text=suggestion,
            trigger_context={"failure_count": len(failures), "models_affected": list(model_ids)},
        ))

    async def analyze_persona_balance(self, user_id: uuid.UUID, archetype_blend: dict[str, float]) -> Optional[RecommendationRead]:
        for archetype, weight in archetype_blend.items():
            if weight > 0.4:
                suggestion = f"Archetype '{archetype}' dominates with {weight*100:.1f}% weight. Consider rebalancing for more balanced persona behavior."
                return await self.create(RecommendationCreate(
                    user_id=user_id,
                    domain=RecommendationDomain.PERSONA,
                    suggestion_text=suggestion,
                    trigger_context={"dominant_archetype": archetype, "weight": weight},
                ))
        return None

    async def _get_read(self, recommendation_id: uuid.UUID, user_id: uuid.UUID) -> RecommendationRead:
        rows = await self._read(user_id)
        row = next((r for r in rows if r.recommendation_id == recommendation_id), None)
        if row is None:
            return None
        return _to_read(row)


def _to_read(row: Recommendation) -> RecommendationRead:
    return RecommendationRead(
        recommendation_id=row.recommendation_id,
        user_id=row.user_id,
        habitat_id=row.habitat_id,
        domain=row.domain,
        suggestion_text=row.suggestion_text,
        trigger_context=row.trigger_context,
        status=row.status,
        created_at=row.created_at,
    )