# Agent Implementation Changelog

This log records every step of the Mini Project 07 build process in strict chronological order, documenting the design intent, commands executed, intermediate issues encountered, and resolution steps.

---

### Step 1: Git Repository Initialization & Identity Setup
- **Reason**: Initialize the repository on branch `main` with the exact Git credentials required by the user (`Pavitragit09` / `pavitrajain054@gmail.com`) and configure the GitHub remote.
- **Commands Executed**:
  ```bash
  git init -b main
  git config user.name "Pavitragit09"
  git config user.email "pavitrajain054@gmail.com"
  git remote add origin https://github.com/pavitragit09/mlsd_Export_Classification_Check.git
  ```
- **Outcome**: Verified Git identity and branch configuration.

---

### Step 2: Workspace Analysis & Problem Statement Inspection
- **Reason**: Understand project scope, grading criteria, and specific edge cases from `MiniProject_07_Export_Classification_Check.pdf` and `00_GLOSSARY.pdf`.
- **Key Findings**:
  - Domain: Customs HS Tariff classification and DGFT export policy check.
  - Core benchmark: "Stainless steel vacuum flask with a moulded plastic outer body" must resolve to heading `9617` (not Chapter 73), applying GRI 1 and Section XV Note 1(m) exclusion.
  - Tech stack: Python 3.11, FastAPI, LangGraph, FAISS, `all-MiniLM-L6-v2`, Redis + RQ, Docker Compose.

---

### Step 3: Git Ignore & Repository Skeleton
- **Reason**: Prevent accidental commit of environment files, virtual environments, binaries, or built index files (`data/index/`, `*.db`).
- **Files Created**:
  - `.gitignore`
  - Package initializers: `ingestion/__init__.py`, `retrieval/__init__.py`, `agents/__init__.py`, `api/__init__.py`, `worker/__init__.py`, `llm/__init__.py`, `stub_llm/__init__.py`, `common/__init__.py`, `tests/__init__.py`
  - `.env.example`
  - `requirements.txt`
  - `Dockerfile`
  - `docker-compose.yml` (services: `redis`, `stub_llm`, `api`, `worker`)
  - `Makefile`
- **Commit**: `chore: initial repository skeleton and configuration` (`3deae37`)

---

### Step 4: Stub LLM Service & LLMClient Architecture
- **Reason**: Provide deterministic, realistic responses for local execution and load testing without external API dependencies or incurring API costs.
- **Files Created**:
  - `stub_llm/main.py`: Tiny FastAPI app with configurable response delay (`STUB_DELAY_SECONDS`) and health endpoints.
  - `llm/circuit_breaker.py`: Three-state circuit breaker (`CLOSED`, `OPEN`, `HALF_OPEN`) with threshold-based tripping and fast-fail fallback.
  - `llm/client.py`: Abstract `LLMClient` with exponential backoff retries, timeouts, and graceful degradation fallback.
  - `llm/providers.py`: Provider adapters for `Stub`, `Groq`, `Gemini`, and `Ollama`.
  - `common/config.py`: Centralized Pydantic `BaseSettings`.
  - `common/logging.py`: Structured JSON logger with correlation ID injection.
  - `common/telemetry.py`: SQLite `run_traces` persistence store and correlation ID contextvar propagation.
  - `common/security.py`: Prompt injection sanitization and output disclaimer enforcement.
- **Commit**: `feat: stub llm service, configuration, logging, security, and LLMClient with circuit breaker` (`4d1d6f6`)

---

### Step 5: Corpus Data Ingestion & Dual FAISS Indexing
- **Reason**: Ingest regulatory text for GRI rules 1–6, Section XV/XX notes, Chapter 73, Chapter 96, and DGFT export policies into two vector collections (fulltext & heading-titles).
- **Files Created**:
  - `data/sample/gri.json`, `data/sample/section_notes.json`, `data/sample/chapter_73.json`, `data/sample/chapter_96.json`, `data/sample/dgft_policy.json`
  - `ingestion/parser.py`, `ingestion/chunker.py`, `ingestion/indexer.py`, `ingestion/corpus_downloader.py`, `ingestion/ingest.py`
- **Commands Executed**:
  ```bash
  python -m ingestion.ingest
  ```
- **Intermediate Issue**: Variable reference typo `fulltext_chunks` in `indexer.py` was caught during initial run.
- **Fix**: Replaced with `chunks` and re-ran. Output confirmed 34 fulltext chunks and 17 heading-title chunks indexed into `data/index/`.
- **Commit**: `feat: corpus sample data, structural chunker, parser, and dual-collection FAISS indexer` (`9b3ce0f`)

---

### Step 6: Vector Retrieval & Agent Tooling
- **Reason**: Provide tools for agents to query vector collections, retrieve specific clauses, and inspect request payload.
- **Files Created**:
  - `retrieval/faiss_loader.py`: `IndexManager` for cosine similarity vector search and metadata mapping.
  - `retrieval/tools.py`: `search_corpus(query, collection, filters)`, `get_clause(clause_id)`, `get_request_fields()`.
- **Commit**: `feat: FAISS index manager and agent retrieval tools` (`2e55a85`)

---

### Step 7: Data Contract, Validation & Quarantine Store
- **Reason**: Enforce schema, range, categorical, and cross-field validation rules; reject and quarantine malformed requests without starting an agent job.
- **Files Created**:
  - `api/models.py`: Pydantic v2 `RunRequest`, `MaterialEnum`, cross-field validation rules.
  - `api/quarantine.py`: SQLite quarantine database logging rejected records and field-level error messages.
  - `agents/prompts/classifier_v1.txt`, `agents/prompts/classifier_v2.txt`, `agents/prompts/verifier_v1.txt`
  - `agents/classifier.py`: Entity extractor, heading titles searcher, note investigator.
  - `agents/verifier.py`: Independent auditor validating citations against retrieved corpus text.
- **Commit**: `feat: classifier agent, verifier agent, versioned prompts, and api validation quarantine store` (`53ac716`)

---

### Step 8: LangGraph Workflow, RQ Worker & FastAPI API
- **Reason**: Combine agents into a bounded LangGraph workflow (max 6 steps, 8 tool calls, 60s timeout), create asynchronous RQ worker, and expose REST endpoints.
- **Files Created**:
  - `agents/graph.py`: StateGraph connecting `classifier_node -> verifier_node -> guardrail_node -> END`.
  - `worker/worker.py`: RQ worker executing graph runs and writing execution traces.
  - `api/main.py`: Endpoints `POST /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/trace`, `GET /schema`, `GET /health`, `GET /metrics`.
- **Commit**: `feat: LangGraph agent graph, RQ worker, and FastAPI REST endpoints with Prometheus metrics` (`8604ed9`)

---

### Step 9: Comprehensive Test Suite & Evaluation Seed
- **Reason**: Validate all functional requirements against automated tests, including quarantine, chunking, retrieval of heading 9617, routing, and the vacuum flask benchmark.
- **Files Created**:
  - `tests/eval_seed.jsonl`: 5 seed scenarios.
  - `tests/test_validation_quarantine.py`
  - `tests/test_chunking.py`
  - `tests/test_retrieval.py`
  - `tests/test_routing.py`
  - `tests/test_vacuum_flask_case.py`
  - `tests/test_security.py`
  - `tests/test_circuit_breaker.py`
- **Commands Executed**:
  ```bash
  python -m pytest tests/ -v
  ```
- **Intermediate Issues & Fixes**:
  - In `test_circuit_breaker.py`, `last_failure_time` was not updated to `time.time()`, causing an immediate reset to `HALF_OPEN`. Fixed.
  - In `verifier.py`, citation token validation logic was enhanced to audit exact tokens against the retrieved passages.
- **Final Test Result**: **17 passed out of 17 tests (100% pass rate)** in 61 seconds.
- **Commit**: `test: comprehensive test suite with 17 tests and 5 evaluation seed scenarios` (`721c6c4`)
