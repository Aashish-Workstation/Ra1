"""
Task Matcher
Given a task request, selects and ranks models that can handle it.
Considers: capability match, task affinity, budget mode, free-tier availability.
Returns a ranked list used as the fallback chain by the router.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

# Load registry once at import time
_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "capability_registry.json"
_PROVIDERS_PATH = Path(__file__).parent.parent / "data" / "providers.json"

with open(_REGISTRY_PATH) as f:
    REGISTRY: dict = json.load(f)

with open(_PROVIDERS_PATH) as f:
    PROVIDERS: dict = json.load(f)


@dataclass
class TaskRequest:
    task_type: str = "general"          # chat | code_gen | code_review | vision | research | quick_qa | summarise | agents
    required_caps: list[str] = None     # must-have capabilities
    min_context_k: int = 0             # minimum context window in thousands
    free_only: bool = False            # restrict to free-tier models only
    exclude_providers: list[str] = None
    max_cost_per_1m: float | None = None
    prefer_fast: bool = False
    user_prefs: dict = None             # personalised affinity overrides { model_id: 0.0-1.0 }

    def __post_init__(self):
        if self.required_caps is None:
            self.required_caps = []
        if self.exclude_providers is None:
            self.exclude_providers = []
        if self.user_prefs is None:
            self.user_prefs = {}


@dataclass
class RankedModel:
    model_id: str
    provider: str
    display_name: str
    score: float
    capabilities: list[str]
    context_window: int
    input_price: float
    output_price: float
    speed: str
    free_tier: dict | None


def match_models(task_req: TaskRequest, available_providers: dict[str, bool]) -> list[RankedModel]:
    """
    Return models ranked by suitability for the task.
    available_providers: { provider_id: True } — only models from these providers are included.
    """
    candidates: list[RankedModel] = []

    for model_id, model in REGISTRY.items():
        provider = model.get("provider", "")

        # ── Hard filters ──────────────────────────────────────────────────
        if provider in (task_req.exclude_providers or []):
            continue

        # Provider key not available — skip cloud models
        if not available_providers.get(provider):
            continue

        caps = model.get("capabilities", [])

        # Required capabilities — all must be present
        if task_req.required_caps:
            if not all(c in caps for c in task_req.required_caps):
                continue

        # Context window
        context_k = model.get("context_window", 0)
        if task_req.min_context_k > 0 and context_k < task_req.min_context_k:
            continue

        # Free tier only
        if task_req.free_only and not model.get("free_tier"):
            continue

        # Cost cap
        input_price = model.get("input_price", 0.0)
        if task_req.max_cost_per_1m is not None and input_price > task_req.max_cost_per_1m:
            continue

        # ── Score ─────────────────────────────────────────────────────────
        score = 0.0
        affinity_map = model.get("task_affinity", {})
        affinity = affinity_map.get(task_req.task_type, affinity_map.get("general", 0.5))
        score += affinity * 50

        user_pref = (task_req.user_prefs or {}).get(model_id, 0.5)
        score += user_pref * 30

        if task_req.prefer_fast:
            speed = model.get("speed", "standard")
            if speed == "instant":
                score += 10
            elif speed == "fast":
                score += 5

        if input_price == 0.0:
            score += 8
        elif input_price < 0.5:
            score += 5
        elif input_price > 10.0:
            score -= 3

        if task_req.free_only and model.get("free_tier"):
            score += 15

        candidates.append(RankedModel(
            model_id=model_id,
            provider=provider,
            display_name=model.get("display_name", model_id),
            score=round(score, 1),
            capabilities=caps,
            context_window=context_k,
            input_price=input_price,
            output_price=model.get("output_price", 0.0),
            speed=model.get("speed", "standard"),
            free_tier=model.get("free_tier"),
        ))

    candidates.sort(key=lambda m: m.score, reverse=True)
    return candidates


def can_do_task(task_req: TaskRequest, available_providers: dict[str, bool]) -> dict:
    """
    Check if a task can be fulfilled at all with current constraints.
    Returns { "possible": bool, "ranked": [...], "reason": str, "suggestion": str }
    """
    ranked = match_models(task_req, available_providers)

    if not ranked:
        paid_req = TaskRequest(
            task_type=task_req.task_type,
            required_caps=task_req.required_caps,
            min_context_k=task_req.min_context_k,
            exclude_providers=task_req.exclude_providers,
        )
        paid_options = match_models(paid_req, available_providers)

        if not paid_options:
            return {
                "possible": False,
                "reason": "No model available that meets the capability requirements.",
                "suggestion": f"Add a provider API key that supports: {', '.join(task_req.required_caps or ['chat'])}",
                "ranked": [],
            }

        cheapest = sorted(paid_options, key=lambda m: m.input_price)[0]
        return {
            "possible": False,
            "reason": "Task cannot be completed with free models.",
            "suggestion": f"Cheapest option: {cheapest.display_name} at ${cheapest.input_price}/1M tokens",
            "cheapest_paid": cheapest,
            "ranked": [],
        }

    return {"possible": True, "ranked": ranked}
