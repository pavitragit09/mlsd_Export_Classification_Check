# Project Architecture & Engineering Rationale

## 1. Problem Statement & Scope

### Domain: Logistics and International Trade Compliance
Under international customs regulations (WCO Harmonized System), every export shipment must be classified under an 8-digit HS tariff code. This classification determines customs duties, licensing requirements, and legal permissibility under national export policies (e.g. DGFT Schedule 2 in India). Misclassification can cause shipments to be detained, confiscated, or penalized.

### Core Challenge: Why Classification is Not a Lookup
Tariff classification is governed by the **General Rules for Interpretation (GRI)**, which must be applied in strict numerical order (GRI 1 through 6). Furthermore, **Section and Chapter Notes** take precedence over heading text. A product that appears to belong under one chapter based on raw material may be explicitly excluded by a note or named specifically under a different chapter.

### Project Scope Boundaries
- **In-Scope Regulatory Texts**:
  - Customs Tariff General Rules for Interpretation (GRI 1 to 6).
  - Chapter 73: Articles of iron or steel (with Section XV Notes and Chapter 73 Notes).
  - Chapter 96: Miscellaneous manufactured articles (with Section XX Notes and Chapter 96 Notes).
  - DGFT Export Policy for Chapters 73 and 96.
- **Out-of-Scope Goods**:
  - Any product outside Chapters 73 and 96 (e.g. Lithium battery packs falling under Chapter 85, pharmaceuticals under Chapter 30, textiles under Chapter 50-63).
  - **Requirement**: Out-of-scope products must never receive a fabricated classification; they must escalate to `specialist-classification-review`.

---

## 2. Why Single-Pass Retrieval Fails on the Vacuum Flask Case

### The Difficult Test Case
- **Input Description**: `"Stainless steel vacuum flask with a moulded plastic outer body."`
- **Declared Materials**: `["stainless_steel", "plastic"]`

### Structural Failure of Naive Single-Pass RAG
1. **The Semantic Trap**:
   A single-pass vector embedding of `"Stainless steel vacuum flask with a moulded plastic outer body"` strongly matches passages describing "stainless steel", "household articles of steel", or "moulded plastics". In the tariff corpus, this scores highest against **Heading 7323** (*"Table, kitchen or other household articles and parts thereof, of iron or steel"*).
2. **The Missing Provision**:
   The user's query describes the item's material construction, but does **not** mention *Section XV Note 1(m)* or the legal phraseology of *Chapter 96*. Because dense embedding similarity optimizes for textual overlap and semantic proximity, a single retrieval pass rarely surfaces Note 1(m).
3. **The Legal Reality**:
   - **GRI 1** dictates that classification is governed by the terms of headings and Section/Chapter notes.
   - **Heading 9617** specifically names: *"Vacuum flasks and other vacuum vessels, complete with cases; parts thereof other than glass inners."*
   - **Section XV Note 1(m)** explicitly provides that Section XV (Base Metals & Chapter 73) **does not cover articles of Chapter 96 (for example, vacuum flasks or other vacuum vessels complete with cases)**.
   - Therefore, classifying under Chapter 73 is legally incorrect.

### The Agentic Multi-Pass Solution
The multi-agent system solves this through sequential, tool-directed retrieval:
1. **Article Extraction**: The Classifier isolates the core article noun phrase (*"vacuum flask"*).
2. **Heading-Titles Index Search**: The agent queries `headings` collection by article name, surfacing **Heading 9617**.
3. **Exclusion Check**: The agent queries notes for candidate headings and retrieves **Section XV Note 1(m)**, proving that Chapter 73 is excluded.
4. **GRI 1 Application**: The agent prioritizes Heading 9617 under GRI 1.
5. **Independent Verification**: The Verifier agent confirms that citations resolve to retrieved text before clearing the recommendation.

---

## 3. Design Decisions & Rejected Alternatives

| Decision | Selected Approach | Rejected Alternative | Engineering Rationale |
| :--- | :--- | :--- | :--- |
| **Reasoning Engine** | LangGraph StateGraph | Fixed linear RAG pipeline | Fixed pipelines cannot re-query based on retrieved notes or branch into escalation when verification fails. |
| **Index Architecture** | Dual Collections (`fulltext` + `headings`) | Single monolithic index | Monolithic search allows high-frequency material keywords to drown out specific heading names. Dual collections let the agent explicitly query heading titles by article identity. |
| **Embeddings** | Local `all-MiniLM-L6-v2` | OpenAI / Paid API embeddings | Local sentence-transformers run offline at zero operational cost, with zero rate-limit risks and instant container restarts. |
| **API Asynchrony** | Redis + RQ Worker (`202 Accepted`) | Synchronous `200 OK` endpoint | Multi-step agent retrieval and verification take 5–15 seconds; synchronous HTTP endpoints cause client timeouts, thread exhaustion, and poor p95 latencies under load. |
| **Reliability** | Circuit Breaker + Graceful Fallback | Unbounded retries / Uncaught errors | A failing LLM provider can exhaust all worker threads. A 3-strike circuit breaker fails fast and routes runs to manual specialist review. |
| **Security** | Delimiter Wrapping + Legal Output Filter + Header Auth | Free-form output generation & query-param keys | Prevents prompt injection attacks, prevents false filing claims, and prevents API keys from leaking into HTTP client logs. |
| **Telemetry & Metrics** | In-Process SQLite Trace Store + Prometheus `/metrics` | Grafana Cloud / OpenTelemetry Collectors | For a standalone college mini project, heavyweight distributed telemetry backends (Grafana, Jaeger, OTel Collector daemons) introduce unnecessary memory overhead, complex configuration, and external cloud dependencies. Self-contained SQLite and Prometheus endpoints provide 100% auditability without third-party services. |
| **Response Caching** | Direct Dynamic Verification | Redis Classification Cache | In customs compliance, caching raw product descriptions risks masking subtle material differences (e.g., steel grade or insulation casing) that legally alter headings. Every declaration must undergo deterministic verification against the corpus. |
| **Rate Limiting** | RQ Bounded Worker Queuing | Distributed Token Bucket Rate Limiting | The asynchronous queue naturally absorbs traffic spikes by buffering jobs in Redis; excess requests are safely sequenced rather than dropped with HTTP 429 errors. |

---

## 4. Current Status: What is Done vs. Not Done

### Completed (Vertical Slice Delivered)
- [x] End-to-end containerized microservices architecture under Docker Compose (`api`, `worker`, `redis`, `stub_llm`).
- [x] Fast dev loop with `docker-compose.override.yml` bind mounts (`uvicorn --reload`, instant worker restarts without image rebuilds).
- [x] Official CBIC Tariff & DGFT PDF extraction pipeline (`python -m ingestion.parse_raw`) parsing raw regulatory documents into structured JSON corpus.
- [x] Idempotent dual-index ingestion pipeline (`python -m ingestion.ingest`) producing dual FAISS indices and `manifest.json`.
- [x] Pydantic v2 data contracts with cross-field validation, custom error handling, and SQLite quarantine store (`api/quarantine.py`).
- [x] User-facing single-page web frontend (`api/static/index.html`) mounted at `/` with one-click test case loading, live polling, and trace inspection.
- [x] Bounded LangGraph agent workflow with Classifier (`prompts/classifier_v3.txt`), Verifier (with fetch-by-ID retry), 3 retrieval tools, and 60s/6-step bounds.
- [x] Reliable heading resolution: 4-digit `resolved_heading` ("9617") and separate `resolved_heading_title` validated against statutory corpus.
- [x] Tri-state routing (`clear-for-filing`, `seek-product-clarification`, `specialist-classification-review`).
- [x] Security & Key Redaction: `x-goog-api-key` header-based authentication, zero-dependency regex redacting Google/Groq/OpenAI keys from URLs, logs, traces, and basis strings (`tests/test_key_redaction.py`).
- [x] Selective provider retry: 429/503 exponential backoff, immediate fail-fast on 400/401/403/404, circuit breaker with graceful fallback.
- [x] 20-scenario quantitative evaluation benchmark (`evaluation/run_eval.py`) supporting `--prompt-version`, `--limit`, `--timeout`, and streaming JSON output; calculated L2/L3 metrics (Route Accuracy, Groundedness, Context Relevance, Faithfulness, Hallucination Rate) and ablation study on verifier retry documented in `docs/EVAL_REPORT.md`.
- [x] Per-step token & cost tracking in `agents/graph.py` and SQLite trace store; cost analysis CLI (`evaluation/cost_report.py`) calculating cost per 100 runs.
- [x] Headless Locust load testing suite (`locustfile.py`) measuring end-to-end user lifecycle (`Complete_Run_Lifecycle`); pre-declared SLA verification and horizontal worker scaling analysis (1 vs 3 workers) documented in `docs/LOAD_TEST.md`.
- [x] Structured JSON logging with correlation ID propagation.
- [x] Operational Runbook (`docs/RUNBOOK.md`) and SRE Incident Post-Mortems (`docs/INCIDENT_LOG.md`).
- [x] 100% passing automated test suite covering chunking, retrieval, routing, quarantine, key redaction, and the vacuum flask benchmark.

### Out of Scope / Intentionally Not Built (Engineering Rationale)

The following capabilities were intentionally excluded with clear architectural justification:

1. **OpenTelemetry / Jaeger Exporters**:
   - *Rationale*: Replaced by structured JSON logs with correlation IDs, in-process SQLite per-run audit traces (`run_traces`), and Prometheus `/metrics`. Dedicated OTel Collector and Jaeger daemons introduce substantial memory footprint and operational complexity without improving observability for a localized microservice deployment.
2. **Toxicity Detection**:
   - *Rationale*: Customs declarations consist strictly of objective commodity specifications (materials, technical applications, physical dimensions). Natural language toxicity classifiers (trained on conversational/social media content) introduce unnecessary inference latency and false-positive rejections with zero relevance to trade compliance.
3. **Response Caching**:
   - *Rationale*: Customs classification demands strict legal determinism. Caching raw input descriptions risks masking minor material nuances (such as steel grade, plating thickness, or insulation casings) that alter the governing tariff heading. Every declaration must undergo full tool-driven verification against the statutory corpus.
4. **Distributed Rate Limiting**:
   - *Rationale*: The asynchronous Redis RQ job queue inherently absorbs traffic spikes by buffering requests rather than dropping them with HTTP 429 errors. The queue naturally paces processing according to available worker capacity.
5. **Feedback / Upvote Endpoints**:
   - *Rationale*: Statutory customs classification is governed strictly by the Customs Tariff Act, GRI rules, and official DGFT notifications—not user sentiment or crowd-sourced voting. Accepting unverified user feedback into classification logic risks regulatory non-compliance. Continuous improvement is achieved through versioned benchmark evaluation sets (`tests/eval_set.jsonl`).

---

## 5. Teammate Task Split & Work Allocation

| Person | Focus Area | Completed Foundation | Implemented Deliverables |
| :--- | :--- | :--- | :--- |
| **Person A** | Ingestion & Retrieval | Dual FAISS indexer, structural chunker, sample corpus, retrieval tools | 1. Official PDF parser (`parse_raw.py`) for CBIC Chapter 73, 96, GRI, and DGFT.<br>2. Dual FAISS index generation (`headings` and `fulltext`).<br>3. Exact citation retrieval tools (`search_corpus`, `get_clause`). |
| **Person B** | Agents, Verification & LLMOps | LangGraph graph, Classifier, Verifier, prompt versions, prompt injection guard | 1. Classifier multi-pass tool-driven retrieval.<br>2. Verifier automated citation auditing and retry search.<br>3. 20-scenario benchmark evaluation suite (`evaluation/run_eval.py`). |
| **Person C** | API, Ops, Observability & Web UI | FastAPI REST endpoints, RQ async worker, Prometheus metrics, circuit breaker, Docker Compose | 1. Web UI frontend (`api/static/index.html`) with live polling.<br>2. Shared volume synchronization and worker async processing.<br>3. Operations Runbook (`RUNBOOK.md`) and Incident Post-Mortems (`INCIDENT_LOG.md`). |

---

## 6. Viva Exam & Demo Walkthrough Guide

When presenting the project to the examiner, demonstrate the following three core scenarios in the Web UI (`http://localhost:8000/`) or via terminal:

### Scenario 1: The Vacuum Flask Benchmark (Complex Classification)
- **Input**: `"Stainless steel vacuum flask with a moulded plastic outer body."`, Materials: `["stainless_steel", "plastic"]`.
- **Why this is hard**: Naive RAG sees "stainless steel" and classifies it as household steel tableware (Heading 7323).
- **Agent Behavior**:
  1. Classifier extracts article noun *"vacuum flask"*, queries `headings` index, and surfaces **Heading 9617**.
  2. Queries `fulltext` notes, discovering **Section XV Note 1(m)** which explicitly excludes articles of Chapter 96 from Chapter 73.
  3. Verifies under **GRI 1** that Heading 9617 governs.
  4. Confirms DGFT policy for 9617 is **Free**.
  5. Verifier validates every citation against corpus text.
- **Outcome**: `clear-for-filing`, Tariff Code `9617`, Export Policy `Free`.

### Scenario 2: Out-of-Scope Goods (Safe Escalation)
- **Input**: `"Lithium battery pack for industrial equipment with durable plastic outer casing."`, Materials: `["plastic"]`.
- **Why this is hard**: Hallucinating LLMs often invent tariff codes for items not in the corpus.
- **Agent Behavior**:
  1. Request passes input schema validation (HTTP 202) because declared plastic casing matches the text.
  2. Agent searches corpus; finds no valid heading in Chapter 73 or 96 (lithium batteries belong to Chapter 85).
  3. Rather than guessing, the agent safely escalates.
- **Outcome**: `specialist-classification-review`, Route reason: *"Out of scope (requires Chapter 85 - Electrical machinery)"*.

### Scenario 3: Malformed & Contradictory Input (Boundary Quarantine)
- **Input**: Description mentions solid steel, but materials only declare `["plastic"]`.
- **System Behavior**:
  1. FastAPI ingress validator catches cross-field contradiction.
  2. Request is immediately rejected with **HTTP 422**.
  3. Payload and detailed error are recorded in SQLite quarantine store (`quarantine.db`).
  4. Never enqueued to Redis and never incurs LLM cost or worker time.

