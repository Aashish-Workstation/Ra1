"""
Notification Engine — Pydantic schemas + enums.

Models for system-level state flags, exceptions, and blocks routing to user workspace.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NotificationPriority(str, Enum):
    P0_BLOCK = "P0_BLOCK"
    P1_URGENT = "P1_URGENT"
    P2_INFORM = "P2_INFORM"
    P3_NOTICE = "P3_NOTICE"
    P_SILENT = "P_SILENT"


class NotificationStatus(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    RESOLVED = "resolved"


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID | None = None
    priority: NotificationPriority
    source_engine: str
    title: str
    message: str
    status: NotificationStatus = NotificationStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    habitat_id: uuid.UUID | None = None
    priority: NotificationPriority
    source_engine: str
    title: str
    message: str


class NotificationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    notification_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID | None = None
    priority: NotificationPriority
    source_engine: str
    title: str
    message: str
    status: NotificationStatus
    created_at: datetime