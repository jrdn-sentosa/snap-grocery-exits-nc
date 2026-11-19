import type { StoreType, Tier } from "./types";

/** USDA store names arrive in ALL CAPS or mixed case; shout-case names get Title Case, mixed-case names are left alone. */
export function displayName(raw: string): string {
  return dropRepeatedNumber(shoutToTitle(raw));
}

/** USDA sometimes repeats the store number at the end ("Aldi 64011 64011", "Walmart Store #1821 1821"): keep it once. */
export function dropRepeatedNumber(name: string): string {
  return name.replace(/(#?\s*)(\d+)\s+\2\s*$/, "$1$2").trim();
}

function shoutToTitle(raw: string): string {
  const letters = raw.replace(/[^A-Za-z]/g, "");
  if (!letters || letters !== letters.toUpperCase()) return raw.trim();
  return raw
    .toLowerCase()
    .replace(/(^|[\s\-/(&])([a-z])/g, (_, sep: string, ch: string) => sep + ch.toUpperCase())
    .replace(/'S\b/g, "'s")
    .replace(/\b(Llc|Inc|Ii|Iii|Usa)\b/g, (m) => m.toUpperCase())
    .replace(/\s(And|Of|The|At|In|On|By|For|To|A|An)\s/g, (m) => m.toLowerCase())
    .replace(/\s+/g, " ")
    .trim();
}

export function titleCase(s: string | null | undefined): string {
  return s ? displayName(s.toUpperCase()) : "";
}

export const TYPE_SHORT: Record<StoreType, string> = {
  Supermarket: "Supermarket",
  "Super Store": "Super store",
  "Large Grocery Store": "Large grocery",
  "Medium Grocery Store": "Medium grocery",
  "Small Grocery Store": "Small grocery",
};
export const TYPE_ORDER: StoreType[] = ["Small Grocery Store", "Medium Grocery Store", "Large Grocery Store", "Supermarket", "Super Store"];

/** Risk as a percent string. Exits are rare, so small scores keep a decimal: 0.4%, 2.1%, 8.4%, then whole numbers from 10%. */
export function fmtPct(p: number): string {
  const v = p * 100;
  if (v < 0.1) return "<0.1%";
  if (v < 10) return `${v.toFixed(1)}%`;
  return `${Math.round(v)}%`;
}
/** Historical rates (typical for a store type, 2012-2021) always keep one decimal, as in the design: 15.9%, 1.5%. */
export const fmtRate = (p: number) => `${(p * 100).toFixed(1)}%`;
export const fmtShare = (p: number | null | undefined, digits = 0) => (p == null ? "—" : `${(p * 100).toFixed(digits)}%`);
export const fmtInt = (n: number | null | undefined) => (n == null ? "—" : Math.round(n).toLocaleString("en-US"));
/** Distances always show two decimals, so the number on screen is the one the gap rule uses. */
export const fmtMi = (n: number | null | undefined) => (n == null ? "—" : `${n.toFixed(2)} mi`);
export const roundMi = (n: number) => Math.round(n * 100) / 100;

export const TIER_LABEL: Record<Tier, string> = { high: "High", medium: "Medium", low: "Low" };
export const TIER_ORDER: Record<Tier, number> = { high: 0, medium: 1, low: 2 };

/** Tailwind text color per tier. */
export const TIER_TEXT: Record<Tier, string> = { high: "text-tomato", medium: "text-mustard-text", low: "text-ink-2" };

/** Share of scored stores with a lower probability than this one, as a whole percent (never 100). */
export function percentile(prob: number, all: number[]): number {
  if (!all.length) return 0;
  return Math.min(99, Math.floor((all.filter((p) => p < prob).length / all.length) * 100));
}

/** "Leaves a gap": the next SNAP grocery is farther than this many miles (the rule used everywhere on the site). */
export const GAP_MILES = 1;
/** The rule on the distance as displayed (two decimals): 1.004 mi shows as 1.00 mi and is NOT a gap; 1.01 mi is. */
export const isGap = (miles: number | null | undefined) => miles != null && roundMi(miles) > GAP_MILES;
