"""
Orchestrator — Pydantic schemas for message orchestration.

Models for the Central Orchestrator service that coordinates
the 10-phase message processing pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.context import ContextPayload
from app.models.gate import GateEvaluation
from app.models.output import OutputSynthesis
from app.models.safety import SafetyEvaluation


class MessageIntent(str, Enum):
    T0 = "T0"
    T1 = "T1"


class PipelinePhase(str, Enum):
    RECEIVE = "receive"
    CLASSIFY = "classify"
    FETCH_ASSEMBLE = "fetch_assemble"
    EXECUTE = "execute"
    INTERCEPT_GUARD = "intercept_guard"
    OUTPUT = "output"
    EVALUATE = "evaluate"
    COMMIT = "commit"
    LOG = "log"
    RETURN = "return"


class OrchestratorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    response: str = ""
    context: Optional[ContextPayload] = None
    safety_eval: Optional[SafetyEvaluation] = None
    output: Optional[OutputSynthesis] = None
    gate_eval: Optional[GateEvaluation] = None
    execution_time_ms: int = 0
    phase_results: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    habitat_id: Optional[uuid.UUID] = None
    input_text: str = ""
    intent: MessageIntent = MessageIntent.T1
    context: Optional[ContextPayload] = None
    model_response: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))