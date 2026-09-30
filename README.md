# 코드 실행

**한국어** | [English](README.en.md)

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다. 원자료는 저장소에 포함되지 않습니다. 아래 파일을 내려받아 지정된 경로에 배치하세요.

| 파일 경로 | 다운로드 |
| --- | --- |
| `data/raw/flood_regions_100yr/RFM_SAREA_NTN_{1..5}_100.zip` | [한강홍수통제소 홍수위험지도](https://data.floodmap.go.kr/main/board/map_data_download): 국가하천 100년 빈도 권역별 ZIP 5개 |
| `data/raw/bus_stops_20251031_euckr.csv` | [국토교통부 버스정류장정보](https://www.data.go.kr/data/15067528/fileData.do): 2025년 10월 31일 자료 |
| `data/raw/sgis_selected/bnd_sigungu_00_2025_2Q.shp`와 부속 파일 | [SGIS 시군구 경계](https://sgis.mods.go.kr/view/pss/openDataIntrcn): 2025년 2분기 |
| `data/raw/sgis_selected/bnd_dong_00_2025_2Q.shp`와 부속 파일 | SGIS 행정동 경계: 2025년 2분기 |
| `data/raw/sgis_selected/2025년기준_2024년_인구총괄(총인구).csv` | SGIS 2024년 총인구 |
| `data/raw/sgis_selected/2025년기준_2024년_성연령별인구.csv` | SGIS 2024년 성·연령별 인구 |
| `data/raw/hira_facilities_202606.zip` | [건강보험심사평가원 병·의원 및 약국 현황](https://opendata.hira.or.kr/op/opc/selectOpenData.do?sno=11925): 2026년 6월 자료 |

저장소 최상위 디렉터리에서 다음 명령을 순서대로 실행하세요. 도로망을 OpenStreetMap에서 내려받는 단계에는 인터넷 연결이 필요합니다.

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

생성한 파일은 `outputs/`에 저장됩니다.
