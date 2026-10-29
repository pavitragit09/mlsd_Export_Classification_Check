"""Locust load test scenario measuring end-to-end classification run duration.

Flow:
1. POST /runs with valid product declaration payload.
2. Receive run_id (HTTP 202).
3. Poll GET /runs/{run_id} every 0.5s until status is 'done' or 'failed'.
4. Record full end-to-end lifecycle duration via custom Locust metric event.
"""

from __future__ import annotations

import time
from locust import HttpUser, task, between, events


PAYLOAD = {
    "description": "Stainless steel vacuum flask with a moulded plastic outer body.",
    "materials": ["stainless_steel", "plastic"],
    "intended_use": "Thermal beverage containment",
}


class ExportClassificationUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def submit_and_poll_classification(self):
        t0 = time.time()
        run_id = None

        # 1. Submit Job
        with self.client.post(
            "/runs",
            json=PAYLOAD,
            headers={"Content-Type": "application/json"},
            name="POST /runs",
            catch_response=True,
        ) as post_resp:
            if post_resp.status_code != 202:
                post_resp.failure(f"Expected 202, got {post_resp.status_code}: {post_resp.text}")
                return
            data = post_resp.json()
            run_id = data.get("run_id")
            if not run_id:
                post_resp.failure("Missing run_id in response")
                return

        # 2. Poll until completion (max 90 seconds timeout)
        max_poll_time = 90.0
        poll_interval = 0.5
        completed = False

        while (time.time() - t0) < max_poll_time:
            time.sleep(poll_interval)
            with self.client.get(
                f"/runs/{run_id}",
                name="GET /runs/{id}",
                catch_response=True,
            ) as get_resp:
                if get_resp.status_code == 200:
                    status = get_resp.json().get("status")
                    if status in ["done", "failed"]:
                        completed = True
                        break
                elif get_resp.status_code == 404:
                    # Still propagating or initializing
                    pass
                else:
                    get_resp.failure(f"Unexpected poll status: {get_resp.status_code}")
                    break

        total_duration_ms = (time.time() - t0) * 1000

        # Fire custom E2E lifecycle metric
        if completed:
            events.request.fire(
                request_type="E2E",
                name="Complete_Run_Lifecycle",
                response_time=total_duration_ms,
                response_length=0,
                exception=None,
            )
        else:
            events.request.fire(
                request_type="E2E",
                name="Complete_Run_Lifecycle",
                response_time=total_duration_ms,
                response_length=0,
                exception=TimeoutError("Run did not complete within max polling window"),
            )
