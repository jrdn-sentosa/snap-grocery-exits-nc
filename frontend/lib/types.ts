/** Shapes of the API (app/api.py, docs/model_spec_d4.md) and of the exported site data (public/data, written by src/site/01_export_site_data.py). */

export type Tier = "low" | "medium" | "high";
export type StoreType = "Supermarket" | "Super Store" | "Large Grocery Store" | "Medium Grocery Store" | "Small Grocery Store";

/** One POST /predict record: `year`, the 20 model inputs and `dist_other_grocery_jan1_mi`. All 22 keys are required (null only where allowed). */
export interface PredictRecord {
  year: number;
  store_type: StoreType;
  store_age_years: number | null;
  auth_date_placeholder: 0 | 1;
  n_prior_spells_same_id: number;
  n_prior_ownership_changes: number;
  chain_size: number;
  n_grocery_05mi: number;
  n_grocery_1mi: number;
  n_convenience_1mi: number;
  convenience_to_grocery_ratio_1mi: number;
  n_grocery_ends_1mi_prior12m: number;
  acs_population: number | null;
  pop_density_sqmi: number | null;
  pct_poverty: number | null;
  median_hh_income: number | null;
  pct_no_vehicle: number | null;
  pct_snap_hh: number | null;
  pct_renter: number | null;
  pct_age_65_plus: number | null;
  unemployment_rate: number | null;
  dist_other_grocery_jan1_mi: number | null;
}

export interface Reason {
  feature: string;
  text: string;
  /** centred log-odds contribution: positive raises the risk */
  effect: number;
}

export interface Prediction {
  row: number;
  raw_score: number;
  probability: number;
  tier: Tier;
  /** access impact in (0, 1] */
  impact: number;
  /** probability x impact */
  priority: number;
  reasons: Reason[];
}

export interface ModelInfo {
  metadata: {
    tier_cutoffs: { low: number; high: number; base_rate_2012_2018?: number };
    training_years?: [number, number] | number[];
    created?: string;
    [key: string]: unknown;
  };
  self_check_passed: boolean;
  limits: string[];
}

// ---- exported site data -------------------------------------------------------------------------------------------------------------

export interface Alternative {
  record_id: string;
  name: string;
  store_type: StoreType;
  distance_mi: number;
  county: string;
}

export interface Store {
  record_id: string;
  name: string;
  store_type: StoreType;
  address: string | null;
  city: string | null;
  zip: string | null;
  lat: number | null;
  lon: number | null;
  tract: string | null;
  since_year: number | null;
  chain_size: number | null;
  independent: boolean | null;
  scorable: boolean;
  unscorable_reason: string | null;
  inputs: PredictRecord;
  context: {
    dist_next_grocery_mi: number | null;
    tract_snap_households: number | null;
    tract_snap_share: number | null;
    tract_no_car_households: number | null;
    tract_no_car_share: number | null;
    tract_households: number | null;
  };
  alternatives: Alternative[];
}

export interface StoresFile {
  score_year: number;
  scored_on: string;
  stores: Store[];
}

export type ShadeStatus = "ok" | "low_data" | "none";

export interface TractProps {
  geoid: string;
  name: string;
  store_years_0821: number;
  exit_share_0821: number | null;
  shade_status: ShadeStatus;
  population: number | null;
  households: number | null;
  snap_households: number | null;
  snap_share: number | null;
  no_car_households: number | null;
  no_car_share: number | null;
  median_hh_income: number | null;
  /** the nine tract-level API inputs (ACS 2018-2022), for the Check page tract picker */
  inputs: Record<"acs_population" | "pop_density_sqmi" | "pct_poverty" | "median_hh_income" | "pct_no_vehicle" | "pct_snap_hh" | "pct_renter" | "pct_age_65_plus" | "unemployment_rate", number | null>;
}

export interface TractsFile {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: TractProps; geometry: GeoJSON.Geometry }[];
}

interface Share {
  n: number;
  share: number;
}
export interface PieCounts {
  ended: number;
  other_exit: Share;
  batch: Share;
  ownership_change: Share;
}

export interface Meta {
  score_year: number;
  scored_on: string;
  acs: { vintage: string; release_date: string; tract_geography: string };
  counts: { stores_2024_statewide: number; stores_2024_mecklenburg: number; stores_scorable: number; tracts: number };
  type_rates: {
    years: [number, number];
    scope: string;
    by_type: Record<StoreType, { store_years: number; exits: number; rate: number }>;
    overall: { store_years: number; exits: number; rate: number };
  };
  pie: { through: string; statewide: PieCounts; mecklenburg: PieCounts };
  past_exit_gap: { years: [number, number]; gap_distance_mi: number; exits: number; with_distance: number; gap_exits: number; share: number };
  shading: { years: [number, number]; min_store_years: number; label: string };
}
