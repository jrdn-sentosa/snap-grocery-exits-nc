# Predicting Grocery Store Exits in North Carolina, with a Charlotte-Mecklenburg Focus

**D1: Problem and Research Question Proposal** (approved, 10/10)

Nick Daniels, Feyruz Habteab, Eric Ho, Vishnu Inuganti, Hailey McCall, Jordan Sentosa

---

## 1. The Problem

15% of Mecklenburg residents live in food deserts and lack access to fresh, affordable groceries (WBTV, 2026). Nationally, 5.5% of census tracts are food deserts in 2023, a share that has barely changed since 2003 (Wiese et al., 2026). Having these SNAP-authorized grocery stores is important to prevent this number from increasing. Recent SNAP benefit cuts have pushed more families toward food banks (PBS NewsHour, 2026), which raises the stakes of losing the grocery stores that accept SNAP. USDA is soon to implement a new policy that increases the requirements for stores to become SNAP-authorized: by November 4, 2026, stores must carry seven varieties in each of four staple food categories (USDA, 2026). While this policy has the positive effect of raising standards and making sure these stores stock more staple and perishable foods, it may also limit the places where SNAP benefits can be used, making this an even more pressing issue.

Food deserts arise as a consequence of historical disinvestment and market forces; a food desert is defined as a low-income and low-access census tract. For urban areas like Charlotte, low-access means at least 500 people, or a third of residents, live more than 1 mile from a supermarket or large grocery store (USDA ERS).

- **Who it affects:** low-income households that rely on SNAP, older adults, people with disabilities, households without a car, and residents of neighborhoods that already have few grocery options.
- **Decision supported:** the Charlotte-Mecklenburg Food Policy Council, local economic-development staff and food nonprofits could use a ranked list of grocery stores at high risk of losing SNAP authorization to act before a closure creates or deepens a food desert.

## 2. Domain Choice

A commonality that we had as a group is that we liked food, but even for us, it is not as affordable as it once was. This problem is exacerbated for children, elderly people, disabled people, and low-income earners. These are the most vulnerable members of our society, whom we have a responsibility to protect. As Charlotte residents, our neighbors are the ones being affected.

Another dimension of this problem is the rapid growth of Charlotte, where rising housing, utility, and transportation costs leave less money for food, which is also subject to inflationary pressures. When a SNAP-authorized grocery store closes, especially in an area with limited access to healthy foodstuffs, our vulnerable neighbors may be losing their only nearby access point to healthy and affordable food. Closures are measurable events in public data, which gives us an objective way to connect geospatial data to food access.

What we hope to understand is: which variables help predict the closure of SNAP-authorized grocery stores, how those variables are associated with closure risk, and how predictions can provide actionable information to policymakers and community organizers?

## 3. Research Question

**Using only information available on January 1 of each year, can we predict which SNAP-authorized grocery stores in North Carolina will lose SNAP authorization within the next 12 months more accurately than the historical exit rate for their store type?**

- **Observation:** one grocery store (Record ID with store type Supermarket, Super Store, or Large, Medium, or Small Grocery Store) authorized on January 1 of a given year (a store-year).
- **Outcome:** 1 if the store's authorization ends within the next 12 months, otherwise 0. A new authorization at the same address within 90 days is treated as an ownership change, not an exit.
- **Population and period:** North Carolina grocery stores, yearly cohorts 2011–2024 (2024 is the last cohort with a complete 12-month outcome). Mecklenburg results are reported separately.
- **Information at prediction time:** store type, years since authorization, chain vs. independent, number of and distance to other active grocery stores that day, tract demographics from the most recently released ACS 5-year estimates, the latest USDA low-income/low-access tract flag released before that year, urban/rural classification, and the ratio of nearby SNAP convenience stores to grocery stores. Cohorts before the first USDA food-access release treat that flag as missing.

## 4. Dataset

- **Primary dataset:** USDA FNS Historical SNAP Retailer Locator Data (https://www.fna.usda.gov/snap/retailer-locator/data), a zipped national CSV (about 23 MB) covering every retailer that held SNAP authorization at any point from 2005 to 2025, with fields Record ID, Store Name, Store Type, street address, City, State, Zip Code, County, Latitude, Longitude, Authorization Date, and End Date.
- **Access and sample inspection:** filtered to North Carolina grocery store types, the file has 4,595 authorization records, 2,133 currently active (Supermarket 1,620 records/998 active; Small Grocery 1,239/220; Super Store 791/576; Medium Grocery 725/261; Large Grocery 220/78). 492 of these records are in Mecklenburg County.
- **Target:** derived from End Date as defined above.
- **Inspection findings (Mecklenburg, all store types, 1,957 records):** a row is an authorization period, not a store; 331 of 1,148 ended stores had a new record at the same address within 90 days, suggesting ownership changes; seven legacy chain records carry a 1/1/1930 placeholder date (next earliest is 1973); and city names are inconsistently spelled.
- **Feature sources:** Census ACS 5-year API (income, poverty, vehicle availability, SNAP households, age, renters); TIGER/Line tract boundaries; USDA Food Access Research Atlas (2010, 2015, 2019); USDA Rural-Urban Commuting Area codes. The Mecklenburg Quality of Life Explorer (grocery proximity, age of residents) covers only Mecklenburg, so we use it for the app and for validating our access measures, not as a model feature.
- **Gaps and restrictions:** an ended authorization is not always a closure (it can be a voluntary withdrawal or disqualification), although for SNAP households losing authorization still means losing access at that store; ACS values have margins of error; tract boundaries changed in 2020. All sources are public government data with no restrictions beyond citation.

## 5. Evaluation Plan

- **Split by time:** train on 2011–2018 cohorts, validate on 2019–2021, and hold out 2022–2024 as untouched test data. The same store appears in many years, so a random split could cause data leaks in training. Preprocessing is fit on training years only.
- **Baseline:** each store type's historical exit rate from training years.
- **Metrics:** precision-recall AUC, precision and recall among the highest-risk stores (top 50 statewide, top 10 in Mecklenburg, matching limited outreach capacity). We will not rely on accuracy, because exits are rare and predicting "no exit" for every store would score highly while being useless.

## 6. Scope and Risks

- **Intended app:** a website focused on Charlotte where a user selects a grocery store (or enters a store's attributes) and sees its predicted 12-month exit risk on a map, along with how many nearby residents, especially low-income and car-free households, would be left more than a mile from a grocery store if it closed.
- **Main feasibility risk:** label quality. SNAP exits only approximate closures, and our ownership-change rule depends on matching inconsistently formatted addresses. To mitigate this, we can standardize addresses before matching, hand-check a sample of labeled exits against news reports, and report how results change under a stricter exit definition.
- **Bias and misleading conclusions:** (1) Demographic features could lead the model to flag stores in Black or low-income neighborhoods because of correlation rather than store-level causes, reinforcing stereotypes. We will compare error rates across tract income and demographic groups with sample sizes, and state that predictions do not establish causes. (2) Survivorship: stores that closed before 2005 are missing (in Mecklenburg, only 281 of 1,957 records predate 2005), and store locations reflect earlier siting decisions, so the model learns from stores that already passed a selection process. We will report this limitation and check whether results differ for newer vs. older stores.
- **Policy change:** the new stocking standards take effect after our data ends (December 2025), so the model cannot capture rule-driven exits. We will present predictions as a pre-rule baseline and report small-grocery results separately.

## References

### Datasets

- Mecklenburg County. *Age of residents – Quality of Life (QOL)* [Data set]. Data.gov. Retrieved October 21, 2026, from https://catalog.data.gov/dataset/age-of-residents-quality-of-life-qol
- Mecklenburg County. *Proximity to a grocery store* [Data set]. Quality of Life Explorer. Retrieved October 21, 2026, from https://maps.mecklenburgcountync.gov/qol/data/meta/m45.html
- U.S. Census Bureau. *American Community Survey 5-year data* [Data set and API]. Retrieved October 21, 2026, from https://www.census.gov/data/developers/data-sets/acs-5year.html
- U.S. Census Bureau. *TIGER/Line shapefiles* [Data set]. Retrieved October 21, 2026, from https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html
- U.S. Department of Agriculture, Economic Research Service. *Food Access Research Atlas* [Data set]. Retrieved October 21, 2026, from https://www.ers.usda.gov/data-products/food-access-research-atlas/
- U.S. Department of Agriculture, Economic Research Service. *Rural-urban commuting area codes* [Data set]. Retrieved October 21, 2026, from https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes/
- U.S. Department of Agriculture, Food and Nutrition Service. *Historical SNAP retailer locator data, 2005–2025* [Data set]. Retrieved October 21, 2026, from https://www.fns.usda.gov/snap/retailer-locator/data

### Background sources

- PBS NewsHour. (2026, October 13). *Cuts to SNAP benefits push many Americans to seek help from food banks* [Video]. https://www.pbs.org/newshour/show/cuts-to-snap-benefits-push-many-americans-to-seek-help-from-food-banks
- U.S. Department of Agriculture. (2026, May 7). *USDA requires SNAP-authorized retailers carry more real food* [Press release]. https://www.usda.gov/about-usda/news/press-releases/2026/05/07/usda-requires-snap-authorized-retailers-carry-more-real-food
- WBTV. (2026, March 26). *New film examines how 15% of Mecklenburg County residents lack access to fresh, affordable groceries.* https://www.wbtv.com/2026/03/26/new-film-examines-how-15-mecklenburg-county-residents-lack-access-fresh-affordable-groceries/
- Wiese, D., Shams-White, M. M., Zheng, Z., Henry, K. A., McCullough, M. L., & Islami, F. (2026, June 17). Changes in neighborhood foodscapes from 2003 to 2023 by area rurality in the United States. *American Journal of Public Health, 116*(7), 1004–1014. https://doi.org/10.2105/AJPH.2026.308495

### Also looked at

- Sustain Charlotte. (2020, August 3). *Food deserts and transit.* Retrieved October 21, 2026, from https://sustaincharlotte.org/food_deserts_and_transit/
- UNC Charlotte Urban Institute. (2020, April 6). *Eating healthy in a food desert: Mecklenburg leaders seek new solutions.* Retrieved October 21, 2026, from https://ui.charlotte.edu/story/eating-healthy-food-desert-mecklenburg-leaders-seek-new-solutions/