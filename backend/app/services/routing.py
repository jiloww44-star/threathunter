"""Routing (OSRM) — spec §1.3 + §Self-Hosted Geo Stack 1.3.

Returns full geometry + per-step segments for the risk timeline. Public OSRM
has no SLA; failures degrade to the fixture corridor (§20 visible fallback).
Self-hosted (docker-compose.geo.yml, ~5 ms latency per §1.1) is a pure
settings change — settings.GEO_OSRM_URL — zero code change.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("th360.routing")
PUBLIC_OSRM = "https://router.project-osrm.org"


class RoutingService:
    """OSRM wrapper — public or self-hosted (§1.3).

    Self-hosting additionally unlocks per-transport-mode `osrm-extract`
    profiles (car/motorcycle/walking) — §1.3 accuracy bonus: the public
    server only offers car.
    """

    def __init__(self, base_url: str | None = None, offline: bool = False):
        from ..config import PUBLIC_OSRM as PUB, settings
        self.osrm_url = (base_url or settings.GEO_OSRM_URL or PUB).rstrip("/")
        self.self_hosted = self.osrm_url != PUB
        self.offline = offline

    async def route(self, origin: dict, dest: dict,
                    profile: str = "driving") -> dict | None:
        if self.offline:
            return None
        url = (f"{self.osrm_url}/route/v1/{profile}/"
               f"{origin['lon']},{origin['lat']};{dest['lon']},{dest['lat']}")
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url, params={
                    "overview": "full", "steps": "true",
                    "geometries": "geojson"})
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("OSRM unavailable (%s): %s", self.osrm_url, e)
            return None
        if not data.get("routes"):
            return None
        route = data["routes"][0]
        legs = []
        t = 0.0
        for leg in route["legs"]:
            for step in leg["steps"]:
                dur = step["duration"]
                coords = step["geometry"]["coordinates"]
                mid = coords[len(coords) // 2]
                legs.append({
                    "segment": step.get("name") or "unnamed road",
                    "start_offset_min": round(t / 60),
                    "duration_min": max(1, round(dur / 60)),
                    "coord": {"lon": mid[0], "lat": mid[1]},
                })
                t += dur
        return {
            "total_km": round(route["distance"] / 1000, 1),
            "total_min": round(t / 60, 1),
            "segments": legs,
            "geometry": route["geometry"],   # full polyline for Leaflet render
        }


_routing: RoutingService | None = None


def get_routing() -> RoutingService:
    global _routing
    if _routing is None:
        from ..config import settings
        _routing = RoutingService(base_url=settings.GEO_OSRM_URL,
                                  offline=settings.OFFLINE)
    return _routing
