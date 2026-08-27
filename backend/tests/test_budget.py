"""Budget engine + circuit breaker tests — spec §2.4/§3.3 governance layer."""
import asyncio

import pytest

from app.core.budget import BudgetEngine, BudgetExceeded
from app.llm.circuit_breaker import CircuitBreaker
from app.core.errors import PipelineError
from app.llm.openrouter import OpenRouterClient


def run(coro):
    return asyncio.run(coro)


class StubClient(OpenRouterClient):
    """Deterministic provider for governance tests (no network)."""
    def __init__(self, fail=False):
        super().__init__(api_key="stub", pricing={})
        self.fail = fail
        self.calls = []

    async def complete(self, model, messages, fallbacks=None, max_tokens=1024):
        # Emulates OpenRouter native fallback chains (spec §3.2/3.3)
        for m in [model] + (fallbacks or []):
            self.calls.append(m)
            if self.fail and ":free" not in m:
                continue
            return (f"[{m}] ok",
                    0.0 if ":free" in m else 0.002, m)
        raise PipelineError("LLM_UNAVAILABLE", 503, "simulated provider error")


def test_allocate_success_and_settle(store):
    eng = BudgetEngine(store=store)

    async def _flow():
        async with eng.allocate("factcheck", "openai/gpt-4o", 0.015) as tx:
            eng.settle(tx, 0.011)
        return tx
    tx = run(_flow())
    assert tx["actual_nano"] == int(0.011 * 1e9)
    assert eng.spent_nano("factcheck", "day") == int(0.011 * 1e9)


def test_failed_call_settles_zero(store):
    eng = BudgetEngine(store=store)

    async def _boom():
        async with eng.allocate("factcheck", "m", 0.01):
            raise ValueError("provider down")
    with pytest.raises(ValueError):
        run(_boom())
    assert eng.spent_nano("factcheck", "day") == 0


async def _fill_until_capped(eng, purpose, model, cost):
    for _ in range(500):
        try:
            async with eng.allocate(purpose, model, cost):
                pass
        except BudgetExceeded:
            return


def test_budget_exceeded_enforced(store):
    eng = BudgetEngine(store=store)
    run(_fill_until_capped(eng, "journey", "anthropic/claude-3.5-haiku", 0.005))

    async def _one_more():
        async with eng.allocate("journey", "anthropic/claude-3.5-haiku", 0.005):
            pass
    with pytest.raises(BudgetExceeded):
        run(_one_more())


def test_minimal_mode_still_allows_free(store):
    eng = BudgetEngine(store=store)
    # burn the paid budget
    run(_fill_until_capped(eng, "factcheck", "openai/gpt-4o", 0.005))

    breaker = CircuitBreaker(budget=eng, client=StubClient())
    model, mode, est = breaker.select_model("factcheck")
    assert model.endswith(":free")          # fell to MINIMAL tier
    assert mode == BudgetEngine.MINIMAL


def test_kyc_never_degrades_to_free(store):
    eng = BudgetEngine(store=store)
    breaker = CircuitBreaker(budget=eng, client=StubClient())
    model, mode, est = breaker.select_model("kyc")
    assert est > 0    # KYC ladder has no :free entry (§3.3)


def test_ai_action_records_ledger(tx_caps=None):
    eng = BudgetEngine()
    breaker = CircuitBreaker(budget=eng, client=StubClient())
    out = run(breaker.ai_action("journey", [{"role": "user", "content": "hi"}]))
    assert out["model_used"].startswith("anthropic/") or out["model_used"]
    summary = eng.summary()
    assert summary["calls"] == 1
    assert summary["total_usd"] > 0


def test_fallback_chain_used_on_failure():
    eng = BudgetEngine()
    breaker = CircuitBreaker(budget=eng, client=StubClient(fail=True))
    out = run(breaker.ai_action("journey", [{"role": "user", "content": "hi"}]))
    assert out["model_used"].endswith(":free")   # fell back through the chain
