# Phase 1データ

このディレクトリのPhase 1データは、固定20都市の構造化分析だけに使います。Wikipedia、GraphRAG corpus、LLMが生成した都市情報は入力にもfactにも含めません。

~~~text
raw/          配布元から取得した固定版
processed/    Phase 1パイプラインの構造化出力
provenance/   出典、条件、変換、実取得hash
~~~

## 再生成

リポジトリのルートで実行します。

~~~bash
uv sync --extra dev --no-install-project
PYTHONPATH=. uv run --no-sync python scripts/download_data.py
PYTHONPATH=. uv run --no-sync python pipeline/06_prepare_phase1.py
PYTHONPATH=. uv run --no-sync python scripts/verify_phase1.py
~~~

<code>scripts/download_data.py</code> は既存の空でないファイルを再利用しますが、再利用時も再取得時も10件のレビュー済みSHA-256と照合し、不一致なら停止します。配布元から取り直す必要がある場合だけ <code>--force</code> を明示してください。<code>--force</code> もhash検証を回避しません。<code>--only ssdse|census|airports|geography</code> は調査用ですが、manifestにはその実行で選択したファイルだけが記録されるため、公開前は引数なしで全件を再確認してください。

## Phase 1の正規入力

次の10ファイルだけが <code>pipeline/06_prepare_phase1.py</code> の正規入力です。

| パス | データ | 固定版 |
|---|---|---|
| <code>raw/SSDSE-A-2026.csv</code> | 市区町村125指標 | SSDSE-A-2026 |
| <code>raw/census_od/table3_shimane.xlsx</code> | 島根県を常住地とする通勤・通学OD | 2020年国勢調査 Table 3 |
| <code>raw/census_od/table3_okayama.xlsx</code> | 岡山県を常住地とする通勤・通学OD | 同上 |
| <code>raw/census_od/table3_hiroshima.xlsx</code> | 広島県を常住地とする通勤・通学OD | 同上 |
| <code>raw/census_od/table3_yamaguchi.xlsx</code> | 山口県を常住地とする通勤・通学OD | 同上 |
| <code>raw/census_od/table3_kagawa.xlsx</code> | 香川県を常住地とする通勤・通学OD | 同上 |
| <code>raw/census_od/table3_ehime.xlsx</code> | 愛媛県を常住地とする通勤・通学OD | 同上 |
| <code>raw/geography/P05-22_GML.zip</code> | 市役所等の公的代表点 | 国土数値情報 P05-22 |
| <code>raw/airports/C28-21_GML.zip</code> | 空港、運用状態、定期便区分、参照点 | 国土数値情報 C28-21 |
| <code>raw/airports/airport_management_2025.xlsx</code> | 空港別の年間旅客数 | 2025年空港管理状況調書 |

期待するSHA-256は <code>scripts/download_data.py</code> の <code>EXPECTED_SHA256</code> に固定し、実際に検証したURL、時刻、サイズ、SHA-256は [provenance/download_manifest.json](provenance/download_manifest.json) に記録します。データセット単位の提供者、正式URL、ライセンス、再配布可否、変換、制限は [provenance/sources.yml](provenance/sources.yml)、人が読む帰属・再配布要約は [provenance/LICENSE_DATA.md](provenance/LICENSE_DATA.md) を参照してください。

### ODの意味

- <code>source</code>：常住する市
- <code>target</code>：従業地または通学地の市
- <code>commuters</code>：15歳以上就業者
- <code>students</code>：15歳未満を含む通学者
- <code>total</code>：commuters + students
- <code>year</code>：2020

県境をまたぐODを保持します。政令指定都市の市計と区を重複集計せず、固定20都市の市コードだけを選びます。自都市行は都市間edgeから除外します。

### 座標と空港

自治体座標は、P05-22の施設分類1に該当し、市名と一意に一致する本庁舎です。政令指定都市も区役所の平均ではなく、名称が一致する市役所を使います。

空港はC28-21で供用中かつ定期便区分1または2の87空港です。市役所代表点から各空港参照点までHaversine距離を計算し、最短の1空港を <code>ACCESS_TO</code> として保存します。道路・鉄道の距離や所要時間ではありません。

## 処理済みテーブル

下記の件数は2026-08-21に生成した同梱snapshotです。入力を更新したときは [processed/processing_report.json](processed/processing_report.json) の再実行値を使ってください。

| ファイル | 現在の件数 | grain / 内容 |
|---|---:|---|
| <code>processed/municipalities.parquet</code> | 20 | 固定20都市につき1行。市役所座標、SSDSE 125項目、比較特徴量 |
| <code>processed/ssdse_metrics.parquet</code> | 2,500 | 都市×SSDSE指標のlong形式 |
| <code>processed/commute_edges.parquet</code> | 342 | 正の通勤者がある有向都市ペア |
| <code>processed/study_edges.parquet</code> | 261 | 正の通学者がある有向都市ペア |
| <code>processed/flow_edges.parquet</code> | 351 | 通勤または通学が正の有向都市ペア |
| <code>processed/airports.parquet</code> | 87 | 供用中かつ定期便対象の空港 |
| <code>processed/airport_access.parquet</code> | 20 | 都市ごとの最寄り対象空港 |

<code>municipalities.csv</code> と <code>flow_edges.csv</code> は主要テーブルの確認用CSVです。<code>ssdse_metric_catalog.csv</code> は指標コード・参照年・項目名・出力列を対応させます。<code>seed_membership_review.csv</code> は固定seedの外にあるOD候補をレビューする診断であり、対象都市を自動変更しません。

### JSON出力

| ファイル | 内容 |
|---|---|
| <code>processed/knowledge_graph.json</code> | Municipality 20、Prefecture 6、Airport 87を持つNetworkX node-link JSON |
| <code>processed/phase1_analysis.json</code> | 双方向人流、中心性、Louvain、類似度、空港アクセスの再現用snapshot |
| <code>processed/quality_report.json</code> | 主要キー、件数、OD、県境、人流relation、空港結合のquality gate |
| <code>processed/processing_report.json</code> | 実行時刻、パイプライン名、出力件数 |
| <code>processed/acceptance_results.json</code> | 7自然言語質問と不足条件テストの判定・定量的根拠 |
| <code>../docs/phase1_acceptance.html</code> | Acceptance結果をブラウザで確認する自己完結型HTMLレポート |

現在のKnowledge Graphは113 nodes / 643 edgesです。relation内訳は <code>IS_IN=20</code>、<code>COMMUTES_TO=342</code>、<code>STUDIES_IN=261</code>、<code>ACCESS_TO=20</code> です。行政・アクセスrelationは人流分析に入りません。

## 品質チェック

<code>pipeline/06_prepare_phase1.py</code> は、主要出力を書き出す前に次を検査します。

- 固定20都市、ID一意性、20件の市役所座標と本庁舎分類
- 各都市125 SSDSE項目
- OD endpoint、source-target一意性、commuters + students = total
- self-loop除外、県境OD保持
- 空港旅客数の結合率90%以上、最寄り空港20件
- node typeと4 relationの分離

現在の [processed/quality_report.json](processed/quality_report.json) は15件すべて <code>pass</code> です。旅客数は86/87空港で結合し、未結合は福岡空港（奈多地区）です。

## Phase 1で使わないrawファイル

次のrawファイルは旧実験または調査時のもので、正規入力にもdownload manifestにも含みません。

- <code>raw/SSDSE-B-2026.csv</code>、<code>SSDSE-C-2026.csv</code>、<code>SSDSE-D-2023.csv</code>、<code>SSDSE-E-2026.csv</code>、<code>SSDSE-F-2023v3.csv</code>
- <code>raw/census_od/e06_02-01.xlsx</code>、<code>e06_03-01.xlsx</code>
- <code>raw/airports/airports.csv</code>、<code>airport_ranking_2025.xlsx</code>

これらが存在してもPhase 1の処理結果には入りません。Wikipedia、GraphRAG、LLMの一般知識をランキング、類似度、Knowledge Graphのfactへ追加しないでください。

## 再配布

コードのMIT Licenseはデータへ適用されません。rawまたはprocessedを再配布する場合は、[provenance/LICENSE_DATA.md](provenance/LICENSE_DATA.md)、[provenance/sources.yml](provenance/sources.yml)、download manifest、出典表記、加工した旨、配布元の制限事項を一緒に保持してください。
