# Export Classification Check Service (Mini Project 07)

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-1.0.0-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docs.docker.com/compose/)

> **Course**: ML System Design & AgentOps (UE24AM342AA5)  
> **Domain**: Logistics and Trade Compliance  
> **Component**: Jackfruit (Level 3)  

---

## 1. Overview
The **Export Classification Check Service** is an asynchronous, multi-agent AI system designed to assist trade compliance analysts in classifying export goods under the **Harmonized System (HS)** tariff code. 

The service enforces the **General Rules for Interpretation (GRI)** in strict numerical order, inspects Chapter and Section exclusionary notes (specifically for **Chapters 73 and 96**), checks the **DGFT Export Policy Schedule**, and independently audits proposed classifications before making recommendations.

> [!IMPORTANT]
> **Strict Non-Filing Policy**: The service NEVER files customs declarations or provides binding legal rulings. It produces evidence-grounded proposals with exact citations for review by licensed customs brokers.

---

## 2. Architecture & Deployment Boundaries

```mermaid
flowchart TD
    subgraph ClientLayer["Client Applications / External Consumers"]
        Client["REST Client (curl / Web)"]
    end

    subgraph ServiceNetwork["Docker Compose Deployment Boundaries"]
        subgraph APIService["mlsd_api Container (Port: 8000)"]
            FastAPI["FastAPI Application"]
            Contract["Pydantic Data Contract & Validator"]
            QuarantineStore[("SQLite Quarantine Store")]
        end

        subgraph QueueService["mlsd_redis Container (Port: 6379)"]
            Redis["Redis 7 (Job Queue)"]
        end

        subgraph WorkerService["mlsd_worker Container (Scalable: --scale worker=3)"]
            RQWorker["RQ Worker Process"]
            LangGraphEngine["LangGraph StateGraph Engine"]
            ClassifierAgent["Classifier Agent"]
            VerifierAgent["Verifier Agent"]
            FAISSLoader["FAISS In-Memory Search Engine"]
            TraceDB[("SQLite Trace Store")]
        end

        subgraph StubService["mlsd_stub_llm Container (Port: 8001)"]
            StubFastAPI["Stub LLM Service (Configurable Delay)"]
        end
    end

    Client -->|POST /runs| FastAPI
    FastAPI -->|Invalid (422)| QuarantineStore
    FastAPI -->|Enqueue (202)| Redis
    Redis -->|Pick Up Job| RQWorker
    RQWorker --> LangGraphEngine
    LangGraphEngine --> ClassifierAgent
    ClassifierAgent -->|Tools| FAISSLoader
    ClassifierAgent --> VerifierAgent
    VerifierAgent -->|Audit| FAISSLoader
    ClassifierAgent -->|Inference| StubFastAPI
    VerifierAgent -->|Inference| StubFastAPI
    LangGraphEngine --> TraceDB
    Client -->|GET /runs/:id| FastAPI
    Client -->|GET /runs/:id/trace| FastAPI
```

---

## 3. Prerequisites
- **Git**
- **Docker** and **Docker Compose** (for containerized deployment)
- *Optional for local development*: **Python 3.11+**

---

## 4. Quick Start (From a Clean Clone)

### Step 1: Clone the Repository
```bash
git clone https://github.com/pavitragit09/mlsd_Export_Classification_Check.git
cd mlsd_Export_Classification_Check
```

### Step 2: Configure Environment
Copy the documented `.env.example` to `.env`:
```bash
# On Linux/macOS:
cp .env.example .env

# On Windows PowerShell:
copy .env.example .env
```
*(By default, `LLM_PROVIDER=stub` is configured, allowing the entire system to run offline with zero credentials or API keys).*

### Step 3: Launch with Docker Compose
```bash
docker compose up --build -d
```
Verify all 4 services are healthy:
```bash
docker compose ps
```

To test worker scalability under load:
```bash
docker compose up --scale worker=3 -d
```

To stop containers:
```bash
docker compose down
```

---

## 5. Local Development & Testing (Without Docker)

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run Ingestion
Builds the dual FAISS indices and writes `manifest.json`:
```bash
python -m ingestion.ingest
```

### Run the Test Suite
Runs all 17 automated tests covering validation, quarantine, retrieval, routing, circuit breaker, and the vacuum flask benchmark:
```bash
python -m pytest tests/ -v
```

---

## 6. Calling the API with `curl`

### 1. Submit the Key Difficult Case (Vacuum Flask)
```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Stainless steel vacuum flask with a moulded plastic outer body.",
    "materials": ["stainless_steel", "plastic"],
    "intended_use": "Thermal beverage insulation"
  }'
```
**Response (`202 Accepted`)**:
```json
{
  "run_id": "060a4f59-bc36-4700-b6c8-10041c305a41",
  "status": "queued",
  "message": "Request accepted and enqueued for classification."
}
```

### 2. Poll the Run Status
```bash
curl http://localhost:8000/runs/060a4f59-bc36-4700-b6c8-10041c305a41
```
**Response (`200 OK`)**:
```json
{
  "run_id": "060a4f59-bc36-4700-b6c8-10041c305a41",
  "correlation_id": "060a4f59-bc36-4700-b6c8-10041c305a41",
  "status": "done",
  "route": "clear-for-filing",
  "basis": "Heading 9617 specifically names vacuum flasks... PROPOSAL ONLY: This service never files a declaration.",
  "resolved_heading": "9617",
  "tariff_code": "9617 00 11",
  "gri_rule": "GRI 1",
  "export_policy": "Free",
  "citations": [
    "Heading 9617",
    "Section XV Note 1(m)",
    "GRI 1"
  ],
  "prompt_version": "classifier_v1"
}
```

### 3. Retrieve End-to-End Run Trace
```bash
curl http://localhost:8000/runs/060a4f59-bc36-4700-b6c8-10041c305a41/trace
```

### 4. Malformed Request & Quarantine Inspection
Send an invalid payload (description too short, missing declared materials):
```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"description": "Flask", "materials": []}'
```
**Response (`422 Unprocessable Entity`)**:
```json
{
  "detail": [
    {"loc": ["body", "description"], "msg": "String should have at least 10 characters"},
    {"loc": ["body", "materials"], "msg": "List should have at least 1 item"}
  ],
  "message": "Request failed schema/cross-field validation and was quarantined. No job was enqueued."
}
```

### 5. Health & Observability Metrics
- Check health:
  ```bash
  curl http://localhost:8000/health
  ```
- Prometheus metrics:
  ```bash
  curl http://localhost:8000/metrics
  ```
- View JSON Schema:
  ```bash
  curl http://localhost:8000/schema
  ```

---

## 7. Environment Variables Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `stub` | Active provider: `stub`, `groq`, `gemini`, `ollama` |
| `STUB_LLM_URL` | `http://stub_llm:8001` | Microservice URL for the stub LLM |
| `STUB_DELAY_SECONDS` | `0.05` | Artificial delay for realistic load testing |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL for RQ queue |
| `QUEUE_NAME` | `export_classification_jobs` | Job queue name |
| `API_PORT` | `8000` | Port exposed by FastAPI |
| `CORPUS_DIR` | `data/sample` | Directory containing regulatory JSON files |
| `INDEX_DIR` | `data/index` | Directory for serialized FAISS indexes & manifest |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local Hugging Face sentence transformer model |
| `CIRCUIT_BREAKER_FAIL_THRESHOLD` | `3` | Consecutive failures before tripping breaker |
| `CIRCUIT_BREAKER_RESET_TIMEOUT_SEC`| `30.0` | Cool-off duration in seconds before HALF_OPEN trial |
| `AGENT_MAX_STEPS` | `6` | Maximum reasoning steps in LangGraph |
| `AGENT_MAX_TOOL_CALLS` | `8` | Maximum tool calls permitted per run |
| `AGENT_WALL_CLOCK_TIMEOUT_SEC` | `60.0` | Execution timeout in seconds per run |

---

## 8. Troubleshooting & Runbook

### Issue: Container cannot connect to Redis
- **Symptom**: `Failed connecting to Redis: Connection refused`.
- **Confirmation**: Check `docker compose logs redis`.
- **Recovery**: Ensure Redis healthcheck passes (`redis-cli ping` returns `PONG`). If running locally without Docker, start Redis via `redis-server` or adjust `REDIS_URL` in `.env`.

### Issue: Circuit Breaker Trips to OPEN
- **Symptom**: API returns `route: specialist-classification-review` with `basis: CIRCUIT_BREAKER_OPEN`.
- **Confirmation**: Check structured logs for message `"Circuit breaker llm_circuit_breaker tripped to OPEN state!"`.
- **Recovery**: Inspect upstream LLM provider API status or API keys in `.env`. The system automatically recovers after 30 seconds by sending a single probe request in `HALF_OPEN` state.
