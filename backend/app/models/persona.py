"""
Persona Engine — Pydantic schemas + enums.

Models for professional identity management with archetype-driven behavior.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Archetype(str, Enum):
    BUILDER = "Builder"
    ANALYST = "Analyst"
    GUARDIAN = "Guardian"
    CAREGIVER = "Caregiver"
    CREATOR = "Creator"
    OPERATOR = "Operator"
    SCIENTIST = "Scientist"
    STRATEGIST = "Strategist"


class PersonaScope(str, Enum):
    GLOBAL = "global"
    HABITAT = "habitat"
    PRIVATE = "private"


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    profession: str
    industry: str
    archetype_blend: dict[str, float]
    tone_rules: list[str]
    rules: list[str]
    scope: PersonaScope
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode='after')
    def validate_archetype_blend(self) -> 'Persona':
        blend = self.archetype_blend
        total = sum(blend.values())
        if not abs(total - 1.0) < 0.0001:
            raise ValueError(f"archetype_blend values must sum to 1.0, got {total}")
        for key in blend:
            if key not in [a.value for a in Archetype]:
                raise ValueError(f"Invalid archetype: {key}")
        return self


class PersonaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    profession: str = Field(min_length=1, max_length=255)
    industry: str = Field(min_length=1, max_length=255)
    archetype_blend: dict[str, float]
    tone_rules: list[str] = []
    rules: list[str] = []
    scope: PersonaScope = PersonaScope.GLOBAL

    @model_validator(mode='after')
    def validate_archetype_blend(self) -> 'PersonaCreate':
        blend = self.archetype_blend
        total = sum(blend.values())
        if not abs(total - 1.0) < 0.0001:
            raise ValueError(f"archetype_blend values must sum to 1.0, got {total}")
        return self


class PersonaRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    profession: str
    industry: str
    archetype_blend: dict[str, float]
    tone_rules: list[str]
    rules: list[str]
    scope: PersonaScope