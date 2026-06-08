"""
Memory Engine — Pydantic schemas + enums.

Three model kinds:
  * ``MemoryRecord``       — full storage model.
  * ``MemoryRecordCreate`` — input from API/service callers.
  * ``MemoryRecordRead``   — output to callers (without internal fields).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeType(str, Enum):
    FACT = "FACT"
    DERIVED_FACT = "DERIVED_FACT"
    HYPOTHESIS = "HYPOTHESIS"
    OPINION = "OPINION"
    RECOMMENDATION = "RECOMMENDATION"
    PROCEDURE = "PROCEDURE"
    TRACE = "TRACE"


class MemorySource(str, Enum):
    USER = "user"
    CONNECTOR = "connector"
    AGENT = "agent"
    FLOW = "flow"
    INFERENCE = "inference"


class KnowledgeLane(str, Enum):
    TEMP = "TEMP"
    SHORT = "SHORT"
    LONG = "LONG"
    SUPER = "SUPER"


class MemoryRecord(BaseModel):
    """Full row as stored in ``memory_records``."""
    model_config = ConfigDict(extra="forbid")

    entity_id:    uuid.UUID
    habitat_id:   uuid.UUID
    user_id:      uuid.UUID
    entity_type:  str
    attribute:    str
    value:        dict[str, Any]
    knowledge_type: KnowledgeType
    confidence:   float = Field(ge=0.0, le=1.0)
    source:       MemorySource
    provenance:   str
    ttl:          Optional[datetime] = None
    lock_status:  bool = False
    links:        dict[str, Any] = Field(default_factory=dict)
    created_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryRecordCreate(BaseModel):
    """Input for creating a new memory record. The service stores this as-is."""
    model_config = ConfigDict(extra="forbid")

    entity_id:    Optional[uuid.UUID] = None
    habitat_id:   uuid.UUID
    user_id:      uuid.UUID
    entity_type:  str = Field(min_length=1, max_length=128)
    attribute:    str = Field(min_length=1, max_length=128)
    value:        dict[str, Any]
    knowledge_type: KnowledgeType
    confidence:   float = Field(default=0.5, ge=0.0, le=1.0)
    source:       MemorySource
    provenance:   str
    ttl:          Optional[datetime] = None
    lock_status:  bool = False
    links:        Optional[dict[str, Any]] = None


class MemoryRecordRead(BaseModel):
    """Output of read operations."""
    model_config = ConfigDict(extra="forbid")

    entity_id:     uuid.UUID
    habitat_id:    uuid.UUID
    user_id:       uuid.UUID
    entity_type:   str
    attribute:     str
    value:         dict[str, Any]
    knowledge_type: KnowledgeType
    confidence:    float
    source:        MemorySource
    provenance:    str
    ttl:           Optional[datetime] = None
    lock_status:   bool
    links:         dict[str, Any]
    created_at:    datetime
    updated_at:    datetime


class MemoryConflict(BaseModel):
    """Represents a detected conflict between memory records."""
    model_config = ConfigDict(extra="forbid")

    entity_id:     uuid.UUID
    conflicting_id: uuid.UUID
    entity_type:   str
    attribute:     str
    existing_value: dict[str, Any]
    new_value:      dict[str, Any]


def confidence_to_lane(confidence: float) -> KnowledgeLane:
    """Map confidence score to knowledge lane."""
    if confidence >= 0.95:
        return KnowledgeLane.SUPER
    elif confidence >= 0.7:
        return KnowledgeLane.LONG
    elif confidence >= 0.5:
        return KnowledgeLane.SHORT
    else:
        return KnowledgeLane.TEMP


class MemoryIsolationError(Exception):
    """Raised when a memory operation is attempted on a record that does not
    belong to the supplied user_id/habitat_id."""
    pass


class MemoryRecordNotFoundError(Exception):
    """Raised when a memory record cannot be found."""
    pass


class MemoryConflictError(Exception):
    """Raised when a write would create a conflict with an existing record."""
    pass