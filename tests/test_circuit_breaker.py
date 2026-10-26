"""Tests for circuit breaker state transitions and fallback handling."""

import pytest
from llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException
from llm.client import LLMClient


class MockFailingProvider(LLMClient):
    def _call_raw(self, prompt: str, system_prompt: str = None) -> str:
        raise ConnectionError("Upstream provider offline")


def test_circuit_breaker_tripping():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0, name="test_breaker")
    assert cb.state == "CLOSED"

    def fail_fn():
        raise RuntimeError("Fail")

    # 1st fail
    with pytest.raises(RuntimeError):
        cb.call(fail_fn)
    assert cb.state == "CLOSED"

    # 2nd fail
    with pytest.raises(RuntimeError):
        cb.call(fail_fn)
    assert cb.state == "CLOSED"

    # 3rd fail -> trips to OPEN
    with pytest.raises(RuntimeError):
        cb.call(fail_fn)
    assert cb.state == "OPEN"

    # Subsequent call immediately fails fast with CircuitBreakerOpenException
    with pytest.raises(CircuitBreakerOpenException):
        cb.call(fail_fn)


def test_llm_client_fallback_on_breaker_open():
    import time
    failing_client = MockFailingProvider()
    failing_client.circuit_breaker.state = "OPEN"
    failing_client.circuit_breaker.last_failure_time = time.time()

    # Should gracefully return degradation fallback instead of raising uncaught exception
    fallback_response = failing_client.generate("Test product prompt")
    assert fallback_response["route"] == "specialist-classification-review"
    assert "CIRCUIT_BREAKER_OPEN" in fallback_response["basis"]
    assert fallback_response.get("degraded") is True
