"""Case attribution for spend — spec §2.1.

`token = current_case_id.set(case.id)` ... `current_case_id.reset(token)`
auto-tags every budget transaction reserved inside the context — firecrawl
scrapes, OpenRouter ladder attempts, KYC actions — so Stage-4 style audit
queries (`budget_tx_for_case`) join the full cost trail by case.

No imports beyond stdlib: `app.core.budget` depends on this module and must
never cycle back through it.
"""
from __future__ import annotations

from contextvars import ContextVar

current_case_id: ContextVar[str | None] = ContextVar(
    "th360_case_id", default=None)
