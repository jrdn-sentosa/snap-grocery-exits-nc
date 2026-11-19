import type { Row } from "./derived";
import { GAP_MILES, displayName } from "./format";

function cell(v: string | number | boolean | null | undefined): string {
  if (v == null) return "";
  const s = String(v);
  // quote anything with a comma, quote, newline; neutralise spreadsheet formulas (=, +, -, @ at the start of a text cell)
  const safe = typeof v === "string" && /^[=+\-@]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** The outreach list as CSV, in the order given (rank 1 first). Scores are as of Jan 1, 2024. */
export function outreachCsv(ranked: Row[]): string {
  const head = [
    "rank", "record_id", "store", "store_type", "address", "zip", "risk_12m", "risk_level", "typical_rate_for_type", "access_impact", "priority",
    "next_snap_grocery_mi", "leaves_gap_over_1mi", "tract_snap_households", "tract_no_car_households", "nearest_alternative", "nearest_alternative_mi", "scored_as_of",
  ];
  const lines = ranked.map(({ store, pred, typical }, i) => {
    const alt = store.alternatives[0];
    const d = store.context.dist_next_grocery_mi;
    return [
      i + 1, store.record_id, displayName(store.name), store.store_type, store.address, store.zip, pred ? +pred.probability.toFixed(4) : null, pred?.tier,
      typical != null ? +typical.toFixed(4) : null, pred ? +pred.impact.toFixed(3) : null, pred ? +pred.priority.toFixed(4) : null,
      d != null ? +d.toFixed(2) : null, d == null ? null : d > GAP_MILES, store.context.tract_snap_households, store.context.tract_no_car_households,
      alt ? displayName(alt.name) : null, alt?.distance_mi, "2024-01-01",
    ].map(cell).join(",");
  });
  return [head.join(","), ...lines].join("\r\n") + "\r\n";
}

export function downloadText(filename: string, text: string, type = "text/csv;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
