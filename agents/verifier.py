"""Verifier agent: audits citations against retrieved passages, GRI compliance, and routing."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional
from common.config import settings
from common.logging import logger
from llm.providers import get_llm_client
from retrieval.tools import search_corpus, get_clause


def _citation_to_clause_id(cit: str) -> Optional[str]:
    """Maps human-readable or variations of legal citations to canonical corpus clause_ids."""
    c = cit.strip().upper()
    # DGFT citations: "DGFT-9617", "DGFT CHAPTER 96 HEADING 9617", "DGFT-7323"
    m_dgft = re.search(r"DGFT.*?(73\d{2}|96\d{2})\b", c)
    if m_dgft:
        return f"DGFT-{m_dgft.group(1)}"

    # Heading citations: "HEADING 9617", "HD9617", "9617"
    m_hd = re.search(r"(?:HEADING|HD)?\s*(73\d{2}|96\d{2})\b", c)
    if m_hd:
        return f"HD{m_hd.group(1)}"

    # GRI citations: "GRI 1", "GRI-1", "GRI 2(A)", etc.
    m_gri = re.search(r"GRI[-\s]*([1-6](?:[A-Z]|\([A-Z]\))?)", c)
    if m_gri:
        rule = m_gri.group(1).replace("(", "").replace(")", "")
        return f"GRI-{rule}"

    # Section XV Note 1(m): "SECTION XV NOTE 1(M)", "SEC-XV-NOTE-1M"
    if "XV" in c and "1" in c and "M" in c:
        return "SEC-XV-NOTE-1M"
    if "XV" in c and "2" in c:
        return "SEC-XV-NOTE-2"
    if "XX" in c and "1" in c:
        return "SEC-XX-NOTE-1"

    return None


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
        retry_allowed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Audits proposal:
        1. Checks citations resolve to retrieved text
        2. Assesses grounding and logic
        3. On failure, optionally triggers a secondary fallback search strategy
        4. Decides final route: clear-for-filing | seek-product-clarification | specialist-classification-review
        """
        if retry_allowed is None:
            retry_allowed = (
                os.environ.get("VERIFIER_RETRY_ENABLED", "true").lower() in ("true", "1", "yes")
                and getattr(settings, "VERIFIER_RETRY_ENABLED", True)
            )
        citations = proposal.get("citations", [])
        raw_heading = proposal.get("resolved_heading")
        resolved_heading = None
        if raw_heading:
            m = re.search(r"\b(73\d{2}|96\d{2}|\d{4})\b", str(raw_heading))
            resolved_heading = m.group(1) if m else str(raw_heading).strip()
            proposal["resolved_heading"] = resolved_heading

        proposal_route = proposal.get("route", "specialist-classification-review")

        # Collect clause IDs, titles, and text of all retrieved passages
        retrieved_clause_ids = {
            str(p.get("clause_id", "")).strip().upper()
            for p in retrieved_passages
            if p.get("clause_id")
        }
        retrieved_titles = [str(p.get("title", "")).lower() for p in retrieved_passages]
        retrieved_texts = [str(p.get("text", "")).lower() for p in retrieved_passages]
        retrieved_corpus_text = " ".join([
            str(p.get("text", "")) + " " + str(p.get("title", "")) + " " + str(p.get("clause_id", ""))
            for p in retrieved_passages
        ]).lower()

        verified_citations: List[str] = []
        unverified_citations: List[str] = []

        # Audit each citation against retrieved corpus passages
        for citation in citations:
            cit_str = str(citation).strip()
            cit_upper = cit_str.upper()
            cit_lower = cit_str.lower()

            # 1. Exact clause_id match
            if cit_upper in retrieved_clause_ids:
                verified_citations.append(citation)
                continue

            # 2. Normalized clause_id match
            norm_id = _citation_to_clause_id(cit_str)
            if norm_id and norm_id.upper() in retrieved_clause_ids:
                verified_citations.append(citation)
                continue

            # 3. Exact substring match in retrieved titles or texts
            if (
                cit_lower in retrieved_corpus_text
                or any(cit_lower in t for t in retrieved_titles)
                or any(cit_lower in txt for txt in retrieved_texts)
            ):
                verified_citations.append(citation)
                continue

            # 4. Token match against corpus text
            cit_clean = cit_lower.replace("-", " ").replace(":", " ")
            cit_words = [
                w for w in cit_clean.split()
                if len(w) >= 2 and w not in ["heading", "rule", "note", "section", "chapter", "the", "for", "and", "of"]
            ]
            if cit_words and any(w in retrieved_corpus_text for w in cit_words):
                verified_citations.append(citation)
            else:
                unverified_citations.append(citation)

        # Check for out-of-scope or clarification conditions
        if proposal_route in ["specialist-classification-review", "seek-product-clarification"]:
            return {
                "verified": True,
                "route": proposal_route,
                "basis": proposal.get("basis", "Product out of scope or requires product clarification."),
                "citations_verified": verified_citations,
                "issues": unverified_citations,
                "strategy_retry_used": False,
            }

        if not resolved_heading:
            return {
                "verified": False,
                "route": "specialist-classification-review",
                "basis": proposal.get("basis", "No resolved heading proposed; escalating for review."),
                "citations_verified": verified_citations,
                "issues": unverified_citations,
                "strategy_retry_used": False,
            }

        # Check citation grounding failure - fetch cited clause by ID before rejecting
        if unverified_citations and retry_allowed:
            logger.warning(f"Verification caught unverified citations: {unverified_citations}. Triggering fetch-by-ID retry search...")
            for uncit in unverified_citations:
                # 1. Try direct clause ID lookup
                clause = get_clause(uncit.strip())
                if clause:
                    retrieved_passages.append(clause)
                    continue

                # 2. Try normalized clause ID lookup
                norm_id = _citation_to_clause_id(uncit)
                if norm_id:
                    clause = get_clause(norm_id)
                    if clause:
                        retrieved_passages.append(clause)
                        continue

                # 3. Fallback vector search on fulltext corpus
                extra_search = search_corpus(query=uncit, collection="fulltext", top_k=2)
                retrieved_passages.extend(extra_search)

            # Re-verify once with fetched evidence
            return self.verify(proposal, retrieved_passages, retry_allowed=False)

        if unverified_citations and not retry_allowed:
            logger.error(f"Secondary search strategy failed to resolve citations. Escalating to specialist review: {unverified_citations}")
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
