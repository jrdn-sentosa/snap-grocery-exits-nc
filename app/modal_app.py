"""Deploy the SNAP grocery exits Streamlit dashboard (app/streamlit_app.py) on Modal.

Same pattern as the iris-eda-app homework. The dashboard reads from Supabase with the PUBLISHABLE key only; the
Modal secret holds just SUPABASE_URL and SUPABASE_KEY. The service-role key used by src/prep/06_load_supabase.py to
write the tables is never put in Modal (and the app refuses to run if SUPABASE_KEY is a secret / service-role key).

Setup (one-time), from the repository root:
    uv run modal setup                                  # authenticate this machine
    uv run modal secret create snap-supabase SUPABASE_URL=https://<project>.supabase.co SUPABASE_KEY=<publishable key>

Deploy:
    uv run modal deploy app/modal_app.py
"""

import subprocess
from pathlib import Path

import modal

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent

app = modal.App("snap-grocery-exits-nc")

image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install(
        "streamlit>=1.66.1",
        "pandas>=3.1.0",
        "plotly>=7.1.0",
        "supabase>=2.33.0",
    )
    .add_local_file(APP_DIR / "streamlit_app.py", "/root/app.py")
    .add_local_file(ROOT / ".streamlit" / "config.toml", "/root/.streamlit/config.toml")
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("snap-supabase")],
    min_containers=1,
)
@modal.concurrent(max_inputs=100)
@modal.web_server(8000, startup_timeout=60)
def run():
    subprocess.Popen(
        "streamlit run /root/app.py "
        "--server.port 8000 --server.address 0.0.0.0 "
        "--server.headless true "
        "--server.enableCORS false --server.enableXsrfProtection false",
        shell=True,
        cwd="/root",
    )
