"""Parsers for structured LLM output.

Extracts structured data from LLM responses that follow the delimiter pattern:
natural prose text
---DELIMITER---
JSON object

Each parser returns a tuple of (prose_text, parsed_object_or_None, error_or_None).
On any failure, a fallback object is returned with error information populated.
"""

import json
import logging
import re
from typing import Tuple, Optional

from .models import EvidencePacket, Claim, ClaimType, EvidenceType, CritiqueReport

logger = logging.getLogger(__name__)


def parse_evidence_packet(raw_text: str, model_name: str) -> Tuple[str, EvidencePacket]:
    """Parse a Stage 1 specialist response into prose text and an EvidencePacket.

    The model is expected to output:
        <natural language answer>
        ---EVIDENCE_PACKET---
        <JSON matching EvidencePacket schema>

    On any failure, returns a fallback EvidencePacket with parse_error populated
    and empty claims list. The answer_text is always the best available prose.

    Args:
        raw_text: The full raw response from the model.
        model_name: The model identifier (used as fallback model_name in the packet).

    Returns:
        Tuple of (answer_text, EvidencePacket). EvidencePacket is never None.
    """
    delimiter = "---EVIDENCE_PACKET---"

    if delimiter not in raw_text:
        # No delimiter found — entire response is prose
        logger.info(f"{model_name}: no evidence packet delimiter found, using fallback")
        return (
            raw_text,
            EvidencePacket(
                model_name=model_name,
                answer_text=raw_text,
                claims=[],
                parse_error="no delimiter found"
            )
        )

    parts = raw_text.split(delimiter, 1)
    answer_text = parts[0].strip()
    json_str = parts[1].strip()

    if not json_str:
        logger.warning(f"{model_name}: empty JSON block after delimiter")
        return (
            answer_text,
            EvidencePacket(
                model_name=model_name,
                answer_text=answer_text,
                claims=[],
                parse_error="empty JSON block after delimiter"
            )
        )

    # Try to parse JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"{model_name}: JSON parse error: {e}")
        return (
            answer_text,
            EvidencePacket(
                model_name=model_name,
                answer_text=answer_text,
                claims=[],
                parse_error=f"JSON parse error: {e}"
            )
        )

    # Try to validate with Pydantic
    try:
        # Ensure model_name is set correctly even if the model got it wrong
        if "model_name" not in data or not data["model_name"]:
            data["model_name"] = model_name

        # Normalize claim_type and evidence_type to valid enum values
        if "claims" in data:
            for claim_data in data["claims"]:
                claim_data["claim_type"] = _normalize_enum(claim_data.get("claim_type", "factual"), ClaimType, ClaimType.factual)
                claim_data["evidence_type"] = _normalize_enum(claim_data.get("evidence_type", "none"), EvidenceType, EvidenceType.none)

        packet = EvidencePacket.model_validate(data)
        logger.info(
            f"{model_name}: parsed evidence packet successfully — "
            f"{len(packet.claims)} claims, "
            f"{len(packet.proposals) if packet.proposals else 0} proposals"
        )
        return (answer_text, packet)

    except Exception as e:
        logger.warning(f"{model_name}: EvidencePacket validation error: {e}")
        return (
            answer_text,
            EvidencePacket(
                model_name=model_name,
                answer_text=answer_text,
                claims=[],
                parse_error=f"Validation error: {e}"
            )
        )


def parse_critique_report(raw_text: str) -> Tuple[str, Optional[CritiqueReport], Optional[str]]:
    """Parse a Stage 2 critique response into prose text and a CritiqueReport.

    The model is expected to output:
        <natural language analysis>
        ---CRITIQUE_REPORT---
        <JSON matching CritiqueReport schema>

    On failure, returns (raw_text, None, error_message).

    Args:
        raw_text: The full raw response from the model.

    Returns:
        Tuple of (critique_prose, CritiqueReport or None, error or None).
    """
    delimiter = "---CRITIQUE_REPORT---"

    if delimiter not in raw_text:
        logger.info("No critique report delimiter found")
        return (raw_text, None, "no delimiter found")

    parts = raw_text.split(delimiter, 1)
    critique_prose = parts[0].strip()
    json_str = parts[1].strip()

    if not json_str:
        logger.warning("Empty JSON block after critique report delimiter")
        return (critique_prose, None, "empty JSON block after delimiter")

    # Try to parse JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error in critique report: {e}")
        return (critique_prose, None, f"JSON parse error: {e}")

    # Try to validate with Pydantic
    try:
        # Normalize enum values in disagreements
        from .models import SeverityLevel, RecommendedAction

        if "disagreements" in data:
            for d in data["disagreements"]:
                d["disagreement_severity"] = _normalize_enum(
                    d.get("disagreement_severity", "medium"), SeverityLevel, SeverityLevel.medium
                )
                d["decision_impact"] = _normalize_enum(
                    d.get("decision_impact", "medium"), SeverityLevel, SeverityLevel.medium
                )
                d["recommended_action"] = _normalize_enum(
                    d.get("recommended_action", "verify"), RecommendedAction, RecommendedAction.verify
                )

        report = CritiqueReport.model_validate(data)
        logger.info(
            f"Parsed critique report: "
            f"{len(report.agreements)} agreements, "
            f"{len(report.disagreements)} disagreements, "
            f"{len(report.candidate_load_bearing_points)} load-bearing, "
            f"{len(report.minority_alerts)} minority alerts"
        )
        return (critique_prose, report, None)

    except Exception as e:
        logger.warning(f"CritiqueReport validation error: {e}")
        return (critique_prose, None, f"Validation error: {e}")


def _normalize_enum(value: str, enum_class, default) -> str:
    """Normalize a string value to a valid enum member value.

    If the value is a valid member of the enum, return it.
    Otherwise, return the default.
    """
    valid_values = [e.value for e in enum_class]
    if isinstance(value, str) and value in valid_values:
        return value
    return default.value