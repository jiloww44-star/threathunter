"""Geocoding (Nominatim) — spec §1.2 + §Self-Hosted Geo Stack 1.3.

Free, keyless. Public endpoint: fair-use limited to 1 req/sec (enforced via
semaphore + pause). Self-hosted instance (docker-compose.geo.yml): the same
class simply reads settings.GEO_NOMINATIM_URL — zero code change — and the
1/sec pause drops away because we own the SLA (§1.3).

A local gazetteer acts as the offline fallback so the Journey module stays
answerable when Nominatim is unreachable — surfaced as data_mode
"offline-fixture", never fabricated coordinates (§20).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("th360.geo")
# Public endpoint kept as the explicit default (§1.2). Self-host URL comes
# from settings (§1.3).
PUBLIC_NOMINATIM = "https://nominatim.openstreetmap.org"
# ToS requires an identifiable UA with contact (§1.2)
HEADERS = {"User-Agent": "ThreatHunter360/1.0 (contact@threathunter360.com)"}

# Offline gazetteer (demo corridor + common hubs) — coordinates approximate,
# used ONLY when the network is unavailable and flagged as such.
GAZETTEER = {
    "lagos": {"lat": 6.5244, "lon": 3.3792, "display_name": "Lagos, Nigeria"},
    "ikeja": {"lat": 6.6018, "lon": 3.3512, "display_name": "Ikeja, Lagos"},
    "ikeja, lagos": {"lat": 6.6018, "lon": 3.3512, "display_name": "Ikeja, Lagos"},
    "victoria island": {"lat": 6.4281, "lon": 3.4219,
                        "display_name": "Victoria Island, Lagos"},
    "victoria island, lagos": {"lat": 6.4281, "lon": 3.4219,
                               "display_name": "Victoria Island, Lagos"},
    "ibadan": {"lat": 7.3775, "lon": 3.9470, "display_name": "Ibadan, Nigeria"},
    "abuja": {"lat": 9.0765, "lon": 7.3986, "display_name": "Abuja, Nigeria"},
    "kano": {"lat": 12.0022, "lon": 8.5920, "display_name": "Kano, Nigeria"},
}


class GeoService:
    """Nominatim wrapper — public fair-use or self-hosted (§1.3).

    Public profile:  asyncio.Semaphore(1) + 1.05s pause per request.
    Self-hosted:     asyncio.Semaphore(20)  # local = no 1/sec limit needed
    """

    def __init__(self, base_url: str | None = None, offline: bool = False,
                 rate_pause: float | None = None,
                 gazetteer: dict | None = None):
        from ..config import PUBLIC_NOMINATIM as PUB, settings
        self.base_url = (base_url or settings.GEO_NOMINATIM_URL or PUB).rstrip("/")
        self.self_hosted = self.base_url != PUB
        # §1.2 public fair-use → 1 req/sec; §1.3 local → no 1/sec limit needed
        self._sem = asyncio.Semaphore(1 if not self.self_hosted else 20)
        self.rate_pause = rate_pause if rate_pause is not None else (
            0.0 if self.self_hosted else 1.05)   # injectable for tests
        self.offline = offline
        self.gazetteer = gazetteer if gazetteer is not None else GAZETTEER
        self._cache: dict[str, dict] = {}

    async def geocode(self, place: str) -> dict | None:
        key = place.strip().lower()
        if key in self._cache:
            return self._cache[key]
        hit = None
        if not self.offline:
            try:
                async with self._sem:
                    if self.rate_pause > 0:
                        await asyncio.sleep(self.rate_pause)
                    async with httpx.AsyncClient(timeout=12) as c:
                        r = await c.get(
                            f"{self.base_url}/search",
                            params={"q": place, "format": "json", "limit": 1},
                            headers=HEADERS)
                        r.raise_for_status()
                        results = r.json()
                if results:
                    hit = {
                        "lat": float(results[0]["lat"]),
                        "lon": float(results[0]["lon"]),
                        "display_name": results[0]["display_name"],
                        "source": "nominatim"
                                  + (" (self-hosted)" if self.self_hosted else ""),
                    }
            except Exception as e:
                log.warning("geocode degraded for %r: %s", place, e)
        if hit is None:
            # §20 — degrade with visibility; no fabrication of precision
            hit = self.gazetteer.get(key)
            if hit is not None:
                hit = {**hit, "source": "offline-gazetteer"}
        if hit is not None:
            self._cache[key] = hit
        return hit


def _haversine_km(a: dict, b: dict) -> float:
    import math
    R = 6371.0
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


_geo: GeoService | None = None


def get_geo() -> GeoService:
    global _geo
    if _geo is None:
        from ..config import settings
        _geo = GeoService(base_url=settings.GEO_NOMINATIM_URL,
                          offline=settings.OFFLINE)
    return _geo
