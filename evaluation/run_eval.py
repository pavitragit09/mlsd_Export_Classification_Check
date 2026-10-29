"""Evaluation benchmark runner (L2/L3 Evaluation).

Computes:
1. Route accuracy
2. Heading accuracy
3. Escalation correctness (out-of-scope & ambiguous)
4. Groundedness (% of citations grounded in retrieved passages)
5. Context relevance (% of retrieved passages used in citations)
6. Faithfulness (% of proposals fully backed by evidence)
7. Hallucination rate (% of citations not in regulatory corpus)

Usage:
  python -m evaluation.run_eval --prompt-version classifier_v3
  python -m evaluation.run_eval --prompt-version classifier_v1 --limit 5
  python -m evaluation.run_eval --prompt-version classifier_v3 --no-verifier-retry
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.graph import compiled_graph, GraphState
from agents.verifier import _citation_to_clause_id
from common.config import settings
from retrieval.faiss_loader import index_manager


def run_evaluation(
    eval_file: str = "tests/eval_set.jsonl",
    prompt_version: str = "classifier_v3",
    output_file: Optional[str] = None,
    limit: Optional[int] = None,
    timeout_sec: float = 60.0,
    verifier_retry: bool = True,
) -> Dict[str, Any]:
    """Runs scenarios from eval_file through the classification agent workflow with per-scenario timeout."""
    if not os.path.exists(eval_file):
        print(f"Error: Eval file '{eval_file}' not found.")
        sys.exit(1)

    if output_file is None:
        retry_tag = "" if verifier_retry else "_no_retry"
        output_file = f"evaluation/eval_results_{prompt_version}{retry_tag}.json"

    # Set verifier retry mode in environment
    os.environ["VERIFIER_RETRY_ENABLED"] = "true" if verifier_retry else "false"

    scenarios: List[Dict[str, Any]] = []
    with open(eval_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                scenarios.append(json.loads(line))

    if limit and limit > 0:
        scenarios = scenarios[:limit]

    print(f"\n========================================================")
    print(f"Running Classification Evaluation Benchmark")
    print(f"Dataset         : {eval_file} ({len(scenarios)} scenarios)")
    print(f"Prompt Version  : {prompt_version}")
    print(f"Active Provider : {settings.LLM_PROVIDER}")
    print(f"Verifier Retry  : {'ENABLED' if verifier_retry else 'DISABLED'}")
    print(f"Per-Item Timeout: {timeout_sec}s")
    print(f"Output File     : {output_file}")
    print(f"========================================================\n")

    results: List[Dict[str, Any]] = []

    valid_clause_ids = set(index_manager._clause_map.keys())

    t0 = time.perf_counter()

    for idx, sc in enumerate(scenarios, start=1):
        sc_id = sc.get("id", f"scenario_{idx:02d}")
        desc = sc["description"]
        materials = sc.get("materials", [])
        intended_use = sc.get("intended_use")
        expected_route = sc.get("expected_route")
        expected_heading = sc.get("expected_heading")

        initial_state = GraphState(
            run_id=f"eval_{sc_id}_{int(time.time())}",
            correlation_id=f"eval-corr-{sc_id}",
            request_data={
                "description": desc,
                "materials": materials,
                "intended_use": intended_use,
            },
            prompt_version=prompt_version,
        )

        item_t0 = time.perf_counter()
        final_state = None
        error_msg = None

        # Execute single scenario with bounded timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(compiled_graph.invoke, initial_state)
            try:
                final_state = future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                error_msg = f"Per-scenario timeout of {timeout_sec}s exceeded"
            except Exception as e:
                error_msg = str(e)

        item_duration = round(time.perf_counter() - item_t0, 3)

        if final_state is not None:
            res = final_state.get("final_result", {}) if isinstance(final_state, dict) else getattr(final_state, "final_result", {})
            retrieved = final_state.get("retrieved_passages", []) if isinstance(final_state, dict) else getattr(final_state, "retrieved_passages", [])
        else:
            res = {
                "route": "specialist-classification-review",
                "resolved_heading": None,
                "basis": f"Evaluation error: {error_msg}",
                "citations": [],
            }
            retrieved = []

        pred_route = res.get("route")
        pred_heading = res.get("resolved_heading")
        pred_citations = res.get("citations", [])

        # 1. Route accuracy
        is_route_correct = (pred_route == expected_route)

        # 2. Heading accuracy
        is_heading_correct = None
        if expected_heading:
            is_heading_correct = (str(pred_heading) == str(expected_heading))

        # 3. Groundedness & Relevance calculation
        # Identify retrieved clause IDs and texts
        retrieved_ids = {
            str(p.get("clause_id", "")).strip().upper()
            for p in retrieved
            if p.get("clause_id")
        }
        retrieved_text_blob = " ".join([
            str(p.get("text", "")) + " " + str(p.get("title", "")) + " " + str(p.get("clause_id", ""))
            for p in retrieved
        ]).lower()

        grounded_citations_count = 0
        hallucinated_citations_count = 0
        cited_passages_count = 0

        for cit in pred_citations:
            cit_str = str(cit).strip()
            cit_upper = cit_str.upper()
            norm_id = _citation_to_clause_id(cit_str) or ""

            # Check if grounded in retrieved passages
            is_grounded = (
                cit_upper in retrieved_ids
                or norm_id.upper() in retrieved_ids
                or cit_str.lower() in retrieved_text_blob
            )
            if is_grounded:
                grounded_citations_count += 1

            # Check if legal citation exists anywhere in statutory corpus
            in_corpus = (
                cit_upper in valid_clause_ids
                or norm_id.upper() in valid_clause_ids
                or any(v in cit_upper for v in ["HEADING", "GRI", "NOTE", "DGFT", "CHAPTER", "POLICY"])
            )
            if not in_corpus:
                hallucinated_citations_count += 1

        # Context relevance: how many retrieved passages were relevant (cited)
        for p in retrieved:
            p_id = str(p.get("clause_id", "")).strip().upper()
            if any(p_id in str(c).upper() or _citation_to_clause_id(str(c)) == p_id for c in pred_citations):
                cited_passages_count += 1

        total_cits = len(pred_citations)
        item_groundedness = (grounded_citations_count / total_cits * 100) if total_cits > 0 else (100.0 if pred_route != "clear-for-filing" else 0.0)
        item_context_rel = (cited_passages_count / len(retrieved) * 100) if len(retrieved) > 0 else 0.0
        item_faithfulness = (grounded_citations_count == total_cits) if total_cits > 0 else True

        item_result = {
            "id": sc_id,
            "category": sc.get("category", "general"),
            "description": desc[:60] + "..." if len(desc) > 60 else desc,
            "expected_route": expected_route,
            "predicted_route": pred_route,
            "route_match": is_route_correct,
            "expected_heading": expected_heading,
            "predicted_heading": pred_heading,
            "heading_match": is_heading_correct,
            "citations": pred_citations,
            "total_citations": total_cits,
            "grounded_citations": grounded_citations_count,
            "groundedness_pct": round(item_groundedness, 1),
            "retrieved_passages_count": len(retrieved),
            "context_relevance_pct": round(item_context_rel, 1),
            "faithful": item_faithfulness,
            "hallucinations_count": hallucinated_citations_count,
            "duration_sec": item_duration,
        }
        results.append(item_result)

        status_sym = "[OK]" if is_route_correct and (is_heading_correct in [True, None]) else "[FAIL]"
        print(f"{idx:02d}. {status_sym} {sc_id:<32} Route: {pred_route:<32} Heading: {str(pred_heading):<6} ({item_duration:.2f}s)")

        # Compute running metrics and stream to disk after every scenario
        _write_summary(
            output_file=output_file,
            prompt_version=prompt_version,
            eval_file=eval_file,
            results=results,
            total_target=len(scenarios),
            elapsed=time.perf_counter() - t0,
            verifier_retry=verifier_retry,
        )

    total_time = time.perf_counter() - t0
    final_summary = _write_summary(
        output_file=output_file,
        prompt_version=prompt_version,
        eval_file=eval_file,
        results=results,
        total_target=len(scenarios),
        elapsed=total_time,
        verifier_retry=verifier_retry,
    )

    print(f"\n========================================================")
    print(f"Evaluation Benchmark Summary")
    print(f"========================================================")
    print(f"Total Scenarios Evaluated  : {len(results)}")
    print(f"Total Execution Duration   : {total_time:.2f}s")
    print(f"Route Accuracy             : {final_summary['metrics']['route_accuracy_pct']}%")
    print(f"Heading Accuracy           : {final_summary['metrics']['heading_accuracy_pct']}%")
    print(f"Groundedness               : {final_summary['metrics']['groundedness_pct']}%")
    print(f"Context Relevance          : {final_summary['metrics']['context_relevance_pct']}%")
    print(f"Faithfulness Rate          : {final_summary['metrics']['faithfulness_rate_pct']}%")
    print(f"Hallucination Rate         : {final_summary['metrics']['hallucination_rate_pct']}%")
    print(f"Results streamed to        : {output_file}")
    print(f"========================================================\n")

    return final_summary


def _write_summary(
    output_file: str,
    prompt_version: str,
    eval_file: str,
    results: List[Dict[str, Any]],
    total_target: int,
    elapsed: float,
    verifier_retry: bool,
) -> Dict[str, Any]:
    n = len(results)
    if n == 0:
        return {}

    route_correct = sum(1 for r in results if r["route_match"])
    evaluated_headings = [r for r in results if r["expected_heading"] is not None]
    heading_correct = sum(1 for r in evaluated_headings if r["heading_match"])

    escalation_items = [r for r in results if r["expected_route"] in ["specialist-classification-review", "seek-product-clarification"]]
    escalation_correct = sum(1 for r in escalation_items if r["route_match"])

    clear_items = [r for r in results if r["predicted_route"] == "clear-for-filing"]
    total_citations = sum(r["total_citations"] for r in clear_items)
    grounded_citations = sum(r["grounded_citations"] for r in clear_items)
    hallucinated_citations = sum(r["hallucinations_count"] for r in results)

    route_acc = (route_correct / n) * 100
    heading_acc = (heading_correct / len(evaluated_headings) * 100) if evaluated_headings else 100.0
    escalation_acc = (escalation_correct / len(escalation_items) * 100) if escalation_items else 100.0
    groundedness = (grounded_citations / total_citations * 100) if total_citations > 0 else 100.0
    
    avg_context_rel = (sum(r["context_relevance_pct"] for r in clear_items) / len(clear_items)) if clear_items else 100.0
    faithfulness = (sum(1 for r in clear_items if r["faithful"]) / len(clear_items) * 100) if clear_items else 100.0
    hallucination_rate = (hallucinated_citations / total_citations * 100) if total_citations > 0 else 0.0

    summary = {
        "benchmark_run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_version": prompt_version,
        "llm_provider": settings.LLM_PROVIDER,
        "verifier_retry_enabled": verifier_retry,
        "total_scenarios_evaluated": n,
        "total_target_scenarios": total_target,
        "duration_seconds": round(elapsed, 2),
        "metrics": {
            "route_accuracy_pct": round(route_acc, 1),
            "heading_accuracy_pct": round(heading_acc, 1),
            "escalation_correctness_pct": round(escalation_acc, 1),
            "groundedness_pct": round(groundedness, 1),
            "context_relevance_pct": round(avg_context_rel, 1),
            "faithfulness_rate_pct": round(faithfulness, 1),
            "hallucination_rate_pct": round(hallucination_rate, 1),
        },
        "counts": {
            "route_correct": route_correct,
            "heading_evaluated": len(evaluated_headings),
            "heading_correct": heading_correct,
            "escalation_scenarios": len(escalation_items),
            "escalation_correct": escalation_correct,
            "clear_for_filing": len(clear_items),
            "total_citations": total_citations,
            "grounded_citations": grounded_citations,
            "hallucinated_citations": hallucinated_citations,
        },
        "detailed_results": results,
    }

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Evaluate Classification Agent against test scenarios.")
    parser.add_argument("--eval-file", default="tests/eval_set.jsonl", help="Path to jsonl eval set")
    parser.add_argument("--prompt-version", default="classifier_v3", help="Prompt version tag")
    parser.add_argument("--output-file", default=None, help="Path to save output results")
    parser.add_argument("--limit", type=int, default=None, help="Maximum scenarios to evaluate")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-scenario timeout in seconds")
    parser.add_argument(
        "--verifier-retry",
        dest="verifier_retry",
        action="store_true",
        default=True,
        help="Enable verifier fetch-by-ID retry",
    )
    parser.add_argument(
        "--no-verifier-retry",
        dest="verifier_retry",
        action="store_false",
        help="Disable verifier fetch-by-ID retry for ablation",
    )

    args = parser.parse_args()
    run_evaluation(
        eval_file=args.eval_file,
        prompt_version=args.prompt_version,
        output_file=args.output_file,
        limit=args.limit,
        timeout_sec=args.timeout,
        verifier_retry=args.verifier_retry,
    )


if __name__ == "__main__":
    main()
