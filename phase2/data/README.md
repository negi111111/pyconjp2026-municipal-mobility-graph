# Phase 2 data

Phase 2のデータは、全国分析空間と承認済み100都市の検索空間を分けて保持します。

```text
raw/          公開元から取得した固定版（再取得スクリプトとmanifest）
processed/    全国分析・100都市検索の構造化出力
provenance/   出典、ライセンス、変換、取得manifest
```

## 再生成

Phase 2ディレクトリのルートで実行します。

```bash
uv sync --extra dev --no-install-project
PYTHONPATH=. uv run --no-sync python pipeline/06_prepare_phase2.py
PYTHONPATH=. uv run --no-sync python scripts/verify_phase2.py
```

## 正規入力

- `raw/SSDSE-A-2026.csv`
- `raw/census_od_national/table3_01.xlsx`〜`table3_47.xlsx`
- `raw/geography/P05-22_GML.zip`
- `raw/airports/C28-21_GML.zip`
- `raw/airports/airport_management_2025.xlsx`
- `configs/phase2_cities.yml`

全国ODの取得情報は
[provenance/national_selection_od_manifest.json](provenance/national_selection_od_manifest.json)、
選定の出典は
[provenance/phase2_selection_sources.yml](provenance/phase2_selection_sources.yml)に記録します。

## 処理済みテーブル

| ファイル | grain / 内容 |
|---|---|
| `municipalities.parquet` | 全国1,719自治体。東京都23区はR13000へ集約し、100都市検索フラグを保持 |
| `commute_edges.parquet` | 全国の正の通勤有向OD |
| `study_edges.parquet` | 全国の正の通学有向OD |
| `flow_edges.parquet` | 通勤または通学の集約有向OD |
| `national_flow_metrics.parquet` | 全国分析空間のweighted degree/PageRank等 |
| `airport_access.parquet` | 承認済み100都市ごとの最寄り定期便空港 |
| `search_universe.json` | Search Universe 100都市とAnalysis Universeの境界 |
| `phase2_analysis.json` | 全国分析から100都市へ投影したsnapshot |
| `phase2_acceptance_results.json` | Phase 2 10問の検証結果 |

## 境界

人流中心性・流入出は全国1,719自治体で計算し、回答表示は100都市へ投影します。
類似度の標準化母集団は承認済み100都市です。自然、家賃、温泉、災害、気候、
観光、鉄道所要時間等はPhase 2の構造化データには含めません。
