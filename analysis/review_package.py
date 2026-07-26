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
from .build_context import parse_timestamp
from .provenance import (
    CURRENT_PUBLICATION,
    PUBLISH_BOUNDED_CLAIM,
    is_fixture,
    provenance_summary,
    qualifies_for_current_publication,
    record_dataset,
    record_origin,
)


def parse_optional_timestamp(value: Any) -> Any:
    """``analysis.build_context.parse_timestamp``, tolerant of ``None`` and
    date-only strings, for comparing package/case cutoffs against evidence
    ``data_period`` values that may be either a date or a date-time."""
    if not value:
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


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
    "Do not give current_situation a current_direction other than 'insufficient_evidence' "
    "without citing at least one eligible evidence_id or indicator_id of its own.",
    "Do not give a key_changes entry any change_type other than 'coverage_change' without "
    "citing at least one eligible evidence_id or indicator_id of its own.",
    "Do not cite an indicator_id in a lane_assessments entry that this package's own "
    "lane_status data for that lane does not associate with it, even if that indicator is "
    "eligible elsewhere in the package.",
    "Do not leave evidence_ids and indicator_ids both empty on a verified_facts, "
    "reported_claims, analytical_inference, observed_impacts or potential_impacts entry.",
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
    indicator IDs.

    ``current_situation`` (WO-010-R4 §1) is a structured
    :data:`currentDisposition <schemas/review_package_output.schema.json>`
    record, not a plain string; its own ``evidence_ids``/``indicator_ids``
    are read here like any other claim-bearing field. Each ``key_changes``
    entry is likewise a structured record now, not a plain string.
    """
    current_situation = output.get("current_situation") or {}
    collected: list[tuple[str, str, list[str], list[str]]] = [
        (
            "current_situation",
            str(current_situation.get("statement", "")),
            list(current_situation.get("evidence_ids", [])),
            list(current_situation.get("indicator_ids", [])),
        )
    ]
    for index, change in enumerate(output.get("key_changes", [])):
        collected.append(
            (
                f"key_changes[{index}]",
                str(change.get("statement", "")),
                list(change.get("evidence_ids", [])),
                list(change.get("indicator_ids", [])),
            )
        )
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
    acquisition_summary: Mapping[str, Any] | None = None,
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

    ``acquisition_summary`` (WO-010-R5 §9) is required in practice -- every
    production caller passes ``analysis.provenance.build_acquisition_summary``'s
    result -- but defaults to an honest empty summary so a caller exercising
    this function in isolation (e.g. a unit test of an unrelated rejection
    rule) is not forced to construct one. Included before the hash is
    computed, so ``package_sha256`` covers it like everything else here: an
    edited acquisition summary is a package integrity failure, the same as
    an edited evidence record.
    """
    acquisition_summary = dict(
        acquisition_summary
        or {
            "qualifying_collection_run_ids": [],
            "qualifying_manual_review_event_ids": [],
            "excluded_unbound_record_count": 0,
            "latest_source_cutoff": None,
            "acquisition_health_limitations": [],
            "collection_run_manifest_hashes": {},
            "manual_review_record_set_hashes": {},
            "included_current_record_ids": [],
            "acquisition_state_sha256": None,
        }
    )
    operational = [event for event in events if event["event_class"] == "direct_operational_event"]
    drivers = [event for event in events if event["event_class"] != "direct_operational_event"]

    conflicts = [
        {"event_id": event["event_id"], **conflict}
        for event in events
        for conflict in event.get("conflicting_evidence", [])
    ]

    # WO-010-R6 §6: a current-publication package's source_cutoff is taken
    # exactly as given -- null stays null rather than silently defaulting to
    # data_cutoff_at, the same correction analysis.build_context.
    # build_context_record already applies to the Build Context. The
    # technical-demo/historical-validation surfaces are unaffected: they are
    # permanently pinned to a fixed fixture cutoff and never claim a null
    # acquisition-derived one.
    resolved_source_cutoff = (
        source_cutoff if dataset == CURRENT_PUBLICATION else (source_cutoff or data_cutoff_at)
    )
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
        "acquisition_summary": acquisition_summary,
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

    # WO-010-R4 §2: a duplicate or namespace-ambiguous ID makes every
    # citation of it unanswerable, whatever dataset the package belongs to.
    problems.extend(duplicate_or_ambiguous_support_id_problems(package))

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


def acquisition_currency_problems(
    package: Mapping[str, Any],
    *,
    collection_runs_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    manual_events_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    current_acquisition_state_sha256: str | None = None,
) -> list[str]:
    """Whether the acquisition events a current package cited still exist,
    unchanged, at the moment of approval (WO-010-R5 §9).

    ``package_provenance_problems`` already re-checks the package's own
    hash against its current on-disk bytes, which catches an *edited*
    package. It cannot catch the different failure this function exists
    for: the package's bytes are untouched, but a collection run or manual
    review event it cited in ``acquisition_summary`` has since disappeared
    (its manifest was corrected or removed), changed status (a run
    originally recorded as ``success`` is now recorded ``error`` after a
    correction, or a manual event moved from ``reviewed`` to
    ``superseded``), or been superseded. An assessment approved against
    acquisition evidence that no longer stands behind it would be published
    as though it still did, unless this is checked again with fresh state
    at the moment of approval -- not only against the state that existed
    when the package was built.

    Intentionally never called from :func:`validate_output`: it needs the
    caller to pass acquisition state read fresh from disk, immediately
    before an approval decision, which is approval-specific policy in the
    same sense the dataset/purpose checks in ``scripts.review_decision.
    approval_provenance_problems`` already are.

    WO-010-R6 §4: ``current_acquisition_state_sha256``, when given, is
    compared against the package's own ``acquisition_summary.
    acquisition_state_sha256`` -- a single hash covering every collection
    run and manual review event this build knows about, not only the ones
    the package happened to cite. This catches what per-ID existence and
    status checks below cannot: a manifest's output list changed but its
    status stayed 'success', a record-set hash changed on an event the
    package never cited, a timestamp was corrected, or a source mapping
    moved -- any of these changes the overall acquisition-state hash even
    when every individually-cited ID still resolves and still shows an
    acceptable status.
    """
    problems: list[str] = []
    summary = package.get("acquisition_summary") or {}

    declared_state_hash = summary.get("acquisition_state_sha256")
    if current_acquisition_state_sha256 is not None and declared_state_hash is not None:
        if declared_state_hash != current_acquisition_state_sha256:
            problems.append(
                f"acquisition_summary.acquisition_state_sha256 {declared_state_hash!r} does "
                f"not match the acquisition state read fresh from disk "
                f"({current_acquisition_state_sha256!r}); some collection-run manifest, "
                "manual-review record-set hash, timestamp or status has changed since this "
                "package was built"
            )

    runs_by_id = {
        run.get("run_id"): run
        for runs in (collection_runs_by_source or {}).values()
        for run in runs
    }
    for run_id in summary.get("qualifying_collection_run_ids", []):
        current = runs_by_id.get(run_id)
        if current is None:
            problems.append(
                f"acquisition_summary cites collection_run_id {run_id!r}, which no longer exists"
            )
        elif current.get("status") not in {"success", "not_modified"}:
            problems.append(
                f"acquisition_summary cites collection_run_id {run_id!r}, whose status has "
                f"changed to {current.get('status')!r} since the package was built"
            )

    events_by_id = {
        event.get("event_id"): event
        for events in (manual_events_by_source or {}).values()
        for event in events
    }
    for event_id in summary.get("qualifying_manual_review_event_ids", []):
        current = events_by_id.get(event_id)
        if current is None:
            problems.append(
                f"acquisition_summary cites manual_review_event_id {event_id!r}, which no "
                "longer exists"
            )
        elif current.get("status") != "reviewed":
            problems.append(
                f"acquisition_summary cites manual_review_event_id {event_id!r}, whose status "
                f"has changed to {current.get('status')!r} since the package was built"
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


def build_support_index(
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """A single normalized index of every support ID the package carries
    (WO-010-R4 §2).

    Keyed by support ID (an ``evidence_id`` or an indicator ``series_id``),
    each entry records what a relevance check needs to answer "does this ID
    actually support *this* claim" rather than only "does this ID exist":
    its support type, dataset, source, geography, the lane(s) it is known to
    relate to, its evidence role or claim type, its evidence strength, its
    geographic scope, its publication-use disposition, its data period and
    its freshness. Built once per validation pass and read by every
    relevance check below, so two checks can never disagree about what one
    ID actually is.
    """
    index: dict[str, dict[str, Any]] = {}

    lane_ids_by_indicator: dict[str, set[str]] = {}
    for lane in package.get("lane_status", []):
        for indicator_id in lane.get("indicator_ids", []):
            lane_ids_by_indicator.setdefault(indicator_id, set()).add(lane.get("lane_id"))

    for indicator in package.get("key_indicators", []):
        series_id = str(indicator.get("series_id") or indicator.get("indicator_id"))
        index[series_id] = {
            "support_id": series_id,
            "support_type": "indicator",
            "dataset": indicator.get("dataset"),
            "source_id": indicator.get("source_id"),
            "geography": indicator.get("geographic_scope"),
            "lane_ids": sorted(lane_ids_by_indicator.get(series_id, set())),
            "domain": None,
            "indicator_family": series_id,
            "evidence_role": None,
            "claim_type": None,
            "evidence_strength": None,
            "geographic_scope": indicator.get("geographic_scope"),
            "publication_use_applied": indicator.get("publication_use_applied"),
            "data_period": indicator.get("current_period"),
            "freshness": (indicator.get("freshness") or {}).get("status"),
        }

    lane_ids_by_event: dict[str, set[str]] = {}
    for lane in package.get("lane_status", []):
        for event_id in (
            *lane.get("active_event_ids", []),
            *lane.get("external_driver_event_ids", []),
        ):
            lane_ids_by_event.setdefault(event_id, set()).add(lane.get("lane_id"))

    # WO-010-R6 §8/§9: each Lane's own reference-model geography (carried
    # into the package by scripts.build_review_package._bounded_lane), used
    # below to find every Lane a piece of evidence actually intersects --
    # not only the Lane(s) the platform's own current assessment happened to
    # link the evidence's event to.
    lane_geo_by_id: dict[str, dict[str, set[str]]] = {
        lane.get("lane_id"): {
            "country_ids": set(lane.get("country_ids") or []),
            "node_ids": set(lane.get("node_ids") or []),
            "chokepoint_ids": set(lane.get("chokepoint_ids") or []),
        }
        for lane in package.get("lane_status", [])
    }

    # WO-010-R5 §5: which event backs each evidence item, and whether that
    # event is an external driver with an admitted (complete) transmission
    # chain -- an external driver whose chain is still incomplete has not
    # established a mechanism into any Lane yet, so its evidence cannot
    # support one.
    events_by_id = {
        event.get("event_id"): event
        for event in (
            *package.get("active_operational_events", []),
            *package.get("external_drivers", []),
        )
    }

    for item in package.get("evidence_records", []):
        evidence_id = str(item.get("evidence_id"))
        event_id = item.get("event_id")
        event = events_by_id.get(event_id) or {}
        event_country_ids = set(event.get("country_ids") or [])
        event_node_ids = set(event.get("node_ids") or [])
        event_chokepoint_ids = set(event.get("chokepoint_ids") or [])

        # WO-010-R6 §9: the event's own reviewed lane_relevance, scoped to
        # entries that actually name this evidence_id -- an explicit
        # reviewed Lane relevance link, not a blanket scope-based pass.
        explicit_lane_ids = {
            relevance.get("lane_id")
            for relevance in (event.get("lane_relevance") or [])
            if evidence_id in (relevance.get("evidence_ids") or [])
        }

        # Real geographic intersection against each Lane's own reference
        # model -- gated by the evidence's *own* recorded scope_supported,
        # not applied indiscriminately: a country/region notice may
        # generalise by country, a node notice by node, a route notice
        # (the shape a chokepoint notice takes) by chokepoint. A facility-
        # or asset-scoped item makes no such claim about a whole country or
        # node and must still rely on an explicit link -- otherwise a
        # single-terminal notice sharing its event's country with a Lane
        # would silently generalise into "Thailand-wide", which is exactly
        # what WO-010-R6 §9 forbids.
        scope_type = item.get("scope_supported")
        geo_lane_ids: set[str] = set()
        if scope_type in {"country", "region"}:
            geo_lane_ids |= {
                lane_id
                for lane_id, geo in lane_geo_by_id.items()
                if geo["country_ids"] & event_country_ids
            }
        if scope_type == "node":
            geo_lane_ids |= {
                lane_id
                for lane_id, geo in lane_geo_by_id.items()
                if geo["node_ids"] & event_node_ids
            }
        if scope_type == "route":
            geo_lane_ids |= {
                lane_id
                for lane_id, geo in lane_geo_by_id.items()
                if geo["chokepoint_ids"] & event_chokepoint_ids
            }

        relevant_lane_ids = (
            lane_ids_by_event.get(event_id, set()) | explicit_lane_ids | geo_lane_ids
        )

        index[evidence_id] = {
            "support_id": evidence_id,
            "support_type": "evidence",
            "dataset": item.get("dataset"),
            "source_id": item.get("source_id"),
            "geography": item.get("scope_supported"),
            "lane_ids": sorted(lid for lid in relevant_lane_ids if lid),
            "domain": None,
            "indicator_family": None,
            "evidence_role": item.get("evidence_role"),
            "claim_type": item.get("claim_type"),
            "evidence_strength": item.get("strength"),
            "geographic_scope": "thailand",
            "publication_use_applied": None,
            "data_period": item.get("publication_date"),
            "freshness": None,
            "event_class": event.get("event_class"),
            "transmission_chain_admitted": (
                (event.get("transmission_chain") or {}).get("completeness") == "complete"
            ),
            # WO-010-R6 §8: the event's own structured geography, carried
            # through rather than collapsed into the coarse scope_supported
            # label -- so a Thailand country-wide notice, a Panama
            # country-wide notice, a Suez-related route notice, a single
            # terminal notice and a global indicator all remain
            # distinguishable at this index.
            "country_ids": sorted(event_country_ids),
            "geography_ids": sorted(event.get("geography_ids") or []),
            "node_ids": sorted(event_node_ids),
            "chokepoint_ids": sorted(event_chokepoint_ids),
            "modes": sorted(event.get("modes") or []),
            "scope_type": item.get("scope_supported"),
        }

    return index


def duplicate_or_ambiguous_support_id_problems(package: Mapping[str, Any]) -> list[str]:
    """Duplicate or namespace-ambiguous support IDs in the package itself
    (WO-010-R4 §2).

    A duplicate evidence_id or series_id makes "which record does this
    citation actually mean" unanswerable; an ID reused across both
    namespaces (an evidence_id that is also a key_indicators series_id) is
    worse -- a citation could mean either, silently. Both fail validation
    rather than being resolved by picking one arbitrarily.
    """
    problems: list[str] = []
    evidence_ids = [str(item.get("evidence_id")) for item in package.get("evidence_records", [])]
    indicator_ids = [
        str(item.get("series_id") or item.get("indicator_id"))
        for item in package.get("key_indicators", [])
    ]

    duplicate_evidence = sorted({eid for eid in evidence_ids if evidence_ids.count(eid) > 1})
    if duplicate_evidence:
        problems.append(
            f"package evidence_records contains duplicate evidence_id(s): {duplicate_evidence}"
        )

    duplicate_indicators = sorted({sid for sid in indicator_ids if indicator_ids.count(sid) > 1})
    if duplicate_indicators:
        problems.append(
            f"package key_indicators contains duplicate series_id(s): {duplicate_indicators}"
        )

    ambiguous = sorted(set(evidence_ids) & set(indicator_ids))
    if ambiguous:
        problems.append(
            f"package uses the same ID(s) as both an evidence_id and an indicator series_id, "
            f"which is ambiguous for any citation: {ambiguous}"
        )

    return problems


def _establishes_thailand_directly(entry: Mapping[str, Any]) -> bool:
    """Whether one support-index entry, on its own, may establish a
    Thailand-wide observed condition without a stated aggregation basis
    (WO-010-R6 §9).

    True only for evidence whose own recorded ``scope_supported`` is
    ``country``/``region`` *and* whose event actually names Thailand
    (``TH``) among its ``country_ids`` -- a genuine Thailand-wide notice.
    Global-scoped evidence, and country/region evidence about somewhere
    else, are deliberately excluded: global evidence "may support context or
    inference, but cannot independently establish a Thailand- or
    Lane-specific observed condition" on its own recorded scope alone.
    """
    return entry.get("geography") in {"country", "region"} and "TH" in (
        entry.get("country_ids") or []
    )


def lane_support_relevance_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Whether a lane assessment's cited evidence and indicators actually
    relate to that lane (WO-010-R4 §2, extended WO-010-R5 §5).

    The package's own ``lane_status`` already records, per lane, exactly
    which indicator_ids the platform's own domain math used
    (``domain_indicator_ids`` / ``indicator_ids``). A returned lane
    assessment may cite any of those; an indicator that is eligible
    somewhere else in the package but was never associated with *this* lane
    is not support for a claim about it, and citing it anyway is rejected --
    "one eligible indicator supports every claim" is exactly the shortcut
    this check exists to close.

    WO-010-R5 §5 applies the same discipline to ``evidence_ids``, and
    WO-010-R6 §9 removes the one exception that discipline used to carry: a
    ``country``/``region``/``global`` ``scope_supported`` value is no longer
    an automatic pass for every lane. Evidence may support a lane only when
    :func:`build_support_index` actually links it there -- via the Lane
    reference model's own ``country_ids``/``node_ids``/``chokepoint_ids``
    intersecting the evidence's event geography, an explicit reviewed
    ``lane_relevance`` entry naming this evidence_id, or the platform's own
    current-assessment linkage (``active_event_ids``/
    ``external_driver_event_ids``). Global-scoped evidence in particular
    must still clear one of those three; it is never an automatic pass on
    its scope value alone. Evidence attached to an ``external_driver`` event
    additionally needs that event's transmission chain to be admitted
    (complete); a driver whose chain is still incomplete has not established
    a mechanism into any lane yet, so citing it for one is rejected the same
    as citing unrelated evidence.
    """
    problems: list[str] = []
    eligible = eligible_indicator_ids(package, registry=registry)
    citable_evidence = citable_evidence_ids(package, registry=registry)
    support_index = build_support_index(package, registry=registry)
    lane_indicator_ids = {
        lane.get("lane_id"): set(lane.get("indicator_ids", []))
        for lane in package.get("lane_status", [])
    }

    for index, lane in enumerate(output.get("lane_assessments", [])):
        lane_id = lane.get("lane_id")
        relevant = lane_indicator_ids.get(lane_id, set())
        cited_indicators = set(lane.get("indicator_ids", []))
        irrelevant = (cited_indicators & eligible) - relevant
        if irrelevant:
            problems.append(
                f"lane_assessments[{index}] ({lane_id}): cites indicator(s) {sorted(irrelevant)} "
                "that this lane's own data in the package does not associate with it"
            )

        for evidence_id in sorted(set(lane.get("evidence_ids", [])) & citable_evidence):
            entry = support_index.get(evidence_id)
            if entry is None:
                continue
            if entry.get("event_class") == "external_driver" and not entry.get(
                "transmission_chain_admitted"
            ):
                problems.append(
                    f"lane_assessments[{index}] ({lane_id}): cites evidence {evidence_id!r} "
                    "from an external driver whose transmission chain is not admitted, which "
                    "cannot support a lane direction"
                )
                continue
            if lane_id in (entry.get("lane_ids") or []):
                continue
            problems.append(
                f"lane_assessments[{index}] ({lane_id}): cites evidence {evidence_id!r} "
                f"(scope_supported={entry.get('geography')!r}) that the reference model does "
                "not link to this lane"
            )

    return problems


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
        if output_field not in output:
            problems.append(f"output is missing required binding field {output_field!r}")
            continue
        output_value = output.get(output_field)
        package_value = package.get(package_field)
        # WO-010-R6 §6: a key that is *present* but null is a valid echo of
        # a package field that is itself honestly null (source_cutoff with
        # zero acquisition-bound evidence) -- only an absent key is a
        # missing binding field. Checking truthiness here previously
        # rejected a correct null echo as though the field were missing.
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

    # WO-010-R4 §1: current_situation is now structured, so the primary
    # check reads its own current_direction/current_disposition/support
    # fields rather than scanning its statement for coverage-gap phrasing.
    # The phrase scan stays as a secondary signal against a statement that
    # contradicts a structurally-correct disposition -- free text alone can
    # never be what decides this, but it can still catch a lie.
    current_situation = output.get("current_situation") or {}
    current_direction = current_situation.get("current_direction")
    if current_direction != "insufficient_evidence":
        problems.append(
            "the package holds no eligible evidence or indicator, but "
            f"current_situation.current_direction is {current_direction!r}, not "
            "'insufficient_evidence'"
        )
    if current_situation.get("current_disposition") != "insufficient_evidence":
        problems.append(
            "the package holds no eligible evidence or indicator, but "
            f"current_situation.current_disposition is "
            f"{current_situation.get('current_disposition')!r}, not 'insufficient_evidence'"
        )
    if current_situation.get("evidence_ids") or current_situation.get("indicator_ids"):
        problems.append(
            "current_situation: cites support references despite the package holding none eligible"
        )
    situation_text = str(current_situation.get("statement", "")).lower()
    if not any(phrase in situation_text for phrase in _COVERAGE_GAP_PHRASES):
        problems.append(
            "the package holds no eligible evidence or indicator, but current_situation's "
            "statement does not state an insufficient-coverage position"
        )

    for index, change in enumerate(output.get("key_changes", [])):
        if change.get("change_type") != "coverage_change":
            problems.append(
                f"key_changes[{index}]: change_type {change.get('change_type')!r} asserts a "
                "change the package holds no eligible evidence or indicator for; only "
                "'coverage_change' is permitted with zero eligible support"
            )
        if change.get("evidence_ids") or change.get("indicator_ids"):
            problems.append(
                f"key_changes[{index}]: cites support references despite the package holding "
                "none eligible"
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
            # WO-010-R4 §3: identical narratives alone are not a structural
            # signal -- two arbitrary but matching sentences would pass that
            # check. Where a case states its own disposition, it must say
            # coverage_only, not merely happen to read the same as the
            # other two.
            if case.get("disposition") is not None and case.get("disposition") != "coverage_only":
                problems.append(
                    f"scenarios[{index}]/{name}: disposition {case.get('disposition')!r} is not "
                    "'coverage_only', but the package holds no eligible evidence or indicator"
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

    # WO-010-R4 §1: current_situation is a claim like any other. A direction
    # other than insufficient_evidence needs its own citation -- the package
    # holding eligible support *somewhere* is not support for *this* claim.
    current_situation = output.get("current_situation") or {}
    if current_situation.get("current_direction") != "insufficient_evidence" and not (
        current_situation.get("evidence_ids") or current_situation.get("indicator_ids")
    ):
        problems.append(
            f"current_situation: current_direction {current_situation.get('current_direction')!r} "
            "cites no evidence_id or indicator_id to support it"
        )

    # WO-010-R4 §1: every key change that is not explicitly a coverage
    # statement needs its own citation, for the same reason.
    for index, change in enumerate(output.get("key_changes", [])):
        if change.get("change_type") != "coverage_change" and not (
            change.get("evidence_ids") or change.get("indicator_ids")
        ):
            problems.append(
                f"key_changes[{index}]: change_type {change.get('change_type')!r} cites no "
                "evidence_id or indicator_id to support it"
            )

    # WO-010-R4 §1/§2: a claim-bearing item with no support of its own is
    # rejected even when the package holds eligible support elsewhere --
    # one eligible indicator somewhere in the package is never support for
    # every other claim. conflicting_evidence is excluded here: its own
    # schema already requires at least two evidence_ids.
    for group in (
        "verified_facts",
        "reported_claims",
        "analytical_inference",
        "observed_impacts",
        "potential_impacts",
    ):
        for index, item in enumerate(output.get(group, [])):
            if not (item.get("evidence_ids") or item.get("indicator_ids")):
                problems.append(
                    f"{group}[{index}]: cites no evidence_id or indicator_id to support it"
                )

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


#: Scenario subject types that describe Thailand as a whole rather than one
#: lane, node or event -- a case here needs either broad-scope evidence or an
#: explicit aggregation_basis before it may rely on narrower evidence.
_THAILAND_WIDE_SUBJECT_TYPES = frozenset({"thailand_ocean", "thailand_overall"})


def scenario_support_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Scenario support validation (WO-010-R4 §3, extended WO-010-R5 §6).

    Every ``base_case`` / ``deterioration_case`` / ``improvement_case``
    ``evidence_ids`` and ``indicator_ids`` is checked against the package the
    same way any other claim-bearing field is -- unknown, fixture,
    historical, excluded or otherwise ineligible IDs are rejected. Not
    checked anywhere else: :func:`_text_fields` never reads scenario cases,
    so before this a scenario's own support references passed through
    entirely unvalidated.

    Beyond reference validity: a differentiated outlook (its three cases do
    not all read the same, i.e. it is actually asserting something rather
    than stating a coverage gap) requires every case to cite its own
    support -- one case borrowing what another case's evidence established
    is exactly the "one eligible indicator supports every claim" shortcut
    this module exists to close. And for a lane-scoped outlook, a cited
    indicator or evidence item must be one this package's own reference
    model actually associates with that lane, the same relevance rule
    :func:`lane_support_relevance_problems` applies to ``lane_assessments``
    -- so one lane's notice cannot support another lane's scenario.

    WO-010-R5 §6 adds: evidence from an unadmitted external driver cannot
    support any case (mirroring the lane check); evidence dated after the
    outlook's own ``data_cutoff_at`` (or, absent one, the package's) falls
    outside the scenario's analytical cutoff and is rejected; discovery-only
    evidence cannot support a scenario outcome, the same as it cannot
    support a lane direction or a preparedness option; and a Thailand-wide
    outlook (``subject_type`` in ``thailand_ocean``/``thailand_overall``)
    relying solely on narrow-scope (facility/node/asset/route) evidence must
    set that case's ``aggregation_basis`` -- a fact this narrow, generalised
    to all of Thailand, needs its own stated reason, not just a citation.
    """
    problems: list[str] = []
    known_evidence = {str(item.get("evidence_id")) for item in package.get("evidence_records", [])}
    citable_evidence = citable_evidence_ids(package, registry=registry)
    known_indicators = {
        str(item.get("series_id") or item.get("indicator_id"))
        for item in package.get("key_indicators", [])
    }
    eligible_indicators = eligible_indicator_ids(package, registry=registry)
    lane_indicator_ids = {
        lane.get("lane_id"): set(lane.get("indicator_ids", []))
        for lane in package.get("lane_status", [])
    }
    support_index = build_support_index(package, registry=registry)
    discovery_only_ids = {
        str(item.get("evidence_id"))
        for item in package.get("evidence_records", [])
        if item.get("evidence_role") == "discovery_only"
    }
    package_cutoff = parse_optional_timestamp(package.get("data_cutoff_at"))
    case_names = ("base_case", "deterioration_case", "improvement_case")

    for index, outlook in enumerate(output.get("scenarios", [])):
        cases = {name: outlook.get(name) for name in case_names}
        if any(case is None for case in cases.values()):
            continue
        label = f"scenarios[{index}] ({outlook.get('outlook_id')})"
        differentiated = len({case.get("narrative") for case in cases.values()}) > 1
        subject_type = outlook.get("subject_type")
        subject_id = outlook.get("subject_id")
        case_cutoff = parse_optional_timestamp(outlook.get("data_cutoff_at")) or package_cutoff

        for name, case in cases.items():
            evidence_ids = set(case.get("evidence_ids", []))
            indicator_ids = set(case.get("indicator_ids", []))

            unknown_evidence = evidence_ids - known_evidence
            if unknown_evidence:
                problems.append(
                    f"{label}/{name}: references unknown evidence IDs {sorted(unknown_evidence)}"
                )
            ineligible_evidence = (evidence_ids & known_evidence) - citable_evidence
            if ineligible_evidence:
                problems.append(
                    f"{label}/{name}: cites evidence {sorted(ineligible_evidence)} that cannot "
                    "support a current claim"
                )
            cited_discovery = evidence_ids & discovery_only_ids
            if cited_discovery:
                problems.append(
                    f"{label}/{name}: rests on discovery-only evidence {sorted(cited_discovery)}, "
                    "which cannot support a scenario outcome"
                )

            unknown_indicators = indicator_ids - known_indicators
            if unknown_indicators:
                problems.append(
                    f"{label}/{name}: references unknown indicator IDs {sorted(unknown_indicators)}"
                )
            ineligible_indicators = (indicator_ids & known_indicators) - eligible_indicators
            if ineligible_indicators:
                problems.append(
                    f"{label}/{name}: cites indicator(s) {sorted(ineligible_indicators)} that "
                    "cannot support a current claim"
                )

            if differentiated and not (evidence_ids or indicator_ids):
                problems.append(
                    f"{label}/{name}: this outlook differentiates its cases but {name} cites no "
                    "evidence_id or indicator_id to support its own narrative"
                )

            valid_cited_evidence = evidence_ids & citable_evidence
            narrow_evidence_scopes: set[str] = set()
            for evidence_id in sorted(valid_cited_evidence):
                entry = support_index.get(evidence_id)
                if entry is None:
                    continue
                if case_cutoff is not None:
                    entry_period = parse_optional_timestamp(entry.get("data_period"))
                    if entry_period is not None and entry_period > case_cutoff:
                        problems.append(
                            f"{label}/{name}: cites evidence {evidence_id!r} dated after this "
                            "scenario's own analytical cutoff"
                        )
                        continue
                if entry.get("event_class") == "external_driver" and not entry.get(
                    "transmission_chain_admitted"
                ):
                    problems.append(
                        f"{label}/{name}: cites evidence {evidence_id!r} from an external "
                        "driver whose transmission chain is not admitted"
                    )
                    continue
                # WO-010-R6 §9: whether this evidence, on its own recorded
                # scope, may independently establish a Thailand-wide
                # condition. Facility/node/asset/route evidence never can;
                # neither can global-scoped evidence or country/region
                # evidence about somewhere other than Thailand -- only a
                # genuine Thailand country/region notice can, and even then
                # only for a Thailand-wide *subject*, never as a substitute
                # for an actual Lane link below.
                if not _establishes_thailand_directly(entry):
                    narrow_evidence_scopes.add(evidence_id)
                if subject_type == "lane" and subject_id not in (entry.get("lane_ids") or []):
                    problems.append(
                        f"{label}/{name}: cites evidence {evidence_id!r} "
                        f"(scope_supported={entry.get('geography')!r}) that the reference "
                        "model does not link to this lane"
                    )

            if (
                subject_type in _THAILAND_WIDE_SUBJECT_TYPES
                and narrow_evidence_scopes
                and not (indicator_ids & eligible_indicators)
                and not case.get("aggregation_basis")
            ):
                problems.append(
                    f"{label}/{name}: relies solely on facility/node/asset/route-scoped "
                    f"evidence {sorted(narrow_evidence_scopes)} for a Thailand-wide subject "
                    "without stating an aggregation_basis"
                )

            if outlook.get("subject_type") == "lane":
                relevant = lane_indicator_ids.get(outlook.get("subject_id"), set())
                irrelevant = (indicator_ids & eligible_indicators) - relevant
                if irrelevant:
                    problems.append(
                        f"{label}/{name}: cites indicator(s) {sorted(irrelevant)} that this "
                        "lane's own data in the package does not associate with it"
                    )

    return problems


def preparedness_support_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Bind preparedness options to support (WO-010-R4 §4).

    An operational option -- anything not explicitly marked
    ``is_data_coverage_action`` -- must cite at least one eligible
    ``evidence_id`` or ``indicator_id`` of its own, exactly like any other
    material claim; ``evidence_basis`` free text is an explanation of that
    citation, never a substitute for it. Every cited ID is checked against
    the package the same way any other reference is: unknown, ineligible or
    discovery-only support is rejected.
    """
    problems: list[str] = []
    known_evidence = {str(item.get("evidence_id")) for item in package.get("evidence_records", [])}
    citable_evidence = citable_evidence_ids(package, registry=registry)
    known_indicators = {
        str(item.get("series_id") or item.get("indicator_id"))
        for item in package.get("key_indicators", [])
    }
    eligible_indicators = eligible_indicator_ids(package, registry=registry)
    discovery_only_ids = {
        str(item.get("evidence_id"))
        for item in package.get("evidence_records", [])
        if item.get("evidence_role") == "discovery_only"
    }

    for index, option in enumerate(output.get("conditional_preparedness_options", [])):
        label = f"conditional_preparedness_options[{index}]"
        evidence_ids = set(option.get("evidence_ids", []))
        indicator_ids = set(option.get("indicator_ids", []))

        unknown_evidence = evidence_ids - known_evidence
        if unknown_evidence:
            problems.append(f"{label}: references unknown evidence IDs {sorted(unknown_evidence)}")
        ineligible_evidence = (evidence_ids & known_evidence) - citable_evidence
        if ineligible_evidence:
            problems.append(
                f"{label}: cites evidence {sorted(ineligible_evidence)} that cannot support a "
                "current claim"
            )
        cited_discovery = evidence_ids & discovery_only_ids
        if cited_discovery:
            problems.append(
                f"{label}: rests on discovery-only evidence {sorted(cited_discovery)}, which "
                "cannot support an operational preparedness option"
            )

        unknown_indicators = indicator_ids - known_indicators
        if unknown_indicators:
            problems.append(
                f"{label}: references unknown indicator IDs {sorted(unknown_indicators)}"
            )
        ineligible_indicators = (indicator_ids & known_indicators) - eligible_indicators
        if ineligible_indicators:
            problems.append(
                f"{label}: cites indicator(s) {sorted(ineligible_indicators)} that cannot "
                "support a current claim"
            )

        if not option.get("is_data_coverage_action") and not (evidence_ids or indicator_ids):
            problems.append(
                f"{label}: is an operational option but cites no evidence_id or indicator_id "
                "of its own; evidence_basis free text is an explanation, not a substitute for "
                "a validated support ID"
            )

    return problems


#: Indicator series_id values compatible with a cost/freight/fuel/FX
#: preparedness applicability declaration (WO-010-R5 §7).
_COST_DOMAIN_INDICATOR_FAMILIES = frozenset(
    {
        "container_freight_benchmark",
        "thailand_diesel_retail_price",
        "usd_thb_reference_rate",
        "brent_crude_price",
        "gscpi_index",
    }
)

#: applicable_domain_ids values that mean "this is a cost/freight/fuel/FX
#: monitoring option" for the purposes of the compatible-indicator check.
_COST_DOMAIN_IDS = frozenset(
    {
        "cost_context",
        "fuel_pressure",
        "fx_pressure",
        "freight_benchmark",
        "freight_market_benchmark_or_proxy",
    }
)


def preparedness_applicability_problems(
    output: Mapping[str, Any],
    package: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Whether a preparedness option's cited support actually overlaps its
    declared applicability (WO-010-R5 §7).

    ``applicable_geography_ids``, ``applicable_lane_ids`` and
    ``applicable_domain_ids`` are optional, so an option that sets none of
    them is not checked here at all -- this function only holds an option to
    the applicability it itself declared. Free-text ``applicable_to`` and
    ``support_basis`` remain explanatory only, exactly as
    :func:`preparedness_support_problems` already treats ``evidence_basis``.

    * A lane-specific option (``applicable_lane_ids`` set) needs at least
      one cited support record the reference model associates with one of
      those lanes.
    * A chokepoint option (an ``applicable_geography_ids`` entry shaped like
      a chokepoint ID, ``CHK-...``) needs support relevant to that
      chokepoint's own exposed lane(s), read from the package's own
      ``lane_status[i].chokepoint_exposure``.
    * A cost/freight/fuel/FX-monitoring option (``applicable_domain_ids``
      naming one of those domains) needs a compatible indicator, not just
      any indicator.
    * An operational-contingency option (``option_type: "contingency"`` or
      an ``operational_contingency`` domain) needs at least one evidence_id
      -- a numeric indicator alone cannot establish an operational
      condition, the same rule :func:`support_adequacy_problems` already
      applies to ``observed_impacts``/``potential_impacts``.
    * A Thailand-wide option (an ``applicable_geography_ids`` entry that is
      neither a chokepoint nor a Lane ID) needs support whose own scope is
      Thailand-wide or broader, unless the option is explicitly a data
      coverage action.

    Discovery-only evidence is not re-checked here: :func:`preparedness_
    support_problems` already rejects it for every operational option,
    applicability declared or not.
    """
    problems: list[str] = []
    support_index = build_support_index(package, registry=registry)

    lanes_by_chokepoint: dict[str, set[str]] = {}
    for lane in package.get("lane_status", []):
        for exposure in lane.get("chokepoint_exposure", []):
            chokepoint_id = exposure.get("chokepoint_id")
            if chokepoint_id:
                lanes_by_chokepoint.setdefault(chokepoint_id, set()).add(lane.get("lane_id"))

    for index, option in enumerate(output.get("conditional_preparedness_options", [])):
        label = f"conditional_preparedness_options[{index}]"
        support_ids = set(option.get("evidence_ids", [])) | set(option.get("indicator_ids", []))
        entries = [support_index[sid] for sid in support_ids if sid in support_index]
        applicable_lane_ids = set(option.get("applicable_lane_ids") or [])
        applicable_geography_ids = set(option.get("applicable_geography_ids") or [])
        applicable_domain_ids = set(option.get("applicable_domain_ids") or [])
        is_coverage = bool(option.get("is_data_coverage_action"))
        support_lane_ids = {
            lane_id for entry in entries for lane_id in (entry.get("lane_ids") or [])
        }

        if applicable_lane_ids and not is_coverage and not (support_lane_ids & applicable_lane_ids):
            problems.append(
                f"{label}: declares applicable_lane_ids {sorted(applicable_lane_ids)} but "
                "cited support relates to none of them"
            )

        chokepoint_ids = {g for g in applicable_geography_ids if g.startswith("CHK-")}
        if chokepoint_ids and not is_coverage:
            relevant_lanes: set[str] = set()
            for chokepoint_id in chokepoint_ids:
                relevant_lanes |= lanes_by_chokepoint.get(chokepoint_id, set())
            if not (support_lane_ids & relevant_lanes):
                problems.append(
                    f"{label}: declares chokepoint applicability {sorted(chokepoint_ids)} but "
                    "cited support is not relevant to that chokepoint's exposed lane(s)"
                )

        if applicable_domain_ids & _COST_DOMAIN_IDS and not is_coverage:
            indicator_families = {
                entry.get("indicator_family")
                for entry in entries
                if entry.get("support_type") == "indicator"
            }
            if not (indicator_families & _COST_DOMAIN_INDICATOR_FAMILIES):
                problems.append(
                    f"{label}: declares a cost/freight/fuel/FX applicable_domain_id but cites "
                    "no compatible indicator"
                )

        if (
            "operational_contingency" in applicable_domain_ids
            or option.get("option_type") == "contingency"
        ) and not is_coverage:
            if not any(entry.get("support_type") == "evidence" for entry in entries):
                problems.append(
                    f"{label}: is an operational contingency option but cites no evidence_id; "
                    "a numeric indicator alone cannot establish an operational condition"
                )

        thailand_wide_geography = applicable_geography_ids - chokepoint_ids - applicable_lane_ids
        if thailand_wide_geography and not is_coverage:
            # WO-010-R6 §9: an indicator's own geographic_scope of
            # "thailand" is a real signal (set once, at the point the
            # platform knows which source produced it); a global-scoped
            # evidence item is not -- only a genuine Thailand country/region
            # notice may independently establish Thailand-wide relevance.
            compatible = any(
                entry.get("geography") == "thailand"
                or (
                    entry.get("support_type") == "evidence"
                    and _establishes_thailand_directly(entry)
                )
                for entry in entries
            )
            if not compatible:
                problems.append(
                    f"{label}: declares Thailand-wide applicable_geography_ids "
                    f"{sorted(thailand_wide_geography)} but cited support does not establish "
                    "Thailand-wide relevance"
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
    problems.extend(lane_support_relevance_problems(output, package, registry=registry))
    problems.extend(scenario_support_problems(output, package, registry=registry))
    problems.extend(preparedness_support_problems(output, package, registry=registry))
    problems.extend(preparedness_applicability_problems(output, package, registry=registry))
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
