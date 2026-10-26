"""Circuit breaker implementation for external LLM provider calls."""

from __future__ import annotations

import time
from typing import Callable, Any
from common.logging import logger


class CircuitBreakerOpenException(Exception):
    """Raised when the circuit breaker is in OPEN state."""
    pass


class CircuitBreaker:
    """
    Standard three-state circuit breaker: CLOSED, OPEN, HALF_OPEN.
    Prevents repeated calls to failing dependencies and enables graceful fallback.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout: float = 30.0,
        name: str = "llm_circuit_breaker",
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.name = name

        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.last_failure_time: float = 0.0

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        now = time.time()

        if self.state == "OPEN":
            if now - self.last_failure_time > self.reset_timeout:
                logger.info(f"Circuit breaker {self.name} entering HALF_OPEN state.")
                self.state = "HALF_OPEN"
            else:
                logger.warning(f"Circuit breaker {self.name} is OPEN. Failing fast.")
                raise CircuitBreakerOpenException(f"Circuit breaker {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self) -> None:
        if self.state == "HALF_OPEN":
            logger.info(f"Circuit breaker {self.name} reset to CLOSED after successful trial.")
        self.state = "CLOSED"
        self.failure_count = 0

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(
            f"Circuit breaker {self.name} failure count: {self.failure_count}/{self.failure_threshold}"
        )

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(f"Circuit breaker {self.name} tripped to OPEN state!")
