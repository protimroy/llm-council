"""Pydantic models for the Self-Testing Agentic LLM Council.

All structured data contracts for inter-stage communication.
Stage 1: EvidencePacket, Claim, Proposal
Stage 2: CritiqueReport, Agreement, Disagreement, etc.
Stage 2.5: FastJudgeDecision
Stage 1.5: VerificationTarget, VerificationResult, VerificationReport
Stage 3: FinalDecision
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────


class ClaimType(str, Enum):
    """Types of claims a specialist can make."""
    factual = "factual"
    causal = "causal"
    predictive = "predictive"
    recommendation = "recommendation"
    definition = "definition"
    comparative = "comparative"
    procedural = "procedural"
    architectural = "architectural"


class EvidenceType(str, Enum):
    """Types of evidence supporting a claim."""
    none = "none"
    reasoning = "reasoning"
    retrieval = "retrieval"
    tool = "tool"
    empirical = "empirical"
    theoretical = "theoretical"
    anecdotal = "anecdotal"
    authoritative = "authoritative"
    statistical = "statistical"
    logical = "logical"


class SeverityLevel(str, Enum):
    """Severity levels for disagreements, confidence, etc."""
    low = "low"
    medium = "medium"
    high = "high"


class RecommendedAction(str, Enum):
    """Recommended actions for disagreements."""
    synthesize_now = "synthesize_now"
    verify = "verify"
    ask_second_round = "ask_second_round"
    preserve_as_minority_view = "preserve_as_minority_view"


class TriageDecision(str, Enum):
    """Fast Judge triage decisions."""
    synthesize_now = "synthesize_now"
    escalate_for_verification = "escalate_for_verification"
    request_second_round = "request_second_round"


class VerificationStatus(str, Enum):
    """Status of a verification run."""
    passed = "passed"
    failed = "failed"
    error = "error"
    timeout = "timeout"
    skipped = "skipped"
    not_testable = "not_testable"


class VerificationTargetType(str, Enum):
    """Types of verification targets."""
    python_check = "python_check"
    consistency_check = "consistency_check"
    not_testable = "not_testable"


class PostVerificationAction(str, Enum):
    """Recommended next step after verification."""
    synthesize_now = "synthesize_now"
    request_second_round = "request_second_round"
    unresolved = "unresolved"


class FinalDecisionType(str, Enum):
    """Final decision types from the post-verification judge."""
    synthesize = "synthesize"
    second_round = "second_round"
    unresolved = "unresolved"


# ─── Stage 1: Evidence Packets ──────────────────────────────────────────────


class Claim(BaseModel):
    """A single structured claim from a specialist."""
    claim_id: str
    claim_text: str
    claim_type: ClaimType = ClaimType.factual
    evidence_type: EvidenceType = EvidenceType.none
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    assumptions: List[str] = Field(default_factory=list)
    falsifiable_hypothesis: str = ""
    test_logic: Optional[str] = None
    risk_if_wrong: str = "medium"


class Proposal(BaseModel):
    """A proposed action or hypothesis from a specialist."""
    proposal_id: str
    title: str
    hypothesis: str
    expected_benefit: str = ""
    expected_risk: str = ""
    suggested_test: str = ""


class EvidencePacket(BaseModel):
    """Structured output from a Stage 1 specialist."""
    model_name: str
    answer_text: str
    claims: List[Claim] = Field(default_factory=list)
    proposals: Optional[List[Proposal]] = None
    parse_error: Optional[str] = None


# ─── Stage 2: Critique Report ────────────────────────────────────────────────


class Agreement(BaseModel):
    """An agreement identified across specialists."""
    agreement_id: str
    shared_claim_summary: str
    supporting_claim_ids: List[str] = Field(default_factory=list)
    aggregate_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    shared_assumptions: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class Disagreement(BaseModel):
    """A disagreement identified across specialists."""
    disagreement_id: str
    claim_ids: List[str] = Field(default_factory=list)
    description: str = ""
    disagreement_severity: SeverityLevel = SeverityLevel.medium
    decision_impact: SeverityLevel = SeverityLevel.medium
    evidence_strength_summary: str = ""
    recommended_action: RecommendedAction = RecommendedAction.verify


class LoadBearingCandidate(BaseModel):
    """A disagreement that could change the final recommendation."""
    disagreement_id: str
    reason: str = ""
    would_change_recommendation: bool = False


class SelectedHypothesis(BaseModel):
    """A hypothesis selected for further consideration."""
    claim_id: str
    hypothesis: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_models: List[str] = Field(default_factory=list)


class MinorityAlert(BaseModel):
    """An outlier insight that might still be valuable."""
    alert_id: str
    claim_id: str = ""
    source_model: str = ""
    why_outlier: str = ""
    why_might_matter: str = ""
    preserve_in_synthesis: bool = False


class CritiqueReport(BaseModel):
    """Structured output from Stage 2 claim-level critique."""
    agreements: List[Agreement] = Field(default_factory=list)
    disagreements: List[Disagreement] = Field(default_factory=list)
    candidate_load_bearing_points: List[LoadBearingCandidate] = Field(default_factory=list)
    top_hypotheses: List[SelectedHypothesis] = Field(default_factory=list)
    minority_alerts: List[MinorityAlert] = Field(default_factory=list)
    critique_notes: Optional[str] = None
    diagnostic_notes: Optional[str] = None


# ─── Stage 2.5: Fast Judge ───────────────────────────────────────────────────


class FastJudgeDecision(BaseModel):
    """Triage decision from the Fast Judge."""
    decision: TriageDecision = TriageDecision.synthesize_now
    rationale: str = ""
    confidence: SeverityLevel = SeverityLevel.medium
    prioritized_issues: List[str] = Field(default_factory=list)
    selected_agreements: List[str] = Field(default_factory=list)
    selected_disagreements: List[str] = Field(default_factory=list)
    minority_alerts_to_preserve: List[str] = Field(default_factory=list)
    verification_targets: Optional[List[str]] = None
    second_round_targets: Optional[List[str]] = None
    diagnostic_notes: Optional[List[str]] = None


# ─── Stage 1.5: Verification ────────────────────────────────────────────────


class VerificationTarget(BaseModel):
    """A claim selected for verification."""
    target_id: str
    source_claim_id: str = ""
    source_model_name: str = ""
    target_type: VerificationTargetType = VerificationTargetType.python_check
    hypothesis: str = ""
    test_logic: Optional[str] = None
    expected_signal: str = ""
    risk_if_wrong: str = "medium"
    timeout_seconds: int = Field(default=5, ge=1, le=30)


class VerificationResult(BaseModel):
    """Result of verifying a single target."""
    target_id: str
    source_claim_id: str = ""
    status: VerificationStatus = VerificationStatus.not_testable
    summary: str = ""
    raw_logs: str = ""
    execution_time_ms: int = 0
    derived_evidence_strength: Optional[str] = None
    notes: Optional[str] = None


class VerificationReport(BaseModel):
    """Summary of all verification runs."""
    decision_source: str = ""
    targets_run: int = 0
    results: List[VerificationResult] = Field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    not_testable_count: int = 0
    summary: str = ""
    recommended_next_step: PostVerificationAction = PostVerificationAction.unresolved


# ─── Stage 3: Post-Verification Judge ────────────────────────────────────────


class FinalDecision(BaseModel):
    """Final reasoning decision after verification."""
    decision: FinalDecisionType = FinalDecisionType.synthesize
    rationale: str = ""
    confidence: SeverityLevel = SeverityLevel.medium
    resolved_claims: List[str] = Field(default_factory=list)
    rejected_claims: List[str] = Field(default_factory=list)
    unresolved_claims: List[str] = Field(default_factory=list)
    preserved_disagreements: List[str] = Field(default_factory=list)
    minority_alerts: List[str] = Field(default_factory=list)
    verification_summary: str = ""
    next_actions: List[str] = Field(default_factory=list)