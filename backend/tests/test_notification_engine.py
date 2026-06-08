"""
Unit tests for the Notification Engine.

Verifies:
1. P0_BLOCK notifications bypass quiet hours and deliver immediately
2. P2_INFORM notifications are held during quiet hours
3. P1_URGENT notifications bypass quiet hours
4. Notification status transitions (queued → delivered)
5. ATRS logging for notification.received and notification.delivered
"""

from __future__ import annotations

import uuid
from datetime import time

import pytest

from app.models.notification import (
    NotificationPriority,
    NotificationStatus,
)
from app.models.atrs import ATRSNotificationEvent


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


def test_p0_bypasses_quiet_hours(make_notification):
    service, pool, atrs_rows, _outbox = make_notification
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.notification import NotificationCreate
    notification = asyncio_run(service.create(NotificationCreate(
        user_id=user_id,
        priority=NotificationPriority.P0_BLOCK,
        source_engine="test_engine",
        title="Critical Alert",
        message="System failure detected",
    )))
    assert notification.status == NotificationStatus.QUEUED

    delivered = asyncio_run(service.process_pending(user_id))
    assert len(delivered) == 1
    assert delivered[0].status == NotificationStatus.DELIVERED


def test_p2_held_during_quiet_hours(make_notification):
    service, pool, atrs_rows, _outbox = make_notification
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.notification import NotificationCreate
    notification = asyncio_run(service.create(NotificationCreate(
        user_id=user_id,
        priority=NotificationPriority.P2_INFORM,
        source_engine="test_engine",
        title="Info Alert",
        message="Routine update available",
    )))
    assert notification.status == NotificationStatus.QUEUED

    original_quiet = service._quiet_start, service._quiet_end
    service._quiet_start = time(0, 0)
    service._quiet_end = time(23, 59)

    delivered = asyncio_run(service.process_pending(user_id))
    assert len(delivered) == 0

    service._quiet_start, service._quiet_end = original_quiet

    delivered = asyncio_run(service.process_pending(user_id))
    assert len(delivered) == 1
    assert delivered[0].status == NotificationStatus.DELIVERED


def test_p1_delivers_immediately(make_notification):
    service, pool, atrs_rows, _outbox = make_notification
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.notification import NotificationCreate
    notification = asyncio_run(service.create(NotificationCreate(
        user_id=user_id,
        priority=NotificationPriority.P1_URGENT,
        source_engine="test_engine",
        title="Urgent Alert",
        message="Action required",
    )))
    assert notification.status == NotificationStatus.QUEUED

    delivered = asyncio_run(service.process_pending(user_id))
    assert len(delivered) == 1
    assert delivered[0].status == NotificationStatus.DELIVERED


def test_notification_status_transitions(make_notification):
    service, pool, atrs_rows, _outbox = make_notification
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.notification import NotificationCreate
    notification = asyncio_run(service.create(NotificationCreate(
        user_id=user_id,
        priority=NotificationPriority.P2_INFORM,
        source_engine="test_engine",
        title="Test",
        message="Test message",
    )))
    assert notification.status == NotificationStatus.QUEUED

    delivered = asyncio_run(service.deliver(notification.notification_id, user_id))
    assert delivered.status == NotificationStatus.DELIVERED


def test_atrs_logging_notification_received(make_notification):
    service, pool, atrs_rows, _outbox = make_notification
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.notification import NotificationCreate
    notification = asyncio_run(service.create(NotificationCreate(
        user_id=user_id,
        priority=NotificationPriority.P0_BLOCK,
        source_engine="test_engine",
        title="Test",
        message="Test message",
    )))

    received_events = [
        r for r in atrs_rows
        if r.get("event_type") == ATRSNotificationEvent.NOTIFICATION_RECEIVED.value
    ]
    assert len(received_events) >= 1
    assert received_events[-1]["status"] == "success"


def test_atrs_logging_notification_delivered(make_notification):
    service, pool, atrs_rows, _outbox = make_notification
    user_id = uuid.uuid4()
    asyncio_run = _run_async

    from app.models.notification import NotificationCreate
    notification = asyncio_run(service.create(NotificationCreate(
        user_id=user_id,
        priority=NotificationPriority.P0_BLOCK,
        source_engine="test_engine",
        title="Test",
        message="Test message",
    )))

    atrs_rows.clear()

    asyncio_run(service.deliver(notification.notification_id, user_id))

    delivered_events = [
        r for r in atrs_rows
        if r.get("event_type") == ATRSNotificationEvent.NOTIFICATION_DELIVERED.value
    ]
    assert len(delivered_events) >= 1
    assert delivered_events[-1]["status"] == "success"