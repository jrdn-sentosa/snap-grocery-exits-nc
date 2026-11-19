"use client";

import Link from "next/link";
import { NoticeBand } from "@/components/site/notice-band";
import { Skeleton } from "@/components/ui/skeleton";
import { useMeta, useModelInfo, useStores } from "@/lib/data";
import { TYPE_ORDER, TYPE_SHORT, displayName, fmtPct, fmtRate } from "@/lib/format";
import { SUPPORT_NOTE } from "@/lib/site";
import { VALIDATION as V } from "@/lib/validation";
import type { PieCounts } from "@/lib/types";

function H2({ children, id }: { children: React.ReactNode; id?: string }) {
  return (
    <h2 id={id} className="scroll-mt-4 font-serif text-4xl md:text-5xl">
      {children}
    </h2>
  );
}

const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`;

/** Pie of how grocery authorizations ended. The ownership-change slice is pulled out: it is the one that is not an exit. */
function Pie({ pie }: { pie: PieCounts }) {
  const slices = [
    { key: "other_exit", n: 1, share: pie.other_exit.share, color: "#b23a12", text: "#fffdf7" },
    { key: "batch", n: 2, share: pie.batch.share, color: "#d97a57", text: "#fffdf7" },
    { key: "ownership_change", n: 3, share: pie.ownership_change.share, color: "#ecd9b3", text: "#1c2b22" },
  ];
  const R = 90;
  const C = 110;
  let a0 = -Math.PI / 2;
  const arcs = slices.map((s) => {
    const a1 = a0 + s.share * 2 * Math.PI;
    const mid = (a0 + a1) / 2;
    const pull = s.key === "ownership_change" ? 10 : 0;
    const ox = Math.cos(mid) * pull;
    const oy = Math.sin(mid) * pull;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M ${C + ox} ${C + oy} L ${C + ox + R * Math.cos(a0)} ${C + oy + R * Math.sin(a0)} A ${R} ${R} 0 ${large} 1 ${C + ox + R * Math.cos(a1)} ${C + oy + R * Math.sin(a1)} Z`;
    const out = { ...s, d, lx: C + ox + R * 0.6 * Math.cos(mid), ly: C + oy + R * 0.6 * Math.sin(mid) };
    a0 = a1;
    return out;
  });
  return (
    <svg viewBox="0 0 220 220" className="mx-auto w-full max-w-[260px]" role="img" aria-label={`Pie chart: ${slices.map((s) => `${s.key.replace("_", " ")} ${pct1(s.share)}`).join(", ")}`}>
      {arcs.map((s) => (
        <g key={s.key}>
          <path d={s.d} fill={s.color} stroke="#fffdf7" strokeWidth={2} />
          <text x={s.lx} y={s.ly} textAnchor="middle" dominantBaseline="central" fontSize="22" fontFamily="var(--font-fraunces), serif" fontWeight="600" fill={s.text}>
            {s.n}
          </text>
        </g>
      ))}
    </svg>
  );
}

function Tile({ label, value, note }: { label: string; value: React.ReactNode; note: React.ReactNode }) {
  return (
    <div className="py-4">
      <p className="label-mono text-ink-2">{label}</p>
      <div className="mt-1 font-serif text-5xl leading-none">{value}</div>
      <p className="mt-2 text-sm text-ink-2">{note}</p>
    </div>
  );
}

export function HowItWorks() {
  const meta = useMeta();
  const info = useModelInfo();
  const stores = useStores();
  const pie = meta.data?.pie.statewide;
  const rates = meta.data?.type_rates;
  const cut = info.data?.metadata.tier_cutoffs;
  const maxRate = rates ? Math.max(...Object.values(rates.by_type).map((r) => r.rate)) : 1;
  const unscored = (stores.data ?? []).filter((s) => !s.scorable);

  return (
    <div className="mx-auto max-w-[1040px] px-4 pb-4 pt-10 md:px-5">
      <p className="label-mono text-forest">Methods</p>
      <h1 className="mt-2 font-serif text-5xl leading-none md:text-7xl">How the risk scores work</h1>
      <p className="mt-5 max-w-3xl text-xl text-ink-2">
        Using only what was known on January 1 of a year, we estimate whether a SNAP-authorized grocery store will stop accepting SNAP within the next 12 months. The model learns from every grocery
        store in North Carolina; this site focuses on Mecklenburg County and shows scores as of <strong className="text-ink">Jan 1, 2024</strong>.
      </p>

      <section className="mt-14" aria-labelledby="records">
        <H2 id="records">From records to a score</H2>
        <div className="mt-6 grid gap-8 md:grid-cols-3">
          {[
            ["01", "Data", "USDA’s SNAP retailer records, 2005–2025: each store’s type, location and authorization dates, joined to Census ACS 5-year neighborhood data for the store’s census tract. Every input uses only information available on Jan 1 of the year being scored."],
            ["02", "Model", "Gradient-boosted trees. Settings were chosen on rolling folds inside 2012–2018; the final model is trained on 2012–2021 and frozen. The test years 2022–2024 are held out and evaluated once."],
            ["03", "Score", "Each store gets a 0–100% chance of exiting in the next 12 months, grouped into Low, Medium and High. The cutoffs were set on the 2019–2021 validation years."],
          ].map(([n, t, body]) => (
            <div key={n} className="border-t-2 border-ink pt-3">
              <p className="font-serif text-5xl italic text-forest">{n}</p>
              <h3 className="mt-2 font-medium">{t}</h3>
              <p className="mt-1 text-ink-2">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-14" aria-labelledby="exit">
        <H2 id="exit">What counts as an exit</H2>
        <div className="mt-6 grid gap-6 border-t-2 border-ink pt-4 md:grid-cols-2">
          <div>
            <h3 className="flex items-center gap-2 font-medium">
              <span aria-hidden className="inline-block size-3.5 rounded-full border-2 border-tomato bg-tomato" /> Exit
            </h3>
            <p className="mt-1 text-ink-2">
              A store’s SNAP authorization ends and no successor takes over. That includes <strong className="text-ink">batch deauthorizations</strong>: dates when USDA ended many stores at once. They are counted as exits
              because those stores did lose SNAP.
            </p>
          </div>
          <div>
            <h3 className="flex items-center gap-2 font-medium">
              <span aria-hidden className="inline-block size-3.5 rounded-full border-2 border-ink-2 bg-paper-light" /> Not an exit: ownership change
            </h3>
            <p className="mt-1 text-ink-2">
              A different USDA record picks up the same store, so the store kept going under new owners. We treat it as a successor when the new record has a matching name nearby (within about 0.15 mile) or is at
              the identical street address, and was authorized shortly before or within 90 days after the old one ended. The same store registered twice also counts. A short list of reviewed exceptions is never treated
              as a successor. A gap of 90 days or less in a single store’s own record does not end its authorization.{" "}
              <a className="text-forest underline underline-offset-2" href="https://github.com/jrdn-sentosa/snap-grocery-exits-nc/blob/main/docs/label_rule_change.md">
                The full rule and its history
              </a>
              .
            </p>
          </div>
        </div>

        <div className="mt-8 grid items-center gap-8 md:grid-cols-[260px_minmax(0,1fr)]">
          {pie ? <Pie pie={pie} /> : <Skeleton className="mx-auto size-56 rounded-full" />}
          <div>
            <h3 className="font-medium">How SNAP grocery authorizations ended, North Carolina, through 2021</h3>
            <p className="label-mono mt-1 text-ink-2">The served slice isn’t an exit: the store kept going under new owners</p>
            <ol className="mt-3 divide-y divide-rule border-y border-rule">
              {[
                ["1", "Other exits", "Authorization ended and no successor took over.", pie?.other_exit, "#b23a12"],
                ["2", "Batch deauthorizations", "Ended on a date when many stores lost authorization at once. Counted as exits; results without them are reported too.", pie?.batch, "#d97a57"],
                ["3", "Ownership changes", "A successor record took over the same store. Not counted as an exit.", pie?.ownership_change, "#ecd9b3"],
              ].map(([n, t, body, share, color]) => (
                <li key={n as string} className="flex items-start gap-3 py-2.5">
                  <span className="mt-0.5 grid size-5 shrink-0 place-items-center text-xs font-medium" style={{ background: color as string, color: n === "3" ? "#1c2b22" : "#fffdf7" }}>
                    {n as string}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{t as string}</p>
                    <p className="text-sm text-ink-2">{body as string}</p>
                  </div>
                  <span className="font-mono text-sm tabular-nums">{share ? pct1((share as { share: number }).share) : "…"}</span>
                </li>
              ))}
            </ol>
            <p className="label-mono mt-2 text-ink-2">{pie ? `${pie.ended.toLocaleString("en-US")} ended grocery authorizations, all of North Carolina, 2005–2021` : ""}</p>
          </div>
        </div>
        <p className="mt-8 border-t border-rule pt-6 font-serif text-2xl italic leading-snug text-ink-2">
          An exit isn’t always a closure. A store can also withdraw from SNAP or be disqualified. For a household that uses SNAP, the result is the same: they can no longer use their benefits there.
        </p>

        <h3 className="mt-8 font-medium">When an exit “leaves a gap”</h3>
        <p className="mt-1 max-w-3xl text-ink-2">
          A gap means the next SNAP grocery is more than 1.00 mile away, rounded to two decimals. It is measured in a straight line from the store, so a store that shows “1.00 mi” is never also marked “leaves a gap”.{" "}
          {meta.data && (
            <>
              Among Mecklenburg’s {meta.data.past_exit_gap.exits} exits in {meta.data.past_exit_gap.years[0]}–{meta.data.past_exit_gap.years[1]}, {meta.data.past_exit_gap.gap_exits} left a gap (
              {Math.round(meta.data.past_exit_gap.share * 100)}%).{" "}
            </>
          )}
          <a className="text-forest underline underline-offset-2" href="https://github.com/jrdn-sentosa/snap-grocery-exits-nc/blob/main/docs/gap_rule.md">
            The rule
          </a>
          .
        </p>
      </section>

      <section className="mt-14" aria-labelledby="type">
        <H2 id="type">Store type matters most</H2>
        <div className="mt-6 grid gap-10 md:grid-cols-[minmax(0,1fr)_300px]">
          <div>
            <h3 className="font-medium">Share of NC grocery stores that exited within a year</h3>
            <p className="label-mono mt-1 text-ink-2">
              By USDA store type · {rates ? `${rates.years[0]}–${rates.years[1]}` : "2012–2021"}, the final model’s training years · the baseline to beat
            </p>
            <ul className="mt-4 space-y-2">
              {TYPE_ORDER.map((t) => {
                const r = rates?.by_type[t];
                return (
                  <li key={t} className="grid grid-cols-[110px_minmax(0,1fr)_56px] items-center gap-3 text-sm">
                    <span>{TYPE_SHORT[t]}</span>
                    <span className="h-5 bg-rule" aria-hidden>
                      <span className="block h-5 bg-forest" style={{ width: r ? `${(r.rate / maxRate) * 100}%` : "0%" }} />
                    </span>
                    <span className="text-right font-mono tabular-nums">{r ? fmtRate(r.rate) : "…"}</span>
                  </li>
                );
              })}
            </ul>
            {rates && (
              <p className="mt-3 text-sm text-ink-2">
                All grocery types together: {fmtRate(rates.overall.rate)} a year, across {rates.overall.store_years.toLocaleString("en-US")} store-years in North Carolina.
              </p>
            )}
          </div>
          <div>
            <h3 className="font-medium">Risk levels on this site</h3>
            <dl className="mt-3 space-y-3 text-sm">
              <div className="grid grid-cols-[70px_minmax(0,1fr)] gap-2">
                <dt className="label-mono text-tomato">High</dt>
                <dd>{cut ? `${fmtPct(cut.high)} or more: at least twice the average exit rate` : <Skeleton className="h-4 w-40" />}</dd>
              </div>
              <div className="grid grid-cols-[70px_minmax(0,1fr)] gap-2">
                <dt className="label-mono text-mustard-text">Medium</dt>
                <dd>{cut ? `${fmtPct(cut.low)} to under ${fmtPct(cut.high)}` : <Skeleton className="h-4 w-40" />}</dd>
              </div>
              <div className="grid grid-cols-[70px_minmax(0,1fr)] gap-2">
                <dt className="label-mono text-ink-2">Low</dt>
                <dd>{cut ? `Under ${fmtPct(cut.low)}: less than half the average exit rate` : <Skeleton className="h-4 w-40" />}</dd>
              </div>
            </dl>
            <p className="mt-3 text-sm text-ink-2">
              Cutoffs come from the live model service and are set relative to the {pct1(V.baseRate)} average exit rate in the training years. Exits are rare, so a 15% score is very high even though it sounds low. They were
              chosen on the validation years 2019–2021, never on the test years.
            </p>
          </div>
        </div>
      </section>

      <section className="mt-14" aria-labelledby="works">
        <H2 id="works">How well it works</H2>
        <p className="mt-3 max-w-3xl text-ink-2">
          We don’t report accuracy: with about 4% of stores exiting each year, predicting “no exit” for everyone would be 96% accurate and useless. We compare against the store-type baseline above instead, and the model is modestly better:
          a higher score means more risk, not a forecast.
        </p>

        <h3 className="mt-6 font-medium">
          Validation, {V.years} <span className="label-mono ml-2 border border-ink px-1.5 py-0.5 text-[0.625rem]">Validation, not test</span>
        </h3>
        <p className="text-sm text-ink-2">Models fit on {V.fitYears} and scored on {V.years}. The same store-years for the model and the baseline. These are validation results: we tuned on earlier folds and set the tier cutoffs on these years.</p>
        <div className="mt-2 grid gap-x-8 border-y-2 border-ink sm:grid-cols-2 lg:grid-cols-4">
          <Tile label="Precision-recall AUC" value={V.prAuc.model.toFixed(3)} note={`Baseline ${V.prAuc.baseline.toFixed(3)}. Model 95% interval ${V.prAuc.modelCi}; difference ${V.prAuc.diffCi}.`} />
          <Tile label="Hits in top 10, Mecklenburg" value={`${V.meckTop10.model} of ${V.meckTop10.flagged}`} note={`Baseline ${V.meckTop10.baseline} of ${V.meckTop10.flagged}. 10 stores a year flagged, 3 years.`} />
          <Tile label="Hits in top 50, statewide" value={`${V.top50.model} of ${V.top50.flagged}`} note={`Baseline ${V.top50.baseline} of ${V.top50.flagged}. 50 stores a year flagged, 3 years.`} />
          <Tile label="Brier score" value={V.brier.model.toFixed(4)} note={`Baseline ${V.brier.baseline.toFixed(4)}. Calibration; lower is better.`} />
        </div>
        <p className="mt-4 max-w-3xl text-sm text-ink-2">
          By tier on {V.years}: the Low tier had {V.tiers[0].exits} exits in {V.tiers[0].storeYears.toLocaleString("en-US")} store-years ({pct1(V.tiers[0].rate)}), Medium {V.tiers[1].exits} in{" "}
          {V.tiers[1].storeYears.toLocaleString("en-US")} ({pct1(V.tiers[1].rate)}), and High {V.tiers[2].exits} in {V.tiers[2].storeYears} ({pct1(V.tiers[2].rate)}), against a {pct1(V.baseRate)} average. The cutoffs were chosen on
          these same years, so this shows how well they separate the groups, not how they will do on new years.
        </p>

        <h3 className="mt-8 font-medium">
          Test, 2022–2024 <span className="label-mono ml-2 border border-ink px-1.5 py-0.5 text-[0.625rem]">Held out</span>
        </h3>
        <div className="mt-2 grid gap-x-8 border-y-2 border-ink sm:grid-cols-2 lg:grid-cols-4">
          {["Precision-recall AUC", "Hits in top 10, Mecklenburg", "Hits in top 50, statewide", "Brier score"].map((l) => (
            <Tile key={l} label={l} value={<span className="text-2xl leading-tight">Evaluated once, after all choices are fixed</span>} note="Baseline evaluated at the same time." />
          ))}
        </div>
      </section>

      <section className="mt-14" aria-labelledby="limits">
        <H2 id="limits">Limits and fairness</H2>
        <NoticeBand className="mt-6" />
        <p className="mt-3 max-w-3xl text-ink-2">
          The new USDA stocking rules are in effect now: every SNAP store must carry 7 varieties in each of 4 staple groups (dairy, fruits and vegetables, grains, and protein). The model was trained on years before the rule, so its
          scores don’t reflect it. Stores that struggle to stock the required variety may be at greater risk than shown.
        </p>

        <div className="mt-8 grid gap-x-10 gap-y-8 md:grid-cols-2">
          <div className="border-t-2 border-ink pt-3">
            <h3 className="font-medium">Higher risk, not a forecast</h3>
            <p className="mt-1 text-ink-2">The model separates higher-risk from lower-risk stores only modestly. Most stores it flags as high risk did not exit in the validation years, and some stores it scored low did. Treat a score as a prompt to check in.</p>
          </div>
          <div className="border-t-2 border-ink pt-3">
            <h3 className="font-medium">Scores are as of Jan 1, 2024</h3>
            <p className="mt-1 text-ink-2">The 12 months after that date have already passed, so these are not live forecasts. Their accuracy on 2022–2024 is reported only after the test evaluation.</p>
          </div>
          <div className="border-t-2 border-ink pt-3">
            <h3 className="font-medium">Some stores can’t be scored</h3>
            <p className="mt-1 text-ink-2">
              {unscored.length > 0 ? `${unscored.length} Mecklenburg stores (${unscored.map((s) => displayName(s.name)).join(" and ")})` : "A few stores"} have no chain size in the USDA data, and the scoring service requires it. They appear on the map as “not scored”.
              On the Check page, such a store is assumed independent, and the page says so.
            </p>
          </div>
          <div className="border-t-2 border-ink pt-3">
            <h3 className="font-medium">Distance is simplified</h3>
            <p className="mt-1 text-ink-2">Distances are straight lines measured from the store, not from where residents live. They ignore highways, bus routes and whether the next store is a full-service grocery. Household counts are for the whole census tract, not the store’s customers.</p>
          </div>
          <div className="border-t-2 border-ink pt-3">
            <h3 className="font-medium">Tracts with too little data</h3>
            <p className="mt-1 text-ink-2">The map leaves a tract unshaded if it had fewer than {meta.data?.shading.min_store_years ?? 15} grocery store-years in 2008–2021, because one closure would swing the share. A blank tract does not mean no exits. Tracts that never had a SNAP grocery are shown in grey. Past-exit shading includes batch deauthorizations.</p>
          </div>
          <div className="border-t-2 border-ink pt-3">
            <h3 className="font-medium">Missing history and what the data can’t see</h3>
            <p className="mt-1 text-ink-2">Stores that left SNAP before 2005 aren’t in USDA’s file, so the model learns only from stores that had already lasted that long. Sales, rent, leases and owners’ plans drive most exits, and none of that is public.</p>
          </div>
        </div>

        <div className="mt-8 border-t-2 border-ink pt-3" id="fairness">
          <h3 className="font-medium">Patterns, not causes: a fairness check</h3>
          <p className="mt-1 max-w-3xl text-ink-2">
            We compared error rates across neighborhoods on the validation years. Among stores that did <em>not</em> exit, a larger share in majority-Black tracts landed in the model’s top 50 for the year: {pct1(V.fairness.withDemographics.black.fpr)} (
            {V.fairness.withDemographics.black.flagged} of {V.fairness.withDemographics.black.nonExits}) against {pct1(V.fairness.withDemographics.white.fpr)} ({V.fairness.withDemographics.white.flagged} of{" "}
            {V.fairness.withDemographics.white.nonExits.toLocaleString("en-US")}) in majority-White tracts, with only 29 and 131 exits in those groups, so the numbers are rough.
          </p>
          <p className="mt-2 max-w-3xl text-ink-2">
            We tested removing the seven tract demographic inputs (income, poverty, SNAP and rent shares, cars, age 65+, unemployment). The gap did not shrink ({pct1(V.fairness.withoutDemographics.black.fpr)} against{" "}
            {pct1(V.fairness.withoutDemographics.white.fpr)}), so it likely comes from store type and chain size rather than from the neighborhood demographics. Under the rule we set in advance, removing them lost too much
            accuracy (mean fold PR-AUC {V.fairness.foldPrAuc.without.toFixed(4)} against a {V.fairness.foldPrAuc.bar.toFixed(3)} bar), so the model keeps them. These are statistical patterns, not causes.
          </p>
          <p className="mt-3 max-w-3xl border-l-4 border-forest pl-3 text-ink-2" role="note">
            {SUPPORT_NOTE}
          </p>
        </div>
      </section>

      <section className="mt-14" aria-labelledby="sources">
        <H2 id="sources">Data sources</H2>
        <ol className="mt-6 border-t-2 border-ink">
          {[
            ["USDA FNS, SNAP Retailer Locator: historical data", "Stores, types, locations and authorization dates, 2005–2025", "https://www.fns.usda.gov/snap/retailer-locator/data"],
            ["U.S. Census Bureau, American Community Survey 5-year estimates", "Income, poverty, cars, SNAP households, rent, age and unemployment by census tract", "https://www.census.gov/data/developers/data-sets/acs-5year.html"],
            ["U.S. Census Bureau, TIGER/Line shapefiles", "Census tract boundaries (2010 and 2020)", "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html"],
            ["USDA ERS, Rural-Urban Commuting Area codes", "Urban, small-town and rural status, used to describe where exits happen", "https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes"],
          ].map(([t, d, href], i) => (
            <li key={t} className="flex gap-4 border-b border-rule py-3">
              <span className="label-mono text-ink-2">[{i + 1}]</span>
              <div>
                <a href={href} className="font-medium text-forest underline underline-offset-2">
                  {t}
                </a>
                <p className="text-sm text-ink-2">{d}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-sm text-ink-2">
          Model served with FastAPI on Modal; site on Vercel.{" "}
          <Link href="/highest-risk" className="text-forest underline underline-offset-2">
            See the highest-risk stores
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
