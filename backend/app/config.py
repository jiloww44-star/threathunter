"""ThreatHunter360 settings — spec Part 1.2.

Secrets come from env / secret manager, never hardcoded. Every setting has a
demo-safe default so the platform runs end-to-end with zero external
dependencies (spec Part 10).
"""
from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = REPO_ROOT / "seed"

# Public OSM endpoints (spec §1.2/§1.3) — self-hosting (spec §Self-Hosted
# Geo Stack 1.2-1.3) swaps these via env or backend/config/settings.yaml.
PUBLIC_NOMINATIM = "https://nominatim.openstreetmap.org"
PUBLIC_OSRM = "https://router.project-osrm.org"


@functools.lru_cache(maxsize=1)
def _settings_yaml() -> dict:
    """config/settings.yaml — spec §1.3 "service layer switch (config-driven,
    zero code change)". Env vars always win over file values."""
    import yaml  # PyYAML is already a hard dependency

    path = BACKEND_ROOT / "config" / "settings.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


@dataclass
class Settings:
    """Mirrors spec Part 1.2 Settings, with demo defaults."""

    ENV: str = os.getenv("TH360_ENV", "demo")  # demo | production
    DATABASE_URL: str = os.getenv(
        "TH360_DATABASE_URL", f"sqlite:///{BACKEND_ROOT / 'th360_demo.db'}"
    )
    DATABASE_PATH: str = field(
        default_factory=lambda: os.getenv(
            "TH360_DATABASE_PATH", str(BACKEND_ROOT / "th360_demo.db")
        )
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    OPENWEATHER_KEY: str = os.getenv("OPENWEATHER_KEY", "")
    TRAFFIC_API_KEY: str = os.getenv("TRAFFIC_API_KEY", "")
    THREAT_INTEL_TOKEN: str = os.getenv("THREAT_INTEL_TOKEN", "")
    KYC_ENCRYPTION_KEY: str = os.getenv("KYC_ENCRYPTION_KEY", "demo-insecure-key")
    MAX_CLAIM_LENGTH: int = int(os.getenv("MAX_CLAIM_LENGTH", "280"))

    # Spec Part 10 — source registry location (demo pack reads local fixtures)
    SOURCES_FILE: str = os.getenv(
        "TH360_SOURCES_FILE", str(SEED_ROOT / "sources_demo.yaml")
    )

    # Spec Part 8 §CI — model-governance version pins (Part 20.2)
    MODEL_VERSIONS: dict = field(
        default_factory=lambda: {
            "reasoning_engine": "1.0.0",
            "embedder": "feature-hash-v2.1.0",
            "nli": "heuristic-v1.0.2",
            "claim_classifier": "keyword-v1.3.0",
        }
    )

    # KYC retention / privacy (spec Part 5.4, §25)
    KYC_RETENTION_DAYS: int = int(os.getenv("KYC_RETENTION_DAYS", "90"))
    RAW_SCRAPE_RETENTION_DAYS: int = int(os.getenv("RAW_SCRAPE_RETENTION_DAYS", "30"))

    # ── Geo stack switch (spec §Self-Hosted 1.3) ─────────────────────────
    # Public now, self-hosted later: change the URL, change nothing else.
    GEO_NOMINATIM_URL: str = field(
        default_factory=lambda: os.getenv("GEO_NOMINATIM_URL")
        or _settings_yaml().get("geo", {}).get("nominatim_url")
        or PUBLIC_NOMINATIM
    )
    GEO_OSRM_URL: str = field(
        default_factory=lambda: os.getenv("GEO_OSRM_URL")
        or _settings_yaml().get("geo", {}).get("osrm_url")
        or PUBLIC_OSRM
    )
    # Force fixture/offline mode (offline demo, CI) — §20 visible degradation
    OFFLINE: bool = field(
        default_factory=lambda: os.getenv("TH360_OFFLINE", "").lower()
        in ("1", "true", "yes")
    )

    @property
    def geo_self_hosted(self) -> bool:
        """§1.3 — self-hosted instances unlock higher concurrency (no 1/sec
        fair-use limit) since we control the SLA ourselves."""
        return (self.GEO_NOMINATIM_URL.rstrip("/") != PUBLIC_NOMINATIM
                or self.GEO_OSRM_URL.rstrip("/") != PUBLIC_OSRM)


settings = Settings()
