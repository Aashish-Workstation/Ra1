"""
Output Engine — Pydantic schemas for output formatting.

Models for the Output Engine service that prepares structured
response components and handles output format determination.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class OutputFormat(str, Enum):
    PROSE = "Prose"
    CODE = "Code block"
    MARKDOWN = "Markdown"
    TABLE = "Table"
    MIXED = "Mixed"


class OutputChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_type: str
    content: str
    format: Optional[OutputFormat] = None
    language: Optional[str] = None
    metadata: dict[str, Any] = ConfigDict(default_factory=dict)


class OutputSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks: list[OutputChunk] = ConfigDict(default_factory=list)
    format: OutputFormat = OutputFormat.PROSE
    total_tokens: int = 0
    synthesized_at: Optional[str] = None


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_format: Optional[OutputFormat] = None
    prefer_code_blocks: bool = False
    prefer_tables: bool = False
    custom_schema: Optional[dict[str, Any]] = None