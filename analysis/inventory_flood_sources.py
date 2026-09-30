#!/usr/bin/env python3
"""Inventory official 100-year national-river SHP downloads, without downloading ZIPs.

The public catalogue endpoints and form fields are used by the provider's own
download page. Catalogue coverage is not proof that every place is modelled.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ORIGIN = "https://data.floodmap.go.kr"
GROUPS = {
    "sa-ntn": "권역별 100년 빈도 국가하천 하천범람지도",
    "rv-ntn": "유역별 100년 빈도 국가하천 하천범람지도",
    "adm-ntn": "행정구역별 100년 빈도 국가하천 하천범람지도",
}


def get_page(route: str, title: str, page: int) -> dict:
    url = f"{ORIGIN}/api/shp-file-list/{route}?" + urlencode(
        {"fileDataSetNm": title, "pageNo": page}
    )
    request = Request(url, headers={"User-Agent": "flood-mobility-equity/0.1"})
    with urlopen(request, timeout=25) as response:
        result = json.load(response)
    if not isinstance(result.get("content"), list):
        raise ValueError(f"Unexpected catalogue response for {route}, page {page}")
    return result


def inventory_group(route: str, title: str) -> tuple[dict, list[dict]]:
    first = get_page(route, title, 1)
    pages = [first]
    with ThreadPoolExecutor(max_workers=3) as executor:
        pages.extend(executor.map(
            lambda page: get_page(route, title, page),
            range(2, first["totalPages"] + 1),
        ))
    entries = [item for page in pages for item in page["content"]]
    names = [item["fileEngNm"] for item in entries]
    if len(entries) != first["totalElements"] or len(names) != len(set(names)):
        raise ValueError(f"Incomplete or duplicate catalogue entries: {route}")
    if any(not name.endswith("_100.zip") for name in names):
        raise ValueError(f"Unexpected frequency in {route}")
    rows = [dict(group=route, dataset=title, **entry) for entry in entries]
    summary = {
        "dataset": title,
        "file_count": len(rows),
        "advertised_zip_bytes": sum(row["fileSize"] for row in rows),
        "update_months": sorted({row["infoUpdtYm"] for row in rows}),
    }
    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=(
        Path(__file__).resolve().parents[1] / "data/metadata"
    ))
    args = parser.parse_args()
    summaries, rows = {}, []
    for route, title in GROUPS.items():
        summary, entries = inventory_group(route, title)
        summaries[route] = summary
        rows.extend(entries)
    receipt = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "한강홍수통제소 홍수위험지도 정보제공포털",
        "catalogue_url": ORIGIN + "/main/board/map_data_download",
        "download_endpoint": ORIGIN + "/api/shp/download",
        "download_method": "POST application/x-www-form-urlencoded",
        "download_form_fields": ["fileEngNm", "fileKorNm", "dataNm"],
        "license": "공공누리 제4유형; 파생결과 공개 허용범위 확인 필요",
        "scope": "100년 빈도 국가하천 하천범람지도",
        "status": "catalogue_verified; ZIP contents not acquired or validated",
        "group_summaries": summaries,
        "entries": rows,
        "notes": [
            "Three groups partition related maps differently; do not combine their totals.",
            "Update month is provider metadata, not a common observation date.",
            "Absent catalogue entries do not imply zero flood hazard.",
            "Source covers national-river scenarios, not every flood mechanism.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "flood_100yr_download_inventory.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.out / "flood_100yr_download_inventory.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=[
            "group", "dataset", "fileEngNm", "fileKorNm", "infoUpdtYm", "fileSize"
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
