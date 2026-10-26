"""LangGraph agent orchestration combining Classifier, Verifier, bounds, and guardrails."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from common.config import settings
from common.logging import logger
from common.security import filter_model_output
from common.telemetry import set_correlation_id
from retrieval.tools import set_active_request
from agents.classifier import ClassifierAgent
from agents.verifier import VerifierAgent


class GraphState(BaseModel):
    run_id: str
    correlation_id: str
    request_data: Dict[str, Any]
    step_count: int = 0
    tool_call_count: int = 0
    start_time: float = Field(default_factory=time.perf_counter)
    per_step_latency: Dict[str, float] = Field(default_factory=dict)
    queries: List[str] = Field(default_factory=list)
    retrieved_passages: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    proposal: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    final_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    prompt_version: str = settings.PROMPT_VERSION


def classifier_node(state: GraphState) -> GraphState:
    t0 = time.perf_counter()
    set_correlation_id(state.correlation_id)
    set_active_request(state.request_data)

    logger.info(f"Agent step {state.step_count + 1}: Executing ClassifierAgent")
    
    # Check bounded limits
    if time.perf_counter() - state.start_time > settings.AGENT_WALL_CLOCK_TIMEOUT_SEC:
        state.error = "Agent wall-clock timeout exceeded during classification"
        logger.error(state.error)
        return state

    try:
        classifier = ClassifierAgent(prompt_version=state.prompt_version)
        result = classifier.run(state.request_data)
        state.proposal = result.get("proposal", {})
        state.queries.extend(result.get("queries", []))
        state.retrieved_passages.extend(result.get("retrieved_passages", []))
        state.tool_calls.extend(result.get("tool_calls", []))
        state.tool_call_count += len(result.get("tool_calls", []))
        state.prompt_version = result.get("prompt_version", state.prompt_version)
    except Exception as e:
        logger.error(f"ClassifierAgent encountered an error: {e}", exc_info=True)
        state.error = f"Classifier error: {str(e)}"
        state.proposal = {
            "route": "specialist-classification-review",
            "basis": f"Agent failure during classification: {str(e)}. Escalated for manual review.",
            "citations": [],
        }

    state.step_count += 1
    state.per_step_latency["classifier"] = round(time.perf_counter() - t0, 3)
    return state


def verifier_node(state: GraphState) -> GraphState:
    t0 = time.perf_counter()
    set_correlation_id(state.correlation_id)
    set_active_request(state.request_data)

    logger.info(f"Agent step {state.step_count + 1}: Executing VerifierAgent")

    # Check bounds
    if time.perf_counter() - state.start_time > settings.AGENT_WALL_CLOCK_TIMEOUT_SEC:
        state.error = "Agent wall-clock timeout exceeded before verification"
        logger.error(state.error)
        return state

    if state.error or not state.proposal:
        state.verification = {
            "verified": False,
            "route": "specialist-classification-review",
            "basis": state.error or "No valid proposal generated",
            "citations_verified": [],
        }
        state.step_count += 1
        state.per_step_latency["verifier"] = round(time.perf_counter() - t0, 3)
        return state

    try:
        verifier = VerifierAgent()
        verif_result = verifier.verify(
            proposal=state.proposal,
            retrieved_passages=state.retrieved_passages,
        )
        state.verification = verif_result
    except Exception as e:
        logger.error(f"VerifierAgent encountered an error: {e}", exc_info=True)
        state.verification = {
            "verified": False,
            "route": "specialist-classification-review",
            "basis": f"Verifier failure mid-run: {str(e)}. Escalating as unverified.",
            "citations_verified": [],
        }

    state.step_count += 1
    state.per_step_latency["verifier"] = round(time.perf_counter() - t0, 3)
    return state


def guardrail_node(state: GraphState) -> GraphState:
    t0 = time.perf_counter()
    logger.info("Applying security output filter & guardrail...")

    proposal = state.proposal or {}
    verif = state.verification or {}

    final_route = verif.get("route") or proposal.get("route") or "specialist-classification-review"
    raw_basis = verif.get("basis") or proposal.get("basis") or "Classification completed."
    filtered_basis = filter_model_output(raw_basis)

    final_citations = verif.get("citations_verified") or proposal.get("citations") or []
    tariff_code = proposal.get("tariff_code")
    resolved_heading = proposal.get("resolved_heading")
    gri_rule = proposal.get("gri_rule", "GRI 1")
    export_policy = proposal.get("export_policy")

    # If route is specialist review or clarification, nullify confident tariff code
    if final_route != "clear-for-filing":
        if final_route == "seek-product-clarification":
            tariff_code = None
            export_policy = None

    state.final_result = {
        "run_id": state.run_id,
        "correlation_id": state.correlation_id,
        "status": "done" if not state.error else "failed",
        "route": final_route,
        "basis": filtered_basis,
        "resolved_heading": resolved_heading,
        "tariff_code": tariff_code,
        "gri_rule": gri_rule,
        "export_policy": export_policy,
        "citations": final_citations,
        "prompt_version": state.prompt_version,
    }

    state.step_count += 1
    state.per_step_latency["guardrail"] = round(time.perf_counter() - t0, 3)
    return state


def build_classification_graph() -> Any:
    workflow = StateGraph(GraphState)

    workflow.add_node("classifier", classifier_node)
    workflow.add_node("verifier", verifier_node)
    workflow.add_node("guardrail", guardrail_node)

    workflow.set_entry_point("classifier")
    workflow.add_edge("classifier", "verifier")
    workflow.add_edge("verifier", "guardrail")
    workflow.add_edge("guardrail", END)

    return workflow.compile()


compiled_graph = build_classification_graph()
