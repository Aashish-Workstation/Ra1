"""
Persona Engine — stateless execution layer for identity management.

Properties:
  1. **Stateless.** All profiles load from or update to the DB node.
  2. **Dynamic blend shifts.** Context tracking updates minor weights.
  3. **Major switch detection.** Threshold crossings propose persona switches.
  4. **ATRS logging.** Events for load, blend update, and manual switch.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus, ATRSPersonaEvent
from app.models.persona import (
    Archetype,
    Persona,
    PersonaCreate,
    PersonaRead,
    PersonaScope,
)

logger = logging.getLogger(__name__)

PersonaRowReader = Callable[[uuid.UUID, Optional[uuid.UUID]], Awaitable[Optional[Persona]]]
PersonaRowWriter = Callable[[Persona], Awaitable[None]]
PersonaUpdater = Callable[[uuid.UUID, dict[str, Any]], Awaitable[None]]
PersonaLister = Callable[[uuid.UUID], Awaitable[list[Persona]]]


class PersonaEngineService:
    """Stateless persona engine with archetype-driven behavior.

    Construct one instance at app startup. Share across requests.
    """

    BLEND_SHIFT_THRESHOLD = 0.15

    def __init__(
        self,
        row_reader: PersonaRowReader,
        row_writer: PersonaRowWriter,
        updater: PersonaUpdater,
        lister: PersonaLister,
        atrs: ATRSService,
    ):
        self._read = row_reader
        self._write = row_writer
        self._update = updater
        self._lister = lister
        self._atrs = atrs

    async def load_persona(
        self,
        user_id: uuid.UUID,
        habitat_id: Optional[uuid.UUID] = None,
    ) -> Optional[PersonaRead]:
        """Load persona with scope precedence: private > habitat > global."""
        scopes = [PersonaScope.PRIVATE, PersonaScope.HABITAT, PersonaScope.GLOBAL]

        for scope in scopes:
            persona = await self._read(user_id, habitat_id if scope == PersonaScope.HABITAT else None)
            if persona is not None:
                if scope == PersonaScope.HABITAT and habitat_id is not None:
                    pass
                await self._atrs.record_simple(
                    engine=ATRSEngine.PERSONA,
                    event_type=ATRSPersonaEvent.PERSONA_LOADED,
                    status=ATRSStatus.SUCCESS,
                    entity_ref=f"persona:{persona.persona_id}",
                    metadata={
                        "scope": persona.scope.value,
                        "profession": persona.profession,
                    },
                )
                return _to_read(persona)
        return None

    async def create(
        self,
        user_id: uuid.UUID,
        persona: PersonaCreate,
    ) -> PersonaRead:
        """Create a new persona profile."""
        now = datetime.now(timezone.utc)
        row = Persona(
            persona_id=uuid.uuid4(),
            user_id=user_id,
            name=persona.name,
            profession=persona.profession,
            industry=persona.industry,
            archetype_blend=persona.archetype_blend,
            tone_rules=persona.tone_rules,
            rules=persona.rules,
            scope=persona.scope,
            created_at=now,
            updated_at=now,
        )
        await self._write(row)
        return _to_read(row)

    async def update_blend(
        self,
        persona_id: uuid.UUID,
        context_updates: dict[str, float],
    ) -> tuple[PersonaRead, bool]:
        """Update archetype blend based on context. Returns (updated, major_switch_proposed)."""
        current = await self._read_by_id(persona_id)
        if current is None:
            raise ValueError(f"Persona {persona_id} not found")

        new_blend = self._apply_blend_shift(current.archetype_blend, context_updates)
        major_switch = self._detect_major_switch(current.archetype_blend, new_blend)

        await self._update(persona_id, {
            "archetype_blend": new_blend,
            "updated_at": datetime.now(timezone.utc),
        })

        await self._atrs.record_simple(
            engine=ATRSEngine.PERSONA,
            event_type=ATRSPersonaEvent.PERSONA_BLEND_UPDATED,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"persona:{persona_id}",
            metadata={
                "shift_amount": sum(abs(new_blend.get(k, 0) - current.archetype_blend.get(k, 0))
                                   for k in set(new_blend) | set(current.archetype_blend)),
            },
        )

        updated = await self._read_by_id(persona_id)
        assert updated is not None
        return _to_read(updated), major_switch

    async def propose_major_switch(
        self,
        persona_id: uuid.UUID,
        proposed_blend: dict[str, float],
    ) -> PersonaRead:
        """Manually propose a major persona switch."""
        current = await self._read_by_id(persona_id)
        if current is None:
            raise ValueError(f"Persona {persona_id} not found")

        await self._update(persona_id, {
            "archetype_blend": proposed_blend,
            "updated_at": datetime.now(timezone.utc),
        })

        await self._atrs.record_simple(
            engine=ATRSEngine.PERSONA,
            event_type=ATRSPersonaEvent.PERSONA_SWITCH_MANUAL,
            status=ATRSStatus.SUCCESS,
            entity_ref=f"persona:{persona_id}",
            metadata={"previous_blend": current.archetype_blend},
        )

        updated = await self._read_by_id(persona_id)
        assert updated is not None
        return _to_read(updated)

    async def _read_by_id(self, persona_id: uuid.UUID) -> Optional[Persona]:
        rows = await self._lister(uuid.UUID(persona_id))
        for row in rows:
            if row.persona_id == persona_id:
                return row
        return None

    def _apply_blend_shift(
        self,
        current: dict[str, float],
        updates: dict[str, float],
    ) -> dict[str, float]:
        """Apply small context-driven shifts to archetype weights."""
        new_blend = dict(current)
        for archetype, delta in updates.items():
            if archetype in new_blend:
                new_blend[archetype] = max(0.0, min(1.0, new_blend[archetype] + delta))
        total = sum(new_blend.values())
        if total > 0:
            new_blend = {k: v / total for k, v in new_blend.items()}
        return new_blend

    def _detect_major_switch(
        self,
        old: dict[str, float],
        new: dict[str, float],
    ) -> bool:
        """Detect if any archetype crossed the threshold for major switch."""
        for k in set(old) | set(new):
            delta = abs(new.get(k, 0) - old.get(k, 0))
            if delta >= self.BLEND_SHIFT_THRESHOLD:
                return True
        return False


def _to_read(row: Persona) -> PersonaRead:
    return PersonaRead(
        persona_id=row.persona_id,
        user_id=row.user_id,
        name=row.name,
        profession=row.profession,
        industry=row.industry,
        archetype_blend=row.archetype_blend,
        tone_rules=row.tone_rules,
        rules=row.rules,
        scope=row.scope,
    )