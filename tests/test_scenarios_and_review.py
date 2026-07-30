"""Scenario completeness, preparedness constraints, and the AI review gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.assessments import (
    DOMAINS,
    attention_level,
    build_domain_assessment,
    build_lane_assessment,
    find_point_forecasts,
    validate_preparedness_option,
    validate_scenario_outlook,
)
from analysis.contracts import schema_errors
from analysis.review_package import (
    BINDING_FIELDS,
    binding_problems,
    build_input_package,
    has_operational_condition_evidence,
    requires_human_review,
    unavailable_series_ids,
    validate_output,
)
from tests.positive_path import TEST_REGISTRY, manual_notice_evidence

ROOT = Path(__file__).resolve().parents[1]


def domain_set(direction="stable", rule_id="FUEL-MOM-V1"):
    return [
        build_domain_assessment(
            domain,
            direction=direction,
            basis="test",
            threshold_rule_id=rule_id if direction != "insufficient_evidence" else None,
        )
        for domain in DOMAINS
    ]


def case(**overrides):
    base = {
        "narrative": "Conditions may change if the triggers below are observed.",
        "time_horizon": "1-4_weeks",
        "trigger_conditions": [{"condition": "x rises", "observable_via": "series x"}],
        "evidence_ids": [],
        "confidence": "low",
        "data_gaps": [],
    }
    base.update(overrides)
    return base


def outlook(**overrides):
    base = {
        "outlook_id": "OUT-TEST",
        "subject_type": "lane",
        "subject_id": "LANE-OCEAN-TH-NEUR",
        "generated_at": "2026-07-24T00:00:00Z",
        "base_case": case(),
        "deterioration_case": case(),
        "improvement_case": case(),
        "known_limitations": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Scenario completeness and point forecasts
# ---------------------------------------------------------------------------


def test_a_complete_outlook_passes():
    assert validate_scenario_outlook(outlook()) == []


@pytest.mark.parametrize("missing", ["base_case", "deterioration_case", "improvement_case"])
def test_a_missing_case_is_rejected(missing):
    problems = validate_scenario_outlook(outlook(**{missing: None}))
    assert any(f"missing {missing}" in problem for problem in problems)


def test_a_case_without_triggers_is_rejected():
    problems = validate_scenario_outlook(outlook(base_case=case(trigger_conditions=[])))
    assert any("no trigger conditions" in problem for problem in problems)


def test_a_numeric_point_forecast_in_a_narrative_is_rejected():
    problems = validate_scenario_outlook(
        outlook(base_case=case(narrative="Freight rates will rise 20 percent within a month."))
    )
    assert any("point forecast" in problem for problem in problems)


@pytest.mark.parametrize(
    "narrative",
    [
        "Transit times are expected to lengthen by 14 days.",
        "The benchmark will reach 3000 index points.",
        "We forecast a 12% increase in cost.",
    ],
)
def test_forecast_phrasings_are_caught(narrative):
    assert find_point_forecasts(narrative)


@pytest.mark.parametrize(
    "narrative",
    [
        "Conditions may deteriorate if the documented thresholds are crossed.",
        "The lane currently reads as deteriorating across 3 of 9 domains.",
        "Carriers rerouted services in December 2023.",
    ],
)
def test_descriptive_sentences_with_numbers_are_not_flagged(narrative):
    assert find_point_forecasts(narrative) == []


def test_a_trigger_threshold_is_not_treated_as_a_forecast():
    """Triggers legitimately carry numbers; they are monitorable, not predictive."""
    problems = validate_scenario_outlook(
        outlook(
            base_case=case(
                narrative="No forecast is offered.",
                trigger_conditions=[
                    {
                        "condition": "benchmark month-over-month change rises above +5 percent",
                        "observable_via": "the freight benchmark series",
                    }
                ],
            )
        )
    )
    assert problems == []


# ---------------------------------------------------------------------------
# Preparedness constraints
# ---------------------------------------------------------------------------


def option(**overrides):
    base = {
        "option_type": "monitor",
        "description": "An organization with exposure to this lane may wish to track it.",
        "applicable_to": "Organizations with exposure",
        "trigger_condition": "The lane is published at watch or elevated attention.",
        "possible_benefit": "Earlier awareness.",
        "tradeoffs": ["Requires attention."],
        "limitations": ["The platform holds no shipment data."],
        "exit_condition": "The lane returns to routine.",
        "evidence_basis": [],
    }
    base.update(overrides)
    return base


def test_a_conditional_neutral_option_passes():
    assert validate_preparedness_option(option()) == []


@pytest.mark.parametrize(
    "description",
    [
        "You must divert cargo away from this lane.",
        "Companies must increase safety stock immediately.",
        "Your company should rebook via an alternative hub.",
    ],
)
def test_mandatory_instructions_are_rejected(description):
    problems = validate_preparedness_option(option(description=description))
    assert any("mandatory instruction phrasing" in problem for problem in problems)


def test_organization_specific_phrasing_is_rejected():
    problems = validate_preparedness_option(
        option(description="Reposition your fleet ahead of the restriction.")
    )
    assert any("organization-specific phrasing" in problem for problem in problems)


def test_an_option_without_a_trigger_is_an_instruction_and_is_rejected():
    problems = validate_preparedness_option(option(trigger_condition=""))
    assert any("instruction, not a conditional option" in problem for problem in problems)


def test_an_option_needs_an_exit_condition_and_limitations():
    assert validate_preparedness_option(option(exit_condition=""))
    assert validate_preparedness_option(option(limitations=[]))


# ---------------------------------------------------------------------------
# Lane assessment assembly
# ---------------------------------------------------------------------------


def test_a_lane_assessment_must_carry_all_nine_domains():
    with pytest.raises(ValueError, match="all nine domains"):
        build_lane_assessment(
            {"lane_id": "LANE-OCEAN-TH-NEUR"},
            assessment_id="LAS-TEST",
            generated_at="2026-07-24T00:00:00Z",
            data_cutoff_at=None,
            domain_assessments=domain_set()[:8],
        )


def test_an_insufficient_domain_never_cites_a_threshold_rule():
    assessment = build_domain_assessment(
        "fuel_pressure",
        direction="insufficient_evidence",
        basis="no data",
        threshold_rule_id="FUEL-MOM-V1",
    )
    assert assessment["threshold_rule_id"] is None


def test_an_unknown_domain_is_rejected():
    with pytest.raises(ValueError, match="Unknown assessment domain"):
        build_domain_assessment("vibes", direction="stable", basis="x")


def test_a_lane_with_no_evidence_is_insufficient_not_routine():
    assert (
        attention_level(domain_set("insufficient_evidence"), active_operational_event_ids=[])
        == "insufficient_evidence"
    )


def test_deterioration_plus_an_open_event_is_elevated():
    domains = domain_set()
    domains[0]["direction"] = "deteriorating"
    assert attention_level(domains, active_operational_event_ids=["EVT-1"]) == "elevated"


def test_deterioration_alone_or_an_event_alone_is_watch():
    domains = domain_set()
    domains[0]["direction"] = "deteriorating"
    assert attention_level(domains, active_operational_event_ids=[]) == "watch"
    assert attention_level(domain_set(), active_operational_event_ids=["EVT-1"]) == "watch"


def test_quiet_and_evidenced_is_routine():
    assert attention_level(domain_set(), active_operational_event_ids=[]) == "routine"


# ---------------------------------------------------------------------------
# ChatGPT review package
# ---------------------------------------------------------------------------


def base_package():
    return build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[
            {
                "series_id": "container_freight_benchmark",
                "current_value": 2136.7,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            },
            {
                "series_id": "thailand_lsci",
                "current_value": None,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            },
        ],
        lane_status=[],
        events=[
            {
                "event_id": "EVT-1",
                "event_class": "direct_operational_event",
                "dataset": "current_publication",
                "conflicting_evidence": [],
            }
        ],
        # A genuinely qualifying evidence item, so these tests exercise the
        # rejection rules rather than tripping the provenance gate first.
        evidence=[
            {
                **manual_notice_evidence(evidence_id="EVD-1", event_id="EVT-1"),
                "scope_supported": "node",
            }
        ],
        previous_assessments=[],
        data_gaps=["no live source"],
    )


def base_output(**overrides):
    bound_to = base_package()
    out = {
        "package_id": "PKG-20260724-001",
        "methodology_version": "0.8",
        "produced_at": "2026-07-24T01:00:00Z",
        "model_reference": "human-run ChatGPT session",
        "input_package_sha256": bound_to["package_sha256"],
        "input_dataset": bound_to["dataset"],
        "input_package_purpose": bound_to["package_purpose"],
        "input_data_cutoff_at": bound_to["data_cutoff_at"],
        "input_source_cutoff": bound_to["source_cutoff"],
        "current_situation": {
            "current_direction": "insufficient_evidence",
            "current_disposition": "insufficient_evidence",
            "evidence_ids": [],
            "indicator_ids": [],
            "statement": "Coverage is insufficient and no lane can be assessed live.",
        },
        "key_changes": [],
        "lane_assessments": [],
        "verified_facts": [],
        "reported_claims": [],
        "analytical_inference": [],
        "conflicting_evidence": [],
        "transmission_chains": [],
        "observed_impacts": [],
        "potential_impacts": [],
        "scenarios": [outlook()],
        "evidence_references": [],
        "data_gaps": [],
        "conditional_preparedness_options": [],
        "highest_severity_claimed": "none",
    }
    out.update(overrides)
    return out


def test_the_package_excludes_and_says_what_it_excluded():
    package = base_package()
    assert package["exclusions_applied"]
    assert package["package_sha256"]
    assert package["output_instructions"]["prohibited_outputs"]


def test_the_package_separates_operational_events_from_drivers():
    package = base_package()
    assert len(package["active_operational_events"]) == 1
    assert package["external_drivers"] == []


def test_a_clean_output_passes():
    assert validate_output(base_output(), base_package(), registry=TEST_REGISTRY) == []


def test_unknown_evidence_is_rejected():
    problems = validate_output(base_output(evidence_references=["EVD-NOPE"]), base_package())
    assert any("unknown evidence IDs" in problem for problem in problems)


def test_citing_evidence_not_declared_in_references_is_rejected():
    output = base_output(
        verified_facts=[{"statement": "A notice was published.", "evidence_ids": ["EVD-1"]}]
    )
    problems = validate_output(output, base_package())
    assert any("not declared in evidence_references" in problem for problem in problems)


def test_a_mismatched_package_id_is_rejected():
    problems = validate_output(base_output(package_id="PKG-20260101-999"), base_package())
    assert any("does not match the input package" in problem for problem in problems)


def test_filling_a_gap_with_a_number_is_rejected():
    """thailand_lsci has no available value; stating one is missing-as-zero."""
    output = base_output(
        analytical_inference=[
            {"statement": "thailand_lsci stands at 44.7 index points.", "evidence_ids": []}
        ]
    )
    problems = validate_output(output, base_package())
    assert any("no available observation" in problem for problem in problems)


def test_presenting_a_proxy_as_a_quotation_is_rejected():
    output = base_output(
        verified_facts=[
            {"statement": "The average Thailand freight rate is elevated.", "evidence_ids": []}
        ]
    )
    problems = validate_output(output, base_package())
    assert any("shipment quotation" in problem for problem in problems)


def test_a_realtime_congestion_claim_without_operational_evidence_is_rejected():
    package = base_package()
    package["evidence_records"][0]["scope_supported"] = "global"
    assert not has_operational_condition_evidence(package, registry=TEST_REGISTRY)
    output = base_output(
        reported_claims=[
            {"statement": "The hub is congested with berth delays.", "evidence_ids": []}
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("real-time operational condition" in problem for problem in problems)


def test_a_congestion_claim_is_permitted_when_operational_evidence_exists():
    package = base_package()
    assert has_operational_condition_evidence(package, registry=TEST_REGISTRY)
    output = base_output(
        evidence_references=["EVD-1"],
        reported_claims=[
            {
                "statement": "The hub is congested per the authority notice.",
                "evidence_ids": ["EVD-1"],
            }
        ],
    )
    assert validate_output(output, package, registry=TEST_REGISTRY) == []


def test_causation_without_an_evidence_reference_is_rejected():
    output = base_output(
        analytical_inference=[
            {"statement": "Transit times lengthened because of the diversion.", "evidence_ids": []}
        ]
    )
    problems = validate_output(output, base_package())
    assert any("asserts causation" in problem for problem in problems)


def test_a_material_impact_without_a_transmission_mechanism_is_rejected():
    output = base_output(
        observed_impacts=[
            {
                "area": "cost",
                "status": "observed",
                "severity": "moderate",
                "description": "Cost pressure.",
                "transmission_mechanism": [],
                "evidence_ids": [],
                "evidence_strength": "B",
                "confidence": "low",
                "time_horizon": "1-4_weeks",
                "known_limitations": [],
            }
        ]
    )
    problems = validate_output(output, base_package())
    assert any("no transmission mechanism" in problem for problem in problems)


def test_the_platform_status_no_material_is_not_accepted_from_an_ai_output():
    output = base_output(
        observed_impacts=[
            {
                "area": "cost",
                "status": "no_material",
                "severity": "none",
                "description": "Nothing found.",
                "transmission_mechanism": [],
                "evidence_ids": [],
                "evidence_strength": "B",
                "confidence": "low",
                "time_horizon": "1-4_weeks",
                "known_limitations": [],
            }
        ]
    )
    problems = validate_output(output, base_package())
    assert any("not accepted from a returned AI assessment" in problem for problem in problems)


def test_an_incomplete_transmission_chain_in_the_output_is_rejected():
    output = base_output(
        transmission_chains=[
            {
                "subject": "x",
                "external_driver": "y",
                "operational_change": None,
                "logistics_mechanism": None,
                "observable_indicator": None,
                "outcome": None,
                "evidence_ids": [],
            }
        ]
    )
    problems = validate_output(output, base_package())
    assert any("incomplete chain" in problem for problem in problems)


def test_preparedness_overreach_in_the_output_is_rejected():
    output = base_output(
        conditional_preparedness_options=[
            option(description="You must reroute all cargo immediately.")
        ]
    )
    problems = validate_output(output, base_package())
    assert any("mandatory instruction phrasing" in problem for problem in problems)


def test_scenario_problems_in_the_output_are_surfaced():
    output = base_output(scenarios=[outlook(base_case=case(trigger_conditions=[]))])
    problems = validate_output(output, base_package())
    assert any("no trigger conditions" in problem for problem in problems)


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_high_and_critical_conclusions_require_human_review(severity):
    assert requires_human_review(base_output(highest_severity_claimed=severity))


@pytest.mark.parametrize("severity", ["none", "low", "moderate"])
def test_lower_severities_do_not_force_human_review(severity):
    assert not requires_human_review(base_output(highest_severity_claimed=severity))


def test_unavailable_series_are_identified():
    assert unavailable_series_ids(base_package()) == {"thailand_lsci"}


def test_the_output_contract_exists_and_the_package_points_at_it():
    package = base_package()
    path = ROOT / package["output_instructions"]["output_schema_path"]
    assert path.exists()
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["$id"] == "review_package_output.schema.json"


# ---------------------------------------------------------------------------
# WO-010-R3 §1 Output-to-package binding
# ---------------------------------------------------------------------------


def test_a_correctly_bound_output_has_no_schema_errors():
    assert schema_errors(base_output(), "review_package_output.schema.json") == []


@pytest.mark.parametrize("field_name", [field for field, _ in BINDING_FIELDS])
def test_an_output_missing_a_binding_field_fails_schema(field_name):
    output = base_output()
    del output[field_name]
    errors = schema_errors(output, "review_package_output.schema.json")
    assert any(field_name in error for error in errors), errors


def test_an_invalid_format_hash_fails_schema():
    output = base_output(input_package_sha256="not-a-valid-hash")
    errors = schema_errors(output, "review_package_output.schema.json")
    assert any("input_package_sha256" in error for error in errors), errors


def test_an_unrecognised_dataset_value_fails_schema():
    output = base_output(input_dataset="not_a_real_dataset")
    errors = schema_errors(output, "review_package_output.schema.json")
    assert any("input_dataset" in error for error in errors), errors


def test_an_unrecognised_purpose_value_fails_schema():
    output = base_output(input_package_purpose="not_a_real_purpose")
    errors = schema_errors(output, "review_package_output.schema.json")
    assert any("input_package_purpose" in error for error in errors), errors


def test_a_missing_binding_field_is_rejected_by_binding_problems():
    output = base_output()
    del output["input_package_sha256"]
    problems = binding_problems(output, base_package())
    assert any("missing required binding field 'input_package_sha256'" in item for item in problems)


def test_a_different_hash_is_rejected_by_binding_problems():
    output = base_output(input_package_sha256="d" * 64)
    problems = binding_problems(output, base_package())
    assert any("input_package_sha256" in item and "does not match" in item for item in problems), (
        problems
    )


def test_a_different_cutoff_is_rejected_by_binding_problems():
    output = base_output(input_data_cutoff_at="2026-06-01T00:00:00Z")
    problems = binding_problems(output, base_package())
    assert any("input_data_cutoff_at" in item and "does not match" in item for item in problems), (
        problems
    )


def test_a_correctly_bound_output_has_no_binding_problems():
    assert binding_problems(base_output(), base_package()) == []


# ---------------------------------------------------------------------------
# WO-010-R3 §2 Structured analytical support references (indicator_ids)
# ---------------------------------------------------------------------------


def _package_with_indicators(key_indicators):
    return build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=key_indicators,
        lane_status=[],
        events=[],
        evidence=[],
        previous_assessments=[],
        data_gaps=[],
    )


def test_referencing_an_unknown_indicator_id_is_rejected():
    output = base_output(
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "insufficient_evidence",
                "summary": "x",
                "evidence_ids": [],
                "indicator_ids": ["NOT_A_REAL_SERIES"],
                "confidence": "low",
                "data_gaps": [],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("unknown indicator IDs" in item for item in problems), problems


def test_a_transmission_chain_citing_an_unknown_indicator_is_rejected():
    output = base_output(
        transmission_chains=[
            {
                "subject": "x",
                "external_driver": "y",
                "operational_change": None,
                "logistics_mechanism": None,
                "observable_indicator": None,
                "outcome": None,
                "evidence_ids": [],
                "indicator_ids": ["NOT_A_REAL_SERIES"],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("unknown indicator IDs" in item for item in problems), problems


def test_referencing_a_fixture_origin_indicator_is_rejected():
    package = _package_with_indicators(
        [
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "synthetic_test_fixture",
            }
        ]
    )
    output = base_output(
        verified_facts=[
            {
                "statement": "Freight benchmark trend supports this.",
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "cannot support a current claim" in item and "container_freight_benchmark" in item
        for item in problems
    ), problems


def test_referencing_a_non_current_dataset_indicator_is_rejected():
    package = _package_with_indicators(
        [
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "technical_demo",
                "evidence_origin": "live_retrieved",
            }
        ]
    )
    output = base_output(
        analytical_inference=[
            {
                "statement": "x",
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("cannot support a current claim" in item for item in problems), problems


def test_referencing_an_eligible_indicator_raises_no_indicator_problem():
    output = base_output(
        reported_claims=[
            {
                "statement": "x",
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("indicator" in item.lower() for item in problems), problems


# ---------------------------------------------------------------------------
# WO-010-R3 §3 Zero-evidence disposition enforced structurally
# ---------------------------------------------------------------------------


def _zero_support_package():
    return build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[],
        lane_status=[],
        events=[],
        evidence=[],
        previous_assessments=[],
        data_gaps=["no live source"],
    )


def _zero_support_output(**overrides):
    package = _zero_support_package()
    out = {
        "package_id": "PKG-20260724-001",
        "methodology_version": "0.8",
        "produced_at": "2026-07-24T01:00:00Z",
        "model_reference": "human-run ChatGPT session",
        "input_package_sha256": package["package_sha256"],
        "input_dataset": package["dataset"],
        "input_package_purpose": package["package_purpose"],
        "input_data_cutoff_at": package["data_cutoff_at"],
        "input_source_cutoff": package["source_cutoff"],
        "current_situation": {
            "current_direction": "insufficient_evidence",
            "current_disposition": "insufficient_evidence",
            "evidence_ids": [],
            "indicator_ids": [],
            "statement": "Coverage is insufficient; no qualified evidence or indicator exists.",
        },
        "key_changes": [],
        "lane_assessments": [
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "insufficient_evidence",
                "summary": "No qualified support.",
                "evidence_ids": [],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": ["no coverage"],
            }
        ],
        "verified_facts": [],
        "reported_claims": [],
        "analytical_inference": [],
        "conflicting_evidence": [],
        "transmission_chains": [],
        "observed_impacts": [],
        "potential_impacts": [],
        "scenarios": [outlook()],
        "evidence_references": [],
        "data_gaps": ["no coverage"],
        "conditional_preparedness_options": [
            {
                "option_type": "monitor",
                "description": "Monitor for a qualified source.",
                "applicable_to": "all lanes",
                "trigger_condition": "A source becomes qualified.",
                "possible_benefit": "Coverage improves.",
                "tradeoffs": [],
                "limitations": ["Purely a data-coverage action; not an operational response."],
                "exit_condition": "N/A",
                "evidence_basis": [],
                "is_data_coverage_action": True,
            }
        ],
        "highest_severity_claimed": "none",
    }
    out.update(overrides)
    return out


def test_zero_evidence_baseline_passes():
    assert (
        validate_output(_zero_support_output(), _zero_support_package(), registry=TEST_REGISTRY)
        == []
    )


def test_zero_evidence_lane_direction_other_than_insufficient_is_rejected():
    output = _zero_support_output()
    output["lane_assessments"][0]["direction"] = "deteriorating"
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any("asserted with zero eligible evidence" in item for item in problems), problems


def test_zero_evidence_stable_lane_direction_is_also_rejected():
    output = _zero_support_output()
    output["lane_assessments"][0]["direction"] = "stable"
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any("asserted with zero eligible evidence" in item for item in problems), problems


def test_zero_evidence_current_situation_with_a_directional_claim_is_rejected():
    output = _zero_support_output(
        current_situation={
            "current_direction": "deteriorating",
            "current_disposition": "assessed",
            "evidence_ids": [],
            "indicator_ids": [],
            "statement": "Trade is deteriorating across every lane.",
        }
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any(
        "current_direction" in item and "insufficient_evidence" in item for item in problems
    ), problems
    assert any("current_disposition" in item for item in problems), problems


def test_zero_evidence_current_situation_without_a_coverage_gap_phrase_is_rejected():
    """Structurally correct (insufficient_evidence/insufficient_evidence,
    no refs) but the statement itself asserts something else -- the
    secondary prose check catches the contradiction the structural fields
    alone would miss."""
    output = _zero_support_output(
        current_situation={
            "current_direction": "insufficient_evidence",
            "current_disposition": "insufficient_evidence",
            "evidence_ids": [],
            "indicator_ids": [],
            "statement": "Trade is deteriorating across every lane.",
        }
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any(
        "statement does not state an insufficient-coverage position" in item for item in problems
    ), problems


def test_zero_evidence_current_situation_citing_support_is_rejected():
    output = _zero_support_output(
        current_situation={
            "current_direction": "insufficient_evidence",
            "current_disposition": "insufficient_evidence",
            "evidence_ids": ["EVD-1"],
            "indicator_ids": [],
            "statement": "Coverage is insufficient.",
        }
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any(
        "current_situation" in item and "cites support references" in item for item in problems
    ), problems


def test_zero_evidence_key_change_with_a_non_coverage_type_is_rejected():
    output = _zero_support_output(
        key_changes=[
            {
                "statement": "Congestion rose sharply.",
                "change_type": "direction_change",
                "evidence_ids": [],
                "indicator_ids": [],
                "comparison_period": None,
                "known_limitations": [],
            }
        ]
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any("key_changes[0]" in item and "coverage_change" in item for item in problems), (
        problems
    )


def test_zero_evidence_reported_claim_is_rejected():
    output = _zero_support_output(
        reported_claims=[
            {"statement": "Congestion is rising.", "evidence_ids": [], "indicator_ids": []}
        ]
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any("reported_claims is non-empty" in item for item in problems), problems


def test_zero_evidence_analytical_inference_is_rejected():
    output = _zero_support_output(
        analytical_inference=[
            {"statement": "Delays are likely.", "evidence_ids": [], "indicator_ids": []}
        ]
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any("analytical_inference is non-empty" in item for item in problems), problems


def test_zero_evidence_directional_scenario_is_rejected():
    output = _zero_support_output(
        scenarios=[outlook(deterioration_case=case(narrative="Conditions worsen materially."))]
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any("base, deterioration and improvement cases differ" in item for item in problems), (
        problems
    )


def test_zero_evidence_operational_preparedness_option_is_rejected():
    output = _zero_support_output(
        conditional_preparedness_options=[
            {
                "option_type": "near_term",
                "description": "Reroute cargo.",
                "applicable_to": "all lanes",
                "trigger_condition": "Congestion is observed.",
                "possible_benefit": "Avoids delay.",
                "tradeoffs": ["Cost"],
                "limitations": [],
                "exit_condition": "Congestion clears.",
                "evidence_basis": [],
            }
        ]
    )
    problems = validate_output(output, _zero_support_package(), registry=TEST_REGISTRY)
    assert any(
        "only a 'monitor' option explicitly marked is_data_coverage_action is permitted" in item
        for item in problems
    ), problems


# ---------------------------------------------------------------------------
# WO-010-R3 §4 Support adequacy, once support exists
# ---------------------------------------------------------------------------


def test_lane_direction_without_any_support_reference_is_rejected():
    output = base_output(
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "stable",
                "summary": "x",
                "evidence_ids": [],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": [],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("cites no evidence_id or indicator_id to support it" in item for item in problems), (
        problems
    )


def test_lane_direction_on_discovery_only_evidence_is_rejected():
    package = build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[],
        lane_status=[],
        events=[],
        evidence=[
            {**manual_notice_evidence(evidence_id="EVD-1"), "evidence_role": "discovery_only"}
        ],
        previous_assessments=[],
        data_gaps=[],
    )
    output = base_output(
        evidence_references=["EVD-1"],
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "deteriorating",
                "summary": "x",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": [],
            }
        ],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("discovery-only evidence" in item for item in problems), problems


def test_a_global_or_proxy_indicator_cannot_support_a_verified_fact():
    package = _package_with_indicators(
        [
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
                "geographic_scope": "global_or_proxy",
            }
        ]
    )
    output = base_output(
        verified_facts=[
            {
                "statement": "Thailand freight rates are rising.",
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("Thailand-specific verified_fact" in item for item in problems), problems


def test_an_operational_condition_impact_needs_evidence_not_only_an_indicator():
    package = _package_with_indicators(
        [
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            }
        ]
    )
    output = base_output(
        observed_impacts=[
            {
                "area": "capacity",
                "status": "observed",
                "severity": "moderate",
                "description": "Capacity is reduced.",
                "transmission_mechanism": ["x"],
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
                "evidence_strength": "C",
                "confidence": "low",
                "time_horizon": "0-7_days",
                "known_limitations": [],
            }
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "a numeric indicator alone cannot establish congestion" in item for item in problems
    ), problems


def test_high_severity_impact_needs_primary_grade_evidence():
    output = base_output(
        observed_impacts=[
            {
                "area": "capacity",
                "status": "observed",
                "severity": "high",
                "description": "x",
                "transmission_mechanism": ["x"],
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
                "evidence_strength": "C",
                "confidence": "medium",
                "time_horizon": "0-7_days",
                "known_limitations": [],
            }
        ],
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("requires primary-grade evidence" in item for item in problems), problems


def test_a_populated_transmission_chain_link_needs_support():
    output = base_output(
        transmission_chains=[
            {
                "subject": "Thailand exports",
                "external_driver": "A storm.",
                "operational_change": None,
                "logistics_mechanism": None,
                "observable_indicator": None,
                "outcome": None,
                "evidence_ids": [],
                "indicator_ids": [],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "populated links cite no evidence_id or indicator_id" in item for item in problems
    ), problems


# ---------------------------------------------------------------------------
# WO-010-R4 §3 Scenario support validation
# ---------------------------------------------------------------------------


def test_a_scenario_citing_an_unknown_evidence_id_is_rejected():
    output = base_output(scenarios=[outlook(base_case=case(evidence_ids=["EVD-NOPE"]))])
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("scenarios[0]" in item and "unknown evidence IDs" in item for item in problems), (
        problems
    )


def test_a_scenario_citing_an_unknown_indicator_id_is_rejected():
    output = base_output(scenarios=[outlook(base_case=case(indicator_ids=["NOT_A_REAL_SERIES"]))])
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("scenarios[0]" in item and "unknown indicator IDs" in item for item in problems), (
        problems
    )


def test_a_differentiated_scenario_case_with_no_support_is_rejected():
    output = base_output(
        scenarios=[
            outlook(
                base_case=case(narrative="Conditions stay as they are."),
                deterioration_case=case(narrative="Conditions worsen materially."),
            )
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "base_case" in item and "cites no evidence_id or indicator_id" in item for item in problems
    ), problems


def test_a_differentiated_scenario_with_every_case_supported_passes():
    output = base_output(
        evidence_references=["EVD-1"],
        scenarios=[
            outlook(
                subject_type="thailand_ocean",
                base_case=case(
                    narrative="Conditions stay as they are.", indicator_ids=["thailand_lsci"]
                ),
                deterioration_case=case(
                    narrative="Conditions worsen materially.",
                    evidence_ids=["EVD-1"],
                    aggregation_basis=(
                        "This node's notice is treated as representative of Thailand-wide "
                        "conditions for this case."
                    ),
                ),
                improvement_case=case(
                    narrative="Conditions improve.", indicator_ids=["thailand_lsci"]
                ),
            )
        ],
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("scenarios[0]" in item for item in problems), problems


def test_a_lane_scoped_scenario_cannot_cite_an_indicator_unrelated_to_that_lane():
    package = build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            }
        ],
        lane_status=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "dataset": "current_publication",
                "overall_direction": "insufficient_evidence",
                "attention_level": "insufficient_evidence",
                "domain_directions": {},
                "domain_indicator_ids": {},
                "indicator_ids": [],
                "active_event_ids": [],
                "external_driver_event_ids": [],
                "chokepoint_exposure": [],
                "data_gaps": [],
            }
        ],
        events=[],
        evidence=[],
        previous_assessments=[],
        data_gaps=[],
    )
    output = base_output(
        scenarios=[
            outlook(
                subject_type="lane",
                subject_id="LANE-OCEAN-TH-NEUR",
                base_case=case(
                    narrative="Conditions stay as they are.",
                    indicator_ids=["container_freight_benchmark"],
                ),
                deterioration_case=case(
                    narrative="Conditions worsen materially.",
                    indicator_ids=["container_freight_benchmark"],
                ),
            )
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "scenarios[0]" in item and "does not associate with it" in item for item in problems
    ), problems


def test_a_lane_assessment_cannot_cite_an_indicator_unrelated_to_that_lane():
    """One eligible package indicator misused for an unrelated conclusion
    (WO-010-R4 §10), at the ``lane_assessments`` level rather than the
    scenario level -- ``container_freight_benchmark`` is eligible in the
    package, but this lane's own ``lane_status`` entry never associated it,
    so citing it here is rejected on the same basis."""
    package = build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            }
        ],
        lane_status=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "dataset": "current_publication",
                "overall_direction": "insufficient_evidence",
                "attention_level": "insufficient_evidence",
                "domain_directions": {},
                "domain_indicator_ids": {},
                "indicator_ids": [],
                "active_event_ids": [],
                "external_driver_event_ids": [],
                "chokepoint_exposure": [],
                "data_gaps": [],
            }
        ],
        events=[],
        evidence=[],
        previous_assessments=[],
        data_gaps=[],
    )
    output = base_output(
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "stable",
                "summary": "x",
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
                "confidence": "low",
                "data_gaps": [],
            }
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "lane_assessments[0]" in item and "does not associate with it" in item for item in problems
    ), problems


# ---------------------------------------------------------------------------
# WO-010-R4 §1 Support adequacy applies claim-by-claim, even when the package
# holds real support -- eligible support elsewhere is never support for an
# unrelated claim that cites none of its own.
# ---------------------------------------------------------------------------


def test_a_verified_fact_with_no_support_in_a_supported_package_is_rejected():
    output = base_output(
        verified_facts=[
            {"statement": "Congestion is rising.", "evidence_ids": [], "indicator_ids": []}
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "verified_facts[0]" in item and "cites no evidence_id" in item for item in problems
    ), problems


def test_a_key_change_with_no_support_in_a_supported_package_is_rejected():
    output = base_output(
        key_changes=[
            {
                "statement": "Congestion rose sharply.",
                "change_type": "direction_change",
                "evidence_ids": [],
                "indicator_ids": [],
                "comparison_period": None,
                "known_limitations": [],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any("key_changes[0]" in item and "cites no evidence_id" in item for item in problems), (
        problems
    )


def test_a_directional_current_situation_with_no_support_in_a_supported_package_is_rejected():
    output = base_output(
        current_situation={
            "current_direction": "deteriorating",
            "current_disposition": "assessed",
            "evidence_ids": [],
            "indicator_ids": [],
            "statement": "Trade is deteriorating.",
        }
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "current_situation" in item and "cites no evidence_id" in item for item in problems
    ), problems


def test_a_preparedness_option_citing_a_fixture_origin_indicator_is_rejected():
    package = _package_with_indicators(
        [
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "synthetic_test_fixture",
            }
        ]
    )
    output = base_output(
        conditional_preparedness_options=[
            {
                "option_type": "near_term",
                "description": "Reroute cargo.",
                "applicable_to": "all lanes",
                "trigger_condition": "The benchmark crosses a threshold.",
                "possible_benefit": "Avoids delay.",
                "tradeoffs": ["Cost"],
                "limitations": [],
                "exit_condition": "The benchmark normalises.",
                "evidence_basis": [],
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item and "cannot support a current claim" in item
        for item in problems
    ), problems


# ---------------------------------------------------------------------------
# WO-010-R4 §10 Positive tests
# ---------------------------------------------------------------------------


def test_an_indicator_backed_trend_statement_passes():
    output = base_output(
        verified_facts=[
            {
                "statement": "The container freight benchmark is at its current level.",
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("verified_facts[0]" in item for item in problems), problems


def test_an_evidence_backed_operational_claim_passes():
    output = base_output(
        evidence_references=["EVD-1"],
        reported_claims=[
            {
                "statement": "A manual notice was recorded for this event.",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
            }
        ],
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("reported_claims[0]" in item for item in problems), problems


def test_a_mixed_evidence_and_indicator_inference_passes():
    output = base_output(
        evidence_references=["EVD-1"],
        analytical_inference=[
            {
                "statement": "Both the notice and the benchmark point the same way.",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": ["container_freight_benchmark"],
            }
        ],
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("analytical_inference[0]" in item for item in problems), problems


def test_a_coverage_only_current_output_passes():
    assert (
        validate_output(_zero_support_output(), _zero_support_package(), registry=TEST_REGISTRY)
        == []
    )


def test_a_support_linked_preparedness_monitoring_option_passes():
    output = base_output(
        conditional_preparedness_options=[
            {
                "option_type": "monitor",
                "description": "Watch the freight benchmark for a sustained move.",
                "applicable_to": "all lanes",
                "trigger_condition": "The benchmark moves materially from its current level.",
                "possible_benefit": "Earlier awareness of a directional change.",
                "tradeoffs": [],
                "limitations": [],
                "exit_condition": "The benchmark stabilises.",
                "evidence_basis": [],
                "evidence_ids": [],
                "indicator_ids": ["container_freight_benchmark"],
                "is_data_coverage_action": False,
            }
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("conditional_preparedness_options[0]" in item for item in problems), problems


# ---------------------------------------------------------------------------
# WO-010-R4 §4 Preparedness options bound to support
# ---------------------------------------------------------------------------


def test_an_operational_preparedness_option_with_no_support_is_rejected():
    output = base_output(conditional_preparedness_options=[option()])
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item
        and "cites no evidence_id or indicator_id" in item
        for item in problems
    ), problems


def test_a_monitor_data_coverage_option_needs_no_support():
    output = base_output(
        conditional_preparedness_options=[
            option(option_type="monitor", is_data_coverage_action=True)
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("conditional_preparedness_options[0]" in item for item in problems), problems


def test_a_preparedness_option_citing_an_unknown_evidence_id_is_rejected():
    output = base_output(conditional_preparedness_options=[option(evidence_ids=["EVD-NOPE"])])
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item and "unknown evidence IDs" in item
        for item in problems
    ), problems


def test_a_preparedness_option_citing_discovery_only_evidence_is_rejected():
    package = build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[],
        lane_status=[],
        events=[],
        evidence=[
            {**manual_notice_evidence(evidence_id="EVD-1"), "evidence_role": "discovery_only"}
        ],
        previous_assessments=[],
        data_gaps=[],
    )
    output = base_output(
        evidence_references=["EVD-1"],
        conditional_preparedness_options=[option(evidence_ids=["EVD-1"])],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item and "discovery-only evidence" in item
        for item in problems
    ), problems


def test_a_supported_operational_preparedness_option_passes():
    output = base_output(
        conditional_preparedness_options=[
            option(
                indicator_ids=["thailand_lsci"],
                support_basis="thailand_lsci shows sustained deterioration this period.",
            )
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert not any("conditional_preparedness_options[0]" in item for item in problems), problems


# ---------------------------------------------------------------------------
# WO-010-R5 §5/§6/§7: evidence relevance beyond ID eligibility
# ---------------------------------------------------------------------------


def _lane_status_entry(lane_id, **overrides):
    entry = {
        "lane_id": lane_id,
        "dataset": "current_publication",
        "overall_direction": "insufficient_evidence",
        "attention_level": "insufficient_evidence",
        "domain_directions": {},
        "domain_indicator_ids": {},
        "indicator_ids": [],
        "active_event_ids": [],
        "external_driver_event_ids": [],
        "chokepoint_exposure": [],
        "data_gaps": [],
        # WO-010-R6 §8: real lanes.json reference geography for every Thai
        # ocean lane used in these tests -- both test lanes genuinely
        # include Thailand, matching the committed reference data.
        "country_ids": ["TH"],
        "node_ids": [],
        "chokepoint_ids": [],
    }
    entry.update(overrides)
    return entry


def _two_lane_package(*, evidence_scope="facility", event_country_ids=()):
    """A package with two lanes: LANE-OCEAN-TH-NEUR (no linked evidence) and
    LANE-OCEAN-TH-JPKR (whose active_event_ids link it to EVT-1, the event
    EVD-1 is attached to)."""
    return build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[],
        lane_status=[
            _lane_status_entry("LANE-OCEAN-TH-NEUR"),
            _lane_status_entry("LANE-OCEAN-TH-JPKR", active_event_ids=["EVT-1"]),
        ],
        events=[
            {
                "event_id": "EVT-1",
                "event_class": "direct_operational_event",
                "country_ids": list(event_country_ids),
                "node_ids": [],
                "chokepoint_ids": [],
                "geography_ids": [],
                "modes": [],
                "lane_relevance": [],
            }
        ],
        evidence=[
            {
                **manual_notice_evidence(evidence_id="EVD-1", event_id="EVT-1"),
                "scope_supported": evidence_scope,
            }
        ],
        previous_assessments=[],
        data_gaps=[],
    )


def test_a_lane_assessment_cannot_cite_evidence_for_another_lane():
    package = _two_lane_package()
    output = base_output(
        evidence_references=["EVD-1"],
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "deteriorating",
                "summary": "x",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": [],
            }
        ],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "lane_assessments[0]" in item and "does not link to this lane" in item for item in problems
    ), problems


def test_a_node_scoped_notice_can_support_the_lane_the_reference_model_links_it_to():
    package = _two_lane_package(evidence_scope="node")
    output = base_output(
        evidence_references=["EVD-1"],
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-JPKR",
                "direction": "deteriorating",
                "summary": "x",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": [],
            }
        ],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert not any("lane_assessments[0]" in item for item in problems), problems


def test_thailand_wide_evidence_can_support_multiple_lanes():
    # WO-010-R6 §9: "country" scope is no longer an automatic pass -- this
    # evidence supports both lanes because its event genuinely names
    # Thailand and both test lanes' own reference geography includes
    # Thailand, not merely because its scope_supported says "country".
    package = _two_lane_package(evidence_scope="country", event_country_ids=["TH"])
    output = base_output(
        evidence_references=["EVD-1"],
        lane_assessments=[
            {
                "lane_id": "LANE-OCEAN-TH-NEUR",
                "direction": "deteriorating",
                "summary": "x",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": [],
            },
            {
                "lane_id": "LANE-OCEAN-TH-JPKR",
                "direction": "deteriorating",
                "summary": "x",
                "evidence_ids": ["EVD-1"],
                "indicator_ids": [],
                "confidence": "low",
                "data_gaps": [],
            },
        ],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert not any("lane_assessments" in item and "does not link" in item for item in problems), (
        problems
    )


def test_a_scenario_cannot_cite_evidence_for_another_lane():
    package = _two_lane_package()
    output = base_output(
        scenarios=[
            outlook(
                subject_type="lane",
                subject_id="LANE-OCEAN-TH-NEUR",
                base_case=case(narrative="Conditions stay as they are.", evidence_ids=["EVD-1"]),
                deterioration_case=case(
                    narrative="Conditions worsen materially.", evidence_ids=["EVD-1"]
                ),
            )
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "scenarios[0]" in item and "does not link to this lane" in item for item in problems
    ), problems


def test_a_thailand_wide_scenario_relying_on_a_facility_notice_needs_an_aggregation_basis():
    package = _two_lane_package()
    output = base_output(
        scenarios=[
            outlook(
                subject_type="thailand_ocean",
                subject_id="THAILAND",
                base_case=case(narrative="Conditions stay as they are.", evidence_ids=["EVD-1"]),
                deterioration_case=case(
                    narrative="Conditions worsen materially.", evidence_ids=["EVD-1"]
                ),
            )
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("scenarios[0]" in item and "aggregation_basis" in item for item in problems), (
        problems
    )


def test_a_preparedness_option_citing_geographically_unrelated_evidence_is_rejected():
    package = _two_lane_package()
    output = base_output(
        evidence_references=["EVD-1"],
        conditional_preparedness_options=[
            option(evidence_ids=["EVD-1"], applicable_lane_ids=["LANE-OCEAN-TH-NEUR"])
        ],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item and "relates to none of them" in item
        for item in problems
    ), problems


def test_a_lane_and_domain_compatible_preparedness_option_passes():
    package = build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[
            {
                "series_id": "container_freight_benchmark",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            }
        ],
        lane_status=[
            _lane_status_entry("LANE-OCEAN-TH-NEUR", indicator_ids=["container_freight_benchmark"])
        ],
        events=[],
        evidence=[],
        previous_assessments=[],
        data_gaps=[],
    )
    output = base_output(
        conditional_preparedness_options=[
            option(
                indicator_ids=["container_freight_benchmark"],
                applicable_lane_ids=["LANE-OCEAN-TH-NEUR"],
                applicable_domain_ids=["fuel_pressure"],
                support_basis="Freight benchmark trend supports monitoring this lane.",
            )
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert not any("conditional_preparedness_options[0]" in item for item in problems), problems


def test_a_cost_monitoring_option_citing_an_incompatible_indicator_is_rejected():
    package = build_input_package(
        package_id="PKG-20260724-001",
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[
            {
                "series_id": "thailand_lsci",
                "current_value": 1.0,
                "dataset": "current_publication",
                "evidence_origin": "live_retrieved",
            }
        ],
        lane_status=[],
        events=[],
        evidence=[],
        previous_assessments=[],
        data_gaps=[],
    )
    output = base_output(
        conditional_preparedness_options=[
            option(
                indicator_ids=["thailand_lsci"],
                applicable_domain_ids=["fuel_pressure"],
                support_basis="thailand_lsci trend.",
            )
        ]
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item and "no compatible indicator" in item
        for item in problems
    ), problems


def test_an_operational_contingency_option_needs_evidence_not_only_an_indicator():
    output = base_output(
        conditional_preparedness_options=[
            option(
                option_type="contingency",
                indicator_ids=["thailand_lsci"],
                support_basis="thailand_lsci trend.",
            )
        ]
    )
    problems = validate_output(output, base_package(), registry=TEST_REGISTRY)
    assert any(
        "conditional_preparedness_options[0]" in item
        and "cannot establish an operational condition" in item
        for item in problems
    ), problems
