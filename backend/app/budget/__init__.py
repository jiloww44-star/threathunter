"""Budget package — spec §2.1 import surface.

Intentionally kept import-free at package level: `app.core.budget` imports
`app.budget.context`, and eager re-exports here would create a cycle.
Import the concrete modules directly:

    from app.budget.guard import llm_budget, BudgetExceeded      # spec §2.1
    from app.budget.context import current_case_id               # spec §2.1
"""
