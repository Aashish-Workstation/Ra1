"""
Usage Tracker
Records every model call: tokens in/out, cost, latency, fallback info.
Enforces daily/monthly budget caps per user.
Writes to PostgreSQL (usage_log table). In-memory totals for fast dashboard reads.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── In-memory spend totals (reset on restart — DB is the source of truth) ─────
_spend_today:    dict[str, dict[str, float]] = {}  # { user_id: { provider: usd } }
_spend_month:    dict[str, dict[str, float]] = {}
_budget_caps:    dict[str, dict] = {}              # { user_id: { daily_usd, monthly_usd } }

_today_key  = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")
_month_key  = lambda: datetime.now(timezone.utc).strftime("%Y-%m")


def estimate_cost(input_price: float, output_price: float, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for a model call."""
    return (tokens_in / 1_000_000) * input_price + (tokens_out / 1_000_000) * output_price


def set_budget(user_id: str, daily_usd: float | None = None, monthly_usd: float | None = None) -> None:
    _budget_caps[user_id] = {"daily_usd": daily_usd, "monthly_usd": monthly_usd}


def check_budget(user_id: str, estimated_cost_usd: float = 0.0) -> dict:
    """Check if a call is within budget before executing."""
    caps = _budget_caps.get(user_id)
    if not caps:
        return {"allowed": True}

    today_spend = sum(_spend_today.get(user_id, {}).values())
    month_spend = sum(_spend_month.get(user_id, {}).values())

    if caps.get("daily_usd") and (today_spend + estimated_cost_usd) > caps["daily_usd"]:
        return {
            "allowed": False,
            "reason": f"Daily budget of ${caps['daily_usd']:.2f} would be exceeded. Today: ${today_spend:.4f}",
            "remaining_usd": max(0.0, caps["daily_usd"] - today_spend),
        }
    if caps.get("monthly_usd") and (month_spend + estimated_cost_usd) > caps["monthly_usd"]:
        return {
            "allowed": False,
            "reason": f"Monthly budget of ${caps['monthly_usd']:.2f} would be exceeded. Month: ${month_spend:.4f}",
            "remaining_usd": max(0.0, caps["monthly_usd"] - month_spend),
        }
    return {"allowed": True}


def record_in_memory(user_id: str, provider: str, cost_usd: float) -> None:
    """Update in-memory spend totals (called after a successful DB write)."""
    _spend_today.setdefault(user_id, {})
    _spend_today[user_id][provider] = _spend_today[user_id].get(provider, 0.0) + cost_usd

    _spend_month.setdefault(user_id, {})
    _spend_month[user_id][provider] = _spend_month[user_id].get(provider, 0.0) + cost_usd


async def record_to_db(
    pool,
    *,
    user_id: str,
    model_id: str,
    provider_id: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str,
    fallback_triggered: bool = False,
    fallback_from: str | None = None,
    fallback_to: str | None = None,
    byok_used: bool = False,
    cost_usd: float = 0.0,
) -> None:
    """Write a usage record to the usage_log table in PostgreSQL."""
    try:
        await pool.execute(
            """
            INSERT INTO usage_log (
                user_id, model_id, provider_id, input_tokens, output_tokens,
                latency_ms, status, fallback_triggered, fallback_from, fallback_to,
                byok_used, cost_usd
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            """,
            user_id, model_id, provider_id, input_tokens, output_tokens,
            latency_ms, status, fallback_triggered, fallback_from, fallback_to,
            byok_used, cost_usd,
        )
        record_in_memory(user_id, provider_id, cost_usd)
    except Exception as e:
        logger.error(f"Failed to write usage_log: {e}")
