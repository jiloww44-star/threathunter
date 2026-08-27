"""LLM Budget engine ("Part E" governance layer in the spec chain).

One accounting core governs BOTH OpenRouter tokens AND Firecrawl credits —
anything with a marginal cost flows through `budget(...)`. Accounting in
nanocents (1e9 = $1) to keep integer precision in storage.

Modes (circuit-breaker compatible, Part E §3.3):
  FULL     → any ladder entry allowed
  STANDARD → paid models allowed, cheapest preferred
  MINIMAL  → free-tier models only (:free variants / firecrawl reserve)
  OFF      → budget exhausted; callers must degrade (§20: surface
             personally, never fabricate)
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import yaml

from ..budget.context import current_case_id
from ..config import REPO_ROOT


class BudgetExceeded(Exception):
    """Raised when a purpose's allocation is spent (§20 — classified, not
    fabricated: caller must degrade visibly, e.g. mark_source_degraded)."""
    def __init__(self, purpose: str, required_nano: int, remaining_nano: int):
        self.purpose = purpose
        self.required_nano = required_nano
        self.remaining_nano = remaining_nano
        super().__init__(
            f"BudgetExceeded purpose={purpose} need≈${required_nano/1e9:.4f} "
            f"remaining≈${max(remaining_nano,0)/1e9:.4f}")


NANO_PER_USD = 1_000_000_000


def _load_budget_config() -> dict:
    path = REPO_ROOT / "backend" / "config" / "budget.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


class BudgetEngine:
    """Purpose-scoped spend ledger with daily/monthly caps.

    Thread-safe; storage through the injected store (table budget_tx) so
    ledger and analytics share one source of truth (§4 analytics rollup).
    """

    def __init__(self, store=None, config_path: str | None = None):
        self._lock = threading.RLock()
        self._store = store
        cfg = yaml.safe_load(Path(config_path).read_text()) if config_path \
            else _load_budget_config()
        self._cfg: dict[str, Any] = cfg or {}
        # Memory ledger fallback (tests / store-less use)
        self._mem: list[dict] = []

    # ---------------------------------------------------------------- cfg
    def caps_for(self, purpose: str) -> dict:
        kinds = self._cfg.get("purposes", {})
        return kinds.get(purpose) or kinds.get(purpose.split(":")[0]) or \
            kinds.get("_default") or {}

    # ------------------------------------------------------------- ledger
    def stored(self, tx: dict):
        with self._lock:
            if self._store is not None:
                try:
                    self._store.insert_budget_tx(tx)
                    return
                except Exception:
                    pass
            self._mem.append(tx)

    def _ledger(self) -> list[dict]:
        if self._store is not None:
            try:
                return self._store.budget_tx_rows()
            except Exception:
                pass
        return list(self._mem)

    def spent_nano(self, purpose: str, period: str) -> int:
        """period: 'day'|'month' — sum actual (or est) nano within window."""
        now = time.gmtime()
        if period == "day":
            prefix = time.strftime("%Y-%m-%d", now)
        else:
            prefix = time.strftime("%Y-%m", now)
        total = 0
        for row in self._ledger():
            created = str(row.get("created_at", ""))
            if not created.startswith(prefix):
                continue
            if purpose != "*" and row.get("purpose") != purpose:
                continue
            actual = row.get("actual_nano")
            # 0 is a real value (failed call settled at zero) — do not fallback
            total += int(actual if actual is not None
                         else row.get("est_nano") or 0)
        return total

    # ------------------------------------------------------------- policy
    def mode_for(self, purpose: str, est_nano: int) -> str:
        caps = self.caps_for(purpose)
        daily = int(caps.get("daily_cap_usd", 0.5) * NANO_PER_USD)
        monthly = int(caps.get("monthly_cap_usd", 10.0) * NANO_PER_USD)
        spent_d = self.spent_nano(purpose, "day")
        spent_m = self.spent_nano(purpose, "month")
        if spent_d + est_nano > daily or spent_m + est_nano > monthly:
            if self.caps_for(purpose).get("min_free_only_when_capped", True):
                # MINIMAL mode: free models are allowed even when paid cap hit
                if est_nano > 0:
                    return BudgetEngine.MINIMAL  # caller re-checks est=0 entries
                return BudgetEngine.MINIMAL
            return BudgetEngine.OFF
        return BudgetEngine.STANDARD

    FULL = "FULL"
    STANDARD = "STANDARD"
    MINIMAL = "MINIMAL"
    OFF = "OFF"

    @asynccontextmanager
    async def allocate(self, purpose: str, model_id: str,
                       est_cost_usd: float) -> AsyncIterator[dict]:
        """async with budget(ctx, purpose, model, est) as tx: ...
        Settles to actual cost on exit via engine.settle(tx, actual_usd)."""
        est_nano = max(0, int(est_cost_usd * NANO_PER_USD))
        mode = self.mode_for(purpose, est_nano)
        if mode == BudgetEngine.OFF:
            raise BudgetExceeded(purpose, est_nano, 0)
        if mode == BudgetEngine.MINIMAL and est_nano > 0:
            raise BudgetExceeded(
                purpose, est_nano,
                self._remaining(purpose))
        tx = {
            "id": uuid.uuid4().hex,
            "purpose": purpose,
            "model_id": model_id,
            "est_nano": est_nano,
            "actual_nano": None,
            "mode": mode,
            # §2.1 — case attribution: everything reserved inside an active
            # app.budget.context.current_case_id scope shares the audit key
            "case_id": current_case_id.get(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        }
        try:
            yield tx
        except Exception:
            tx["actual_nano"] = 0  # failed calls settle at zero
            self.stored(tx)
            raise
        else:
            if tx.get("actual_nano") is None:
                tx["actual_nano"] = est_nano  # assume estimate when unsettled
            self.stored(tx)

    def settle(self, tx: dict, actual_cost_usd: float):
        tx["actual_nano"] = max(0, int(actual_cost_usd * NANO_PER_USD))

    def _remaining(self, purpose: str) -> int:
        caps = self.caps_for(purpose)
        daily = int(caps.get("daily_cap_usd", 0.5) * NANO_PER_USD)
        return daily - self.spent_nano(purpose, "day")

    # -------------------------------------------------------------- stats
    def summary(self) -> dict:
        rows = self._ledger()
        by_purpose: dict[str, int] = {}
        calls = len(rows)
        total = 0
        for r in rows:
            actual = r.get("actual_nano")
            amt = int(actual if actual is not None else r.get("est_nano") or 0)
            by_purpose[r.get("purpose", "?")] = by_purpose.get(
                r.get("purpose", "?"), 0) + amt
            total += amt
        return {
            "total_usd": round(total / NANO_PER_USD, 6),
            "calls": calls,
            "by_purpose_usd": {k: round(v / NANO_PER_USD, 6)
                               for k, v in by_purpose.items()},
            "modes_run": list({r.get("mode") for r in rows}),
        }


# ------------------------------------------------ deprecated friendly alias
_budget_engine: BudgetEngine | None = None


def get_budget() -> BudgetEngine:
    from ..store.db import get_store
    global _budget_engine
    if _budget_engine is None or _budget_engine._store is not get_store():
        _budget_engine = BudgetEngine(store=get_store())
    return _budget_engine


def reset_budget(engine: BudgetEngine | None = None):
    global _budget_engine
    _budget_engine = engine
