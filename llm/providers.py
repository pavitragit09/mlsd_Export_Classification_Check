"""Provider adapters for LLMClient (Stub, Groq, Gemini, Ollama)."""

from __future__ import annotations

import json
from typing import Optional
import httpx
from common.config import settings
from common.logging import logger
from llm.client import LLMClient
from stub_llm.main import _generate_stub_response


class StubLLMClient(LLMClient):
    """Stub LLM provider communicating with stub_llm microservice or local fallback."""

    def __init__(self, service_url: Optional[str] = None):
        super().__init__()
        self.service_url = service_url or settings.STUB_LLM_URL

    def _call_raw(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # Try calling the stub service over HTTP
        try:
            with httpx.Client(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
                res = client.post(
                    f"{self.service_url}/v1/chat/completions",
                    json={
                        "model": "stub-model",
                        "messages": [
                            {"role": "system", "content": system_prompt or ""},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                if res.status_code == 200:
                    payload = res.json()
                    return payload["choices"][0]["message"]["content"]
        except Exception as e:
            logger.info(f"Stub HTTP call failed ({e}); falling back to in-process stub engine.")

        # In-process deterministic stub fallback
        combined_text = f"{system_prompt or ''}\n{prompt}"
        resp_obj = _generate_stub_response(combined_text)
        return json.dumps(resp_obj)


class GroqLLMClient(LLMClient):
    """Groq API adapter."""

    def __init__(self):
        super().__init__()
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL

    def _call_raw(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not configured")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
            resp = client.post(
                url,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


class GeminiLLMClient(LLMClient):
    """Google Gemini API adapter."""

    def __init__(self):
        super().__init__()
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL

    def _call_raw(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System Instructions:\n{system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        with httpx.Client(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
            resp = client.post(
                url,
                json={"contents": contents},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]


class OllamaLLMClient(LLMClient):
    """Local Ollama adapter."""

    def __init__(self):
        super().__init__()
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL

    def _call_raw(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.base_url}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
            resp = client.post(
                url,
                json={"model": self.model, "messages": messages, "stream": False, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]


def get_llm_client() -> LLMClient:
    """Factory selecting the provider implementation from configuration."""
    provider = settings.LLM_PROVIDER.lower()
    if provider == "groq":
        return GroqLLMClient()
    elif provider == "gemini":
        return GeminiLLMClient()
    elif provider == "ollama":
        return OllamaLLMClient()
    elif provider == "stub":
        return StubLLMClient()
    else:
        logger.warning(f"Unknown LLM_PROVIDER '{provider}', falling back to Stub.")
        return StubLLMClient()
