"""Unit tests verifying API key redaction and non-leakage across logs, traces, and LLM clients."""

import logging
import pytest
from unittest.mock import MagicMock, patch
import httpx

from common.security import redact_sensitive_text
from common.logging import JSONFormatter
from llm.client import LLMClient
from llm.providers import GeminiLLMClient


DUMMY_KEY = "AIzaSyDummyKeyForTestingPurposes12345"


def test_redact_sensitive_text():
    raw_text = f"Failed to connect: https://example.com/api?key={DUMMY_KEY}&other=123"
    sanitized = redact_sensitive_text(raw_text)
    assert DUMMY_KEY not in sanitized
    assert "[REDACTED]" in sanitized

    header_text = f"Headers sent: x-goog-api-key: {DUMMY_KEY}"
    sanitized_header = redact_sensitive_text(header_text)
    assert DUMMY_KEY not in sanitized_header
    assert "[REDACTED]" in sanitized_header

    auth_text = "Authorization: Bearer sk-abcdef12345678901234567890"
    sanitized_auth = redact_sensitive_text(auth_text)
    assert "sk-abcdef" not in sanitized_auth


def test_json_formatter_redacts_logs_and_exceptions():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg=f"Error calling upstream with key {DUMMY_KEY}",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert DUMMY_KEY not in formatted
    assert "[REDACTED_API_KEY]" in formatted or "[REDACTED]" in formatted


def test_gemini_client_header_based_delivery():
    client = GeminiLLMClient()
    client.api_key = DUMMY_KEY
    
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"result": "ok"}'}]}}]
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        client._call_raw("hello prompt")

        # Verify URL does NOT have key query parameter
        called_args, called_kwargs = mock_post.call_args
        called_url = called_args[0]
        assert "key=" not in called_url
        assert DUMMY_KEY not in called_url

        # Verify headers DO contain x-goog-api-key
        headers = called_kwargs.get("headers", {})
        assert headers.get("x-goog-api-key") == DUMMY_KEY


class FailingClient(LLMClient):
    def __init__(self, exception_to_raise):
        super().__init__()
        self.call_count = 0
        self.exception_to_raise = exception_to_raise

    def _call_raw(self, prompt: str, system_prompt=None) -> str:
        self.call_count += 1
        raise self.exception_to_raise


def test_llm_client_redacts_basis_on_failure():
    exc = RuntimeError(f"Connection to https://api.google.com?key={DUMMY_KEY} failed")
    client = FailingClient(exc)
    result = client.generate("test prompt")

    assert result.get("degraded") is True
    assert result.get("route") == "specialist-classification-review"
    assert DUMMY_KEY not in result["basis"]


def test_llm_client_fail_fast_on_401():
    req = httpx.Request("POST", "http://test")
    resp = httpx.Response(status_code=401, request=req)
    exc = httpx.HTTPStatusError("Unauthorized", request=req, response=resp)

    client = FailingClient(exc)
    result = client.generate("test prompt")

    # Fatal error should not retry; call_count should be exactly 1
    assert client.call_count == 1
    assert result.get("degraded") is True
    assert "PROVIDER_FAILURE" in result["basis"]


def test_llm_client_retries_on_503():
    req = httpx.Request("POST", "http://test")
    resp = httpx.Response(status_code=503, request=req)
    exc = httpx.HTTPStatusError("Service Unavailable", request=req, response=resp)

    client = FailingClient(exc)
    result = client.generate("test prompt")

    # 503 should retry up to max_retries (3)
    assert client.call_count == 3
    assert result.get("degraded") is True
