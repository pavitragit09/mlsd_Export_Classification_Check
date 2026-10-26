"""Tests for routing decisions and escalation behavior."""

from agents.verifier import VerifierAgent


def test_routing_clear_for_filing():
    verifier = VerifierAgent()
    proposal = {
        "article": "Vacuum flask",
        "resolved_heading": "9617",
        "route": "clear-for-filing",
        "citations": ["Heading 9617", "GRI 1"],
        "basis": "Heading 9617 names the article directly.",
    }
    retrieved = [
        {"clause_id": "HD9617", "heading": "9617", "text": "Vacuum flasks and other vacuum vessels", "title": "Heading 9617"},
        {"clause_id": "GRI-1", "heading": "", "text": "GRI 1 terms of the headings and relative Section or Chapter Notes", "title": "GRI 1"}
    ]
    res = verifier.verify(proposal, retrieved)
    assert res["route"] == "clear-for-filing"
    assert res["verified"] is True


def test_routing_escalation_on_out_of_scope():
    verifier = VerifierAgent()
    proposal = {
        "article": "Lithium battery pack",
        "resolved_heading": None,
        "route": "specialist-classification-review",
        "citations": [],
        "basis": "Chapter 85 goods are outside Chapter 73/96 scope.",
    }
    retrieved = []
    res = verifier.verify(proposal, retrieved)
    assert res["route"] == "specialist-classification-review"
    assert "outside" in res["basis"].lower()


def test_routing_unsupported_citation_escalation():
    verifier = VerifierAgent()
    proposal = {
        "article": "Steel vessel",
        "resolved_heading": "7323",
        "route": "clear-for-filing",
        "citations": ["NonExistentRegulation-9999"],
        "basis": "Fabricated citation test.",
    }
    retrieved = [
        {"clause_id": "HD7323", "heading": "7323", "text": "Table articles", "title": "Heading 7323"}
    ]
    res = verifier.verify(proposal, retrieved, retry_allowed=False)
    assert res["route"] == "specialist-classification-review"
    assert res["verified"] is False
