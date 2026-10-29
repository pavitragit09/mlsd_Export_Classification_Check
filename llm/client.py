"""LLMClient interface with retries, timeouts, and circuit breaker protection."""

from __future__ import annotations

import abc
import json
import time
from typing import Any, Dict, Optional
from common.config import settings
from common.logging import logger
from common.security import redact_sensitive_text
from llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException


class LLMClient(abc.ABC):
    """Abstract interface for all LLM providers."""

    def __init__(self):
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=settings.CIRCUIT_BREAKER_FAIL_THRESHOLD,
            reset_timeout=settings.CIRCUIT_BREAKER_RESET_TIMEOUT_SEC,
            name=f"{self.__class__.__name__}_breaker",
        )

    @abc.abstractmethod
    def _call_raw(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Raw call to provider API."""
        pass

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes model call protected by circuit breaker, timeout, and bounded exponential backoff.
        Retries only on 429 and 503; fails fast on 400, 401, 403, and 404.
        Returns parsed JSON dict or graceful degradation fallback on failure.
        """
        max_retries = int(getattr(settings, "LLM_MAX_RETRIES", 3))
        backoff_sec = 0.5

        def _execute_with_retries() -> str:
            last_err = None
            for attempt in range(max_retries):
                try:
                    return self._call_raw(prompt, system_prompt)
                except Exception as e:
                    last_err = e
                    status_code = getattr(getattr(e, "response", None), "status_code", None)
                    # Check for fatal client errors (400, 401, 403, 404)
                    if status_code in (400, 401, 403, 404):
                        logger.error(
                            f"LLM call fatal client error {status_code}: {redact_sensitive_text(str(e))}. Not retrying."
                        )
                        raise e

                    # Only retry on 429, 503, or connection/timeout errors (when status_code is None)
                    if status_code is not None and status_code not in (429, 503):
                        logger.error(
                            f"LLM call non-retryable status {status_code}: {redact_sensitive_text(str(e))}. Not retrying."
                        )
                        raise e

                    if attempt < max_retries - 1:
                        sleep_time = backoff_sec * (2 ** attempt)
                        logger.warning(
                            f"LLM call attempt {attempt + 1} failed: {redact_sensitive_text(str(e))}. Retrying in {sleep_time:.2f}s..."
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(
                            f"LLM call attempt {attempt + 1} failed (max retries reached): {redact_sensitive_text(str(e))}."
                        )
            raise last_err or RuntimeError("LLM max retries exceeded")

        try:
            raw_text = self.circuit_breaker.call(_execute_with_retries)
            # Try parsing JSON if formatted as such
            try:
                # Handle possible markdown codeblocks ```json ... ```
                cleaned = raw_text.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json")[1].split("```")[0].strip()
                elif "```" in cleaned:
                    cleaned = cleaned.split("```")[1].split("```")[0].strip()
                data = json.loads(cleaned)
                return data
            except Exception:
                return {"raw_response": raw_text}

        except CircuitBreakerOpenException:
            logger.error("LLM Provider circuit breaker OPEN. Applying graceful degradation fallback.")
            return {
                "article": "Unknown",
                "candidate_headings": [],
                "resolved_heading": None,
                "tariff_code": None,
                "gri_rule": "GRI 1",
                "citations": [],
                "route": "specialist-classification-review",
                "basis": "CIRCUIT_BREAKER_OPEN: The external AI classification model is temporarily unavailable. Request escalated for manual specialist review.",
                "degraded": True,
            }
        except Exception as e:
            sanitized_err = redact_sensitive_text(str(e))
            logger.error(f"LLM invocation failed completely: {sanitized_err}. Returning fallback escalation.")
            return {
                "article": "Unknown",
                "candidate_headings": [],
                "resolved_heading": None,
                "tariff_code": None,
                "gri_rule": "GRI 1",
                "citations": [],
                "route": "specialist-classification-review",
                "basis": f"PROVIDER_FAILURE: {sanitized_err}. Escalated for manual specialist review.",
                "degraded": True,
            }
