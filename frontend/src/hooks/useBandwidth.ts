// §5.4 Accessibility & Universal Design — low-bandwidth degraded mode.
// Auto: honors the user's own network signals (Save-Data header / 2g-class
// effectiveType). Manual override lives in Settings → Access.
// Text-first Strategy Map + verdict summaries are the contract: heavy media
// (map tiles) degrades to text, never blocks core intelligence.
const KEY = "th360.bandwidth";

export type BandwidthMode = "auto" | "on" | "off";

export function getBandwidthMode(): BandwidthMode {
  const v = localStorage.getItem(KEY);
  return v === "on" || v === "off" ? v : "auto";
}

export function setBandwidthMode(mode: BandwidthMode): void {
  localStorage.setItem(KEY, mode);
  applyBandwidthAttr();
  window.dispatchEvent(new Event("th360-bandwidth"));
}

interface NetworkInformationLike {
  saveData?: boolean;
  effectiveType?: string;
}

export function isLowBandwidth(): boolean {
  const mode = getBandwidthMode();
  if (mode === "on") return true;
  if (mode === "off") return false;
  const conn = (navigator as Navigator & {
    connection?: NetworkInformationLike;
  }).connection;
  if (conn?.saveData) return true;
  const t = conn?.effectiveType || "";
  return t === "slow-2g" || t === "2g";
}

export function applyBandwidthAttr(): void {
  const el = document.querySelector(".shell") ?? document.documentElement;
  el.setAttribute("data-bandwidth", isLowBandwidth() ? "low" : "full");
}
