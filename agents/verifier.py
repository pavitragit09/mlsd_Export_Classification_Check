"""Verifier agent: audits citations against retrieved passages, GRI compliance, and routing."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from common.config import settings
from common.logging import logger
from llm.providers import get_llm_client
from retrieval.tools import search_corpus, get_clause


def load_verifier_prompt() -> str:
    path = os.path.join("agents", "prompts", "verifier_v1.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "Audit proposed classification citations against retrieved passages."


class VerifierAgent:
    """Verifier agent auditing proposal claims, citations, and GRI rule compliance."""

    def __init__(self):
        self.system_prompt = load_verifier_prompt()
        self.llm = get_llm_client()

    def verify(
        self,
        proposal: Dict[str, Any],
        retrieved_passages: List[Dict[str, Any]],
        retry_allowed: bool = True,
    ) -> Dict[str, Any]:
        """
        Audits proposal:
        1. Checks citations resolve to retrieved text
        2. Assesses grounding and logic
        3. On failure, optionally triggers a secondary fallback search strategy
        4. Decides final route: clear-for-filing | seek-product-clarification | specialist-classification-review
        """
        citations = proposal.get("citations", [])
        resolved_heading = proposal.get("resolved_heading")
        proposal_route = proposal.get("route", "specialist-classification-review")

        # Collect text of all retrieved passages
        retrieved_corpus_text = " ".join([p.get("text", "") + " " + p.get("title", "") for p in retrieved_passages]).lower()

        verified_citations: List[str] = []
        unverified_citations: List[str] = []

        # Audit each citation against retrieved corpus text
        for citation in citations:
            cit_clean = citation.lower().replace("-", " ").replace(":", " ")
            cit_words = [
                w for w in cit_clean.split()
                if len(w) >= 3 and w not in ["heading", "rule", "note", "section", "chapter", "the", "for"]
            ]
            if cit_words and any(w in retrieved_corpus_text for w in cit_words):
                verified_citations.append(citation)
            else:
                unverified_citations.append(citation)

        # Check for out-of-scope conditions
        if proposal_route == "specialist-classification-review" or not resolved_heading:
            return {
                "verified": True,
                "route": "specialist-classification-review",
                "basis": proposal.get("basis", "Product out of scope or requires specialist review."),
                "citations_verified": verified_citations,
                "issues": unverified_citations,
                "strategy_retry_used": False,
            }

        # Check citation grounding failure
        if unverified_citations and retry_allowed:
            logger.warning(f"Verification caught unverified citations: {unverified_citations}. Triggering secondary search...")
            # Secondary search strategy: Search specifically for the missing citation clause
            missing_query = unverified_citations[0] if unverified_citations else f"Heading {resolved_heading}"
            extra_search = search_corpus(query=missing_query, collection="fulltext", top_k=3)
            retrieved_passages.extend(extra_search)
            # Re-verify once
            return self.verify(proposal, retrieved_passages, retry_allowed=False)

        if unverified_citations and not retry_allowed:
            logger.error("Secondary search strategy failed to resolve citations. Escalating.")
            return {
                "verified": False,
                "route": "specialist-classification-review",
                "basis": f"Verification failed: Citations could not be verified against regulatory corpus ({unverified_citations}).",
                "citations_verified": verified_citations,
                "issues": unverified_citations,
                "strategy_retry_used": True,
            }

        # LLM Verification call for deep logic audit
        verification_prompt = f"""
PROPOSED CLASSIFICATION:
{proposal}

RETRIEVED PASSAGES TO AUDIT AGAINST:
{[p.get('text', '')[:200] for p in retrieved_passages]}

Perform independent audit of citations and GRI order.
Output JSON format as per system prompt.
"""
        audit_res = self.llm.generate(prompt=verification_prompt, system_prompt=self.system_prompt)
        final_route = audit_res.get("route", proposal.get("route", "clear-for-filing"))
        final_basis = audit_res.get("basis", proposal.get("basis", "Classification verified."))

        return {
            "verified": audit_res.get("verified", True),
            "route": final_route,
            "basis": final_basis,
            "citations_verified": verified_citations,
            "issues": audit_res.get("issues", []),
            "strategy_retry_used": False,
        }
