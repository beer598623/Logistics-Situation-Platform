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

WO-010-R3 adds two things to that list. First, the output is now
cryptographically bound to the exact input package it was produced from
(:func:`binding_problems`): the returned assessment must echo the package's
own hash, dataset, purpose and both cutoffs, and any mismatch is rejected
before anything else is read. Second, a claim can now be supported either by
evidence or by a qualified current indicator, and the two are validated
against one combined eligible-support set (:func:`eligible_support_ids`)
rather than evidence alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .assessments import validate_preparedness_option, validate_scenario_outlook
from .provenance import (
    CURRENT_PUBLICATION,
    PUBLISH_BOUNDED_CLAIM,
    is_fixture,
    provenance_summary,
    qualifies_for_current_publication,
    record_dataset,
    record_origin,
)

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

#: Impact areas that describe a physical operating condition. A trend in a
#: numeric indicator is context, not a sighting; establishing that congestion,
#: a service disruption or another operational impact actually occurred
#: requires at least one evidence_id, never indicator_ids alone.
_OPERATIONAL_CONDITION_AREAS = frozenset({"capacity", "service", "transport", "logistics"})

#: Severities that may never rest on evidence weaker than A/B grade. Mirrors
#: the same rule the platform applies to its own events in
#: ``analysis.events.validate_event``.
_HUMAN_REVIEW_SEVERITIES = frozenset({"high", "critical"})
_PRIMARY_GRADE_EVIDENCE = frozenset({"A", "B"})

#: Coverage-gap phrasing expected in ``current_situation`` whenever the
#: package holds no eligible support at all. One signal among several -- the
#: structural checks below (every lane insufficient, every claim group empty)
#: do the actual enforcing; this only catches prose that contradicts them.
_COVERAGE_GAP_PHRASES = (
    "insufficient",
    "no qualified",
    "no current",
    "coverage gap",
    "no eligible",
)

#: The links of a transmission chain. A chain with any of these populated is
#: making a claim and must cite the support behind it.
_CHAIN_LINKS = (
    "external_driver",
    "operational_change",
    "logistics_mechanism",
    "observable_indicator",
    "outcome",
)

#: What a package is for. A package built to demonstrate the engine can never
#: be approved into the current Dashboard, and the purpose is what says so.
CURRENT_INTELLIGENCE = "current_intelligence_assessment"
ENGINE_DEMONSTRATION = "engine_demonstration"

PACKAGE_PURPOSES = (CURRENT_INTELLIGENCE, ENGINE_DEMONSTRATION)

#: Which purpose each dataset may carry. A current-publication package is for
#: current intelligence and nothing else; a demo or historical package is a
#: demonstration whatever it is labelled.
PURPOSE_BY_DATASET = {
    CURRENT_PUBLICATION: CURRENT_INTELLIGENCE,
    "technical_demo": ENGINE_DEMONSTRATION,
    "historical_validation": ENGINE_DEMONSTRATION,
}

#: The output fields that bind an assessment to its exact input package, and
#: the package field each must equal. Checked as a fixed list, not field by
#: field ad hoc, so a sixth binding field added later cannot be forgotten in
#: one of the two places that used to check these by hand.
BINDING_FIELDS: tuple[tuple[str, str], ...] = (
    ("input_package_sha256", "package_sha256"),
    ("input_dataset", "dataset"),
    ("input_package_purpose", "package_purpose"),
    ("input_data_cutoff_at", "data_cutoff_at"),
    ("input_source_cutoff", "source_cutoff"),
)

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
    "Do not reference any indicator series_id that is not present in this package's "
    "key_indicators.",
    "Do not state a material impact without a complete transmission mechanism.",
    "Do not treat a missing, suppressed or unpublished value as zero.",
    "Do not present a market benchmark or route proxy as a Thailand shipment quotation.",
    "Do not claim real-time port congestion without operational evidence in this package.",
    "Do not assert causation from timing overlap or correlation alone.",
    "Do not issue mandatory instructions to any specific organization.",
    "Do not present a numeric point forecast for freight, transit time, inventory or cost.",
    "Do not use a numeric indicator alone to establish congestion, a service disruption or "
    "any other operational-condition impact (areas: capacity, service, transport, "
    "logistics) -- those require at least one evidence_id.",
    "Do not present a global or route-proxy indicator as a Thailand-specific verified fact "
    "or observed impact.",
    "Do not claim high or critical severity on evidence weaker than A/B grade.",
)

#: Copied into every package so the human operator and ChatGPT both see, in
#: one place, exactly which five values the output must echo back verbatim.
#: The WO-010-R3 correction: previously the output carried no binding field at
#: all, so an assessment produced from a stale or substituted package was
#: indistinguishable from one produced from the package actually being
#: approved.
REQUIRED_OUTPUT_BINDING_INSTRUCTIONS = (
    "Copy these five values into the corresponding output fields exactly as given, with no "
    "reformatting: input_package_sha256, input_dataset, input_package_purpose, "
    "input_data_cutoff_at, input_source_cutoff. These identify which package this output was "
    "produced from and are checked before anything else in the output is read. "
    "produced_at is a separate field you fill in yourself with when you wrote the output -- "
    "it is not one of these five and must not be used in place of any of them."
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


def _text_fields(output: Mapping[str, Any]) -> list[tuple[str, str, list[str], list[str]]]:
    """Collect every free-text assertion with its location, evidence IDs and
    indicator IDs."""
    collected: list[tuple[str, str, list[str], list[str]]] = [
        ("current_situation", str(output.get("current_situation", "")), [], [])
    ]
    for index, change in enumerate(output.get("key_changes", [])):
        collected.append((f"key_changes[{index}]", str(change), [], []))
    for group in ("verified_facts", "reported_claims", "analytical_inference"):
        for index, item in enumerate(output.get(group, [])):
            collected.append(
                (
                    f"{group}[{index}]",
                    str(item.get("statement", "")),
                    list(item.get("evidence_ids", [])),
                    list(item.get("indicator_ids", [])),
                )
            )
    for group in ("observed_impacts", "potential_impacts"):
        for index, item in enumerate(output.get(group, [])):
            collected.append(
                (
                    f"{group}[{index}]",
                    str(item.get("description", "")),
                    list(item.get("evidence_ids", [])),
                    list(item.get("indicator_ids", [])),
                )
            )
    for index, assessment in enumerate(output.get("lane_assessments", [])):
        collected.append(
            (
                f"lane_assessments[{index}]",
                str(assessment.get("summary", "")),
                list(assessment.get("evidence_ids", [])),
                list(assessment.get("indicator_ids", [])),
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
    dataset: str = CURRENT_PUBLICATION,
    source_cutoff: str | None = None,
    excluded_fixture_record_count: int = 0,
) -> dict[str, Any]:
    """Assemble the bounded input package.

    Events are split into operational events and external drivers here rather
    than by the reader, so the distinction survives the hand-off. Discovery
    leads are carried inside ``external_drivers`` with their class intact and
    are never promoted.

    The package records which surface it was built from, what it is for, and
    how many fixture records the filter dropped. Those three facts are what
    let the approval gate refuse a demonstration package without having to
    re-derive where its contents came from. ``required_output_binding``
    restates the same five values the output must echo, so the instruction
    and the ground truth cannot drift apart.
    """
    operational = [event for event in events if event["event_class"] == "direct_operational_event"]
    drivers = [event for event in events if event["event_class"] != "direct_operational_event"]

    conflicts = [
        {"event_id": event["event_id"], **conflict}
        for event in events
        for conflict in event.get("conflicting_evidence", [])
    ]

    resolved_source_cutoff = source_cutoff or data_cutoff_at
    package = {
        "package_id": package_id,
        "methodology_version": "0.8",
        "dataset": dataset,
        "package_purpose": PURPOSE_BY_DATASET.get(dataset, ENGINE_DEMONSTRATION),
        "generated_at": generated_at,
        "data_cutoff_at": data_cutoff_at,
        "source_cutoff": resolved_source_cutoff,
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
        "provenance_summary": {
            "evidence": provenance_summary(list(evidence)),
            "events": provenance_summary(list(events)),
            "excluded_fixture_record_count": excluded_fixture_record_count,
        },
        "output_instructions": {
            "required_sections": list(REQUIRED_OUTPUT_SECTIONS),
            "prohibited_outputs": list(PROHIBITED_OUTPUTS),
            "output_schema_path": "schemas/review_package_output.schema.json",
            "required_output_binding_instructions": REQUIRED_OUTPUT_BINDING_INSTRUCTIONS,
        },
        # Restated as literal values (not just instructions) so whoever pastes
        # this package can copy them directly rather than hunting for the
        # fields above -- and so a script diffing the two packages has a
        # single well-known location to read.
        "required_output_binding": {
            "input_package_sha256": None,
            "input_dataset": dataset,
            "input_package_purpose": PURPOSE_BY_DATASET.get(dataset, ENGINE_DEMONSTRATION),
            "input_data_cutoff_at": data_cutoff_at,
            "input_source_cutoff": resolved_source_cutoff,
        },
        "exclusions_applied": list(EXCLUSIONS_APPLIED),
        "package_sha256": None,
    }
    package["package_sha256"] = hashlib.sha256(
        json.dumps(package, sort_keys=True).encode("utf-8")
    ).hexdigest()
    package["required_output_binding"]["input_package_sha256"] = package["package_sha256"]
    return package


def package_hash(package: Mapping[str, Any]) -> str:
    """Recompute a package's own hash the way :func:`build_input_package` did.

    The stored ``package_sha256`` is over the package with that field (and
    the nested ``required_output_binding.input_package_sha256`` echo of it)
    null, so re-deriving it here detects a package edited after it was
    generated -- an approval bound to a package that no longer exists on disk
    is not an approval of anything.
    """
    restated = {
        **package,
        "package_sha256": None,
        "required_output_binding": {
            **(package.get("required_output_binding") or {}),
            "input_package_sha256": None,
        },
    }
    return hashlib.sha256(json.dumps(restated, sort_keys=True).encode("utf-8")).hexdigest()


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


def has_operational_condition_evidence(
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> bool:
    """True when the package holds evidence that can support an operational
    condition claim such as congestion or delay.

    WO-010-R2: an official-looking ``claim_type`` is not enough. In a current
    package the item must itself be eligible for current publication --
    otherwise a historical fixture that happens to be classed
    ``official_notice`` silently licenses a congestion claim about today.
    """
    current = package.get("dataset") == CURRENT_PUBLICATION
    for item in package.get("evidence_records", []):
        if item.get("claim_type") not in _OPERATIONAL_CLAIM_TYPES:
            continue
        if item.get("evidence_role") != "confirming":
            continue
        if item.get("scope_supported") not in {"facility", "node", "route", "lane"}:
            continue
        if current and not qualifies_for_current_publication(
            item, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        ):
            continue
        return True
    return False


def package_provenance_problems(
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Provenance checks on the package itself, before its output is read.

    Validators used to inspect only whether an evidence ID existed. An ID that
    exists is not an ID that may be cited as current fact, and that gap is how
    a demonstration package could be walked through the approval gate.

    Also checks the package's own integrity: a package edited on disk after
    its ``package_sha256`` was computed no longer matches that hash, and an
    approval bound to it would be bound to nothing. Checking this here, not
    only at approval time, means a plain review also catches a tampered
    package rather than waiting until someone tries to approve it.
    """
    problems: list[str] = []
    dataset = package.get("dataset")
    purpose = package.get("package_purpose")

    recomputed = package_hash(package)
    if package.get("package_sha256") != recomputed:
        problems.append(
            "the input package has changed since it was generated: its recorded "
            f"package_sha256 {package.get('package_sha256')!r} does not match the hash of "
            f"its current contents {recomputed!r}"
        )

    if dataset not in PURPOSE_BY_DATASET:
        problems.append(f"package dataset {dataset!r} is not a recognised publication surface")
        return problems
    if purpose != PURPOSE_BY_DATASET[dataset]:
        problems.append(
            f"package dataset {dataset!r} and package_purpose {purpose!r} disagree; a "
            f"{dataset} package is a {PURPOSE_BY_DATASET[dataset]}"
        )

    if dataset != CURRENT_PUBLICATION:
        return problems

    for item in package.get("evidence_records", []):
        evidence_id = item.get("evidence_id")
        if is_fixture(record_origin(item)):
            problems.append(
                f"evidence {evidence_id!r}: a {record_origin(item)} record is present in a "
                "current-intelligence package"
            )
            continue
        if record_dataset(item) != CURRENT_PUBLICATION:
            problems.append(
                f"evidence {evidence_id!r}: belongs to the {record_dataset(item)!r} dataset "
                "and cannot support a current assessment"
            )
            continue
        if item.get("retrieval_status") == "not_retrieved" and record_origin(item) != (
            "human_reviewed_manual"
        ):
            problems.append(
                f"evidence {evidence_id!r}: retrieval_status is 'not_retrieved' with no human "
                "review behind it, so it cannot be used as a verified current fact"
            )
            continue
        decision = qualifies_for_current_publication(
            item, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
        if not decision:
            problems.append(f"evidence {evidence_id!r}: {decision.reason}")

    for group in ("active_operational_events", "external_drivers"):
        for event in package.get(group, []):
            if record_dataset(event) not in {None, CURRENT_PUBLICATION}:
                problems.append(
                    f"{group}: event {event.get('event_id')!r} belongs to the "
                    f"{record_dataset(event)!r} dataset"
                )

    for indicator in package.get("key_indicators", []):
        if is_fixture(indicator.get("evidence_origin")):
            problems.append(
                f"key_indicators: series {indicator.get('series_id')!r} is a "
                f"{indicator.get('evidence_origin')} and cannot appear in a current package"
            )
        elif indicator.get("dataset") not in {None, CURRENT_PUBLICATION}:
            problems.append(
                f"key_indicators: series {indicator.get('series_id')!r} belongs to the "
                f"{indicator.get('dataset')!r} dataset"
            )

    return problems


def citable_evidence_ids(
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> set[str]:
    """Evidence IDs present in the package that may actually be cited.

    In a current package, "present" and "citable" are different sets. An
    assessment may only cite evidence that could itself carry a current
    claim; anything else is excluded from the citable set even if it somehow
    reached the ``evidence_records`` list.
    """
    is_current = package.get("dataset") == CURRENT_PUBLICATION
    return {
        str(item.get("evidence_id"))
        for item in package.get("evidence_records", [])
        if not is_current
        or qualifies_for_current_publication(
            item, registry=registry, publication_use=PUBLISH_BOUNDED_CLAIM
        )
    }


def eligible_indicator_ids(
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> set[str]:
    """Indicator ``series_id`` values present in the package that may be cited.

    A current package's ``key_indicators`` are already the output of
    ``build_current_indicators`` -- qualified, current-publication records
    only -- so this is primarily a defensive re-check: an indicator that is a
    fixture, or that claims a non-current dataset despite sitting in a
    current package, is excluded rather than trusted on sight.
    """
    is_current = package.get("dataset") == CURRENT_PUBLICATION
    eligible: set[str] = set()
    for indicator in package.get("key_indicators", []):
        series_id = indicator.get("series_id") or indicator.get("indicator_id")
        if not series_id:
            continue
        if is_current:
            if is_fixture(indicator.get("evidence_origin")):
                continue
            if indicator.get("dataset") not in {None, CURRENT_PUBLICATION}:
                continue
        eligible.add(str(series_id))
    return eligible


def eligible_support_ids(
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> set[str]:
    """The combined set an assessment may draw on: citable evidence plus
    eligible indicators.

    A current assessment may be supported by either kind of record. This is
    the one set every support-adequacy check below is validated against, so
    "may this claim cite that ID" always has one answer rather than two that
    could disagree.
    """
    return citable_evidence_ids(package, registry=registry) | eligible_indicator_ids(
        package, registry=registry
    )


def _global_or_proxy_indicator_ids(package: Mapping[str, Any]) -> set[str]:
    """Indicators the package itself marks as global or route-proxy scoped.

    Read from the indicator's own ``geographic_scope`` field
    (``analysis``/``scripts.build_analysis.build_current_indicators`` and
    ``scripts.build_dashboard`` both set it), never inferred from the series
    name here -- the platform records the scope once, at the point it knows
    which source produced the record, and every reader of the package trusts
    that recorded value rather than re-guessing it.
    """
    return {
        str(indicator.get("series_id"))
        for indicator in package.get("key_indicators", [])
        if indicator.get("geographic_scope") == "global_or_proxy"
    }


def binding_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
) -> list[str]:
    """Whether the output is bound to exactly this package.

    Every one of :data:`BINDING_FIELDS` must be present on the output and
    equal to the package's own value. This is checked unconditionally, field
    by field, rather than only when a field happens to be present: a missing
    binding field is exactly as disqualifying as a mismatched one, and an
    output produced against a different package must never be readable as
    current simply because most of its fields happen to still line up.
    """
    problems: list[str] = []
    for output_field, package_field in BINDING_FIELDS:
        output_value = output.get(output_field)
        package_value = package.get(package_field)
        if not output_value:
            problems.append(f"output is missing required binding field {output_field!r}")
            continue
        if output_value != package_value:
            problems.append(
                f"output's {output_field} ({output_value!r}) does not match the input "
                f"package's {package_field} ({package_value!r})"
            )
    return problems


def zero_evidence_disposition_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Enforce the coverage-only shape whenever the package has nothing to
    cite from.

    When neither eligible evidence nor an eligible indicator exists, the
    output must be structurally incapable of stating a direction: every claim
    group is empty, every lane reads ``insufficient_evidence`` with no
    support references, no scenario differentiates its three cases, and any
    preparedness option is a labelled data-coverage action rather than an
    operational one. These are structural checks against the output's own
    fields, not a scan for forbidden words -- a single, narrow prose check on
    ``current_situation`` is the only place free text is read, and it is one
    signal among the rest, never the only one.
    """
    if package.get("dataset") != CURRENT_PUBLICATION:
        return []
    if eligible_support_ids(package, registry=registry):
        return []

    problems: list[str] = []

    if output.get("highest_severity_claimed") not in {None, "none"}:
        problems.append(
            "the package holds no eligible evidence or indicator, but "
            f"highest_severity_claimed is {output.get('highest_severity_claimed')!r}, not "
            "'none'"
        )

    situation = str(output.get("current_situation", "")).lower()
    if not any(phrase in situation for phrase in _COVERAGE_GAP_PHRASES):
        problems.append(
            "the package holds no eligible evidence or indicator, but current_situation "
            "does not state an insufficient-coverage position"
        )

    for index, lane in enumerate(output.get("lane_assessments", [])):
        if lane.get("direction") != "insufficient_evidence":
            problems.append(
                f"lane_assessments[{index}] ({lane.get('lane_id')}): direction "
                f"{lane.get('direction')!r} is asserted with zero eligible evidence or "
                "indicators in the package"
            )
        if lane.get("evidence_ids") or lane.get("indicator_ids"):
            problems.append(
                f"lane_assessments[{index}] ({lane.get('lane_id')}): cites support "
                "references despite the package holding none eligible"
            )

    for group in (
        "verified_facts",
        "reported_claims",
        "analytical_inference",
        "conflicting_evidence",
        "transmission_chains",
        "observed_impacts",
        "potential_impacts",
    ):
        if output.get(group):
            problems.append(
                f"{group} is non-empty, but the package holds no eligible evidence or "
                "indicator to support any entry in it"
            )

    case_names = ("base_case", "deterioration_case", "improvement_case")
    for index, outlook in enumerate(output.get("scenarios", [])):
        cases = [outlook.get(name) for name in case_names]
        if any(case is None for case in cases):
            continue
        narratives = {case.get("narrative") for case in cases}
        if len(narratives) != 1:
            problems.append(
                f"scenarios[{index}] ({outlook.get('outlook_id')}): base, deterioration and "
                "improvement cases differ, which asserts a direction the package holds no "
                "evidence or indicator for"
            )
        for name, case in zip(case_names, cases, strict=True):
            if case.get("evidence_ids") or case.get("indicator_ids"):
                problems.append(
                    f"scenarios[{index}]/{name}: cites support references despite the "
                    "package holding none eligible"
                )

    for index, option in enumerate(output.get("conditional_preparedness_options", [])):
        if option.get("option_type") != "monitor" or not option.get("is_data_coverage_action"):
            problems.append(
                f"conditional_preparedness_options[{index}]: with zero eligible evidence or "
                "indicators, only a 'monitor' option explicitly marked "
                "is_data_coverage_action is permitted"
            )

    return problems


def support_adequacy_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Checks that apply whenever the package *does* hold eligible support.

    Complementary to :func:`zero_evidence_disposition_problems`: these do not
    require zero coverage to fire, and instead check that whatever support
    exists is used honestly -- a direction needs some citation, an
    operational-condition impact needs evidence rather than an indicator
    trend, a global or proxy indicator cannot be laundered into a
    Thailand-specific verified fact, severity cannot outrun evidence
    strength, and a populated transmission-chain link needs support behind
    it.
    """
    problems: list[str] = []
    global_or_proxy = _global_or_proxy_indicator_ids(package)
    discovery_only_ids = {
        str(item.get("evidence_id"))
        for item in package.get("evidence_records", [])
        if item.get("evidence_role") == "discovery_only"
    }

    for index, lane in enumerate(output.get("lane_assessments", [])):
        direction = lane.get("direction")
        if direction != "insufficient_evidence" and not (
            lane.get("evidence_ids") or lane.get("indicator_ids")
        ):
            problems.append(
                f"lane_assessments[{index}] ({lane.get('lane_id')}): direction {direction!r} "
                "cites no evidence_id or indicator_id to support it"
            )
        cited_discovery = set(lane.get("evidence_ids", [])) & discovery_only_ids
        if direction != "insufficient_evidence" and cited_discovery:
            problems.append(
                f"lane_assessments[{index}] ({lane.get('lane_id')}): direction {direction!r} "
                f"rests on discovery-only evidence {sorted(cited_discovery)}, which cannot "
                "support a material current conclusion"
            )

    for group in ("verified_facts", "observed_impacts"):
        for index, item in enumerate(output.get(group, [])):
            cited_discovery = set(item.get("evidence_ids", [])) & discovery_only_ids
            if cited_discovery:
                problems.append(
                    f"{group}[{index}]: rests on discovery-only evidence "
                    f"{sorted(cited_discovery)}, which cannot support a material current "
                    "conclusion"
                )

    for group in ("verified_facts", "observed_impacts"):
        for index, item in enumerate(output.get(group, [])):
            cited_proxy = set(item.get("indicator_ids", [])) & global_or_proxy
            if cited_proxy:
                problems.append(
                    f"{group}[{index}]: cites global or route-proxy indicator(s) "
                    f"{sorted(cited_proxy)} as a Thailand-specific {group.rstrip('s')}; a "
                    "proxy indicator can support reported_claims/analytical_inference/"
                    "potential_impacts but not a verified or observed fact"
                )

    for group in ("observed_impacts", "potential_impacts"):
        for index, impact in enumerate(output.get(group, [])):
            area = impact.get("area")
            status = impact.get("status")
            severity = impact.get("severity", "none")
            if (
                area in _OPERATIONAL_CONDITION_AREAS
                and status in {"observed", "potential"}
                and severity != "none"
                and not impact.get("evidence_ids")
            ):
                problems.append(
                    f"{group}[{index}] ({area}): an operational-condition impact is "
                    "supported only by indicator_ids; a numeric indicator alone cannot "
                    "establish congestion, a service disruption or another operational "
                    "impact"
                )
            if (
                severity in _HUMAN_REVIEW_SEVERITIES
                and impact.get("evidence_strength") not in _PRIMARY_GRADE_EVIDENCE
            ):
                problems.append(
                    f"{group}[{index}] ({area}): {severity} severity requires primary-grade "
                    f"evidence (A or B), not {impact.get('evidence_strength')!r}"
                )

    for index, chain in enumerate(output.get("transmission_chains", [])):
        if any(chain.get(link) for link in _CHAIN_LINKS):
            if not (chain.get("evidence_ids") or chain.get("indicator_ids")):
                problems.append(
                    f"transmission_chains[{index}] ({chain.get('subject')}): populated "
                    "links cite no evidence_id or indicator_id to support them"
                )

    return problems


def support_reference_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Unknown or ineligible ``indicator_ids`` references, mirroring the
    existing evidence-reference checks."""
    problems: list[str] = []
    known_indicators = {
        str(item.get("series_id") or item.get("indicator_id"))
        for item in package.get("key_indicators", [])
    }
    eligible_indicators = eligible_indicator_ids(package, registry=registry)

    for location, _text, _evidence_ids, indicator_ids in _text_fields(output):
        unknown = set(indicator_ids) - known_indicators
        if unknown:
            problems.append(f"{location}: references unknown indicator IDs {sorted(unknown)}")
        ineligible = (set(indicator_ids) & known_indicators) - eligible_indicators
        if ineligible:
            problems.append(
                f"{location}: cites indicator(s) {sorted(ineligible)} that cannot support a "
                "current claim"
            )

    for index, chain in enumerate(output.get("transmission_chains", [])):
        indicator_ids = list(chain.get("indicator_ids", []))
        unknown = set(indicator_ids) - known_indicators
        if unknown:
            problems.append(
                f"transmission_chains[{index}]: references unknown indicator IDs {sorted(unknown)}"
            )
        ineligible = (set(indicator_ids) & known_indicators) - eligible_indicators
        if ineligible:
            problems.append(
                f"transmission_chains[{index}]: cites indicator(s) {sorted(ineligible)} that "
                "cannot support a current claim"
            )

    return problems


def validate_output(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Apply the Gate I rejection rules to a returned assessment.

    Returns a list of reasons the assessment must be rejected. An empty list
    means the mechanical checks passed -- it does not mean the assessment is
    approved. Approval is a separate, explicitly recorded human act.

    Binding is checked first and unconditionally: if the output is not
    provably about this exact package, nothing else about it is worth
    validating yet.
    """
    problems: list[str] = []
    problems.extend(package_provenance_problems(package, registry=registry))
    problems.extend(binding_problems(output, package))

    if output.get("package_id") != package.get("package_id"):
        problems.append(
            f"output package_id {output.get('package_id')!r} does not match the input "
            f"package {package.get('package_id')!r}"
        )

    known_evidence = {str(item.get("evidence_id")) for item in package.get("evidence_records", [])}
    citable_evidence = citable_evidence_ids(package, registry=registry)
    support = eligible_support_ids(package, registry=registry)

    referenced = set(output.get("evidence_references", []))
    unknown = referenced - known_evidence
    if unknown:
        problems.append(f"references unknown evidence IDs {sorted(unknown)}")
    ineligible = (referenced & known_evidence) - citable_evidence
    if ineligible:
        problems.append(
            f"cites evidence {sorted(ineligible)} that is excluded from this current package's "
            "citable set; fixture and historical evidence cannot support a current claim"
        )

    for location, _text, evidence_ids, _indicator_ids in _text_fields(output):
        unknown_local = set(evidence_ids) - known_evidence
        if unknown_local:
            problems.append(f"{location}: references unknown evidence IDs {sorted(unknown_local)}")
        undeclared = set(evidence_ids) - referenced
        if undeclared:
            problems.append(
                f"{location}: cites evidence {sorted(undeclared)} that is not declared in "
                "evidence_references"
            )
        ineligible_local = (set(evidence_ids) & known_evidence) - citable_evidence
        if ineligible_local:
            problems.append(
                f"{location}: cites evidence {sorted(ineligible_local)} that cannot support a "
                "current claim"
            )

    problems.extend(support_reference_problems(output, package, registry=registry))
    problems.extend(zero_evidence_disposition_problems(output, package, registry=registry))
    if support:
        problems.extend(support_adequacy_problems(output, package, registry=registry))

    missing_series = unavailable_series_ids(package)
    operational_evidence = has_operational_condition_evidence(package, registry=registry)

    for location, text, evidence_ids, _indicator_ids in _text_fields(output):
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
                        f"{location}: asserts causation ({phrase!r}) with no evidence reference"
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

    if output.get("highest_severity_claimed") in {"high", "critical"} and not citable_evidence:
        problems.append(
            f"claims {output.get('highest_severity_claimed')} severity while the package "
            "contains no evidence eligible to support a current conclusion"
        )

    for outlook in output.get("scenarios", []):
        problems.extend(validate_scenario_outlook(outlook))

    for option in output.get("conditional_preparedness_options", []):
        problems.extend(validate_preparedness_option(option))

    return problems


def requires_human_review(output: Mapping[str, Any]) -> bool:
    """High or Critical conclusions always require an explicit human record."""
    return output.get("highest_severity_claimed") in {"high", "critical"}
