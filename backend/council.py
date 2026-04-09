"""3-stage LLM Council orchestration.

Supports both the original baseline pipeline (whole-answer ranking)
and the new structured pipeline (evidence packets, claim critique,
fast judge triage, verification, and post-verification synthesis).
"""

import logging
from typing import List, Dict, Any, Tuple, Optional

from .openrouter import query_models_parallel, query_model
from .config import get_council_models, get_chairman_model
from .prompts import STAGE1_SPECIALIST_PROMPT, STAGE2_CRITIQUE_PROMPT
from .parsing import parse_evidence_packet, parse_critique_report

# Maximum number of second-round iterations to prevent infinite loops
MAX_ROUNDS = 2
from .models import (
    EvidencePacket, CritiqueReport, FastJudgeDecision, TriageDecision,
    VerificationTarget, VerificationTargetType, VerificationReport, VerificationResult,
    VerificationStatus, PostVerificationAction, FinalDecision, FinalDecisionType,
    SeverityLevel, RecommendedAction,
)
from .judge import fast_judge_triage, select_verification_targets, post_verification_judge
from .verification import run_verification

logger = logging.getLogger(__name__)


async def stage1_collect_responses(user_query: str) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Each model receives a system prompt instructing it to provide both
    a natural language answer and a structured evidence packet (claims,
    proposals). The evidence packet is parsed from the response; if
    parsing fails, a fallback packet with parse_error is created.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model', 'response', and 'evidence_packet' keys.
        'response' contains the human-readable prose (delimiter and JSON stripped).
        'evidence_packet' contains the parsed EvidencePacket dict (or fallback).
    """
    messages = [
        {"role": "system", "content": STAGE1_SPECIALIST_PROMPT},
        {"role": "user", "content": user_query}
    ]

    # Query all models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Parse each response
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            raw_content = response.get('content', '')
            answer_text, packet = parse_evidence_packet(raw_content, model)

            logger.info(
                f"{model}: raw_length={len(raw_content)}, "
                f"parse_ok={packet.parse_error is None}, "
                f"claims={len(packet.claims)}, "
                f"proposals={len(packet.proposals) if packet.proposals else 0}"
            )

            stage1_results.append({
                "model": model,
                "response": answer_text,
                "evidence_packet": packet.model_dump()
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage2_critique_claims(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str], Optional[CritiqueReport]]:
    """
    Stage 2 (new): Claim-level critique replacing whole-answer ranking.

    Each council model reviews anonymized claims from all specialists
    and produces a structured CritiqueReport identifying agreements,
    disagreements, load-bearing points, and minority alerts.

    Returns a backward-compatible stage2 results list (with 'model',
    'ranking', 'parsed_ranking', and 'critique' keys), the label_to_model
    mapping, and the merged CritiqueReport.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1 (with evidence_packet fields)

    Returns:
        Tuple of (stage2_results_list, label_to_model, merged_critique_report)
    """
    # Create anonymized labels for specialists (Specialist A, B, C, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]

    label_to_model = {
        f"Specialist {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build claims presentation from evidence packets
    claims_sections = []
    for label, result in zip(labels, stage1_results):
        packet_data = result.get('evidence_packet')
        if packet_data and packet_data.get('claims'):
            # Structured claims available
            claims_text = ""
            for claim in packet_data['claims']:
                claims_text += (
                    f"  - [{claim.get('claim_id', '?')}] {claim.get('claim_text', '')}\n"
                    f"    Type: {claim.get('claim_type', 'factual')}, "
                    f"Evidence: {claim.get('evidence_type', 'none')}, "
                    f"Confidence: {claim.get('confidence', 0.5)}\n"
                    f"    Falsifiable: {claim.get('falsifiable_hypothesis', 'N/A')}\n"
                    f"    Risk if wrong: {claim.get('risk_if_wrong', 'medium')}\n"
                )
            if packet_data.get('proposals'):
                claims_text += "\n  Proposals:\n"
                for prop in packet_data['proposals']:
                    claims_text += f"  - [{prop.get('proposal_id', '?')}] {prop.get('title', '')}: {prop.get('hypothesis', '')}\n"
            claims_sections.append(f"Specialist {label}:\n{claims_text}")
        else:
            # No structured claims — use the prose answer
            claims_sections.append(
                f"Specialist {label} (unstructured response):\n"
                f"  {result.get('response', 'No response available.')}\n"
            )

    claims_text = "\n\n".join(claims_sections)

    # Format the critique prompt
    critique_prompt = STAGE2_CRITIQUE_PROMPT.format(
        user_query=user_query,
        claims_text=claims_text
    )

    messages = [{"role": "user", "content": critique_prompt}]

    # Get critiques from all council models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Parse each response
    individual_reports: List[Optional[CritiqueReport]] = []
    stage2_results = []

    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            critique_prose, critique_report, parse_error = parse_critique_report(full_text)

            logger.info(
                f"{model}: critique parse_ok={critique_report is not None}, "
                f"error={parse_error}"
            )

            individual_reports.append(critique_report)

            # Backward-compatible result shape
            stage2_results.append({
                "model": model,
                "ranking": critique_prose,  # Frontend renders this via ReactMarkdown
                "parsed_ranking": [],  # Empty — old ranking format deprecated
                "critique": critique_report.model_dump() if critique_report else None
            })

    # Merge individual critique reports into a single report
    merged_report = _merge_critique_reports(individual_reports)

    if merged_report:
        logger.info(
            f"Merged critique: {len(merged_report.agreements)} agreements, "
            f"{len(merged_report.disagreements)} disagreements, "
            f"{len(merged_report.candidate_load_bearing_points)} load-bearing, "
            f"{len(merged_report.minority_alerts)} minority alerts"
        )

    return stage2_results, label_to_model, merged_report


def _merge_critique_reports(
    reports: List[Optional[CritiqueReport]]
) -> Optional[CritiqueReport]:
    """Merge multiple individual CritiqueReports into a single report.

    Strategy:
    - Agreements: union, dedup by overlapping supporting_claim_ids
    - Disagreements: union, dedup by overlapping claim_ids, take highest severity
    - Load-bearing candidates: union
    - Top hypotheses: union
    - Minority alerts: union, dedup by claim_id
    """
    from .models import (
        Agreement, Disagreement, LoadBearingCandidate,
        SelectedHypothesis, MinorityAlert
    )

    valid_reports = [r for r in reports if r is not None]
    if not valid_reports:
        return None

    if len(valid_reports) == 1:
        return valid_reports[0]

    # Merge agreements — dedup by overlapping supporting_claim_ids
    merged_agreements: List[Agreement] = []
    seen_claim_sets: list = []

    for report in valid_reports:
        for agreement in report.agreements:
            claim_set = set(agreement.supporting_claim_ids)
            # Check if we already have an agreement with overlapping claims
            merged = False
            for i, existing in enumerate(merged_agreements):
                existing_set = set(existing.supporting_claim_ids)
                if claim_set & existing_set:  # Overlap
                    # Merge: take the one with higher confidence
                    if agreement.aggregate_confidence > existing.aggregate_confidence:
                        merged_agreements[i] = agreement
                    merged = True
                    break
            if not merged:
                merged_agreements.append(agreement)

    # Merge disagreements — dedup by overlapping claim_ids, take highest severity
    severity_order = {"low": 0, "medium": 1, "high": 2}
    merged_disagreements: List[Disagreement] = []

    for report in valid_reports:
        for disagreement in report.disagreements:
            claim_set = set(disagreement.claim_ids)
            merged = False
            for i, existing in enumerate(merged_disagreements):
                existing_set = set(existing.claim_ids)
                if claim_set & existing_set:  # Overlap
                    # Take the one with higher severity
                    if (severity_order.get(disagreement.disagreement_severity.value, 0) >
                            severity_order.get(existing.disagreement_severity.value, 0)):
                        merged_disagreements[i] = disagreement
                    merged = True
                    break
            if not merged:
                merged_disagreements.append(disagreement)

    # Merge load-bearing candidates — union by disagreement_id
    merged_load_bearing: List[LoadBearingCandidate] = []
    seen_lb_ids = set()
    for report in valid_reports:
        for lb in report.candidate_load_bearing_points:
            if lb.disagreement_id not in seen_lb_ids:
                merged_load_bearing.append(lb)
                seen_lb_ids.add(lb.disagreement_id)

    # Merge top hypotheses — union by claim_id
    merged_hypotheses: List[SelectedHypothesis] = []
    seen_hyp_ids = set()
    for report in valid_reports:
        for hyp in report.top_hypotheses:
            if hyp.claim_id not in seen_hyp_ids:
                merged_hypotheses.append(hyp)
                seen_hyp_ids.add(hyp.claim_id)

    # Merge minority alerts — union by claim_id
    merged_alerts: List[MinorityAlert] = []
    seen_alert_ids = set()
    for report in valid_reports:
        for alert in report.minority_alerts:
            if alert.alert_id not in seen_alert_ids:
                merged_alerts.append(alert)
                seen_alert_ids.add(alert.alert_id)

    return CritiqueReport(
        agreements=merged_agreements,
        disagreements=merged_disagreements,
        candidate_load_bearing_points=merged_load_bearing,
        top_hypotheses=merged_hypotheses,
        minority_alerts=merged_alerts,
        critique_notes="Merged from multiple reviewer reports.",
        diagnostic_notes=f"Merged {len(valid_reports)} individual critique reports."
    )


def aggregate_from_critique(
    critique_report: Optional[CritiqueReport],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Compute synthetic aggregate rankings from a CritiqueReport.

    This produces a backward-compatible aggregate_rankings list for the
    frontend. Models are scored by: (claims in agreements) - (claims in
    disagreements). Higher score = better rank.

    Args:
        critique_report: The merged CritiqueReport (may be None).
        label_to_model: Mapping from "Specialist X" to model names.

    Returns:
        List of dicts with 'model', 'average_rank', and 'rankings_count'.
    """
    from collections import defaultdict

    if critique_report is None:
        # Fallback: equal ranking for all models
        return [
            {"model": model, "average_rank": 1.0, "rankings_count": 1}
            for model in label_to_model.values()
        ]

    # Count how many agreements and disagreements each model's claims appear in
    model_agreement_count: Dict[str, int] = defaultdict(int)
    model_disagreement_count: Dict[str, int] = defaultdict(int)

    # We need to map claim_ids back to models.
    # Since claims are anonymized, we use a simple heuristic:
    # claims with IDs like "c1", "c2" from Specialist A are mapped
    # via the label_to_model mapping. For v1, we score by model
    # based on how many of their claims appear in agreements vs disagreements.

    # Simple scoring: each model gets +1 for each agreement, -1 for each disagreement
    # Since we can't perfectly map claims to models in the anonymized view,
    # we use a proxy: distribute scores evenly across all models.
    num_models = len(label_to_model) or 1
    agreement_score = len(critique_report.agreements) / num_models
    disagreement_penalty = len(critique_report.disagreements) / num_models

    # Build scores for each model
    scores = {}
    for label, model in label_to_model.items():
        scores[model] = agreement_score - disagreement_penalty

    # Sort by score descending (higher = better)
    sorted_models = sorted(scores.keys(), key=lambda m: scores[m], reverse=True)

    # Convert to rank format
    result = []
    for rank, model in enumerate(sorted_models, start=1):
        result.append({
            "model": model,
            "average_rank": float(rank),
            "rankings_count": len(label_to_model)
        })

    return result


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    critique_report: Optional[CritiqueReport] = None,
    final_decision: Optional[FinalDecision] = None,
    verification_report: Optional[VerificationReport] = None
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    When structured data (critique_report, final_decision, verification_report)
    is available, the chairman prompt is enriched with agreements, disagreements,
    verification results, and guidance on what to emphasize.

    When no structured data is available, falls back to the original
    whole-answer ranking format.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Critique results from Stage 2
        critique_report: Optional merged CritiqueReport
        final_decision: Optional FinalDecision from post-verification judge
        verification_report: Optional VerificationReport

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build Stage 1 context (always available)
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    # Build Stage 2 context (always available)
    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nCritique: {result['ranking']}"
        for result in stage2_results
    ])

    # Choose prompt path based on available structured data
    if final_decision is not None and critique_report is not None:
        # Enriched prompt with structured data
        chairman_prompt = _build_enriched_prompt(
            user_query, stage1_text, stage2_text,
            critique_report, final_decision, verification_report
        )
    else:
        # Fallback: original prompt format
        chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then critiqued each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Critiques:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer critiques and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    chairman_model = get_chairman_model()
    response = await query_model(chairman_model, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": chairman_model,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": chairman_model,
        "response": response.get('content', '')
    }


def _build_enriched_prompt(
    user_query: str,
    stage1_text: str,
    stage2_text: str,
    critique_report: CritiqueReport,
    final_decision: FinalDecision,
    verification_report: Optional[VerificationReport] = None
) -> str:
    """Build an enriched chairman prompt using structured data.

    Args:
        user_query: The original user query
        stage1_text: Formatted Stage 1 responses
        stage2_text: Formatted Stage 2 critiques
        critique_report: The merged CritiqueReport
        final_decision: The FinalDecision from post-verification judge
        verification_report: Optional VerificationReport

    Returns:
        The enriched chairman prompt string.
    """
    # Agreements section
    agreements_text = ""
    if critique_report.agreements:
        agreements_text = "\n".join([
            f"- {a.shared_claim_summary} (confidence: {a.aggregate_confidence:.0%})"
            for a in critique_report.agreements
        ])
    else:
        agreements_text = "No strong agreements identified."

    # Disagreements section
    disagreements_text = ""
    if critique_report.disagreements:
        disagreements_text = "\n".join([
            f"- [{d.disagreement_severity.value} impact, {d.decision_impact.value} severity] {d.description}"
            for d in critique_report.disagreements
        ])
    else:
        disagreements_text = "No significant disagreements identified."

    # Minority alerts section
    minority_text = ""
    if critique_report.minority_alerts:
        minority_text = "\n".join([
            f"- {m.why_outlier} (may matter because: {m.why_might_matter})"
            for m in critique_report.minority_alerts
            if m.preserve_in_synthesis
        ])
    else:
        minority_text = "No minority alerts to preserve."

    # Verification results section
    verification_text = "No verification was performed."
    if verification_report and verification_report.results:
        verification_text = "\n".join([
            f"- Claim {r.source_claim_id}: {r.status.value} — {r.summary}"
            for r in verification_report.results
        ])

    # Decision context
    decision_context = f"""The council's analysis has reached the following conclusion:
- Decision: {final_decision.decision.value}
- Rationale: {final_decision.rationale}
- Confidence: {final_decision.confidence.value}
- Resolved claims: {len(final_decision.resolved_claims)}
- Rejected claims: {len(final_decision.rejected_claims)}
- Unresolved claims: {len(final_decision.unresolved_claims)}"""

    prompt = f"""You are the Chairman of a Self-Testing LLM Council. Multiple AI specialists have provided responses, critiqued each other's claims, and the system has verified key claims where possible.

Original Question: {user_query}

STAGE 1 - Specialist Responses:
{stage1_text}

STAGE 2 - Claim-Level Critique:
{stage2_text}

STRUCTURED ANALYSIS:

Agreements (well-supported claims):
{agreements_text}

Disagreements (conflicting claims):
{disagreements_text}

Minority Insights (outlier perspectives worth preserving):
{minority_text}

Verification Results:
{verification_text}

COUNCIL DECISION:
{decision_context}

Your task as Chairman is to synthesize a final answer that:
1. Emphasizes the well-supported agreements
2. Acknowledges and explains the disagreements
3. Preserves valuable minority insights
4. Notes any claims that were verified or could not be verified
5. Is honest about what remains uncertain

Provide a clear, well-reasoned final answer:"""

    return prompt


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_council(user_query: str) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete council process with structured pipeline.

    New pipeline (with fallback to original on error):
    1. Stage 1: Collect evidence packets from specialists
    2. Stage 2: Claim-level critique (replaces whole-answer ranking)
    3. Fast Judge: Triage decision (synthesize/verify/second_round)
    4. Verification: Run targeted checks if escalated (Stage 1.5)
    5. Post-verification judge: Final decision
    6. Stage 3: Synthesis enriched with structured data

    If any new stage fails, falls back to the original
    whole-answer ranking pipeline.

    Args:
        user_query: The user's question

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses (with evidence packets)
    stage1_results = await stage1_collect_responses(user_query)

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Try the new structured pipeline
    try:
        logger.info("Running structured pipeline (claim critique + fast judge + verification)")

        # Stage 2: Claim-level critique
        stage2_results, label_to_model, critique_report = await stage2_critique_claims(
            user_query, stage1_results
        )

        # Compute aggregate rankings from critique
        aggregate_rankings = aggregate_from_critique(critique_report, label_to_model)

        # Fast Judge: Triage decision
        judge_decision = fast_judge_triage(critique_report)
        logger.info(f"Fast Judge decision: {judge_decision.decision.value}")

        # Verification (if escalated)
        verification_report = None
        if judge_decision.decision == TriageDecision.escalate_for_verification:
            logger.info("Escalated for verification — selecting targets")
            targets = select_verification_targets(
                judge_decision, critique_report, stage1_results
            )
            if targets:
                logger.info(f"Running verification for {len(targets)} targets")
                verification_report = await run_verification(targets)
            else:
                logger.info("No testable verification targets found")

        # Post-verification judge: Final decision
        final_decision = post_verification_judge(
            critique_report, judge_decision, verification_report
        )
        logger.info(f"Post-verification decision: {final_decision.decision.value}")

        # Check if a second round is needed
        if final_decision.decision == FinalDecisionType.second_round:
            logger.info("Second round requested — re-querying specialists")
            return await run_second_round(
                user_query, final_decision, stage1_results,
                critique_report=critique_report,
                verification_report=verification_report,
                round_number=1
            )

        # Stage 3: Synthesis enriched with structured data
        stage3_result = await stage3_synthesize_final(
            user_query,
            stage1_results,
            stage2_results,
            critique_report=critique_report,
            final_decision=final_decision,
            verification_report=verification_report
        )

        # Prepare metadata (additive — includes all new fields)
        metadata = {
            "label_to_model": label_to_model,
            "aggregate_rankings": aggregate_rankings,
            "critique_report": critique_report.model_dump() if critique_report else None,
            "judge_decision": judge_decision.model_dump(),
            "verification_report": verification_report.model_dump() if verification_report else None,
            "final_decision": final_decision.model_dump(),
        }

        return stage1_results, stage2_results, stage3_result, metadata

    except Exception as e:
        # Fallback to original pipeline on any error
        logger.warning(
            f"Structured pipeline failed, falling back to original: {e}",
            exc_info=True
        )
        return await _run_original_pipeline(user_query, stage1_results)


async def _run_original_pipeline(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List, List, Dict, Dict]:
    """Run the original whole-answer ranking pipeline as a fallback.

    This preserves the baseline behavior if the new structured
    pipeline encounters any errors.

    Args:
        user_query: The user's question
        stage1_results: Already-collected Stage 1 results

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 2: Original whole-answer ranking
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Original synthesis
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results
    )

    # Prepare metadata (original format)
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "critique_report": None,
        "judge_decision": None,
        "verification_report": None,
        "final_decision": None,
    }

    return stage1_results, stage2_results, stage3_result, metadata


async def run_second_round(
    user_query: str,
    final_decision: FinalDecision,
    stage1_results: List[Dict[str, Any]],
    critique_report: Optional[CritiqueReport] = None,
    verification_report: Optional[VerificationReport] = None,
    round_number: int = 1
) -> Tuple[List, List, Dict, Dict]:
    """Execute a second round of specialist consultation.

    When FinalDecision.decision == "second_round", this function
    generates targeted follow-up queries based on unresolved claims
    and re-runs specialists with focused questions, then re-enters
    the pipeline from stage2.

    The second round:
    1. Builds a follow-up prompt from unresolved claims and next_actions
    2. Re-queries specialists with the follow-up question
    3. Merges new results with original stage1 results
    4. Re-enters the pipeline from stage2 (critique → judge → verify → synthesize)
    5. If the new final_decision is still "second_round" and round_number < MAX_ROUNDS,
       recurses; otherwise synthesizes with uncertainty acknowledgment

    Args:
        user_query: The original user query
        final_decision: The FinalDecision indicating second_round
        stage1_results: The original Stage 1 results
        critique_report: The previous CritiqueReport (for context)
        verification_report: The previous VerificationReport (for context)
        round_number: Current round number (1-based, max MAX_ROUNDS)

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    logger.info(
        f"Starting second round (round {round_number}/{MAX_ROUNDS}). "
        f"Unresolved claims: {final_decision.unresolved_claims}. "
        f"Next actions: {final_decision.next_actions}"
    )

    # ── Step 1: Build follow-up prompt ──────────────────────────────────

    follow_up_prompt = _build_follow_up_prompt(
        user_query, final_decision, critique_report, verification_report
    )

    # ── Step 2: Re-query specialists with follow-up ─────────────────────

    logger.info(f"Second round: querying specialists with follow-up prompt")
    follow_up_messages = [
        {"role": "system", "content": STAGE1_SPECIALIST_PROMPT},
        {"role": "user", "content": follow_up_prompt}
    ]

    follow_up_responses = await query_models_parallel(get_council_models(), follow_up_messages)

    # Parse follow-up responses
    follow_up_results = []
    for model, response in follow_up_responses.items():
        if response is not None:
            raw_content = response.get('content', '')
            answer_text, packet = parse_evidence_packet(raw_content, model)
            logger.info(
                f"Second round {model}: parse_ok={packet.parse_error is None}, "
                f"claims={len(packet.claims)}"
            )
            follow_up_results.append({
                "model": model,
                "response": answer_text,
                "evidence_packet": packet.model_dump(),
                "is_follow_up": True  # Mark as second-round response
            })

    if not follow_up_results:
        logger.warning("Second round: no follow-up responses, synthesizing with uncertainty")
        return await _synthesize_with_uncertainty(
            user_query, stage1_results, final_decision, critique_report, verification_report
        )

    # ── Step 3: Merge new results with original ─────────────────────────

    # Tag original results so we can distinguish them
    merged_results = []
    for r in stage1_results:
        merged_results.append({**r, "is_follow_up": False})
    merged_results.extend(follow_up_results)

    logger.info(f"Second round: merged {len(merged_results)} total results "
                f"({len(stage1_results)} original + {len(follow_up_results)} follow-up)")

    # ── Step 4: Re-enter pipeline from stage2 ───────────────────────────

    try:
        # Stage 2: Re-critique with merged results
        stage2_results, label_to_model, new_critique = await stage2_critique_claims(
            user_query, merged_results
        )

        # Compute aggregate rankings
        aggregate_rankings = aggregate_from_critique(new_critique, label_to_model)

        # Fast Judge: Re-triage
        judge_decision = fast_judge_triage(new_critique)
        logger.info(f"Second round Fast Judge decision: {judge_decision.decision.value}")

        # Verification (if escalated)
        new_verification_report = None
        if judge_decision.decision == TriageDecision.escalate_for_verification:
            targets = select_verification_targets(
                judge_decision, new_critique, merged_results
            )
            if targets:
                new_verification_report = await run_verification(targets)

        # Post-verification judge
        new_final_decision = post_verification_judge(
            new_critique, judge_decision, new_verification_report
        )
        logger.info(f"Second round post-verification decision: {new_final_decision.decision.value}")

        # ── Step 5: Check for another round ──────────────────────────────

        if (new_final_decision.decision == FinalDecisionType.second_round
                and round_number < MAX_ROUNDS):
            logger.info(f"Second round requests another round (round {round_number + 1})")
            return await run_second_round(
                user_query, new_final_decision, merged_results,
                critique_report=new_critique,
                verification_report=new_verification_report,
                round_number=round_number + 1
            )

        # ── Step 6: Synthesize with enriched data ────────────────────────

        stage3_result = await stage3_synthesize_final(
            user_query,
            merged_results,
            stage2_results,
            critique_report=new_critique,
            final_decision=new_final_decision,
            verification_report=new_verification_report
        )

        metadata = {
            "label_to_model": label_to_model,
            "aggregate_rankings": aggregate_rankings,
            "critique_report": new_critique.model_dump() if new_critique else None,
            "judge_decision": judge_decision.model_dump(),
            "verification_report": new_verification_report.model_dump() if new_verification_report else None,
            "final_decision": new_final_decision.model_dump(),
            "second_round": True,
            "round_number": round_number,
        }

        return merged_results, stage2_results, stage3_result, metadata

    except Exception as e:
        logger.warning(f"Second round pipeline failed, synthesizing with uncertainty: {e}", exc_info=True)
        return await _synthesize_with_uncertainty(
            user_query, merged_results, final_decision, critique_report, verification_report
        )


def _build_follow_up_prompt(
    user_query: str,
    final_decision: FinalDecision,
    critique_report: Optional[CritiqueReport] = None,
    verification_report: Optional[VerificationReport] = None
) -> str:
    """Build a targeted follow-up prompt for the second round.

    Combines the original question with specific unresolved claims,
    verification failures, and next actions from the FinalDecision.

    Args:
        user_query: The original user question
        final_decision: The FinalDecision from the first round
        critique_report: The previous CritiqueReport (may be None)
        verification_report: The previous VerificationReport (may be None)

    Returns:
        A follow-up prompt string for specialists.
    """
    parts = [
        f"ORIGINAL QUESTION: {user_query}",
        "",
        "The council has identified unresolved issues that need further investigation.",
        "",
    ]

    # Add unresolved claims
    if final_decision.unresolved_claims:
        parts.append("UNRESOLVED CLAIMS that need clarification:")
        for claim_id in final_decision.unresolved_claims:
            parts.append(f"  - {claim_id}")
        parts.append("")

    # Add rejected claims (verification failures)
    if final_decision.rejected_claims:
        parts.append("CLAIMS THAT WERE REJECTED by verification:")
        for claim_id in final_decision.rejected_claims:
            parts.append(f"  - {claim_id}")
        parts.append("")

    # Add disagreements from critique
    if critique_report and critique_report.disagreements:
        parts.append("KEY DISAGREEMENTS between specialists:")
        for d in critique_report.disagreements:
            parts.append(f"  - [{d.disagreement_severity.value}] {d.description}")
        parts.append("")

    # Add verification results
    if verification_report and verification_report.results:
        parts.append("VERIFICATION RESULTS:")
        for r in verification_report.results:
            parts.append(f"  - Claim {r.source_claim_id}: {r.status.value} — {r.summary}")
        parts.append("")

    # Add next actions as guidance
    if final_decision.next_actions:
        parts.append("SPECIFIC QUESTIONS TO ADDRESS:")
        for action in final_decision.next_actions:
            parts.append(f"  - {action}")
        parts.append("")

    # Add rationale
    parts.append(f"COUNCIL RATIONALE: {final_decision.rationale}")
    parts.append("")
    parts.append("Please provide a focused response that addresses these unresolved issues. "
                  "Provide your answer and an evidence packet as usual.")

    return "\n".join(parts)


async def _synthesize_with_uncertainty(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    final_decision: FinalDecision,
    critique_report: Optional[CritiqueReport] = None,
    verification_report: Optional[VerificationReport] = None
) -> Tuple[List, List, Dict, Dict]:
    """Synthesize a final answer with explicit uncertainty acknowledgment.

    Used when the second round cannot proceed further (max rounds reached
    or pipeline failure) to produce a synthesis that acknowledges what
    remains unresolved.

    Args:
        user_query: The original user question
        stage1_results: Available specialist results
        final_decision: The FinalDecision with unresolved claims
        critique_report: The previous CritiqueReport (may be None)
        verification_report: The previous VerificationReport (may be None)

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    logger.info("Synthesizing with uncertainty acknowledgment")

    # Use the original stage2 pipeline for a basic synthesis
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Build an uncertainty-aware synthesis prompt
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        critique_report=critique_report,
        final_decision=final_decision,
        verification_report=verification_report
    )

    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "critique_report": critique_report.model_dump() if critique_report else None,
        "judge_decision": None,
        "verification_report": verification_report.model_dump() if verification_report else None,
        "final_decision": final_decision.model_dump(),
        "second_round": True,
        "synthesized_with_uncertainty": True,
    }

    return stage1_results, stage2_results, stage3_result, metadata
