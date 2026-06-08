"""
Safety Engine — context-aware boundary enforcement.

Properties:
  1. **Evaluation layer** — Returns outcomes: Clear, Flag, Block - Rewrite, Block - Hard.
  2. **Sacred Interceptor** — Blocks on credential leaks and sensitive profile elements.
  3. **ATRS logging** — Events for safety.evaluated and safety.blocked.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.atrs import ATRSService
from app.models.atrs import ATRSEngine, ATRSStatus, ATRSSafetyEvent
from app.models.safety import SafetyConfig, SafetyEvaluation, SafetyOutcome

logger = logging.getLogger(__name__)

DEFAULT_SENSITIVE_PATTERNS = [
    "ssn",
    "social_security",
    "credit_card",
    "cvv",
    "bank_account",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret_key",
    "secretkey",
    "access_key",
    "accesskey",
    "token",
    "refresh_token",
    "private_key",
    "privatekey",
    "client_secret",
]


class SafetyEngineService:
    """Stateless safety evaluation service.

    Construct one instance at app startup. Share across requests.
    """

    def __init__(
        self,
        atrs: ATRSService,
        config: Optional[SafetyConfig] = None,
    ):
        self._atrs = atrs
        self._config = config or SafetyConfig()

    async def evaluate_input(self, text: str) -> SafetyEvaluation:
        """Evaluate incoming text for safety concerns."""
        return await self._evaluate(text, is_input=True)

    async def evaluate_output(self, text: str) -> SafetyEvaluation:
        """Evaluate outgoing response for safety concerns."""
        return await self._evaluate(text, is_input=False)

    async def _evaluate(self, text: str, is_input: bool) -> SafetyEvaluation:
        """Core evaluation logic."""
        credential_match = self._check_credentials(text)
        if credential_match:
            await self._log_blocked(credential_match, "credential_leak")
            return SafetyEvaluation(
                outcome=SafetyOutcome.BLOCK_HARD,
                category="credential_leak",
                reason="Unencrypted credential detected",
                matched_text=credential_match,
                requires_rewrite=False,
            )

        sensitive_match = self._check_sensitive_fields(text)
        if sensitive_match:
            await self._log_blocked(sensitive_match, "privacy_breach")
            return SafetyEvaluation(
                outcome=SafetyOutcome.BLOCK_HARD,
                category="privacy_breach",
                reason="Sensitive profile element detected",
                matched_text=sensitive_match,
                requires_rewrite=False,
            )

        await self._log_evaluated("clear")
        return SafetyEvaluation(
            outcome=SafetyOutcome.CLEAR,
            reason="No safety concerns detected",
        )

    def _check_credentials(self, text: str) -> Optional[str]:
        """Check for unencrypted credential values using simple string matching."""
        text_lower = text.lower()
        for pattern in self._config.credential_patterns:
            if pattern.lower() in text_lower:
                return pattern
        return None

    def _check_sensitive_fields(self, text: str) -> Optional[str]:
        """Check for sensitive profile elements using simple string matching."""
        text_lower = text.lower()
        for pattern in DEFAULT_SENSITIVE_PATTERNS:
            if pattern.lower() in text_lower:
                return pattern
        return None

    async def _log_evaluated(self, result: str) -> None:
        """Log safety evaluation to ATRS."""
        await self._atrs.record_simple(
            engine=ATRSEngine.SAFETY,
            event_type=ATRSSafetyEvent.SAFETY_EVALUATED,
            status=ATRSStatus.SUCCESS,
            metadata={"result": result},
        )

    async def _log_blocked(self, matched_text: str, category: str) -> None:
        """Log blocked content to ATRS."""
        await self._atrs.record_simple(
            engine=ATRSEngine.SAFETY,
            event_type=ATRSSafetyEvent.SAFETY_BLOCKED,
            status=ATRSStatus.BLOCKED,
            metadata={"category": category, "matched": matched_text[:50]},
        )