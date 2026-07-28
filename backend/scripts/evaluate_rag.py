"""以固定 45 題測試集比較 v2 與 legacy RAG。"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from knowledge import retrieval as rag
from knowledge.common import BASE_DIR

DEFAULT_CASES = BASE_DIR / "tests" / "data" / "rag_gold_cases.json"
HIGH_SIGNAL_GARBAGE_MARKERS = {
    "log in",
    "view media gallery",
    "find us on",
    "privacy policy",
}


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    return ordered[index]


def evaluate_cases(cases: list[dict], version: str) -> dict:
    original_version = rag.RAG_INDEX_VERSION
    rag.RAG_INDEX_VERSION = version
    latencies = []
    route_passes = 0
    must_hit_passes = 0
    red_flag_total = 0
    red_flag_hits = 0
    noise_failures = 0
    details = []

    try:
        for case in cases:
            selected_routes = rag.select_routes(
                query=case["query"],
                primary_route=case["primary_route"],
                purpose=case["purpose"],
            )
            route_ok = set(case["expected_routes"]).issubset(selected_routes)
            route_passes += route_ok

            started = time.perf_counter()
            results = rag.retrieve(
                case["query"],
                primary_route=case["primary_route"],
                purpose=case["purpose"],
                final_k=6,
            )
            latencies.append((time.perf_counter() - started) * 1000)
            combined = " ".join(
                f"{item.get('title', '')} {item.get('text', '')}" for item in results
            ).casefold()
            must_hit = any(term.casefold() in combined for term in case["must_include_any"])
            must_hit_passes += must_hit
            noise_found = any(
                term.casefold() in combined
                for term in case["forbidden_terms"]
                if term.casefold() in HIGH_SIGNAL_GARBAGE_MARKERS
            )
            noise_failures += noise_found

            if case.get("red_flag"):
                red_flag_total += 1
                red_flag_hits += must_hit

            details.append(
                {
                    "id": case["id"],
                    "route_ok": route_ok,
                    "selected_routes": selected_routes,
                    "must_hit": must_hit,
                    "noise_found": noise_found,
                    "result_titles": [item.get("title", "") for item in results],
                }
            )
    finally:
        rag.RAG_INDEX_VERSION = original_version

    return {
        "version": version,
        "case_count": len(cases),
        "route_accuracy": round(route_passes / len(cases), 4),
        "recall_at_6": round(must_hit_passes / len(cases), 4),
        "red_flag_recall": round(red_flag_hits / red_flag_total, 4) if red_flag_total else None,
        "noise_failure_count": noise_failures,
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2),
            "p95": round(percentile_95(latencies), 2),
        },
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="執行 RAG 黃金測試")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--version", default="v2")
    parser.add_argument("--compare-legacy", action="store_true")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="未達紅旗、召回、雜訊或 P95 上線門檻時回傳失敗",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    reports = [evaluate_cases(cases, args.version)]
    if args.compare_legacy:
        reports.append(evaluate_cases(cases, "legacy"))

    result: dict[str, Any] = {"reports": reports}
    failures = []
    v2_report = reports[0]
    if v2_report["red_flag_recall"] != 1.0:
        failures.append("v2 red_flag_recall 必須為 1.0")
    if v2_report["noise_failure_count"] != 0:
        failures.append("v2 不得召回網站垃圾內容")
    if v2_report["route_accuracy"] != 1.0:
        failures.append("v2 route_accuracy 必須為 1.0")
    if len(reports) == 2:
        legacy_report = reports[1]
        if v2_report["recall_at_6"] < legacy_report["recall_at_6"]:
            failures.append("v2 Recall@6 低於 legacy")
        if v2_report["latency_ms"]["p95"] > legacy_report["latency_ms"]["p95"]:
            failures.append("v2 P95 latency 高於 legacy")
    result["acceptance_failures"] = failures
    result["passed"] = not failures
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.enforce and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
