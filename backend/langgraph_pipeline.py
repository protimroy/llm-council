"""Optional LangGraph orchestration for LLM Council.

This module exposes the current council pipeline through a LangGraph graph
without replacing the existing hand-written orchestrator. It is intended as
an integration layer so the project can experiment with graph-based execution
while preserving the stable API path in backend.council.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .council import (
    _run_original_pipeline,
    aggregate_from_critique,
    run_second_round,
    stage1_collect_responses,
    stage2_critique_claims,
    stage3_synthesize_final,
)
from .judge import fast_judge_triage, post_verification_judge, select_verification_targets
from .models import CritiqueReport, FastJudgeDecision, FinalDecision, FinalDecisionType, TriageDecision, VerificationReport
from .verification import run_verification

logger = logging.getLogger(__name__)


class CouncilGraphState(TypedDict, total=False):
    user_query: str
    stage1_results: List[Dict[str, Any]]
    stage2_results: List[Dict[str, Any]]
    stage3_result: Dict[str, Any]
    metadata: Dict[str, Any]
    label_to_model: Dict[str, str]
    aggregate_rankings: List[Dict[str, Any]]
    critique_report: Optional[CritiqueReport]
    judge_decision: Optional[FastJudgeDecision]
    verification_report: Optional[VerificationReport]
    final_decision: Optional[FinalDecision]


async def _stage1_node(state: CouncilGraphState) -> CouncilGraphState:
    stage1_results = await stage1_collect_responses(state["user_query"])
    if not stage1_results:
        raise RuntimeError("All models failed to respond")
    return {"stage1_results": stage1_results}


async def _stage2_node(state: CouncilGraphState) -> CouncilGraphState:
    stage2_results, label_to_model, critique_report = await stage2_critique_claims(
        state["user_query"], state["stage1_results"]
    )
    aggregate_rankings = aggregate_from_critique(critique_report, label_to_model)
    return {
        "stage2_results": stage2_results,
        "label_to_model": label_to_model,
        "critique_report": critique_report,
        "aggregate_rankings": aggregate_rankings,
    }


async def _judge_node(state: CouncilGraphState) -> CouncilGraphState:
    judge_decision = fast_judge_triage(state.get("critique_report"))
    return {"judge_decision": judge_decision}


async def _verification_node(state: CouncilGraphState) -> CouncilGraphState:
    judge_decision = state.get("judge_decision")
    critique_report = state.get("critique_report")
    stage1_results = state.get("stage1_results", [])

    verification_report = None
    if judge_decision and judge_decision.decision == TriageDecision.escalate_for_verification:
        targets = select_verification_targets(judge_decision, critique_report, stage1_results)
        if targets:
            verification_report = await run_verification(targets)

    return {"verification_report": verification_report}


async def _post_judge_node(state: CouncilGraphState) -> CouncilGraphState:
    final_decision = post_verification_judge(
        state.get("critique_report"),
        state["judge_decision"],
        state.get("verification_report"),
    )
    return {"final_decision": final_decision}


async def _second_round_node(state: CouncilGraphState) -> CouncilGraphState:
    stage1_results, stage2_results, stage3_result, metadata = await run_second_round(
        state["user_query"],
        state["final_decision"],
        state["stage1_results"],
        critique_report=state.get("critique_report"),
        verification_report=state.get("verification_report"),
        round_number=1,
    )
    return {
        "stage1_results": stage1_results,
        "stage2_results": stage2_results,
        "stage3_result": stage3_result,
        "metadata": metadata,
    }


async def _synthesis_node(state: CouncilGraphState) -> CouncilGraphState:
    stage3_result = await stage3_synthesize_final(
        state["user_query"],
        state["stage1_results"],
        state["stage2_results"],
        critique_report=state.get("critique_report"),
        final_decision=state.get("final_decision"),
        verification_report=state.get("verification_report"),
    )
    metadata = {
        "label_to_model": state.get("label_to_model", {}),
        "aggregate_rankings": state.get("aggregate_rankings", []),
        "critique_report": state["critique_report"].model_dump() if state.get("critique_report") else None,
        "judge_decision": state["judge_decision"].model_dump() if state.get("judge_decision") else None,
        "verification_report": state["verification_report"].model_dump() if state.get("verification_report") else None,
        "final_decision": state["final_decision"].model_dump() if state.get("final_decision") else None,
        "engine": "langgraph",
    }
    return {"stage3_result": stage3_result, "metadata": metadata}


def _route_after_judge(state: CouncilGraphState) -> str:
    judge_decision = state.get("judge_decision")
    if judge_decision and judge_decision.decision == TriageDecision.escalate_for_verification:
        return "verification"
    return "post_judge"


def _route_after_post_judge(state: CouncilGraphState) -> str:
    final_decision = state.get("final_decision")
    if final_decision and final_decision.decision == FinalDecisionType.second_round:
        return "second_round"
    return "synthesis"


def build_council_graph():
    workflow = StateGraph(CouncilGraphState)
    workflow.add_node("stage1", _stage1_node)
    workflow.add_node("stage2", _stage2_node)
    workflow.add_node("judge", _judge_node)
    workflow.add_node("verification", _verification_node)
    workflow.add_node("post_judge", _post_judge_node)
    workflow.add_node("second_round", _second_round_node)
    workflow.add_node("synthesis", _synthesis_node)

    workflow.set_entry_point("stage1")
    workflow.add_edge("stage1", "stage2")
    workflow.add_edge("stage2", "judge")
    workflow.add_conditional_edges(
        "judge",
        _route_after_judge,
        {
            "verification": "verification",
            "post_judge": "post_judge",
        },
    )
    workflow.add_edge("verification", "post_judge")
    workflow.add_conditional_edges(
        "post_judge",
        _route_after_post_judge,
        {
            "second_round": "second_round",
            "synthesis": "synthesis",
        },
    )
    workflow.add_edge("second_round", END)
    workflow.add_edge("synthesis", END)
    return workflow.compile()


_COMPILED_COUNCIL_GRAPH = build_council_graph()


async def run_full_council_langgraph(user_query: str):
    """Run the council pipeline through LangGraph.

    Returns the same tuple shape as backend.council.run_full_council.
    Falls back to the original ranking pipeline if graph execution fails.
    """
    try:
        state = await _COMPILED_COUNCIL_GRAPH.ainvoke({"user_query": user_query})
        return (
            state.get("stage1_results", []),
            state.get("stage2_results", []),
            state.get("stage3_result", {"model": "error", "response": "No synthesis produced."}),
            state.get("metadata", {"engine": "langgraph"}),
        )
    except Exception as exc:
        logger.warning("LangGraph pipeline failed, falling back to original pipeline: %s", exc, exc_info=True)
        stage1_results = await stage1_collect_responses(user_query)
        if not stage1_results:
            return [], [], {"model": "error", "response": "All models failed to respond. Please try again."}, {}
        return await _run_original_pipeline(user_query, stage1_results)
