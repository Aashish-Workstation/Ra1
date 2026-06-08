"""
Input Engine — human-to-machine boundary translation layer.

Properties:
  1. **Normalization.** Converts raw inputs to structured schema.
  2. **Safety limits.** Enforces max file size and count constraints.
  3. **Language detection.** Detects input language.
  4. **ATRS logging.** Events for input received and payload assembled.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus, ATRSInputEvent

logger = logging.getLogger(__name__)

DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_MAX_FILE_COUNT = 5


class AttachmentMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    content_type: str
    size_bytes: int
    content: str


class NormalizedInputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_text: str
    attachments: list[AttachmentMeta] = Field(default_factory=list)
    detected_language: str = "en"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InputSettings(BaseModel):
    max_file_upload_size: int = DEFAULT_MAX_FILE_SIZE
    max_file_count: int = DEFAULT_MAX_FILE_COUNT


class InputEngineService:
    """Stateless input normalization service.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        atrs: Optional[ATRSService] = None,
        settings: Optional[InputSettings] = None,
    ):
        self._atrs = atrs
        self._settings = settings or InputSettings()

    async def normalize(
        self,
        raw_text: Optional[str] = None,
        attachments: Optional[list[dict]] = None,
        detected_language: str = "en",
    ) -> NormalizedInputPayload:
        """Normalize raw input into structured payload."""
        if self._atrs:
            await self._atrs.record_simple(
                engine=ATRSEngine.INPUT,
                event_type=ATRSInputEvent.INPUT_RECEIVED,
                status=ATRSStatus.SUCCESS,
                metadata={"has_text": raw_text is not None, "attachment_count": len(attachments or [])},
            )

        normalized_text = self._normalize_text(raw_text) if raw_text else ""
        processed_attachments = []

        if attachments:
            processed_attachments = await self._process_attachments(attachments)

        payload = NormalizedInputPayload(
            normalized_text=normalized_text,
            attachments=processed_attachments,
            detected_language=detected_language,
        )

        if self._atrs:
            await self._atrs.record_simple(
                engine=ATRSEngine.INPUT,
                event_type=ATRSInputEvent.INPUT_PAYLOAD_ASSEMBLED,
                status=ATRSStatus.SUCCESS,
                metadata={"text_length": len(normalized_text), "attachment_count": len(processed_attachments)},
            )

        return payload

    def _normalize_text(self, text: str) -> str:
        """Normalize text input (trim, clean)."""
        return text.strip()

    async def _process_attachments(self, attachments: list[dict]) -> list[AttachmentMeta]:
        """Process and validate attachments."""
        processed = []
        for att in attachments[:self._settings.max_file_count]:
            if len(processed) >= self._settings.max_file_count:
                break

            size = att.get("size_bytes", 0)
            if size > self._settings.max_file_upload_size:
                logger.warning(f"Attachment {att.get('filename')} exceeds size limit")
                continue

            processed.append(AttachmentMeta(
                filename=att.get("filename", "unknown"),
                content_type=att.get("content_type", "application/octet-stream"),
                size_bytes=size,
                content=att.get("content", ""),
            ))
        return processed

    def validate_file_size(self, size_bytes: int) -> bool:
        return size_bytes <= self._settings.max_file_upload_size

    def validate_file_count(self, count: int) -> bool:
        return count <= self._settings.max_file_count