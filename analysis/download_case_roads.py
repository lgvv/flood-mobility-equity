#!/usr/bin/env python3
"""Acquire a drivable OSM street graph around a selected district."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import osmnx as ox


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", required=True)
    ap.add_argument("--buffer-m", type=float, default=3000)
    ap.add_argument("--boundary", type=Path, default=Path("data/raw/sgis_selected/bnd_sigungu_00_2025_2Q.shp"))
    ap.add_argument("--out", type=Path, default=Path("data/raw/osm_roads"))
    args = ap.parse_args()
    selected = gpd.read_file(args.boundary)
    selected = selected.loc[selected.SIGUNGU_CD.eq(args.district)]
    if len(selected) != 1:
        raise ValueError(f"Could not uniquely find district {args.district}")
    query_polygon = selected.to_crs("EPSG:5179").geometry.iloc[0].buffer(args.buffer_m)
    query_polygon = gpd.GeoSeries([query_polygon], crs="EPSG:5179").to_crs("EPSG:4326").iloc[0]
    ox.settings.use_cache = True
    ox.settings.cache_folder = "data/raw/osm_cache"
    ox.settings.timeout = 180
    ox.settings.log_console = True
    print(f"Requesting OSM drive graph for {args.district}, buffer {args.buffer_m} m", flush=True)
    graph = ox.graph.graph_from_polygon(
        query_polygon, network_type="drive", simplify=True, retain_all=True
    )
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.district}_drive_{int(args.buffer_m)}m.graphml"
    ox.io.save_graphml(graph, filepath=path)
    receipt = {
        "district_code": args.district,
        "buffer_m": args.buffer_m,
        "source": "OpenStreetMap contributors via OSMnx/Overpass API",
        "graphml": str(path),
        "sha256": sha256(path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "crs": str(graph.graph.get("crs")),
        "warning": "OSM topology, one-way tags, and bridge tags require coverage checks before accessibility claims.",
    }
    (args.out / f"{args.district}_drive_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
