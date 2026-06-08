"""
Model Engine — Pydantic schemas for model catalog and status lifecycle.

Model nodes represent AI models available in the catalog with their metadata,
capabilities, and credential references.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ModelStatus(str, Enum):
    """Lifecycle states for models in the catalog."""
    DISCOVERED   = "discovered"
    ACTIVE       = "active"
    DEPRECATED   = "deprecated"
    REMOVED      = "removed"


class AccountType(str, Enum):
    """Account types for billing/guard layer."""
    FREE   = "free"
    PRO    = "pro"
    BYOK   = "byok"


class ModelNode(BaseModel):
    """Full row as stored in ``model_catalog``. Includes encrypted credential reference."""
    model_config = ConfigDict(extra="forbid")

    model_id:           str
    provider:           str
    display_name:       str
    status:             ModelStatus = ModelStatus.ACTIVE
    capabilities:       list[str] = Field(default_factory=list)
    credential_ref:     Optional[uuid.UUID] = None
    context_window:     int = 0
    input_price:        float = 0.0
    output_price:       float = 0.0
    speed:              str = "standard"
    created_at:         datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:         datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelNodeCreate(BaseModel):
    """Input for creating a new model entry."""
    model_config = ConfigDict(extra="forbid")

    model_id:         str
    provider:         str
    display_name:     str
    capabilities:     list[str] = Field(default_factory=list)
    credential_ref:   Optional[uuid.UUID] = None
    context_window:   int = 0
    input_price:      float = 0.0
    output_price:     float = 0.0
    speed:            str = "standard"
    status:           ModelStatus = ModelStatus.ACTIVE


class ModelNodeRead(BaseModel):
    """Output model — exposes metadata without internal details."""
    model_config = ConfigDict(extra="forbid")

    model_id:       str
    provider:       str
    display_name:   str
    status:         ModelStatus
    capabilities:   list[str]
    context_window: int
    input_price:    float
    output_price:   float
    speed:          str