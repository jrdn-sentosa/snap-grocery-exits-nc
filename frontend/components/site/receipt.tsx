"use client";

import { ArrowDown, ArrowUp, Link2, Printer } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Barcode } from "@/components/site/barcode";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Row } from "@/lib/derived";
import { GAP_MILES, isGap, TIER_LABEL, TIER_TEXT, TYPE_SHORT, displayName, fmtInt, fmtMi, fmtPct, fmtRate, titleCase } from "@/lib/format";
import type { Tier } from "@/lib/types";

const STAMP: Record<Tier, string> = {
  high: "border-tomato text-tomato",
  medium: "border-mustard-text text-mustard-text",
  low: "border-ink-2 text-ink-2",
};

function Line({ label, value, sub }: { label: string; value: React.ReactNode; sub?: boolean }) {
  return (
    <div className={`flex items-baseline gap-2 ${sub ? "pl-3 text-ink-2" : ""}`}>
      <span className="label-mono shrink-0">{label}</span>
      <span className="min-w-0 flex-1 border-b border-dotted border-rule" />
      <span className="font-mono text-sm tabular-nums">{value}</span>
    </div>
  );
}

export function ReceiptSkeleton() {
  return (
    <div className="space-y-3 border border-rule bg-paper-light p-5" aria-busy="true" aria-label="Loading store details">
      <Skeleton className="mx-auto h-3 w-40" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
      <Skeleton className="ml-auto h-12 w-24" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export function Receipt({ row, scoresLoading }: { row: Row; scoresLoading?: boolean }) {
  const { store, pred, pct, typical } = row;
  const c = store.context;
  const dist = c.dist_next_grocery_mi;
  const gap = isGap(dist);
  const [copied, setCopied] = useState(false);
  const since = store.since_year ? `since ${store.since_year}` : "since before 2005 (exact year not recorded)";
  const owner = store.independent == null ? "ownership unknown" : store.independent ? "independent" : `chain of ${store.chain_size} in NC`;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(`${location.origin}/?store=${store.record_id}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked: the address bar already holds the link */
    }
  }

  return (
    <div>
      <article className="relative border border-rule bg-paper-light px-5 pb-8 pt-5 print:border-0" aria-label={`Risk check for ${displayName(store.name)}`}>
        <header className="text-center">
          <p className="label-mono font-medium">Grocery Watch · Charlotte</p>
          <p className="label-mono mt-1 text-ink-2">SNAP risk check · Jan 1, 2024</p>
        </header>
        <hr className="my-4 border-dashed border-rule" />
        <h2 className="font-mono text-[0.9375rem] font-medium uppercase leading-snug">{displayName(store.name)}</h2>
        <p className="label-mono mt-1 text-ink-2">
          {[titleCase(store.address), store.zip].filter(Boolean).join(" · ")}
        </p>
        <p className="label-mono text-ink-2">
          {TYPE_SHORT[store.store_type]} · {owner}
        </p>
        <p className="label-mono text-ink-2">Accepts SNAP {since}</p>
        <hr className="my-4 border-dashed border-rule" />

        <p className="label-mono">12-month exit risk</p>
        {pred ? (
          <>
            <div className="flex items-end justify-between gap-3 pt-1">
              <p className="max-w-[9rem] font-mono text-xs leading-snug text-ink-2">Chance this store stops accepting SNAP</p>
              <p className={`font-number text-6xl font-semibold leading-none ${TIER_TEXT[pred.tier]}`}>{fmtPct(pred.probability)}</p>
            </div>
            <div className="mt-3 space-y-1">
              {typical != null && <Line label={`Typical ${TYPE_SHORT[store.store_type].toLowerCase()}`} value={fmtRate(typical)} />}
              {pct != null && <Line label="Riskier than" value={`${pct}% of Mecklenburg stores`} />}
            </div>
          </>
        ) : scoresLoading ? (
          <Skeleton className="mt-2 h-14 w-full" />
        ) : (
          <p className="mt-2 text-sm text-ink-2">
            {store.scorable
              ? "No score yet: the scoring service did not answer."
              : `Not scored: the data for this store is incomplete (${store.unscorable_reason}).`}
          </p>
        )}

        <hr className="my-4 border-dashed border-rule" />
        <p className="label-mono">If it stopped taking SNAP</p>
        <div className="mt-2 space-y-1">
          <Line label="Nearest other SNAP grocery" value={fmtMi(dist)} />
          <Line label="SNAP households in tract" value={fmtInt(c.tract_snap_households)} />
          <Line label="No-car households in tract" value={fmtInt(c.tract_no_car_households)} />
        </div>
        <p className="mt-3 text-xs leading-snug text-ink-2">
          {dist == null
            ? "Distance to the next SNAP grocery is not available for this store."
            : gap
              ? `The next SNAP grocery is more than ${GAP_MILES} mile away, so neighbors without a car could be left without a store they can reach.`
              : `Another SNAP grocery is within ${GAP_MILES} mile, so most neighbors would still have a store nearby.`}{" "}
          Household counts are for the whole census tract (ACS 2018–2022), not just this store’s customers.
        </p>

        {pred && (
          <div
            className={`mx-auto mt-5 w-fit -rotate-3 border-2 px-3 py-1 font-mono text-sm font-medium uppercase tracking-[0.2em] ${STAMP[pred.tier]}`}
            aria-label={`${TIER_LABEL[pred.tier]} risk`}
          >
            {TIER_LABEL[pred.tier]} risk
          </div>
        )}
        <Barcode value={store.record_id} className="mx-auto mt-4 h-10 w-40" />
        <p className="mt-1 text-center font-mono text-sm tracking-[0.3em]">{store.record_id}</p>
        <p className="label-mono text-center text-ink-2">USDA SNAP record ID</p>
        <p className="label-mono mt-4 text-center text-[0.625rem] text-ink-2">Statistical estimate · not a forecast</p>
        <div
          aria-hidden
          className="absolute inset-x-0 -bottom-2 h-2 bg-[linear-gradient(135deg,var(--paper-light)_25%,transparent_25%),linear-gradient(225deg,var(--paper-light)_25%,transparent_25%)] bg-[length:10px_10px]"
        />
      </article>

      <div className="no-print mt-4 flex gap-2">
        <Button type="button" variant="outline" size="sm" onClick={copyLink}>
          <Link2 aria-hidden /> {copied ? "Link copied" : "Copy link"}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => window.print()}>
          <Printer aria-hidden /> Print receipt
        </Button>
        <Link href={`/check?store=${store.record_id}`} className="inline-flex min-h-8 items-center rounded-md border border-rule bg-paper-light px-3 text-sm hover:bg-paper">
          Change a detail and re-check
        </Link>
      </div>

      <section className="mt-8" aria-labelledby="alts">
        <h3 id="alts" className="border-b-2 border-ink pb-1 font-serif text-2xl">
          Nearest SNAP alternatives
        </h3>
        {store.alternatives.length ? (
          <ul>
            {store.alternatives.map((a) => (
              <li key={a.record_id} className="flex items-baseline justify-between gap-3 border-b border-rule py-2">
                <div>
                  <p className="font-medium">{displayName(a.name)}</p>
                  <p className="label-mono text-ink-2">{TYPE_SHORT[a.store_type]}</p>
                </div>
                <p className="font-mono text-sm">{fmtMi(a.distance_mi)}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-2 text-sm text-ink-2">No other SNAP grocery found.</p>
        )}
      </section>

      <section className="mt-8" aria-labelledby="why">
        <h3 id="why" className="border-b-2 border-ink pb-1 font-serif text-2xl">
          What’s behind this score
        </h3>
        {pred && pred.reasons.length > 0 ? (
          <ul>
            {pred.reasons.map((r) => {
              const up = r.effect > 0;
              return (
                <li key={r.feature} className="flex items-center gap-3 border-b border-rule py-2">
                  <span className={`grid size-8 shrink-0 place-items-center rounded-full ${up ? "bg-raises text-tomato" : "bg-lowers text-forest"}`}>
                    {up ? <ArrowUp className="size-4" aria-hidden /> : <ArrowDown className="size-4" aria-hidden />}
                  </span>
                  <div>
                    <p>{r.text}</p>
                    <p className="label-mono text-ink-2">{up ? "Raises risk" : "Lowers risk"}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="py-2 text-sm text-ink-2">
            {pred ? "Low-risk scores come without a list of reasons." : "Reasons appear once the store is scored."}
          </p>
        )}
        <p className="mt-3 font-serif text-lg italic text-ink-2">These are statistical patterns, not causes. They say nothing about how the store is run.</p>
      </section>
    </div>
  );
}
