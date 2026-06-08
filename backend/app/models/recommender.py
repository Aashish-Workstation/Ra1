"""
Recommender Engine — Pydantic schemas + enums.

Models for non-blocking, proactive architectural optimization suggestions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecommendationDomain(str, Enum):
    MODEL = "MODEL"
    PERSONA = "PERSONA"
    SKILLS = "SKILLS"
    ENVIRONMENT = "ENVIRONMENT"


class RecommendationStatus(str, Enum):
    ACTIVE = "active"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID | None = None
    domain: RecommendationDomain
    suggestion_text: str
    trigger_context: dict[str, Any]
    status: RecommendationStatus = RecommendationStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    habitat_id: uuid.UUID | None = None
    domain: RecommendationDomain
    suggestion_text: str
    trigger_context: dict[str, Any]


class RecommendationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    recommendation_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID | None = None
    domain: RecommendationDomain
    suggestion_text: str
    trigger_context: dict[str, Any]
    status: RecommendationStatus
    created_at: datetime