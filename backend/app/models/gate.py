"""
Quality Gate — Pydantic schemas for generation evaluation.

Models for the Quality Gate service that evaluates completed
generations across multiple dimensions.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class GateOutcome(str, Enum):
    PASS = "Pass"
    PASS_WITH_FLAG = "Pass with flag"
    REJECT_RETRY = "Reject - retry"
    REJECT_SURFACE = "Reject - surface"


class QualityDimension(str, Enum):
    COMPLETENESS = "completeness"
    COHERENCE = "coherence"
    FORMAT_CORRECTNESS = "format_correctness"
    HALLUCINATION = "hallucination"


class QualityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completeness: float = 1.0
    coherence: float = 1.0
    format_correctness: float = 1.0
    hallucination_flag: bool = False
    hallucination_details: Optional[str] = None


class GateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: GateOutcome
    metrics: QualityMetrics
    failed_dimensions: list[QualityDimension] = ConfigDict(default_factory=list)
    retry_reason: Optional[str] = None
    surface_error: Optional[str] = None


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completeness_threshold: float = 0.7
    coherence_threshold: float = 0.6
    format_threshold: float = 0.8
    hallucination_tolerance: float = 0.1
    max_retry_attempts: int = 2