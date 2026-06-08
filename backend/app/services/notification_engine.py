"""
Notification Engine — service layer.

Properties:
1. **Priority routing.** P0_BLOCK and P1_URGENT always break through immediately.
2. **Quiet hours.** P2_INFORM and P3_NOTICE are held/queued during quiet hours window.
3. **ATRS logging.** Emits notification.received and notification.delivered events.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSNotificationEvent, ATRSStatus
from app.models.notification import (
    Notification,
    NotificationCreate,
    NotificationPriority,
    NotificationRead,
    NotificationStatus,
)

logger = logging.getLogger(__name__)

NotificationRowWriter = Callable[[Notification], Awaitable[None]]
NotificationRowReader = Callable[[uuid.UUID], Awaitable[list[Notification]]]
NotificationUpdater = Callable[[uuid.UUID, dict[str, Any]], Awaitable[None]]


class NotificationEngineService:
    """Service for system-level notifications with priority routing and quiet hours."""

    DEFAULT_QUIET_HOURS_START = time(22, 0)
    DEFAULT_QUIET_HOURS_END = time(8, 0)

    def __init__(
        self,
        row_writer: NotificationRowWriter,
        row_reader: NotificationRowReader,
        updater: NotificationUpdater,
        atrs: ATRSService,
        quiet_hours_start: Optional[time] = None,
        quiet_hours_end: Optional[time] = None,
    ):
        self._write = row_writer
        self._read = row_reader
        self._update = updater
        self._atrs = atrs
        self._quiet_start = quiet_hours_start or self.DEFAULT_QUIET_HOURS_START
        self._quiet_end = quiet_hours_end or self.DEFAULT_QUIET_HOURS_END

    def _is_quiet_hours(self) -> bool:
        now = datetime.now(timezone.utc).time()
        if self._quiet_start < self._quiet_end:
            return self._quiet_start <= now < self._quiet_end
        else:
            return now >= self._quiet_start or now < self._quiet_end

    def _should_deliver_immediately(self, priority: NotificationPriority) -> bool:
        return priority in (NotificationPriority.P0_BLOCK, NotificationPriority.P1_URGENT)

    async def create(self, notification: NotificationCreate) -> NotificationRead:
        now = datetime.now(timezone.utc)
        row = Notification(
            notification_id=uuid.uuid4(),
            user_id=notification.user_id,
            habitat_id=notification.habitat_id,
            priority=notification.priority,
            source_engine=notification.source_engine,
            title=notification.title,
            message=notification.message,
            status=NotificationStatus.QUEUED,
            created_at=now,
        )
        await self._atrs.record_simple(
            engine=ATRSEngine.NOTIFICATION,
            event_type=ATRSNotificationEvent.NOTIFICATION_RECEIVED,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"notification:{row.notification_id}",
            metadata={
                "priority": row.priority.value,
                "source_engine": row.source_engine,
            },
        )
        await self._write(row)
        return _to_read(row)

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationRead]:
        rows = await self._read(user_id)
        return [_to_read(r) for r in rows]

    async def deliver(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> NotificationRead:
        notifications = await self._read(user_id)
        row = next((n for n in notifications if (n.notification_id if hasattr(n, 'notification_id') else uuid.UUID(n['notification_id'])) == notification_id), None)
        if row is None:
            return None
        await self._update(notification_id, {
            "status": NotificationStatus.DELIVERED,
            "updated_at": datetime.now(timezone.utc),
        })
        await self._atrs.record_simple(
            engine=ATRSEngine.NOTIFICATION,
            event_type=ATRSNotificationEvent.NOTIFICATION_DELIVERED,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"notification:{notification_id}",
        )
        notifications = await self._read(user_id)
        row = next((n for n in notifications if (n.notification_id if hasattr(n, 'notification_id') else uuid.UUID(n['notification_id'])) == notification_id), None)
        return _to_read(row) if row else None

    async def process_pending(self, user_id: uuid.UUID) -> list[NotificationRead]:
        notifications = await self._read(user_id)
        pending = [
            n for n in notifications
            if n.status == NotificationStatus.QUEUED
        ]
        delivered = []
        for n in pending:
            if self._should_deliver_immediately(n.priority):
                await self.deliver(n.notification_id, user_id)
                delivered.append(n)
            elif not self._is_quiet_hours():
                await self.deliver(n.notification_id, user_id)
                delivered.append(n)
        return delivered


def _to_read(row) -> NotificationRead:
    if isinstance(row, NotificationRead):
        return row
    if isinstance(row, dict):
        return NotificationRead(
            notification_id=uuid.UUID(row["notification_id"]),
            user_id=uuid.UUID(row["user_id"]),
            habitat_id=uuid.UUID(row["habitat_id"]) if row.get("habitat_id") else None,
            priority=row["priority"] if isinstance(row["priority"], NotificationPriority) else NotificationPriority(row["priority"]),
            source_engine=row["source_engine"],
            title=row["title"],
            message=row["message"],
            status=row["status"] if isinstance(row["status"], NotificationStatus) else NotificationStatus(row["status"]),
            created_at=row["created_at"],
        )
    return NotificationRead(
        notification_id=row.notification_id,
        user_id=row.user_id,
        habitat_id=row.habitat_id,
        priority=row.priority,
        source_engine=row.source_engine,
        title=row.title,
        message=row.message,
        status=row.status,
        created_at=row.created_at,
    )
    return NotificationRead(
        notification_id=row.notification_id,
        user_id=row.user_id,
        habitat_id=row.habitat_id,
        priority=row.priority,
        source_engine=row.source_engine,
        title=row.title,
        message=row.message,
        status=row.status,
        created_at=row.created_at,
    )