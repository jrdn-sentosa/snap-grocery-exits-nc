"use client";

import { Skeleton } from "@/components/ui/skeleton";
import type { Row } from "@/lib/derived";
import { TIER_LABEL, TIER_TEXT, TYPE_SHORT, displayName, fmtPct } from "@/lib/format";
import type { Tier } from "@/lib/types";

export function TierDot({ tier }: { tier?: Tier }) {
  const cls =
    tier === "high"
      ? "bg-tomato border-tomato-ring"
      : tier === "medium"
        ? "bg-mustard border-mustard-text"
        : tier === "low"
          ? "bg-paper-light border-ink-2"
          : "bg-no-snap border-dashed border-muted-ink";
  return <span aria-hidden className={`inline-block size-3.5 shrink-0 rounded-full border-2 ${cls}`} />;
}

export function StoreList({ rows, selectedId, onSelect, loading }: { rows: Row[]; selectedId?: string | null; onSelect: (id: string) => void; loading?: boolean }) {
  if (loading && rows.length === 0) {
    return (
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-x-6 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading stores">
        {Array.from({ length: 9 }, (_, i) => (
          <li key={i} className="border-b border-rule py-3">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="mt-2 h-3 w-1/2" />
          </li>
        ))}
      </ul>
    );
  }
  if (rows.length === 0) return <p className="py-6 text-ink-2">No stores match.</p>;
  return (
    <ul className="grid grid-cols-[minmax(0,1fr)] gap-x-6 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map(({ store, pred }) => {
        const sel = store.record_id === selectedId;
        return (
          <li key={store.record_id} className="border-b border-rule">
            <button
              type="button"
              aria-pressed={sel}
              onClick={() => onSelect(store.record_id)}
              className={`flex min-h-14 w-full items-center gap-3 px-2 py-2 text-left hover:bg-paper-light ${sel ? "bg-paper-light outline outline-2 outline-ink" : ""}`}
            >
              <TierDot tier={pred?.tier} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{displayName(store.name)}</span>
                <span className="label-mono block truncate text-ink-2">
                  {TYPE_SHORT[store.store_type]} · {store.zip ?? "—"}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block font-mono text-sm tabular-nums">{pred ? fmtPct(pred.probability) : "—"}</span>
                <span className={`label-mono block ${pred ? TIER_TEXT[pred.tier] : "text-ink-2"}`}>{pred ? TIER_LABEL[pred.tier] : "Not scored"}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
