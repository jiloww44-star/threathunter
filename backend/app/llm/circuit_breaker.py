"""Circuit breaker + AI action gateway — spec "Part E" ladder, §3.3-3.4.

Every AI call in the platform goes through `ai_action`:
  1. select_model walks the purpose's ladder against budget mode
     (FULL → STANDARD → MINIMAL(:free only) → OFF)
  2. OpenRouter executes with native fallback chain
  3. actual cost settles into the nanocent ledger (feeds analytics §4.1)

Without a provider key the gateway reports LLM_UNAVAILABLE and modules fall
back to their deterministic template paths — the demo profile's honest
degradation (§20).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..core.budget import BudgetEngine, BudgetExceeded, get_budget
from ..core.errors import PipelineError
from ..config import REPO_ROOT
from .openrouter import OpenRouterClient, get_client

_LADDER_PATH = REPO_ROOT / "backend" / "config" / "model_ladder.yaml"


def load_ladder(purpose: str) -> list[dict]:
    cfg = yaml.safe_load(_LADDER_PATH.read_text()) or {}
    ladders = cfg.get("ladders", {})
    return ladders.get(purpose) or ladders.get("narrative") or []


class CircuitBreaker:
    def __init__(self, budget: BudgetEngine | None = None,
                 client: OpenRouterClient | None = None):
        self.budget = budget or get_budget()
        self.client = client or get_client()

    def select_model(self, purpose: str) -> tuple[str, str, float]:
        """(model_id, mode, est_cost_usd). Raises PipelineError(OFF) when the
        purpose has NO permitted slot — never substitutes silently."""
        ladder = load_ladder(purpose)
        if not ladder:
            raise PipelineError("LLM_UNAVAILABLE", 503, f"no ladder for {purpose}")
        # Probe best-paid first; on budget-cap BudgetExceeded try cheaper
        # entries, ending at :free (MINIMAL mode). KYC ladder has no :free →
        # fails OFF loudly (no degradation, per spec §3.3).
        saw_cost_error = None
        chosen_mode = BudgetEngine.STANDARD
        for entry in ladder:
            est = float(entry.get("est_cost_usd", 0.0))
            mode = self.budget.mode_for(purpose, int(est * 1e9))
            if mode == BudgetEngine.OFF:
                saw_cost_error = "budget exhausted"
                continue
            if mode == BudgetEngine.MINIMAL and est > 0:
                saw_cost_error = "budget caps paid models"
                chosen_mode = BudgetEngine.MINIMAL
                continue
            skip_free_for_sensitive = (
                purpose == "kyc" and float(est) == 0.0
                and not self.budget.caps_for(purpose).get(
                    "min_free_only_when_capped", True))
            if skip_free_for_sensitive:
                saw_cost_error = "KYC disallows degraded models (§3.3)"
                continue
            # A free-slot choice after paid entries were capped is MINIMAL
            effective = BudgetEngine.MINIMAL if chosen_mode == BudgetEngine.MINIMAL \
                else mode
            return entry["model"], effective, est
        raise PipelineError("LLM_UNAVAILABLE", 503,
                            saw_cost_error or "all ladder entries blocked")

    async def ai_action(self, purpose: str, messages: list[dict],
                        max_tokens: int = 512) -> dict:
        """Spec §3.3 gateway. Returns {text, model_used, mode} — or raises
        PipelineError so callers degrade with a classified code."""
        model, mode, est = self.select_model(purpose)
        ladder = load_ladder(purpose)
        fallbacks = [e["model"] for e in ladder
                     if e["model"] != model and not (
                         purpose == "kyc" and float(e.get("est_cost_usd", 0)) == 0.0)]
        try:
            async with self.budget.allocate(purpose, model, est) as tx:
                try:
                    text, actual, model_used = await self.client.complete(
                        model, messages, fallbacks=fallbacks,
                        max_tokens=max_tokens)
                except PipelineError:
                    raise
                self.budget.settle(tx, actual)
        except BudgetExceeded as e:
            raise PipelineError("LLM_BUDGET_EXCEEDED", 503, str(e)) from e
        return {"text": text, "model_used": model_used, "mode": mode}


_breaker: CircuitBreaker | None = None


def get_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker()
    # The evidence store can be rebound (test/demo store resets, seeded swaps)
    # — the ledger must follow the ACTIVE store, not the connection captured
    # at first use, or spend would land on a stale database.
    cur = get_budget()
    if _breaker.budget is not cur:
        _breaker.budget = cur
    return _breaker


async def ai_action(purpose: str, messages: list[dict],
                    max_tokens: int = 512) -> dict:
    return await get_breaker().ai_action(purpose, messages, max_tokens)
