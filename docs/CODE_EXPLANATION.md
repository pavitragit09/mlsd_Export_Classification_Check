# Code Explanation Guide (Viva & Review Reference)

This document provides a plain-language, function-level explanation of every module in the **Export Classification Check Service**, designed to help team members explain the system clearly in an academic viva or code review.

---

## 1. System Architecture & High-Level Agent Graph Flow

```mermaid
flowchart TD
    Client["Client / User"] -->|POST /runs (Request)| Boundary["Ingestion Boundary (FastAPI)"]
    Boundary -->|Validation Error (422)| Quarantine[("Quarantine Store (SQLite)")]
    Boundary -->|202 Accepted (run_id)| RedisQueue[("Redis Job Queue (RQ)")]
    RedisQueue --> Worker["RQ Worker Process"]

    subgraph AgentSystem["Bounded LangGraph Workflow (Max 6 Steps, 8 Tools, 60s)"]
        Worker --> Classifier["Classifier Agent"]
        Classifier -->|Tool: search_corpus (headings)| FAISSHD[("FAISS Headings Index")]
        Classifier -->|Tool: search_corpus (fulltext)| FAISSFT[("FAISS Fulltext Index")]
        Classifier -->|Tool: get_clause| ClauseStore[("Corpus Clauses & Notes")]
        Classifier -->|Proposal + Citations| Verifier["Verifier Agent"]
        Verifier -->|Citation Audit Failed (Retry 1x)| RetrySearch["Secondary Search Strategy"]
        RetrySearch --> Verifier
        Verifier -->|Audit Verified / Escalated| Guardrail["Output Security & Disclaimer Guardrail"]
    end

    Guardrail --> TraceStore[("Trace Store (SQLite)")]
    Client -->|GET /runs/{run_id}| StatusAPI["Status & Result API"]
    Client -->|GET /runs/{run_id}/trace| TraceAPI["Trace Audit API"]
```

### Why LangGraph?
LangGraph models multi-step reasoning as a directed cyclic graph where state transitions, retry loops, and step bounds are explicit and observable. Unlike rigid chains, the agent can call tools dynamically and branch based on evidence.

---

## 2. File-by-File & Function-Level Explanation

### `/common` (Cross-Cutting Infrastructure)
- **`config.py`**:
  - `Settings`: Pydantic `BaseSettings` object reading configuration from environment variables or `.env`. Ensures zero hard-coded credentials or model names exist in the repository.
- **`logging.py`**:
  - `JSONFormatter`: Formats Python log records into structured JSON lines.
  - Automatically enriches each log with `timestamp`, `level`, `logger`, `message`, and the active `correlation_id`.
  - `setup_logger()`: Configures standard stream handler emitting structured JSON.
- **`telemetry.py`**:
  - `_CORRELATION_ID`: Python `contextvars.ContextVar` storing the current correlation ID per thread/coroutine.
  - `set_correlation_id()`, `get_correlation_id()`: Propagates correlation IDs across the API, queue worker, and agent steps.
  - `TraceStore`: SQLite repository managing the `run_traces` table. Records step latencies, tool calls, query strings, retrieved passage IDs, token counts, and verification outcomes for every run.
- **`security.py`**:
  - `inspect_and_sanitize_input()`: Scans free-text descriptions for adversarial prompt injection patterns (e.g., "ignore previous instructions", "jailbreak"). Wraps untrusted text in `<untrusted_user_input>` delimiters.
  - `filter_model_output()`: Checks model responses for prohibited legal determinations (e.g., "I have filed your declaration") and redacts them, while appending the mandatory non-filing disclaimer.

---

### `/ingestion` (Corpus Parsing, Chunking & Indexing)
- **`corpus_downloader.py`**:
  - `ensure_corpus()`: Verifies that required regulatory corpus JSON files are present in `data/sample/`.
- **`parser.py`**:
  - `CorpusParser.load_all()`: Idempotently loads regulatory documents (GRI rules, Section XV/XX notes, Chapter 73, Chapter 96, DGFT export policy).
- **`chunker.py`**:
  - `Chunk`: Pydantic data model representing a structural chunk with metadata (`clause_id`, `type`, `chapter`, `heading`, `title`, `text`, `source_doc`).
  - `CorpusChunker.chunk_records()`: Splits documents strictly by regulatory structure: one chunk per heading, per section/chapter note, per GRI rule, and per DGFT policy row.
- **`indexer.py`**:
  - `CorpusIndexer`: Uses `all-MiniLM-L6-v2` to compute 384-dimensional dense vectors.
  - Generates **two separate FAISS collections**:
    1. `fulltext.index`: Contains all 34 regulatory passages for deep contextual retrieval.
    2. `headings.index`: Contains heading-titles-only so the Classifier can query by article name.
  - Writes `data/index/manifest.json` recording build timestamp, source versions, and chunk counts.
- **`ingest.py`**:
  - Executable CLI entrypoint: `python -m ingestion.ingest`.

---

### `/retrieval` (Vector Search & Agent Tools)
- **`faiss_loader.py`**:
  - `IndexManager`: Singleton that loads both FAISS indices and metadata into memory.
  - `search()`: Encodes user query, performs cosine similarity search using `IndexFlatIP`, and applies metadata filters (e.g. `filters={"type": "note"}`).
  - `get_clause()`: Performs $O(1)$ dictionary lookup of any clause by ID (`HD9617`, `SEC-XV-NOTE-1M`, `GRI-1`).
- **`tools.py`**:
  - `search_corpus(query, collection, filters, top_k)`: Tool exposed to LangGraph agents.
  - `get_clause(clause_id)`: Tool allowing agents to inspect exact regulatory clauses.
  - `get_request_fields(field_name)`: Tool enabling agents to inspect the product description, declared materials, or intended use.

---

### `/llm` & `/stub_llm` (LLM Interface & Reliability)
- **`llm/circuit_breaker.py`**:
  - `CircuitBreaker`: Implements `CLOSED`, `OPEN`, and `HALF_OPEN` states.
  - If 3 consecutive failures occur, the breaker opens for 30 seconds, immediately short-circuiting calls and returning a graceful escalation fallback without exhausting worker threads.
- **`llm/client.py`**:
  - `LLMClient`: Abstract interface wrapping provider calls with bounded retries (3 attempts), exponential backoff (0.5s, 1.0s, 2.0s), and the circuit breaker.
- **`llm/providers.py`**:
  - `StubLLMClient`: Calls the stub service over HTTP with an automatic in-process fallback.
  - `GroqLLMClient`, `GeminiLLMClient`, `OllamaLLMClient`: Provider adapters configured via environment variables.
  - `get_llm_client()`: Factory reading `LLM_PROVIDER`.
- **`stub_llm/main.py`**:
  - Microservice providing fixed responses after a configurable delay (`STUB_DELAY_SECONDS`) for benchmark test cases (vacuum flask, stainless steel tableware, ballpoint pens, out-of-corpus batteries).

---

### `/agents` (Reasoning & Verification)
- **`classifier.py`**:
  - `ClassifierAgent.run()`:
    1. Extracts article keyword and materials.
    2. Queries `headings` collection for named article (e.g., "vacuum flask").
    3. Queries `fulltext` collection for Section XV Note 1(m) exclusion.
    4. Evaluates GRI rules in numerical order (GRI 1 first).
    5. Formulates classification proposal with citations.
- **`verifier.py`**:
  - `VerifierAgent.verify()`:
    1. Audits every cited clause against the actual retrieved text passages.
    2. Flags unverified or hallucinated citations.
    3. If citations are missing, triggers a secondary search strategy targeting the missing clause.
    4. If still unsupported, escalates to `specialist-classification-review`.
- **`graph.py`**:
  - `GraphState`: State container tracking step counts, latencies, tool calls, and evidence.
  - `classifier_node`, `verifier_node`, `guardrail_node`: The three stages of reasoning.
  - Enforces bounding constraints: maximum 6 steps, maximum 8 tool calls, and 60-second wall-clock timeout.

---

### `/api` (REST Gateway & Quarantine)
- **`models.py`**:
  - `MaterialEnum`: Validated material categories.
  - `RunRequest`: Enforces 10–500 character description length, minimum 1 material, and cross-field consistency (if description mentions "steel", materials must declare it).
  - `RunStatusResponse`: Published response contract.
- **`quarantine.py`**:
  - `QuarantineStore`: SQLite database (`quarantine_records`) storing malformed payloads and field-level validation errors.
- **`main.py`**:
  - `POST /runs`: Enforces boundary validation; returns `202 Accepted` and enqueues to Redis RQ.
  - `GET /runs/{run_id}`: Returns run status and recommendation.
  - `GET /runs/{run_id}/trace`: Returns full audit trail.
  - `GET /schema`: Publishes JSON schema.
  - `GET /health`: Health check evaluating API, Redis, and index freshness.
  - `GET /metrics`: Prometheus metrics scraper.

---

### `/worker` (Asynchronous Job Queue)
- **`worker.py`**:
  - `execute_classification_run()`: Asynchronous job handler invoked by RQ. Manages state, executes the LangGraph workflow, updates SQLite traces, and handles fatal exceptions gracefully.
  - `start_worker()`: Worker process loop listening on Redis queue.
