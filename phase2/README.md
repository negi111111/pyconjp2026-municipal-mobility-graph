# Phase 2：全国主要100都市 Mobility Knowledge Graph

このディレクトリはPhase 1の最終状態をコピーし、全国主要100都市へ拡張したPhase 2です。
Phase 1との差分はこのディレクトリ内だけに実装し、[phase1/](../phase1/)は変更しません。

## 現在の状態

- 検索空間：承認済み全国100都市
- 分析空間：全国1,719自治体（東京都23区を`R13000 / 東京都区部`へ集約）
- OD：2020年国勢調査Table 3、47都道府県
- 都市属性：SSDSE-A-2026
- 地理・空港：P05-22 / C28-21
- LLM：Phase 1と同じPlanner/Response境界
- 性能・メモリベンチマーク：Phase 3完了時の横断監査で実測済み

全国100都市の根拠は[docs/city_selection.md](docs/city_selection.md)、
実装・検証の概要は[docs/phase2_implementation_report.html](docs/phase2_implementation_report.html)、
Phase 2 Acceptanceは[docs/phase2_acceptance.html](docs/phase2_acceptance.html)です。

## クイックスタート

Phase 2ディレクトリで実行します。

```bash
uv sync --extra dev --no-install-project
make acceptance
```

`make acceptance`は、全国分析データの生成、テスト、Phase 2の10問Acceptanceを実行します。
Phase 1の基準経路だけを再検証する場合は、次を実行します。

```bash
make acceptance-phase1-baseline
```

LLMコマンドはリポジトリルートの`.env`または環境変数を読み込みます。
`.env`をPhase内へコピーしたり、ログへ出力したりする必要はありません。

```bash
make acceptance-llm
```

### LLM Queryを試すコマンド

承認済み100都市のprocessed dataを準備した後、Phase 2ディレクトリで実行します。
接続設定はルート`.env`（または環境変数）から読み込みます。

```bash
make query-llm Q="福岡市に都市特性が似ていて空港アクセスも良い都市は？"
```

全国人流ハブのStructured EvidenceをJSONで確認する場合：

```bash
make query-llm-json Q="全国主要都市で人流ハブ性が高い都市は？"
```

`--llm`を付けても、全国OD、PageRank、類似度、空港距離、人口・地域フィルタは
Phase 2のpandas / NetworkXが計算します。LLM接続を含む全10問は
`make acceptance-llm`で再実行できます。
Chat Deploymentは`AZURE_OPENAI_CHAT_DEPLOYMENT`です。通常QueryはPlanner=`high` /
Response=`medium` / 各4096 token、比較考察は`xhigh` / 8192 tokenです。

## 全国データ処理

全国ODを候補選定用に取得・再生成する場合：

```bash
make download-selection-od
make select-cities
```

承認済み100都市のproductionデータを生成する場合：

```bash
make prepare-phase2
```

全国ODは100都市へ先に切り捨てません。全国自治体を分析空間としてOD中心性を計算し、
その結果を100都市の検索空間へ投影します。

## 自然言語検索

Phase 2では、Phase 1の質問に加えて全国・地域・複合条件を扱います。

| 質問例 | 実行する分析 |
|---|---|
| 福岡市に都市特性が似ている都市は？ | 全国100都市のSSDSE類似度 |
| 福岡市のように空港アクセスが良く、都市機能もある都市は？ | 類似度＋空港距離 |
| 広島市に似ている都市を全国から探して | 全国100都市のSSDSE類似度 |
| 医療面で仙台市と似ている都市は？ | 医療カテゴリの類似度 |
| 全国主要都市で人流ハブ性が高い都市は？ | 全国1,719自治体の中心性を100都市へ投影 |
| 九州で福岡市に似ている都市は？ | 九州地域フィルタ＋類似度 |
| 九州以外で福岡市に似ていて空港アクセスが良い都市は？ | 除外地域＋類似度＋空港距離 |
| 人口規模を抑えながら、都市機能が比較的充実した都市は？ | 人口上限＋全国weighted degree代理指標 |

LLMは意図・都市・条件の解釈と説明だけを担当します。OD集計、PageRank、
類似度、距離、ランキング、統計値はpandas / NetworkXが計算します。
「都市機能」は固定livability scoreではなく、明示的な全国weighted degreeを
代理指標として扱います。

## 主な生成物

- `data/processed/municipalities.parquet`：全国1,719自治体、SSDSE属性、検索フラグ
- `data/processed/flow_edges.parquet`：全国177,274件の集約済み有向OD
- `data/processed/national_flow_metrics.parquet`：全国自治体の中心性
- `data/processed/search_universe.json`：承認済み100都市の検索境界
- `data/processed/phase2_analysis.json`：全国分析と100都市投影のsnapshot
- `data/processed/knowledge_graph.json`：100都市検索グラフの投影
- `data/processed/quality_report.json`：全国データ品質とグラフ層の検証
- `data/processed/phase2_acceptance_results.json`：Phase 2 10問の機械可読結果
- `data/processed/phase2_acceptance_llm_results.json`：LLM経路10問の機械可読結果
- `docs/phase2_acceptance.html`：Phase 2 Acceptance HTML
- `docs/phase2_acceptance_llm.html`：LLM経路のPhase 2 Acceptance HTML

## フェーズ2の制約

- 人流指標は全国1,719自治体で計算し、表示対象だけを100都市へ投影します。
- 東京都区部は23区の集約エンティティです。
- 空港距離は市役所代表点からC28参照点までのHaversine直線距離です。
- 類似度の標準化母集団は承認済み100都市です。Phase 1の20都市スコアは流用しません。
- 自然、温泉、家賃、気候、災害、観光、鉄道所要時間は構造化データに含めません。
- 性能・メモリの実測値は、Phase 3の[横断監査報告書](../phase3/docs/cross_phase_audit.html)に記録しています。

## 出典とライセンス

選定・全国OD診断の出典は
[data/provenance/phase2_selection_sources.yml](data/provenance/phase2_selection_sources.yml)、
取得manifestは[data/provenance/national_selection_od_manifest.json](data/provenance/national_selection_od_manifest.json)です。
コードはルートの[MIT License](../LICENSE)、データは各配布元の条件に従います。
