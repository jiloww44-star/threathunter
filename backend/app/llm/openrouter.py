"""OpenRouter client — spec §3 (AI actions layer).

One API, many models; fallbacks chain natively; :free variants back MINIMAL
mode. When no OPENROUTER_API_KEY is configured the client is absent and the
platform's deterministic templates handle text (demo profile — §20: degrade
with a visible data_mode marker, never fabricate).
"""
from __future__ import annotations

import json
import logging
import os
import time

import httpx

from ..core.errors import PipelineError

log = logging.getLogger("th360.llm")
OPENROUTER = "https://openrouter.ai/api/v1"

# Fallback pricing table (per token, USD) — refreshed nightly from /models
# (spec §3.4 sync_model_pricing) into pricing_cache.json.
_PRICING_DEFAULTS = {
    "openai/gpt-4o": {"prompt": 2.5e-6, "completion": 1e-5},
    "openai/gpt-4o-mini": {"prompt": 1.5e-7, "completion": 6e-7},
    "anthropic/claude-3.5-haiku": {"prompt": 8e-7, "completion": 4e-6},
    "anthropic/claude-3.5-sonnet": {"prompt": 3e-6, "completion": 1.5e-5},
    "meta-llama/llama-3.1-8b-instruct:free": {"prompt": 0.0, "completion": 0.0},
}


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, referer: str | None = None,
                 pricing: dict | None = None):
        self.api_key = api_key if api_key is not None else \
            os.getenv("OPENROUTER_API_KEY", "")
        self.referer = referer or os.getenv(
            "TH360_SITE_URL", "https://threathunter360.com")
        self.pricing = {**_PRICING_DEFAULTS, **(pricing or {})}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.referer,     # required for rankings
            "X-Title": "ThreatHunter360",
        }

    async def complete(self, model: str, messages: list[dict],
                       fallbacks: list[str] | None = None,
                       max_tokens: int = 1024) -> tuple[str, float, str]:
        """Returns (text, actual_cost_usd, model_used). Falls back through the
        chain on failure; raises PipelineError(LLM_UNAVAILABLE) when exhausted."""
        if not self.available:
            raise PipelineError("LLM_UNAVAILABLE", 503,
                                "OPENROUTER_API_KEY not configured")
        chain = [model] + (fallbacks or [])
        last_err: Exception | None = None
        for m in chain:
            for attempt in (0, 1):  # one soft retry per model
                try:
                    async with httpx.AsyncClient(timeout=60) as c:
                        r = await c.post(
                            f"{OPENROUTER}/chat/completions",
                            json={"model": m, "messages": messages,
                                  "max_tokens": max_tokens},
                            headers=self._headers())
                        r.raise_for_status()
                        body = r.json()
                    usage = body.get("usage") or {}
                    cost = self._cost_usd(m, usage)
                    return body["choices"][0]["message"]["content"], cost, m
                except Exception as e:  # httpx error / key error / 5xx
                    last_err = e
                    if attempt == 0:
                        import asyncio
                        await asyncio.sleep(1.2)
                    continue
        raise PipelineError("LLM_UNAVAILABLE", 503, str(last_err))

    def _cost_usd(self, model: str, usage: dict) -> float:
        gen = usage.get("cost")                 # OpenRouter generation stats
        if gen is not None:
            try:
                return float(gen)
            except (TypeError, ValueError):
                pass
        pricing = self.pricing.get(model, {"prompt": 0.0, "completion": 0.0})
        return (usage.get("prompt_tokens", 0) * pricing["prompt"] +
                usage.get("completion_tokens", 0) * pricing["completion"])


_client: OpenRouterClient | None = None


def get_client() -> OpenRouterClient:
    global _client
    if _client is None:
        _client = OpenRouterClient()
    return _client


def sync_model_pricing(cache_path: str | None = None) -> int:
    """§3.4 — nightly sync of the pricing table from OpenRouter's model list.
    Keeps _cost_usd accurate automatically. Returns entries updated."""
    if not get_client().available:
        log.warning("pricing sync skipped — no OPENROUTER_API_KEY")
        return 0
    body = httpx.get(f"{OPENROUTER}/models", timeout=30).json()
    out = {}
    for m in body.get("data", []):
        p = m.get("pricing") or {}
        try:
            out[m["id"]] = {
                "prompt": float(p.get("prompt", 0) or 0),
                "completion": float(p.get("completion", 0) or 0),
            }
        except (TypeError, ValueError):
            continue
    path = cache_path or os.path.join(os.path.dirname(__file__),
                                      "pricing_cache.json")
    with open(path, "w") as f:
        json.dump({"synced_at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.gmtime()),
                   "models": out}, f, indent=1)
    return len(out)
