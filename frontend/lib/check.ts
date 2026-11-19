import { SCORE_YEAR } from "./site";
import type { PredictRecord, Store, StoreType, TractProps } from "./types";

/** The 21 model inputs a visitor can set (the 22nd API key, `year`, is fixed to the score year). */
export const FIELD_KEYS = [
  "store_type", "store_age_years", "auth_date_placeholder", "n_prior_spells_same_id", "n_prior_ownership_changes", "chain_size",
  "n_grocery_05mi", "n_grocery_1mi", "n_convenience_1mi", "convenience_to_grocery_ratio_1mi", "n_grocery_ends_1mi_prior12m",
  "acs_population", "pop_density_sqmi", "pct_poverty", "median_hh_income", "pct_no_vehicle", "pct_snap_hh", "pct_renter", "pct_age_65_plus",
  "unemployment_rate", "dist_other_grocery_jan1_mi",
] as const;
export type FieldKey = (typeof FIELD_KEYS)[number];

export const TRACT_KEYS: FieldKey[] = ["acs_population", "pop_density_sqmi", "pct_poverty", "median_hh_income", "pct_no_vehicle", "pct_snap_hh", "pct_renter", "pct_age_65_plus", "unemployment_rate"];

/** Plain-language label and hint for each input, shown in the "all inputs" list and in error messages. */
export const FIELD_LABEL: Record<FieldKey, { label: string; hint?: string }> = {
  store_type: { label: "Store type" },
  store_age_years: { label: "Years accepting SNAP", hint: "as of Jan 1, 2024" },
  auth_date_placeholder: { label: "Start year unknown" },
  n_prior_spells_same_id: { label: "Earlier SNAP authorizations of this store", hint: "whole number" },
  n_prior_ownership_changes: { label: "Earlier ownership changes", hint: "whole number" },
  chain_size: { label: "Stores in the chain in North Carolina", hint: "1 = independent" },
  n_grocery_05mi: { label: "Other SNAP groceries within 0.5 mile", hint: "whole number" },
  n_grocery_1mi: { label: "Other SNAP groceries within 1 mile", hint: "whole number" },
  n_convenience_1mi: { label: "SNAP convenience stores within 1 mile", hint: "whole number" },
  convenience_to_grocery_ratio_1mi: { label: "Convenience-to-grocery ratio", hint: "worked out from the two counts" },
  n_grocery_ends_1mi_prior12m: { label: "SNAP grocery exits within 1 mile in 2023", hint: "whole number" },
  acs_population: { label: "Tract population", hint: "people" },
  pop_density_sqmi: { label: "Tract population density", hint: "people per square mile" },
  pct_poverty: { label: "Tract poverty rate", hint: "0 to 1, e.g. 0.18" },
  median_hh_income: { label: "Tract median household income", hint: "dollars" },
  pct_no_vehicle: { label: "Tract households without a car", hint: "0 to 1" },
  pct_snap_hh: { label: "Tract households on SNAP", hint: "0 to 1" },
  pct_renter: { label: "Tract households that rent", hint: "0 to 1" },
  pct_age_65_plus: { label: "Tract residents aged 65 or older", hint: "0 to 1" },
  unemployment_rate: { label: "Tract unemployment rate", hint: "0 to 1" },
  dist_other_grocery_jan1_mi: { label: "Miles to the next SNAP grocery", hint: "straight line" },
};

/** Fields that have no input of their own on the form: an API error about them is shown under the control that sets them. */
export const ERROR_HOME: Partial<Record<string, string>> = {
  store_age_years: "firstYear",
  auth_date_placeholder: "firstYear",
  convenience_to_grocery_ratio_1mi: "n_convenience_1mi",
  year: "general",
};

export interface FormState {
  /** Record ID of the store the form was filled from, or "" */
  start: string;
  /** census tract GEOID, or "" */
  tract: string;
  v: Record<FieldKey, string>;
  chain: boolean;
  firstYear: string;
  yearUnknown: boolean;
  /** exact age taken from a starting store; cleared as soon as the visitor edits the year */
  ageExact: string | null;
  /** the starting store has no chain size in the USDA data, so "independent" is an assumption; cleared when the visitor sets ownership */
  chainAssumed: boolean;
}

const s = (n: number | string | null | undefined) => (n == null ? "" : String(n));

export function blankForm(): FormState {
  const v = Object.fromEntries(FIELD_KEYS.map((k) => [k, ""])) as Record<FieldKey, string>;
  v.store_type = "Small Grocery Store";
  v.chain_size = "";
  for (const k of ["n_prior_spells_same_id", "n_prior_ownership_changes", "n_grocery_05mi", "n_grocery_1mi", "n_convenience_1mi", "n_grocery_ends_1mi_prior12m"] as const) v[k] = "0";
  return { start: "", tract: "", v, chain: false, firstYear: "", yearUnknown: false, ageExact: null, chainAssumed: false };
}

export function formFromStore(store: Store, tractKnown: boolean): FormState {
  const f = blankForm();
  for (const k of FIELD_KEYS) f.v[k] = s(store.inputs[k] as number | string | null);
  f.start = store.record_id;
  f.tract = tractKnown && store.tract ? store.tract : "";
  f.chain = (store.chain_size ?? 1) > 1;
  f.chainAssumed = store.inputs.chain_size == null;
  f.firstYear = s(store.since_year);
  f.yearUnknown = store.inputs.auth_date_placeholder === 1;
  f.ageExact = store.inputs.store_age_years == null ? null : String(store.inputs.store_age_years);
  // the distance only feeds the impact score (not the probability), so a readable 4-decimal value is safe to show
  if (store.inputs.dist_other_grocery_jan1_mi != null) f.v.dist_other_grocery_jan1_mi = String(Math.round(store.inputs.dist_other_grocery_jan1_mi * 10000) / 10000);
  return f;
}

export function applyTract(f: FormState, t: TractProps | undefined): FormState {
  const v = { ...f.v };
  for (const k of TRACT_KEYS) v[k] = t ? s(t.inputs[k as keyof TractProps["inputs"]]) : "";
  return { ...f, tract: t?.geoid ?? "", v };
}

/** Text to a JSON value: "" is null, a number is a number, anything else is passed on untouched so the API can refuse it and name the field. */
function parse(text: string): number | string | null {
  const t = text.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : t;
}

/** The 22-key request record. Not validated here on purpose: the API is the one rulebook and answers 422 with the field. */
export function buildRecord(f: FormState): Record<string, unknown> {
  const rec: Record<string, unknown> = { year: SCORE_YEAR };
  for (const k of FIELD_KEYS) rec[k] = k === "store_type" ? f.v.store_type : parse(f.v[k]);
  rec.auth_date_placeholder = f.yearUnknown ? 1 : 0;
  if (f.yearUnknown) rec.store_age_years = null;
  else if (f.ageExact != null) rec.store_age_years = parse(f.ageExact);
  else {
    const y = parse(f.firstYear);
    rec.store_age_years = typeof y === "number" ? SCORE_YEAR - y : y;
  }
  rec.chain_size = f.chain ? parse(f.v.chain_size) : 1;
  const g = parse(f.v.n_grocery_1mi);
  const c = parse(f.v.n_convenience_1mi);
  // same definition as src/prep/05_features.py: convenience stores / (groceries + 1), the +1 being the store itself
  rec.convenience_to_grocery_ratio_1mi = typeof g === "number" && typeof c === "number" ? c / (g + 1) : null;
  return rec;
}

export interface Variant {
  label: string;
  record: Record<string, unknown>;
}

const TYPE_LABEL: Record<StoreType, string> = {
  Supermarket: "a supermarket",
  "Super Store": "a super store",
  "Large Grocery Store": "a large grocery",
  "Medium Grocery Store": "a medium grocery",
  "Small Grocery Store": "a small grocery",
};

/** "How the score shifts if…": three single changes to the entered store, scored in the same batched request. Associations, not causes. */
export function buildVariants(rec: Record<string, unknown>, typicalChain: number): Variant[] {
  const out: Variant[] = [];
  const chain = typeof rec.chain_size === "number" ? rec.chain_size : 1;
  // "typical chain" = the median chain size among the chain stores on the map (the model only reacts to large chains, so a made-up small number would show no change)
  out.push(
    chain > 1
      ? { label: "it were independent", record: { ...rec, chain_size: 1 } }
      : { label: `it were part of a typical chain (${typicalChain} stores)`, record: { ...rec, chain_size: typicalChain } },
  );
  const age = typeof rec.store_age_years === "number" ? rec.store_age_years : null;
  out.push(
    age != null && age >= 10
      ? { label: "it had been on SNAP for only 2 years", record: { ...rec, store_age_years: 2, auth_date_placeholder: 0 } }
      : { label: "it had been on SNAP for 10 years", record: { ...rec, store_age_years: 10, auth_date_placeholder: 0 } },
  );
  const type = rec.store_type === "Medium Grocery Store" ? "Small Grocery Store" : "Medium Grocery Store";
  out.push({ label: `it were ${TYPE_LABEL[type]}`, record: { ...rec, store_type: type } });
  return out;
}

/** The request as the page sends it, typed for lib/api. */
export const asRecord = (r: Record<string, unknown>) => r as unknown as PredictRecord;

/** Median chain size among the chain stores (more than one store) in the data; 100 if the data has not loaded. */
export function typicalChainSize(stores: Store[] | undefined): number {
  const sizes = (stores ?? []).map((x) => x.chain_size ?? 1).filter((n) => n > 1);
  if (!sizes.length) return 100;
  const sorted = [...sizes].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}
