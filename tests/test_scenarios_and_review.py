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
from analysis.review_package import (
    build_input_package,
    has_operational_condition_evidence,
    requires_human_review,
    unavailable_series_ids,
    validate_output,
)

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
            {"series_id": "container_freight_benchmark", "current_value": 2136.7},
            {"series_id": "thailand_lsci", "current_value": None},
        ],
        lane_status=[],
        events=[
            {
                "event_id": "EVT-1",
                "event_class": "direct_operational_event",
                "conflicting_evidence": [],
            }
        ],
        evidence=[
            {
                "evidence_id": "EVD-1",
                "claim_type": "official_notice",
                "evidence_role": "confirming",
                "scope_supported": "node",
            }
        ],
        previous_assessments=[],
        data_gaps=["no live source"],
    )


def base_output(**overrides):
    out = {
        "package_id": "PKG-20260724-001",
        "methodology_version": "0.8",
        "produced_at": "2026-07-24T01:00:00Z",
        "model_reference": "human-run ChatGPT session",
        "current_situation": "Coverage is insufficient and no lane can be assessed live.",
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
    assert validate_output(base_output(), base_package()) == []


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
    assert not has_operational_condition_evidence(package)
    output = base_output(
        reported_claims=[
            {"statement": "The hub is congested with berth delays.", "evidence_ids": []}
        ]
    )
    problems = validate_output(output, package)
    assert any("real-time operational condition" in problem for problem in problems)


def test_a_congestion_claim_is_permitted_when_operational_evidence_exists():
    package = base_package()
    assert has_operational_condition_evidence(package)
    output = base_output(
        evidence_references=["EVD-1"],
        reported_claims=[
            {
                "statement": "The hub is congested per the authority notice.",
                "evidence_ids": ["EVD-1"],
            }
        ],
    )
    assert validate_output(output, package) == []


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
