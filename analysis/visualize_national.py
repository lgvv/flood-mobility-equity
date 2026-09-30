#!/usr/bin/env python3
"""Create national exposure figures and a frozen case selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
import numpy as np
import pandas as pd

KO_FONT = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
if KO_FONT.exists():
    rcParams["font.family"] = font_manager.FontProperties(fname=str(KO_FONT)).get_name()
rcParams["axes.unicode_minus"] = False

PROVINCES = {
    "11":"서울","21":"부산","22":"대구","23":"인천","24":"광주",
    "25":"대전","26":"울산","29":"세종","31":"경기","32":"강원",
    "33":"충북","34":"충남","35":"전북","36":"전남","37":"경북",
    "38":"경남","39":"제주",
}
COLORS = {"metropolitan":"#2563eb","city":"#16a34a","county":"#e11d48"}


def save(fig, base: Path) -> None:
    fig.savefig(base.with_suffix(".png"), dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", type=Path, default=Path("outputs/tables/national_district_exposure.csv"))
    ap.add_argument("--boundary", type=Path, default=Path("data/raw/sgis_selected/bnd_sigungu_00_2025_2Q.shp"))
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()
    d = pd.read_csv(args.table, dtype={"SIGUNGU_CD":str})
    d["province"] = d.SIGUNGU_CD.str[:2].map(PROVINCES)
    d["district_label"] = d.province + " " + d.SIGUNGU_NM
    d["exposure_percent"] = d.stop_exposure_rate * 100
    figures = args.out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(args.boundary)[["SIGUNGU_CD","geometry"]]
    mapdata = boundary.merge(d[["SIGUNGU_CD","exposure_percent","valid_stops"]], on="SIGUNGU_CD")
    # The published figure is a visual summary; simplify only its drawing,
    # leaving the exact boundary used for the point join untouched.
    mapdata["geometry"] = mapdata.geometry.simplify(250, preserve_topology=True)
    fig, ax = plt.subplots(figsize=(9,10))
    mapdata.plot(
        column="exposure_percent", ax=ax, cmap="YlOrRd", vmin=0, vmax=50,
        edgecolor="#9ca3af", linewidth=0.15,
        legend=True, legend_kwds={"label":"정류장 노출률 (%)", "shrink":0.58},
        missing_kwds={"color":"#ddd", "label":"정류장 없음"},
    )
    ax.set_xlim(mapdata.total_bounds[0]-12000,mapdata.total_bounds[2]+20000)
    ax.set_ylim(mapdata.total_bounds[1]-12000,mapdata.total_bounds[3]+12000)
    ax.set_axis_off()
    ax.set_title("국가하천 100년 빈도 범람구역과 겹치는 정류장 비율", fontsize=16, pad=18)
    fig.text(0.5,0.04,"2025.10 정류장 · 2025 Q2 시군구 경계 · 5개 권역 홍수지도 / 지도 미제공 지역은 안전지역을 뜻하지 않음",
             ha="center",fontsize=9,color="#475569")
    save(fig, figures / "national_stop_exposure_map")

    top = d.nlargest(15,"exposed_stops").sort_values("exposed_stops")
    fig, ax = plt.subplots(figsize=(9,7))
    bars = ax.barh(top.district_label,top.exposed_stops,color=top.urban_type.map(COLORS))
    ax.bar_label(bars,padding=3,fontsize=9)
    ax.set_xlim(0,top.exposed_stops.max()*1.15)
    ax.set_xlabel("침수지도와 겹치는 정류장 수")
    ax.set_title("노출 정류장이 가장 많은 시군구 15곳",fontsize=16,pad=14)
    ax.spines[["top","right"]].set_visible(False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=COLORS[k],label=v) for k,v in [
        ("metropolitan","특별·광역시"),("city","시·일반구"),("county","군")
    ]],frameon=False,loc="lower right")
    fig.tight_layout()
    save(fig,figures / "national_top15_exposed_stops")

    fig,ax=plt.subplots(figsize=(9,6.5))
    for typ,label in [("metropolitan","특별·광역시"),("city","시·일반구"),("county","군")]:
        subset=d[(d.urban_type==typ)&d.valid_stops.ge(100)]
        ax.scatter(
            subset.older_share_lower*100,subset.exposure_percent,
            s=np.maximum(15,subset.exposed_stops)*0.65,alpha=0.62,
            color=COLORS[typ],label=label,edgecolor="white",linewidth=0.4
        )
    selected_codes=["11160","38070","38520"]
    for row in d[d.SIGUNGU_CD.isin(selected_codes)].itertuples():
        ax.annotate(row.district_label,(row.older_share_lower*100,row.exposure_percent),
                    xytext=(5,5),textcoords="offset points",fontsize=9)
    ax.set_xlabel("65세 이상 인구 비율 하한 (%) · 2024 SGIS")
    ax.set_ylabel("정류장 노출률 (%) · 2025 정류장")
    ax.set_title("고령화 수준과 정류장 노출률의 분포",fontsize=16,pad=12)
    ax.grid(alpha=0.18);ax.legend(frameon=False)
    fig.tight_layout()
    save(fig,figures / "district_age_vs_stop_exposure")

    selection = {
        "selection_frozen_before_network_analysis": True,
        "minimum_valid_stops_for_rate_ranking": 100,
        "selected": [
            {"code":"11160","reason":"Highest exposure rate among metropolitan districts with at least 100 valid stops; also high absolute exposure and medical-site exposure."},
            {"code":"38070","reason":"Highest exposed-stop count among city/general-district class."},
            {"code":"38520","reason":"Highest exposed-stop count and rate among county class; substantial older-population share."},
        ],
        "alternatives": [
            {"code":"21120","reason":"Highest metropolitan exposed-stop count; lower older share and medical-site exposure than selected Seoul Gangseo."},
            {"code":"38111","reason":"Highest city-class stop exposure rate but lower count and medical-site exposure than Gimhae."},
        ],
        "selection_warning":"The classes compare administrative districts, not equally sized regions. Selection is descriptive and does not establish causal risk.",
    }
    (args.out/"metadata/case_selection.json").write_text(
        json.dumps(selection,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(selection,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
