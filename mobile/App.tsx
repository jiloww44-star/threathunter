import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import type { Feature, FeatureCollection, Point } from "geojson";
import {
  Map,
  MapChoropleth,
  MapCircle,
  MapClusterLayer,
  MapControls,
  MapGeoJSON,
  MapHeatmap,
  MapLegend,
  MapLocationPuck,
  MapMarker,
  MapPolygon,
  MapPopup,
  MapRoute,
  MapStyleSwitcher,
  useLocationTracking,
} from "@/components/ui/mapcn";

/**
 * ThreatHunter360 Ops Node — spatial capability demo (mapcn-rn, every
 * registry component on screen). Center: Lagos, NG.
 *
 * Data below is illustrative only — it is DEMO data, not intelligence.
 */

const LAGOS: [number, number] = [3.3792, 6.5244];
const HQ: [number, number] = [3.4025, 6.4553]; // Tafawa Balewa Square
const GEOFENCE: [number, number] = [3.3514, 6.6018]; // Ikeja GRA

/** ~28 simulated field-report points across Lagos. */
const REPORTS: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    [3.3244, 6.4665, 3], [3.3401, 6.4512, 6], [3.3120, 6.5010, 2],
    [3.3535, 6.4476, 8], [3.3742, 6.6021, 5], [3.3502, 6.5960, 7],
    [3.3300, 6.5830, 4], [3.3958, 6.4470, 9], [3.4210, 6.4300, 6],
    [3.4470, 6.4476, 3], [3.4730, 6.4390, 7], [3.5020, 6.4461, 2],
    [3.3812, 6.5224, 5], [3.3690, 6.5593, 6], [3.3125, 6.5450, 4],
    [3.2950, 6.4690, 8], [3.2780, 6.4420, 1], [3.4290, 6.4630, 5],
    [3.4605, 6.4702, 6], [3.5100, 6.4680, 3], [3.3901, 6.4900, 7],
    [3.3675, 6.4680, 2], [3.3445, 6.4870, 6], [3.5180, 6.4250, 4],
    [3.5550, 6.4380, 5], [3.6020, 6.4690, 2], [3.3980, 6.5150, 6],
    [3.2620, 6.5250, 3],
  ].map(([lng, lat, sev], i) => ({
    type: "Feature" as const,
    id: i,
    properties: { name: `Report ${i + 1}`, sev },
    geometry: { type: "Point" as const, coordinates: [lng, lat] },
  })),
};

/** Simulated LGA risk choropleth (demo values). */
const LGA_RISK: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { id: "lagos-island", name: "Lagos Island", risk: 7.2 },
      geometry: {
        type: "Polygon",
        coordinates: [[[3.375, 6.44], [3.425, 6.44], [3.432, 6.472], [3.382, 6.477], [3.375, 6.44]]],
      },
    },
    {
      type: "Feature",
      properties: { id: "ikeja", name: "Ikeja", risk: 4.1 },
      geometry: {
        type: "Polygon",
        coordinates: [[[3.318, 6.578], [3.382, 6.578], [3.388, 6.628], [3.324, 6.628], [3.318, 6.578]]],
      },
    },
    {
      type: "Feature",
      properties: { id: "etiosa", name: "Eti-Osa", risk: 5.8 },
      geometry: {
        type: "Polygon",
        coordinates: [[[3.448, 6.428], [3.525, 6.428], [3.533, 6.462], [3.462, 6.467], [3.448, 6.428]]],
      },
    },
  ],
};

/** Simulated convoy route: MMIA → Victoria Island. */
const CONVOY_ROUTE: Array<[number, number]> = [
  [3.3212, 6.5774], [3.3540, 6.5810], [3.3580, 6.5240],
  [3.3440, 6.4620], [3.3780, 6.4450], [3.4200, 6.4280],
];

/** Demo cordon polygon (Lekki Phase 1 approximation). */
const CORDON: Array<Array<[number, number]>> = [[
  [3.4550, 6.4400], [3.4900, 6.4380], [3.4950, 6.4580],
  [3.4620, 6.4610], [3.4550, 6.4400],
]];

/** Sensor posts rendered as raw GeoJSON. */
const SENSORS: FeatureCollection = {
  type: "FeatureCollection",
  features: ([
    [3.3510, 6.5240, "S-01"], [3.4100, 6.5000, "S-02"], [3.3000, 6.4700, "S-03"],
  ] as Array<[number, number, string]>).map(([lng, lat, id]) => ({
    type: "Feature" as const,
    id,
    properties: { id },
    geometry: { type: "Point" as const, coordinates: [lng, lat] },
  })),
};

type Overlay = "clusters" | "heat";

export default function App() {
  const [overlay, setOverlay] = useState<Overlay>("clusters");
  const [popupOpen, setPopupOpen] = useState(false);
  const [legend, setLegend] = useState<React.ComponentProps<typeof MapLegend>["data"] | null>(null);
  const [tracking, setTracking] = useState(false);
  const location = useLocationTracking({ accuracy: "balanced", distanceInterval: 10 });

  const toggleLocate = async () => {
    if (tracking) {
      location.stop();
      setTracking(false);
    } else {
      await location.start();
      setTracking(true);
    }
  };

  const onClusterPress = (cluster: Feature) => {
    console.log("cluster pressed:", cluster.properties);
  };

  const onPointPress = (feature: Feature) => {
    console.log("report pressed:", feature.properties);
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <Map
        defaultViewport={{ center: LAGOS, zoom: 10.2 }}
        compass={{ position: "top-right" }}
        attribution={{ position: "bottom-right" }}
      >
        {/* Base layers */}
        <MapChoropleth
          data={LGA_RISK}
          value="risk"
          opacity={0.35}
          onLegendChange={setLegend}
          onFeaturePress={(f) => console.log("LGA pressed:", f.properties)}
        />
        <MapPolygon
          coordinates={CORDON}
          fill={{ color: "#f97316", opacity: 0.15 }}
          stroke={{ color: "#f97316", width: 2 }}
        />
        <MapCircle
          center={GEOFENCE}
          radius={1500}
          fill={{ color: "#8b5cf6", opacity: 0.12 }}
          stroke={{ color: "#8b5cf6", width: 2 }}
        />
        <MapCircle
          center={HQ}
          radius={300}
          units="kilometers"
          fill={false}
          stroke={{ color: "#dc2626", width: 1, dashArray: [4, 3] }}
        />
        <MapRoute coordinates={CONVOY_ROUTE} color="#0ea5e9" width={4} dashArray={[6, 4]} />
        <MapGeoJSON
          data={SENSORS}
          point={{ color: "#7c3aed", radius: 6, strokeColor: "#ffffff", strokeWidth: 2 }}
          fill={false}
          line={false}
        />

        {/* Toggleable analysis overlay */}
        {overlay === "clusters" ? (
          <MapClusterLayer
            data={REPORTS}
            onClusterPress={onClusterPress}
            onPointPress={onPointPress}
          />
        ) : (
          <MapHeatmap
            data={REPORTS}
            weight="sev"
            weightRange={[1, 10]}
            radius={[
              { zoom: 8, value: 14 },
              { zoom: 12, value: 30 },
            ]}
            colors={["#22d3ee", "#a3e635", "#facc15", "#fb923c", "#ef4444"]}
          />
        )}

        {/* Featured marker + popup */}
        <MapMarker coordinate={HQ} label="HQ" onPress={() => setPopupOpen(true)} />
        <MapPopup
          coordinate={HQ}
          visible={popupOpen}
          onClose={() => setPopupOpen(false)}
          closeButton
        >
          <Text style={styles.popupTitle}>ThreatHunter360 HQ</Text>
          <Text style={styles.popupBody}>
            Tafawa Balewa Square · Lagos Island{"\n"}Demo marker popup — no live data.
          </Text>
        </MapPopup>

        {/* Location puck + overlays */}
        <MapLocationPuck
          visible={tracking}
          bearing="heading"
          accuracyRing
          follow={tracking ? "position" : false}
        />
      </Map>

      {/* Chrome (overlays sit outside the map canvas) */}
      <MapStyleSwitcher position="top-left" layout="menu" />
      {legend && <MapLegend data={legend} title="LGA risk (demo)" position="bottom-left" />}
      <MapControls
        position="bottom-right"
        showZoom
        showLocate
        onLocate={() => {
          void toggleLocate();
        }}
      />
      <View style={styles.chips} pointerEvents="box-none">
        <Pressable
          onPress={() => setOverlay("clusters")}
          style={[styles.chip, overlay === "clusters" && styles.chipActive]}
        >
          <Text style={[styles.chipText, overlay === "clusters" && styles.chipTextActive]}>
            Clusters
          </Text>
        </Pressable>
        <Pressable
          onPress={() => setOverlay("heat")}
          style={[styles.chip, overlay === "heat" && styles.chipActive]}
        >
          <Text style={[styles.chipText, overlay === "heat" && styles.chipTextActive]}>
            Heatmap
          </Text>
        </Pressable>
        <Pressable onPress={() => void toggleLocate()} style={styles.chip}>
          <Text style={styles.chipText}>{tracking ? "◉ tracking" : "◎ locate"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  chips: {
    position: "absolute",
    top: 8,
    right: 8,
    flexDirection: "row",
    gap: 6,
  },
  chip: {
    backgroundColor: "rgba(255,255,255,0.92)",
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: "#d4d4d8",
  },
  chipActive: { backgroundColor: "#18181b", borderColor: "#18181b" },
  chipText: { fontSize: 12, color: "#18181b", fontWeight: "600" },
  chipTextActive: { color: "#fafafa" },
  popupTitle: { fontSize: 14, fontWeight: "700", color: "#111827" },
  popupBody: { fontSize: 12, color: "#374151", marginTop: 4 },
});
