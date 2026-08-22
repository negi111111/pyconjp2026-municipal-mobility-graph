# Phase 3 data

Phase 3は、Phase 2の全国分析空間と承認済み100都市の検索空間に、
気候・新幹線アクセスのFeature Storeを追加します。

```text
raw/          JMA / MLITの固定版（download scriptとmanifestから再取得）
processed/    Phase 2基盤とPhase 3 Feature Storeの構造化出力
provenance/   出典、ライセンス、変換、取得manifest
```

## 再生成

Phase 3ディレクトリのルートで実行します。

```bash
uv sync --extra dev --no-install-project
PYTHONPATH=. uv run --no-sync python pipeline/07_prepare_phase3.py
PYTHONPATH=. uv run --no-sync python scripts/verify_phase3.py
```

ソースアーカイブを再取得する場合は、先に
`PYTHONPATH=. uv run --no-sync python scripts/download_phase3_data.py`を実行します。

## Phase 3 Feature Store

| ファイル | grain / 内容 |
|---|---|
| `environmental_metrics.parquet` | 100都市×7特徴量。単位、期間、出典、取得時刻、ライセンス、変換を保持 |
| `weather_station_access.parquet` | 都市と最近傍JMA観測所、距離、1991-2020期間 |
| `shinkansen_access.parquet` | 都市と最近傍新幹線駅、距離、駅所属未判定状態 |
| `shinkansen_stations.parquet` | N02-20から抽出した92駅 |
| `phase3_feature_catalog.json` | 採用特徴量と住居費・災害・自然の採否 |
| `phase3_processing_report.json` | 件数、coverage、制約、処理情報 |
| `phase3_acceptance_results.json` | Phase 3 offline Acceptance |
| `phase3_acceptance_llm_results.json` | Phase 3 LLM Acceptance |
| `cross_phase_benchmark.json` | Phase 1〜3のロード・Query性能・最大RSS |

## データ境界

- 気候値はJMA観測所の平年値であり、自治体全域平均ではありません。
- 新幹線は最近傍駅までのHaversine直線距離のみです。所要時間・運賃・乗換は含みません。
- `station_in_municipality`はポリゴン結合未実装のため`not_spatially_joined`を保持します。
- 住居費は同一定義で100都市を完全カバーできるデータを確認していないため未採用です。
- 災害・自然は都市全体の集約方法が未確定のため未採用です。
- 欠損は平均値、LLM、固定スコアで補完しません。
