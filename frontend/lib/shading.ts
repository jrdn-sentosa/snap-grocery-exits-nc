import type { TractProps } from "./types";

export type ShadeMode = "exits" | "nocar";

/** Five-step map scale from the mockup README (fewer to more). */
export const SHADE_COLORS = ["#f3e0a8", "#e7b672", "#d98654", "#bc4b24", "#86280d"] as const;
export const NO_SNAP_COLOR = "#e1dbcf";
export const LOW_DATA_COLOR = "#f4efe3";

/** Upper bounds of classes 1-4 (class 5 is everything above). Breaks are fixed, chosen from the spread of the tract values. */
const BREAKS: Record<ShadeMode, number[]> = {
  exits: [0, 0.05, 0.08, 0.12],
  nocar: [0.03, 0.06, 0.1, 0.2],
};

export const SCALE_LABELS: Record<ShadeMode, string[]> = {
  exits: ["0%", "up to 5%", "5–8%", "8–12%", "over 12%"],
  nocar: ["under 3%", "3–6%", "6–10%", "10–20%", "over 20%"],
};

export const MODE_TITLE: Record<ShadeMode, string> = {
  exits: "Share of store-years ending in an exit, 2008–2021",
  nocar: "Households without a car, ACS 2018–2022",
};

export type TractClass = { color: string; label: string; kind: "scale" | "low_data" | "none" | "missing" };

export function classify(p: TractProps, mode: ShadeMode): TractClass {
  if (mode === "exits") {
    if (p.shade_status === "none") return { color: NO_SNAP_COLOR, label: "No SNAP grocery store in 2008–2021", kind: "none" };
    if (p.shade_status === "low_data" || p.exit_share_0821 == null) return { color: LOW_DATA_COLOR, label: "Not enough data", kind: "low_data" };
    return scale(p.exit_share_0821, mode);
  }
  if (p.no_car_share == null) return { color: LOW_DATA_COLOR, label: "No data", kind: "missing" };
  return scale(p.no_car_share, mode);
}

function scale(v: number, mode: ShadeMode): TractClass {
  const b = BREAKS[mode];
  let i = b.findIndex((x) => v <= x);
  if (i < 0) i = 4;
  return { color: SHADE_COLORS[i], label: SCALE_LABELS[mode][i], kind: "scale" };
}
