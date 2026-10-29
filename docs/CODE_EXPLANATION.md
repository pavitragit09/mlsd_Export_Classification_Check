# Code Explanation Guide (Viva & Review Reference)

This document provides a plain-language, function-level explanation of every module in the **Export Classification Check Service**, designed to help team members explain the system clearly in an academic viva or code review.

---

## 1. System Architecture & High-Level Agent Graph Flow

```mermaid
flowchart TD
    Browser["Web UI Client (http://localhost:8000/)"] -->|POST /runs (Request)| Boundary["Ingestion Boundary (FastAPI)"]
    Client["Client / cURL / Script"] -->|POST /runs (Request)| Boundary
    Boundary -->|Validation Error (422)| Quarantine[("Quarantine Store (SQLite)")]
    Boundary -->|202 Accepted (run_id)| RedisQueue[("Redis Job Queue (RQ)")]
    RedisQueue --> Worker["RQ Worker Process"]

    subgraph IngestionSystem["Corpus Ingestion Pipeline"]
        RawPDFs[("Official PDFs in data/raw/")] --> PDFParser["parse_raw.py (pypdf)"]
        PDFParser --> CorpusJSON[("data/corpus/*.json")]
        CorpusJSON --> Chunker["chunker.py (Structural Splitting)"]
        Chunker --> Indexer["indexer.py (all-MiniLM-L6-v2)"]
        Indexer --> FAISSHD[("FAISS Headings Index")]
        Indexer --> FAISSFT[("FAISS Fulltext Index")]
    end

    subgraph AgentSystem["Bounded LangGraph Workflow (Max 6 Steps, 8 Tools, 60s)"]
        Worker --> Classifier["Classifier Agent"]
        Classifier -->|Tool: search_corpus (headings)| FAISSHD
        Classifier -->|Tool: search_corpus (fulltext)| FAISSFT
        Classifier -->|Tool: get_clause| ClauseStore[("Corpus Clauses & Notes")]
        Classifier -->|Proposal + Citations| Verifier["Verifier Agent"]
        Verifier -->|Citation Audit Failed (Retry 1x)| RetrySearch["Secondary Search Strategy"]
        RetrySearch --> Verifier
        Verifier -->|Audit Verified / Escalated| Guardrail["Output Security & Disclaimer Guardrail"]
    end

    Guardrail --> TraceStore[("Trace Store (SQLite)")]
    Browser -->|GET /runs/{run_id} (Polling)| StatusAPI["Status & Result API"]
    Browser -->|GET /runs/{run_id}/trace (Modal)| TraceAPI["Trace Audit API"]
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
  - `TraceStore`: SQLite repository managing the `run_traces` table. Records step latencies, tool calls, query strings, retrieved passage IDs, token counts, per-step token and cost tracking (`per_step_tokens`, `per_step_cost`, `total_cost`), and verification outcomes for every run.
- **`security.py`**:
  - `inspect_and_sanitize_input()`: Scans free-text descriptions for adversarial prompt injection patterns (e.g., "ignore previous instructions", "jailbreak"). Wraps untrusted text in `<untrusted_user_input>` delimiters.
  - `filter_model_output()`: Checks model responses for prohibited legal determinations (e.g., "I have filed your declaration") and redacts them, while appending the mandatory non-filing disclaimer.
  - `redact_sensitive_text()`: Zero-dependency regex sanitization engine stripping Google (`AIza...`), Groq (`gsk_...`), and OpenAI (`sk-...`) API keys from URLs, request headers (`x-goog-api-key`), log messages, exception tracebacks, and basis strings.

---

### `/ingestion` (Corpus Parsing, Chunking & Indexing)
- **`parse_raw.py`**:
  - Uses `pypdf` to parse official statutory documents directly from `data/raw/*.pdf` (CBIC Tariff GRI 2023, Chapter 73, Chapter 96, and DGFT Export Policy).
  - Normalizes text, extracts Section XV Note 1(m) exclusions, Section XX Note 1, all 18 headings, and produces structured JSON files in `data/corpus/`.
- **`corpus_downloader.py`**:
  - `ensure_corpus()`: Verifies that required regulatory corpus JSON files are present in `data/corpus/` or fallback sample directories.
- **`parser.py`**:
  - `CorpusParser.load_all()`: Idempotently loads regulatory documents (GRI rules, Section XV/XX notes, Chapter 73, Chapter 96, DGFT export policy).
- **`chunker.py`**:
  - `Chunk`: Pydantic data model representing a structural chunk with metadata (`clause_id`, `type`, `chapter`, `heading`, `title`, `text`, `source_doc`).
  - `CorpusChunker.chunk_records()`: Splits documents strictly by regulatory structure: one chunk per heading, per section/chapter note, per GRI rule, and per DGFT policy row.
- **`indexer.py`**:
  - `CorpusIndexer`: Uses `all-MiniLM-L6-v2` to compute 384-dimensional dense vectors.
  - Generates **two separate FAISS collections**:
    1. `fulltext.index`: Contains all 35 regulatory passages for deep contextual retrieval.
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
  - `LLMClient`: Abstract interface wrapping provider calls with selective retry logic:
    - Retries only transient server faults (HTTP 429 Rate Limit, 503 Service Unavailable) with exponential backoff (0.5s, 1.0s, 2.0s).
    - Fails fast immediately without retry on client/authentication errors (HTTP 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found) to avoid wasting worker time and quota.
    - Sanitizes error text and API keys in the generated `basis` fallback.
- **`llm/providers.py`**:
  - `StubLLMClient`: Calls the stub service over HTTP with an automatic in-process fallback.
  - `GeminiLLMClient`: Transmits API keys securely via HTTP header (`x-goog-api-key: ...`) rather than query parameters, preventing secret exposure in HTTP client exceptions and access logs.
  - `GroqLLMClient`, `OllamaLLMClient`: Provider adapters configured via environment variables.
  - `get_llm_client()`: Factory reading `LLM_PROVIDER`.
- **`stub_llm/main.py`**:
  - Microservice providing fixed responses after a configurable delay (`STUB_DELAY_SECONDS`) for benchmark test cases (vacuum flask, stainless steel tableware, ballpoint pens, out-of-corpus batteries). Note: While the stub matches prompt keywords to deliver structured JSON, the LangGraph agents execute dynamic tool calls against the real FAISS vector store and SQLite trace store.

---

### `/agents` (Reasoning & Verification)
- **`classifier.py`**:
  - `ClassifierAgent.run()`:
    1. Extracts article keyword and materials.
    2. Queries `headings` collection for named article (e.g., "vacuum flask").
    3. Queries `fulltext` collection for Section XV Note 1(m) exclusion.
    4. Evaluates GRI rules in numerical order (GRI 1 first).
    5. Formulates classification proposal with citations.
    6. Returns 4-digit heading (`resolved_heading`, e.g. "9617") and separates title (`resolved_heading_title`).
- **`prompts/classifier_v3.txt`**:
  - System prompt enforcing strict citation grounding: *"Cite ONLY clause IDs returned by your tools in this run; never cite a clause you did not retrieve."* Configured dynamically via `CLASSIFIER_PROMPT_VERSION` (default `classifier_v3`).
- **`verifier.py`**:
  - `VerifierAgent.verify()`:
    1. Audits every cited clause against the actual retrieved text passages.
    2. Flags unverified citations.
    3. Triggers fetch-by-ID retry (`get_clause(clause_id)`) before rejecting any citation, ensuring valid statutory clauses retrieved during multi-turn reasoning are not dropped due to top-$k$ truncation.
    4. If still unsupported or hallucinated, escalates to `specialist-classification-review`.
- **`graph.py`**:
  - `GraphState`: State container tracking step counts, latencies, tool calls, token usage, and evidence.
  - `classifier_node`, `verifier_node`, `guardrail_node`: The three stages of reasoning.
  - Records per-step prompt/completion token usage and calculates estimated cost using configurable token rates.
  - Enforces bounding constraints: maximum 6 steps, maximum 8 tool calls, and 60-second wall-clock timeout.

---

### `/api` (REST Gateway & Quarantine)
- **`models.py`**:
  - `MaterialEnum`: Validated material categories.
  - `RunRequest`: Enforces 10–500 character description length, minimum 1 material, and cross-field consistency.
  - `RunStatusResponse`: Published response contract.
- **`quarantine.py`**:
  - `QuarantineStore`: SQLite database (`quarantine_records`) storing malformed payloads and field-level validation errors.
- **`static/index.html`**:
  - Web UI single-page application mounted at `/`.
  - Provides one-click pre-fills for the Vacuum Flask benchmark, Out-of-Scope Lithium battery, and Malformed quarantine check.
  - Asynchronously polls `GET /runs/{run_id}` every 1s, displays live progress spinner, renders recommendation badge, tariff heading, GRI rule, export policy, and interactive JSON audit trace viewer.
- **`main.py`**:
  - `GET /`: Serves web frontend application via FastAPI `StaticFiles(html=True)`.
  - `POST /runs`: Enforces boundary validation; returns `202 Accepted` and enqueues to Redis RQ.
  - `GET /runs/{run_id}`: Returns run status and recommendation with Redis job inspection fallback.
  - `GET /runs/{run_id}/trace`: Returns full audit trail.
  - `GET /schema`: Publishes JSON schema.
  - `GET /health`: Health check evaluating API, Redis, and index freshness.
  - `GET /metrics`: Prometheus metrics scraper.

---

### `/worker` (Asynchronous Job Queue)
- **`worker.py`**:
  - `execute_classification_run()`: Asynchronous job handler invoked by RQ. Manages state, executes the LangGraph workflow, updates SQLite traces with per-step token and cost metrics, and handles fatal exceptions gracefully.
  - `start_worker()`: Worker process loop listening on Redis queue.

---

### `/evaluation` & Load Testing (Benchmark, Cost & Performance)
- **`tests/eval_set.jsonl`**:
  - Ground-truth evaluation dataset containing 20 curated scenarios (benchmark vacuum flask, 4 out-of-scope, 2 ambiguous, 6 Chapter 73 steel articles, 7 Chapter 96 articles).
- **`run_eval.py`**:
  - Automated benchmark harness supporting `--prompt-version`, `--limit`, `--timeout`, `--verifier-retry` / `--no-verifier-retry`, and incremental streaming JSON results.
  - Calculates L2/L3 metrics:
    - **Route Accuracy**: % of items with exact routing match.
    - **Heading Accuracy**: % of in-scope classified items matching target 4-digit heading.
    - **Escalation Correctness**: % of out-of-scope/ambiguous items properly escalated.
    - **Groundedness**: % of citations verified in statutory corpus.
    - **Context Relevance**: Precision of retrieved chunks against necessary citations.
    - **Faithfulness**: % of claims supported by retrieved context.
    - **Hallucination Rate**: % of cited clauses that do not exist in the corpus.
- **`cost_report.py`**:
  - Analyzes per-step token usage and costs from SQLite trace database (`traces.db`).
  - Reports average input/output tokens per run, average cost per run, cost per 100 runs, projected cost for 10,000 runs, and identifies primary agent cost drivers.
- **`locustfile.py`**:
  - Headless load testing suite using Locust.
  - Implements full end-to-end user lifecycle (`Complete_Run_Lifecycle`): submits `POST /runs` and polls `GET /runs/{id}` until terminal status (`done` or `escalated`), reporting realistic asynchronous system response times.

---

### Additional Operational Documentation
- **`docs/RUNBOOK.md`**: Operational guide covering service lifecycle, fast dev loop without image rebuilds, and troubleshooting guides for queue stalls, container healthcheck cold-starts, circuit breaker trips, and quarantine inspection.
- **`docs/INCIDENT_LOG.md`**: SRE post-mortem logs documenting three real incidents encountered during development:
  1. HTTP 500 on validation failure caused by Pydantic ValueError object serialization.
  2. Lithium battery casing rejection at API validation boundary vs expected classifier escalation.
  3. Vacuum flask run stuck in `queued` state due to container filesystem isolation.
- **`docs/VIVA_AND_DEMO_GUIDE.md`**: Comprehensive presentation and viva exam question/answer guide.
