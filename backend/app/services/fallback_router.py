"""
Fallback Router
Executes a model call with automatic fallback on failure.
Classifies errors to decide cooldown duration and whether to retry.
Every switch is logged — no silent failures.
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ── In-memory cooldown store ──────────────────────────────────────────────────
# In production this should be backed by Valkey/Redis for multi-process safety.
_cooldowns: dict[str, dict] = {}  # model_id → { "until": float, "reason": str }

COOLDOWN_DEFAULT_S = 60
COOLDOWN_RATE_S    = 300  # 5 min for rate limits
COOLDOWN_AUTH_S    = 3600 # 1 hour for auth errors


def set_cooldown(model_id: str, reason: str, duration_s: int = COOLDOWN_DEFAULT_S) -> None:
    _cooldowns[model_id] = {"until": time.time() + duration_s, "reason": reason}


def is_on_cooldown(model_id: str) -> bool:
    entry = _cooldowns.get(model_id)
    if not entry:
        return False
    if time.time() > entry["until"]:
        del _cooldowns[model_id]
        return False
    return True


def get_cooldowns() -> dict:
    now = time.time()
    return {
        mid: {**data, "remaining_s": round(data["until"] - now)}
        for mid, data in _cooldowns.items()
        if now < data["until"]
    }


def _classify_error(exc: Exception, status_code: int = 0) -> tuple[str, int]:
    """Returns (error_type, cooldown_seconds)."""
    if status_code == 429:
        return "rate_limit", COOLDOWN_RATE_S
    if status_code in (502, 503):
        return "provider_outage", COOLDOWN_DEFAULT_S * 5
    if status_code in (401, 403):
        return "auth_error", COOLDOWN_AUTH_S
    if status_code == 413 or "context" in str(exc).lower():
        return "context_overflow", 0
    if "timeout" in str(exc).lower():
        return "timeout", COOLDOWN_DEFAULT_S
    return "unknown_error", COOLDOWN_DEFAULT_S


async def execute_with_fallback(
    ranked_models: list[Any],   # list of RankedModel or dicts with .model_id / ["model_id"]
    execute_fn: Callable[[str], Awaitable[Any]],
    max_retries: int = 2,
) -> dict:
    """
    Execute execute_fn(model_id) with automatic fallback through ranked_models.

    Returns:
    {
        "response": <result of execute_fn> | None,
        "model_used": str | None,
        "fallback_triggered": bool,
        "fallback_from": str | None,
        "switches": [...],
        "error": dict | None,
    }
    """
    switches = []
    fallback_from = None

    def get_model_id(m) -> str:
        return m.model_id if hasattr(m, "model_id") else m["model_id"]

    # Filter out models on cooldown
    candidates = []
    for m in ranked_models:
        mid = get_model_id(m)
        if is_on_cooldown(mid):
            switches.append({"from": mid, "to": None, "reason": f"skipped — on cooldown: {_cooldowns[mid]['reason']}"})
        else:
            candidates.append(m)

    if not candidates:
        return {
            "response": None, "model_used": None,
            "fallback_triggered": False, "fallback_from": None,
            "switches": switches,
            "error": {"type": "all_models_unavailable", "message": "All candidate models are on cooldown."},
        }

    for i, current in enumerate(candidates):
        current_id = get_model_id(current)
        next_model = candidates[i + 1] if i + 1 < len(candidates) else None
        last_exc = None

        for attempt in range(max_retries + 1):
            try:
                response = await execute_fn(current_id)
                return {
                    "response": response,
                    "model_used": current_id,
                    "fallback_triggered": i > 0,
                    "fallback_from": fallback_from,
                    "switches": switches,
                    "error": None,
                }
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", getattr(exc, "status", 0))
                error_type, cooldown = _classify_error(exc, status)

                if error_type == "auth_error":
                    set_cooldown(current_id, f"auth_error: {exc}", COOLDOWN_AUTH_S)
                    break
                if error_type == "rate_limit":
                    set_cooldown(current_id, "rate_limit", COOLDOWN_RATE_S)
                    break
                if error_type == "provider_outage":
                    set_cooldown(current_id, "provider_outage", cooldown)
                    break
                if error_type == "context_overflow":
                    break
                # Transient — retry with backoff
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt * 0.5)
                    continue
                if cooldown > 0:
                    set_cooldown(current_id, error_type, cooldown)

        # This model exhausted — log switch
        if next_model:
            next_id = get_model_id(next_model)
            reason = f"{_classify_error(last_exc, 0)[0]}: {last_exc}" if last_exc else "unknown"
            switches.append({"from": current_id, "to": next_id, "reason": reason})
            fallback_from = current_id
            logger.warning(f"Model fallback: {current_id} → {next_id} — {reason}")

    return {
        "response": None, "model_used": None,
        "fallback_triggered": len(candidates) > 1,
        "fallback_from": fallback_from,
        "switches": switches,
        "error": {"type": "all_models_failed", "message": "All candidate models failed after retries."},
    }
