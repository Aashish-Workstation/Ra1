"""
Safety Engine — Pydantic schemas for safety evaluation.

Models for the Safety + Guardrails service that enforces
context-aware boundary checks.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SafetyOutcome(str, Enum):
    CLEAR = "Clear"
    FLAG = "Flag"
    BLOCK_REWRITE = "Block - Rewrite"
    BLOCK_HARD = "Block - Hard"


class SafetyCategory(str, Enum):
    CREDENTIAL_LEAK = "credential_leak"
    PRIVACY_BREACH = "privacy_breach"
    HARMFUL_CONTENT = "harmful_content"
    POLICY_VIOLATION = "policy_violation"
    UNSAFE_QUERY = "unsafe_query"


class SafetyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: SafetyOutcome
    category: Optional[SafetyCategory] = None
    reason: str = ""
    matched_text: Optional[str] = None
    requires_rewrite: bool = False


class SafetyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    credential_patterns: list[str] = Field(default_factory=lambda: [
        "api_key",
        "api_key",
        "apikey",
        "secret_key",
        "secretkey",
        "access_key",
        "accesskey",
        "password",
        "passwd",
        "token",
        "refresh_token",
        "private_key",
        "privatekey",
        "client_secret",
    ])
    sensitive_profile_fields: list[str] = Field(default_factory=lambda: [
        "ssn",
        "social_security",
        "credit_card",
        "cvv",
        "bank_account",
    ])