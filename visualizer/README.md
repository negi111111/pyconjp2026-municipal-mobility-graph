# Phase 1-3 Visualizer

Phase 1〜3の既存Graph、Feature Store、Query結果を、人間が比較・探索するための
ローカルStreamlit UIです。既存Phaseの分析関数や順位計算を再実装せず、processed
dataと`tools/compare_phases.py`を読み込みます。Query比較とグラフ探索は同じ画面の
左右カラムに表示し、Query実行後すぐに候補Graphを確認できます。

画面上部の「システム構成とLLM境界を表示」toggleをONにすると、
公開データ → Planner → pandas / NetworkX → Hard Facts → LLM Response / Soft Knowledge
の全体フローを確認できます。通常の発表デモではOFFにして画面を軽くできます。

## 起動

```bash
cd visualizer
make install
make run
```

The bundled `.streamlit/config.toml` disables Streamlit usage statistics for this local
visual audit app. Do not put secrets in `.streamlit/config.toml`; use the repository
root `.env` only for optional Azure OpenAI access.

基本機能はAPIキー不要です。

- Phase Evolution
- Graph Explorer
- Query Comparison（offline）
- Node Inspector
- Feature provenance
- coverage / diagnostics

LLM比較考察を使う場合だけ、リポジトリルートの`.env`または環境変数を読み込みます。
`.env`をvisualizerへコピーしません。

## 画面

### Phase Evolution

画面上の表示は日本語で、Phase 1→2→3の検索対象、分析対象、node/edge、Relation、
Feature、対応Queryを比較します。Phase 2→3はGraph structure unchanged、
Climate/Rail Feature addedとして正確に表示します。

### グラフ探索

実際のGraph snapshotだけを描画します。Phase 2/3では検索対象100都市を
デフォルトにし、地域、ノード種別、関係、N-hop、OD weight、top Nで絞り込みます。
ノード間隔を広げたrepulsionレイアウト、エッジ数上限、Relation filterで重なりを抑えます。
ノードクリックで選択自治体を都市情報へ渡せます。
Relationの初期値は行政所属、通勤、通学、空港アクセスの全種類です。地域を変更すると、
表示自治体数・都道府県/空港の接続・エッジ件数も同時に更新されます。
全国1,719自治体の全Graphを起動時に描画しません。

### クエリ比較

「選択したPhaseのみ」と「Phase 1〜3を比較」を切り替えられます。
Chat入力、デモ用Query preset、回答履歴、回答候補からGraph/都市情報への選択、
Structured Result、実行経路、数値整合性チェックを表示します。

### Query Comparison

内部識別子では、既存の`tools/compare_phases.py`を使って各Phaseの日本語回答、
status、Structured Result、上位候補、execution path、retrievers、numeric claim checkを
取得します。候補都市を選択するとGraph ExplorerとNode Inspectorの選択を更新します。

### Node Inspector

選択したMunicipalityについて、Basic、Demographics、SSDSE原指標、派生Feature、
Mobility、Airport、Climate、Rail、ProvenanceをPhaseに存在する範囲だけ表示します。
PrefectureやAirportをクリックした場合も、基本属性と実際の接続Relation・weightを表示します。
SSDSE原指標はindicator code、label、reference year、value、source URLとともに表示します。
WeatherStationとShinkansenStationがGraph node/edgeに存在しない場合は、Feature Storeの
recordとして表示し、架空のGraph edgeは作りません。

## 実装境界

- NetworkXのGraph snapshotを読み込むが、PageRank・OD・距離・類似度を再計算しない。
- Queryは既存の`tools/compare_phases.py`へ委譲する。
- `st.cache_data` / `st.cache_resource`でprocessed dataとGraphをcacheする。
- Graphは選択Phase・選択範囲でlazy loadする。
- LLM説明はHard Facts・順位を変更しない。

## 起動後のデモQuery

- `広島市と都市特性が似ている都市は？`
- `広島市と人の行き来が最も多い都市は？`
- `福岡市に似ていて冬が比較的暖かい都市は？`
- `空港と新幹線の両方へのアクセスが良い都市は？`
- `福岡市に似ていて家賃が安く、災害リスクが低い都市は？`

最後の質問は、未収録条件を適当にランキングしないことを確認するためのプリセットです。
