"""Custom scikit-learn preprocessing for the D4 exit model (used inside the saved Pipeline).

`StoreYearPreprocessor` turns raw store-year records (as in data/processed/store_year_trainval.parquet, or one
API request) into the model's input frame. It is the first step of the Pipeline saved by
src/model/04_fit_final.py and served by app/api.py, so training, local scoring and the API all apply the
same preprocessing:

1. **Feature rules.** Only the listed feature columns are passed on (04 passes `feature_columns()`, i.e.
   role == "feature" in docs/column_inventory.csv, without the D4 candidates that were not adopted).
   `fit` refuses a feature list containing `year`, the cohort key, or any qa_*, impact_*, exit_* or bias_*
   column, and everything else in the input (year, labels, QA flags, ids) is dropped.
2. **store_type as a categorical** with the five grocery types as fixed categories, so a one-row request
   gets the same category coding as the training data. Any other store type is an error.
3. **median_hh_income -> within-cohort percentile.** Nominal ACS income drifts upward across vintages, so
   D3/D4 use each store's income percentile among the store-years of the same cohort year
   (`common_model.load_rows`: `groupby("year").rank(pct=True)`). One API request cannot be ranked against its
   cohort, so the transformer stores each cohort's income values (`income_reference`) and computes the same
   average-rank percentile against them. These references are Jan-1 feature values only (no outcomes), the
   same rows `load_rows` ranks today, which keeps the saved model identical to the evaluated one. The
   request's `cohort_year` is used only to pick the reference; it is dropped before the model and is never
   a feature (calendar-year rule). A cohort without a reference is an error.
4. **unemployment_rate median imputation, fitted on the training rows passed to `fit`.** The column is
   missing for the whole 2012 cohort, so a NaN branch (or missing indicator) would mark "cohort 2012", a
   year proxy (docs/changes_since_d3.md, item 1). Same rule as `ImputeUnemployment` in 01_evaluate.py.
   Other columns keep NaN; the gradient-boosted trees handle it natively.
"""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted

GROCERY_TYPES = ("Large Grocery Store", "Medium Grocery Store", "Small Grocery Store", "Super Store", "Supermarket")
FORBIDDEN_PREFIXES = ("qa_", "impact_", "exit_", "bias_")


class StoreYearPreprocessor(TransformerMixin, BaseEstimator):
    """Select and type the model features, rank income within its cohort, impute unemployment_rate.

    Parameters
    ----------
    features : list of str
        Model feature columns, in output order.
    income_reference : dict {cohort year: array of median_hh_income values}
        Every store-year's income in each cohort (missing values are ignored), used for the percentile.
    categorical : str
        The categorical feature; its categories are `store_types`.
    store_types : tuple of str
        Allowed categories of `categorical`, in a fixed order.
    impute_median : tuple of str
        Columns median-imputed with medians learned in `fit`.
    income_col, cohort_col : str
        The income column to convert, and the cohort-year column used only to look up its reference.
    """

    def __init__(self, features, income_reference, categorical="store_type", store_types=GROCERY_TYPES,
                 impute_median=("unemployment_rate",), income_col="median_hh_income", cohort_col="cohort_year"):
        self.features = features
        self.income_reference = income_reference
        self.categorical = categorical
        self.store_types = store_types
        self.impute_median = impute_median
        self.income_col = income_col
        self.cohort_col = cohort_col

    # ------------------------------------------------------------------ checks
    def _check_feature_rules(self):
        feats = list(self.features)
        bad = [c for c in feats if c in ("year", self.cohort_col) or c.startswith(FORBIDDEN_PREFIXES)]
        if bad:
            raise ValueError(f"not allowed as model features (year / qa_ / impact_ / exit_ / bias_): {bad}")
        if len(set(feats)) != len(feats):
            raise ValueError("duplicate feature names")
        needed = [self.categorical, self.income_col, *self.impute_median]
        missing = [c for c in needed if c not in feats]
        if missing:
            raise ValueError(f"columns handled by the transformer but absent from `features`: {missing}")

    def _check_input(self, X):
        if not isinstance(X, pd.DataFrame):
            raise TypeError("StoreYearPreprocessor expects a pandas DataFrame with named columns")
        missing = [c for c in (*self.features, self.cohort_col) if c not in X.columns]
        if missing:
            raise ValueError(f"input is missing columns: {missing}")

    # ------------------------------------------------------------------ fit / transform
    def fit(self, X, y=None):
        self._check_feature_rules()
        self._check_input(X)
        self.features_ = list(self.features)
        self.n_features_in_ = len(self.features_)
        self.feature_names_in_ = np.array(self.features_, dtype=object)
        # Sorted, non-missing incomes per cohort; a copy, so the fitted object never shares the caller's arrays.
        self.income_reference_ = {}
        for year, vals in self.income_reference.items():
            v = np.asarray(vals, dtype=float)
            self.income_reference_[int(year)] = np.sort(v[~np.isnan(v)])
        cohorts = set(pd.to_numeric(X[self.cohort_col]).astype(int))
        if not cohorts <= set(self.income_reference_):
            raise ValueError(f"no income reference for cohorts {sorted(cohorts - set(self.income_reference_))}")
        # Medians come from the rows passed to fit only (04 passes training years 2012-2018).
        self.medians_ = {c: float(self._numeric(X[c]).median()) for c in self.impute_median}
        return self

    @staticmethod
    def _numeric(s):
        # Nullable Int64 / bool -> float64 with NaN for missing, as common_model.load_rows does.
        return pd.to_numeric(s, errors="coerce").astype(float)

    def income_percentile(self, income, cohort):
        """Average-rank percentile of each income within its cohort's reference, as
        pandas `rank(pct=True)` (method "average", missing values ignored) computes it.

        For a value that is in the reference this is exactly the D3/D4 feature. For a new value it is the
        same formula: (number below + (number equal + 1) / 2) / n.
        """
        income = np.asarray(income, dtype=float)
        cohort = np.asarray(cohort).astype(int)
        out = np.full(income.shape, np.nan)
        for year in np.unique(cohort):
            if year not in self.income_reference_:
                known = f"{min(self.income_reference_)}-{max(self.income_reference_)}"
                raise ValueError(f"no income reference for cohort {year} (available: {known})")
            ref = self.income_reference_[year]
            idx = np.flatnonzero((cohort == year) & ~np.isnan(income))
            lo = np.searchsorted(ref, income[idx], side="left")
            hi = np.searchsorted(ref, income[idx], side="right")
            out[idx] = (lo + (hi - lo + 1) / 2) / len(ref)
        return out

    def transform(self, X):
        check_is_fitted(self, "medians_")
        self._check_input(X)
        out = pd.DataFrame(index=X.index)
        for c in self.features_:
            if c == self.categorical:
                bad = sorted(set(X[c].dropna().astype(str)) - set(self.store_types))
                if bad or X[c].isna().any():
                    raise ValueError(f"{c} must be one of {list(self.store_types)}; got {bad or 'missing'}")
                out[c] = pd.Categorical(X[c].astype(str), categories=list(self.store_types))
            elif c == self.income_col:
                out[c] = self.income_percentile(self._numeric(X[c]), X[self.cohort_col])
            else:
                out[c] = self._numeric(X[c])
        for c, m in self.medians_.items():
            out[c] = out[c].fillna(m)
        return out

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, "features_")
        return np.array(self.features_, dtype=object)
