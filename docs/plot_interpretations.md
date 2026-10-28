# Plot interpretations

Figures are made by `src/eda/plots.py` from **train and validation rows only** (cohort years 2008-2021; end dates through
2021-12-31). The numbers behind every chart are in `figures/data/*.csv`. `exit_12m` counts all true exits, batch ends included,
under the current ownership-change rule of `03_spells.py` (`docs/label_rule_change.md`); `exit_12m_strict` leaves batch-end exits out of
the sample. The text below is written by hand from the figures as generated (after the revised rule of 2026-10-28); re-read it if the
data or the code changes.

## (a) Annual exit rate, both labels, with batch days marked
![a](../figures/a_yearly_exit_rate.png)

The all-exits rate sits near 2.8-3.1% in 2008-2011, falls to 1.9% in 2012, then jumps to 4.5% in 2013 and peaks at 6.0% in 2014
(130 exits). Batch ends are 60% of exits in 2013 and 72% in 2014, which is why the strict rate is much flatter (1.2% in 2012,
1.9% in 2013, 1.8% in 2014); the one year the two labels nearly meet is 2020, when only one batch day occurred and the strict rate
peaks at 3.2%. The year-to-year swings track USDA administrative clean-ups as much as store behaviour, which is why calendar year
is not allowed as a feature and why every result should be reported under both labels.

## (b) Train exit rate by store type
![b](../figures/b_exit_rate_by_store_type.png)

Small grocery stores exit far more often than any other type: 15.4% (444 exits in 2,892 store-years) against 1.5% for
supermarkets and for super stores, a ten-fold gap. Batch ends hit small stores hardest: 301 of their 444 exits are
batch ends, so the strict rate drops to 5.5%, while super stores barely move (1.5% to 1.3%). Store type alone already separates
risk strongly, so the historical-rate-by-type baseline is a demanding benchmark, and supermarkets and super stores
(16,396 of the 22,554 train store-years) have too few exits per year for fine-grained comparisons.

## (c) Authorization end dates per day, with batch days
![c](../figures/c_end_dates_per_day.png)

On a typical day 2 or 3 NC retailers lose authorization (3,085 ordinary days average 2.4 ends), but 32 days hold 40 to 281 ends
each: together 3,509 of the 11,012 ends through 2021 (32%), and the five largest days (Mar 2013, Dec 2014, Sep 2016, Mar 2014,
Sep 2011) alone are 11%. Batch days occur in every year from 2006 on, one or two a year through 2016 and three or four a year in 2017, 2018, 2019 and 2021.
The 40-retailer threshold is the 99th percentile of daily counts, a convention rather than a natural break, so a few days just
above it (40-60 ends) may be ordinary busy days; the strict label is the sensitivity check. (This chart counts authorization ends,
not exits, so the ownership-change rule does not change it.)

## (d) How far is the next grocery? By urban-rural group
![d](../figures/d_distance_by_ruca.png)

When an urban store (RUCA 1) exits, another grocery is usually close: only 14% (91 of 662) leave a gap of more than a mile and
none leave more than 10 miles. The metro fringe (RUCA 2-3) has the highest share beyond a mile, 55% (60 of 109), above rural
areas (44%, 20 of 45), but rural exits are the only ones with a sizeable share beyond 10 miles (16%, 7 of 45, against 2% or
less elsewhere). The rural and metro-fringe groups are small (45 and 109 exits), so their percentages are imprecise; one exit in
a zero-population tract is omitted.

## (e) Exit rate by tract income quintile (2012 onward)
![e](../figures/e_exit_rate_by_income_quintile.png)

Exit rates fall steadily with tract income: 6.0% in the lowest quintile (255 exits in 4,268 store-years) down to 2.5% in the
highest (105 in 4,267), about 2.4 times higher at the bottom. The gradient survives dropping batch ends (3.0% down to 1.3%), so it
is not just an artefact of administrative clean-ups. Quintiles are ranked within each cohort year because dollars are adjusted to
different vintage years; this is an association only, and income may partly stand in for store type or size (not checked here:
whether small stores are concentrated in low-income tracts), which should be tested in D3 before reading it as a neighbourhood effect.
