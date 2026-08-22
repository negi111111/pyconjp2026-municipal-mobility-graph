"""Streamlit UI for auditing Phase 1-3 graph and feature evolution."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.compare_phases import run as compare_phases  # noqa: E402
from tools.compare_phases import run_single_phase  # noqa: E402

from adapters import NODE_TYPES, PHASES, RELATIONS, PhaseRepository  # noqa: E402


@st.cache_data(show_spinner=False)
def cached_summary(phase: str) -> dict[str, Any]:
    return PhaseRepository(phase).summary()


@st.cache_resource(show_spinner=False)
def cached_repository(phase: str) -> PhaseRepository:
    return PhaseRepository(phase)


@st.cache_resource(show_spinner=False)
def cached_graph(phase: str):
    return cached_repository(phase).load_graph()


@st.cache_data(show_spinner=False)
def cached_municipalities(phase: str) -> pd.DataFrame:
    return cached_repository(phase).load_municipalities()


@st.cache_data(show_spinner=False)
def cached_inspector(phase: str, municipality_id: str) -> dict[str, Any]:
    return cached_repository(phase).inspector(municipality_id)


@st.cache_data(show_spinner=False)
def cached_graph_view(
    phase: str,
    relation_filter: tuple[str, ...],
    node_type_filter: tuple[str, ...],
    selected_id: str | None,
    region: str | None,
    max_nodes: int,
    top_edges: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return cached_repository(phase).graph_view(
        relation_filter=set(relation_filter),
        node_type_filter=set(node_type_filter),
        selected_id=selected_id,
        region=region,
        max_nodes=max_nodes,
        top_edges=top_edges,
    )


def _phase_label(phase: str) -> str:
    return {"phase1": "Phase 1", "phase2": "Phase 2", "phase3": "Phase 3"}[phase]


def _relation_label(relation: str) -> str:
    return {
        "IS_IN": "行政所属",
        "COMMUTES_TO": "通勤",
        "STUDIES_IN": "通学",
        "ACCESS_TO": "空港アクセス",
    }.get(relation, relation)


def _node_type_label(node_type: str) -> str:
    return {
        "Municipality": "自治体",
        "Prefecture": "都道府県",
        "Airport": "空港",
    }.get(node_type, node_type)


def _render_architecture_flow() -> None:
    st.subheader("データから回答までの全体構成")
    st.caption(
        "通常のデモでは非表示にできます。表示時は、計算結果とLLM補足の境界を確認できます。"
    )
    st.markdown(
        """
        <div style="align-items:stretch;display:flex;flex-wrap:wrap;gap:.55rem;
                    justify-content:center;margin:1rem 0">
          <div style="background:#fff7d6;border:2px solid #e0b400;border-radius:10px;
                      flex:1 1 130px;padding:.75rem;text-align:center">
            <strong>公開データ</strong><br><small>SSDSE / OD / 空港<br>気候 / 新幹線</small>
          </div>
          <div style="align-items:center;display:flex;font-size:1.5rem">→</div>
          <div style="background:#e7f3fb;border:2px solid #2f80ed;border-radius:10px;
                      flex:1 1 130px;padding:.75rem;text-align:center">
            <strong>Planner</strong><br><small>意図・都市・条件<br>Rule / LLM</small>
          </div>
          <div style="align-items:center;display:flex;font-size:1.5rem">→</div>
          <div style="background:#e8f7ef;border:2px solid #28a36a;border-radius:10px;
                      flex:1 1 150px;padding:.75rem;text-align:center">
            <strong>Executor</strong><br><small>pandas / NetworkX<br>Query計算</small>
          </div>
          <div style="align-items:center;display:flex;font-size:1.5rem">→</div>
          <div style="background:#e8f7ef;border:2px solid #28a36a;border-radius:10px;
                      flex:1 1 150px;padding:.75rem;text-align:center">
            <strong>Hard Facts</strong><br><small>順位・数値・距離<br>Structured Evidence</small>
          </div>
          <div style="align-items:center;display:flex;font-size:1.5rem">→</div>
          <div style="background:#f0ebff;border:2px solid #7b61ff;border-radius:10px;
                      flex:1 1 150px;padding:.75rem;text-align:center">
            <strong>LLM Response</strong><br><small>説明・Soft Knowledge<br>順位変更なし</small>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "ランキング・数値・Graph factは公開データ＋Python計算。"
        " LLMは意図解釈と説明だけを担当し、retrievers_used=[]です。"
    )


def _node_color(node_type: str) -> str:
    return {
        "Municipality": "#2f80ed",
        "Prefecture": "#f0ad4e",
        "Airport": "#28a36a",
    }.get(node_type, "#8b98a8")


def _render_phase_evolution() -> None:
    st.header("フェーズ比較")
    st.write("Phase 1→2→3で探索空間、Graph、Feature、Query能力がどう増えたかを確認します。")
    summaries = {phase: cached_summary(phase) for phase in PHASES}
    columns = st.columns(3)
    for column, phase in zip(columns, PHASES, strict=True):
        summary = summaries[phase]
        with column:
            st.subheader(_phase_label(phase))
            st.metric("検索対象都市", summary["search_universe_count"])
            st.metric("分析対象自治体", summary["analysis_universe_count"])
            st.metric("Graphノード", summary["graph_node_count"])
            st.metric("Graphエッジ", summary["graph_edge_count"])
    chart_data = pd.DataFrame(
        [
            {
                "phase": _phase_label(phase),
                "検索対象": summaries[phase]["search_universe_count"],
                "分析対象": summaries[phase]["analysis_universe_count"],
            }
            for phase in PHASES
        ]
    ).melt(id_vars="phase", var_name="metric", value_name="count")
    st.plotly_chart(
        px.bar(chart_data, x="phase", y="count", color="metric", barmode="group"),
        width="stretch",
    )
    comparison = pd.DataFrame(
        [
            {
                "Phase": _phase_label(phase),
                "検索対象": summary["search_universe_count"],
                "分析対象": summary["analysis_universe_count"],
                "ノード": summary["graph_node_count"],
                "エッジ": summary["graph_edge_count"],
                "Relation": ", ".join(
                    _relation_label(relation) for relation in sorted(summary["relation_counts"])
                ),
                "Feature": " / ".join(summary["features"]),
            }
            for phase, summary in summaries.items()
        ]
    )
    st.dataframe(comparison, width="stretch", hide_index=True)
    st.subheader("フェーズ間の追加機能")
    st.info(
        "Phase 1→2：全国分析・100都市検索・地域/人口条件を追加。"
        " Phase 2→3：Graph構造は同じで、気候・新幹線Featureと明示条件を追加。"
    )


def _render_graph_explorer() -> None:
    st.header("グラフ探索")
    st.write("実際のGraph snapshotだけを描画します。Phase 2/3は検索対象100都市を既定にします。")
    st.session_state.setdefault("graph_phase", st.session_state.get("selected_phase", "phase3"))
    phase = st.selectbox("対象フェーズ", PHASES, format_func=_phase_label, key="graph_phase")
    municipalities = cached_municipalities(phase)
    available_regions = (
        sorted(str(value) for value in municipalities["region"].dropna().unique())
        if "region" in municipalities
        else []
    )
    region_options = ["すべて", *available_regions]
    if st.session_state.get("_graph_filter_version") != 2:
        st.session_state.pop("graph_relations", None)
        st.session_state.pop("graph_region", None)
        st.session_state["_graph_filter_version"] = 2
    if st.session_state.get("graph_region") not in region_options:
        st.session_state["graph_region"] = "すべて"
    with st.sidebar:
        st.subheader("グラフ絞り込み")
        relation_kwargs = (
            {} if "graph_relations" in st.session_state else {"default": list(RELATIONS)}
        )
        relation_filter = st.multiselect(
            "表示する関係",
            RELATIONS,
            format_func=_relation_label,
            key="graph_relations",
            **relation_kwargs,
        )
        node_type_filter = st.multiselect(
            "表示するノード種別",
            NODE_TYPES,
            default=["Municipality", "Prefecture", "Airport"],
            format_func=_node_type_label,
            key="graph_node_types",
        )
        region = st.selectbox("地域", region_options, key="graph_region")
        max_nodes = st.slider("最大ノード数", 20, 250, 80, 10)
        top_edges = st.slider("最大エッジ数", 20, 350, 120, 10)
    selected_id = st.session_state.get("selected_node")
    nodes, edges = cached_graph_view(
        phase,
        tuple(relation_filter),
        tuple(node_type_filter),
        selected_id,
        None if region == "すべて" else region,
        max_nodes,
        top_edges,
    )
    displayed_municipalities = sum(
        node["node_type"] == "Municipality" for node in nodes
    )
    st.info(
        f"現在のGraph表示：{_phase_label(phase)} / 地域={region} / "
        f"自治体{displayed_municipalities}件 / ノード{len(nodes)}件 / エッジ{len(edges)}件"
    )
    st.caption(f"表示ノード {len(nodes)} / 表示エッジ {len(edges)}")
    graph_nodes = [
        Node(
            id=row["id"],
            title=f'{_node_type_label(row["node_type"])}：{row["label"]}',
            label=row["label"],
            size=24 if row["id"] == selected_id else 18,
            color=_node_color(row["node_type"]),
            shape="diamond" if row["node_type"] == "Prefecture" else "dot",
        )
        for row in nodes
    ]
    graph_edges = [
        Edge(
            source=row["source"],
            target=row["target"],
            label=_relation_label(row["relation"]),
            title=f'{_relation_label(row["relation"])} / weight {row["weight"]:,.0f}',
            width=max(1, min(8, 1 + row["weight"] ** 0.5 / 50)),
        )
        for row in edges
    ]
    if not graph_nodes:
        st.warning("条件に一致するGraph nodeがありません。")
        return
    config = Config(
        width=900,
        height=600,
        directed=True,
        physics=True,
        hierarchical=False,
        solver="repulsion",
        minVelocity=0.5,
        timestep=0.35,
        nodeHighlightBehavior=True,
        highlightColor="#F7A7A6",
        collapsible=False,
    )
    config.physics["repulsion"] = {
        "nodeDistance": 180,
        "centralGravity": 0.08,
        "springLength": 220,
        "springConstant": 0.04,
        "damping": 0.12,
    }
    clicked = agraph(nodes=graph_nodes, edges=graph_edges, config=config)
    if clicked:
        st.session_state["selected_node"] = str(clicked)
        st.session_state["selected_phase"] = phase
        st.session_state["inspector_phase"] = phase
        st.rerun()
    if selected_id:
        st.info(f"選択中：{selected_id}（「都市情報」画面で詳細を確認できます）")


def _render_node_inspector() -> None:
    st.header("都市情報")
    st.session_state.setdefault(
        "inspector_phase", st.session_state.get("selected_phase", "phase3")
    )
    phase = st.selectbox("対象フェーズ", PHASES, format_func=_phase_label, key="inspector_phase")
    graph = cached_graph(phase)
    selected_graph_node = st.session_state.get("selected_node")
    selected_type = (
        graph.nodes[selected_graph_node].get(
            "node_type", graph.nodes[selected_graph_node].get("type", "Unknown")
        )
        if selected_graph_node in graph
        else None
    )
    if selected_type and selected_type != "Municipality":
        result = cached_inspector(phase, selected_graph_node)
        st.subheader(result["basic"].get("name", result["basic"].get("label", selected_graph_node)))
        st.caption(f"ノード種別：{_node_type_label(selected_type)}")
        with st.expander("技術情報", expanded=True):
            st.json(result["basic"])
        with st.expander("接続関係", expanded=True):
            st.dataframe(
                pd.DataFrame(result["connections"]),
                width="stretch",
                hide_index=True,
            )
        return
    municipalities = cached_municipalities(phase)
    records = municipalities[["municipality_id", "name", "prefecture"]].copy()
    records["municipality_id"] = records["municipality_id"].astype(str)
    selected = st.session_state.get("selected_node")
    default_index = (
        records.index[records["municipality_id"].eq(str(selected))].tolist()[:1] or [0]
    )[0]
    selected_id = st.selectbox(
        "自治体",
        records["municipality_id"].tolist(),
        index=default_index,
        format_func=lambda value: str(
            records.loc[records["municipality_id"].eq(value), "name"].iloc[0]
        ),
    )
    st.session_state["selected_node"] = selected_id
    result = cached_inspector(phase, selected_id)
    st.subheader(result["basic"].get("name", selected_id))
    with st.expander("技術情報", expanded=False):
        st.json(result["basic"])
    for title, key in (
        ("人口・世帯", "demographics"),
        ("SSDSE原指標", "ssdse"),
        ("都市特性Feature", "features"),
        ("人流・中心性", "mobility"),
        ("空港アクセス", "airport"),
        ("Phase 3環境Feature", "phase3_features"),
        ("気象観測所", "weather_station"),
        ("新幹線アクセス", "shinkansen"),
    ):
        value = result.get(key)
        if value:
            with st.expander(title, expanded=key in {"phase3_features", "shinkansen"}):
                if key == "ssdse":
                    st.dataframe(pd.DataFrame(value), width="stretch", hide_index=True)
                else:
                    st.json(value)


def _render_query_comparison() -> None:
    st.header("クエリ比較")
    st.write("自然言語Queryを選択したPhaseまたはPhase 1〜3へ渡し、回答と根拠を確認します。")
    st.session_state.setdefault("chat_history", [])
    for message in st.session_state["chat_history"][-6:]:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    mode = st.radio(
        "実行対象",
        ["選択したPhaseのみ", "Phase 1〜3を比較"],
        horizontal=True,
        key="query_mode",
    )
    selected_phase = st.selectbox(
        "対象Phase",
        PHASES,
        format_func=_phase_label,
        disabled=mode != "選択したPhaseのみ",
        key="query_phase",
    )
    presets = {
        "自由入力": "",
        "Phase 1→2の類似度差": "広島市と都市特性が似ている都市は？",
        "人流の関係": "広島市と人の行き来が最も多い都市は？",
        "Phase 3の気候": "福岡市に似ていて冬が比較的暖かい都市は？",
        "Phase 3の交通": "空港と新幹線の両方へのアクセスが良い都市は？",
        "未収録条件": "福岡市に似ていて家賃が安く、災害リスクが低い都市は？",
    }
    preset = st.selectbox("デモ用Query", list(presets), key="query_preset")
    manual_query = st.chat_input("自然言語で質問を入力してEnter")
    preset_query = presets[preset]
    if preset_query:
        st.info(f"選択中のQuery：{preset_query}")
        run_preset = st.button("選択したQueryを実行", type="primary")
    else:
        run_preset = False
    col1, col2 = st.columns(2)
    with col1:
        phase_llm = st.checkbox("各PhaseのLLM Planner/Responseを使用", value=False)
    with col2:
        comparison_llm = st.checkbox(
            "比較結果をLLMで考察（比較モードのみ）",
            value=False,
            disabled=mode != "Phase 1〜3を比較",
        )
    query = manual_query or (preset_query if run_preset else "")
    if query.strip():
        output_dir = Path(tempfile.gettempdir()) / "pyconjp2026-mobility-kg-visualizer"
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                if mode == "Phase 1〜3を比較":
                    report = compare_phases(
                        query.strip(),
                        phase_llm=phase_llm or comparison_llm,
                        llm_analysis=comparison_llm,
                        output_dir=output_dir,
                    )
                else:
                    payload = run_single_phase(
                        selected_phase,
                        query.strip(),
                        use_llm=phase_llm,
                    )
                    report = {
                        "query": query.strip(),
                        "phase_results": {selected_phase: payload},
                        "deterministic_comparison": None,
                        "llm_analysis": None,
                    }
            st.session_state["comparison_report"] = report
            st.session_state["chat_history"].append(
                {"role": "user", "content": query.strip()}
            )
            statuses = " / ".join(
                f"{_phase_label(phase)}: {payload['result'].get('status')}"
                for phase, payload in report["phase_results"].items()
            )
            st.session_state["chat_history"].append(
                {"role": "assistant", "content": f"実行結果：{statuses}"}
            )
        except Exception as exc:
            st.error(f"Query実行に失敗しました：{exc}")
    report = st.session_state.get("comparison_report")
    if not report:
        st.info("Queryを入力するか、デモ用Queryを選択して実行してください。")
        return
    result_phases = list(report["phase_results"])
    columns = st.columns(len(result_phases))
    candidate_options = []
    for column, phase in zip(columns, result_phases, strict=True):
        payload = report["phase_results"][phase]
        result = payload["result"]
        with column:
            st.subheader(_phase_label(phase))
            st.write(f"状態：`{result.get('status')}`")
            st.write(f"Intent：`{(result.get('plan') or {}).get('intent')}`")
            st.caption("ランキング・数値：公開データ＋pandas / NetworkX")
            st.text(payload["rendered_response"])
            for row in (result.get("hard_facts") or {}).get("ranking") or []:
                candidate_options.append(
                    (f"{_phase_label(phase)}：{row.get('name')}", phase, row.get("municipality_id"))
                )
            with st.expander("分析結果の詳細"):
                st.json(result)
            boundary = result.get("provenance_boundary") or {}
            st.caption(
                f"実行経路：{' → '.join(boundary.get('execution_path', []))}\n"
                f"retrievers：{boundary.get('retrievers_used', [])}"
            )
            llm_response = result.get("llm_response") or {}
            if llm_response.get("evidence_explanation"):
                with st.expander("AIによる説明"):
                    st.write(llm_response["evidence_explanation"])
                    st.caption(
                        f"数値整合性："
                        f"{(llm_response.get('numeric_claim_check') or {}).get('status', '未確認')}"
                    )
    if candidate_options:
        labels = ["選択しない", *[item[0] for item in candidate_options]]
        selected_candidate = st.selectbox("回答候補をGraph/都市情報で確認", labels)
        if selected_candidate != "選択しない" and st.button("選択候補を表示"):
            selected = next(item for item in candidate_options if item[0] == selected_candidate)
            st.session_state["selected_phase"] = selected[1]
            st.session_state["selected_node"] = selected[2]
            st.session_state["graph_phase"] = selected[1]
            st.session_state["inspector_phase"] = selected[1]
            st.info("グラフ探索・都市情報タブに選択候補を反映しました。")
    if report.get("deterministic_comparison"):
        st.subheader("機械的な差分")
        st.json(report["deterministic_comparison"])
        st.info(
            "Phase 1→2は探索母集団と標準化母集団が変化。"
            " Phase 2→3はcore similarityを維持し、環境Featureを明示条件で追加。"
        )
    if report.get("llm_analysis"):
        st.subheader("LLMによる比較考察")
        st.write(report["llm_analysis"]["overall_comparison"])
        with st.expander("考察の詳細"):
            st.json(report["llm_analysis"])


def _render_diagnostics() -> None:
    st.header("診断情報")
    for phase in PHASES:
        summary = cached_summary(phase)
        with st.expander(_phase_label(phase)):
            st.json(
                {
                    "graph": {
                        "nodes": summary["graph_node_count"],
                        "edges": summary["graph_edge_count"],
                    },
                    "analysis_universe": summary["analysis_universe_count"],
                    "search_universe": summary["search_universe_count"],
                    "coverage": summary["coverage"],
                    "capabilities": summary["capabilities"],
                }
            )


def main() -> None:
    st.set_page_config(
        page_title="Phase 1-3 Mobility KG Visualizer",
        page_icon="🗺️",
        layout="wide",
    )
    st.title("Phase 1〜3 地域探索 Knowledge Graph")
    st.caption(
        "既存のGraph / Feature Store / Query結果を監査するローカルUI。"
        "分析値はこのUIで再計算しません。"
    )
    if st.toggle("システム構成とLLM境界を表示", value=False):
        _render_architecture_flow()
    with st.expander("フェーズ比較（全体の成長）", expanded=False):
        _render_phase_evolution()
    query_column, graph_column = st.columns([1.05, 1.35], gap="large")
    with query_column:
        _render_query_comparison()
    with graph_column:
        _render_graph_explorer()
    with st.expander("都市情報（選択したノード）", expanded=True):
        _render_node_inspector()
    with st.expander("診断情報", expanded=False):
        _render_diagnostics()


if __name__ == "__main__":
    main()
