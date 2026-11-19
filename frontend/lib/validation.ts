/**
 * Validation-period (2019-2021) results shown on How it works. Copied by hand from the generated docs, which are the source of truth:
 *   - docs/model_results.md  (exit_12m table: models fit on 2012-2018, scored on 2019-2021)
 *   - docs/risk_tiers.md     (observed exit rate by tier on the same years; the tier cutoffs were chosen on these years)
 *   - docs/fairness_variant.md (false-positive rates by tract majority, with and without the tract demographic inputs)
 * Nothing here comes from the reserved test years (2022-2024); those are evaluated once, in D6.
 */
export const VALIDATION = {
  years: "2019–2021",
  fitYears: "2012–2018",
  prAuc: { model: 0.149, modelCi: "0.118–0.194", baseline: 0.108, baselineCi: "0.088–0.130", diffCi: "0.022 to 0.076" },
  rocAuc: { model: 0.818, baseline: 0.752 },
  brier: { model: 0.0321, baseline: 0.0324 },
  top50: { flagged: 150, model: 38, baseline: 22 },
  meckTop10: { flagged: 30, model: 8, baseline: 6 },
  gapExitsTop50: { total: 44, model: 8, baseline: 1 },
  tiers: [
    { tier: "low", storeYears: 2973, exits: 8, rate: 0.003 },
    { tier: "medium", storeYears: 2728, exits: 117, rate: 0.043 },
    { tier: "high", storeYears: 647, exits: 100, rate: 0.155 },
  ],
  baseRate: 0.0422,
  fairness: {
    withDemographics: { black: { flagged: 31, nonExits: 636, fpr: 0.041 }, white: { flagged: 81, nonExits: 4024, fpr: 0.015 } },
    withoutDemographics: { black: { flagged: 36, nonExits: 636, fpr: 0.046 }, white: { flagged: 63, nonExits: 4024, fpr: 0.012 } },
    foldPrAuc: { withDemographics: 0.1549, without: 0.1486, bar: 0.15 },
  },
} as const;
