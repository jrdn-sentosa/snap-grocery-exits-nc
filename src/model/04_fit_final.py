"""D4: fit the frozen exit_12m model as one scikit-learn Pipeline and save it for the API.

    uv run python src/model/04_fit_final.py

Needs data/processed/store_year_trainval.parquet (src/prep/05_features.py). The reserved test file is never read.

Model (frozen after the post-D3 rerun, CLAUDE.md / docs/changes_since_d3.md): HistGradientBoostingClassifier,
learning_rate 0.1, max_leaf_nodes 2, min_samples_leaf 100, l2_regularization 0, max_iter 300 (no early stopping),
label exit_12m, fit on train cohorts 2012-2018 only. Nothing is tuned or selected here.

Pipeline = [StoreYearPreprocessor (src/model/transformers.py) -> HistGradientBoostingClassifier]. It takes raw
store-year columns plus `cohort_year` and does all preprocessing itself (feature selection, store_type categories,
within-cohort income percentile, unemployment_rate imputation fitted on the training rows).

Checks before saving (the script stops if one fails):
- the transformer's income percentile equals common_model.load_rows()'s exactly on every 2012-2021 row;
- the D3/D4 evaluation code path (01_evaluate.make_hgb on load_rows()) gives the same validation probabilities;
- validation PR-AUC equals the trees row for exit_12m in docs/model_results.csv.

Writes models/exit_model.joblib (committed) and models/exit_model.json (versions, features, rows, PR-AUC).
"""

import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from common_model import DOCS, SEED, TRAIN_YEARS, TRAINVAL, VAL_YEARS, feature_columns, load_rows  # noqa: E402
# Imported by its package path so the pickled Pipeline refers to `src.model.transformers`; anything that loads
# the .joblib (app/api.py, 05_verify_api.py, the Modal image) needs the repository root on sys.path.
from src.model.transformers import StoreYearPreprocessor  # noqa: E402

MODELS = ROOT / "models"
MODEL_PATH = MODELS / "exit_model.joblib"
META_PATH = MODELS / "exit_model.json"
LABEL = "exit_12m"
HGB_PARAMS = dict(learning_rate=0.1, max_leaf_nodes=2, min_samples_leaf=100, l2_regularization=0.0, max_iter=300)
FEATURES = feature_columns()  # inventory "feature" columns, without the D4 candidates that were not adopted


def load_raw() -> pd.DataFrame:
    """2012-2021 store-years with raw feature values (income in dollars) and `cohort_year`."""
    df = pd.read_parquet(TRAINVAL)
    assert df["year"].max() <= 2021, "test-period rows found in the train/validation file"
    df = df[df["year"].isin(list(TRAIN_YEARS) + list(VAL_YEARS))].copy()
    df["cohort_year"] = df["year"].astype(int)
    return df


def income_reference(df: pd.DataFrame) -> dict[int, list[float]]:
    # Every store-year of each cohort, as load_rows ranks them: Jan-1 feature values only, no outcomes.
    inc = pd.to_numeric(df["median_hh_income"], errors="coerce").astype(float)
    return {int(y): inc[df["cohort_year"] == y].dropna().tolist() for y in sorted(df["cohort_year"].unique())}


def build_pipeline(ref) -> Pipeline:
    return Pipeline([
        ("prep", StoreYearPreprocessor(features=FEATURES, income_reference=ref)),
        ("hgb", HistGradientBoostingClassifier(**HGB_PARAMS, early_stopping=False,
                                               categorical_features="from_dtype", random_state=SEED)),
    ])


def reference_val_probs(train_idx, val_idx):
    """Fit the same model through 01_evaluate's code path (load_rows + make_hgb) and score validation."""
    spec = importlib.util.spec_from_file_location("evaluate01", HERE / "01_evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    rows = load_rows()
    m = ev.make_hgb(lr=HGB_PARAMS["learning_rate"], leaves=HGB_PARAMS["max_leaf_nodes"],
                    min_leaf=HGB_PARAMS["min_samples_leaf"], l2=HGB_PARAMS["l2_regularization"])
    m.fit(rows.loc[train_idx, FEATURES], rows.loc[train_idx, LABEL].astype(int))
    return rows, m.predict_proba(rows.loc[val_idx, FEATURES])[:, 1]


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def main():
    df = load_raw()
    df = df[df[LABEL].notna()]  # rows_for_label: exit_12m is never missing, kept for symmetry with 01
    train = df[df["cohort_year"].isin(TRAIN_YEARS)]
    val = df[df["cohort_year"].isin(VAL_YEARS)]
    y_train, y_val = train[LABEL].astype(int), val[LABEL].astype(int)
    X_cols = [*FEATURES, "cohort_year"]
    print(f"train {len(train):,} rows / {y_train.sum()} exits; validation {len(val):,} / {y_val.sum()}")

    ref = income_reference(load_raw())
    pipe = build_pipeline(ref).fit(train[X_cols], y_train)
    p_val = pipe.predict_proba(val[X_cols])[:, 1]
    ap = average_precision_score(y_val, p_val)

    # --- check 1: income percentile identical to load_rows()
    rows, p_ref = reference_val_probs(train.index, val.index)
    prep = pipe.named_steps["prep"]
    pct = prep.income_percentile(df["median_hh_income"].astype(float), df["cohort_year"])
    pct_ref = rows.loc[df.index, "median_hh_income"].to_numpy(dtype=float)
    same_nan = np.array_equal(np.isnan(pct), np.isnan(pct_ref))
    pct_diff = float(np.nanmax(np.abs(pct - pct_ref)))
    assert same_nan and pct_diff == 0.0, f"income percentile differs from load_rows (max diff {pct_diff})"
    # --- check 2: same predictions as the evaluation code path
    prob_diff = float(np.max(np.abs(p_val - p_ref)))
    assert prob_diff < 1e-12, f"validation probabilities differ from 01_evaluate's model by {prob_diff}"
    # --- check 3: same validation PR-AUC as docs/model_results.csv
    res = pd.read_csv(DOCS / "model_results.csv")
    doc_ap = float(res.loc[(res["label"] == LABEL) & (res["model"] == "Gradient-boosted trees"), "val_pr_auc"].iloc[0])
    assert abs(ap - doc_ap) < 1e-9, f"validation PR-AUC {ap} != docs/model_results.csv {doc_ap}"
    names_out = list(pipe[:-1].get_feature_names_out())
    assert names_out == FEATURES and "cohort_year" not in names_out and "year" not in names_out
    print(f"checks passed: income percentile max diff {pct_diff}, probability max diff {prob_diff:.1e}, "
          f"validation PR-AUC {ap:.4f} (docs/model_results.csv {doc_ap:.4f})")

    MODELS.mkdir(exist_ok=True)
    joblib.dump(pipe, MODEL_PATH, compress=3)
    meta = {
        "model": "exit_12m gradient-boosted trees (frozen D4 model)",
        "label": LABEL,
        "estimator": "sklearn.ensemble.HistGradientBoostingClassifier",
        "hyperparameters": {**HGB_PARAMS, "early_stopping": False, "random_state": SEED},
        "features": FEATURES,
        "request_only_fields": {"cohort_year": "selects the income reference; dropped before the model, never a feature"},
        "income_reference_cohorts": sorted(ref),
        "unemployment_rate_median_imputed": prep.medians_["unemployment_rate"],
        "train_cohorts": [min(TRAIN_YEARS), max(TRAIN_YEARS)],
        "train_rows": int(len(train)), "train_exits": int(y_train.sum()),
        "validation_cohorts": [min(VAL_YEARS), max(VAL_YEARS)],
        "validation_rows": int(len(val)), "validation_exits": int(y_val.sum()),
        "validation_pr_auc": ap, "validation_pr_auc_docs_model_results": doc_ap,
        "versions": {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                     "pandas": pd.__version__, "numpy": np.__version__, "joblib": joblib.__version__},
        "git_commit": git_commit(),
        "joblib_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
    }
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {MODEL_PATH.relative_to(ROOT)} ({MODEL_PATH.stat().st_size / 1024:.0f} KB) and {META_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
