"""Test fixtures — spec Part 8. The engine suite is a trust-critical asset;
CI gate requires ≥90% reasoning-engine coverage (Part 8.4)."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.scraper.orchestrator import load_sources, run_pipeline  # noqa: E402
from app.store.db import reset_store  # noqa: E402
from app.core.reasoning_engine import ReasoningEngine  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = reset_store(str(tmp_path / "test.db"))
    yield s
    s.close()


@pytest.fixture
def seeded(store):
    """Demo seed pack ingested into an isolated store."""
    asyncio.run(run_pipeline(store, load_sources()))
    return store


@pytest.fixture
def engine(seeded):
    return ReasoningEngine(seeded)


@pytest.fixture
def now():
    return datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
