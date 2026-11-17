"""Prediction API for the frozen D4 exit_12m model (FastAPI).

Loads models/exit_model.joblib (built by src/model/04_fit_final.py) and returns the probability that each
SNAP-authorized grocery store-year loses authorization within the next 12 months (exit_12m). It reads no
database and needs no credentials.

Run locally, from the repository root:
    uv run fastapi dev app/api.py          # http://127.0.0.1:8000/docs
Deployed on Modal by app/modal_api.py.

Endpoints: GET /health, GET /model-info, POST /predict (interactive docs at /docs).

The saved Pipeline does all preprocessing (src/model/transformers.py). Each record carries the raw Jan-1
feature values plus `cohort_year`, which only selects the income reference for the within-cohort income
percentile and is never a model feature. Unknown fields (e.g. `year`, labels, qa_* flags) are rejected.
"""

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal

import joblib
import numpy as np
import pandas as pd
import sklearn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # the pickled Pipeline imports src.model.transformers
MODEL_PATH = Path(os.environ.get("EXIT_MODEL_PATH", ROOT / "models" / "exit_model.joblib"))
META = json.loads(MODEL_PATH.with_suffix(".json").read_text(encoding="utf-8"))

# A pickled scikit-learn model is only guaranteed to load and predict identically under the version that
# fit it, so refuse to start under any other version (the Modal image pins it from exit_model.json).
if sklearn.__version__ != META["versions"]["scikit-learn"]:
    raise RuntimeError(f"scikit-learn {sklearn.__version__} installed, but the model was fit with "
                       f"{META['versions']['scikit-learn']}; install that version.")
MODEL = joblib.load(MODEL_PATH)
COHORTS = META["income_reference_cohorts"]

GroceryType = Literal["Supermarket", "Super Store", "Large Grocery Store", "Medium Grocery Store", "Small Grocery Store"]
Count = Annotated[int, Field(ge=0, le=10_000)]
Share = Annotated[float | None, Field(ge=0, le=1, description="Proportion between 0 and 1 (not a percent)")]


class StoreYear(BaseModel):
    """One grocery store authorized on Jan 1 of `cohort_year`, with features known on that date."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "record_id": "example-1", "cohort_year": 2021, "store_type": "Small Grocery Store",
        "store_age_years": 3.2, "auth_date_placeholder": False, "n_prior_spells_same_id": 0,
        "n_prior_ownership_changes": 1, "chain_size": 1, "n_grocery_05mi": 2, "n_grocery_1mi": 5,
        "n_convenience_1mi": 9, "convenience_to_grocery_ratio_1mi": 1.8, "n_grocery_ends_1mi_prior12m": 1,
        "acs_population": 4210, "pop_density_sqmi": 3150.5, "pct_poverty": 0.24, "median_hh_income": 38750,
        "pct_no_vehicle": 0.11, "pct_snap_hh": 0.22, "pct_renter": 0.58, "pct_age_65_plus": 0.12,
        "unemployment_rate": 0.07}]})

    record_id: str | None = Field(default=None, max_length=64, description="Optional; echoed back")
    cohort_year: int = Field(ge=min(COHORTS), le=max(COHORTS),
                             description="Cohort year t (Jan 1 snapshot). Selects the income reference only; not a feature.")
    store_type: GroceryType
    store_age_years: float | None = Field(default=None, ge=0, le=150, description="Years since authorization; null if unknown")
    auth_date_placeholder: bool = Field(description="Authorization date was the 1/1/1930 placeholder")
    n_prior_spells_same_id: Count
    n_prior_ownership_changes: Count
    chain_size: int | None = Field(default=None, ge=1, le=100_000, description="SNAP stores with the same cleaned name")
    n_grocery_05mi: Count
    n_grocery_1mi: Count
    n_convenience_1mi: Count
    convenience_to_grocery_ratio_1mi: float = Field(ge=0, le=10_000)
    n_grocery_ends_1mi_prior12m: Count
    acs_population: float | None = Field(default=None, ge=0, le=1_000_000, description="Tract population (ACS)")
    pop_density_sqmi: float | None = Field(default=None, ge=0, le=1_000_000, description="Tract people per sq mi")
    pct_poverty: Share = None
    median_hh_income: float | None = Field(default=None, ge=0, le=250_001,
                                           description="Tract median household income, nominal dollars of the ACS vintage for this cohort")
    pct_no_vehicle: Share = None
    pct_snap_hh: Share = None
    pct_renter: Share = None
    pct_age_65_plus: Share = None
    unemployment_rate: float | None = Field(default=None, ge=0, le=1,
                                            description="Tract unemployment rate (proportion); null is median-imputed")


REQUEST_ONLY = {"record_id", "cohort_year"}
_schema_features = set(StoreYear.model_fields) - REQUEST_ONLY
assert _schema_features == set(META["features"]), f"API schema and model features differ: {_schema_features ^ set(META['features'])}"


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[StoreYear] = Field(min_length=1, max_length=1000)


class Prediction(BaseModel):
    record_id: str | None
    cohort_year: int
    exit_probability: float


class PredictResponse(BaseModel):
    model: str
    predictions: list[Prediction]


app = FastAPI(
    title="SNAP grocery store exit model (North Carolina)",
    version=META["git_commit"],
    description="Probability that a SNAP-authorized NC grocery store loses authorization within 12 months "
                "(exit_12m), from information available on Jan 1. Frozen D4 gradient-boosted trees; "
                "see GET /model-info.",
)


@app.get("/")
def root():
    return {"docs": "/docs", "health": "/health", "model_info": "/model-info", "predict": "POST /predict"}


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": MODEL is not None, "scikit_learn": sklearn.__version__}


@app.get("/model-info")
def model_info():
    return {**META, "runtime_versions": {"python": sys.version.split()[0], "scikit-learn": sklearn.__version__,
                                         "pandas": pd.__version__, "numpy": np.__version__}}


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    X = pd.DataFrame([r.model_dump(exclude={"record_id"}) for r in req.records])
    try:
        p = MODEL.predict_proba(X)[:, 1]
    except ValueError as e:  # e.g. a cohort without an income reference
        raise HTTPException(status_code=422, detail=str(e))
    return {"model": META["model"],
            "predictions": [{"record_id": r.record_id, "cohort_year": r.cohort_year, "exit_probability": float(pi)}
                            for r, pi in zip(req.records, p)]}
