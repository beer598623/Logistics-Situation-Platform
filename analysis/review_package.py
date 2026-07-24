"""Human-triggered ChatGPT review package: build, and validate what comes back.

No AI API is called anywhere in this repository. The workflow is:

1. ``scripts/build_review_package.py`` writes a bounded input package.
2. A human opens it, runs it through ChatGPT out-of-band, and saves the
   structured reply into ``data/review/inbound/``.
3. ``scripts/import_review.py`` validates the reply against
   ``schemas/review_package_output.schema.json`` **and** against the
   rejection rules in this module.
4. ``scripts/review_decision.py`` records an explicit human approval or
   rejection and archives the assessment it supersedes.

The rejection rules are deliberately mechanical. They cannot catch every bad
assessment, and they are not meant to: they catch the specific failure modes
the Work Order names, so that a reviewer's attention goes to the judgement
calls instead of to the checklist.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .assessments import validate_preparedness_option, validate_scenario_outlook

#: Phrasing that asserts a real-time operational condition. Permitted only
#: when the input package actually contained operational-condition evidence.
_REALTIME_CONGESTION_PHRASES = (
    "real-time congestion",
    "real time congestion",
    "currently congested",
    "is congested",
    "berth delay",
    "berth delays",
    "yard congestion",
    "truck delay",
    "truck delays",
    "vessel queue",
    "waiting time is",
)

#: Phrasing that presents a benchmark or proxy as an actual shipment price.
_QUOTATION_PHRASES = (
    "average thailand freight rate",
    "thailand freight rate is",
    "quoted rate",
    "quotation for",
    "actual freight rate",
    "the rate to ship from thailand",
    "spot rate from thailand",
)

#: Causal connectives. A statement using one of these with no evidence
#: reference is asserting causation the package cannot support.
_CAUSAL_PHRASES = (
    "caused by",
    "because of",
    "due to",
    "led to",
    "resulted in",
    "as a result of",
    "driven by",
    "triggered by",
)

_QUANTITY = re.compile(r"\d")

#: Evidence claim types that can support an operational-condition statement.
_OPERATIONAL_CLAIM_TYPES = frozenset({"official_notice", "verified_fact"})

#: The sections every returned assessment must contain, echoed into the
#: package so the human's prompt and the validator cannot drift apart.
REQUIRED_OUTPUT_SECTIONS = (
    "current_situation",
    "key_changes",
    "lane_assessments",
    "verified_facts",
    "reported_claims",
    "analytical_inference",
    "conflicting_evidence",
    "transmission_chains",
    "observed_impacts",
    "potential_impacts",
    "scenarios",
    "evidence_references",
    "data_gaps",
    "conditional_preparedness_options",
)

PROHIBITED_OUTPUTS = (
    "Do not reference any evidence ID that is not present in this package.",
    "Do not state a material impact without a complete transmission mechanism.",
    "Do not treat a missing, suppressed or unpublished value as zero.",
    "Do not present a market benchmark or route proxy as a Thailand shipment quotation.",
    "Do not claim real-time port congestion without operational evidence in this package.",
    "Do not assert causation from timing overlap or correlation alone.",
    "Do not issue mandatory instructions to any specific organization.",
    "Do not present a numeric point forecast for freight, transit time, inventory or cost.",
)

EXCLUSIONS_APPLIED = (
    "Secrets and credentials: none exist in this repository and none are exported.",
    "Private company information: the public core holds none; the Private Decision "
    "Overlay is out of scope for WO-010.",
    "Raw licensed content: only bounded claims and source links are exported, never a "
    "full article or a stored raw response.",
    "Unbounded news text: evidence claims are capped at 600 characters by "
    "schemas/event_evidence.schema.json.",
    "Unsupported claims: only records that pass scripts/validate.py are exported.",
)


def _text_fields(output: Mapping[str, Any]) -> list[tuple[str, str, list[str]]]:
    """Collect every free-text assertion with its location and evidence IDs."""
    collected: list[tuple[str, str, list[str]]] = [
        ("current_situation", str(output.get("current_situation", "")), [])
    ]
    for index, change in enumerate(output.get("key_changes", [])):
        collected.append((f"key_changes[{index}]", str(change), []))
    for group in ("verified_facts", "reported_claims", "analytical_inference"):
        for index, item in enumerate(output.get(group, [])):
            collected.append(
                (f"{group}[{index}]", str(item.get("statement", "")), list(item.get("evidence_ids", [])))
            )
    for group in ("observed_impacts", "potential_impacts"):
        for index, item in enumerate(output.get(group, [])):
            collected.append(
                (
                    f"{group}[{index}]",
                    str(item.get("description", "")),
                    list(item.get("evidence_ids", [])),
                )
            )
    for index, assessment in enumerate(output.get("lane_assessments", [])):
        collected.append(
            (
                f"lane_assessments[{index}]",
                str(assessment.get("summary", "")),
                list(assessment.get("evidence_ids", [])),
            )
        )
    return collected


def build_input_package(
    *,
    package_id: str,
    generated_at: str,
    data_cutoff_at: str,
    source_health: Mapping[str, Any],
    key_indicators: Sequence[Mapping[str, Any]],
    lane_status: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    previous_assessments: Sequence[Mapping[str, Any]],
    data_gaps: Sequence[str],
) -> dict[str, Any]:
    """Assemble the bounded input package.

    Events are split into operational events and external drivers here rather
    than by the reader, so the distinction survives the hand-off. Discovery
    leads are carried inside ``external_drivers`` with their class intact and
    are never promoted.
    """
    operational = [event for event in events if event["event_class"] == "direct_operational_event"]
    drivers = [event for event in events if event["event_class"] != "direct_operational_event"]

    conflicts = [
        {"event_id": event["event_id"], **conflict}
        for event in events
        for conflict in event.get("conflicting_evidence", [])
    ]

    package = {
        "package_id": package_id,
        "methodology_version": "0.8",
        "generated_at": generated_at,
        "data_cutoff_at": data_cutoff_at,
        "source_health_summary": {
            "overall_status": source_health.get("overall_status", "insufficient"),
            "coverage_message": source_health.get("coverage_message", ""),
            "sources": list(source_health.get("sources", [])),
            "capabilities": list(source_health.get("capabilities", [])),
        },
        "key_indicators": [dict(item) for item in key_indicators],
        "lane_status": [dict(item) for item in lane_status],
        "active_operational_events": [dict(event) for event in operational],
        "external_drivers": [dict(event) for event in drivers],
        "evidence_records": [dict(item) for item in evidence],
        "conflicting_evidence": conflicts,
        "previous_assessments": [dict(item) for item in previous_assessments],
        "data_gaps": list(data_gaps),
        "output_instructions": {
            "required_sections": list(REQUIRED_OUTPUT_SECTIONS),
            "prohibited_outputs": list(PROHIBITED_OUTPUTS),
            "output_schema_path": "schemas/review_package_output.schema.json",
        },
        "exclusions_applied": list(EXCLUSIONS_APPLIED),
        "package_sha256": None,
    }
    package["package_sha256"] = hashlib.sha256(
        json.dumps(package, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return package


def unavailable_series_ids(package: Mapping[str, Any]) -> set[str]:
    """Series in the package that currently have no usable value.

    Used to catch an assessment that quietly fills a gap with a number.
    """
    unavailable: set[str] = set()
    for indicator in package.get("key_indicators", []):
        if indicator.get("current_value") is None:
            series_id = indicator.get("series_id") or indicator.get("indicator_id")
            if series_id:
                unavailable.add(str(series_id))
    return unavailable


def has_operational_condition_evidence(package: Mapping[str, Any]) -> bool:
    """True when the package contains evidence that can support a claim about
    an operational condition such as congestion or delay."""
    return any(
        item.get("claim_type") in _OPERATIONAL_CLAIM_TYPES
        and item.get("evidence_role") == "confirming"
        and item.get("scope_supported") in {"facility", "node", "route", "lane"}
        for item in package.get("evidence_records", [])
    )


def validate_output(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
) -> list[str]:
    """Apply the Gate I rejection rules to a returned assessment.

    Returns a list of reasons the assessment must be rejected. An empty list
    means the mechanical checks passed -- it does not mean the assessment is
    approved. Approval is a separate, explicitly recorded human act.
    """
    problems: list[str] = []

    if output.get("package_id") != package.get("package_id"):
        problems.append(
            f"output package_id {output.get('package_id')!r} does not match the input "
            f"package {package.get('package_id')!r}"
        )

    known_evidence = {
        str(item.get("evidence_id")) for item in package.get("evidence_records", [])
    }
    referenced = set(output.get("evidence_references", []))
    unknown = referenced - known_evidence
    if unknown:
        problems.append(f"references unknown evidence IDs {sorted(unknown)}")

    for location, text, evidence_ids in _text_fields(output):
        unknown_local = set(evidence_ids) - known_evidence
        if unknown_local:
            problems.append(f"{location}: references unknown evidence IDs {sorted(unknown_local)}")
        undeclared = set(evidence_ids) - referenced
        if undeclared:
            problems.append(
                f"{location}: cites evidence {sorted(undeclared)} that is not declared in "
                "evidence_references"
            )

    missing_series = unavailable_series_ids(package)
    operational_evidence = has_operational_condition_evidence(package)

    for location, text, evidence_ids in _text_fields(output):
        lowered = text.lower()

        for series_id in missing_series:
            if series_id.lower() in lowered and _QUANTITY.search(text):
                problems.append(
                    f"{location}: states a numeric value for {series_id!r}, which has no "
                    "available observation in this package; missing data must not be "
                    "presented as a value"
                )

        for phrase in _QUOTATION_PHRASES:
            if phrase in lowered:
                problems.append(
                    f"{location}: presents a market benchmark or proxy as a shipment "
                    f"quotation ({phrase!r})"
                )

        if not operational_evidence:
            for phrase in _REALTIME_CONGESTION_PHRASES:
                if phrase in lowered:
                    problems.append(
                        f"{location}: claims a real-time operational condition "
                        f"({phrase!r}) but the package contains no operational-condition "
                        "evidence"
                    )

        if not evidence_ids:
            for phrase in _CAUSAL_PHRASES:
                if phrase in lowered:
                    problems.append(
                        f"{location}: asserts causation ({phrase!r}) with no evidence "
                        "reference"
                    )

    for group in ("observed_impacts", "potential_impacts"):
        for index, impact in enumerate(output.get(group, [])):
            if impact.get("severity") != "none" and not impact.get("transmission_mechanism"):
                problems.append(
                    f"{group}[{index}] ({impact.get('area')}): material impact has no "
                    "transmission mechanism"
                )
            if impact.get("status") == "no_material":
                problems.append(
                    f"{group}[{index}] ({impact.get('area')}): 'no_material' is a platform "
                    "assessment status recorded against negative operational evidence and "
                    "is not accepted from a returned AI assessment"
                )

    for index, chain in enumerate(output.get("transmission_chains", [])):
        missing_links = [
            link
            for link in (
                "operational_change",
                "logistics_mechanism",
                "observable_indicator",
                "outcome",
            )
            if not chain.get(link)
        ]
        if missing_links:
            problems.append(
                f"transmission_chains[{index}] ({chain.get('subject')}): incomplete chain, "
                f"missing {', '.join(missing_links)}"
            )

    for outlook in output.get("scenarios", []):
        problems.extend(validate_scenario_outlook(outlook))

    for option in output.get("conditional_preparedness_options", []):
        problems.extend(validate_preparedness_option(option))

    return problems


def requires_human_review(output: Mapping[str, Any]) -> bool:
    """High or Critical conclusions always require an explicit human record."""
    return output.get("highest_severity_claimed") in {"high", "critical"}
