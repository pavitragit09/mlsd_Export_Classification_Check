"""Key difficult case test: Stainless steel vacuum flask with a moulded plastic outer body."""

from agents.graph import compiled_graph, GraphState
from retrieval.tools import search_corpus


def test_vacuum_flask_end_to_end_resolution():
    description = "Stainless steel vacuum flask with a moulded plastic outer body."
    materials = ["stainless_steel", "plastic"]

    # 1. Verify retrieval finds Heading 9617 rather than falling into Chapter 73
    title_search = search_corpus(query="vacuum flask", collection="headings", top_k=2)
    assert any(h["heading"] == "9617" for h in title_search)

    # 2. Execute full LangGraph agent workflow
    state = GraphState(
        run_id="test-flask-run-01",
        correlation_id="test-flask-corr-01",
        request_data={
            "description": description,
            "materials": materials,
            "intended_use": "Insulated food/beverage storage",
        },
    )

    final_state = compiled_graph.invoke(state)
    result = final_state.get("final_result", {}) if isinstance(final_state, dict) else final_state.final_result

    # 3. Assertions on output
    assert result is not None
    assert result["route"] == "clear-for-filing"
    assert result["resolved_heading"] == "9617"
    assert "9617" in (result["tariff_code"] or "")
    assert "GRI 1" in result["gri_rule"]

    # Citations must include Heading 9617 and Section XV Note 1(m) exclusion
    cit_text = " ".join(result["citations"]).lower()
    assert "9617" in cit_text
    assert "section xv" in cit_text or "note 1(m)" in cit_text

    # Guardrail check: disclaimer must be present, no claims of filing
    assert "PROPOSAL ONLY" in result["basis"]
    assert "have filed" not in result["basis"].lower()
