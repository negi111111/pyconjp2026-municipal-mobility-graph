# Phase 3：生活環境データ拡張

このディレクトリは、承認済みのPhase 2をコピーして作成したPhase 3の独立実行単位です。
Phase 1/2は変更せず、Phase 3の追加コード・設定・データ・証跡はこのディレクトリ内で完結します。

実装・検証の結論は[Phase 3実装・検証報告書](docs/phase3_implementation_report.html)、
受入の詳細は[Phase 3 Acceptance](docs/phase3_acceptance.html)を参照してください。

## 実装範囲

- 分析空間：全国1,719自治体（東京都23区は`R13000 / 東京都区部`へ集約）
- 検索空間：ユーザー承認済み全国主要100都市
- 気候：気象庁1991-2020年平年値、最近傍地上観測所、6特徴量
- 広域交通：国土数値情報N02-20 (2020) の新幹線駅、最近傍駅までの直線距離
- 既存分析：SSDSE、2020年国勢調査OD、空港アクセス、全国中心性、100都市類似度
- LLM：Query Plannerと説明だけ。Hard Factsの数値・順位・条件判定には使用しない

住居費、災害、自然は、coverage・定義・集約方法が十分でないためPhase 3の標準ランキングへ
追加していません。詳細は[data_gaps.md](docs/data_gaps.md)を参照してください。

## クイックスタート

Phase 3ディレクトリで実行します。

```bash
uv sync --extra dev --no-install-project
make acceptance
```

`make acceptance`は、Phase 3 Feature Storeの再生成、回帰テスト、オフラインAcceptanceを実行します。
ソースアーカイブを再取得・checksum検証する場合は次を先に実行します。

```bash
make download-phase3
make acceptance
```

LLM経路（Azure OpenAI）を検証する場合は、ルートの`.env`をPhase内へコピーせず、
既存のプロジェクト環境変数読込を利用します。

```bash
make acceptance-phase3-llm
```

出力：

- `data/processed/phase3_acceptance_results.json`
- `docs/phase3_acceptance.html`
- `data/processed/phase3_acceptance_llm_results.json`
- `docs/phase3_acceptance_llm.html`

## 実行コマンド

| コマンド | 内容 |
|---|---|
| `make install` | Phase 3依存を`--no-install-project`で同期 |
| `make download-phase3` | JMA / MLIT N02-20を取得しSHA-256 manifestを生成 |
| `make prepare-phase2` | Phase 2全国分析データを再生成 |
| `make prepare-phase3` | 気候・新幹線Feature Storeを再生成 |
| `make query Q='...'` | 日本語Queryを実行し、説明文を表示 |
| `make query-json Q='...'` | Structured EvidenceをJSON表示 |
| `make query-llm Q='...'` | Azure OpenAI Planner/Responseを使用 |
| `make query-llm-json Q='...'` | Azure OpenAI経由のStructured EvidenceをJSON表示 |
| `make compare-phases Q='...'` | 同一QueryをPhase 1〜3へ渡し、各回答と機械的差分を表示 |
| `make compare-phases-llm Q='...'` | 同一Queryの3結果をLLMへ渡して差分を考察 |
| `make diagnose-similarity` | Phase 1→2のfit母集団差とfeature寄与を診断 |
| `make test` | Phase 1〜3のPhase 3内コピーに対する回帰テスト |
| `make lint` | Phase 3コード、パイプライン、Acceptance、テストをlint |
| `make acceptance` | Phase 3の標準受入 |
| `PYTHONPATH=. uv run --no-sync python scripts/benchmark_cross_phase.py` | Phase 1〜3ロード・Query性能/RSSを測定 |

### LLM Queryを試すコマンド

Phase 3のFeature Storeとprocessed dataを準備した後、Phase 3ディレクトリで実行します。
接続設定はルート`.env`（または環境変数）から読み込みます。

```bash
make query-llm Q="福岡市に似ていて冬が比較的暖かい都市は？"
```

空港・新幹線の複合条件をStructured Evidenceで確認する場合：

```bash
make query-llm-json Q="空港と新幹線の両方へのアクセスが良い都市は？"
```

LLMはPlannerと説明だけを担当し、気候値、新幹線距離、空港距離、人口、
人流、順位はPhase 3のローカル計算結果です。接続確認を含む全6問は
`make acceptance-phase3-llm`で再実行できます。
Chat Deploymentは`AZURE_OPENAI_CHAT_DEPLOYMENT`です。通常QueryはPlanner=`high` /
Response=`medium` / 各4096 token、Phase比較考察は`xhigh` / 8192 tokenです。
役割別環境変数で上書きできます。

### Phase 1〜3へ同じQueryを渡して比較する

Phase 3ディレクトリから、同一の日本語Queryを3Phaseへ一度ずつ渡せます。
各Phaseの日本語回答、status、intent、上位候補、Structured Resultを表示し、
`/tmp/pyconjp2026-mobility-kg-phase-comparison/`へJSON/Markdownも保存します。

```bash
make compare-phases Q="広島市と都市特性が似ている都市は？"
```

各PhaseのLLM Planner/Responseを通したうえで、3つの結果自体をxhighのLLMへ渡して
差分を考察する場合：

```bash
make compare-phases-llm Q="広島市と都市特性が似ている都市は？"
```

保存先を変える場合：

```bash
make compare-phases-llm \
  Q="広島市と都市特性が似ている都市は？" \
  COMPARE_OUTPUT_DIR="/tmp/my-phase-comparison"
```

LLMによる考察は説明専用で、PhaseごとのHard Facts、順位、数値を変更しません。
実装本体はリポジトリ共通ツールの[`tools/compare_phases.py`](../tools/compare_phases.py)です。

類似度の「20都市fitから100都市fitへの変化」をA-Dケースで切り分ける場合：

```bash
make diagnose-similarity
```

既定で`/tmp/pyconjp2026-mobility-kg-similarity-diagnostic.json`と`.md`へ出力します。
Feature selectionを自動変更せず、広島市と東京都区部・福岡市・岡山市の上位寄与を
監査用に表示します。

## ローカル可視化UI

Phase 1〜3のGraph、Feature、同一Query比較を確認するUIは、リポジトリルートの
[`visualizer/`](../visualizer/)にあります。Phase 3のStreamlit依存環境とは独立しています。

```bash
cd ../visualizer
make install
make run
```

## 代表的なQuery

| 質問 | Hard Facts |
|---|---|
| 福岡市に似ていて住居費が比較的安い都市は？ | 類似度を返すが、住居費は`partial` / `rent`として未収録を明示 |
| 福岡市に似ていて冬が比較的暖かい都市は？ | 類似度＋JMA 1月平均気温 |
| 空港と新幹線の両方へのアクセスが良い都市は？ | 空港距離＋最近傍新幹線駅距離 |
| 人口規模を抑えつつ、広域交通が便利な都市は？ | 人口上限＋新幹線距離＋全国weighted degree |
| 中国・四国で冬が比較的暖かく、都市機能もある都市は？ | 中国/四国フィルタ＋JMA気候＋weighted degree |
| 九州以外で福岡市に似ていて住居費を抑えやすい都市は？ | 九州除外＋類似度、住居費は未収録 |

複合条件では、条件ごとの`feature`、`unit`、`rule`、`reference_value`をEvidenceへ保持します。
参照都市がないQueryは、検索集合の中央値を明示的な基準として使用します。

## 生成物

- `data/processed/environmental_metrics.parquet`：100都市×7特徴量、来歴列付き
- `data/processed/weather_station_access.parquet`：100都市のJMA最近傍観測所
- `data/processed/shinkansen_access.parquet`：100都市の最近傍新幹線駅
- `data/processed/shinkansen_stations.parquet`：N02-20から抽出した92駅
- `data/processed/phase3_feature_catalog.json`：採用特徴量と未採用条件
- `data/processed/phase3_processing_report.json`：coverage・制約・処理件数
- `data/processed/cross_phase_benchmark.json`：Phase 1〜3のロード・Query性能・最大RSS
- `data/provenance/phase3_sources.yml`：出典、ライセンス、再配布、変換
- `data/provenance/phase3_download_manifest.json`：取得時刻、サイズ、SHA-256
- `docs/phase3_acceptance.html`：オフラインAcceptance
- `docs/phase3_acceptance_llm.html`：LLM経路Acceptance
- `docs/phase3_implementation_report.html`：日本語実装・検証報告書
- `docs/cross_phase_audit.html`：Phase 1〜3横断監査・最適化報告書

## データと計算の境界

- 気候値はJMA観測所の1991-2020年平年値で、自治体全域平均ではありません。
- 新幹線アクセスはN02-20駅までのHaversine直線距離で、所要時間・運賃・乗換ではありません。
- `station_in_municipality`はポリゴン結合未実装のため、`not_spatially_joined`を保持します。
- Phase 3特徴量はPhase 2のcore_similarityへ自動追加しません。
- 欠損値、未確認coverage、未採用条件を国平均・地域平均・LLMで補完しません。
- 固定の`livability_score`やLLM生成スコアは作成しません。

## 出典・ライセンス

Phase 3の出典と変換定義は
[phase3_sources.yml](data/provenance/phase3_sources.yml)、取得証跡は
[phase3_download_manifest.json](data/provenance/phase3_download_manifest.json)です。
コードはルートの[MIT License](../LICENSE)、データは各配布元の条件に従います。
