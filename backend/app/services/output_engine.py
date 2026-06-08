"""
Output Engine — structured response preparation.

Properties:
  1. **Output format determination** — Prose, Code, Markdown, Table, Mixed.
  2. **Composite delivery** — Packages multi-part generation structures.
  3. **ATRS logging** — Events for output.received and output.synthesised.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus, ATSROutputEvent
from app.models.output import OutputChunk, OutputFormat, OutputSynthesis, OutputSpec

logger = logging.getLogger(__name__)


class OutputEngineService:
    """Stateless output preparation service.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        atrs: ATRSService,
    ):
        self._atrs = atrs

    async def determine_format(self, spec: Optional[OutputSpec] = None) -> OutputFormat:
        """Determine output format based on spec or defaults."""
        if spec and spec.requested_format:
            return spec.requested_format
        return OutputFormat.PROSE

    async def synthesize(
        self,
        content: str,
        spec: Optional[OutputSpec] = None,
        format: Optional[OutputFormat] = None,
    ) -> OutputSynthesis:
        """Synthesize output into structured chunks."""
        output_format = format or await self.determine_format(spec)

        await self._atrs.record_simple(
            engine=ATRSEngine.OUTPUT,
            event_type=ATSROutputEvent.OUTPUT_RECEIVED,
            status=ATRSStatus.SUCCESS,
            metadata={"format": output_format.value, "content_length": len(content)},
        )

        chunk = OutputChunk(
            chunk_type="main",
            content=content,
            format=output_format,
        )

        synthesis = OutputSynthesis(
            chunks=[chunk],
            format=output_format,
            total_tokens=len(content) // 4,
            synthesized_at="now",
        )

        await self._atrs.record_simple(
            engine=ATRSEngine.OUTPUT,
            event_type=ATSROutputEvent.OUTPUT_SYNTHESISED,
            status=ATRSStatus.SUCCESS,
            metadata={"chunk_count": len(synthesis.chunks), "format": output_format.value},
        )

        return synthesis

    async def package_multi_part(
        self,
        text_block: str,
        code_blocks: Optional[list[tuple[str, str]]] = None,
        tables: Optional[list[str]] = None,
    ) -> OutputSynthesis:
        """Package multiple output components into composite delivery."""
        chunks = []

        if text_block:
            chunks.append(OutputChunk(
                chunk_type="text",
                content=text_block,
                format=OutputFormat.PROSE,
            ))

        if code_blocks:
            for lang, code in code_blocks:
                chunks.append(OutputChunk(
                    chunk_type="code",
                    content=code,
                    format=OutputFormat.CODE,
                    language=lang,
                ))

        if tables:
            for table in tables:
                chunks.append(OutputChunk(
                    chunk_type="table",
                    content=table,
                    format=OutputFormat.TABLE,
                ))

        total_tokens = sum(len(c.content) for c in chunks) // 4
        format_type = OutputFormat.MIXED if len(chunks) > 1 else OutputFormat.PROSE

        synthesis = OutputSynthesis(
            chunks=chunks,
            format=format_type,
            total_tokens=total_tokens,
            synthesized_at="now",
        )

        await self._atrs.record_simple(
            engine=ATRSEngine.OUTPUT,
            event_type=ATSROutputEvent.OUTPUT_SYNTHESISED,
            status=ATRSStatus.SUCCESS,
            metadata={"chunk_count": len(chunks), "format": format_type.value},
        )

        return synthesis