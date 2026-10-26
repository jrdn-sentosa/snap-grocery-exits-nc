"""Download and verify data/raw/ from the manifest data/sources.yaml.

  uv run python src/prep/download_raw.py            # fetch what is missing, verify everything
  uv run python src/prep/download_raw.py --check    # verify only, download nothing

For every file listed in data/sources.yaml:
  1. If it exists, its size and SHA-256 must match the manifest. A mismatch is a hard error (the file is
     never overwritten silently; delete it to re-fetch, or fix the manifest if the change is intended).
  2. If it is missing, it is downloaded from the official `url` (unzipping archive members as needed).
     If the official download fails, or serves bytes that do not match the manifest, it is taken from the
     GitHub Release asset named in the manifest (`fallback`, tag data-v1) instead.
  3. Every file is then verified again. Any missing or mismatched file ends the run with a non-zero exit
     and a message saying what to do.

Files with `url: null` (the SNAP file, which FNS blocks for scripts, and the manual QOL export) can only
come from the Release fallback or be placed in data/raw/ by hand following `manual_instructions`.

Other options: --only ID[,ID]  restrict to datasets;  --dest DIR  use another directory than data/raw;
--no-official  skip official URLs;  --fallback-zip PATH  use a local copy of the release asset (offline use).
data/raw/acs/ is not covered here: 00_download_acs.py builds it from the Census API.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
import yaml

from common import RAW, ROOT

SOURCES = ROOT / "data" / "sources.yaml"
HEADERS = {"User-Agent": "snap-grocery-exits-nc/1.0 (academic reproducibility download)"}
CHUNK = 1 << 20


class Problem(Exception):
    """A file could not be obtained or did not match the manifest."""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def check_file(path: Path, entry: dict) -> str | None:
    """None if the file matches the manifest, otherwise a short reason."""
    if not path.exists():
        return "missing"
    size = path.stat().st_size
    if size != entry["size_bytes"]:
        return f"size {size:,} bytes, manifest says {entry['size_bytes']:,}"
    got = sha256_of(path)
    if got != entry["sha256"]:
        return f"SHA-256 {got[:16]}..., manifest says {entry['sha256'][:16]}..."
    return None


def install(src, dest: Path, entry: dict) -> None:
    """Copy a byte stream to dest through a .part file, publishing it only if size and SHA-256 match."""
    part = dest.with_name(dest.name + ".part")
    h, n = hashlib.sha256(), 0
    with open(part, "wb") as out:
        for chunk in iter(lambda: src.read(CHUNK), b""):
            out.write(chunk)
            h.update(chunk)
            n += len(chunk)
    if n != entry["size_bytes"] or h.hexdigest() != entry["sha256"]:
        part.unlink(missing_ok=True)
        raise Problem(f"{dest.name}: received {n:,} bytes with SHA-256 {h.hexdigest()[:16]}..., manifest says "
                      f"{entry['size_bytes']:,} bytes / {entry['sha256'][:16]}...")
    part.replace(dest)


def download(url: str, target: Path) -> None:
    with requests.get(url, headers=HEADERS, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)


def from_official(ds: dict, wanted: list[dict], dest_dir: Path, tmp: Path) -> list[str]:
    """Try the dataset's official URL for the wanted files. Returns messages for anything that failed."""
    payload = tmp / "payload"
    try:
        print(f"  [{ds['id']}] downloading {ds['url'].split('?')[0]}")
        download(ds["url"], payload)
        if ds.get("archive") == "zip":
            with zipfile.ZipFile(payload) as z:
                for e in wanted:
                    with z.open(e["member"]) as src:
                        install(src, dest_dir / e["local"], e)
        else:
            (e,) = wanted
            with open(payload, "rb") as src:
                install(src, dest_dir / e["local"], e)
        return []
    except (requests.RequestException, zipfile.BadZipFile, KeyError, Problem, ValueError) as exc:
        return [f"{type(exc).__name__}: {exc}"]
    finally:
        payload.unlink(missing_ok=True)


def fetch_fallback_zip(cfg: dict, local_zip: str | None, tmp: Path) -> Path:
    if local_zip:
        return Path(local_zip)
    fb = cfg["fallback"]
    url = f"https://github.com/{fb['github_repo']}/releases/download/{fb['release_tag']}/{fb['asset']}"
    target = tmp / fb["asset"]
    print(f"  [fallback] downloading {url}")
    try:
        download(url, target)
        return target
    except requests.RequestException as exc:
        if shutil.which("gh"):  # private repos need an authenticated download
            print(f"  [fallback] plain download failed ({exc}); trying `gh release download`")
            res = subprocess.run(["gh", "release", "download", fb["release_tag"], "--repo", fb["github_repo"],
                                  "--pattern", fb["asset"], "--dir", str(tmp), "--clobber"], capture_output=True, text=True)
            if res.returncode == 0 and target.exists():
                return target
            raise Problem(f"fallback release asset unavailable: {exc}; gh said: {res.stderr.strip()[:300]}") from None
        raise Problem(f"fallback release asset unavailable: {exc} (install gh, or pass --fallback-zip PATH)") from None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify only, download nothing")
    ap.add_argument("--only", help="comma-separated dataset ids")
    ap.add_argument("--dest", default=str(RAW), help="target directory (default data/raw)")
    ap.add_argument("--no-official", action="store_true", help="skip the official URLs, use the fallback only")
    ap.add_argument("--fallback-zip", help="local copy of the release asset zip")
    args = ap.parse_args()

    cfg = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    datasets = [d for d in cfg["datasets"] if only is None or d["id"] in only]
    if only and len(datasets) != len(only):
        raise SystemExit(f"Unknown dataset id in --only; known: {[d['id'] for d in cfg['datasets']]}")

    source_of: dict[str, str] = {}
    mismatched: list[tuple[str, str]] = []
    needs: dict[str, list[dict]] = {}
    for ds in datasets:
        for e in ds["files"]:
            err = check_file(dest_dir / e["local"], e)
            if err is None:
                source_of[e["local"]] = "already present"
            elif err == "missing":
                needs.setdefault(ds["id"], []).append(e)
            else:
                mismatched.append((e["local"], err))

    errors: list[str] = []
    if needs and not args.check:
        by_id = {d["id"]: d for d in datasets}
        with tempfile.TemporaryDirectory(prefix="snap_raw_") as t:
            tmp = Path(t)
            if not args.no_official:
                for ds_id, wanted in list(needs.items()):
                    ds = by_id[ds_id]
                    if not ds.get("url"):
                        continue
                    msgs = from_official(ds, wanted, dest_dir, tmp)
                    for e in wanted:
                        if check_file(dest_dir / e["local"], e) is None:
                            source_of[e["local"]] = "official URL"
                    if msgs:
                        print(f"  [{ds_id}] official download failed: {msgs[0]}")
            still = {i: [e for e in es if e["local"] not in source_of] for i, es in needs.items()}
            still = {i: es for i, es in still.items() if es}
            if still:
                try:
                    zpath = fetch_fallback_zip(cfg, args.fallback_zip, tmp)
                    with zipfile.ZipFile(zpath) as z:
                        names = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
                        for ds_id, es in still.items():
                            for e in es:
                                if e["local"] not in names:
                                    errors.append(f"{e['local']}: not in the fallback zip")
                                    continue
                                try:
                                    with z.open(names[e["local"]]) as src:
                                        install(src, dest_dir / e["local"], e)
                                    source_of[e["local"]] = "GitHub Release fallback"
                                except Problem as exc:
                                    errors.append(str(exc))
                except (Problem, zipfile.BadZipFile) as exc:
                    errors.append(str(exc))

    # final verification of every file in scope
    rows, bad = [], list(mismatched)
    for ds in datasets:
        for e in ds["files"]:
            err = check_file(dest_dir / e["local"], e)
            if err is None:
                rows.append((e["local"], source_of.get(e["local"], "already present")))
            elif err == "missing":
                hint = ds.get("manual_instructions") or "rerun without --check, or place the file by hand"
                bad.append((e["local"], f"MISSING. {hint}"))
            elif (e["local"], err) not in bad:
                bad.append((e["local"], err))

    if rows:
        print("\nVerified (size + SHA-256 match data/sources.yaml):")
    for name, how in rows:
        print(f"  OK   {name}  [{how}]")
    extra = sorted(p.name for p in dest_dir.iterdir() if p.is_file() and p.name != ".gitkeep") if dest_dir.exists() else []
    known = {e["local"] for d in cfg["datasets"] for e in d["files"]}
    for name in extra:
        if name not in known and not name.endswith(".part"):
            print(f"  NOTE {name} is in {dest_dir.name}/ but not in data/sources.yaml (ignored)")
    if errors or bad:
        print("\nFAILED:", file=sys.stderr)
        for name, why in bad:
            print(f"  {name}: {why}", file=sys.stderr)
        for msg in errors:
            print(f"  {msg}", file=sys.stderr)
        if mismatched:
            print("  A file that exists but does not match the manifest is never overwritten. If the new file is the"
                  " intended one, update data/sources.yaml; otherwise delete it and rerun to re-fetch.", file=sys.stderr)
        return 1
    print(f"\nAll {len(rows)} files verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
