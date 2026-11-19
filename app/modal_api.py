"""Deploy the D4 prediction API (app/api.py) on Modal as an ASGI app.

HW4 pattern: the FastAPI app lives in its own module (app/api.py); this file only builds the image and returns that app from an
@modal.asgi_app() function. It is a separate Modal app from the Streamlit dashboard (app/modal_app.py). The API reads no database, so
**no credential is attached** (the snap-supabase secret is not needed). The only value passed in is FRONTEND_ORIGIN, the public website origin
that CORS must allow (see below).

Build the model first (models/ is gitignored; the bundle is baked into the image from the local build):
    uv run python src/model/09_final_refit.py           # after the README "Reproduce" steps
Deploy, from the repository root (set FRONTEND_ORIGIN in the shell to override the default production domain):
    uv run python -m modal deploy app/modal_api.py
URL: https://<modal-workspace>--snap-grocery-exits-api.us-east.modal.run  (/docs, /health, /model-info, POST /predict)

The image mirrors the repository layout (/root/app/api.py, /root/src/model/*.py, /root/models/pipeline.joblib), so api.py finds
store_prep.py, serving.py, explain.py and impact.py on its import path and serving.Bundle finds the bundle. Package versions are pinned to
the ones the bundle was built with (docs/model_spec_d4.md, section 8), read from models/metadata.json; scikit-learn must be 1.9.1.
"""

import json
import os
import re
from pathlib import Path

import modal

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
MODEL_SRC = ROOT / "src" / "model"
SKLEARN_PIN = "1.9.1"           # spec section 8
FASTAPI_PIN = "0.163.1"         # same as the `api` dependency group in pyproject.toml

# CORS: the one extra origin app/api.py allows (besides http://localhost:3000). Read from the LOCAL environment at deploy time, defaulting to the
# production site. Not a secret (it is a public URL); Modal.Secret.from_dict is just the way to hand an environment variable to the container.
DEFAULT_FRONTEND_ORIGIN = "https://snap-grocery-exits-nc.vercel.app"
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "").strip().rstrip("/") or DEFAULT_FRONTEND_ORIGIN
if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?", FRONTEND_ORIGIN):   # an origin has no path, query or trailing slash
    raise SystemExit(f"FRONTEND_ORIGIN must be an origin like https://example.vercel.app (no path), got {FRONTEND_ORIGIN!r}")

app = modal.App("snap-grocery-exits-api")

if modal.is_local():
    # Read only where the repository exists (deploy time); inside the container the image is already built.
    meta = json.loads((ROOT / "models" / "metadata.json").read_text(encoding="utf-8"))
    if meta["sklearn_version"] != SKLEARN_PIN:
        raise SystemExit(f"bundle built with scikit-learn {meta['sklearn_version']}, spec pins {SKLEARN_PIN}: rebuild before deploying")
    PINS = [f"scikit-learn=={SKLEARN_PIN}", f"numpy=={meta['numpy_version']}", f"pandas=={meta['pandas_version']}",
            "scipy==1.18.1", "joblib==1.6.0", f"fastapi[standard]=={FASTAPI_PIN}"]
else:
    PINS = []

image = modal.Image.debian_slim(python_version="3.13").pip_install(*PINS).add_local_file(APP_DIR / "api.py", "/root/app/api.py")
for name in ("store_prep.py", "serving.py", "explain.py", "impact.py"):
    image = image.add_local_file(MODEL_SRC / name, f"/root/src/model/{name}")
image = image.add_local_file(ROOT / "models" / "pipeline.joblib", "/root/models/pipeline.joblib")


@app.function(image=image, secrets=[modal.Secret.from_dict({"FRONTEND_ORIGIN": FRONTEND_ORIGIN})])  # no credentials: only the public CORS origin
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="snap-grocery-exits-api")
def api():
    import sys

    sys.path.insert(0, "/root")
    from app.api import app as web_app  # app/api.py, as copied into the image; it loads the bundle and runs the self-check

    return web_app
