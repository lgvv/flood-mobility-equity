#!/usr/bin/env python3
"""Road-distance stress test and two restoration heuristics for a selected district."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import shapely

HOSPITAL_TYPES = {"상급종합", "종합병원", "병원"}
DISTANCE_THRESHOLD_M = 20_000
SNAP_LIMIT_M = 1_500
REPAIR_FRACTIONS = (0.01, 0.02, 0.05, 0.10, 0.20)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def near_nodes(graph, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    points = gpd.GeoSeries(
        gpd.points_from_xy(frame.longitude, frame.latitude), crs="EPSG:4326"
    ).to_crs(graph.graph["crs"])
    nodes, distances = ox.distance.nearest_nodes(
        graph, points.x.to_numpy(), points.y.to_numpy(), return_dist=True
    )
    return np.asarray(nodes), np.asarray(distances)


def flood_closed_edges(graph, archives: Path) -> tuple[set, set, list]:
    edges = ox.convert.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    raw_flags = np.zeros(len(edges), dtype=bool)
    inventory = []
    for archive in sorted(archives.glob("RFM_SAREA_NTN_*_100.zip")):
        polygons = gpd.read_file(archive)
        if set(polygons.FLDLV_FREQ.astype(str)) != {"100"} or not polygons.geometry.is_valid.all():
            raise ValueError(f"Invalid flood layer {archive}")
        if polygons.crs != edges.crs:
            polygons = polygons.to_crs(edges.crs)
        parts = shapely.get_parts(polygons.geometry.array)
        index = shapely.STRtree(parts)
        pairs = index.query(edges.geometry.array, predicate="intersects")
        raw_flags[np.unique(pairs[0])] = True
        inventory.append({
            "file": archive.name, "sha256": sha256(archive),
            "parts": len(parts), "cumulative_intersecting_directed_edges": int(raw_flags.sum())
        })
        print(json.dumps(inventory[-1]), flush=True)
        del polygons, parts, index
    if len(inventory) != 5:
        raise ValueError("Five national-river flood archives are required")
    intersected = set(edges.index[raw_flags].tolist())
    bridge_edges = {
        key for key in intersected
        if str(graph.get_edge_data(*key).get("bridge", "no")).lower() not in {"no", "none", "nan", ""}
    }
    closed = intersected - bridge_edges
    return closed, bridge_edges, inventory


def distance_map(graph, destination_nodes: set) -> tuple[dict, dict]:
    if not destination_nodes:
        return {}, {}
    distances, paths = nx.multi_source_dijkstra(
        graph.reverse(copy=False), sources=destination_nodes, weight="length"
    )
    return distances, paths


def physical_pair(edge: tuple) -> tuple:
    u, v, _ = edge
    return tuple(sorted((u, v)))


def min_edge_on_path(graph, u, v) -> tuple:
    edges = graph.get_edge_data(u, v)
    key = min(edges, key=lambda k: float(edges[k]["length"]))
    return (u, v, key)


def make_repair_projects(graph, closed: set) -> dict:
    projects = {}
    for edge in closed:
        pair = physical_pair(edge)
        record = projects.setdefault(pair, {"edges": set(), "length_m": 0.0})
        record["edges"].add(edge)
        record["length_m"] = max(record["length_m"], float(graph.get_edge_data(*edge)["length"]))
    return projects


def repair_route_requirements(graph, base_paths: dict, origins: pd.DataFrame, closed: set) -> dict:
    requirements = {}
    closed_pairs = {physical_pair(edge) for edge in closed}
    for row in origins.itertuples():
        if row.node not in base_paths:
            continue
        route = list(reversed(base_paths[row.node]))
        needed = set()
        for u, v in zip(route[:-1], route[1:]):
            edge = min_edge_on_path(graph, u, v)
            if edge in closed:
                needed.add(physical_pair(edge))
            elif physical_pair(edge) in closed_pairs and not graph.has_edge(u, v):
                needed.add(physical_pair(edge))
        requirements[row.ADM_CD] = needed
    return requirements


def select_projects(origins: pd.DataFrame, requirements: dict, projects: dict,
                    budget_m: float, weight: str) -> set:
    chosen = set()
    candidates = origins.loc[origins.ADM_CD.isin(requirements)].copy()
    while True:
        ranked = []
        for row in candidates.itertuples():
            needed = requirements[row.ADM_CD] - chosen
            if not needed:
                continue
            cost = sum(projects[p]["length_m"] for p in needed)
            if cost <= 0 or cost + sum(projects[p]["length_m"] for p in chosen) > budget_m:
                continue
            value = getattr(row, weight)
            if pd.isna(value) or value <= 0:
                continue
            ranked.append((value / cost, value, row.ADM_CD, needed))
        if not ranked:
            break
        _, _, _, next_projects = max(ranked, key=lambda x: (x[0], x[1], x[2]))
        chosen.update(next_projects)
    return chosen


def evaluate(graph, origins: pd.DataFrame, distances: dict) -> dict:
    d = origins.copy()
    d["road_distance_m"] = d.node.map(distances).fillna(np.inf)
    in_range = d.road_distance_m.le(DISTANCE_THRESHOLD_M)
    reachable = np.isfinite(d.road_distance_m)
    return {
        "reachable_origins": int(reachable.sum()),
        "reachable_population": int(d.loc[reachable, "population_2024"].sum()),
        "reachable_older_lower": int(d.loc[reachable, "older_65_lower"].sum()),
        "within_20km_origins": int(in_range.sum()),
        "within_20km_population": int(d.loc[in_range, "population_2024"].sum()),
        "within_20km_older_lower": int(d.loc[in_range, "older_65_lower"].sum()),
        "median_finite_road_distance_km": float(d.loc[reachable, "road_distance_m"].median()/1000) if reachable.any() else None,
    }


def major_disruption(origins: pd.DataFrame, baseline: dict, scenario: dict) -> dict:
    frame = origins.copy()
    frame["before_m"] = frame.node.map(baseline).fillna(np.inf)
    frame["after_m"] = frame.node.map(scenario).fillna(np.inf)
    disrupted = np.isfinite(frame.before_m) & (
        ~np.isfinite(frame.after_m) |
        ((frame.after_m - frame.before_m >= 2_000) &
         (frame.after_m >= 1.5 * frame.before_m))
    )
    return {
        "major_disruption_origins": int(disrupted.sum()),
        "major_disruption_population": int(frame.loc[disrupted, "population_2024"].sum()),
        "major_disruption_older_lower": int(frame.loc[disrupted, "older_65_lower"].sum()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", required=True)
    ap.add_argument("--buffer-m", type=int, required=True)
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--processed", type=Path, default=Path("data/processed"))
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()
    graph_path = args.raw / f"osm_roads/{args.district}_drive_{args.buffer_m}m.graphml"
    graph = ox.io.load_graphml(graph_path)
    graph = ox.projection.project_graph(graph, to_crs="EPSG:5186")
    boundary = gpd.read_file(args.raw / "sgis_selected/bnd_sigungu_00_2025_2Q.shp")
    boundary = boundary.loc[boundary.SIGUNGU_CD.eq(args.district)].to_crs("EPSG:5186")
    if len(boundary) != 1:
        raise ValueError("District not found")
    padded = boundary.geometry.iloc[0].buffer(args.buffer_m)
    origin_raw = pd.read_csv(args.processed / "sgis_dong_origins_2024.csv", dtype={"SIGUNGU_CD":str, "ADM_CD":str})
    origins = origin_raw.loc[
        origin_raw.SIGUNGU_CD.eq(args.district) & origin_raw.population_2024.gt(0)
    ].copy()
    facility_raw = pd.read_csv(args.processed / "medical_sites_with_exposure.csv", dtype={"facility_id":str})
    facility_raw = facility_raw.loc[facility_raw.facility_type.isin(HOSPITAL_TYPES)].copy()
    facility_points = gpd.GeoSeries(
        gpd.points_from_xy(facility_raw.longitude, facility_raw.latitude), crs="EPSG:4326"
    ).to_crs("EPSG:5186")
    facilities = facility_raw.loc[facility_points.within(padded).to_numpy()].copy()
    print(f"{args.district}: {len(origins)} origins, {len(facilities)} nearby broad hospitals", flush=True)
    origin_node, origin_snap = near_nodes(graph, origins)
    facility_node, facility_snap = near_nodes(graph, facilities)
    origins["node"], origins["snap_m"] = origin_node, origin_snap
    facilities["node"], facilities["snap_m"] = facility_node, facility_snap
    all_origin_count = len(origins)
    all_origin_pop = int(origins.population_2024.sum())
    origin_accepted = origins.snap_m.le(SNAP_LIMIT_M)
    facility_accepted = facilities.snap_m.le(SNAP_LIMIT_M)
    origins = origins.loc[origin_accepted].copy()
    facilities = facilities.loc[facility_accepted].copy()
    if not len(facilities):
        raise ValueError("No accepted hospital snap")
    destinations = set(facilities.node)
    intact_destinations = set(facilities.loc[~facilities.exposed, "node"])
    base_dist, base_paths = distance_map(graph, destinations)
    closed, protected_bridge, flood_inventory = flood_closed_edges(
        graph, args.raw / "flood_regions_100yr"
    )
    flood_graph = graph.copy()
    flood_graph.remove_edges_from(closed)
    flood_dist, _ = distance_map(flood_graph, destinations)
    dry_facility_dist, _ = distance_map(flood_graph, intact_destinations)
    all_intersections_graph = flood_graph.copy()
    all_intersections_graph.remove_edges_from(protected_bridge)
    all_intersections_dist, _ = distance_map(all_intersections_graph, destinations)
    projects = make_repair_projects(graph, closed)
    route_requirements = repair_route_requirements(graph, base_paths, origins, closed)
    total_closed_length = sum(x["length_m"] for x in projects.values())
    origins["baseline_m"] = origins.node.map(base_dist).fillna(np.inf)
    origins["closure_m"] = origins.node.map(flood_dist).fillna(np.inf)
    beneficiary_origins = origins.loc[
        np.isfinite(origins.baseline_m) &
        (~np.isfinite(origins.closure_m) |
         ((origins.closure_m-origins.baseline_m >= 2_000) &
          (origins.closure_m >= 1.5*origins.baseline_m)))
    ].copy()
    origin_detail = origins[["ADM_CD","ADM_NM","population_2024","older_65_lower","older_65_upper","snap_m","node"]].copy()
    for label, distances in [("baseline",base_dist),("road_closure",flood_dist),
                             ("road_and_facility",dry_facility_dist),
                             ("all_intersecting_roads",all_intersections_dist)]:
        origin_detail[label+"_m"] = origin_detail.node.map(distances).fillna(np.inf)
    baseline = evaluate(graph, origins, base_dist)
    closure = evaluate(flood_graph, origins, flood_dist)
    closure_facility = evaluate(flood_graph, origins, dry_facility_dist)
    all_intersections = evaluate(all_intersections_graph, origins, all_intersections_dist)
    closure.update(major_disruption(origins, base_dist, flood_dist))
    closure_facility.update(major_disruption(origins, base_dist, dry_facility_dist))
    all_intersections.update(major_disruption(origins, base_dist, all_intersections_dist))
    policy_rows = []
    for fraction in REPAIR_FRACTIONS:
        budget_m = total_closed_length * fraction
        for policy, field in [("total_population","population_2024"),
                              ("older_population","older_65_lower")]:
            chosen = select_projects(beneficiary_origins, route_requirements, projects, budget_m, field)
            repaired = flood_graph.copy()
            for pair in chosen:
                for edge in projects[pair]["edges"]:
                    repaired.add_edge(*edge, **graph.get_edge_data(*edge))
            repaired_dist, _ = distance_map(repaired, destinations)
            results = evaluate(repaired, origins, repaired_dist)
            results.update(major_disruption(origins, base_dist, repaired_dist))
            results.update({
                "district_code":args.district,"budget_fraction":fraction,
                "budget_m":budget_m,"policy":policy,
                "restored_physical_segments":len(chosen),
                "restored_length_m":sum(projects[p]["length_m"] for p in chosen),
                "within_20km_population_recovered_vs_closure":results["within_20km_population"]-closure["within_20km_population"],
                "within_20km_older_recovered_vs_closure":results["within_20km_older_lower"]-closure["within_20km_older_lower"],
                "major_disruption_population_recovered":closure["major_disruption_population"]-results["major_disruption_population"],
                "major_disruption_older_recovered":closure["major_disruption_older_lower"]-results["major_disruption_older_lower"],
            })
            policy_rows.append(results)
            print(json.dumps(results,ensure_ascii=False),flush=True)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"tables").mkdir(exist_ok=True)
    (args.out/"metadata").mkdir(exist_ok=True)
    (args.out/"geodata").mkdir(exist_ok=True)
    road_edges = ox.convert.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    road_state = road_edges[["length","geometry"]].reset_index()
    road_state["state"] = "not_intersecting"
    road_state.loc[
        road_edges.index.isin(closed), "state"
    ] = "closed_ground_road"
    road_state.loc[
        road_edges.index.isin(protected_bridge), "state"
    ] = "bridge_kept"
    road_state.to_file(
        args.out/f"geodata/case_{args.district}_road_state.gpkg",
        layer="road_state", driver="GPKG"
    )
    origin_detail.drop(columns="node").to_csv(
        args.out/f"tables/case_{args.district}_origin_access.csv",index=False,encoding="utf-8-sig"
    )
    pd.DataFrame(policy_rows).to_csv(
        args.out/f"tables/case_{args.district}_restoration.csv",index=False,encoding="utf-8-sig"
    )
    result = {
        "district_code":args.district,"road_graph_sha256":sha256(graph_path),
        "road_graph_nodes":len(graph),"road_graph_directed_edges":graph.number_of_edges(),
        "buffer_m":args.buffer_m,"origin_snap_limit_m":SNAP_LIMIT_M,
        "all_origins":all_origin_count,"accepted_origins":len(origins),
        "all_origin_population":all_origin_pop,
        "accepted_origin_population":int(origins.population_2024.sum()),
        "origin_population_coverage":float(origins.population_2024.sum()/all_origin_pop),
        "median_origin_snap_m":float(np.median(origin_snap)),
        "max_origin_snap_m":float(np.max(origin_snap)),
        "all_nearby_broad_hospitals":len(facility_raw.loc[facility_points.within(padded).to_numpy()]),
        "accepted_hospitals":len(facilities),
        "hospital_types":facilities.facility_type.value_counts().to_dict(),
        "flood_exposed_accepted_hospitals":int(facilities.exposed.sum()),
        "hospital_snap_median":float(np.median(facility_snap)),
        "flood_intersecting_bridge_edges_kept":len(protected_bridge),
        "closed_directed_edges":len(closed),
        "closed_physical_segments":len(projects),
        "closed_physical_road_length_m":total_closed_length,
        "restoration_beneficiary_origins":len(beneficiary_origins),
        "major_disruption_rule":"Baseline reachable and then unreachable, or road-distance increase of at least 2 km and 50%.",
        "flood_archives":flood_inventory,
        "baseline":baseline,"road_closure":closure,
        "road_and_facility_closure":closure_facility,
        "all_intersecting_roads_closure":all_intersections,
        "baseline_connected_population_coverage":baseline["reachable_population"]/int(origins.population_2024.sum()),
        "policy_budgets":list(REPAIR_FRACTIONS),
        "interpretation": "Static road-distance stress test. Entire simplified OSM edge closes if any part intersects mapped flood, except tagged bridges in the main scenario. No observed travel times, actual facility shutdowns, or repair costs. Administrative-dong populations are assigned to one representative point each.",
    }
    (args.out/f"metadata/case_{args.district}_access.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps({k:v for k,v in result.items() if k!="flood_archives"},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
