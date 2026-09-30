#!/usr/bin/env python3
"""National 100-year national-river flood exposure of stops and medical sites."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def points(frame: pd.DataFrame, lon: str, lat: str) -> gpd.GeoDataFrame:
    frame = frame.reset_index(drop=True)
    return gpd.GeoDataFrame(
        frame, geometry=gpd.points_from_xy(frame[lon], frame[lat]), crs="EPSG:4326"
    ).to_crs("EPSG:5186")


def load_stops(path: Path) -> tuple[gpd.GeoDataFrame, dict]:
    raw = pd.read_csv(path, encoding="cp949", dtype=str)
    latitude = pd.to_numeric(raw["위도"], errors="coerce")
    longitude = pd.to_numeric(raw["경도"], errors="coerce")
    swapped = latitude.gt(90) & longitude.between(30, 45)
    raw["latitude"] = latitude.where(~swapped, longitude)
    raw["longitude"] = longitude.where(~swapped, latitude)
    valid = raw.latitude.between(33, 39) & raw.longitude.between(124, 132)
    clean = raw.loc[valid, ["정류장번호", "도시명", "latitude", "longitude"]].copy()
    if clean["정류장번호"].duplicated().any():
        raise ValueError("Bus stop IDs are not unique")
    return points(clean, "longitude", "latitude"), {
        "raw_rows": len(raw), "corrected_swaps": int(swapped.sum()),
        "invalid_coordinates": int((~valid).sum()), "valid_rows": len(clean),
        "sha256": sha256(path),
    }


def assign_district(frame: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    joined = gpd.sjoin(frame, districts[["SIGUNGU_CD", "geometry"]], how="left", predicate="within")
    duplicates = int(joined.index.duplicated().sum())
    if duplicates:
        raise ValueError(f"{duplicates} points were assigned to multiple districts")
    joined = joined.drop(columns="index_right")
    return joined, {
        "points": len(frame), "district_matched": int(joined.SIGUNGU_CD.notna().sum()),
        "district_unmatched": int(joined.SIGUNGU_CD.isna().sum()),
    }


def intersect_flood(stops: gpd.GeoDataFrame, facilities: gpd.GeoDataFrame, directory: Path) -> tuple[list, dict]:
    stop_flags = np.zeros(len(stops), dtype=bool)
    facility_flags = np.zeros(len(facilities), dtype=bool)
    receipt = []
    for archive in sorted(directory.glob("RFM_SAREA_NTN_*_100.zip")):
        flood = gpd.read_file(archive)
        if flood.crs is None or set(flood["FLDLV_FREQ"].astype(str)) != {"100"}:
            raise ValueError(f"{archive.name}: invalid CRS or frequency")
        if not flood.geometry.is_valid.all():
            raise ValueError(f"{archive.name}: invalid geometry")
        if flood.crs != stops.crs:
            flood = flood.to_crs(stops.crs)
        # Regional files contain only five enormous MultiPolygons. Their
        # bounding boxes overlap most points and make direct joins very slow.
        # Index individual polygon parts while preserving exact intersections.
        parts = shapely.get_parts(flood.geometry.array)
        tree = shapely.STRtree(parts)
        print(f"{archive.name}: indexed {len(parts)} polygon parts", flush=True)
        for sites, flags in [(stops, stop_flags), (facilities, facility_flags)]:
            pairs = tree.query(sites.geometry.array, predicate="intersects")
            flags[np.unique(pairs[0])] = True
        receipt.append({
            "archive": archive.name, "sha256": sha256(archive), "polygons": len(flood),
            "crs": str(flood.crs), "frequency": "100",
            "invalid_geometries": 0, "polygon_parts": len(parts),
            "flooded_stops_cumulative": int(stop_flags.sum()),
            "flooded_facilities_cumulative": int(facility_flags.sum()),
        })
        print(json.dumps(receipt[-1], ensure_ascii=False), flush=True)
        del flood, parts, tree
    if len(receipt) != 5:
        raise ValueError(f"Expected five regional archives; found {len(receipt)}")
    return (stop_flags, facility_flags), {"regions": receipt}


def load_population(total_file: Path, age_file: Path) -> pd.DataFrame:
    total = pd.read_csv(total_file, encoding="cp949", dtype=str)
    age = pd.read_csv(age_file, encoding="cp949", dtype=str)
    total = total[(total["행정구역코드"].str.len() == 5) & (total["통계항목"] == "to_in_001")]
    total = total[["행정구역코드", "통계값"]].rename(columns={"행정구역코드": "SIGUNGU_CD", "통계값": "population_2024"})
    total["population_2024"] = pd.to_numeric(total.population_2024, errors="coerce")
    old = age[(age["행정구역코드"].str.len() == 5) & age["통계항목"].isin(
        [f"in_age_{i:03d}" for i in range(14, 22)]
    )].copy()
    old["known"] = pd.to_numeric(old["통계값"], errors="coerce")
    agg = old.groupby("행정구역코드").agg(
        older_65_lower=("known", "sum"),
        suppressed_older_cells=("known", lambda s: int(s.isna().sum())),
        older_age_cells=("known", "size"),
    ).reset_index().rename(columns={"행정구역코드": "SIGUNGU_CD"})
    agg["older_65_upper"] = agg.older_65_lower + 4 * agg.suppressed_older_cells
    result = total.merge(agg, on="SIGUNGU_CD", how="outer", validate="one_to_one")
    result["older_share_lower"] = result.older_65_lower / result.population_2024
    result["older_share_upper"] = result.older_65_upper / result.population_2024
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--processed", type=Path, default=Path("data/processed"))
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()
    districts = gpd.read_file(args.raw / "sgis_selected/bnd_sigungu_00_2025_2Q.shp")
    if districts.crs != "EPSG:5179" or districts.SIGUNGU_CD.duplicated().any():
        raise ValueError("Invalid district geometry or non-unique codes")
    districts = districts.to_crs("EPSG:5186")
    stops, stop_qa = load_stops(args.raw / "bus_stops_20251031_euckr.csv")
    facilities_raw = pd.read_csv(args.processed / "hira_medical_sites_202606.csv", dtype={"facility_id": str})
    facilities = points(facilities_raw, "longitude", "latitude")
    stops, stop_join_qa = assign_district(stops, districts)
    facilities, facility_join_qa = assign_district(facilities, districts)
    (stop_flags, facility_flags), flood_qa = intersect_flood(
        stops, facilities, args.raw / "flood_regions_100yr"
    )
    stops["exposed"] = stop_flags
    facilities["exposed"] = facility_flags
    pop = load_population(
        args.raw / "sgis_selected/2025년기준_2024년_인구총괄(총인구).csv",
        args.raw / "sgis_selected/2025년기준_2024년_성연령별인구.csv",
    )
    stop_summary = stops.groupby("SIGUNGU_CD", dropna=True).agg(
        valid_stops=("정류장번호", "nunique"), exposed_stops=("exposed", "sum")
    )
    types = ["상급종합", "종합병원", "병원", "의원", "보건의료원", "약국"]
    selected = facilities[facilities.facility_type.isin(types)]
    facility_summary = selected.groupby("SIGUNGU_CD", dropna=True).agg(
        selected_medical_sites=("facility_id", "nunique"),
        exposed_medical_sites=("exposed", "sum"),
    )
    for typ in types:
        subset = facilities[facilities.facility_type.eq(typ)]
        counts = subset.groupby("SIGUNGU_CD", dropna=True).agg(
            **{f"{typ}_sites": ("facility_id", "nunique"), f"{typ}_exposed": ("exposed", "sum")}
        )
        facility_summary = facility_summary.join(counts, how="outer")
    frame = districts.drop(columns="geometry").merge(pop, on="SIGUNGU_CD", how="left", validate="one_to_one")
    frame = frame.join(stop_summary, on="SIGUNGU_CD").join(facility_summary, on="SIGUNGU_CD")
    count_cols = ["valid_stops", "exposed_stops", "selected_medical_sites", "exposed_medical_sites"] + [
        f"{typ}_{suffix}" for typ in types for suffix in ("sites", "exposed")
    ]
    frame[count_cols] = frame[count_cols].fillna(0).astype(int)
    frame["stop_exposure_rate"] = frame.exposed_stops.div(frame.valid_stops.replace(0, np.nan))
    frame["selected_medical_exposure_rate"] = frame.exposed_medical_sites.div(
        frame.selected_medical_sites.replace(0, np.nan)
    )
    frame["urban_type"] = np.where(
        frame.SIGUNGU_CD.str[:2].isin(["11", "21", "22", "23", "24", "25", "26", "29"]),
        "metropolitan", np.where(frame.SIGUNGU_NM.str.endswith("군"), "county", "city")
    )
    frame["flood_scenario"] = "100-year national-river map (five regional files)"
    frame["flood_hazard_zero_means"] = "no intersection with mapped national-river scenario"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "tables").mkdir(exist_ok=True)
    (args.out / "metadata").mkdir(exist_ok=True)
    args.processed.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out / "tables/national_district_exposure.csv", index=False, encoding="utf-8-sig")
    stops.drop(columns="geometry").to_csv(args.processed / "bus_stops_with_exposure.csv", index=False, encoding="utf-8-sig")
    facilities.drop(columns="geometry").to_csv(args.processed / "medical_sites_with_exposure.csv", index=False, encoding="utf-8-sig")
    summary = {
        "district_count": len(frame),
        "stops": stop_qa,
        "stop_district_join": stop_join_qa,
        "facility_district_join": facility_join_qa,
        "flood": flood_qa,
        "total_exposed_stops": int(stop_flags.sum()),
        "total_exposed_facilities_all_types": int(facility_flags.sum()),
        "total_exposed_selected_medical_sites": int(selected.exposed.sum()),
        "districts_with_exposed_stops": int(frame.exposed_stops.gt(0).sum()),
        "districts_with_suppressed_older_cells": int(frame.suppressed_older_cells.gt(0).sum()),
        "population_source": "SGIS 2024 census estimates, 2025 Q2 boundaries; suppressed age cells bounded 0-4",
        "interpretation": "Exposure is point intersection with a modelled national-river flood polygon, not observed closure or patient harm.",
    }
    (args.out / "metadata/national_exposure_qa.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k:v for k,v in summary.items() if k!="flood"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
