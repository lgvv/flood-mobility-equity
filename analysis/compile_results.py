#!/usr/bin/env python3
"""Reconcile the final national and regional outputs into review tables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

CASES = [("11160", "서울 강서구"), ("38070", "경남 김해시"), ("38520", "경남 함안군")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()
    n = pd.read_csv(args.out / "tables/national_district_exposure.csv", dtype={"SIGUNGU_CD": str})
    q = json.loads((args.out / "metadata/national_exposure_qa.json").read_text())
    assert len(n) == q["district_count"] == 252
    assert int(n.exposed_stops.sum()) == q["total_exposed_stops"]
    assert int(n.exposed_medical_sites.sum()) == q["total_exposed_selected_medical_sites"]
    assert int(n.valid_stops.sum()) == q["stops"]["valid_rows"] - q["stop_district_join"]["district_unmatched"]
    assert int(n.exposed_stops.gt(0).sum()) == q["districts_with_exposed_stops"]
    rows = []
    for code, name in CASES:
        row = n.loc[n.SIGUNGU_CD.eq(code)]
        assert len(row) == 1
        row = row.iloc[0]
        case = json.loads((args.out / "metadata" / f"case_{code}_access.json").read_text())
        origins = pd.read_csv(args.out / "tables" / f"case_{code}_origin_access.csv")
        repairs = pd.read_csv(args.out / "tables" / f"case_{code}_restoration.csv")
        assert len(origins) == case["accepted_origins"]
        assert int(origins.population_2024.sum()) == case["accepted_origin_population"]
        assert case["origin_population_coverage"] >= .9
        assert case["baseline_connected_population_coverage"] >= .9
        assert len(repairs) == 10
        assert (repairs.restored_length_m <= repairs.budget_m + .001).all()
        before = case["baseline"]
        after = case["road_closure"]
        rows.append({
            "district_code": code, "district": name,
            "valid_stops": int(row.valid_stops), "exposed_stops": int(row.exposed_stops),
            "stop_exposure_percent": float(row.stop_exposure_rate * 100),
            "selected_medical_sites": int(row.selected_medical_sites),
            "exposed_medical_sites": int(row.exposed_medical_sites),
            "dong_origins": case["accepted_origins"],
            "represented_population": case["accepted_origin_population"],
            "baseline_connected_population_coverage_percent": case["baseline_connected_population_coverage"]*100,
            "hospitals_in_buffer": case["accepted_hospitals"],
            "baseline_20km_population": before["within_20km_population"],
            "closure_20km_population": after["within_20km_population"],
            "loss_20km_population": before["within_20km_population"]-after["within_20km_population"],
            "closure_major_disruption_population": after["major_disruption_population"],
            "closure_major_disruption_older_lower": after["major_disruption_older_lower"],
            "closed_physical_road_km": case["closed_physical_road_length_m"]/1000,
            "bridge_intersecting_edges_kept": case["flood_intersecting_bridge_edges_kept"],
        })
    result = pd.DataFrame(rows)
    result.to_csv(args.out / "tables/case_comparison.csv", index=False, encoding="utf-8-sig")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
