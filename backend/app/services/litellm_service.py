"""
LiteLLM Service
Manages runtime model configuration in LiteLLM.
When a user or admin stores an API key, this service pushes it to LiteLLM
so the model becomes available for routing immediately — no restart needed.
"""

import os
import httpx
import logging

logger = logging.getLogger(__name__)

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

# Maps provider IDs to the prefix LiteLLM expects in model names
PROVIDER_PREFIX_MAP: dict[str, str] = {
    "openai":      "openai/",
    "anthropic":   "anthropic/",
    "gemini":      "gemini/",
    "google":      "gemini/",
    "groq":        "groq/",
    "mistral":     "mistral/",
    "cohere":      "cohere/",
    "together":    "together_ai/",
    "openrouter":  "openrouter/",
}


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
        "Content-Type": "application/json",
    }


async def get_litellm_models() -> list[dict]:
    """Fetch all models currently registered in LiteLLM."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{LITELLM_URL}/model/info",
            headers=_auth_headers(),
        )
        response.raise_for_status()
        body = response.json()
        return body.get("data", [])


async def update_model_key(model_name: str, model: str, api_key: str, api_base: str | None = None) -> None:
    """Update a single model's API key in LiteLLM's runtime config."""
    litellm_params: dict = {"model": model, "api_key": api_key}
    if api_base:
        litellm_params["api_base"] = api_base

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LITELLM_URL}/model/update",
            headers=_auth_headers(),
            json={"model_name": model_name, "litellm_params": litellm_params},
        )
        response.raise_for_status()


async def update_models_for_provider(provider_id: str, api_key: str) -> dict[str, int]:
    """
    Update all LiteLLM models belonging to a provider with a new API key.
    Called automatically when a key is stored in the vault.
    Returns { "updated": N, "failed": N }
    """
    try:
        models = await get_litellm_models()
    except Exception as e:
        logger.warning(f"LiteLLM unreachable — skipping model sync for {provider_id}: {e}")
        return {"updated": 0, "failed": 0}

    prefix = PROVIDER_PREFIX_MAP.get(provider_id.lower(), f"{provider_id}/")
    matching = [m for m in models if m.get("litellm_params", {}).get("model", "").startswith(prefix)]

    updated = 0
    failed = 0
    for model in matching:
        try:
            await update_model_key(
                model_name=model["model_name"],
                model=model["litellm_params"]["model"],
                api_key=api_key,
                api_base=model["litellm_params"].get("api_base"),
            )
            updated += 1
        except Exception as e:
            logger.error(f"Failed to update model {model['model_name']}: {e}")
            failed += 1

    logger.info(f"LiteLLM sync for {provider_id}: updated={updated} failed={failed}")
    return {"updated": updated, "failed": failed}


def get_litellm_prefix(provider_id: str) -> str:
    """Return the LiteLLM model prefix for a given provider ID."""
    return PROVIDER_PREFIX_MAP.get(provider_id.lower(), f"{provider_id}/")
