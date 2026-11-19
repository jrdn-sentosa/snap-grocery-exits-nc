import Link from "next/link";
import { Barcode } from "@/components/site/barcode";
import type { Row } from "@/lib/derived";
import { isGap, TIER_TEXT, TYPE_SHORT, displayName, fmtInt, fmtMi, fmtPct } from "@/lib/format";

/** One outreach "shelf tag". Needs a scored row. */
export function ShelfTag({ row, rank }: { row: Row; rank: number }) {
  const { store, pred, typical } = row;
  if (!pred) return null;
  const d = store.context.dist_next_grocery_mi;
  const gap = isGap(d);
  const alt = store.alternatives[0];
  const ratio = typical ? pred.probability / typical : null;
  return (
    <article className="border border-ink bg-paper-light" aria-label={`Rank ${rank}: ${displayName(store.name)}`}>
      <div className="label-mono flex justify-between bg-forest px-3 py-1.5 text-paper-light">
        <span>SNAP exit risk</span>
        <span>No. {rank}</span>
      </div>
      <div className="p-3">
        <h3 className="truncate text-lg font-medium leading-tight">
          <Link href={`/?store=${store.record_id}`} className="underline-offset-2 hover:underline">
            {displayName(store.name)}
          </Link>
        </h3>
        <p className="label-mono mt-0.5 text-ink-2">
          {TYPE_SHORT[store.store_type]} · {store.zip ?? "—"}
        </p>
        <div className="mt-3 flex items-end justify-between gap-2">
          <div>
            <p className={`font-number text-5xl font-semibold leading-none ${TIER_TEXT[pred.tier]}`}>{fmtPct(pred.probability)}</p>
            <p className="label-mono mt-1 text-ink-2">Per 12 months</p>
          </div>
          {typical != null && (
            <p className="label-mono border border-ink px-2 py-1 text-right leading-snug">
              Typical
              <br />
              {fmtPct(typical)}
              {ratio != null && (
                <>
                  <br />
                  <strong>{ratio.toFixed(1)}×</strong>
                </>
              )}
            </p>
          )}
        </div>
        <hr className="my-3 border-dashed border-rule" />
        <dl className="space-y-1 text-sm">
          <div className="flex items-baseline justify-between gap-2">
            <dt className="label-mono">Next SNAP grocery</dt>
            <dd className="font-mono tabular-nums">{fmtMi(d)}</dd>
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <dt className="label-mono">Priority (risk × impact)</dt>
            <dd className="font-mono tabular-nums">{pred.priority.toFixed(3)}</dd>
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <dt className="label-mono">No-car households in tract</dt>
            <dd className="font-mono tabular-nums">{fmtInt(store.context.tract_no_car_households)}</dd>
          </div>
        </dl>
        <p className="mt-2 truncate text-sm text-ink-2">{alt ? `Nearest: ${displayName(alt.name)} · ${fmtMi(alt.distance_mi)}` : "No nearby alternative found"}</p>
        <div className="mt-3 flex items-center justify-between gap-2">
          {gap ? (
            <span className="label-mono bg-tomato px-2 py-1 font-medium text-paper-light">Leaves a gap</span>
          ) : (
            <span className="label-mono text-ink-2">SNAP store nearby</span>
          )}
          <Barcode value={store.record_id} className="h-6 w-16" />
        </div>
      </div>
    </article>
  );
}
