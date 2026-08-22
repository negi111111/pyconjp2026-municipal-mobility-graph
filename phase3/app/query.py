"""Command-line entry point for Phase 3 natural-language city exploration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .executor import QueryExecutor
from .llm import AzureOpenAIChatClient, AzureOpenAIError, AzureOpenAIPlanner, AzureOpenAIResponse
from .response import attach_response_supplement, render_response

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def run_query(
    query: str,
    *,
    processed_data: str | Path = DEFAULT_PROCESSED_DIR,
    similarity_config: str | Path | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Load processed data and execute one question."""

    executor = QueryExecutor.from_processed_dir(
        processed_data,
        similarity_config=similarity_config,
    )
    planner = None
    response_provider = None
    if use_llm:
        client = AzureOpenAIChatClient.from_environment()
        planner = AzureOpenAIPlanner(client)
        response_provider = AzureOpenAIResponse(client)

    result = executor.execute(query, planner_provider=planner)
    if response_provider is not None and result.get("hard_facts") is not None:
        result = attach_response_supplement(result, response_provider)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 3の構造化データをpandas/NetworkXで分析し、"
            "日本語の質問に根拠付きで答えます。"
        )
    )
    parser.add_argument("--query", required=True, help="例: 広島市と一番人の行き来が多い都市は？")
    parser.add_argument(
        "--processed-data",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"処理済みParquetのディレクトリ（既定: {DEFAULT_PROCESSED_DIR}）",
    )
    parser.add_argument(
        "--similarity-config",
        type=Path,
        help="類似度FeatureSpec YAML。省略時はconfigs/similarity_features.ymlを自動検出。",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Azure OpenAIでQuery Plannerと回答説明を実行（数値計算はローカル）。",
    )
    parser.add_argument("--json", action="store_true", help="Structured EvidenceをJSONで出力")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_query(
            args.query,
            processed_data=args.processed_data,
            similarity_config=args.similarity_config,
            use_llm=args.llm,
        )
    except (AzureOpenAIError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"クエリを実行できません: {exc}") from exc

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(render_response(result))
    return 0 if result.get("status") not in {"cannot_execute"} else 2


if __name__ == "__main__":  # pragma: no cover - exercised via ``python -m``.
    raise SystemExit(main())


__all__ = ["DEFAULT_PROCESSED_DIR", "build_parser", "main", "run_query"]
