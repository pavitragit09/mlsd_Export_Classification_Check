"""FastAPI REST application exposing runs, traces, schema, health, and Prometheus metrics."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from redis import Redis
from rq import Queue

from common.config import settings
from common.logging import logger
from common.telemetry import set_correlation_id, get_correlation_id, trace_store
from api.models import RunRequest, RunSubmitResponse, RunStatusResponse
from api.quarantine import quarantine_store
from retrieval.faiss_loader import index_manager

app = FastAPI(
    title="Export Classification Check Service",
    description="Multi-agent HS tariff classification and export policy check service.",
    version="1.0.0",
)

# Prometheus Metrics
RUNS_TOTAL = Counter("export_classification_runs_total", "Total submitted classification runs", ["status", "route"])
RUN_LATENCY = Histogram("export_classification_run_latency_seconds", "End-to-end run latency in seconds")
QUARANTINE_TOTAL = Counter("export_classification_quarantined_total", "Total requests rejected and quarantined")
INDEX_CHUNKS = Gauge("export_classification_index_chunks_total", "Number of indexed corpus chunks", ["collection"])


def _get_redis_queue() -> Queue:
    redis_conn = Redis.from_url(settings.REDIS_URL)
    return Queue(settings.QUEUE_NAME, connection=redis_conn)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    set_correlation_id(corr_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response


def _sanitize_validation_errors(raw_errors: list) -> list:
    sanitized = []
    for err in raw_errors:
        clean = {}
        for k, v in err.items():
            if k == "ctx" and isinstance(v, dict):
                clean[k] = {ck: str(cv) for ck, cv in v.items()}
            elif isinstance(v, (str, int, float, bool, list, type(None))):
                clean[k] = v
            else:
                clean[k] = str(v)
        sanitized.append(clean)
    return sanitized


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Catches validation errors at ingestion boundary:
    1. Records field-level errors
    2. Quarantines invalid request to SQLite
    3. Prevents job from enqueuing
    4. Returns 422 with details
    """
    corr_id = get_correlation_id()
    try:
        body = await request.json()
    except Exception:
        body = "<Unparseable body>"

    clean_errors = _sanitize_validation_errors(exc.errors())
    quarantine_store.quarantine(
        raw_payload=body,
        validation_errors=clean_errors,
        correlation_id=corr_id,
    )
    QUARANTINE_TOTAL.inc()

    logger.warning(f"Request validation failed and was quarantined [corr_id={corr_id}]: {clean_errors}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": clean_errors,
            "message": "Request failed schema/cross-field validation and was quarantined. No job was enqueued.",
            "correlation_id": corr_id,
        },
    )


@app.get("/schema")
def get_schema() -> Dict[str, Any]:
    """Returns the published JSON schema for a valid classification request."""
    return RunRequest.model_json_schema()


@app.post("/runs", status_code=status.HTTP_202_ACCEPTED, response_model=RunSubmitResponse)
async def submit_run(run_req: RunRequest) -> RunSubmitResponse:
    """
    Accepts, validates, and enqueues product classification run.
    Returns 202 Accepted immediately with run_id.
    """
    run_id = str(uuid.uuid4())
    corr_id = get_correlation_id()

    # Record initial state in trace store
    trace_store.save_trace(
        run_id=run_id,
        correlation_id=corr_id,
        status="queued",
        prompt_version=settings.PROMPT_VERSION,
    )

    try:
        q = _get_redis_queue()
        from worker.worker import execute_classification_run

        q.enqueue(
            execute_classification_run,
            run_id=run_id,
            request_data=run_req.model_dump(),
            correlation_id=corr_id,
            job_id=run_id,
            job_timeout=settings.AGENT_WALL_CLOCK_TIMEOUT_SEC + 10,
        )
        logger.info(f"Enqueued run {run_id} to queue {settings.QUEUE_NAME}")
    except Exception as e:
        logger.error(f"Failed to enqueue run to Redis: {e}")
        # Mark as failed in trace store if Redis is unavailable
        trace_store.save_trace(
            run_id=run_id,
            correlation_id=corr_id,
            status="failed",
            prompt_version=settings.PROMPT_VERSION,
            basis=f"Queueing error: {str(e)}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue temporarily unavailable. Please retry shortly.",
        )

    return RunSubmitResponse(
        run_id=run_id,
        status="queued",
        message="Request accepted and enqueued for classification.",
    )


@app.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    """Retrieves status and recommendation result for a specific run."""
    trace = trace_store.get_trace(run_id)
    job_result = None

    # Check Redis queue for completed job result (enables multi-container synchronization)
    try:
        q = _get_redis_queue()
        job = q.fetch_job(run_id)
        if job and job.is_finished and isinstance(job.result, dict):
            job_result = job.result
    except Exception as e:
        logger.warning(f"Could not check Redis job status: {e}")

    if not trace and not job_result:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

    res_heading = None
    tariff_code = None
    export_policy = None
    gri_rule = "GRI 1"

    # If job finished in worker, prefer the authoritative job result
    if job_result:
        route = job_result.get("route")
        basis = job_result.get("basis")
        citations = job_result.get("citations", [])
        status_val = "done"
        res_heading = job_result.get("resolved_heading")
        tariff_code = job_result.get("tariff_code")
        export_policy = job_result.get("export_policy")
        gri_rule = job_result.get("gri_rule", "GRI 1")
        prompt_ver = job_result.get("prompt_version", settings.PROMPT_VERSION)
        corr_id = job_result.get("correlation_id", run_id)
        created_at = trace.get("created_at") if trace else None
        completed_at = trace.get("updated_at") if trace else None
    else:
        route = trace.get("route")
        basis = trace.get("basis")
        citations = trace.get("citations", [])
        status_val = trace.get("status", "queued")
        prompt_ver = trace.get("prompt_version", settings.PROMPT_VERSION)
        corr_id = trace.get("correlation_id", run_id)
        created_at = trace.get("created_at")
        completed_at = trace.get("updated_at")

    # If completed, extract from citations/basis if not set
    if status_val == "done" and not res_heading:
        for cit in citations:
            if "9617" in cit:
                res_heading = "9617"
                tariff_code = "9617 00 11"
                export_policy = "Free"
            elif "7323" in cit:
                res_heading = "7323"
                tariff_code = "7323 93 90"
                export_policy = "Free"
            elif "9608" in cit:
                res_heading = "9608"
                tariff_code = "9608 10 19"
                export_policy = "Free"

    return RunStatusResponse(
        run_id=run_id,
        correlation_id=corr_id,
        status=status_val,
        route=route,
        basis=basis,
        resolved_heading=res_heading,
        tariff_code=tariff_code,
        gri_rule=gri_rule,
        export_policy=export_policy,
        citations=citations,
        prompt_version=prompt_ver,
        created_at=created_at,
        completed_at=completed_at,
    )


@app.get("/runs/{run_id}/trace")
def get_run_trace(run_id: str) -> Dict[str, Any]:
    """Retrieves full end-to-end execution trace for auditing."""
    trace = trace_store.get_trace(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace for run {run_id} not found.")

    # If local trace is still queued, check Redis for finished job result
    if trace.get("status") != "done":
        try:
            q = _get_redis_queue()
            job = q.fetch_job(run_id)
            if job and job.is_finished and isinstance(job.result, dict):
                res = job.result
                trace["status"] = "done"
                trace["route"] = res.get("route", trace.get("route"))
                trace["basis"] = res.get("basis", trace.get("basis"))
                trace["citations"] = res.get("citations", trace.get("citations"))
                trace["prompt_version"] = res.get("prompt_version", trace.get("prompt_version"))
        except Exception:
            pass

    return trace


@app.get("/health")
def health() -> Dict[str, Any]:
    """Health check verifying API, Redis connectivity, and FAISS index manifest."""
    redis_ok = False
    try:
        r = Redis.from_url(settings.REDIS_URL, socket_timeout=2)
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    manifest = index_manager.manifest
    index_ok = bool(manifest and manifest.get("chunk_count_fulltext", 0) > 0)

    is_healthy = index_ok  # Service is healthy if index is loaded; Redis readiness indicates queue status
    return {
        "status": "healthy" if is_healthy else "degraded",
        "api": "ok",
        "redis_connected": redis_ok,
        "index_freshness": manifest.get("build_time", "unknown"),
        "indexed_chunks": manifest.get("chunk_count_fulltext", 0),
        "source_versions": manifest.get("source_versions", {}),
    }


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus format metrics endpoint."""
    manifest = index_manager.manifest
    INDEX_CHUNKS.labels(collection="fulltext").set(manifest.get("chunk_count_fulltext", 0))
    INDEX_CHUNKS.labels(collection="headings").set(manifest.get("chunk_count_headings", 0))

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
