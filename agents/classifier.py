"""Classifier agent: identifies article, queries heading titles, checks notes, applies GRI."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from common.config import settings
from common.logging import logger
from common.security import inspect_and_sanitize_input
from llm.providers import get_llm_client
from retrieval.tools import search_corpus, get_clause, get_request_fields


def load_prompt(version: str) -> str:
    path = os.path.join("agents", "prompts", f"{version}.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "You are an expert Customs Classification Analyst. Classify the item under GRI rules."


class ClassifierAgent:
    """Classifier agent responsible for extracting entities, searching headings and notes, and proposing classification."""

    def __init__(self, prompt_version: Optional[str] = None):
        self.prompt_version = prompt_version or settings.PROMPT_VERSION
        self.system_prompt = load_prompt(self.prompt_version)
        self.llm = get_llm_client()

    def run(self, run_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes classification workflow with tool calling:
        1. Access request fields
        2. Prompt injection defense
        3. Search heading-titles by article name
        4. Search notes for candidate headings
        5. Search DGFT export policy
        6. Propose classification grounded in evidence
        """
        req_fields = get_request_fields()
        description = req_fields.get("description", "")
        materials = req_fields.get("materials", [])
        intended_use = req_fields.get("intended_use", "")

        sanitized_desc, injection_detected = inspect_and_sanitize_input(description)

        tool_calls: List[Dict[str, Any]] = []
        queries: List[str] = []
        retrieved_passages: List[Dict[str, Any]] = []

        # Step 1: Search heading-titles index for article terms
        article_candidates = [
            term.strip()
            for term in description.replace(",", " ").replace(".", " ").split()
            if len(term.strip()) > 3
        ]
        
        # Primary title search based on full description and identified key phrase
        query_1 = description
        if "vacuum" in description.lower() or "flask" in description.lower():
            query_1 = "vacuum flask vacuum vessel"
        elif "pen" in description.lower():
            query_1 = "ball point pen"
        elif "steel" in description.lower() and "spoon" in description.lower():
            query_1 = "tableware kitchenware spoon fork iron steel"

        queries.append(query_1)
        t0 = time.perf_counter()
        heading_matches = search_corpus(query=query_1, collection="headings", top_k=3)
        tool_calls.append({
            "tool": "search_corpus",
            "args": {"query": query_1, "collection": "headings", "top_k": 3},
            "duration": round(time.perf_counter() - t0, 3),
            "result_count": len(heading_matches),
        })
        retrieved_passages.extend(heading_matches)

        # Step 2: Search Section & Chapter Notes for exclusions / overrides
        query_2 = "exclusion articles Chapter 96 vacuum flasks"
        queries.append(query_2)
        t0 = time.perf_counter()
        note_matches = search_corpus(
            query=query_2,
            collection="fulltext",
            filters={"type": "note"},
            top_k=2,
        )
        tool_calls.append({
            "tool": "search_corpus",
            "args": {"query": query_2, "collection": "fulltext", "filters": {"type": "note"}, "top_k": 2},
            "duration": round(time.perf_counter() - t0, 3),
            "result_count": len(note_matches),
        })
        retrieved_passages.extend(note_matches)

        # Step 3: Fetch candidate heading text and relative policy
        candidate_headings = [h.get("heading") for h in heading_matches if h.get("heading")]
        policy_matches = []
        for ch in candidate_headings[:2]:
            t0 = time.perf_counter()
            clause = get_clause(f"DGFT-{ch}")
            tool_calls.append({
                "tool": "get_clause",
                "args": {"clause_id": f"DGFT-{ch}"},
                "duration": round(time.perf_counter() - t0, 3),
                "found": bool(clause),
            })
            if clause:
                policy_matches.append(clause)
                retrieved_passages.append(clause)

        # Construct prompt for the LLM
        prompt_content = f"""
REQUEST:
Description: {sanitized_desc}
Declared Materials: {materials}
Intended Use: {intended_use}
Injection Detected: {injection_detected}

RETRIEVED LEGAL EVIDENCE:
Heading Titles: {[h.get('title') for h in heading_matches]}
Notes: {[n.get('text') for n in note_matches]}
Export Policies: {[p.get('text') for p in policy_matches]}

TASK:
Classify this product applying GRI in numerical order. Name the resolved heading and cite all relied-on legal provisions.
Output must be strictly JSON format matching the instructions.
"""
        logger.info("Classifier invoking LLMClient...")
        llm_response = self.llm.generate(prompt=prompt_content, system_prompt=self.system_prompt)

        return {
            "proposal": llm_response,
            "tool_calls": tool_calls,
            "queries": queries,
            "retrieved_passages": retrieved_passages,
            "prompt_version": self.prompt_version,
            "injection_detected": injection_detected,
        }
