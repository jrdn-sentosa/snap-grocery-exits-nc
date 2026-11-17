"""Deploy the D4 prediction API (app/api.py) on Modal as an ASGI app.

Same pattern as HW4: the FastAPI app lives in its own module (app/api.py) and this file only builds the image
and returns that app from an @modal.asgi_app() function. It is a separate Modal app from the Streamlit
dashboard (app/modal_app.py) on purpose: the API reads no database, so it has **no secrets attached**, and it
can be deployed without the snap-supabase secret existing.

Setup (one-time): uv run python -m modal setup
Deploy, from the repository root:
    uv run python -m modal deploy app/modal_api.py
URL: https://<modal-workspace>--snap-grocery-exits-api.<region>.modal.run (printed by the deploy; ours:
https://hgmccall--snap-grocery-exits-api.us-east.modal.run). Paths: /docs, /health, /model-info, POST /predict.

The image contains api.py, src/model/transformers.py (the pickled Pipeline imports it) and the committed
models/exit_model.joblib + .json, at the same relative paths as in the repository. scikit-learn, pandas, numpy
and joblib are pinned to the versions recorded in models/exit_model.json, i.e. the versions that fit the
model, so the deployed predictions match local ones exactly (src/model/05_verify_api.py checks this).
"""

import json
from importlib.metadata import version
from pathlib import Path

import modal

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent

app = modal.App("snap-grocery-exits-api")

if modal.is_local():
    # Read only where the repository exists (deploy time); inside the container the image is already built.
    FIT_VERSIONS = json.loads((ROOT / "models" / "exit_model.json").read_text(encoding="utf-8"))["versions"]
    PINS = [f"{pkg}=={FIT_VERSIONS[pkg]}" for pkg in ("scikit-learn", "pandas", "numpy", "joblib")]
    PINS += [f"fastapi[standard]=={version('fastapi')}", f"pydantic=={version('pydantic')}"]
else:
    PINS = []

image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install(*PINS)
    .add_local_file(APP_DIR / "api.py", "/root/app/api.py")
    .add_local_file(ROOT / "src" / "model" / "transformers.py", "/root/src/model/transformers.py")
    .add_local_file(ROOT / "models" / "exit_model.joblib", "/root/models/exit_model.joblib")
    .add_local_file(ROOT / "models" / "exit_model.json", "/root/models/exit_model.json")
)


@app.function(image=image)  # no secrets: the API needs no credentials
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="snap-grocery-exits-api")
def api():
    import sys

    sys.path.insert(0, "/root")
    from app.api import app as web_app  # app/api.py, as copied into the image

    return web_app
