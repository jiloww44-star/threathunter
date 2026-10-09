# ThreatHunter360 Ops Node — mobile (mapcn-rn)

Expo app running **mapcn-rn** ([aikenahac/mapcn-react-native](https://github.com/aikenahac/mapcn-react-native),
docs <https://mapcn-rn.dev>) — shadcn-style, copy-owned map components for
React Native — with **every registry component installed and exercised** in
[`App.tsx`](App.tsx) (a Lagos-centered spatial demo: choropleth, cluster
layer, heatmap, route, circles, polygon, markers, popup, controls, legend,
style switcher, location puck + tracking hook, raw GeoJSON).

> Demo data in `App.tsx` is illustrative only. It is not intelligence.

## What was installed (exact commands)

```bash
npx create-expo-app@latest mobile --template blank-typescript   # Expo SDK 57 / RN 0.86
cd mobile
npx mapcn-rn init --renderer maplibre --provider carto --all --yes \
  --registry /tmp/mapcn-mono/apps/docs/public/r                 # see "Registry provenance"
npm install uniwind tailwindcss tailwind-merge clsx             # styling framework (see below)
npx expo prebuild --clean                                       # android/ + ios/ generated (gitignored)
```

Renderer/provider decision: **MapLibre + CARTO**. It is the only
keyless pairing (no API token anywhere), so the demo runs as-is on any
machine. Switch any time with `npx mapcn-rn provider` (MapTiler needs
`EXPO_PUBLIC_MAPTILER_API_KEY`; Mapbox needs public + downloads tokens).

Styling: the copied components style their chrome (controls, popups,
legend, switcher) with utility `className` tokens. mapcn-rn deliberately
does not bundle a styling runtime, so **Uniwind** (the author's own demo
stack, metro-only, no babel) was installed per the official theming doc:
`metro.config.js` (`withUniwindConfig`), `global.css` (shadcn semantic
tokens, copied verbatim from the canonical demo app), `lib/utils.ts`
(`cn`), `uniwind-types.d.ts`. `mapcn.json` records `styling: "uniwind"`.

## Registry provenance (read this before `npx mapcn-rn init` elsewhere)

The CLI hardcodes its registry base URL to `https://mapcn-rn.dev/r`,
which is outside this sandbox's network allowlist. Fortunately the CLI
ships an official escape hatch — `--registry <base>` accepts a local
directory or `file://` URL — and the exact registry the docs site serves
lives in the monorepo at `apps/docs/public/r/`. The install above was
therefore executed with the **official CLI against the author's own
registry content** (schema v2, 16 components + core, sha256 file hashes
recorded in `mapcn.json`). Nothing was patched or hand-copied outside
`components/ui/mapcn/`, `lib/mapcn/`, and `hooks/` — i.e. no registry
file hash was touched. Where network is unrestricted, plain
`npx mapcn-rn init --renderer maplibre --provider carto --all --yes` is
sufficient and equivalent.

`core` lib files (types/geo/scale/colors/provider/style) land in
`lib/mapcn/`; components and the barrel in `components/ui/mapcn/`;
`hooks/use-location-tracking.ts` backs the location pieces.

## Verified here

| Gate | Result |
| --- | --- |
| `npx mapcn-rn doctor` | ✅ all checks passed |
| `npx tsc --noEmit` (whole app incl. copied components) | ✅ clean |
| `npx expo prebuild --clean` | ✅ android/ + ios/ generated, `@maplibre/maplibre-react-native` plugin stamps present in Gradle files |
| Expo plugin + location permissions in `app.json` | ✅ written by `init` |

## Boundaries (honest, not silently skipped)

- **No native binary was built here.** Android needs the Android SDK/Gradle
  downloads; iOS needs macOS/Xcode — both outside this sandbox. Run
  `npm run android` / `npm run ios` on a dev machine. `prebuild` output is
  committed-never (regenerable, gitignored).
- **Expo Go cannot run this app** (native map renderer); use an Expo
  development build — per the mapcn-rn docs.
- Basemap tiles come from CARTO's CDN at runtime; on an offline device the
  map renders styled UI with no basemap.

## Daily commands

```bash
npm start                 # Expo dev server (open in a dev build)
npx mapcn-rn list         # all components + install state
npx mapcn-rn diff         # local edits vs registry (copy-owned model)
npx mapcn-rn add choropleth ...   # already all installed
npx expo prebuild --clean # after ANY renderer/plugin change
```
