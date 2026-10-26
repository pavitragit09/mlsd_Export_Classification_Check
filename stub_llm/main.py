"""Stub LLM service providing predictable responses with realistic delay."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request
from pydantic import BaseModel

app = FastAPI(title="Stub LLM Service", version="1.0.0")

STUB_DELAY = float(os.getenv("STUB_DELAY_SECONDS", "0.05"))


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "stub-model"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.0
    max_tokens: Optional[int] = 1000


def _generate_stub_response(prompt_text: str) -> Dict[str, Any]:
    text_lower = prompt_text.lower()

    # Case 1: Out of corpus / scope (e.g., lithium battery, pharmaceuticals, textiles)
    if "lithium" in text_lower or "battery" in text_lower or "textile" in text_lower or "paracetamol" in text_lower:
        if "verifier" in text_lower:
            return {
                "verified": True,
                "citations_verified": [],
                "issues": ["Item is outside Chapter 73 and Chapter 96 scope"],
                "route": "specialist-classification-review",
                "basis": "Product is outside Chapter 73 and Chapter 96; out-of-scope escalation per F7.",
            }
        return {
            "article": "Lithium battery pack",
            "materials": ["lithium", "plastic"],
            "candidate_headings": [],
            "resolved_heading": None,
            "tariff_code": None,
            "gri_rule": "GRI 1",
            "export_policy": "Unknown (Out of Scope)",
            "citations": [],
            "route": "specialist-classification-review",
            "basis": "The item falls under Chapter 85 (electrical machinery and equipment), which is outside the tariff scope of Chapter 73 and Chapter 96. Escalating for specialist review.",
            "prompt_injection_detected": False,
        }

    # Case 2: Vacuum flask test case
    if "vacuum flask" in text_lower or "vacuum vessel" in text_lower:
        if "verifier" in text_lower:
            return {
                "verified": True,
                "citations_verified": [
                    "Heading 9617",
                    "Section XV Note 1(m)",
                    "GRI 1",
                ],
                "issues": [],
                "route": "clear-for-filing",
                "basis": "Verified against retrieved passages. Heading 9617 specifically names vacuum flasks. Section XV Note 1(m) explicitly excludes Chapter 96 articles from Chapter 73. GRI 1 governs.",
            }
        return {
            "article": "Vacuum flask",
            "materials": ["stainless steel", "plastic"],
            "candidate_headings": ["9617", "7323"],
            "resolved_heading": "9617",
            "tariff_code": "9617 00 11",
            "gri_rule": "GRI 1",
            "export_policy": "Free",
            "citations": [
                "Heading 9617",
                "Section XV Note 1(m)",
                "GRI 1",
                "DGFT Export Policy 2023 Ch 96",
            ],
            "route": "clear-for-filing",
            "basis": "Heading 9617 specifically names vacuum flasks and other vacuum vessels complete with cases. Section XV Note 1(m) excludes goods of Chapter 96 from Chapter 73 (Articles of iron or steel). GRI 1 applies by terms of heading 9617. Export policy is Free.",
            "prompt_injection_detected": False,
        }

    # Case 3: Chapter 73 Steel kitchenware / table article
    if "stainless steel spoon" in text_lower or "steel fork" in text_lower or "kitchenware" in text_lower or "tableware" in text_lower:
        if "verifier" in text_lower:
            return {
                "verified": True,
                "citations_verified": ["Heading 7323", "GRI 1"],
                "issues": [],
                "route": "clear-for-filing",
                "basis": "Verified against retrieved passages. Heading 7323 covers table, kitchen or other household articles of iron or steel.",
            }
        return {
            "article": "Kitchenware / Tableware",
            "materials": ["stainless steel"],
            "candidate_headings": ["7323"],
            "resolved_heading": "7323",
            "tariff_code": "7323 93 90",
            "gri_rule": "GRI 1",
            "export_policy": "Free",
            "citations": ["Heading 7323", "GRI 1", "DGFT Chapter 73 Policy"],
            "route": "clear-for-filing",
            "basis": "Heading 7323 covers table, kitchen or other household articles of iron or steel. Classified under GRI 1. Export policy is Free.",
            "prompt_injection_detected": False,
        }

    # Case 4: Ballpoint pen (Chapter 96)
    if "ballpoint" in text_lower or "ball point" in text_lower or "pen" in text_lower:
        if "verifier" in text_lower:
            return {
                "verified": True,
                "citations_verified": ["Heading 9608", "GRI 1"],
                "issues": [],
                "route": "clear-for-filing",
                "basis": "Verified against retrieved passages. Heading 9608 covers ball point pens.",
            }
        return {
            "article": "Ball point pen",
            "materials": ["plastic", "steel"],
            "candidate_headings": ["9608"],
            "resolved_heading": "9608",
            "tariff_code": "9608 10 19",
            "gri_rule": "GRI 1",
            "export_policy": "Free",
            "citations": ["Heading 9608", "GRI 1", "DGFT Chapter 96 Policy"],
            "route": "clear-for-filing",
            "basis": "Heading 9608 covers ball point pens, felt tipped and other porous-tipped pens and markers. Classified under GRI 1. Export policy is Free.",
            "prompt_injection_detected": False,
        }

    # Case 5: Ambiguous / unresolvable (e.g. "Steel composite rod with unknown core")
    if "ambiguous" in text_lower or "unknown" in text_lower:
        if "verifier" in text_lower:
            return {
                "verified": True,
                "citations_verified": [],
                "issues": ["Product description is ambiguous"],
                "route": "seek-product-clarification",
                "basis": "Material composition and function are insufficiently specified to distinguish between competing headings.",
            }
        return {
            "article": "Composite rod",
            "materials": ["steel"],
            "candidate_headings": ["7304", "7306"],
            "resolved_heading": None,
            "tariff_code": None,
            "gri_rule": "GRI 3(b)",
            "export_policy": None,
            "citations": [],
            "route": "seek-product-clarification",
            "basis": "Description lacks manufacturing specifics (seamless vs welded) required to classify between 7304 and 7306.",
            "prompt_injection_detected": False,
        }

    # Default fallback
    if "verifier" in text_lower:
        return {
            "verified": True,
            "citations_verified": ["GRI 1"],
            "issues": [],
            "route": "specialist-classification-review",
            "basis": "General verification fallback: candidate requires specialist review.",
        }
    return {
        "article": "General article",
        "materials": ["steel"],
        "candidate_headings": ["7326"],
        "resolved_heading": "7326",
        "tariff_code": "7326 90 99",
        "gri_rule": "GRI 1",
        "export_policy": "Free",
        "citations": ["Heading 7326", "GRI 1"],
        "route": "specialist-classification-review",
        "basis": "Default basket heading 7326 identified, escalating to specialist review for specific classification confirmation.",
        "prompt_injection_detected": False,
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy", "service": "stub_llm"}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest) -> Dict[str, Any]:
    if STUB_DELAY > 0:
        await asyncio.sleep(STUB_DELAY)

    all_content = " ".join([m.content for m in req.messages])
    result_data = _generate_stub_response(all_content)
    result_json = json.dumps(result_data)

    return {
        "id": "stub-" + str(int(time.time() * 1000)),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result_json,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(all_content.split()),
            "completion_tokens": len(result_json.split()),
            "total_tokens": len(all_content.split()) + len(result_json.split()),
        },
    }


@app.post("/generate")
async def generate(req: Request) -> Dict[str, Any]:
    data = await req.json()
    prompt = data.get("prompt", "") or str(data.get("messages", ""))
    if STUB_DELAY > 0:
        await asyncio.sleep(STUB_DELAY)
    result_data = _generate_stub_response(prompt)
    return {
        "response": json.dumps(result_data),
        "data": result_data,
        "prompt_tokens": len(prompt.split()),
        "completion_tokens": len(json.dumps(result_data).split()),
    }
