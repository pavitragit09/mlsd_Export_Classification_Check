# Production Incident Post-Mortem & Incident Log

This document records real production incidents encountered during the development and testing of the **Export Classification Check Service**, formatted according to standard SRE post-mortem practices.

---

## Incident 1: HTTP 500 Internal Server Error on API Schema Validation Failures

### Summary
- **Date / Time**: 2026-10-26 14:15 UTC
- **Severity**: Sev-2 (Unexpected server crash on invalid client input)
- **Impact**: Clients sending invalid requests (e.g., descriptions mentioning steel without declared materials) received an unhandled HTTP 500 error instead of a clean, structured HTTP 422 Quarantine response.
- **Root Cause**: Pydantic v2 `RequestValidationError.errors()` contained non-JSON-serializable objects (such as `ValueError` instances inside `ctx["error"]`). When FastAPI or the Quarantine logging module called `json.dumps()` or returned the response dictionary, Python raised `TypeError: Object of type ValueError is not JSON serializable`.

### Timeline
1. **Detection**: Client submitted a malformed request testing the quarantine boundary:
   `{"description": "Stainless steel flask...", "materials": ["plastic"], "intended_use": "Beverage"}`.
2. **Observation**: API returned HTTP 500 with stack trace: `TypeError: Object of type ValueError is not JSON serializable` in `fastapi/encoders.py`.
3. **Investigation**: Inspected error object emitted by Pydantic's `@model_validator(mode="after")`. In Pydantic v2, custom validation raises `ValueError("...")`, which is stored as an exception object in `ctx["error"]`.
4. **Mitigation**:
   - Implemented `_sanitize_validation_errors(raw_errors)` in `api/main.py` converting any non-serializable exception or complex object in `ctx["error"]` into a clean string.
   - Added `default=str` fallback in `api/quarantine.py` SQLite JSON dump.

### Remediation & Prevention
- Wrapped all custom validation exceptions into string representations prior to serializing error responses.
- Added automated regression test `tests/test_validation_quarantine.py` to assert HTTP 422 is returned with `application/json` payload on all malformed and cross-field contradictory inputs.

---

## Incident 2: Lithium Battery Pack Rejected at Validation Boundary vs. Classifier Escalation

### Summary
- **Date / Time**: 2026-10-26 17:30 UTC
- **Severity**: Sev-3 (Faulty boundary contract blocking expected out-of-scope escalation)
- **Impact**: Valid export classification requests for products outside Chapters 73 and 96 (specifically: *"Lithium battery pack for industrial equipment with durable plastic outer casing"* declaring material `plastic`) were rejected at HTTP ingress with 422 instead of entering the agent workflow and escalating to `specialist-classification-review`.
- **Root Cause**: The API validation model (`api/models.py`) contained a cross-field keyword list `material_keywords` that included `"lithium"`. If the description contained `"lithium"`, the validator asserted that `"lithium"` had to be declared in `materials`. However, `MaterialEnum` only supported base materials (`plastic`, `stainless_steel`, `rubber`, etc.) and deliberately lacked `lithium` because lithium batteries belong to Chapter 85 (out of scope).

### Timeline
1. **Detection**: Integration test for out-of-scope products submitted a battery pack request.
2. **Observation**: API quarantined the request with: *"Description mentions lithium but materials does not declare it"*.
3. **Investigation**: The boundary validation was over-zealous. The purpose of input validation is to ensure schema and basic field coherence, not to act as a tariff classification engine. Articles out-of-scope (like battery packs, textiles, furniture) should pass boundary validation as long as their declared materials match the text (e.g. plastic casing declared as `plastic`), allowing the LangGraph agent to classify and safely route them to `specialist-classification-review`.
4. **Mitigation**:
   - Removed `"lithium"` from `material_keywords` mapping in `api/models.py`.
   - Preserved core cross-field checks for in-scope materials (`steel`, `iron`, `plastic`, `glass`, `rubber`, `aluminium`).

### Remediation & Prevention
- Validated that out-of-scope items (Lithium batteries, Wooden dining chairs, Cotton t-shirts, Paracetamol tablets) receive HTTP 202 Accepted, enter the queue, and are cleanly routed to `specialist-classification-review` by the Verifier.

---

## Incident 3: Vacuum Flask Run Permanently Stuck in `queued` State

### Summary
- **Date / Time**: 2026-10-27 09:20 UTC
- **Severity**: Sev-1 (Core asynchronous execution pipeline stall)
- **Impact**: Jobs submitted to `POST /runs` were accepted (`202 Accepted`), but subsequent polls to `GET /runs/{run_id}` permanently returned `{"status": "queued"}`.
- **Root Cause**: Container filesystem isolation. The `api` container and the `worker` container had isolated local directories. While both connected to the same Redis instance for queuing, the Worker executed the job and wrote the result trace to its local SQLite database at `/app/data/trace.db`. The API read from its own separate `/app/data/trace.db`, never seeing the worker's updates.

### Timeline
1. **Detection**: User executed PowerShell script submitting the benchmark vacuum flask test case and polled `GET /runs/{id}` for 10+ seconds.
2. **Observation**: Status remained `"queued"` indefinitely; worker container logs showed job execution succeeded in 2.3 seconds.
3. **Investigation**:
   - Inspected Docker container mounts: `api` and `worker` mounted separate file layers.
   - Inspected `api/main.py`: Checked SQLite database first; if row had no `status == "completed"`, it fell back to returning `"queued"` without inspecting the RQ job object in Redis.
4. **Mitigation**:
   - Added shared named volume `shared_data` mounted to `/app/data` in both `api` and `worker` containers in `docker-compose.yml`.
   - Updated `api/main.py` with dual-layer state synchronization: if SQLite row is not yet synchronized, the API directly queries Redis RQ for the active job status and extracts `job.result` directly.
   - Synchronized `run_id` as the primary correlation ID across the API, RQ queue payload, and worker context.

### Remediation & Prevention
- Verified with end-to-end multi-container polling: job transitions from `queued` to `completed` in under 3.5 seconds across separated container processes.

---

## Incident 4: Secret API Key Leakage in Worker Exception Logs During 503 Outage

### Summary
- **Date / Time**: 2026-10-28 11:45 UTC
- **Severity**: Sev-1 (Security: Credential leak in application log output)
- **Impact**: When upstream Google Gemini service returned HTTP 503 (Service Unavailable) or HTTP 429, the raw API key was logged to stdout and persisted into `traces.db` exception traces.
- **Root Cause**: In `llm/providers.py`, `GeminiLLMClient` passed the API key as a URL query parameter:
  `https://generativelanguage.googleapis.com/.../models/{model}:generateContent?key={api_key}`.
  When `httpx` raised `HTTPStatusError`, the exception string contained the full request URL including `?key=...`. When logged or formatted into the run fallback `basis`, the secret key was exposed.

### Timeline
1. **Detection**: During multi-run stability testing with Gemini, an upstream 503 error occurred.
2. **Observation**: Worker JSON log output included the plaintext API key in `message` and `exception` fields.
3. **Investigation**: Query parameters in URLs are routinely captured by HTTP client error messages and tracebacks.
4. **Mitigation**:
   - Switched Gemini API client authentication to header-based delivery: `headers={"x-goog-api-key": self.api_key}` and stripped `?key=` entirely from the request URL.
   - Created `redact_sensitive_text(text: str)` in `common/security.py` using regular expressions covering Google keys (`AIza...`), Groq (`gsk_...`), OpenAI (`sk-...`), and query/header credentials.
   - Integrated redaction into `common/logging.py` (`JSONFormatter`), `llm/client.py`, and `agents/graph.py` output filters.
   - Added automated unit test `tests/test_key_redaction.py` to prevent regression.

### Remediation & Prevention
- Verified via `tests/test_key_redaction.py`: Simulated upstream errors with fake keys never leak keys into logs, basis, or trace outputs.

---

## Incident 5: Verifier Citation Rejection on Unretrieved Legal Notes ("Section XX Note 1")

### Summary
- **Date / Time**: 2026-10-28 18:20 UTC
- **Severity**: Sev-2 (False positive verification escalation on valid benchmark item)
- **Impact**: Benchmark vacuum flask runs with Gemini were rejected by the `VerifierAgent` with `Citations could not be verified: ['Section XX Note 1']`, causing clear-for-filing items to escalate to `specialist-classification-review`.
- **Root Cause**: Two contributing factors:
  1. The LLM prompt (`classifier_v1`) did not constrain the model to cite only retrieved clause IDs. The model hallucinated or recalled from general pretraining "Section XX Note 1" (which does not exist in Chapter 96 corpus).
  2. The verifier's word parser required token length $\ge 3$ and excluded legal keywords, causing 2-letter Roman numerals (`XX`) and single-digit numbers (`1`) to be dropped from citation matching.

### Timeline
1. **Detection**: Live Gemini test case on vacuum flask resulted in `route: specialist-classification-review`.
2. **Investigation**: Inspection of `GET /runs/{id}/trace` showed `unverified_citations: ['Section XX Note 1']`. The corpus contained `SEC-XV-NOTE-1M` (base metals exclusion) but no Section XX note.
3. **Mitigation**:
   - Created `agents/prompts/classifier_v3.txt` mandating: *"Cite ONLY clause IDs returned by your tools in this run; never cite a clause you did not retrieve. In the 'citations' field, list ONLY the exact Clause IDs provided in the RETRIEVED LEGAL EVIDENCE."*
   - Implemented targeted fetch-by-ID retry in `VerifierAgent`: before rejecting an unverified citation, the verifier attempts `get_clause(clause_id)` lookup.
   - Updated citation token parser to support 2-letter Roman numeral clause identifiers.

### Remediation & Prevention
- Verified across 5 repeated live Gemini runs: all 5 runs achieved 100% verification success, routing to `clear-for-filing` with Heading 9617 and exact statutory clause IDs.
