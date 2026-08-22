#!/usr/bin/env python3
"""Measure representative load/query latency and peak RSS for Phase 1-3."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "phase3" / "data" / "processed" / "cross_phase_benchmark.json"

CHILD_CODE = r"""
import json
import resource
import statistics
import time

from app.executor import QueryExecutor

queries = json.loads(__QUERIES__)
started = time.perf_counter()
executor = QueryExecutor.from_processed_dir("data/processed")
load_ms = (time.perf_counter() - started) * 1000
timings = {}
statuses = {}
for query in queries:
    values = []
    for _ in range(3):
        query_started = time.perf_counter()
        result = executor.execute(query)
        values.append((time.perf_counter() - query_started) * 1000)
        statuses[query] = result.get("status")
    timings[query] = {
        "median_ms": statistics.median(values),
        "runs": values,
    }
max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rss_mb = max_rss / (1024 * 1024 if __import__("sys").platform == "darwin" else 1024)
print(json.dumps({
    "load_ms": load_ms,
    "query_timings": timings,
    "statuses": statuses,
    "max_rss_mb": rss_mb,
    "analysis_municipality_count": len(executor.municipalities),
    "search_municipality_count": len(
        getattr(executor, "search_municipalities", executor.municipalities)
    ),
    "environmental_metric_rows": len(
        getattr(executor, "environmental_metrics", [])
    ),
    "graph_nodes": executor.graph.number_of_nodes(),
    "graph_edges": executor.graph.number_of_edges(),
}, ensure_ascii=False))
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_phase(phase: str, queries: list[str]) -> dict[str, object]:
    phase_dir = ROOT / phase
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "."
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD_CODE.replace(
                "__QUERIES__",
                repr(json.dumps(queries, ensure_ascii=False)),
            ),
        ],
        cwd=phase_dir,
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{phase} benchmark failed: {completed.stderr.strip()}")
    return {"phase": phase, "queries": queries, **json.loads(completed.stdout)}


def write_report(output: Path, results: list[dict[str, object]]) -> dict[str, object]:
    report = {
        "generated_at": utc_now(),
        "method": {
            "load": "QueryExecutor.from_processed_dir(data/processed)",
            "query_runs": 3,
            "latency": "median of three in-process executions after load",
            "memory": "maximum resident set size reported by resource.getrusage",
            "environment": "same Phase 3 uv environment, phase-specific PYTHONPATH",
        },
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    phase_queries = {
        "phase1": ["広島市と都市特性が似ている都市は？", "広島市と人の行き来が最も多い都市は？"],
        "phase2": ["福岡市と都市特性が似ている都市は？", "全国主要都市で人流ハブ性が高い都市は？"],
        "phase3": [
            "福岡市に似ていて冬が比較的暖かい都市は？",
            "空港と新幹線の両方へのアクセスが良い都市は？",
        ],
    }
    results = [run_phase(phase, queries) for phase, queries in phase_queries.items()]
    report = write_report(args.output, results)
    print(
        json.dumps(
            {"output": str(args.output), "phases": len(report["results"])},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
