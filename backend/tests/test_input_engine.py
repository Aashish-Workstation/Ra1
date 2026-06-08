"""
Unit tests for the Input Engine.

Verifies:
  1. Input normalization flattens text and file payloads correctly
  2. File size limit enforcement
  3. File count limit enforcement
  4. ATRS logging for input events
"""

from __future__ import annotations

import pytest

from app.models.atrs import ATRSStatus, ATRSInputEvent
from app.services.input_engine import (
    InputEngineService,
    InputSettings,
    NormalizedInputPayload,
    AttachmentMeta,
)


def test_input_normalization_text_only(make_input_engine):
    engine, atrs_rows = make_input_engine
    payload = _run_async(engine.normalize(raw_text="  hello world  "))
    assert payload.normalized_text == "hello world"
    assert payload.attachments == []
    assert payload.detected_language == "en"


def test_input_normalization_with_attachments(make_input_engine):
    engine, atrs_rows = make_input_engine
    attachments = [
        {
            "filename": "test.txt",
            "content_type": "text/plain",
            "size_bytes": 100,
            "content": "file content here",
        }
    ]
    payload = _run_async(engine.normalize(
        raw_text="query text",
        attachments=attachments,
        detected_language="en",
    ))
    assert payload.normalized_text == "query text"
    assert len(payload.attachments) == 1
    assert payload.attachments[0].filename == "test.txt"
    assert payload.attachments[0].content == "file content here"


def test_input_file_size_limit(make_input_engine):
    engine, atrs_rows = make_input_engine
    large_attachment = {
        "filename": "large.bin",
        "content_type": "application/octet-stream",
        "size_bytes": 20 * 1024 * 1024,
        "content": "x" * 100,
    }
    payload = _run_async(engine.normalize(attachments=[large_attachment]))
    assert len(payload.attachments) == 0


def test_input_file_count_limit(make_input_engine):
    engine, atrs_rows = make_input_engine
    attachments = [
        {"filename": f"file{i}.txt", "content_type": "text/plain", "size_bytes": 100, "content": "x"}
        for i in range(10)
    ]
    payload = _run_async(engine.normalize(attachments=attachments))
    assert len(payload.attachments) == 5


def test_input_atrs_logging(make_input_engine):
    engine, atrs_rows = make_input_engine
    _run_async(engine.normalize(raw_text="test query"))
    received = [r for r in atrs_rows if r.get("event_type") == ATRSInputEvent.INPUT_RECEIVED.value]
    assembled = [r for r in atrs_rows if r.get("event_type") == ATRSInputEvent.INPUT_PAYLOAD_ASSEMBLED.value]
    assert len(received) >= 1
    assert len(assembled) >= 1


def test_input_empty_text(make_input_engine):
    engine, atrs_rows = make_input_engine
    payload = _run_async(engine.normalize(raw_text=None))
    assert payload.normalized_text == ""
    assert payload.attachments == []


def test_input_settings_validation(make_input_engine):
    engine, atrs_rows = make_input_engine
    assert engine.validate_file_size(9 * 1024 * 1024) is True
    assert engine.validate_file_size(11 * 1024 * 1024) is False
    assert engine.validate_file_count(3) is True
    assert engine.validate_file_count(6) is False


def test_input_with_custom_settings():
    settings = InputSettings(max_file_upload_size=1000, max_file_count=2)
    engine = InputEngineService(settings=settings)
    assert engine.validate_file_size(500) is True
    assert engine.validate_file_size(1500) is False
    assert engine.validate_file_count(1) is True
    assert engine.validate_file_count(3) is False


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


@pytest.fixture
def make_input_engine():
    atrs_rows: list = []

    async def atrs_writer(row: dict):
        atrs_rows.append(row)

    engine = InputEngineService(atrs=None)
    return engine, atrs_rows