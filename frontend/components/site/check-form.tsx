"use client";

import { ArrowDown, ArrowUp, Check } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ApiErrorBanner, WakingNotice } from "@/components/site/api-banner";
import { Barcode } from "@/components/site/barcode";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, predict } from "@/lib/api";
import { FIELD_KEYS, FIELD_LABEL, ERROR_HOME, applyTract, asRecord, blankForm, buildRecord, buildVariants, formFromStore, typicalChainSize, type FieldKey, type FormState, type Variant } from "@/lib/check";
import { useMeta, useScores, useStores, useTracts } from "@/lib/data";
import { TIER_LABEL, TIER_TEXT, TYPE_ORDER, TYPE_SHORT, displayName, fmtInt, fmtMi, fmtPct, fmtRate } from "@/lib/format";
import { SCORE_YEAR } from "@/lib/site";
import type { Prediction, StoreType } from "@/lib/types";

interface Result {
  record: Record<string, unknown>;
  pred: Prediction;
  variants: { label: string; pred: Prediction }[];
  form: FormState;
}

const inputCls = "h-11 w-full rounded-md border bg-paper-light px-3 aria-[invalid=true]:border-tomato";

function Section({ n, title, children, className }: { n: string; title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`border-t-2 border-ink pt-3 ${className ?? ""}`}>
      <h2 className="flex items-baseline gap-2 font-serif text-3xl">
        <span className="label-mono text-forest">{n}</span> {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ErrorText({ id, msg }: { id: string; msg?: string }) {
  return msg ? (
    <p id={id} role="alert" className="mt-1 text-sm text-tomato">
      {msg}
    </p>
  ) : null;
}

export function CheckForm() {
  const stores = useStores();
  const tracts = useTracts();
  const meta = useMeta();
  const scores = useScores();
  const urlStore = useSyncExternalStore(
    () => () => {},
    () => new URLSearchParams(location.search).get("store"),
    () => null,
  );

  const [form, setForm] = useState<FormState>(blankForm);
  const [seenUrl, setSeenUrl] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<Error | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle");
  const [slow, setSlow] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const run = useRef(0);

  const tractList = useMemo(() => (tracts.data?.features ?? []).map((f) => f.properties).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })), [tracts.data]);
  const tractById = useMemo(() => new Map(tractList.map((t) => [t.geoid, t])), [tractList]);
  const storeList = useMemo(() => [...(stores.data ?? [])].sort((a, b) => displayName(a.name).localeCompare(displayName(b.name))), [stores.data]);

  // "?store=<id>" (from a receipt) pre-fills the form once the data is in; adjusting state during render, not in an effect
  if (urlStore && urlStore !== seenUrl && stores.data && tracts.data) {
    setSeenUrl(urlStore);
    const st = stores.data.find((x) => x.record_id === urlStore);
    if (st) setForm(formFromStore(st, tractById.has(st.tract ?? "")));
  }

  const set = (k: FieldKey, value: string) => setForm((f) => ({ ...f, v: { ...f.v, [k]: value } }));
  const err = (key: string) => fieldErrors[key];
  const bind = (k: FieldKey) => ({
    id: `f-${k}`,
    value: form.v[k],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(k, e.target.value),
    "aria-invalid": !!err(k) || undefined,
    "aria-describedby": err(k) ? `e-${k}` : undefined,
    className: `${inputCls} ${err(k) ? "border-tomato" : "border-rule"}`,
    autoComplete: "off",
  });

  function pickStore(id: string) {
    const st = stores.data?.find((x) => x.record_id === id);
    setFieldErrors({});
    setForm(st ? formFromStore(st, tractById.has(st.tract ?? "")) : blankForm());
  }
  function pickTract(geoid: string) {
    setForm((f) => applyTract(f, tractById.get(geoid)));
  }
  function reset() {
    run.current++;
    setForm(blankForm());
    setFieldErrors({});
    setGeneralError(null);
    setApiError(null);
    setResult(null);
    setStatus("idle");
  }

  async function estimate(e: React.FormEvent) {
    e.preventDefault();
    const mine = ++run.current;
    setFieldErrors({});
    setGeneralError(null);
    setApiError(null);
    setStatus("loading");
    setSlow(false);
    const record = buildRecord(form);
    const variants: Variant[] = buildVariants(record, typicalChain);
    try {
      // one batched request: the entered store first, then the three "what if" variants
      const res = await predict([asRecord(record), ...variants.map((v) => asRecord(v.record))], { onSlow: () => mine === run.current && setSlow(true) });
      if (mine !== run.current) return;
      setResult({ record, pred: res[0], variants: variants.map((v, i) => ({ label: v.label, pred: res[i + 1] })), form });
      setStatus("done");
    } catch (error) {
      if (mine !== run.current) return;
      setStatus("idle");
      if (error instanceof ApiError && error.kind === "validation") {
        // errors about the entered store (index 0) go under their inputs; the variants are derived from it, so they add nothing
        const map: Record<string, string> = {};
        const own = error.fields.filter((x) => x.index === 0);
        const direct = new Set(own.map((x) => x.field));
        for (const fe of own) {
          // the ratio is worked out from the two counts: if either count already has its own error, that is the one to show
          if (fe.field === "convenience_to_grocery_ratio_1mi" && (direct.has("n_grocery_1mi") || direct.has("n_convenience_1mi"))) continue;
          const home = fe.field === "" ? "general" : (ERROR_HOME[fe.field] ?? fe.field);
          const label = FIELD_LABEL[fe.field as FieldKey]?.label;
          // a derived field (e.g. store_age_years) has no input of its own: name it in the message shown under the control that sets it
          map[home] ??= ERROR_HOME[fe.field] && label ? `${label}: ${fe.message}` : fe.message;
        }
        if (map.general) {
          setGeneralError(map.general);
          delete map.general;
        }
        setFieldErrors(map);
        if (!Object.keys(map).length) setGeneralError(error.fields[0]?.message ?? error.message);
        setResult(null);
      } else {
        setApiError(error instanceof Error ? error : new Error(String(error)));
      }
    }
  }

  const hiddenKeys = new Set<string>(["n_prior_spells_same_id", "n_prior_ownership_changes", ...FIELD_KEYS.filter((k) => ["acs_population", "pop_density_sqmi", "pct_poverty", "median_hh_income", "pct_no_vehicle", "pct_snap_hh", "pct_renter", "pct_age_65_plus", "unemployment_rate"].includes(k))]);
  const moreHasError = [...hiddenKeys].some((k) => fieldErrors[k]);
  // median chain size among the chain stores on the map: the reference for the "part of a typical chain" variant
  const typicalChain = typicalChainSize(stores.data);
  const typical = (t: string) => meta.data?.type_rates.by_type[t as StoreType]?.rate;
  const allProbs = useMemo(() => (scores.data ? [...scores.data.values()].map((p) => p.probability) : []), [scores.data]);
  const tractProps = result?.form.tract ? tractById.get(result.form.tract) : undefined;
  const startStore = result?.form.start ? stores.data?.find((x) => x.record_id === result.form.start) : undefined;
  const age = form.yearUnknown ? null : form.ageExact != null ? Number(form.ageExact) : form.firstYear.trim() ? SCORE_YEAR - Number(form.firstYear) : null;
  const ratio = (() => {
    const g = Number(form.v.n_grocery_1mi), c = Number(form.v.n_convenience_1mi);
    return form.v.n_grocery_1mi.trim() && form.v.n_convenience_1mi.trim() && Number.isFinite(g) && Number.isFinite(c) ? (c / (g + 1)).toFixed(2) : "";
  })();

  return (
    <div className="mx-auto max-w-[1440px] px-4 pb-4 pt-10 md:px-5">
      <h1 className="font-serif text-5xl md:text-7xl">Check a store</h1>
      <p className="mt-3 max-w-2xl text-lg text-ink-2">
        Enter a store’s details to estimate its risk as of Jan 1, 2024. Use it for a store that isn’t on the map, or to see how a change, like joining a chain, would shift the score.
      </p>

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_400px]">
        <form onSubmit={estimate} noValidate className="min-w-0 space-y-8" aria-label="Store details">
          {generalError && (
            <p role="alert" className="border border-tomato bg-paper-light px-4 py-3 text-tomato">
              {generalError}
            </p>
          )}

          <Section n="01" title="Location">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label htmlFor="start" className="label-mono text-ink-2">
                  Start from a store on the map (optional)
                </label>
                <select id="start" value={form.start} onChange={(e) => pickStore(e.target.value)} className={`${inputCls} mt-1 border-rule`} disabled={!stores.data}>
                  <option value="">— a store that isn’t listed —</option>
                  {storeList.map((s) => (
                    <option key={s.record_id} value={s.record_id}>
                      {displayName(s.name)} · {s.zip ?? "—"}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-sm text-ink-2">Fills in everything below from the store’s Jan 1, 2024 record. You can change any of it.</p>
              </div>
              <div>
                <label htmlFor="tract" className="label-mono text-ink-2">
                  Census tract
                </label>
                <select id="tract" value={form.tract} onChange={(e) => pickTract(e.target.value)} className={`${inputCls} mt-1 border-rule`} disabled={!tracts.data}>
                  <option value="">— choose a tract —</option>
                  {tractList.map((t) => (
                    <option key={t.geoid} value={t.geoid}>
                      {t.name}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-sm text-ink-2">Fills in the neighborhood figures (income, cars, SNAP, rent, age, unemployment) from the Census ACS 2018–2022. Not sure which tract? Find the store on the map first.</p>
              </div>
            </div>
            {form.tract && tractById.get(form.tract) && (
              <p className="mt-3 flex items-center gap-2 bg-lowers px-3 py-2 text-sm">
                <Check className="size-4 shrink-0 text-forest" aria-hidden />
                <span>
                  {tractById.get(form.tract)!.name}, Mecklenburg County. {fmtInt(tractById.get(form.tract)!.snap_households)} households on SNAP and {fmtInt(tractById.get(form.tract)!.no_car_households)} without a car.
                </span>
              </p>
            )}
            <div className="mt-4 max-w-xs">
              <label htmlFor="f-dist_other_grocery_jan1_mi" className="label-mono text-ink-2">
                Miles to the next SNAP grocery
              </label>
              <input {...bind("dist_other_grocery_jan1_mi")} inputMode="decimal" placeholder="e.g. 0.45" />
              <ErrorText id="e-dist_other_grocery_jan1_mi" msg={err("dist_other_grocery_jan1_mi")} />
              <p className="mt-1 text-sm text-ink-2">Straight line to the nearest other SNAP grocery. Leave empty if you don’t know.</p>
            </div>
          </Section>

          <Section n="02" title="Store type">
            <p className="text-ink-2">
              USDA’s category for the store. The figure is how often NC stores of that type stopped accepting SNAP within a year, {meta.data ? `${meta.data.type_rates.years[0]}–${meta.data.type_rates.years[1]}` : "2012–2021"}.
            </p>
            <div role="radiogroup" aria-label="Store type" className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {TYPE_ORDER.map((t) => {
                const on = form.v.store_type === t;
                return (
                  <label key={t} className={`cursor-pointer border px-3 py-2 text-center has-[:focus-visible]:outline-2 ${on ? "border-ink bg-paper-light" : "border-rule hover:bg-paper-light"}`}>
                    <input type="radio" name="store_type" value={t} checked={on} onChange={() => set("store_type", t)} className="sr-only" />
                    <span className="block font-medium">{TYPE_SHORT[t]}</span>
                    <span className={`label-mono block ${on ? "text-tomato" : "text-ink-2"}`}>{typical(t) != null ? `${fmtRate(typical(t)!)} / yr` : "—"}</span>
                  </label>
                );
              })}
            </div>
            <ErrorText id="e-store_type" msg={err("store_type")} />
          </Section>

          <div className="grid gap-8 md:grid-cols-2">
            <Section n="03" title="Ownership">
              <div role="radiogroup" aria-label="Ownership" className="flex">
                {(
                  [
                    [false, "Independent"],
                    [true, "Part of a chain"],
                  ] as const
                ).map(([val, label]) => (
                  <label key={label} className={`min-h-11 cursor-pointer border border-rule px-4 py-2.5 first:rounded-l-md last:rounded-r-md has-[:focus-visible]:outline-2 ${form.chain === val ? "bg-forest text-paper-light" : "bg-paper-light"}`}>
                    <input type="radio" name="ownership" checked={form.chain === val} onChange={() => setForm((f) => ({ ...f, chainAssumed: false, chain: val, v: { ...f.v, chain_size: val && !f.v.chain_size ? "10" : f.v.chain_size } }))} className="sr-only" />
                    {label}
                  </label>
                ))}
              </div>
              {form.chainAssumed && !form.chain && (
                <p className="mt-2 text-sm text-mustard-text" role="note">
                  Assumed independent: chain size is missing in the USDA data for this store. Choose an option above if you know.
                </p>
              )}
              {form.chain && (
                <div className="mt-3 max-w-xs">
                  <label htmlFor="f-chain_size" className="label-mono text-ink-2">
                    Stores in the chain in North Carolina
                  </label>
                  <input {...bind("chain_size")} inputMode="numeric" placeholder="e.g. 12" />
                  <ErrorText id="e-chain_size" msg={err("chain_size")} />
                </div>
              )}
            </Section>
            <Section n="04" title="Time accepting SNAP">
              <label htmlFor="firstYear" className="label-mono text-ink-2">
                First year authorized
              </label>
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <input
                  id="firstYear"
                  value={form.firstYear}
                  onChange={(e) => setForm((f) => ({ ...f, firstYear: e.target.value, ageExact: null }))}
                  inputMode="numeric"
                  placeholder="e.g. 2015"
                  disabled={form.yearUnknown}
                  aria-invalid={!!err("firstYear") || undefined}
                  aria-describedby={err("firstYear") ? "e-firstYear" : undefined}
                  className={`${inputCls} w-36 ${err("firstYear") ? "border-tomato" : "border-rule"}`}
                  autoComplete="off"
                />
                <span className="text-ink-2">{age != null && Number.isFinite(age) ? `${age < 1 ? age.toFixed(1) : Math.round(age * 10) / 10} years as of Jan 1, 2024` : ""}</span>
              </div>
              <ErrorText id="e-firstYear" msg={err("firstYear")} />
              <label className="mt-3 flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.yearUnknown} onChange={(e) => setForm((f) => ({ ...f, yearUnknown: e.target.checked }))} className="size-4 accent-[var(--forest)]" />
                Start year not known (before 2005, or not recorded)
              </label>
            </Section>
          </div>

          <Section n="05" title="Nearby SNAP stores">
            <p className="text-ink-2">Counts of <em>other</em> SNAP-authorized stores around the location on Jan 1, 2024.</p>
            <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {(
                [
                  ["n_grocery_05mi", "Groceries within 0.5 mile"],
                  ["n_grocery_1mi", "Groceries within 1 mile"],
                  ["n_convenience_1mi", "Convenience stores within 1 mile"],
                  ["n_grocery_ends_1mi_prior12m", "Grocery exits within 1 mile in 2023"],
                ] as const
              ).map(([k, label]) => (
                <div key={k}>
                  <label htmlFor={`f-${k}`} className="label-mono text-ink-2">
                    {label}
                  </label>
                  <input {...bind(k)} inputMode="numeric" />
                  <ErrorText id={`e-${k}`} msg={err(k)} />
                </div>
              ))}
            </div>
          </Section>

          <details key={moreHasError ? "open" : "closed"} open={moreHasError || undefined} className="border-t-2 border-ink pt-3">
            <summary className="cursor-pointer font-serif text-2xl">
              <span className="label-mono mr-2 text-forest">06</span>All inputs
            </summary>
            <p className="mt-2 text-ink-2">Every number the model uses, as sent to the scoring service. The tract figures fill in when you pick a tract or a store.</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {FIELD_KEYS.filter((k) => hiddenKeys.has(k)).map((k) => (
                <div key={k}>
                  <label htmlFor={`f-${k}`} className="label-mono text-ink-2">
                    {FIELD_LABEL[k].label}
                  </label>
                  <input {...bind(k)} inputMode="decimal" />
                  <p className="mt-0.5 text-xs text-ink-2">{FIELD_LABEL[k].hint}</p>
                  <ErrorText id={`e-${k}`} msg={err(k)} />
                </div>
              ))}
              <div>
                <label htmlFor="f-ratio" className="label-mono text-ink-2">
                  {FIELD_LABEL.convenience_to_grocery_ratio_1mi.label}
                </label>
                <input id="f-ratio" value={ratio} readOnly className={`${inputCls} border-rule bg-paper`} />
                <p className="mt-0.5 text-xs text-ink-2">{FIELD_LABEL.convenience_to_grocery_ratio_1mi.hint}</p>
              </div>
            </div>
          </details>

          <div className="flex flex-wrap gap-3">
            <button type="submit" disabled={status === "loading"} className="min-h-11 rounded-md bg-forest px-5 font-medium text-paper-light hover:bg-forest-dark disabled:opacity-60">
              {status === "loading" ? "Estimating…" : "Estimate risk"}
            </button>
            <button type="button" onClick={reset} className="min-h-11 rounded-md border border-ink bg-paper-light px-5 hover:bg-paper">
              Reset
            </button>
          </div>
        </form>

        <aside aria-label="Risk estimate" aria-live="polite" className="min-w-0">
          {slow && status === "loading" && <div className="mb-4"><WakingNotice /></div>}
          {apiError && (
            <div className="mb-4">
              <ApiErrorBanner error={apiError} onRetry={() => estimate({ preventDefault() {} } as React.FormEvent)} retrying={status === "loading"} />
            </div>
          )}

          {status === "loading" && !result && (
            <div className="space-y-3 border border-rule bg-paper-light p-5" aria-busy="true">
              <Skeleton className="mx-auto h-3 w-40" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="ml-auto h-12 w-24" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}

          {!result && status !== "loading" && (
            <div className="border border-dashed border-rule bg-paper-light p-5 text-ink-2">
              <p className="label-mono">Risk estimate</p>
              <p className="mt-2">Fill in the form and press <strong>Estimate risk</strong>. The estimate, how it would shift under a few changes, and the exact request sent to the scoring service appear here.</p>
            </div>
          )}

          {result && (
            <div className={status === "loading" ? "opacity-60" : ""}>
              <article className="relative border border-rule bg-paper-light px-5 pb-8 pt-5" aria-label="Risk estimate">
                <header className="text-center">
                  <p className="label-mono font-medium">Grocery Watch · Charlotte</p>
                  <p className="label-mono mt-1 text-ink-2">Risk estimate · {startStore ? "adjusted store" : "entered store"}</p>
                </header>
                <hr className="my-4 border-dashed border-rule" />
                <h2 className="font-mono text-[0.9375rem] font-medium uppercase leading-snug">{startStore ? displayName(startStore.name) : "Entered store"}</h2>
                <p className="label-mono mt-1 text-ink-2">{tractProps ? `${tractProps.name}, Mecklenburg Co.` : "No census tract chosen"}</p>
                <p className="label-mono text-ink-2">
                  {TYPE_SHORT[result.record.store_type as StoreType] ?? String(result.record.store_type)} · {Number(result.record.chain_size) > 1 ? `chain of ${result.record.chain_size}` : result.form.chainAssumed ? "independent (assumed: chain size missing)" : "independent"}
                </p>
                <hr className="my-4 border-dashed border-rule" />
                <p className="label-mono">12-month exit risk</p>
                <div className="flex items-end justify-between gap-3 pt-1">
                  <p className="max-w-[9rem] font-mono text-xs leading-snug text-ink-2">Chance a store like this stops accepting SNAP</p>
                  <p className={`font-number text-6xl font-semibold leading-none ${TIER_TEXT[result.pred.tier]}`}>{fmtPct(result.pred.probability)}</p>
                </div>
                <div className="mt-3 space-y-1 font-mono text-sm">
                  {typical(String(result.record.store_type)) != null && (
                    <div className="flex justify-between gap-2">
                      <span className="label-mono">Typical {TYPE_SHORT[result.record.store_type as StoreType]?.toLowerCase()}</span>
                      <span>{fmtRate(typical(String(result.record.store_type))!)}</span>
                    </div>
                  )}
                  {allProbs.length > 0 && (
                    <div className="flex justify-between gap-2">
                      <span className="label-mono">Riskier than</span>
                      <span>{Math.min(99, Math.floor((allProbs.filter((p) => p < result.pred.probability).length / allProbs.length) * 100))}% of Mecklenburg stores</span>
                    </div>
                  )}
                </div>

                <hr className="my-4 border-dashed border-rule" />
                <p className="label-mono">How the score shifts if…</p>
                <ul className="mt-2 space-y-1.5">
                  {result.variants.map((v) => {
                    const d = (v.pred.probability - result.pred.probability) * 100;
                    return (
                      <li key={v.label} className="flex items-baseline justify-between gap-3 text-sm">
                        <span>{v.label}</span>
                        <span className="shrink-0 font-mono tabular-nums">
                          {fmtPct(v.pred.probability)}{" "}
                          <span className={Math.abs(d) < 0.05 ? "text-ink-2" : d > 0 ? "text-tomato" : "text-forest"}>
                            ({d > 0 ? "+" : d < 0 ? "−" : "±"}
                            {Math.abs(d).toFixed(1)} pts)
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <p className="mt-2 text-xs text-ink-2">These are patterns in the data, not causes: they do not say that changing one thing would change a real store’s chances.</p>

                <hr className="my-4 border-dashed border-rule" />
                <p className="label-mono">Who relies on a store here</p>
                <div className="mt-2 space-y-1 font-mono text-sm">
                  <div className="flex justify-between gap-2">
                    <span className="label-mono">Next SNAP grocery</span>
                    <span>{fmtMi(typeof result.record.dist_other_grocery_jan1_mi === "number" ? result.record.dist_other_grocery_jan1_mi : null)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="label-mono">SNAP households in tract</span>
                    <span>{tractProps ? fmtInt(tractProps.snap_households) : "—"}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="label-mono">No-car households in tract</span>
                    <span>{tractProps ? fmtInt(tractProps.no_car_households) : "—"}</span>
                  </div>
                </div>

                <div className={`mx-auto mt-5 w-fit -rotate-3 border-2 px-3 py-1 font-mono text-sm font-medium uppercase tracking-[0.2em] ${result.pred.tier === "high" ? "border-tomato text-tomato" : result.pred.tier === "medium" ? "border-mustard-text text-mustard-text" : "border-ink-2 text-ink-2"}`}>
                  {TIER_LABEL[result.pred.tier]} risk
                </div>
                <Barcode value="2024" className="mx-auto mt-4 h-8 w-32" />
                <p className="label-mono mt-3 text-center text-[0.625rem] text-ink-2">Statistical estimate · not a forecast</p>
                <div aria-hidden className="absolute inset-x-0 -bottom-2 h-2 bg-[linear-gradient(135deg,var(--paper-light)_25%,transparent_25%),linear-gradient(225deg,var(--paper-light)_25%,transparent_25%)] bg-[length:10px_10px]" />
              </article>

              {result.pred.reasons.length > 0 && (
                <section className="mt-6" aria-labelledby="why-check">
                  <h3 id="why-check" className="border-b-2 border-ink pb-1 font-serif text-2xl">
                    What’s behind this score
                  </h3>
                  <ul>
                    {result.pred.reasons.map((r) => {
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
                </section>
              )}

              <details className="mt-6 bg-ink text-paper-light">
                <summary className="label-mono cursor-pointer px-4 py-3">Developer view · POST /predict → 200</summary>
                <div className="space-y-3 px-4 pb-4">
                  <div>
                    <p className="label-mono text-paper-rule">Request (first of 4 records)</p>
                    <pre className="mt-1 max-h-64 overflow-auto text-xs leading-relaxed">{JSON.stringify(result.record, null, 2)}</pre>
                  </div>
                  <div>
                    <p className="label-mono text-paper-rule">Response (first of 4 predictions)</p>
                    <pre className="mt-1 max-h-64 overflow-auto text-xs leading-relaxed">{JSON.stringify(result.pred, null, 2)}</pre>
                  </div>
                </div>
              </details>
            </div>
          )}

          <p className="mt-6 font-serif text-lg italic text-ink-2">
            Estimates come from the same model as the map. They describe stores like this one on average, not a particular owner’s plans.{" "}
            <Link href="/how-it-works" className="text-forest underline underline-offset-2">
              How scores work
            </Link>
          </p>
        </aside>
      </div>
    </div>
  );
}
