"""Prediction API for the frozen D4 model (FastAPI), built on src/model/serving.py.

The contract is docs/model_spec_d4.md (sections 2, 8, 9, 10, 11). Nothing about scoring is implemented here: every number comes from
`serving.Bundle.score`, which runs the saved Pipeline (store_prep.StoreFeaturePrep -> frozen HistGradientBoostingClassifier),
explain.py and impact.py.

Startup: load models/pipeline.joblib and run `Bundle.self_check()`. Until it passes, POST /predict answers 503; GET /health reports the result
and the failure messages.

Run locally, from the repository root (FastAPI is in the `api` dependency group of pyproject.toml):
    uv run --group api fastapi dev app/api.py      # http://127.0.0.1:8000/docs
Deployed on Modal by app/modal_api.py.

Request: POST /predict takes a JSON array of 1-1000 store-year records. Each record has every key in store_prep.FIELD_RULES
(`year` = cohort year, the 20 model inputs with median_hh_income in dollars, and dist_other_grocery_jan1_mi for the impact score);
`null` only where the rule allows it. The Pydantic model is generated from FIELD_RULES, so invalid input gets a 422 naming the field.
"""

import os
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from annotated_types import Len
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, create_model

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))  # store_prep (the pickle imports it by that name), serving, explain, impact
import serving  # noqa: E402
from store_prep import FIELD_RULES  # noqa: E402

MODEL_DIR = Path(os.environ.get("MODEL_DIR", ROOT / "models"))
MAX_RECORDS = 1000

# Limits the app must state (docs/model_spec_d4.md, section 10), verbatim.
LIMITS = [
    "Estimates a store's chance of losing SNAP authorization within 12 months of Jan 1, with ownership changes not counted as exits and "
    "administrative batch ends counted as exits (exit_12m). It does not say a store will close.",
    "Discrimination is modest: 2012-2018 model validation PR-AUC 0.149 against a 3.5% exit rate; top-50-per-year precision 25%. "
    "Say 'higher risk', not 'will exit'.",
    "Fairness: dropping the seven tract demographic inputs did not narrow the majority-Black vs majority-White false-positive gap "
    "(4.1% vs 1.5% with them, 4.6% vs 1.2% without, validation, top 50 per year); it is plausibly carried by store type and chain size. "
    "To be reported on the test set in D6 (docs/changes_since_d3.md).",
    "The 2022-2024 cohorts have never been scored. The refit model's only evaluation is the D6 test run.",
]

# ---------------------------------------------------------------- startup: load the bundle and run the self-check
BUNDLE: serving.Bundle | None = None
SELF_CHECK_OK = False
PROBLEMS: list[str] = []
try:
    BUNDLE = serving.Bundle(MODEL_DIR)
    SELF_CHECK_OK, PROBLEMS = BUNDLE.self_check()
except Exception as exc:  # a bundle that cannot load is a failed check: the app still starts and answers 503
    PROBLEMS = [f"could not load {MODEL_DIR / serving.BUNDLE_FILE}: {type(exc).__name__}: {exc}"]


# ---------------------------------------------------------------- request model, generated from store_prep.FIELD_RULES
def _store_types() -> tuple[str, ...]:
    """The categories the fitted transformer accepts (it rejects anything else)."""
    if BUNDLE is not None:
        return tuple(BUNDLE.pipeline.named_steps["prep"].store_type_categories_)
    return ("Large Grocery Store", "Medium Grocery Store", "Small Grocery Store", "Super Store", "Supermarket")


def _field_type(name: str, rule: dict) -> Any:
    kind = rule["kind"]
    if kind == "category":
        t = Literal[_store_types()]
    elif kind == "int":
        t = Annotated[int, Field(ge=rule.get("min"), le=rule.get("max"))]
    elif kind == "binary":
        t = Annotated[int, Field(ge=0, le=1, description="0 or 1")]
    elif kind == "share":
        t = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, description="share from 0 to 1")]
    elif kind == "float":
        t = Annotated[float, Field(ge=rule.get("min"), le=rule.get("max"), allow_inf_nan=False)]
    else:
        raise ValueError(f"FIELD_RULES[{name!r}]: unknown kind {kind!r}")
    return t | None if rule["nullable"] else t


# Every key is required (`...`); nullable fields accept null but must still be present. Unknown keys are rejected.
StoreYearRecord = create_model(
    "StoreYearRecord",
    __config__=ConfigDict(extra="forbid"),
    **{name: (_field_type(name, rule), ...) for name, rule in FIELD_RULES.items()},
)


class Reason(BaseModel):
    feature: str
    text: str
    effect: float


class ScoredRow(BaseModel):
    row: int
    raw_score: float
    probability: float
    tier: str
    impact: float
    priority: float
    reasons: list[Reason]


class PredictResponse(BaseModel):
    predictions: list[ScoredRow]


def _example_request() -> list[dict]:
    """ex1 from the bundle's fixed examples (the same content as docs/model_examples_d4.json), as a one-record request."""
    if BUNDLE is None:
        return []
    ex = next(e for e in BUNDLE.examples if e["id"] == "ex1")
    return [{"year": ex["cohort_year"], **ex["inputs"], **ex["context"]}]


# ---------------------------------------------------------------- app
app = FastAPI(
    title="SNAP grocery store exit risk (North Carolina), D4",
    version=(BUNDLE.meta.get("created", "unknown") if BUNDLE else "unavailable"),
    description=(
        "Risk that a SNAP-authorized NC grocery store loses authorization within 12 months of Jan 1 (`exit_12m`), with a risk tier, "
        "an access-impact score, priority = risk x impact, and the top reasons (medium and high tier only). Frozen D4 gradient-boosted "
        "trees refit on cohorts 2012-2021; contract in docs/model_spec_d4.md.\n\n**Limits:**\n\n" + "\n".join(f"- {s}" for s in LIMITS)
    ),
)


# CORS: a browser front end may call the API from the local dev server or from our Vercel site. The Vercel origin comes from the
# FRONTEND_ORIGIN environment variable; the default is an inert placeholder (a reserved .invalid host), so nothing real is allowed
# until it is set. Only GET and POST are allowed, and no credentials (the API has no cookies or auth).
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "https://placeholder.invalid").rstrip("/")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", FRONTEND_ORIGIN], allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"], allow_credentials=False)


def _require_model() -> serving.Bundle:
    if BUNDLE is None or not SELF_CHECK_OK:
        raise HTTPException(status_code=503, detail={"error": "model unavailable: startup self-check has not passed", "problems": PROBLEMS})
    return BUNDLE


@app.get("/")
def root():
    return {"docs": "/docs", "health": "/health", "model_info": "/model-info", "predict": "POST /predict"}


@app.get("/health")
def health():
    """Startup self-check result (serving.Bundle.self_check). Scoring answers 503 while `self_check_passed` is false."""
    return {"status": "ok" if SELF_CHECK_OK else "unavailable", "self_check_passed": SELF_CHECK_OK, "problems": PROBLEMS}


@app.get("/model-info")
def model_info():
    """Bundle metadata (versions, tier cutoffs, training years, features, ...) and the limits of the model."""
    if BUNDLE is None:
        raise HTTPException(status_code=503, detail={"error": "model bundle not loaded", "problems": PROBLEMS})
    return {"metadata": BUNDLE.meta, "self_check_passed": SELF_CHECK_OK, "limits": LIMITS}


@app.post("/predict", response_model=PredictResponse)
def predict(records: Annotated[list[StoreYearRecord], Len(1, MAX_RECORDS),  # type: ignore[valid-type]
                               Body(examples=[_example_request()])]):
    bundle = _require_model()
    X = pd.DataFrame([r.model_dump() for r in records])
    for c in X.columns:  # JSON null -> NaN; the Pipeline and impact score treat missing values as in training
        if c != "store_type":
            X[c] = pd.to_numeric(X[c]).astype(int if c == "year" else float)
    try:
        out = bundle.score(X)
    except ValueError as e:  # defence in depth (spec section 11): the transformer's ValueError is a client error, not a 500
        raise HTTPException(status_code=422, detail=[{"loc": ["body"], "msg": str(e), "type": "value_error"}])
    rows = []
    for i, r in enumerate(out.itertuples(index=False)):
        rows.append({"row": i, "raw_score": float(r.raw_score), "probability": float(r.probability), "tier": str(r.tier),
                     "impact": float(r.impact), "priority": float(r.priority),
                     "reasons": [{"feature": str(x["feature"]), "text": str(x["text"]), "effect": float(x["effect"])} for x in r.reasons]})
    return {"predictions": rows}
