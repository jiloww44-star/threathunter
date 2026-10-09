"""llm_budget guard — spec §2.1 usage surface.

Everything with a marginal cost (OpenRouter tokens, Firecrawl credits) goes
through one reserve→settle context manager:

    async with llm_budget(ctx, purpose="firecrawl:gov_portal",
                          model_id="firecrawl-credit",
                          est_cost_usd=0.01) as tx:
        ...                                         # do the metered call
        budget.settle(tx, actual_usd)               # optional; else est

Raises BudgetExceeded when the purpose's allocation is spent — callers must
degrade visibly (§20): mark the source degraded, drop to MINIMAL ladder
entries, or answer UNDETERMINED. Never fabricate.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from ..core.budget import BudgetExceeded, get_budget

__all__ = ["llm_budget", "BudgetExceeded", "demo_tenant_ctx"]


@asynccontextmanager
async def llm_budget(ctx: Any, purpose: str, model_id: str,
                     est_cost_usd: float) -> AsyncIterator[dict]:
    """Reserve est → yield tx → settle actual on exit (engine.allocate).

    ctx is the tenant/request context (Part 13 sandbox tenant in the demo
    pack); case attribution itself flows through
    `app.budget.context.current_case_id`, so nested AI actions of one case
    share an audit key without threading an id through every call site.
    """
    _ = ctx  # tenant/user labels ride on the ctx for observability hooks
    async with get_budget().allocate(purpose, model_id, est_cost_usd) as tx:
        yield tx


from dataclasses import dataclass  # noqa: E402


@dataclass
class DemoTenantCtx:
    """Part 13 sandbox tenant for the demo tooling (demo/e2e script)."""
    tenant_id: str = "tenant-demo-sandbox"
    user: str = "demo-analyst"
    env: str = "demo"


def demo_tenant_ctx() -> DemoTenantCtx:
    return DemoTenantCtx()
