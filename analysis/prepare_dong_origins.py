#!/usr/bin/env python3
"""Create administrative-dong origins with bounded 65+ counts from SGIS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw/sgis_selected"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    args = ap.parse_args()
    boundary = gpd.read_file(args.raw / "bnd_dong_00_2025_2Q.shp")
    total = pd.read_csv(args.raw / "2025년기준_2024년_인구총괄(총인구).csv", encoding="cp949", dtype=str)
    age = pd.read_csv(args.raw / "2025년기준_2024년_성연령별인구.csv", encoding="cp949", dtype=str)
    total = total[(total["행정구역코드"].str.len() == 8) & total["통계항목"].eq("to_in_001")]
    total = total[["행정구역코드", "통계값"]].rename(columns={"행정구역코드": "ADM_CD", "통계값": "population_2024"})
    total["population_2024"] = pd.to_numeric(total.population_2024, errors="coerce")
    old = age[(age["행정구역코드"].str.len() == 8) & age["통계항목"].isin(
        [f"in_age_{i:03d}" for i in range(14, 22)]
    )].copy()
    old["known"] = pd.to_numeric(old["통계값"], errors="coerce")
    agg = old.groupby("행정구역코드").agg(
        older_65_lower=("known", "sum"),
        suppressed_older_cells=("known", lambda s: int(s.isna().sum())),
        older_age_cells=("known", "size"),
    ).reset_index().rename(columns={"행정구역코드": "ADM_CD"})
    agg["older_65_upper"] = agg.older_65_lower + 4 * agg.suppressed_older_cells
    origin = boundary.merge(total, on="ADM_CD", how="left", validate="one_to_one")
    origin = origin.merge(agg, on="ADM_CD", how="left", validate="one_to_one")
    representative = origin.geometry.representative_point().to_crs("EPSG:4326")
    origin["longitude"] = representative.x
    origin["latitude"] = representative.y
    origin["SIGUNGU_CD"] = origin.ADM_CD.str[:5]
    origin["older_share_lower"] = origin.older_65_lower / origin.population_2024
    origin["older_share_upper"] = origin.older_65_upper / origin.population_2024
    args.out.mkdir(parents=True, exist_ok=True)
    origin.drop(columns="geometry").to_csv(args.out / "sgis_dong_origins_2024.csv", index=False, encoding="utf-8-sig")
    receipt = {
        "boundary_dong_count": len(boundary),
        "population_joined": int(origin.population_2024.notna().sum()),
        "elderly_age_joined": int(origin.older_65_lower.notna().sum()),
        "suppressed_elderly_age_dongs": int(origin.suppressed_older_cells.gt(0).sum()),
        "zero_or_missing_population_dongs": int(origin.population_2024.fillna(0).le(0).sum()),
        "origin_method": "polygon representative point, not a residential address or population-weighted centroid",
        "limitation": "Published counts are 2024 census values joined to 2025 Q2 boundaries; age cells under five are bounded 0-4.",
    }
    (args.out / "sgis_dong_origins_qa.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
