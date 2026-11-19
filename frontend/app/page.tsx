"use client";

import { ArrowDown, ArrowRight, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, useSyncExternalStore } from "react";
import { ApiErrorBanner, WakingNotice } from "@/components/site/api-banner";
import { NoticeBand } from "@/components/site/notice-band";
import { Receipt, ReceiptSkeleton } from "@/components/site/receipt";
import { ShadeLegend } from "@/components/site/shade-legend";
import { StoreList, TierDot } from "@/components/site/store-list";
import { TractMap } from "@/components/site/tract-map";
import { Skeleton } from "@/components/ui/skeleton";
import { useTracts } from "@/lib/data";
import { useRows } from "@/lib/derived";
import { TIER_LABEL, TYPE_ORDER, TYPE_SHORT, fmtPct, titleCase } from "@/lib/format";
import { type ShadeMode } from "@/lib/shading";
import type { Tier } from "@/lib/types";

export default function Home() {
  const { rows, stores, scores, meta, info } = useRows();
  const tracts = useTracts();
  const [mode, setMode] = useState<ShadeMode>("exits");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [tierFilter, setTierFilter] = useState("all");
  // Selection lives in the URL (?store=<record id>) so "Copy link" works. Derived, not synced by effects: a click wins, then the
  // link's store, then the highest-risk store once scores are in.
  const [picked, setPicked] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const urlId = useSyncExternalStore(
    () => () => {},
    () => new URLSearchParams(location.search).get("store"),
    () => null,
  );
  const known = (id: string | null) => (id && rows.some((r) => r.store.record_id === id) ? id : null);
  const selectedId = known(picked) ?? known(urlId) ?? (rows.find((r) => r.pred) ?? rows[0])?.store.record_id ?? null;
  function select(id: string) {
    setPicked(id);
    history.replaceState(null, "", `/?store=${id}`);
  }

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      rows.filter(({ store, pred }) => {
        if (typeFilter !== "all" && store.store_type !== typeFilter) return false;
        if (tierFilter === "unscored" ? !!pred : tierFilter !== "all" && pred?.tier !== tierFilter) return false;
        if (!q) return true;
        return [store.name, store.address, store.zip, store.city].some((v) => v?.toLowerCase().includes(q));
      }),
    [rows, q, typeFilter, tierFilter],
  );
  const matchIds = useMemo(() => (q || typeFilter !== "all" || tierFilter !== "all" ? new Set(filtered.map((r) => r.store.record_id)) : undefined), [filtered, q, typeFilter, tierFilter]);
  const PREVIEW = 24; // the list starts short; searching or filtering shows every match
  const shown = expanded || matchIds ? filtered : filtered.slice(0, PREVIEW);
  const selected = rows.find((r) => r.store.record_id === selectedId);
  const cut = info.data?.metadata.tier_cutoffs;
  const scoring = scores.status === "loading" || scores.status === "idle";

  return (
    <>
      {/* hero: tract choropleth behind the headline */}
      <section className="relative isolate overflow-hidden border-b-2 border-ink">
        <div className="absolute inset-0 -z-10" aria-hidden>
          {tracts.data && <TractMap tracts={tracts.data} mode="exits" decorative className="h-full w-full" />}
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,var(--paper)_10%,transparent_60%)] opacity-80" />
        </div>
        <div className="mx-auto flex min-h-[420px] max-w-[1440px] flex-col items-center justify-center px-4 py-14 text-center md:min-h-[520px]">
          <p className="label-mono tracking-[0.2em]">Charlotte–Mecklenburg · North Carolina</p>
          <h1 className="mt-4 max-w-4xl font-serif text-5xl leading-[0.95] md:text-8xl">
            Which grocery stores <em className="text-tomato">will lose SNAP?</em>
          </h1>
          <p className="mt-5 max-w-xl text-lg">Predicting SNAP grocery store exits, store by store, and who would be left without one nearby.</p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <a href="#find" className="inline-flex min-h-11 items-center gap-2 rounded-md bg-forest px-4 text-paper-light hover:bg-forest-dark">
              Find a store <ArrowDown className="size-4" aria-hidden />
            </a>
            <Link href="/highest-risk" className="inline-flex min-h-11 items-center rounded-md border border-rule bg-paper-light px-4 hover:bg-paper">
              See highest-risk stores
            </Link>
          </div>
        </div>
        <div className="mx-auto flex max-w-[1440px] flex-col gap-3 px-4 pb-4 md:flex-row md:items-end md:justify-between md:px-5">
          <ShadeLegend mode="exits" />
          <p className="max-w-md border border-ink bg-paper-light px-3 py-2 text-sm">
            Census tracts shaded by the share of SNAP grocery store-years ending in an exit, 2008–2021, including administrative batch deauthorizations. Tracts with fewer than {meta.data?.shading.min_store_years ?? 15} store-years are left
            uncolored.
          </p>
        </div>
      </section>

      <div className="mx-auto max-w-[1440px] space-y-10 px-4 pt-6 md:px-5">
        <NoticeBand />

        <section id="find" className="scroll-mt-4">
          <p className="label-mono text-forest">01 · Find a store</p>
          <h2 className="mt-1 font-serif text-4xl md:text-5xl">
            Pick a store, <em>see what’s at stake</em>
          </h2>
          <p className="mt-2 max-w-xl text-ink-2">Each store’s chance of losing SNAP authorization in the 12 months after Jan 1, 2024, and how far the next SNAP grocery is.</p>

          {(scores.slow || info.slow) && <div className="mt-4"><WakingNotice /></div>}
          {scores.error && (
            <div className="mt-4">
              <ApiErrorBanner error={scores.error} onRetry={scores.retry} retrying={scores.status === "loading"} />
            </div>
          )}
          {stores.error && <p className="mt-4 text-tomato">Could not load the store list. Reload the page.</p>}

          <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
            <div className="min-w-0">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <div className="flex-1">
                  <label htmlFor="q" className="label-mono text-ink-2">
                    Find a store or address
                  </label>
                  <div className="relative mt-1">
                    <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-2" aria-hidden />
                    <input
                      id="q"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && filtered[0] && select(filtered[0].store.record_id)}
                      placeholder="Beatties Ford Rd"
                      className="h-11 w-full rounded-md border border-rule bg-paper-light pl-9 pr-3 outline-none focus-visible:outline-2"
                      autoComplete="off"
                    />
                  </div>
                </div>
                <div role="group" aria-label="Shade the map by" className="flex">
                  <span className="label-mono mr-2 hidden self-center text-ink-2 xl:block">Shade the map by</span>
                  {(
                    [
                      ["exits", "Past exits"],
                      ["nocar", "No-car households"],
                    ] as const
                  ).map(([m, label]) => (
                    <button
                      key={m}
                      type="button"
                      aria-pressed={mode === m}
                      onClick={() => setMode(m)}
                      className={`min-h-11 border border-rule px-3 text-sm first:rounded-l-md last:rounded-r-md ${mode === m ? "bg-forest text-paper-light" : "bg-paper-light hover:bg-paper"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <figure className="mt-4 border border-ink bg-paper-light">
                <figcaption className="label-mono flex justify-between gap-2 border-b border-rule px-4 py-2 text-ink-2">
                  <span className="font-medium text-ink">Plate 1 — Mecklenburg County</span>
                  <span className="hidden sm:inline">Select a store to see its 1-mile area</span>
                </figcaption>
                <div className="mx-auto aspect-[4/5] max-h-[760px] w-full bg-paper">
                  {tracts.data ? (
                    <TractMap tracts={tracts.data} mode={mode} rows={rows} selectedId={selectedId} matchIds={matchIds} onSelect={select} className="h-full w-full" />
                  ) : (
                    <Skeleton className="h-full w-full rounded-none" />
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-rule px-4 py-3 text-xs">
                  <span className="label-mono text-ink-2">12-month risk</span>
                  {(["high", "medium", "low"] as Tier[]).map((t) => (
                    <span key={t} className="flex items-center gap-1.5">
                      <TierDot tier={t} /> {TIER_LABEL[t]}
                      {cut && ` · ${t === "high" ? `${fmtPct(cut.high)} or more` : t === "medium" ? `${fmtPct(cut.low)} to under ${fmtPct(cut.high)}` : `under ${fmtPct(cut.low)}`}`}
                    </span>
                  ))}
                  <span className="flex items-center gap-1.5">
                    <TierDot /> Not scored
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span aria-hidden className="inline-block size-3.5 rounded-full border-2 border-dashed border-ink" /> 1 mile from selected store
                  </span>
                </div>
              </figure>
              <div className="mt-3">
                <ShadeLegend mode={mode} />
              </div>
            </div>

            <aside aria-label="Selected store" className="min-w-0">
              {selected ? <Receipt row={selected} scoresLoading={scoring} /> : <ReceiptSkeleton />}
            </aside>
          </div>
        </section>

        <section aria-labelledby="stores" className="pb-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="stores" className="font-serif text-3xl">
                Stores on this map
              </h2>
              <p className="label-mono text-ink-2">
                {filtered.length} of {rows.length} Mecklenburg grocery stores · sorted by risk{shown.length < filtered.length ? ` · showing ${shown.length}` : ""}
              </p>
            </div>
            <div className="flex gap-2">
              <select aria-label="Store type" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="min-h-11 rounded-md border border-rule bg-paper-light px-2 text-sm">
                <option value="all">All store types</option>
                {TYPE_ORDER.map((t) => (
                  <option key={t} value={t}>
                    {TYPE_SHORT[t]}
                  </option>
                ))}
              </select>
              <select aria-label="Risk level" value={tierFilter} onChange={(e) => setTierFilter(e.target.value)} className="min-h-11 rounded-md border border-rule bg-paper-light px-2 text-sm">
                <option value="all">All risk levels</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
                <option value="unscored">Not scored</option>
              </select>
            </div>
          </div>
          <div className="mt-3 border-t-2 border-ink">
            <StoreList rows={shown} selectedId={selectedId} onSelect={select} loading={stores.loading} />
          </div>
          {shown.length < filtered.length && (
            <button type="button" onClick={() => setExpanded(true)} className="mt-4 min-h-11 rounded-md border border-rule bg-paper-light px-4 text-sm hover:bg-paper">
              Show all {filtered.length} stores
            </button>
          )}
          <p className="mt-6 text-sm text-ink-2">
            Search “{titleCase(query) || "…"}” matches store names, street addresses and ZIP codes. Scores come from the live model; the map shows the same stores.
          </p>
          <Link href="/highest-risk" className="mt-3 inline-flex items-center gap-2 text-forest underline underline-offset-2">
            See highest-risk stores <ArrowRight className="size-4" aria-hidden />
          </Link>
        </section>
      </div>
    </>
  );
}
