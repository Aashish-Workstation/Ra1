"""
Context Assembler — Pydantic schemas for context assembly.

Models for the Context Assembler service that fetches and packages
contextual data under a strict token budget.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ContextSource(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PERSONA = "persona"
    CONNECTOR = "connector"


class ContextChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ContextSource
    content: Any
    token_count: int
    priority: float = 1.0


class PersonaState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: Optional[uuid.UUID] = None
    name: str = ""
    profession: str = ""
    industry: str = ""
    archetype_blend: dict[str, float] = Field(default_factory=dict)
    tone_rules: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)


class WorkingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: Optional[uuid.UUID] = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    token_count: int = 0


class EpisodicContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: Optional[uuid.UUID] = None
    summary: str = ""
    key_facts: list[dict[str, Any]] = Field(default_factory=list)
    token_count: int = 0


class SemanticContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    token_count: int = 0


class ContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    working: WorkingContext
    episodic: EpisodicContext
    semantic: SemanticContext
    persona: PersonaState
    connector: Optional[dict[str, Any]] = None
    total_tokens: int = 0
    truncated: bool = False
    truncation_reason: Optional[str] = None
    assembled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContextFetchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    habitat_id: Optional[uuid.UUID] = None
    query: str = ""
    max_tokens: int = 128000