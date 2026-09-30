# Run the code

[한국어](README.md) | **English**

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). Source files are not included in this repository. Download the following files and place them at the specified paths.

| File path | Download |
| --- | --- |
| `data/raw/flood_regions_100yr/RFM_SAREA_NTN_{1..5}_100.zip` | [Flood Hazard Map portal](https://data.floodmap.go.kr/main/board/map_data_download): five regional ZIPs for the 100-year national-river scenario |
| `data/raw/bus_stops_20251031_euckr.csv` | [National bus-stop data](https://www.data.go.kr/data/15067528/fileData.do): October 31, 2025 |
| `data/raw/sgis_selected/bnd_sigungu_00_2025_2Q.shp` and sidecars | [SGIS district boundaries](https://sgis.mods.go.kr/view/pss/openDataIntrcn): 2025 Q2 |
| `data/raw/sgis_selected/bnd_dong_00_2025_2Q.shp` and sidecars | SGIS administrative-dong boundaries: 2025 Q2 |
| `data/raw/sgis_selected/2025년기준_2024년_인구총괄(총인구).csv` | SGIS 2024 total population |
| `data/raw/sgis_selected/2025년기준_2024년_성연령별인구.csv` | SGIS 2024 population by sex and age |
| `data/raw/hira_facilities_202606.zip` | [HIRA medical-facility and pharmacy export](https://opendata.hira.or.kr/op/opc/selectOpenData.do?sno=11925): June 2026 |

Run the following commands in order from the repository root. Downloading road networks from OpenStreetMap requires an internet connection.

```bash
uv sync --locked

uv run python analysis/inventory_flood_sources.py
uv run python analysis/download_flood_regions.py
uv run python analysis/prepare_medical_sites.py
uv run python analysis/prepare_dong_origins.py
uv run python analysis/analyze_national_exposure.py
uv run python analysis/visualize_national.py

uv run python analysis/download_case_roads.py --district 11160 --buffer-m 3000
uv run python analysis/analyze_case_access.py --district 11160 --buffer-m 3000
uv run python analysis/download_case_roads.py --district 38070 --buffer-m 5000
uv run python analysis/analyze_case_access.py --district 38070 --buffer-m 5000
uv run python analysis/download_case_roads.py --district 38520 --buffer-m 8000
uv run python analysis/analyze_case_access.py --district 38520 --buffer-m 8000

uv run python analysis/visualize_cases.py
uv run python analysis/compile_results.py
```

Generated files are written to `outputs/`.
