// JourneyMap — spec §1.5 (Leaflet, zero cost). Renders OSRM route geometry
// when available, plus risk hotspots as severity-colored circles. Falls back
// to a schematic strip view offline (honest degradation, §20).
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { JourneySegmentRisk, RiskLevel } from "../types";

const SEVERITY_COLOR: Record<string, string> = {
  HIGH: "#ef4444", CRITICAL: "#b91c1c", MODERATE: "#f59e0b",
  LOW: "#22c55e", NONE: "#64748b",
};

interface Props {
  geometry: { coordinates: [number, number][] } | null;
  segments: JourneySegmentRisk[];
  dataMode: "live" | "offline-fixture";
}

export function JourneyMap({ geometry, segments, dataMode }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }

    const pts: [number, number][] = [];
    if (geometry) {
      for (const [lon, lat] of geometry.coordinates) pts.push([lat, lon]);
    } else {
      for (const s of segments) {
        if (s.lat != null && s.lon != null) pts.push([s.lat, s.lon]);
      }
    }

    const map = L.map(ref.current, { scrollWheelZoom: false });
    mapRef.current = map;

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);

    if (geometry) {
      L.polyline(pts, { color: "#2563eb", weight: 4 }).addTo(map);
    }

    const markers: L.CircleMarker[] = [];
    for (const s of segments) {
      if (s.lat == null || s.lon == null) continue;
      const sev = s.max_severity && s.max_severity !== "NONE"
        ? s.max_severity : s.risk;
      const m = L.circleMarker([s.lat, s.lon], {
        radius: sev === "HIGH" || sev === "CRITICAL" ? 11 : 8,
        color: SEVERITY_COLOR[sev] || "#f59e0b",
        weight: 2, fillOpacity: 0.55,
      }).addTo(map);
      m.bindTooltip(
        `${s.segment} · ${s.risk}` +
        (s.incident_count ? ` · ${s.incident_count} recent report(s)` : "") +
        ` · ETA ${s.time}`);
      markers.push(m);
    }

    if (pts.length === 1) {
      map.setView(pts[0], 10);
    } else if (pts.length > 1) {
      map.fitBounds(L.latLngBounds(pts), { padding: [30, 30] });
    }

    return () => { map.remove(); mapRef.current = null; };
  }, [geometry, segments]);

  return (
    <div className="graph-wrap">
      <div ref={ref} style={{ height: 400, borderRadius: 12 }}
           role="img" aria-label="Journey risk map with route and hotspots" />
      <div className="graph-legend">
        {Object.entries(SEVERITY_COLOR).map(([k, c]) => (
          <span key={k}><i style={{ background: c }} />{k}</span>
        ))}
        <span className={dataMode === "live" ? "" : "muted"}>
          mode: {dataMode === "live"
            ? "live (Nominatim + OSRM geometry)"
            : "offline-fixture corridor (OSM unavailable — staleness visible §20)"}
        </span>
      </div>
    </div>
  );
}
