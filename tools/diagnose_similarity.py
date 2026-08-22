#!/usr/bin/env python3
"""Decompose Phase 1 -> Phase 2 similarity changes and feature contributions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("/tmp/pyconjp2026-mobility-kg-similarity-diagnostic.json")

CHILD_CODE = r"""
import json
import math

from app.analysis import _prepare_similarity_matrix, city_similarity
from app.executor import QueryExecutor

target_name = json.loads(__TARGET__)
candidate_names = json.loads(__CANDIDATES__)
executor = QueryExecutor.from_processed_dir("data/processed")
target_id = executor.city_index.resolve(target_name)
candidate_ids = {
    name: executor.city_index.resolve(name)
    for name in candidate_names
    if name in executor.city_index.city_names
}
result = city_similarity(
    executor.search_municipalities,
    target_id,
    feature_specs=executor.feature_specs,
    top_n=None,
)
ranking = result["ranking"]
ranking_by_id = {row["municipality_id"]: row for row in ranking}
matrix, transformations = _prepare_similarity_matrix(
    executor.search_municipalities,
    executor.feature_specs,
)
target_position = executor.search_municipalities.index[
    executor.search_municipalities["municipality_id"] == target_id
][0]
target_vector = matrix.loc[target_position].to_numpy(dtype=float)
feature_by_name = {
    item["feature"]: item for item in transformations
}

contributions = {}
for name, municipality_id in candidate_ids.items():
    position = executor.search_municipalities.index[
        executor.search_municipalities["municipality_id"] == municipality_id
    ][0]
    candidate_vector = matrix.loc[position].to_numpy(dtype=float)
    denominator = float(
        math.sqrt(float((target_vector * target_vector).sum()))
        * math.sqrt(float((candidate_vector * candidate_vector).sum()))
    )
    rows = []
    for index, feature in enumerate(matrix.columns):
        contribution = (
            float(target_vector[index] * candidate_vector[index] / denominator)
            if denominator > 0
            else 0.0
        )
        rows.append(
            {
                "feature": feature,
                "category": feature_by_name[feature]["category"],
                "standardized_target": float(target_vector[index]),
                "standardized_candidate": float(candidate_vector[index]),
                "cosine_contribution": contribution,
                "absolute_contribution": abs(contribution),
            }
        )
    rows.sort(key=lambda row: (-row["absolute_contribution"], row["feature"]))
    contributions[name] = {
        "municipality_id": municipality_id,
        "similarity": ranking_by_id.get(municipality_id, {}).get("similarity"),
        "top_positive": [
            row for row in sorted(
                rows, key=lambda row: (-row["cosine_contribution"], row["feature"])
            ) if row["cosine_contribution"] > 0
        ][:10],
        "top_negative": [
            row for row in sorted(
                rows, key=lambda row: (row["cosine_contribution"], row["feature"])
            ) if row["cosine_contribution"] < 0
        ][:10],
        "top_absolute": rows[:10],
    }

common_ids = json.loads(__COMMON_IDS__)
common_ranking = [
    row for row in ranking if row["municipality_id"] in set(common_ids)
]
print(json.dumps({
    "universe_count": len(executor.search_municipalities),
    "target": {"name": target_name, "municipality_id": target_id},
    "feature_count": result["feature_count"],
    "feature_selection": result["feature_selection"],
    "fit_population": "phase2_search_universe_100",
    "ranking_top5": ranking[:5],
    "common_city_projection_top5": common_ranking[:5],
    "candidate_scores": {
        name: ranking_by_id.get(municipality_id, {}).get("similarity")
        for name, municipality_id in candidate_ids.items()
    },
    "contributions": contributions,
}, ensure_ascii=False, allow_nan=False))
"""


def _run_phase(
    phase: str,
    *,
    target_name: str,
    candidate_names: list[str],
    common_ids: list[str] | None = None,
) -> dict[str, Any]:
    phase_dir = ROOT / phase
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "."
    code = (
        CHILD_CODE.replace("__TARGET__", repr(json.dumps(target_name, ensure_ascii=False)))
        .replace("__CANDIDATES__", repr(json.dumps(candidate_names, ensure_ascii=False)))
        .replace("__COMMON_IDS__", repr(json.dumps(common_ids or [], ensure_ascii=False)))
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=phase_dir,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _phase1_result(target_name: str, candidate_names: list[str]) -> dict[str, Any]:
    phase_dir = ROOT / "phase1"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "."
    code = r"""
import json
from app.analysis import city_similarity
from app.executor import QueryExecutor
executor = QueryExecutor.from_processed_dir("data/processed")
target_id = executor.city_index.resolve(json.loads(__TARGET__))
result = city_similarity(
    executor.municipalities,
    target_id,
    feature_specs=executor.feature_specs,
    top_n=None,
)
names = set(json.loads(__CANDIDATES__))
print(json.dumps({
    "universe_count": len(executor.municipalities),
    "target": {"name": json.loads(__TARGET__), "municipality_id": target_id},
    "feature_count": result["feature_count"],
    "feature_selection": result["feature_selection"],
    "ranking_top5": result["ranking"][:5],
    "candidate_scores": {
        row["name"]: row["similarity"]
        for row in result["ranking"]
        if row["name"] in names
    },
    "common_city_ids": executor.municipalities["municipality_id"].tolist(),
}, ensure_ascii=False, allow_nan=False))
"""
    code = (
        code.replace("__TARGET__", repr(json.dumps(target_name, ensure_ascii=False)))
        .replace("__CANDIDATES__", repr(json.dumps(candidate_names, ensure_ascii=False)))
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=phase_dir,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _markdown(report: dict[str, Any]) -> str:
    phase1 = report["phase1_fit20"]
    phase2 = report["phase2_fit100"]
    lines = [
        "# Phase 1→2 類似度感度診断",
        "",
        "## A-D分解",
        "",
        "| ケース | fit母集団 | 出力範囲 | 目的 |",
        "|---|---|---|---|",
        "| A | Phase 1の20都市 | 20都市 | Phase 1実装の基準値 |",
        "| B | Phase 2の100都市 | Phase 1共通都市 | fit母集団だけを100都市へ変更 |",
        "| C | Phase 2の100都市 | 100都市 | Phase 2 production値 |",
        "| D | Cの結果 | Phase 1共通都市 | Phase 2尺度で共通都市だけを見る |",
        "",
        "### 上位5",
        "",
        "| ケース | 1位 | 2位 | 3位 | 4位 | 5位 |",
        "|---|---|---|---|---|---|",
    ]
    rows = {
        "A: Phase1 fit20": phase1["ranking_top5"],
        "C: Phase2 fit100": phase2["ranking_top5"],
        "D: common projection": phase2["common_city_projection_top5"],
    }
    for label, ranking in rows.items():
        values = [f'{item["name"]} ({item["similarity"]:.6f})' for item in ranking]
        lines.append(f"| {label} | " + " | ".join(values + ["—"] * (5 - len(values))) + " |")
    lines.extend(["", "## 対象都市のスコア", ""])
    lines.append("| 都市 | A: fit20 | B/D: fit100尺度 | C順位 |")
    lines.append("|---|---:|---:|---:|")
    for name, score_a in phase1["candidate_scores"].items():
        score_c = phase2["candidate_scores"].get(name)
        rank_c = next(
            (
                row["rank"]
                for row in phase2["ranking_top5"]
                if row["name"] == name
            ),
            "top5外",
        )
        lines.append(
            f"| {name} | {score_a if score_a is not None else '対象外'} | "
            f"{score_c if score_c is not None else '対象外'} | {rank_c} |"
        )
    lines.extend(
        [
            "",
            "## 寄与度の見方",
            "",
            (
                "Phase 2の100都市fitで、標準化後ベクトルの各feature積を"
                "cosine分子へ寄与する値として表示する。"
            ),
            "これは因果効果ではなく、類似度計算におけるベクトル寄与の監査用分解である。",
            "",
        ]
    )
    for name, contribution in phase2["contributions"].items():
        lines.extend(
            [
                f"### 広島市 vs {name}",
                "",
                "| feature | category | contribution |",
                "|---|---|---:|",
            ]
        )
        for row in contribution["top_absolute"][:10]:
            lines.append(
                f'| `{row["feature"]}` | {row["category"]} | {row["cosine_contribution"]:.6f} |'
            )
        lines.append("")
    lines.extend(
        [
            "## 解釈",
            "",
            "- A→Dで差が残る場合、Phase 1とPhase 2/3の標準化母集団差が影響している。",
            "- BとDは同じPhase 2尺度の共通都市投影であり、候補追加そのものと尺度変更を切り分ける。",
            "- この診断はfeature selectionを自動変更しない。変更は別レビューとAcceptanceが必要。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(target_name: str, candidate_names: list[str], output: Path) -> dict[str, Any]:
    phase1 = _phase1_result(target_name, candidate_names)
    common_ids = phase1["common_city_ids"]
    phase2 = _run_phase(
        "phase2",
        target_name=target_name,
        candidate_names=candidate_names,
        common_ids=common_ids,
    )
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": target_name,
        "candidates": candidate_names,
        "phase1_fit20": phase1,
        "phase2_fit100": phase2,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    markdown_path = output.with_suffix(".md")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report), end="")
    print(f"\nJSON: {output}\nMarkdown: {markdown_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="広島市")
    parser.add_argument(
        "--candidates",
        nargs="+",
        default=["東京都区部", "福岡市", "岡山市"],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.target, args.candidates, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
