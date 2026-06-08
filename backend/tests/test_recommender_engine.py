"""
Unit tests for the Recommender Engine.

Verifies:
1. Dismissed recommendations are blocked from re-display
2. Model failure recommendations trigger on ATRS error rate thresholds
3. Persona blend suggestions trigger on archetype drift
4. ATRS logging for recommendation.fired/accepted/dismissed
"""

from __future__ import annotations

import uuid

import pytest

from app.models.recommender import (
    RecommendationDomain,
    RecommendationStatus,
)
from app.models.atrs import ATRSRecommenderEvent


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


def test_dismissed_recommendations_blocked(make_recommender):
    service, pool, atrs_rows, _outbox, dismissed = make_recommender
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.recommender import RecommendationCreate
    recommendation = asyncio_run(service.create(RecommendationCreate(
        user_id=user_id,
        domain=RecommendationDomain.MODEL,
        suggestion_text="Test suggestion",
        trigger_context={"test": "context"},
    )))
    assert recommendation.status == RecommendationStatus.ACTIVE

    asyncio_run(service.dismiss(recommendation.recommendation_id, user_id))
    assert recommendation.recommendation_id in dismissed

    list_result = asyncio_run(service.list_for_user(user_id))
    assert len(list_result) == 0


def test_model_failure_triggers_recommendation(make_recommender):
    service, pool, atrs_rows, _outbox, dismissed = make_recommender
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    for _ in range(15):
        atrs_rows.append({
            "event_type": "model.call.failure",
            "status": "failure",
            "entity_ref": "model:gpt-4",
            "metadata": {},
        })

    result = asyncio_run(service.analyze_model_failures(user_id))
    assert result is not None
    assert result.domain == RecommendationDomain.MODEL
    assert "failure rate" in result.suggestion_text.lower() or "reliability" in result.suggestion_text.lower()


def test_persona_blend_suggestion(make_recommender):
    service, pool, atrs_rows, _outbox, dismissed = make_recommender
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.recommender import RecommendationCreate
    result = asyncio_run(service.analyze_persona_balance(
        user_id=user_id,
        archetype_blend={"Builder": 0.6, "Analyst": 0.4},
    ))
    assert result is not None
    assert result.domain == RecommendationDomain.PERSONA


def test_atrs_logging_recommendation_fired(make_recommender):
    service, pool, atrs_rows, _outbox, dismissed = make_recommender
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.recommender import RecommendationCreate
    recommendation = asyncio_run(service.create(RecommendationCreate(
        user_id=user_id,
        domain=RecommendationDomain.MODEL,
        suggestion_text="Test suggestion",
        trigger_context={"test": "context"},
    )))

    fired_events = [
        r for r in atrs_rows
        if r.get("event_type") == ATRSRecommenderEvent.RECOMMENDATION_FIRED.value
    ]
    assert len(fired_events) >= 1
    assert fired_events[-1]["status"] == "success"


def test_atrs_logging_recommendation_accepted(make_recommender):
    service, pool, atrs_rows, _outbox, dismissed = make_recommender
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.recommender import RecommendationCreate
    recommendation = asyncio_run(service.create(RecommendationCreate(
        user_id=user_id,
        domain=RecommendationDomain.MODEL,
        suggestion_text="Test suggestion",
        trigger_context={"test": "context"},
    )))

    atrs_rows.clear()

    asyncio_run(service.accept(recommendation.recommendation_id, user_id))

    accepted_events = [
        r for r in atrs_rows
        if r.get("event_type") == ATRSRecommenderEvent.RECOMMENDATION_ACCEPTED.value
    ]
    assert len(accepted_events) >= 1


def test_atrs_logging_recommendation_dismissed(make_recommender):
    service, pool, atrs_rows, _outbox, dismissed = make_recommender
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.recommender import RecommendationCreate
    recommendation = asyncio_run(service.create(RecommendationCreate(
        user_id=user_id,
        domain=RecommendationDomain.MODEL,
        suggestion_text="Test suggestion",
        trigger_context={"test": "context"},
    )))

    atrs_rows.clear()

    asyncio_run(service.dismiss(recommendation.recommendation_id, user_id))

    dismissed_events = [
        r for r in atrs_rows
        if r.get("event_type") == ATRSRecommenderEvent.RECOMMENDATION_DISMISSED.value
    ]
    assert len(dismissed_events) >= 1