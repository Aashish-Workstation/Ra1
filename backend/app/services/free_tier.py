"""
Free Tier Tracker
Tracks RPM / TPM / RPD quota usage for free-tier models.
Rotates to the next available free model when a quota is hit.
Reset windows: per-minute (rolling), per-day (midnight UTC).
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_PROVIDERS_PATH = Path(__file__).parent.parent / "data" / "providers.json"
with open(_PROVIDERS_PATH) as f:
    _PROVIDERS: dict = json.load(f)

_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "capability_registry.json"
with open(_REGISTRY_PATH) as f:
    _REGISTRY: dict = json.load(f)

# { model_id → { requests_this_minute, tokens_this_minute, requests_today, reset_minute_at, reset_day_at } }
_usage: dict[str, dict] = {}


def _next_midnight_utc() -> float:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    return (midnight + timedelta(days=1)).timestamp()


def _get_or_init(model_id: str) -> dict:
    if model_id not in _usage:
        now = time.time()
        _usage[model_id] = {
            "requests_this_minute": 0,
            "tokens_this_minute": 0,
            "requests_today": 0,
            "reset_minute_at": now + 60,
            "reset_day_at": _next_midnight_utc(),
        }
    return _usage[model_id]


def _rollover(u: dict) -> None:
    now = time.time()
    if now >= u["reset_minute_at"]:
        u["requests_this_minute"] = 0
        u["tokens_this_minute"] = 0
        u["reset_minute_at"] = now + 60
    if now >= u["reset_day_at"]:
        u["requests_today"] = 0
        u["reset_day_at"] = _next_midnight_utc()


def check_quota(model_id: str, estimated_tokens: int = 500) -> dict:
    """Check if a free-tier model still has quota. Returns { available, reason, resets_in_s }"""
    model = _REGISTRY.get(model_id)
    if not model or not model.get("free_tier"):
        return {"available": False, "reason": "Not a free-tier model"}

    limits = model["free_tier"]
    u = _get_or_init(model_id)
    _rollover(u)

    rpm = limits.get("rpm")
    tpm = limits.get("tpm")
    rpd = limits.get("rpd")

    if rpm and u["requests_this_minute"] >= rpm:
        return {"available": False, "reason": f"RPM limit reached ({rpm}/min)", "resets_in_s": u["reset_minute_at"] - time.time()}
    if tpm and (u["tokens_this_minute"] + estimated_tokens) > tpm:
        return {"available": False, "reason": f"TPM limit would be exceeded ({tpm}/min)", "resets_in_s": u["reset_minute_at"] - time.time()}
    if rpd and u["requests_today"] >= rpd:
        return {"available": False, "reason": f"Daily request limit reached ({rpd}/day)", "resets_in_s": u["reset_day_at"] - time.time()}

    return {"available": True}


def record_usage(model_id: str, tokens_used: int = 0) -> None:
    """Record a completed free-tier call."""
    u = _get_or_init(model_id)
    _rollover(u)
    u["requests_this_minute"] += 1
    u["tokens_this_minute"] += tokens_used
    u["requests_today"] += 1


def get_best_free_model(task_type: str = "general", estimated_tokens: int = 500) -> dict:
    """Return the best available free-tier model for a task type."""
    free_models = {
        mid: m for mid, m in _REGISTRY.items()
        if m.get("free_tier") and "free_tier" in m.get("capabilities", [])
    }

    available = []
    for model_id, model in free_models.items():
        quota = check_quota(model_id, estimated_tokens)
        if quota["available"]:
            affinity = model.get("task_affinity", {}).get(task_type, model.get("task_affinity", {}).get("general", 0.5))
            available.append({"model_id": model_id, "display_name": model.get("display_name", model_id), "affinity": affinity})

    if not available:
        soonest = min(
            (_get_or_init(mid)["reset_minute_at"] for mid in free_models),
            default=None
        )
        return {
            "available": False,
            "reason": "All free-tier quotas exhausted.",
            "resets_in_s": round(soonest - time.time()) if soonest else None,
        }

    available.sort(key=lambda m: m["affinity"], reverse=True)
    return {"available": True, **available[0], "all_available": [m["model_id"] for m in available]}


def get_quota_status() -> dict:
    """Return current quota status for all free-tier models (for admin dashboard)."""
    free_models = {mid: m for mid, m in _REGISTRY.items() if m.get("free_tier")}
    status = {}
    for model_id, model in free_models.items():
        u = _get_or_init(model_id)
        _rollover(u)
        limits = model["free_tier"]
        status[model_id] = {
            "display_name": model.get("display_name", model_id),
            "provider": model.get("provider"),
            "requests_this_minute": u["requests_this_minute"],
            "rpm_limit": limits.get("rpm"),
            "tokens_this_minute": u["tokens_this_minute"],
            "tpm_limit": limits.get("tpm"),
            "requests_today": u["requests_today"],
            "rpd_limit": limits.get("rpd"),
            "minute_resets_in_s": round(max(0.0, u["reset_minute_at"] - time.time())),
            "day_resets_in_s": round(max(0.0, u["reset_day_at"] - time.time())),
        }
    return status
