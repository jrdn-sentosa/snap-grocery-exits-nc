"use client";

import { Download, MapPin, Printer } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ApiErrorBanner, WakingNotice } from "@/components/site/api-banner";
import { NoticeBand } from "@/components/site/notice-band";
import { ShelfTag } from "@/components/site/shelf-tag";
import { TierDot } from "@/components/site/store-list";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { downloadText, outreachCsv } from "@/lib/csv";
import { useRows, type Row } from "@/lib/derived";
import { SUPPORT_NOTE } from "@/lib/site";
import { GAP_MILES, isGap, TIER_LABEL, TYPE_ORDER, TYPE_SHORT, displayName, fmtInt, fmtMi, fmtPct } from "@/lib/format";

type RankBy = "priority" | "risk";
const TOP = 10;
const TABLE_PREVIEW = 25;

function Tile({ label, value, note, tone }: { label: string; value: React.ReactNode; note: React.ReactNode; tone?: "red" }) {
  return (
    <div className="py-4">
      <p className="label-mono text-ink-2">{label}</p>
      <div className={`mt-1 font-serif text-6xl leading-none ${tone === "red" ? "text-tomato" : ""}`}>{value}</div>
      <p className="mt-2 text-sm text-ink-2">{note}</p>
    </div>
  );
}

export function HighestRisk() {
  const { rows, stores, scores, meta, info } = useRows();
  const [rankBy, setRankBy] = useState<RankBy>("priority");
  const [type, setType] = useState("all");
  const [zip, setZip] = useState("all");
  const [view, setView] = useState<"tags" | "table">("tags");
  const [expanded, setExpanded] = useState(false);

  const scored = useMemo(() => rows.filter((r) => r.pred), [rows]);
  const zips = useMemo(() => [...new Set(scored.map((r) => r.store.zip).filter((z): z is string => !!z))].sort(), [scored]);
  const ranked = useMemo(() => {
    const key = (r: Row) => (rankBy === "priority" ? r.pred!.priority : r.pred!.probability);
    return scored
      .filter((r) => (type === "all" || r.store.store_type === type) && (zip === "all" || r.store.zip === zip))
      .sort((a, b) => key(b) - key(a) || b.pred!.probability - a.pred!.probability);
  }, [scored, rankBy, type, zip]);

  const cut = info.data?.metadata.tier_cutoffs;
  const gapOf = (r: Row) => isGap(r.store.context.dist_next_grocery_mi);
  const high = scored.filter((r) => r.pred!.tier === "high");
  const highGap = high.filter(gapOf);
  const top = ranked.slice(0, TOP);
  const topGap = top.filter(gapOf).length;
  const pg = meta.data?.past_exit_gap;
  const loading = scores.status === "idle" || scores.status === "loading";
  const shownTable = expanded ? ranked : ranked.slice(0, TABLE_PREVIEW);
  const maxP = Math.max(0.0001, ...ranked.map((r) => r.pred!.probability));
  const notScored = rows.length - scored.length;

  return (
    <div className="mx-auto max-w-[1440px] px-4 pb-4 pt-10 md:px-5">
      <p className="label-mono text-forest">Outreach list</p>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="max-w-5xl font-serif text-5xl leading-none md:text-7xl">Stores most likely to stop accepting SNAP</h1>
          <p className="mt-4 max-w-3xl text-lg text-ink-2">
            For the Food Policy Council and partners. Ranked by each store’s predicted chance of losing SNAP authorization in the 12 months after Jan 1, 2024, weighted by how much access would be lost.
          </p>
        </div>
        <div className="no-print max-w-sm">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!ranked.length}
              onClick={() => downloadText("grocery-watch-outreach-list-2024.csv", outreachCsv(ranked))}
              className="inline-flex min-h-11 items-center gap-2 rounded-md border border-ink bg-paper-light px-4 hover:bg-paper disabled:opacity-50"
            >
              <Download className="size-4" aria-hidden /> Download CSV
            </button>
            <button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-md bg-forest px-4 text-paper-light hover:bg-forest-dark">
              <Printer className="size-4" aria-hidden /> Print outreach list
            </button>
          </div>
          <p className="mt-2 text-xs leading-snug text-ink-2">{SUPPORT_NOTE}</p>
        </div>
      </div>

      {(scores.slow || info.slow) && <div className="mt-6"><WakingNotice /></div>}
      {scores.error && (
        <div className="mt-6">
          <ApiErrorBanner error={scores.error} onRetry={scores.retry} retrying={loading} />
        </div>
      )}
      {stores.error && <p className="mt-6 text-tomato">Could not load the store list. Reload the page.</p>}

      <section aria-label="Summary" className="mt-8 grid gap-x-8 border-y-2 border-ink sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="Grocery stores scored"
          value={loading ? <Skeleton className="h-14 w-24" /> : fmtInt(scored.length)}
          note={`SNAP-authorized, Mecklenburg County${!loading && notScored ? ` · ${notScored} not scored (incomplete data)` : ""}`}
        />
        <Tile
          label="High risk"
          tone="red"
          value={loading ? <Skeleton className="h-14 w-24" /> : fmtInt(high.length)}
          note={cut ? `Scores of ${fmtPct(cut.high)} or more` : "Highest risk level"}
        />
        <Tile
          label="High risk and would leave a gap"
          value={loading ? <Skeleton className="h-14 w-24" /> : fmtInt(highGap.length)}
          note={`Next SNAP grocery more than ${GAP_MILES} mile away`}
        />
        <Tile
          label="Past exits that left a gap"
          value={pg ? `${Math.round(pg.share * 100)}%` : <Skeleton className="h-14 w-24" />}
          note={pg ? `${pg.gap_exits} of ${pg.with_distance} Mecklenburg exits, ${pg.years[0]}–${pg.years[1]}, had no other SNAP grocery within ${pg.gap_distance_mi} mile` : ""}
        />
      </section>

      {!loading && top.length > 0 && (
        <p className="mt-6 flex items-start gap-3 bg-lowers px-4 py-3">
          <MapPin className="mt-1 size-4 shrink-0 text-forest" aria-hidden />
          <span>
            <em className="font-serif text-xl">Where to start.</em>{" "}
            {topGap === 0 ? (
              <>None of these {top.length} stores would leave neighbors more than a mile from another SNAP grocery: each has another SNAP store nearby.</>
            ) : (
              <>
                {topGap} of these {top.length} stores would leave neighbors more than a mile from another SNAP grocery if they exited. Their tags are marked <strong>Leaves a gap</strong>. The other{" "}
                {top.length - topGap} have another SNAP store nearby.
              </>
            )}
          </span>
        </p>
      )}

      <div className="no-print mt-8 flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <div role="group" aria-label="Rank by" className="flex">
            <span className="label-mono mr-2 self-center text-ink-2">Rank by</span>
            {(
              [
                ["priority", "Priority"],
                ["risk", "Risk"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                aria-pressed={rankBy === k}
                onClick={() => setRankBy(k)}
                className={`min-h-11 border border-rule px-3 text-sm first:rounded-l-md last:rounded-r-md ${rankBy === k ? "bg-forest text-paper-light" : "bg-paper-light hover:bg-paper"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <select aria-label="Store type" value={type} onChange={(e) => setType(e.target.value)} className="min-h-11 rounded-md border border-rule bg-paper-light px-2 text-sm">
            <option value="all">All store types</option>
            {TYPE_ORDER.map((t) => (
              <option key={t} value={t}>
                {TYPE_SHORT[t]}
              </option>
            ))}
          </select>
          <select aria-label="ZIP code" value={zip} onChange={(e) => setZip(e.target.value)} className="min-h-11 rounded-md border border-rule bg-paper-light px-2 text-sm">
            <option value="all">All ZIP codes</option>
            {zips.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </div>
        <div role="group" aria-label="View" className="flex">
          <span className="label-mono mr-2 self-center text-ink-2">View</span>
          {(
            [
              ["tags", "Shelf tags"],
              ["table", "Table"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={view === k}
              onClick={() => setView(k)}
              className={`min-h-11 border border-rule px-3 text-sm first:rounded-l-md last:rounded-r-md ${view === k ? "bg-forest text-paper-light" : "bg-paper-light hover:bg-paper"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-3 text-sm text-ink-2">
        {rankBy === "priority"
          ? "Priority = predicted risk × access impact. Impact is half distance to the next SNAP grocery, a quarter the tract’s share of SNAP households and a quarter its share of households without a car."
          : "Ranked by predicted risk alone, ignoring how much access would be lost."}
      </p>

      {/* next to the list; this one also prints (the note beside the buttons is screen-only) */}
      <p className="mt-3 border-l-4 border-forest pl-3 text-sm text-ink-2" role="note">
        {SUPPORT_NOTE}
      </p>

      {loading && (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5" aria-busy="true" aria-label="Loading scores">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-60" />
          ))}
        </div>
      )}

      {!loading && ranked.length === 0 && <p className="mt-8 text-ink-2">{scores.error ? "Scores are not available right now." : "No scored stores match these filters."}</p>}

      {!loading && ranked.length > 0 && view === "tags" && (
        <div className="mt-6 space-y-8">
          {[0, 1].map((shelf) => {
            const slice = top.slice(shelf * 5, shelf * 5 + 5);
            if (!slice.length) return null;
            return (
              <section key={shelf} aria-label={`Shelf ${shelf + 1}`}>
                <p className="label-mono mb-1 text-ink-2">
                  Shelf {shelf + 1} · Ranks {shelf * 5 + 1}–{shelf * 5 + slice.length}
                </p>
                <div className="border-t-8 border-ink bg-[#e3dccb] p-3 pb-4 shadow-[0_3px_0_#d8cfba]">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                    {slice.map((r, i) => (
                      <ShelfTag key={r.store.record_id} row={r} rank={shelf * 5 + i + 1} />
                    ))}
                  </div>
                </div>
              </section>
            );
          })}
          {ranked.length > TOP && (
            <button type="button" onClick={() => setView("table")} className="no-print min-h-11 rounded-md border border-rule bg-paper-light px-4 text-sm hover:bg-paper">
              See all {ranked.length} stores in the table
            </button>
          )}
        </div>
      )}

      {!loading && ranked.length > 0 && view === "table" && (
        <div className="mt-6 overflow-x-auto border-t-2 border-ink">
          <Table className="min-w-[960px]">
            <TableHeader>
              <TableRow>
                <TableHead className="label-mono w-12">No.</TableHead>
                <TableHead className="label-mono">Store</TableHead>
                <TableHead className="label-mono">12-month risk</TableHead>
                <TableHead className="label-mono">vs. typical</TableHead>
                <TableHead className="label-mono text-right">Priority</TableHead>
                <TableHead className="label-mono text-right">Next SNAP grocery</TableHead>
                <TableHead className="label-mono text-right">SNAP hh (tract)</TableHead>
                <TableHead className="label-mono text-right">No-car hh (tract)</TableHead>
                <TableHead className="label-mono">Nearest alternative</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shownTable.map(({ store, pred, typical }, i) => {
                const p = pred!;
                const alt = store.alternatives[0];
                return (
                  <TableRow key={store.record_id}>
                    <TableCell className="font-mono tabular-nums">{i + 1}</TableCell>
                    <TableCell>
                      <Link href={`/?store=${store.record_id}`} className="font-medium underline-offset-2 hover:underline">
                        {displayName(store.name)}
                      </Link>
                      <span className="label-mono block text-ink-2">
                        {TYPE_SHORT[store.store_type]} · {store.zip ?? "—"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <TierDot tier={p.tier} />
                        <span className="w-12 font-mono tabular-nums">{fmtPct(p.probability)}</span>
                        <span className="hidden h-2 w-24 bg-rule sm:block" aria-hidden>
                          <span className="block h-2 bg-tomato" style={{ width: `${(p.probability / maxP) * 100}%` }} />
                        </span>
                        <span className="label-mono text-ink-2">{TIER_LABEL[p.tier]}</span>
                      </span>
                    </TableCell>
                    <TableCell className="font-mono tabular-nums">{typical ? `${(p.probability / typical).toFixed(1)}×` : "—"}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{p.priority.toFixed(3)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{fmtMi(store.context.dist_next_grocery_mi)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{fmtInt(store.context.tract_snap_households)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{fmtInt(store.context.tract_no_car_households)}</TableCell>
                    <TableCell className="text-sm">{alt ? `${displayName(alt.name)} · ${fmtMi(alt.distance_mi)}` : "—"}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {shownTable.length < ranked.length && (
            <button type="button" onClick={() => setExpanded(true)} className="no-print my-4 min-h-11 rounded-md border border-rule bg-paper-light px-4 text-sm hover:bg-paper">
              Show all {ranked.length} stores
            </button>
          )}
        </div>
      )}

      <div className="mt-12 grid gap-10 md:grid-cols-2">
        <section>
          <h2 className="border-t-2 border-ink pt-3 font-serif text-3xl">Use this list to offer support</h2>
          <p className="mt-2 text-ink-2">
            A high score is not a judgment of a store or its owners. It flags places where retention help, help meeting the new stocking rules, or a backup plan like a mobile market could keep food access in place.
          </p>
        </section>
        <section>
          <h2 className="border-t-2 border-ink pt-3 font-serif text-3xl">How “leaves a gap” is counted</h2>
          <p className="mt-2 text-ink-2">
            A store “leaves a gap” when the next SNAP-authorized grocery on Jan 1, 2024 is more than {GAP_MILES} mile away in a straight line. Household counts are for the store’s whole census tract (ACS 2018–2022), not just its customers.{" "}
            <Link href="/how-it-works" className="text-forest underline underline-offset-2">
              Methods
            </Link>
          </p>
        </section>
      </div>
      <NoticeBand className="no-print mt-10" />
    </div>
  );
}
