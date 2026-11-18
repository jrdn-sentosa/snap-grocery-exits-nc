"""Verify the D4 API, locally and deployed, against the fixed examples in docs/model_examples_d4.json.

    uv run --group api python app/verify_api.py
    uv run --group api python app/verify_api.py --local-url http://127.0.0.1:8000   # use a running server

For each target (a local server, which this script starts on a free port unless --local-url is given, and the deployed Modal URL):
- GET /health: the startup self-check must have passed;
- POST /predict with all 9 `examples`: raw_score, probability, impact and priority must match `expected` within 1e-9, and tier and
  reasons (feature and text, in order; effect within 1e-9) must match exactly;
- POST each of the 8 `invalid_examples` (as a one-record list): the status must be 422 (never 500), and the error must name the field
  in `expected_error.loc`.
A third check starts a throwaway local server with MODEL_DIR pointing at an empty temporary folder (the deployed app is never touched):
/health must report self_check_passed = false and POST /predict with ex1 must return 503 (never 500).
Writes docs/api_verification.md and exits non-zero if any check fails. Only the fixed examples are sent; no data file is read.
"""

import argparse
import json
import socket
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((ROOT / "docs" / "model_examples_d4.json").read_text(encoding="utf-8"))
DEPLOYED_URL = "https://hgmccall--snap-grocery-exits-api.us-east.modal.run"
OUT = ROOT / "docs" / "api_verification.md"
TOL = 1e-9
NUMERIC = ("raw_score", "probability", "impact", "priority")


def request_rows(examples):
    return [{"year": e["cohort_year"], **e["inputs"], **e["context"]} for e in examples]


def check_target(url: str) -> dict:
    res = {"url": url, "failures": []}
    fail = res["failures"].append

    health = requests.get(f"{url}/health", timeout=180).json()  # the first call may wake a cold container
    res["health"] = health
    if not health.get("self_check_passed"):
        fail(f"self-check not passed: {health.get('problems')}")
    info = requests.get(f"{url}/model-info", timeout=60).json()
    res["sklearn"] = info.get("metadata", {}).get("sklearn_version")

    ex = EXAMPLES["examples"]
    r = requests.post(f"{url}/predict", json=request_rows(ex), timeout=120)
    res["examples"] = []
    if r.status_code != 200:
        fail(f"POST /predict with the 9 examples returned {r.status_code}: {r.text[:300]}")
    else:
        for e, got in zip(ex, r.json()["predictions"]):
            want = e["expected"]
            diffs = {k: abs(got[k] - want[k]) for k in NUMERIC}
            reasons_ok = (len(got["reasons"]) == len(want["reasons"]) and all(
                g["feature"] == w["feature"] and g["text"] == w["text"] and abs(g["effect"] - w["effect"]) <= TOL
                for g, w in zip(got["reasons"], want["reasons"])))
            ok = max(diffs.values()) <= TOL and got["tier"] == want["tier"] and reasons_ok
            res["examples"].append({"id": e["id"], "tier": got["tier"], "tier_expected": want["tier"], "max_diff": max(diffs.values()),
                                    "n_reasons": len(got["reasons"]), "reasons_ok": reasons_ok, "ok": ok, "probability": got["probability"]})
            if not ok:
                fail(f"{e['id']}: diffs {diffs}, tier {got['tier']} vs {want['tier']}, reasons match {reasons_ok}")

    res["invalid"] = []
    for b in EXAMPLES["invalid_examples"]:
        r = requests.post(f"{url}/predict", json=[b["payload"]], timeout=60)
        field = b["expected_error"]["loc"][-1]
        locs = [d.get("loc", []) for d in r.json().get("detail", [])] if r.headers.get("content-type", "").startswith("application/json") else []
        named = any(field in loc for loc in locs)
        ok = r.status_code == 422 and named
        res["invalid"].append({"id": b["id"], "case": b["description"], "status": r.status_code, "field": field, "named": named,
                               "locs": locs, "ok": ok})
        if not ok:
            fail(f"{b['id']}: status {r.status_code}, error locations {locs} (expected 422 naming {field!r})")
    return res


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_local(env: dict | None = None):
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT,
                            env={**os.environ, **(env or {})}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            requests.get(f"{url}/health", timeout=1)
            return proc, url
        except requests.ConnectionError:
            if proc.poll() is not None:
                raise SystemExit("local server exited during startup (run it by hand to see why)")
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("local server did not start within 60 s")


def check_unavailable() -> dict:
    """Local server whose MODEL_DIR is an empty folder: the bundle cannot load, so the self-check fails and /predict must answer 503."""
    res = {"failures": []}
    fail = res["failures"].append
    with tempfile.TemporaryDirectory() as empty:
        proc, url = start_local({"MODEL_DIR": empty})
        try:
            health = requests.get(f"{url}/health", timeout=30).json()
            ex1 = request_rows([next(e for e in EXAMPLES["examples"] if e["id"] == "ex1")])
            r = requests.post(f"{url}/predict", json=ex1, timeout=30)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    res.update(url=url, health=health, status=r.status_code, body=r.text[:300])
    if health.get("self_check_passed") is not False:
        fail(f"/health self_check_passed = {health.get('self_check_passed')!r}, expected false")
    if r.status_code != 503:
        fail(f"POST /predict with ex1 returned {r.status_code}, expected 503")
    return res


def write_report(results: list[dict], all_ok: bool, unavailable: dict):
    L = ["# D4 API verification", "",
         "Generated by `app/verify_api.py`; do not edit by hand. Inputs are the fixed examples in `docs/model_examples_d4.json` "
         "(9 scored examples, 8 invalid requests); no data file is read.", "",
         f"- Checked: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
         f"- **Overall: {'PASS' if all_ok else 'FAIL'}**", ""]
    for name, r in zip(("Local", "Deployed"), results):
        n_ex = sum(x["ok"] for x in r["examples"])
        n_bad = sum(x["ok"] for x in r["invalid"])
        L += [f"## {name}: {r['url']}", "",
              f"- `/health`: self-check passed = {r['health'].get('self_check_passed')}; problems: {r['health'].get('problems') or 'none'}",
              f"- scikit-learn (bundle metadata): {r['sklearn']}",
              f"- Examples: **{n_ex} of {len(EXAMPLES['examples'])} match** (numbers within {TOL:g}; tier and reasons exact)",
              f"- Invalid requests: **{n_bad} of {len(EXAMPLES['invalid_examples'])} return 422 naming the field**",
              "", "| example | probability | tier (expected) | reasons | max abs diff (raw score, probability, impact, priority) | match |",
              "|---|---|---|---|---|---|"]
        for x in r["examples"]:
            L.append(f"| {x['id']} | {x['probability']:.6f} | {x['tier']} ({x['tier_expected']}) | {x['n_reasons']} "
                     f"{'same' if x['reasons_ok'] else 'DIFFERENT'} | {x['max_diff']:.1e} | {'yes' if x['ok'] else 'NO'} |")
        L += ["", "| invalid | case | status | error points at | ok |", "|---|---|---|---|---|"]
        for x in r["invalid"]:
            where = "; ".join(".".join(str(p) for p in loc) for loc in x["locs"]) or "-"
            L.append(f"| {x['id']} | {x['case']} | {x['status']} | `{where}` | {'yes' if x['ok'] else 'NO'} |")
        if r["failures"]:
            L += ["", "Failures:", ""] + [f"- {f}" for f in r["failures"]]
        L.append("")
    u = unavailable
    L += [f"## Model unavailable (local, empty MODEL_DIR): {u['url']}", "",
          "A throwaway local server started with `MODEL_DIR` pointing at an empty temporary folder; the deployed app is not touched.", "",
          f"- `/health`: self-check passed = {u['health'].get('self_check_passed')} (expected False); status = {u['health'].get('status')}",
          f"- problems: {u['health'].get('problems')}",
          f"- `POST /predict` with ex1: HTTP **{u['status']}** (expected 503, never 500)",
          f"- Result: **{'PASS' if not u['failures'] else 'FAIL'}**", ""]
    if u["failures"]:
        L += ["Failures:", ""] + [f"- {f}" for f in u["failures"]] + [""]
    OUT.write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-url", help="use a running local server instead of starting one")
    ap.add_argument("--deployed-url", default=DEPLOYED_URL)
    args = ap.parse_args()

    proc = None
    if args.local_url:
        local_url = args.local_url.rstrip("/")
    else:
        proc, local_url = start_local()
    try:
        results = [check_target(local_url), check_target(args.deployed_url.rstrip("/"))]
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
    unavailable = check_unavailable()
    all_ok = not any(r["failures"] for r in results) and not unavailable["failures"]
    write_report(results, all_ok, unavailable)
    for name, r in zip(("local", "deployed"), results):
        print(f"{name:8s} {r['url']}: examples {sum(x['ok'] for x in r['examples'])}/9, invalid->422 {sum(x['ok'] for x in r['invalid'])}/8"
              + ("" if not r["failures"] else f"  FAILURES: {r['failures']}"))
    print(f"unavailable {unavailable['url']}: /health self_check_passed={unavailable['health'].get('self_check_passed')}, "
          f"POST /predict -> {unavailable['status']}" + ("" if not unavailable["failures"] else f"  FAILURES: {unavailable['failures']}"))
    print(f"{'PASS' if all_ok else 'FAIL'}; wrote {OUT.relative_to(ROOT)}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
