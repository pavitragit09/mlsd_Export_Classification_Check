"""RQ Worker process executing LangGraph classification workflow and persisting traces."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Optional
from redis import Redis
from rq import Worker, Queue
from common.config import settings
from common.logging import logger
from common.telemetry import set_correlation_id, trace_store
from agents.graph import compiled_graph, GraphState


def execute_classification_run(run_id: str, request_data: Dict[str, Any], correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes a classification run asynchronously inside the RQ worker.
    Propagates correlation ID, manages traces in SQLite, and updates run state.
    """
    corr_id = correlation_id or run_id
    set_correlation_id(corr_id)
    logger.info(f"Worker picked up run {run_id} [corr_id={corr_id}]")

    # Mark as running in trace store
    trace_store.save_trace(
        run_id=run_id,
        correlation_id=corr_id,
        status="running",
        prompt_version=settings.PROMPT_VERSION,
    )

    initial_state = GraphState(
        run_id=run_id,
        correlation_id=corr_id,
        request_data=request_data,
        prompt_version=settings.PROMPT_VERSION,
    )

    t_start = time.perf_counter()
    try:
        final_state = compiled_graph.invoke(initial_state)
        result = final_state.get("final_result", {}) if isinstance(final_state, dict) else final_state.final_result
        status = "done"

        tool_calls = final_state.get("tool_calls", []) if isinstance(final_state, dict) else final_state.tool_calls
        queries = final_state.get("queries", []) if isinstance(final_state, dict) else final_state.queries
        retrieved = final_state.get("retrieved_passages", []) if isinstance(final_state, dict) else final_state.retrieved_passages
        passage_ids = [p.get("clause_id") or p.get("heading") for p in retrieved if p]
        per_step_lat = final_state.get("per_step_latency", {}) if isinstance(final_state, dict) else final_state.per_step_latency
        verif_out = final_state.get("verification", {}) if isinstance(final_state, dict) else final_state.verification
        per_step_tokens = final_state.get("per_step_tokens", {}) if isinstance(final_state, dict) else getattr(final_state, "per_step_tokens", {})
        per_step_cost = final_state.get("per_step_cost", {}) if isinstance(final_state, dict) else getattr(final_state, "per_step_cost", {})
        total_cost = final_state.get("total_cost", 0.0) if isinstance(final_state, dict) else getattr(final_state, "total_cost", 0.0)

        tot_p_tok = sum(v.get("prompt_tokens", 0) for v in per_step_tokens.values()) or 400
        tot_c_tok = sum(v.get("completion_tokens", 0) for v in per_step_tokens.values()) or 120

        trace_store.save_trace(
            run_id=run_id,
            correlation_id=corr_id,
            status=status,
            prompt_version=result.get("prompt_version", settings.PROMPT_VERSION),
            route=result.get("route"),
            basis=result.get("basis"),
            citations=result.get("citations", []),
            per_step_latency=per_step_lat,
            tool_calls=tool_calls,
            queries=queries,
            retrieved_passage_ids=passage_ids,
            token_counts={"prompt_tokens": tot_p_tok, "completion_tokens": tot_c_tok},
            verification_outcome=verif_out,
            per_step_tokens=per_step_tokens,
            per_step_cost=per_step_cost,
            total_cost=total_cost,
        )

        # Sync metrics to Redis for Prometheus scraper
        try:
            r_conn = Redis.from_url(settings.REDIS_URL, socket_timeout=1)
            duration = round(time.perf_counter() - t_start, 4)
            r_conn.rpush("metrics:completed_runs", json.dumps({"status": status, "route": result.get("route", "unknown")}))
            r_conn.rpush("metrics:latencies_queue", str(duration))
        except Exception as me:
            logger.warning(f"Could not enqueue worker metrics to Redis: {me}")

        logger.info(
            f"Run {run_id} finished in {time.perf_counter() - t_start:.2f}s with route '{result.get('route')}'"
        )
        return result

    except Exception as e:
        logger.error(f"Execution failed for run {run_id}: {e}", exc_info=True)
        fallback_basis = f"Worker runtime exception: {str(e)}. Escalating for manual specialist review."
        trace_store.save_trace(
            run_id=run_id,
            correlation_id=corr_id,
            status="failed",
            prompt_version=settings.PROMPT_VERSION,
            route="specialist-classification-review",
            basis=fallback_basis,
            citations=[],
        )
        try:
            r_conn = Redis.from_url(settings.REDIS_URL, socket_timeout=1)
            duration = round(time.perf_counter() - t_start, 4)
            r_conn.rpush("metrics:completed_runs", json.dumps({"status": "failed", "route": "specialist-classification-review"}))
            r_conn.rpush("metrics:latencies_queue", str(duration))
        except Exception:
            pass
        return {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "status": "failed",
            "route": "specialist-classification-review",
            "basis": fallback_basis,
            "citations": [],
            "prompt_version": settings.PROMPT_VERSION,
        }


def start_worker() -> None:
    """Connects to Redis and listens on the configured queue."""
    logger.info(f"Connecting worker to Redis at {settings.REDIS_URL} on queue '{settings.QUEUE_NAME}'...")
    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        redis_conn.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.critical(f"Failed connecting to Redis: {e}")
        sys.exit(1)

    worker = Worker([settings.QUEUE_NAME], connection=redis_conn)
    logger.info(f"Worker initialized and listening on queue '{settings.QUEUE_NAME}'...")
    worker.work()


if __name__ == "__main__":
    start_worker()
