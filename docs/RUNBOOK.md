# Operations Runbook: Export Classification Check Service

This runbook provides step-by-step procedures for operators and developers running, debugging, and troubleshooting the multi-agent Export Classification Check Service.

---

## 1. Quick Start & Service Lifecycle

### 1.1 Prerequisites
- Docker & Docker Compose v2+
- (Optional for host testing) Python 3.11–3.13 with `pip install -r requirements.txt`

### 1.2 Starting the System
Start all microservices in detached mode:
```powershell
docker compose up -d
```
Check health status of all containers:
```powershell
docker compose ps
```
Expected output:
- `mlsd_api`: Healthy (port 8000)
- `mlsd_redis`: Healthy (port 6379)
- `mlsd_stub_llm`: Healthy (port 8001)
- `mlsdminiproject-worker-1`: Running

Access the web interface at: `http://localhost:8000/`

### 1.3 Stopping the System
```powershell
docker compose stop
```
*Note: Do not run `docker compose down -v` as this removes persistent trace and index volumes.*

### 1.4 Restarting a Single Service
When modifying code or recovering from a transient issue:
```powershell
# Restart the background worker
docker compose restart worker

# Restart the API gateway
docker compose restart api

# Restart the stub LLM microservice
docker compose restart stub_llm
```

### 1.5 Inspecting Logs
Tail logs in real time:
```powershell
# Tail worker logs (agent reasoning and tool executions)
docker compose logs -f worker

# Tail API logs (HTTP ingress, validation, and quarantine)
docker compose logs -f api

# View last 100 lines of all services
docker compose logs --tail=100
```

---

## 2. Fast Dev Loop (Code Changes Without Rebuilding Images)

Thanks to `docker-compose.override.yml`, local directories are bind-mounted into `/app` inside containers:
- **API service (`api`)**: Runs with `uvicorn --reload`. Python code edits in `api/`, `retrieval/`, `common/` reload automatically.
- **Stub LLM service (`stub_llm`)**: Runs with `uvicorn --reload`. Changes to mock completions reload automatically.
- **Worker service (`worker`)**: RQ worker processes do not hot-reload dynamically. After editing `worker/`, `agents/`, or `llm/`, execute:
  ```powershell
  docker compose restart worker
  ```
- **Web UI (`api/static/index.html`)**: HTML/CSS/JS changes reflect immediately upon browser refresh (F5).

---

## 3. Operational Troubleshooting Guide

### 3.1 Issue: Run Stuck in `queued` State
**Symptom**: `GET /runs/{run_id}` repeatedly returns `{"status": "queued"}` beyond 10 seconds.

**Root Causes & Diagnosis**:
1. **Worker Container Not Running**:
   Check if the worker crashed or exited:
   ```powershell
   docker compose ps worker
   docker compose logs --tail=50 worker
   ```
2. **Directory Isolation Between Containers**:
   The API and Worker write/read trace data from SQLite in `data/trace.db`. Both services must mount the shared volume `shared_data:/app/data` (defined in `docker-compose.yml`). If volumes mismatch, the worker completes the job and writes to its local DB, while the API checks a different file.
   *Resolution*: Verify `shared_data` volume is mounted in both `api` and `worker` blocks in `docker-compose.yml`.
3. **Redis Job State Inspection Fallback**:
   The API has built-in inspection logic in `api/main.py`: if `trace.db` has not updated yet, the API directly inspects RQ job status in Redis (`job.get_status()`, `job.result`). If the job failed in Redis:
   ```powershell
   docker compose exec redis redis-cli keys "rq:job:*"
   ```
   Check the failed job message using the worker logs.

---

### 3.2 Issue: Container Healthcheck Failing / Unhealthy
**Symptom**: `mlsd_api` shows `(unhealthy)` or `starting` for an extended period.

**Root Causes & Diagnosis**:
1. **PyTorch & Embedding Model Cold Start**:
   On cold starts, `all-MiniLM-L6-v2` SentenceTransformer loads into memory and initializes PyTorch tensors. On low-spec host machines or non-SSD disks, this takes 20–40 seconds.
   *Resolution*: Ensure `docker-compose.yml` specifies `start_period: 90s` and `retries: 10` for `api` and `stub_llm`.
2. **Offline Mode Network Hang**:
   If SentenceTransformer attempts to query HuggingFace Hub during startup without internet or behind a firewall, it can hang until socket timeout.
   *Resolution*: `retrieval/faiss_loader.py` enforces `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `local_files_only=True` to load from local cache.

---

### 3.3 Issue: Circuit Breaker Trips (HTTP 503 / Repeated Fallbacks)
**Symptom**: Runs immediately route to `specialist-classification-review` with reasoning: *"CIRCUIT_BREAKER_OPEN: The external AI classification model is temporarily unavailable..."*, and logs record circuit breaker state transitions.

**Root Causes & Diagnosis**:
1. **External LLM Provider Outage**:
   If using Groq, Gemini, or Ollama, 3 consecutive timeouts or connection errors trip the circuit breaker into `OPEN` state for 30 seconds (`CIRCUIT_BREAKER_RESET_TIMEOUT_SEC`) to protect worker concurrency.
2. **Stub LLM Unreachable**:
   In Docker, `STUB_LLM_URL` must point to `http://stub_llm:8001`. On the host outside Docker, it automatically falls back to in-process mock execution.

#### Step-by-Step Circuit Breaker Demonstration:
To demonstrate circuit breaker tripping and automatic recovery for evaluators:
1. **Simulate Provider Outage**:
   Stop the LLM container:
   ```powershell
   docker compose stop stub_llm
   ```
2. **Trigger Failures to Open Breaker**:
   Submit 3 classification requests (failure threshold is 3):
   ```powershell
   $body = '{"description": "Stainless steel insulated vacuum flask.", "materials": ["steel"], "intended_use": "Beverage storage"}'
   1..3 | ForEach-Object {
       Invoke-RestMethod -Uri "http://localhost:8000/runs" -Method Post -ContentType "application/json" -Body $body
       Start-Sleep -Seconds 1
   }
   ```
3. **Observe Graceful Degradation**:
   Inspect worker logs or query the resulting runs:
   ```powershell
   docker compose logs --tail=30 worker
   ```
   Notice that the breaker transitions to `OPEN`. Subsequent requests return immediately with `route: specialist-classification-review` and `degraded: true` without waiting for network timeouts.
4. **Restore LLM Service**:
   Start the LLM container:
   ```powershell
   docker compose start stub_llm
   ```
5. **Verify Automatic Self-Healing (HALF_OPEN -> CLOSED)**:
   Wait 30 seconds for the reset window to elapse. Submit a new request:
   The circuit breaker tests the probe request in `HALF_OPEN` state. Upon success, it automatically closes (`CLOSED` state) and normal operations resume.

---

### 3.4 Issue: HTTP 422 Request Quarantined
**Symptom**: `POST /runs` returns HTTP 422 with `{"message": "Request failed schema/cross-field validation and was quarantined. No job was enqueued."}`.

**Behavior**:
This is **intended behavior** protecting the agent pipeline from malformed data:
- Descriptions shorter than 10 characters or longer than 500 characters.
- Empty material lists.
- Cross-field contradictions (e.g., description declares "made of solid steel" but materials list declares `["plastic"]`).

**Inspection**:
To inspect quarantined payloads and failure reasons:
```powershell
# Inside container or host
python -c "import sqlite3; c=sqlite3.connect('data/quarantine.db'); print(c.execute('SELECT correlation_id, errors FROM quarantine_records ORDER BY timestamp DESC LIMIT 5').fetchall())"
```

---

## 4. Disaster Recovery & Manual Health Verifications

### 4.1 Re-generating FAISS Vector Indices
If vector indices in `data/index/` become corrupted:
```powershell
# Parse raw PDFs into corpus JSON
python -m ingestion.parse_raw

# Rebuild dual FAISS indices and manifest
python -m ingestion.ingest
```

### 4.2 Verifying In-Scope Test Cases via CLI
Run the automated evaluation benchmark:
```powershell
python -m evaluation.run_eval
```
Expected output:
- Route accuracy: 100% (20/20)
- Heading accuracy: 100% (14/14)
- Citation grounding rate: 100% (14/14)
- Hallucination rate: 0.0%
