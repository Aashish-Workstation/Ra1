"""
Search Engine — unified search across Memory and Knowledge Base domains.

Properties:
  1. **Multi-domain.** Scans Memory and Knowledge Base simultaneously.
  2. **Relevance filtering.** Returns only entries above configurable threshold.
  3. **Unified results.** Single sorted list with scores.
  4. **ATRS logging.** Events for search received and results returned.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus, ATRSKnowledgeEvent
from app.models.knowledge import KnowledgeItem, KnowledgeItemRead, SearchResult
from app.models.memory import MemoryRecordRead

logger = logging.getLogger(__name__)

MemoryLister = Callable[[uuid.UUID, uuid.UUID], Awaitable[list[MemoryRecordRead]]]
KnowledgeLister = Callable[[uuid.UUID, uuid.UUID], Awaitable[list[KnowledgeItemRead]]]

DEFAULT_RELEVANCE_THRESHOLD = 0.5


class SearchEngineService:
    """Unified search engine for Memory and Knowledge domains.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        memory_lister: Optional[MemoryLister] = None,
        knowledge_lister: Optional[KnowledgeLister] = None,
        atrs: Optional[ATRSService] = None,
        relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    ):
        self._memory_list = memory_lister
        self._knowledge_list = knowledge_lister
        self._atrs = atrs
        self._threshold = relevance_threshold

    async def search(
        self,
        query: str,
        user_id: uuid.UUID,
        habitat_id: uuid.UUID,
        domains: list[str] = ["memory", "knowledge"],
        threshold: Optional[float] = None,
    ) -> list[SearchResult]:
        """Execute cross-domain search with relevance filtering."""
        threshold = threshold if threshold is not None else self._threshold
        query_lower = query.lower()
        results: list[SearchResult] = []
        timestamp = datetime.now(timezone.utc)

        if self._atrs:
            await self._atrs.record_simple(
                engine=ATRSEngine.KNOWLEDGE,
                event_type=ATRSKnowledgeEvent.SEARCH_RECEIVED,
                status=ATRSStatus.SUCCESS,
                metadata={"query": query[:100], "domains": domains},
            )

        if "memory" in domains and self._memory_list:
            memory_results = await self._search_memory(query_lower, user_id, habitat_id)
            results.extend(memory_results)

        if "knowledge" in domains and self._knowledge_list:
            knowledge_results = await self._search_knowledge(query_lower, user_id, habitat_id)
            results.extend(knowledge_results)

        filtered = [r for r in results if r.score >= threshold]
        filtered.sort(key=lambda x: x.score, reverse=True)

        if self._atrs:
            await self._atrs.record_simple(
                engine=ATRSEngine.KNOWLEDGE,
                event_type=ATRSKnowledgeEvent.SEARCH_RESULTS_RETURNED,
                status=ATRSStatus.SUCCESS,
                metadata={"result_count": len(filtered), "domains": domains},
            )

        return filtered

    async def _search_memory(
        self,
        query: str,
        user_id: uuid.UUID,
        habitat_id: uuid.UUID,
    ) -> list[SearchResult]:
        if self._memory_list is None:
            return []
        records = await self._memory_list(user_id, habitat_id)
        results = []
        for record in records:
            score = self._calculate_memory_score(record, query)
            if score >= self._threshold:
                results.append(SearchResult(
                    item_id=record.entity_id,
                    score=score,
                    content_preview=self._extract_preview(record.value),
                    content_type="structured",
                ))
        return results

    async def _search_knowledge(
        self,
        query: str,
        user_id: uuid.UUID,
        habitat_id: uuid.UUID,
    ) -> list[SearchResult]:
        if self._knowledge_list is None:
            return []
        items = await self._knowledge_list(user_id, habitat_id)
        results = []
        for item in items:
            score = self._calculate_knowledge_score(item, query)
            if score >= self._threshold:
                results.append(SearchResult(
                    item_id=item.item_id,
                    score=score,
                    content_preview=self._extract_preview(item.content),
                    content_type=item.content_type,
                ))
        return results

    def _calculate_memory_score(self, record: MemoryRecordRead, query: str) -> float:
        """Calculate relevance score for memory records."""
        value_str = str(record.value).lower()
        if query in value_str:
            return 0.8
        entity_type_match = query in record.entity_type.lower()
        if entity_type_match:
            return 0.6
        return 0.0

    def _calculate_knowledge_score(self, item: KnowledgeItemRead, query: str) -> float:
        """Calculate relevance score for knowledge items."""
        tags_match = any(query in t.lower() for t in item.tags)
        collections_match = any(query in c.lower() for c in item.collections)
        content_str = str(item.content).lower()
        content_match = query in content_str

        if tags_match or collections_match:
            return 0.9
        if content_match:
            return 0.7
        return 0.0

    def _extract_preview(self, content: Any) -> str:
        """Extract text preview from content."""
        if isinstance(content, str):
            return content[:200]
        if isinstance(content, dict):
            return str(content)[:200]
        return str(content)[:200]