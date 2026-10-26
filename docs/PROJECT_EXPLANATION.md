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
| **Security** | Delimiter Wrapping + Legal Output Filter | Free-form output generation | Prevents prompt injection attacks from hijacking tool calls, and prevents the system from claiming it has filed customs declarations. |

---

## 4. Current Status: What is Done vs. Not Done

### Completed (Vertical Slice Delivered)
- [x] End-to-end containerized microservices architecture under Docker Compose (`api`, `worker`, `redis`, `stub_llm`).
- [x] Idempotent ingestion pipeline (`python -m ingestion.ingest`) producing dual FAISS indices and `manifest.json`.
- [x] Pydantic v2 data contracts with cross-field validation, custom error handling, and SQLite quarantine store.
- [x] Bounded LangGraph agent workflow with Classifier, Verifier, 3 retrieval tools, and 60s/6-step bounds.
- [x] Independent Verifier agent with automated citation checking and secondary search retry.
- [x] Tri-state routing (`clear-for-filing`, `seek-product-clarification`, `specialist-classification-review`).
- [x] Circuit breaker on LLMClient with graceful degradation fallback.
- [x] Structured JSON logging with correlation ID propagation.
- [x] Observability: SQLite trace persistence (`GET /runs/{run_id}/trace`) and Prometheus metrics (`GET /metrics`).
- [x] 100% passing automated test suite (17 tests) covering chunking, retrieval, routing, quarantine, and the vacuum flask benchmark.

### Out of Scope / Extension Points (Not Done)
- [ ] Distributed OpenTelemetry exporters to external Jaeger / Grafana Tempo backends.
- [ ] TruLens automated evaluation dashboard over live production samples.
- [ ] Locust distributed load testing script at 50+ concurrency.
- [ ] User-facing web frontend (UI client).

---

## 5. Teammate Task Split & Remaining Work Allocation

| Person | Focus Area | Completed Foundation | Remaining Requirements to Implement |
| :--- | :--- | :--- | :--- |
| **Person A** | Ingestion & Retrieval | Dual FAISS indexer, structural chunker, sample corpus, retrieval tools | 1. Expand corpus to remaining Chapters (e.g. Ch 84, 85).<br>2. Add incremental document update script without re-indexing.<br>3. Benchmark vector recall against BM25 hybrid search. |
| **Person B** | Agents, Verification & LLMOps | LangGraph graph, Classifier, Verifier, prompt versions, prompt injection guard | 1. Implement TruLens groundedness & faithfulness scoring pipeline on `tests/eval_seed.jsonl`.<br>2. Compare prompt variants v1 vs v2 on 20 scenarios.<br>3. Add toxicity filter on user input. |
| **Person C** | API, Ops, Observability & Reliability | FastAPI REST endpoints, RQ async worker, Prometheus metrics, circuit breaker, Docker Compose | 1. Write Locust load testing script (`locustfile.py`) measuring p95 SLO under `worker=3`.<br>2. Add OpenTelemetry Jaeger exporter to Docker Compose.<br>3. Deploy Grafana dashboard visualizing run counts, latency, and queue length. |
