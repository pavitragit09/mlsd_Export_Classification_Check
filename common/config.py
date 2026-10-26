"""Application configuration using Pydantic Settings."""

from __future__ import annotations

import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM Settings
    LLM_PROVIDER: Literal["gemini", "groq", "ollama", "stub"] = "stub"
    STUB_LLM_URL: str = "http://stub_llm:8001"
    STUB_DELAY_SECONDS: float = 0.05
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    # Redis and Queue
    REDIS_URL: str = "redis://redis:6379/0"
    QUEUE_NAME: str = "export_classification_jobs"

    # API & Worker
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    WORKER_CONCURRENCY: int = 1

    # Corpus & Vector Index
    CORPUS_DIR: str = "data/sample"
    INDEX_DIR: str = "data/index"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # Storage Paths
    QUARANTINE_DB_PATH: str = "data/quarantine.db"
    TRACE_DB_PATH: str = "data/traces.db"

    # Observability & Logging
    LOG_LEVEL: str = "INFO"

    # Reliability & Circuit Breaker
    CIRCUIT_BREAKER_FAIL_THRESHOLD: int = 3
    CIRCUIT_BREAKER_RESET_TIMEOUT_SEC: float = 30.0
    LLM_REQUEST_TIMEOUT_SEC: float = 15.0
    TOOL_CALL_TIMEOUT_SEC: float = 10.0

    # Agent Limits
    AGENT_MAX_STEPS: int = 6
    AGENT_MAX_TOOL_CALLS: int = 8
    AGENT_WALL_CLOCK_TIMEOUT_SEC: float = 60.0
    PROMPT_VERSION: str = "classifier_v1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
