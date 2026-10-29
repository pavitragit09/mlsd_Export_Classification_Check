"""Correlation ID propagation, latency tracking, and SQLite trace persistence."""

from __future__ import annotations

import contextvars
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from common.config import settings

# Context variable for thread-safe/async correlation ID propagation
_CORRELATION_ID: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="system")


def get_correlation_id() -> str:
    return _CORRELATION_ID.get()


def set_correlation_id(correlation_id: str) -> None:
    _CORRELATION_ID.set(correlation_id)


class StepTimer:
    """Context manager to measure step latency."""

    def __init__(self, step_name: str):
        self.step_name = step_name
        self.start_time: float = 0.0
        self.duration: float = 0.0

    def __enter__(self) -> StepTimer:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.duration = time.perf_counter() - self.start_time


class TraceStore:
    """Stores full execution traces in SQLite for observability and auditing."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.TRACE_DB_PATH
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_traces (
                    run_id TEXT PRIMARY KEY,
                    correlation_id TEXT,
                    status TEXT,
                    prompt_version TEXT,
                    route TEXT,
                    basis TEXT,
                    citations TEXT,
                    per_step_latency TEXT,
                    tool_calls TEXT,
                    queries TEXT,
                    retrieved_passage_ids TEXT,
                    token_counts TEXT,
                    verification_outcome TEXT,
                    per_step_tokens TEXT,
                    per_step_cost TEXT,
                    total_cost REAL DEFAULT 0.0,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            for col, c_type in [("per_step_tokens", "TEXT"), ("per_step_cost", "TEXT"), ("total_cost", "REAL DEFAULT 0.0")]:
                try:
                    conn.execute(f"ALTER TABLE run_traces ADD COLUMN {col} {c_type}")
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    def save_trace(
        self,
        run_id: str,
        correlation_id: str,
        status: str,
        prompt_version: str,
        route: Optional[str] = None,
        basis: Optional[str] = None,
        citations: Optional[List[str]] = None,
        per_step_latency: Optional[Dict[str, float]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        queries: Optional[List[str]] = None,
        retrieved_passage_ids: Optional[List[str]] = None,
        token_counts: Optional[Dict[str, int]] = None,
        verification_outcome: Optional[Dict[str, Any]] = None,
        per_step_tokens: Optional[Dict[str, Dict[str, int]]] = None,
        per_step_cost: Optional[Dict[str, float]] = None,
        total_cost: Optional[float] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO run_traces (
                    run_id, correlation_id, status, prompt_version,
                    route, basis, citations, per_step_latency,
                    tool_calls, queries, retrieved_passage_ids,
                    token_counts, verification_outcome, per_step_tokens,
                    per_step_cost, total_cost, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    route=excluded.route,
                    basis=excluded.basis,
                    citations=excluded.citations,
                    per_step_latency=excluded.per_step_latency,
                    tool_calls=excluded.tool_calls,
                    queries=excluded.queries,
                    retrieved_passage_ids=excluded.retrieved_passage_ids,
                    token_counts=excluded.token_counts,
                    verification_outcome=excluded.verification_outcome,
                    per_step_tokens=excluded.per_step_tokens,
                    per_step_cost=excluded.per_step_cost,
                    total_cost=excluded.total_cost,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    correlation_id,
                    status,
                    prompt_version,
                    route or "",
                    basis or "",
                    json.dumps(citations or []),
                    json.dumps(per_step_latency or {}),
                    json.dumps(tool_calls or []),
                    json.dumps(queries or []),
                    json.dumps(retrieved_passage_ids or []),
                    json.dumps(token_counts or {"prompt_tokens": 0, "completion_tokens": 0}),
                    json.dumps(verification_outcome or {}),
                    json.dumps(per_step_tokens or {}),
                    json.dumps(per_step_cost or {}),
                    float(total_cost or 0.0),
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_trace(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM run_traces WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None

            keys = row.keys()
            return {
                "run_id": row["run_id"],
                "correlation_id": row["correlation_id"],
                "status": row["status"],
                "prompt_version": row["prompt_version"],
                "route": row["route"],
                "basis": row["basis"],
                "citations": json.loads(row["citations"] or "[]"),
                "per_step_latency": json.loads(row["per_step_latency"] or "{}"),
                "tool_calls": json.loads(row["tool_calls"] or "[]"),
                "queries": json.loads(row["queries"] or "[]"),
                "retrieved_passage_ids": json.loads(row["retrieved_passage_ids"] or "[]"),
                "token_counts": json.loads(row["token_counts"] or "{}"),
                "verification_outcome": json.loads(row["verification_outcome"] or "{}"),
                "per_step_tokens": json.loads(row["per_step_tokens"] if "per_step_tokens" in keys and row["per_step_tokens"] else "{}"),
                "per_step_cost": json.loads(row["per_step_cost"] if "per_step_cost" in keys and row["per_step_cost"] else "{}"),
                "total_cost": float(row["total_cost"] if "total_cost" in keys and row["total_cost"] is not None else 0.0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }


trace_store = TraceStore()
