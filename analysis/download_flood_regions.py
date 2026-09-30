#!/usr/bin/env python3
"""Download the five official 100-year national-river regional SHP archives."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ENDPOINT = "https://data.floodmap.go.kr/api/shp/download"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(entry: dict, target: Path) -> dict:
    size = entry["fileSize"]
    if target.exists() and target.stat().st_size == size:
        return {"file": target.name, "bytes": size, "sha256": digest(target), "cached": True}
    partial = target.with_suffix(".zip.part")
    subprocess.run([
        "curl", "--fail", "--location", "--silent", "--show-error",
        "--retry", "2", "--max-time", "900",
        "--output", str(partial), ENDPOINT,
        "--header", "Content-Type: application/x-www-form-urlencoded",
        "--data-urlencode", f"fileEngNm={entry['fileEngNm']}",
        "--data-urlencode", f"fileKorNm={entry['fileKorNm']}",
        "--data-urlencode", f"dataNm={entry['dataset']}",
    ], check=True)
    got = partial.stat().st_size
    if got != size:
        raise ValueError(f"{target.name}: expected {size} bytes, received {got}")
    with partial.open("rb") as stream:
        if stream.read(4) != b"PK\x03\x04":
            raise ValueError(f"{target.name}: response is not ZIP")
    partial.rename(target)
    return {"file": target.name, "bytes": got, "sha256": digest(target), "cached": False}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=Path("data/metadata/flood_100yr_download_inventory.json"))
    ap.add_argument("--out", type=Path, default=Path("data/raw/flood_regions_100yr"))
    ap.add_argument("--only", help="Region number 1-5 to download first")
    args = ap.parse_args()
    entries = json.loads(args.inventory.read_text(encoding="utf-8"))["entries"]
    selected = [item for item in entries if item["group"] == "sa-ntn"]
    if args.only:
        selected = [item for item in selected if item["fileEngNm"].split("_")[3] == args.only]
    if not selected:
        raise ValueError("No selected regional files")
    args.out.mkdir(parents=True, exist_ok=True)
    receipts = []
    for item in selected:
        receipt = download(item, args.out / item["fileEngNm"])
        receipt["update_month"] = item["infoUpdtYm"]
        receipts.append(receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    (args.out / "download_receipt.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
