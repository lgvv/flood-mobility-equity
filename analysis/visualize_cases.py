#!/usr/bin/env python3
"""Render case comparison and road-state maps."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

FONT = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
if FONT.exists():
    rcParams["font.family"] = font_manager.FontProperties(fname=str(FONT)).get_name()
rcParams["axes.unicode_minus"] = False
CASES = [("11160", "서울 강서구"), ("38070", "경남 김해시"), ("38520", "경남 함안군")]
BLUE, RED, GREEN, DARK = "#2563eb", "#e05b50", "#17866a", "#203048"


def save(fig, path: Path) -> None:
    fig.savefig(path.with_suffix(".png"), dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_comparison(out: Path, cases: list[tuple[str, str, dict]]) -> None:
    names = [name for _, name, _ in cases]
    before = [x["baseline"]["within_20km_population"] for _, _, x in cases]
    after = [x["road_closure"]["within_20km_population"] for _, _, x in cases]
    disrupted = [x["road_closure"]["major_disruption_population"] for _, _, x in cases]
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.3), gridspec_kw={"width_ratios": [1.2, 1]})
    y = np.arange(len(names))
    axes[0].barh(y - .18, np.array(before)/1000, height=.32, color=BLUE, label="정상 도로망")
    axes[0].barh(y + .18, np.array(after)/1000, height=.32, color=RED, label="침수 교차 도로 차단")
    axes[0].set_yticks(y, names); axes[0].invert_yaxis()
    axes[0].set_xlabel("20 km 이내 병원 접근 가능 동 대표점 인구 (천 명)")
    axes[0].legend(frameon=False, loc="lower right")
    axes[0].set_xlim(0, max(before)*1.14/1000)
    for i, (b, a) in enumerate(zip(before, after)):
        axes[0].text(b/1000+2, i-.18, f"{b:,}", va="center", fontsize=9)
        axes[0].text(a/1000+2, i+.18, f"{a:,}", va="center", fontsize=9)
    axes[1].barh(y, np.array(disrupted)/1000, height=.45, color=GREEN)
    axes[1].set_yticks(y, names); axes[1].invert_yaxis()
    axes[1].set_xlabel("접근 불가 또는 거리 2 km·50% 이상 증가 (천 명)")
    axes[1].set_xlim(0, max(disrupted)*1.27/1000)
    for i, v in enumerate(disrupted):
        axes[1].text(v/1000+1, i, f"{v:,}", va="center", fontsize=9)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", alpha=.12)
    fig.suptitle("같은 홍수 시나리오에서도 접근성 변화의 차이", fontsize=17, color=DARK)
    fig.text(.5, -.01, "2024 행정동 인구를 대표점에 배정한 도로거리 시뮬레이션 · 실제 통행·고립 인구가 아님", ha="center", fontsize=9, color="#66788a")
    fig.tight_layout(rect=[0,.04,1,.93])
    save(fig, out/"case_access_comparison")


def plot_case(out: Path, raw: Path, processed: Path, code: str, name: str, result: dict) -> None:
    roads = gpd.read_file(out.parent/"geodata"/f"case_{code}_road_state.gpkg")
    boundary = gpd.read_file(raw/"sgis_selected/bnd_sigungu_00_2025_2Q.shp")
    boundary = boundary.loc[boundary.SIGUNGU_CD.eq(code)].to_crs(roads.crs)
    detail = pd.read_csv(out.parent/"tables"/f"case_{code}_origin_access.csv", dtype={"ADM_CD":str})
    all_origins = pd.read_csv(processed/"sgis_dong_origins_2024.csv", dtype={"ADM_CD":str})
    merged = all_origins.merge(detail, on="ADM_CD", suffixes=("", "_case"))
    points = gpd.GeoDataFrame(merged, geometry=gpd.points_from_xy(merged.longitude, merged.latitude), crs="EPSG:4326").to_crs(roads.crs)
    baseline = points.baseline_m.to_numpy()
    closure = points.road_closure_m.to_numpy()
    both_finite = np.isfinite(baseline) & np.isfinite(closure)
    large_detour = np.zeros(len(points), dtype=bool)
    large_detour[both_finite] = (
        (closure[both_finite] - baseline[both_finite] >= 2000)
        & (closure[both_finite] >= 1.5 * baseline[both_finite])
    )
    affected = np.isfinite(baseline) & (~np.isfinite(closure) | large_detour)
    fig, ax = plt.subplots(figsize=(8.4, 8.0))
    boundary.plot(ax=ax, facecolor="#f8fafc", edgecolor="#5e6f82", linewidth=1.3)
    roads.loc[roads.state.eq("not_intersecting")].plot(ax=ax, color="#bfcbd6", linewidth=.35, alpha=.5)
    roads.loc[roads.state.eq("closed_ground_road")].plot(ax=ax, color=RED, linewidth=.85, alpha=.75)
    roads.loc[roads.state.eq("bridge_kept")].plot(ax=ax, color=BLUE, linewidth=1, alpha=.8)
    points.loc[~affected].plot(ax=ax, color=GREEN, edgecolor="white", linewidth=.8, markersize=38, zorder=5)
    points.loc[affected].plot(ax=ax, color="#f9a329", edgecolor="white", linewidth=.9, markersize=65, zorder=6)
    xmin,ymin,xmax,ymax=boundary.total_bounds
    margin=max(xmax-xmin,ymax-ymin)*.09
    ax.set_xlim(xmin-margin,xmax+margin);ax.set_ylim(ymin-margin,ymax+margin)
    ax.set_axis_off()
    ax.set_title(f"{name}: 홍수지도와 교차하는 도로와 접근성 변화", fontsize=15, color=DARK, pad=17)
    ax.legend(handles=[Patch(color=RED,label="침수 교차 지상도로(차단 가정)"),
                       Patch(color=BLUE,label="교량 태그가 있어 유지"),
                       Patch(color="#f9a329",label="접근성 크게 악화된 동 대표점"),
                       Patch(color=GREEN,label="그 외 동 대표점")],
              loc="lower center",bbox_to_anchor=(.5,-.06),ncol=2,frameon=False,fontsize=9)
    fig.text(.5,.01,f"차단 {result['closed_physical_segments']:,}개 물리 구간 · 동 대표점 {result['accepted_origins']}개 · OSM 도로거리 모델",ha="center",fontsize=9,color="#66788a")
    fig.tight_layout(rect=[0,.04,1,.94])
    save(fig,out/f"case_{code}_road_access_map")


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--raw",type=Path,default=Path("data/raw"))
    ap.add_argument("--processed",type=Path,default=Path("data/processed"))
    ap.add_argument("--out",type=Path,default=Path("outputs"))
    args=ap.parse_args()
    args.out.joinpath("figures").mkdir(parents=True,exist_ok=True)
    cases=[(code,name,json.loads((args.out/"metadata"/f"case_{code}_access.json").read_text())) for code,name in CASES]
    plot_comparison(args.out/"figures",cases)
    for code,name,result in cases:
        plot_case(args.out/"figures",args.raw,args.processed,code,name,result)


if __name__=="__main__":
    main()
