"""Refresh docling.rs model assets, downloading only the ones that actually changed.

Usage:
    uv run python experiments/refresh_models.py
    uv run python experiments/refresh_models.py --dry-run

The upstream cache has no version stamp and its assets live under a fixed release
tag, so the package version says nothing about whether a model moved. One HEAD per
asset answers it: size alone when no stamp exists, size and ETag once one does.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from docling_rs.models import BASE_URL, _ENRICH, _OPTIONAL, _REQUIRED, cache_dir

STAMP = "etags.json"


def head(url):
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request) as response:
        return int(response.headers.get("content-length") or 0), response.headers.get("etag", "")


def verdict(local, remote_size, remote_etag, known_etag):
    if not local.exists():
        return "missing"
    if local.stat().st_size != remote_size:
        return "size"
    if known_etag and known_etag != remote_etag:
        return "etag"
    return ""


def fetch(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".download")
    try:
        with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        tmp.rename(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = cache_dir()
    stamp_path = root / STAMP
    etags = json.loads(stamp_path.read_text()) if stamp_path.exists() else {}
    assets = {**_REQUIRED, **_OPTIONAL, **_ENRICH}

    print(f"docling.rs models at {root}")
    fetched = 0
    for name, rel in assets.items():
        url, local = f"{BASE_URL}/{name}", root / rel
        try:
            size, etag = head(url)
        except Exception as exc:
            print(f"  {rel:<40} unreachable ({type(exc).__name__}) — left alone")
            continue
        why = verdict(local, size, etag, etags.get(rel))
        if not why:
            print(f"  {rel:<40} {size:>12,}  skip")
            continue
        print(f"  {rel:<40} {size:>12,}  FETCH ({why})")
        if not args.dry_run:
            fetch(url, local)
            etags[rel] = etag
            fetched += 1

    if not args.dry_run:
        stamp_path.write_text(json.dumps(etags, indent=1, sort_keys=True))
    print(f"{fetched} of {len(assets)} fetched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
