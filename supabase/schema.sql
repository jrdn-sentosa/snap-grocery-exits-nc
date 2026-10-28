-- ============================================================================
-- SNAP grocery exits (NC): Supabase schema
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
-- Safe to re-run: tables are created only if missing; policies are recreated.
--
-- Data through 2021-12-31 only. The reserved test cohorts (2022-2024) are never loaded, and the CHECK
-- constraints below make the database refuse them even if a loader is changed by mistake.
-- Writes come only from src/prep/06_load_supabase.py with the service-role key (which bypasses RLS);
-- the dashboard uses the publishable/anon key, which can only SELECT.
-- Column definitions: docs/data_dictionary.md. The loader's --dry-run checks these column lists
-- against the data frames, so keep them in sync.
-- ============================================================================

-- store_year: one row per grocery-type Record ID authorized on Jan 1 of year t (train 2008-2018, validation 2019-2021)
create table if not exists store_year (
  -- id
  record_id bigint not null,
  spell_id text,
  year smallint not null check (year between 2008 and 2021),
  split text not null check (split in ('train', 'validation')),
  -- features (known on Jan 1 of t)
  store_type text not null,
  store_age_years double precision,
  auth_date_placeholder boolean,
  n_prior_spells_same_id integer,
  n_prior_ownership_changes integer,
  chain_size integer,
  n_grocery_05mi integer,
  n_grocery_1mi integer,
  n_convenience_1mi integer,
  convenience_to_grocery_ratio_1mi double precision,
  n_grocery_ends_1mi_prior12m integer,
  acs_population double precision,
  pop_density_sqmi double precision,
  pct_poverty double precision,
  median_hh_income double precision,
  pct_no_vehicle double precision,
  pct_snap_hh double precision,
  pct_renter double precision,
  pct_age_65_plus double precision,
  unemployment_rate double precision,
  -- bias_ (group error analysis only, never a feature)
  bias_pct_hispanic double precision,
  bias_pct_white_nh double precision,
  bias_pct_black_nh double precision,
  bias_pct_asian_nh double precision,
  bias_pct_aian_nh double precision,
  bias_pct_other_multi_nh double precision,
  -- grouping (never features)
  acs_available boolean,
  acs_vintage text,
  acs_release_date date,
  acs_tract_vintage text,
  store_name text,
  county text,
  latitude double precision,
  longitude double precision,
  tract_geoid_2010 text,
  tract_geoid_2020 text,
  ruca_primary smallint,
  ruca_group text,
  ruca_vintage smallint,
  ruca_release_date date,
  -- labels
  exit_12m smallint not null check (exit_12m in (0, 1)),
  exit_12m_strict smallint check (exit_12m_strict in (0, 1)),   -- null = batch-end exit, excluded from strict analyses
  exit_is_batch boolean,                                        -- exits only
  -- impact_ / qa_ (outcome-side, never features)
  impact_dist_nearest_other_grocery_mi double precision,
  qa_coord_invalid boolean,
  qa_tract_unmatched boolean,
  qa_ownership_change_in_year boolean,
  qa_spell_end date,
  primary key (record_id, year)
);

-- snap_retailers_nc: every NC SNAP retailer of every store type, one row per authorization period.
-- End dates after 2021-12-31 are loaded as NULL ("still authorized as of the data cut-off") so the dashboard
-- cannot show test-period exits; the qa_ flags derived from an end date are cleared for those rows,
-- and authorizations that began after 2021-12-31 are not loaded.
create table if not exists snap_retailers_nc (
  record_id bigint not null,
  period_seq smallint not null,
  store_name text,
  name_std text,
  store_type text not null,
  is_grocery boolean,
  is_convenience boolean,
  street_number text,
  street_name text,
  additional_address text,
  address_std text,
  address_key text,
  city text,
  city_raw text,
  zip5 text,
  zip4 text,
  county text,
  latitude double precision,
  longitude double precision,
  auth_date date check (auth_date is null or auth_date <= date '2021-12-31'),
  auth_date_placeholder boolean,
  end_date date check (end_date is null or end_date <= date '2021-12-31'),
  qa_batch_end boolean,
  qa_coord_invalid boolean,
  qa_name_malformed boolean,
  qa_zero_length_period boolean,
  qa_end_before_auth boolean,
  primary key (record_id, period_seq)
);

-- cleaning_log: every cleaning rule with row counts before/after (the data note's cleaning table)
create table if not exists cleaning_log (
  script text not null,
  seq integer not null,
  step text not null,
  step_type text check (step_type in ('filter', 'transform', 'flag', 'audit', 'build')),   -- rows_before / rows_after are null for audit and build steps
  rule text,
  why text,
  rows_before bigint,
  rows_after bigint,
  rows_affected bigint,
  primary key (script, seq)
);
-- a table created before step_type existed gets the column here (safe to re-run)
alter table cleaning_log add column if not exists step_type text;

-- data_meta: key/value facts the dashboard shows on every page (data_through, cohort years, ...)
create table if not exists data_meta (
  key text primary key,
  value text not null
);

-- location_gap: one row per grocery-type record that ENDED between 2008-01-01 and 2021-12-31, with the days its location (address) went
-- without any SNAP authorization under any Record ID until the next one started. A location whose next authorization came after
-- 2021-12-31 is 'not re-authorized by 2021-12-31', so no post-cut-off fact is stored. Built by src/prep/05b_location_gaps.py.
create table if not exists location_gap (
  spell_id text primary key,
  record_id bigint not null,
  store_name text,
  store_type text not null,
  county text,
  end_date date not null check (end_date <= date '2021-12-31'),
  end_year smallint not null check (end_year between 2008 and 2021),
  split text not null check (split in ('train', 'validation')),
  is_batch boolean,
  end_kind text check (end_kind in ('exit', 'ownership change')),
  gap_days integer check (gap_days is null or gap_days >= 0),
  gap_class text not null check (gap_class in ('0 days', '1-90 days', '91-365 days', 'more than 365 days', 'not re-authorized by 2021-12-31')),
  reauth_same_id boolean
);

-- indexes for the dashboard's filters
create index if not exists idx_location_gap_county_type on location_gap (county, store_type);
create index if not exists idx_store_year_year_type on store_year (year, store_type);
create index if not exists idx_store_year_county on store_year (county);
create index if not exists idx_snap_retailers_end_date on snap_retailers_nc (end_date);

-- Row Level Security: public (anon key) can read; nobody but the service role can write.
alter table store_year enable row level security;
alter table snap_retailers_nc enable row level security;
alter table cleaning_log enable row level security;
alter table data_meta enable row level security;
alter table location_gap enable row level security;

drop policy if exists "Allow public read access" on location_gap;
create policy "Allow public read access" on location_gap for select using (true);

drop policy if exists "Allow public read access" on store_year;
drop policy if exists "Allow public read access" on snap_retailers_nc;
drop policy if exists "Allow public read access" on cleaning_log;
drop policy if exists "Allow public read access" on data_meta;
create policy "Allow public read access" on store_year for select using (true);
create policy "Allow public read access" on snap_retailers_nc for select using (true);
create policy "Allow public read access" on cleaning_log for select using (true);
create policy "Allow public read access" on data_meta for select using (true);

grant select on store_year, snap_retailers_nc, cleaning_log, data_meta, location_gap to anon, authenticated;
