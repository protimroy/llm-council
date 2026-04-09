"""Fast Judge triage layer.

Decides whether the current evidence is sufficient to synthesize,
or whether the system needs to verify claims or request a second round
of specialist input.

The v1 heuristic is rule-based, not LLM-powered. It examines the
CritiqueReport for load-bearing disagreements, severity levels, and
evidence strength to make a triage decision.
"""

import logging
from typing import List, Optional

from .models import (
    CritiqueReport, FastJudgeDecision, TriageDecision, FinalDecision, FinalDecisionType,
    SeverityLevel, VerificationTarget, VerificationTargetType,
    VerificationReport, VerificationStatus,
)

logger = logging.getLogger(__name__)


def fast_judge_triage(critique_report: Optional[CritiqueReport]) -> FastJudgeDecision:
    """Make a triage decision based on the structured critique report.

    v1 heuristic:
    - If no critique report → synthesize_now (safe fallback)
    - If any load-bearing point with would_change_recommendation=True
      AND evidence is weak/speculative/mixed → escalate_for_verification
    - If high-severity + high-impact disagreements exist but evidence
      is not clearly weak → request_second_round
    - Otherwise → synthesize_now

    Args:
        critique_report: The merged CritiqueReport from Stage 2 (may be None).

    Returns:
        FastJudgeDecision with decision, rationale, and target lists.
    """
    if critique_report is None:
        logger.info("Fast Judge: no critique report, defaulting to synthesize_now")
        return FastJudgeDecision(
            decision=TriageDecision.synthesize_now,
            rationale="No structured critique available. Proceeding with synthesis.",
            confidence=SeverityLevel.low,
            diagnostic_notes=["No critique report provided to Fast Judge."]
        )

    # Extract key signals
    disagreements = critique_report.disagreements
    load_bearing = critique_report.candidate_load_bearing_points
    minority_alerts = critique_report.minority_alerts
    agreements = critique_report.agreements

    # Check for load-bearing points that would change the recommendation
    needs_verification = False
    verification_claim_ids: List[str] = []
    verification_rationale_parts: List[str] = []

    for lb in load_bearing:
        if lb.would_change_recommendation:
            # Find the associated disagreement to check evidence strength
            associated_disagreement = None
            for d in disagreements:
                if d.disagreement_id == lb.disagreement_id:
                    associated_disagreement = d
                    break

            evidence_strength = (
                associated_disagreement.evidence_strength_summary.lower()
                if associated_disagreement
                else "unknown"
            )

            # Escalate if evidence is weak, mixed, or speculative
            weak_evidence = any(
                keyword in evidence_strength
                for keyword in ["weak", "speculative", "mixed", "unknown"]
            )

            if weak_evidence or associated_disagreement is None:
                needs_verification = True
                if associated_disagreement:
                    verification_claim_ids.extend(associated_disagreement.claim_ids)
                verification_rationale_parts.append(
                    f"Load-bearing point '{lb.disagreement_id}' with weak evidence "
                    f"(strength: {evidence_strength})"
                )

    # Check for high-severity + high-impact disagreements
    high_severity_disagreements = [
        d for d in disagreements
        if d.disagreement_severity == SeverityLevel.high
        and d.decision_impact == SeverityLevel.high
    ]

    needs_second_round = False
    second_round_rationale_parts: List[str] = []

    if high_severity_disagreements and not needs_verification:
        # High severity but evidence might be strong enough — need more detail
        needs_second_round = True
        for d in high_severity_disagreements:
            second_round_rationale_parts.append(
                f"High-severity disagreement '{d.disagreement_id}': {d.description}"
            )

    # Collect all agreement and disagreement IDs
    all_agreement_ids = [a.agreement_id for a in agreements]
    all_disagreement_ids = [d.disagreement_id for d in disagreements]
    minority_alert_ids = [
        a.alert_id for a in minority_alerts if a.preserve_in_synthesis
    ]

    # Make the decision
    if needs_verification:
        decision = TriageDecision.escalate_for_verification
        rationale = (
            "Load-bearing disagreements with weak evidence detected. "
            "Targeted verification may resolve key uncertainties. "
            + " ".join(verification_rationale_parts)
        )
        confidence = SeverityLevel.medium
    elif needs_second_round:
        decision = TriageDecision.request_second_round
        rationale = (
            "High-severity disagreements require more specialist input. "
            + " ".join(second_round_rationale_parts)
        )
        confidence = SeverityLevel.medium
    else:
        decision = TriageDecision.synthesize_now
        rationale = (
            f"Agreements ({len(agreements)}) outweigh unresolved disagreements "
            f"({len(disagreements)}). Evidence is sufficient for synthesis."
        )
        confidence = SeverityLevel.high

    logger.info(
        f"Fast Judge decision: {decision.value}, "
        f"confidence: {confidence.value}, "
        f"agreements: {len(agreements)}, "
        f"disagreements: {len(disagreements)}, "
        f"load_bearing: {len(load_bearing)}, "
        f"verification_targets: {len(verification_claim_ids)}"
    )

    return FastJudgeDecision(
        decision=decision,
        rationale=rationale,
        confidence=confidence,
        prioritized_issues=all_disagreement_ids,
        selected_agreements=all_agreement_ids,
        selected_disagreements=all_disagreement_ids,
        minority_alerts_to_preserve=minority_alert_ids,
        verification_targets=verification_claim_ids if verification_claim_ids else None,
        second_round_targets=(
            [d.disagreement_id for d in high_severity_disagreements]
            if needs_second_round else None
        ),
        diagnostic_notes=[
            f"Agreements: {len(agreements)}",
            f"Disagreements: {len(disagreements)}",
            f"Load-bearing: {len(load_bearing)}",
            f"Minority alerts: {len(minority_alerts)}",
        ]
    )


def select_verification_targets(
    judge_decision: FastJudgeDecision,
    critique_report: Optional[CritiqueReport],
    stage1_results: List[dict]
) -> List[VerificationTarget]:
    """Select verification targets from the Fast Judge decision.

    For each claim_id in judge_decision.verification_targets, look up
    the source claim in stage1_results evidence packets. Create a
    VerificationTarget for each testable claim.

    Only claims with both falsifiable_hypothesis and test_logic become
    python_check targets. Claims without test_logic become not_testable.
    Capped at 3 targets for v1.

    Args:
        judge_decision: The Fast Judge triage decision.
        critique_report: The merged CritiqueReport (may be None).
        stage1_results: Results from Stage 1 (with evidence_packet fields).

    Returns:
        List of VerificationTarget objects (max 3).
    """
    if not judge_decision.verification_targets:
        return []

    # Build a lookup of all claims from all evidence packets
    all_claims: dict = {}  # claim_id -> (claim_dict, model_name)
    for result in stage1_results:
        packet = result.get('evidence_packet')
        if not packet:
            continue
        model_name = result.get('model', 'unknown')
        for claim in packet.get('claims', []):
            claim_id = claim.get('claim_id', '')
            if claim_id:
                all_claims[claim_id] = (claim, model_name)

    targets: List[VerificationTarget] = []
    target_count = 0

    for claim_id in judge_decision.verification_targets:
        if target_count >= 3:
            logger.info(f"Verification target cap (3) reached, skipping {claim_id}")
            break

        if claim_id not in all_claims:
            logger.warning(f"Claim {claim_id} not found in evidence packets, skipping")
            continue

        claim, model_name = all_claims[claim_id]

        # Determine target type based on available fields
        test_logic = claim.get('test_logic')
        hypothesis = claim.get('falsifiable_hypothesis', '')

        if test_logic and isinstance(test_logic, str) and test_logic.strip():
            target_type = VerificationTargetType.python_check
        else:
            target_type = VerificationTargetType.not_testable

        target = VerificationTarget(
            target_id=f"vt_{target_count + 1}",
            source_claim_id=claim_id,
            source_model_name=model_name,
            target_type=target_type,
            hypothesis=hypothesis or claim.get('claim_text', ''),
            test_logic=test_logic if target_type == VerificationTargetType.python_check else None,
            expected_signal=f"Claim should {'pass' if target_type == VerificationTargetType.python_check else 'be evaluated manually'}",
            risk_if_wrong=claim.get('risk_if_wrong', 'medium'),
            timeout_seconds=5,
        )
        targets.append(target)
        target_count += 1

        logger.info(
            f"Verification target: {target.target_id} for claim {claim_id} "
            f"from {model_name}, type={target_type.value}"
        )

    return targets


def post_verification_judge(
    critique_report: Optional[CritiqueReport],
    judge_decision: FastJudgeDecision,
    verification_report: Optional[VerificationReport]
) -> FinalDecision:
    """Make the final reasoning decision after verification results are in.

    Classifies claims as resolved, rejected, or unresolved based on
    verification outcomes and the critique report.

    Decision logic:
    - If no failed verifications and no critical unresolved → synthesize
    - If critical unresolved claims exist → second_round
    - Otherwise → unresolved (with explanation)

    Args:
        critique_report: The merged CritiqueReport (may be None).
        judge_decision: The Fast Judge triage decision.
        verification_report: The verification report (may be None if not escalated).

    Returns:
        FinalDecision with classification of claims and next actions.
    """
    from .models import FinalDecision, FinalDecisionType

    # If no critique report, default to synthesis
    if critique_report is None:
        return FinalDecision(
            decision=FinalDecisionType.synthesize,
            rationale="No structured critique available. Proceeding with synthesis.",
            confidence=SeverityLevel.low,
            verification_summary="No verification performed.",
            next_actions=["Proceed with synthesis using available data."]
        )

    # Classify claims based on verification results
    resolved_claims: List[str] = []
    rejected_claims: List[str] = []
    unresolved_claims: List[str] = []

    if verification_report and verification_report.results:
        for result in verification_report.results:
            claim_id = result.source_claim_id
            if result.status == VerificationStatus.passed:
                resolved_claims.append(claim_id)
            elif result.status == VerificationStatus.failed:
                rejected_claims.append(claim_id)
            else:
                # not_testable, timeout, error, skipped
                unresolved_claims.append(claim_id)
    else:
        # No verification was run — all disagreements are unresolved
        for d in critique_report.disagreements:
            unresolved_claims.extend(d.claim_ids)

    # Collect preserved disagreements and minority alerts
    preserved_disagreements = judge_decision.selected_disagreements
    minority_alerts = judge_decision.minority_alerts_to_preserve

    # Determine decision
    has_critical_unresolved = len(unresolved_claims) > 0 and len(rejected_claims) == 0
    has_failures = len(rejected_claims) > 0

    if has_failures:
        # Some claims were actively disproven — need more investigation
        decision = FinalDecisionType.second_round
        rationale = (
            f"Verification found {len(rejected_claims)} rejected claims. "
            f"Further investigation needed before synthesis."
        )
        confidence = SeverityLevel.medium
    elif has_critical_unresolved:
        # Claims couldn't be verified — uncertain but not disproven
        decision = FinalDecisionType.unresolved
        rationale = (
            f"{len(unresolved_claims)} claims could not be verified. "
            f"Proceeding with synthesis but noting uncertainty."
        )
        confidence = SeverityLevel.low
    else:
        # All verified claims passed, or no verification was needed
        decision = FinalDecisionType.synthesize
        rationale = (
            f"All {len(resolved_claims)} verified claims passed. "
            f"Proceeding with synthesis."
        )
        confidence = SeverityLevel.high

    # Build verification summary
    if verification_report:
        verification_summary = verification_report.summary
    else:
        verification_summary = "No verification was performed (not escalated)."

    # Build next actions
    next_actions = []
    if decision == FinalDecisionType.synthesize:
        next_actions.append("Synthesize final answer from verified claims and agreements.")
        if preserved_disagreements:
            next_actions.append("Preserve unresolved disagreements in synthesis.")
        if minority_alerts:
            next_actions.append("Include minority insights in final answer.")
    elif decision == FinalDecisionType.second_round:
        next_actions.append("Generate targeted follow-up questions for rejected claims.")
        next_actions.append("Re-run specialists with focused queries.")
    else:  # unresolved
        next_actions.append("Synthesize with uncertainty acknowledgment.")
        next_actions.append("Flag unresolved claims in the final answer.")

    logger.info(
        f"Post-verification judge: {decision.value}, "
        f"resolved={len(resolved_claims)}, "
        f"rejected={len(rejected_claims)}, "
        f"unresolved={len(unresolved_claims)}"
    )

    return FinalDecision(
        decision=decision,
        rationale=rationale,
        confidence=confidence,
        resolved_claims=resolved_claims,
        rejected_claims=rejected_claims,
        unresolved_claims=unresolved_claims,
        preserved_disagreements=preserved_disagreements,
        minority_alerts=minority_alerts,
        verification_summary=verification_summary,
        next_actions=next_actions
    )