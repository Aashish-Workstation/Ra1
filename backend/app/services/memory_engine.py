"""
Memory Engine — stateless execution layer with Knowledge Arbitration Core (KAC).

Properties:
  1. **Stateless.** All state persists in the database Memory Node.
  2. **KAC pipeline.** Every write passes through arbitration.
  3. **Lock enforcement.** User-locked records cannot be modified.
  4. **Confidence promotion.** Records move across lanes based on confidence.
  5. **Conflict detection.** Opposing assertions are flagged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus
from app.models.memory import (
    KnowledgeLane,
    KnowledgeType,
    MemoryConflict,
    MemoryRecord,
    MemoryRecordCreate,
    MemoryRecordRead,
    MemorySource,
    confidence_to_lane,
)

logger = logging.getLogger(__name__)

MemoryRowWriter = Callable[[MemoryRecord], Awaitable[None]]
MemoryRowReader = Callable[[uuid.UUID, uuid.UUID, uuid.UUID], Awaitable[Optional[MemoryRecord]]]
MemoryLister = Callable[[uuid.UUID, uuid.UUID], Awaitable[list[MemoryRecord]]]
MemoryUpdater = Callable[[uuid.UUID, uuid.UUID, uuid.UUID, dict[str, Any]], Awaitable[None]]
MemoryConflictWriter = Callable[[dict[str, Any]], Awaitable[None]]


class MemoryEngineService:
    """Stateless memory engine with KAC arbitration.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        *,
        row_writer: MemoryRowWriter,
        row_reader: MemoryRowReader,
        lister: MemoryLister,
        updater: MemoryUpdater,
        atrs: ATRSService,
        conflict_writer: Optional[MemoryConflictWriter] = None,
    ):
        self._write = row_writer
        self._read = row_reader
        self._list = lister
        self._update = updater
        self._atrs = atrs
        self._conflict_log = conflict_writer

    async def propose(
        self,
        record: MemoryRecordCreate,
    ) -> tuple[MemoryRecordRead, Optional[MemoryConflict]]:
        """Propose a new memory record. Runs through KAC pipeline."""
        existing = await self._find_existing(record)
        if existing:
            return await self._handle_reinforcement(existing, record)
        return await self._handle_new_record(record)

    async def read(
        self,
        user_id: uuid.UUID,
        habitat_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> MemoryRecordRead:
        """Read a memory record with scope enforcement."""
        row = await self._read(user_id, habitat_id, entity_id)
        if row is None:
            raise MemoryRecordNotFoundError(
                f"Memory record {entity_id} not found for user {user_id}"
            )
        await self._atrs.record_simple(
            engine=ATRSEngine.MEMORY,
            event_type="memory.read",
            status=ATRSStatus.SUCCESS,
            entity_ref=f"record:{entity_id}",
            metadata={"lane": confidence_to_lane(row.confidence).value},
        )
        return _to_read(row)

    async def list_for_scope(
        self,
        user_id: uuid.UUID,
        habitat_id: uuid.UUID,
        entity_type: Optional[str] = None,
        lane: Optional[KnowledgeLane] = None,
    ) -> list[MemoryRecordRead]:
        """List records scoped to user/habitat with optional filtering."""
        rows = await self._list(user_id, habitat_id)
        result = []
        for row in rows:
            if entity_type and row.entity_type != entity_type:
                continue
            if lane and confidence_to_lane(row.confidence) != lane:
                continue
            result.append(_to_read(row))
        return result

    async def lock_record(
        self,
        user_id: uuid.UUID,
        habitat_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> MemoryRecordRead:
        """Lock a record to prevent engine modifications."""
        row = await self._read(user_id, habitat_id, entity_id)
        if row is None:
            raise MemoryRecordNotFoundError(f"Record {entity_id} not found")
        if row.lock_status:
            raise ValueError("Record is already locked")
        await self._update(user_id, habitat_id, entity_id, {"lock_status": True})
        updated = await self._read(user_id, habitat_id, entity_id)
        assert updated is not None
        return _to_read(updated)

    async def _verify_not_locked(
        self, user_id: uuid.UUID, habitat_id: uuid.UUID, entity_id: uuid.UUID
    ) -> MemoryRecord:
        """Verify record is not locked before modification. Raises if locked."""
        row = await self._read(user_id, habitat_id, entity_id)
        if row is None:
            raise MemoryRecordNotFoundError(f"Record {entity_id} not found")
        if row.lock_status:
            raise ValueError("Cannot modify locked record")
        return row

    async def _find_existing(self, record: MemoryRecordCreate) -> Optional[MemoryRecord]:
        """Find existing record with same entity_type/attribute."""
        rows = await self._list(record.user_id, record.habitat_id)
        for row in rows:
            if row.entity_type == record.entity_type and row.attribute == record.attribute:
                return row
        return None

    async def _handle_reinforcement(
        self, existing: MemoryRecord, new: MemoryRecordCreate
    ) -> tuple[MemoryRecordRead, Optional[MemoryConflict]]:
        """Handle reinforcement of an existing fact."""
        if existing.lock_status:
            await self._atrs.record_simple(
                engine=ATRSEngine.MEMORY,
                event_type="memory.write.rejected",
                status=ATRSStatus.BLOCKED,
                entity_ref=f"record:{existing.entity_id}",
                metadata={"reason": "locked_record"},
            )
            raise ValueError("Cannot modify locked record")

        conflict = None
        if self._is_opposing_fact(existing.value, new.value):
            conflict = MemoryConflict(
                entity_id=existing.entity_id,
                conflicting_id=new.entity_id if new.entity_id else uuid.uuid4(),
                entity_type=existing.entity_type,
                attribute=existing.attribute,
                existing_value=existing.value,
                new_value=new.value,
            )
            await self._log_conflict(conflict)

        new_confidence = min(1.0, max(0.0, self._calculate_reinforced_confidence(
            existing.confidence, new.confidence, new.source
        )))
        await self._update(
            existing.user_id, existing.habitat_id, existing.entity_id,
            {"value": new.value, "confidence": new_confidence, "updated_at": datetime.now(timezone.utc)},
        )
        updated = await self._read(existing.user_id, existing.habitat_id, existing.entity_id)
        assert updated is not None
        await self._atrs.record_simple(
            engine=ATRSEngine.MEMORY,
            event_type="memory.write.committed",
            status=ATRSStatus.SUCCESS,
            entity_ref=f"record:{updated.entity_id}",
            metadata={"lane": confidence_to_lane(new_confidence).value},
        )
        return _to_read(updated), conflict

    async def _handle_new_record(self, record: MemoryRecordCreate) -> tuple[MemoryRecordRead, None]:
        """Create a new memory record."""
        entity_id = record.entity_id if record.entity_id else uuid.uuid4()
        confidence = min(1.0, max(0.0, record.confidence))
        row = MemoryRecord(
            entity_id=entity_id,
            habitat_id=record.habitat_id,
            user_id=record.user_id,
            entity_type=record.entity_type,
            attribute=record.attribute,
            value=record.value,
            knowledge_type=record.knowledge_type,
            confidence=confidence,
            source=record.source,
            provenance=record.provenance,
            ttl=record.ttl,
            lock_status=record.lock_status,
            links=record.links or {},
        )
        await self._write(row)
        await self._atrs.record_simple(
            engine=ATRSEngine.MEMORY,
            event_type="memory.write.committed",
            status=ATRSStatus.SUCCESS,
            entity_ref=f"record:{entity_id}",
            metadata={
                "lane": confidence_to_lane(confidence).value,
                "knowledge_type": record.knowledge_type.value,
            },
        )
        return _to_read(row), None

    def _is_opposing_fact(self, existing: dict[str, Any], new: dict[str, Any]) -> bool:
        """Detect if two facts are opposing assertions."""
        if existing == new:
            return False
        if isinstance(existing, dict) and isinstance(new, dict):
            for key in existing:
                if key in new and existing[key] != new[key]:
                    return True
        return False

    def _calculate_reinforced_confidence(
        self, existing: float, new: float, source: MemorySource
    ) -> float:
        """Calculate new confidence when a fact is reinforced."""
        source_weight = 0.3 if source == MemorySource.USER else 0.1
        new_conf = min(1.0, existing + 0.2 + source_weight)
        return round(new_conf, 3)

    async def _log_conflict(self, conflict: MemoryConflict) -> None:
        """Log conflict to ATRS."""
        await self._atrs.record_simple(
            engine=ATRSEngine.MEMORY,
            event_type="memory.conflict.detected",
            status=ATRSStatus.SUCCESS,
            entity_ref=f"record:{conflict.entity_id}",
            metadata={
                "conflicting_id": str(conflict.conflicting_id),
                "entity_type": conflict.entity_type,
                "attribute": conflict.attribute,
            },
        )
        if self._conflict_log:
            await self._conflict_log(conflict.model_dump(mode='json'))


def _to_read(row: MemoryRecord) -> MemoryRecordRead:
    """Convert storage model to read model."""
    return MemoryRecordRead(
        entity_id=row.entity_id,
        habitat_id=row.habitat_id,
        user_id=row.user_id,
        entity_type=row.entity_type,
        attribute=row.attribute,
        value=row.value,
        knowledge_type=row.knowledge_type,
        confidence=row.confidence,
        source=row.source,
        provenance=row.provenance,
        ttl=row.ttl,
        lock_status=row.lock_status,
        links=row.links,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )