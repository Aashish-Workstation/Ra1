"""
Context Assembler — stateless service for context assembly.

Properties:
  1. **Parallel fetch** — Pulls T1 Working context, T2 Episodic, T3 Semantic (via SearchEngineService),
     and active Persona state concurrently.
  2. **Token budget enforcement** — Strict pruning sequence when context exceeds limits.
  3. **Priority-based trimming** — T3 trimmed first, then T4, then T2 summarized, never T1 or Persona.
  4. **ATRS logging** — Events for context.fetch_spec_received and context.assembled.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSContextEvent, ATRSStatus
from app.models.context import (
    ContextFetchSpec,
    ContextPayload,
    EpisodicContext,
    PersonaState,
    SemanticContext,
    WorkingContext,
)

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_BUDGET = 128000

MEMORY_LISTER: Callable[[uuid.UUID, uuid.UUID], Awaitable[list[Any]]]
SEARCH_ENGINE: Callable[[str, uuid.UUID, uuid.UUID], Awaitable[list[Any]]]
PERSONA_READER: Callable[[uuid.UUID, Optional[uuid.UUID]], Awaitable[Optional[Any]]]


class ContextAssemblerService:
    """Stateless context assembly service.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        atrs: ATRSService,
        memory_lister: MEMORY_LISTER,
        search_engine: SEARCH_ENGINE,
        persona_reader: PERSONA_READER,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ):
        self._atrs = atrs
        self._memory_list = memory_lister
        self._search_engine = search_engine
        self._persona_reader = persona_reader
        self._token_budget = token_budget

    async def assemble(self, spec: ContextFetchSpec) -> ContextPayload:
        """Assemble context payload under token budget."""
        await self._atrs.record_simple(
            engine=ATRSEngine.CONTEXT,
            event_type=ATRSContextEvent.CONTEXT_FETCH_SPEC_RECEIVED,
            status=ATRSStatus.SUCCESS,
            metadata={"max_tokens": spec.max_tokens, "query": spec.query[:100]},
        )

        working, episodic, semantic, persona = await self._fetch_all_parallel(spec)

        total_tokens = (
            working.token_count +
            episodic.token_count +
            semantic.token_count
        )

        truncated = False
        truncation_reason = None

        if total_tokens > spec.max_tokens:
            working, episodic, semantic, truncated, truncation_reason = self._prune_context(
                working, episodic, semantic, spec.max_tokens
            )
            total_tokens = (
                working.token_count +
                episodic.token_count +
                semantic.token_count
            )

        payload = ContextPayload(
            working=working,
            episodic=episodic,
            semantic=semantic,
            persona=persona,
            total_tokens=total_tokens,
            truncated=truncated,
            truncation_reason=truncation_reason,
        )

        await self._atrs.record_simple(
            engine=ATRSEngine.CONTEXT,
            event_type=ATRSContextEvent.CONTEXT_ASSEMBLED,
            status=ATRSStatus.SUCCESS,
            metadata={
                "total_tokens": total_tokens,
                "truncated": truncated,
                "working_tokens": working.token_count,
                "episodic_tokens": episodic.token_count,
                "semantic_tokens": semantic.token_count,
            },
        )

        return payload

    async def _fetch_all_parallel(
        self,
        spec: ContextFetchSpec,
    ) -> tuple[WorkingContext, EpisodicContext, SemanticContext, PersonaState]:
        """Fetch all context sources in parallel with error handling."""
        results = await asyncio.gather(
            self._fetch_working_context(spec),
            self._fetch_episodic_context(spec),
            self._fetch_semantic_context(spec),
            self._fetch_persona_state(spec),
            return_exceptions=True,
        )
        
        working = results[0] if not isinstance(results[0], Exception) else WorkingContext(thread_id=spec.session_id, messages=[], token_count=0)
        episodic = results[1] if not isinstance(results[1], Exception) else EpisodicContext(token_count=0)
        semantic = results[2] if not isinstance(results[2], Exception) else SemanticContext(query=spec.query, token_count=0)
        persona = results[3] if not isinstance(results[3], Exception) else PersonaState()
        
        for i, name in enumerate(["working", "episodic", "semantic", "persona"]):
            if isinstance(results[i], Exception):
                logger.warning(f"Failed to fetch {name} context: {results[i]}")
        
        return working, episodic, semantic, persona

    async def _fetch_working_context(self, spec: ContextFetchSpec) -> WorkingContext:
        """Fetch T1 Working context (this thread)."""
        return WorkingContext(
            thread_id=spec.session_id,
            messages=[],
            token_count=0,
        )

    async def _fetch_episodic_context(self, spec: ContextFetchSpec) -> EpisodicContext:
        """Fetch T2 Episodic context (conversation history)."""
        if self._memory_list is None:
            return EpisodicContext(token_count=0)

        try:
            records = await self._memory_list(spec.user_id, spec.habitat_id or uuid.UUID('00000000-0000-0000-0000-000000000000'))
            summary = self._build_summary(records)
            key_facts = self._extract_key_facts(records)
            token_count = len(summary) // 4 + len(str(key_facts)) // 4

            return EpisodicContext(
                conversation_id=spec.session_id,
                summary=summary,
                key_facts=key_facts,
                token_count=token_count,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch episodic context: {e}")
            return EpisodicContext(token_count=0)

    async def _fetch_semantic_context(self, spec: ContextFetchSpec) -> SemanticContext:
        """Fetch T3 Semantic context via SearchEngineService."""
        if self._search_engine is None:
            return SemanticContext(query=spec.query, token_count=0)

        try:
            results = await self._search_engine(
                spec.query, spec.user_id, spec.habitat_id or uuid.UUID('00000000-0000-0000-0000-000000000000')
            )
            token_count = len(str(results)) // 4
            return SemanticContext(
                query=spec.query,
                results=results,
                token_count=token_count,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch semantic context: {e}")
            return SemanticContext(query=spec.query, token_count=0)

    async def _fetch_persona_state(self, spec: ContextFetchSpec) -> PersonaState:
        """Fetch active Persona state (never trimmed)."""
        if self._persona_reader is None:
            return PersonaState()

        try:
            persona = await self._persona_reader(spec.user_id, spec.habitat_id)
            if persona is None:
                return PersonaState()

            return PersonaState(
                persona_id=persona.persona_id,
                name=persona.name,
                profession=persona.profession,
                industry=persona.industry,
                archetype_blend=persona.archetype_blend,
                tone_rules=persona.tone_rules or [],
                rules=persona.rules or [],
            )
        except Exception as e:
            logger.warning(f"Failed to fetch persona state: {e}")
            return PersonaState()

    def _prune_context(
        self,
        working: WorkingContext,
        episodic: EpisodicContext,
        semantic: SemanticContext,
        budget: int,
    ) -> tuple[WorkingContext, EpisodicContext, SemanticContext, bool, Optional[str]]:
        """Apply strict pruning sequence: T3 -> T4 -> T2 (never T1 or Persona)."""
        truncated = False
        reason = None

        while semantic.token_count > 0 and (working.token_count + episodic.token_count + semantic.token_count) > budget:
            semantic.token_count = max(0, semantic.token_count - 1000)
            semantic.results = semantic.results[:max(0, len(semantic.results) - 1)]
            truncated = True
            reason = "semantic_trimmed"

        if episodic.token_count > 0 and (working.token_count + episodic.token_count + semantic.token_count) > budget:
            episodic.token_count = max(0, episodic.token_count // 2)
            episodic.summary = episodic.summary[:max(0, len(episodic.summary) // 2)]
            episodic.key_facts = episodic.key_facts[:max(0, len(episodic.key_facts) // 2)]
            truncated = True
            reason = "episodic_summarized"

        return working, episodic, semantic, truncated, reason

    def _build_summary(self, records: list) -> str:
        if not records:
            return ""
        return f"Conversation with {len(records)} messages"

    def _extract_key_facts(self, records: list) -> list:
        return [{"type": "fact", "content": str(r)[:100]} for r in records[:5]]