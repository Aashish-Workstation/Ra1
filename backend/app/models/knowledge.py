"""
Knowledge Base — Pydantic schemas for curated knowledge assets.

Models for explicit user-curated knowledge (documents, notes, web clips, structured data).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ContentType(str, Enum):
    DOCUMENT = "document"
    NOTE = "note"
    WEB_CLIP = "web_clip"
    STRUCTURED = "structured"


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID
    content_type: ContentType
    content: dict[str, Any] | str
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    habitat_id: uuid.UUID
    content_type: ContentType
    content: dict[str, Any] | str
    tags: list[str] = []
    collections: list[str] = []


class KnowledgeItemRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID
    content_type: ContentType
    content: dict[str, Any] | str
    tags: list[str]
    collections: list[str]
    created_at: datetime
    updated_at: datetime


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    score: float = Field(ge=0.0, le=1.0)
    content_preview: str
    content_type: ContentType