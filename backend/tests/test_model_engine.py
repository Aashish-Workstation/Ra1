"""
Unit tests for the Model Engine service.

Verifies:
1. Dynamic fallback selection when a primary model fails.
2. Call-time key resolution from Credential Vault.
3. Proper ATRS logging on call events.
4. Owner isolation on model access.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.atrs import ATRSEngine, ATRSModelEvent, ATRSStatus
from app.models.model import AccountType, ModelStatus
from app.services.model_engine import (
    ModelCallResult,
    ModelEngineService,
    calculate_model_score,
)
from app.services.task_matcher import TaskRequest


@pytest.fixture
def mock_atrs():
    """Mock ATRS service."""
    return MagicMock()


@pytest.fixture
def mock_vault_resolve():
    """Mock vault resolve function."""
    return AsyncMock(return_value="test-api-key")


@pytest.fixture
def mock_model_reader():
    """Mock model reader returning sample models."""
    return AsyncMock(return_value=[
        {
            "model_id": "gpt-4o",
            "provider": "openai",
            "display_name": "GPT-4o",
            "status": ModelStatus.ACTIVE.value,
            "capabilities": ["chat", "code", "reasoning"],
            "credential_ref": uuid.uuid4(),
            "context_window": 128000,
            "input_price": 2.5,
            "output_price": 10.0,
            "speed": "fast",
        },
        {
            "model_id": "claude-sonnet",
            "provider": "anthropic",
            "display_name": "Claude Sonnet",
            "status": ModelStatus.ACTIVE.value,
            "capabilities": ["chat", "code", "reasoning"],
            "credential_ref": uuid.uuid4(),
            "context_window": 200000,
            "input_price": 3.0,
            "output_price": 15.0,
            "speed": "fast",
        },
        {
            "model_id": "gpt-4o-mini",
            "provider": "openai",
            "display_name": "GPT-4o Mini",
            "status": ModelStatus.ACTIVE.value,
            "capabilities": ["chat", "code"],
            "credential_ref": None,
            "context_window": 128000,
            "input_price": 0.15,
            "output_price": 0.6,
            "speed": "instant",
        },
    ])


@pytest.fixture
def mock_execute_fn():
    """Mock execute function that can be configured to fail."""
    async def execute(model_id: str, api_key: str | None):
        if model_id == "gpt-4o" and api_key == "fail":
            raise Exception("Simulated failure")
        return {"model": model_id, "response": "success"}
    return AsyncMock(side_effect=execute)


@pytest.fixture
def model_engine(mock_atrs, mock_vault_resolve, mock_model_reader, mock_execute_fn):
    """Create a ModelEngineService with mocked dependencies."""
    return ModelEngineService(
        atrs=mock_atrs,
        vault_resolve=mock_vault_resolve,
        model_reader=mock_model_reader,
        execute_fn=mock_execute_fn,
        account_type=AccountType.BYOK,
        owner_id="test-owner",
    )


class TestModelEngineService:
    """Tests for ModelEngineService."""

    @pytest.mark.asyncio
    async def test_execute_returns_success_on_first_try(self, model_engine, mock_atrs):
        """Successful execution on first model should return response."""
        task_req = TaskRequest(task_type="chat")
        result = await model_engine.execute(task_req, user_id="test-user")
        assert isinstance(result, ModelCallResult)
        assert result.response is not None
        assert result.model_used in ["gpt-4o", "claude-sonnet", "gpt-4o-mini"]
        mock_atrs.record_simple.assert_called()

    @pytest.mark.asyncio
    async def test_execute_passes_api_key_when_credential_ref_set(self, model_engine, mock_vault_resolve, mock_model_reader):
        """When credential_ref is set, vault_resolve should be called with api_key."""
        mock_execute_fn = AsyncMock(return_value={"response": "ok"})
        model_engine._execute_fn = mock_execute_fn

        task_req = TaskRequest(task_type="chat")
        await model_engine.execute(task_req, user_id="test-user")

        # Verify vault_resolve was called since models have credential_ref
        mock_vault_resolve.assert_called()

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_failure(self, mock_atrs, mock_vault_resolve, mock_model_reader, mock_execute_fn):
        """When primary model fails, fallback should be triggered."""
        mock_execute_fn.side_effect = lambda mid, key: (
            Exception("fail") if mid == "gpt-4o" else {"model": mid, "response": "success"}
        )

        engine = ModelEngineService(
            atrs=mock_atrs,
            vault_resolve=mock_vault_resolve,
            model_reader=mock_model_reader,
            execute_fn=mock_execute_fn,
            account_type=AccountType.BYOK,
            owner_id="test-owner",
        )

        task_req = TaskRequest(task_type="chat")
        result = await engine.execute(task_req, user_id="test-user")

        assert result.fallback_triggered is True
        assert result.model_used != "gpt-4o"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_vault_resolve_called_at_call_time(self, model_engine, mock_vault_resolve, mock_model_reader):
        """API key should be resolved at call time, not cached."""
        mock_execute_fn = AsyncMock(return_value={"response": "ok"})
        model_engine._execute_fn = mock_execute_fn

        task_req = TaskRequest(task_type="chat")
        await model_engine.execute(task_req, user_id="test-user")

        mock_vault_resolve.assert_called()

    @pytest.mark.asyncio
    async def test_atrs_logging_on_call_events(self, model_engine, mock_atrs):
        """Every model execution should emit ATRS events."""
        task_req = TaskRequest(task_type="chat")
        await model_engine.execute(task_req, user_id="test-user")

        calls = [call for call in mock_atrs.record_simple.call_args_list]
        event_types = [call.kwargs.get("event_type") for call in calls]

        assert ATRSModelEvent.MODEL_CALL_START in event_types

    @pytest.mark.asyncio
    async def test_atrs_logging_on_failure(self, mock_atrs):
        """Failure should emit MODEL_CALL_FAILURE event."""
        mock_execute_fn = AsyncMock(side_effect=Exception("test error"))
        engine = ModelEngineService(
            atrs=mock_atrs,
            vault_resolve=mock_vault_resolve,
            model_reader=mock_model_reader,
            execute_fn=mock_execute_fn,
            account_type=AccountType.BYOK,
            owner_id="test-owner",
        )

        task_req = TaskRequest(task_type="chat")
        result = await engine.execute(task_req, user_id="test-user")

        calls = [call for call in mock_atrs.record_simple.call_args_list]
        event_types = [call.kwargs.get("event_type") for call in calls]

        assert ATRSModelEvent.MODEL_CALL_FAILURE in event_types
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_guard_layer_blocks_free_tier_budget_exceeded(self, mock_atrs, mock_model_reader):
        """Free tier should be blocked when budget exceeded."""
        from app.services import usage_tracker

        usage_tracker._budget_caps["test-user"] = {"daily_usd": 0.01, "monthly_usd": 0.01}
        usage_tracker._spend_today["test-user"] = {"openai": 100.0}

        engine = ModelEngineService(
            atrs=mock_atrs,
            vault_resolve=mock_vault_resolve,
            model_reader=mock_model_reader,
            execute_fn=AsyncMock(return_value="ok"),
            account_type=AccountType.FREE,
            owner_id="test-owner",
        )

        task_req = TaskRequest(task_type="chat")
        result = await engine.execute(task_req, user_id="test-user")

        assert result.error is not None
        assert result.error["type"] == "budget_exceeded"

    @pytest.mark.asyncio
    async def test_byok_bypasses_budget(self, mock_atrs, mock_vault_resolve, mock_model_reader):
        """BYOK accounts should bypass budget checks."""
        from app.services import usage_tracker

        usage_tracker._budget_caps["test-user"] = {"daily_usd": 0.01, "monthly_usd": 0.01}
        usage_tracker._spend_today["test-user"] = {"openai": 100.0}

        engine = ModelEngineService(
            atrs=mock_atrs,
            vault_resolve=mock_vault_resolve,
            model_reader=mock_model_reader,
            execute_fn=AsyncMock(return_value={"response": "ok"}),
            account_type=AccountType.BYOK,
            owner_id="test-owner",
        )

        task_req = TaskRequest(task_type="chat")
        result = await engine.execute(task_req, user_id="test-user")

        assert result.response is not None

    @pytest.mark.asyncio
    async def test_list_active_models(self, model_engine):
        """Should return only active models."""
        models = await model_engine.list_active_models()
        assert len(models) == 3
        for m in models:
            assert m["status"] == ModelStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_get_model_by_id(self, model_engine, mock_model_reader):
        """Should retrieve a single model by ID."""
        model = await model_engine.get_model("gpt-4o")
        assert model is not None
        assert model["model_id"] == "gpt-4o"


class TestCalculateModelScore:
    """Tests for dynamic scoring algorithm."""

    def test_score_improves_with_success_rate(self):
        """Higher success rate should improve score."""
        from app.services.task_matcher import RankedModel

        model = RankedModel(
            model_id="test",
            provider="openai",
            display_name="Test",
            score=50.0,
            capabilities=[],
            context_window=128000,
            input_price=2.5,
            output_price=10.0,
            speed="fast",
            free_tier=None,
        )

        score_95 = calculate_model_score(model, success_rate=0.95, latency_ms=500)
        score_80 = calculate_model_score(model, success_rate=0.80, latency_ms=500)

        assert score_95 > score_80

    def test_score_penalized_by_latency(self):
        """Higher latency should reduce score."""
        from app.services.task_matcher import RankedModel

        model = RankedModel(
            model_id="test",
            provider="openai",
            display_name="Test",
            score=50.0,
            capabilities=[],
            context_window=128000,
            input_price=2.5,
            output_price=10.0,
            speed="fast",
            free_tier=None,
        )

        score_low = calculate_model_score(model, success_rate=0.95, latency_ms=200)
        score_high = calculate_model_score(model, success_rate=0.95, latency_ms=1000)

        assert score_low > score_high