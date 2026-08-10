"""Tests for analysis/attachment.py (WO-049 / Issue #92 item 4): the
minimal claim -> Development attachment path -- rules 3, 6 and 7 of design
part 1 Section 1.4 only.
"""

from __future__ import annotations

from analysis.attachment import decide_attachment, gate_matches


def _claim(**overrides) -> dict:
    base = {
        "claim_id": "CLM-20260810-0001",
        "assertion": {
            "subject_type": "node",
            "subject_ref": "NODE-SYNTH-NGT",
            "predicate": "berths_suspended",
            "object_value": None,
            "object_unit": None,
            "predicate_class": "berth_or_facility_availability",
        },
        "event_start_at": "2026-08-10T06:00:00Z",
        "event_end_at": None,
        "event_date_precision": "datetime",
        "node_ids": ["NODE-SYNTH-NGT"],
        "chokepoint_ids": [],
        "lane_ids": [],
        "country_ids": [],
    }
    base.update(overrides)
    return base


def _event(**overrides) -> dict:
    base = {
        "event_id": "EVT-20260810-001",
        "node_ids": ["NODE-SYNTH-NGT"],
        "chokepoint_ids": [],
        "event_date": "2026-08-10",
        "event_end_date": None,
        "operator_or_entity": "NODE-SYNTH-NGT",
        "claim_ids": ["CLM-EXISTING-0001"],
    }
    base.update(overrides)
    return base


def _existing_claim(**overrides) -> dict:
    base = {
        "claim_id": "CLM-EXISTING-0001",
        "assertion": {
            "subject_type": "node",
            "subject_ref": "NODE-SYNTH-NGT",
            "predicate": "berths_suspended",
            "object_value": None,
            "object_unit": None,
            "predicate_class": "berth_or_facility_availability",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# gate_matches (S2 AND S3 AND S4)
# ---------------------------------------------------------------------------


def test_gate_fails_without_shared_geography():
    claim = _claim(node_ids=["NODE-SYNTH-OTHER"])
    event = _event()
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    assert gate_matches(claim, event, claims_by_id) is False


def test_gate_fails_on_different_predicate_class_family():
    claim = _claim(
        assertion={
            "subject_type": "node",
            "subject_ref": "NODE-SYNTH-NGT",
            "predicate": "toll_changed",
            "object_value": None,
            "object_unit": None,
            "predicate_class": "tariff_or_fee",
        }
    )
    event = _event()
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    assert gate_matches(claim, event, claims_by_id) is False


def test_gate_fails_on_non_overlapping_time_window():
    claim = _claim(event_start_at="2026-01-01T00:00:00Z")
    event = _event()
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    assert gate_matches(claim, event, claims_by_id) is False


def test_gate_passes_when_all_three_hold():
    claim = _claim()
    event = _event()
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    assert gate_matches(claim, event, claims_by_id) is True


# ---------------------------------------------------------------------------
# decide_attachment
# ---------------------------------------------------------------------------


def test_rule_3_auto_attach_on_gate_plus_entity_match():
    claim = _claim()
    event = _event()
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    decision = decide_attachment(claim, [event], claims_by_id)
    assert decision.outcome == "auto_attach"
    assert decision.event_ids == ["EVT-20260810-001"]
    assert decision.merge_status == "matched_fingerprint"
    assert decision.rule_id == "rule_3"


def test_rule_3_does_not_fire_against_two_matching_candidates():
    claim = _claim()
    event_a = _event(event_id="EVT-20260810-001")
    event_b = _event(event_id="EVT-20260810-002")
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    decision = decide_attachment(claim, [event_a, event_b], claims_by_id)
    assert decision.outcome != "auto_attach"


def test_rule_6_auto_new_when_no_candidate_but_claim_has_geography():
    claim = _claim(node_ids=["NODE-SYNTH-OTHER"])
    event = _event()  # gate fails: different node
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    decision = decide_attachment(claim, [event], claims_by_id)
    assert decision.outcome == "auto_new"
    assert decision.event_ids == []
    assert decision.rule_id == "rule_6"


def test_rule_7_unattached_when_no_candidate_and_no_geography():
    claim = _claim(node_ids=[], chokepoint_ids=[], lane_ids=[], country_ids=[])
    decision = decide_attachment(claim, [], {})
    assert decision.outcome == "unattached"
    assert decision.event_ids == []
    assert decision.rule_id == "rule_7"


def test_rule_7_unattached_with_no_candidates_at_all_and_country_present_is_rule_6():
    """A claim with a country_id but no candidate Developments at all still
    gets rule 6 (auto_new), never rule 7 -- country_ids counts as geography
    just as node/chokepoint/lane do."""
    claim = _claim(node_ids=[], chokepoint_ids=[], lane_ids=[], country_ids=["TH"])
    decision = decide_attachment(claim, [], {})
    assert decision.outcome == "auto_new"


def test_predicate_class_agreement_alone_is_sufficient_for_rule_3():
    """S6 (predicate-class agreement) alone, without an entity match,
    still supports rule 3."""
    claim = _claim(
        assertion={
            "subject_type": "node",
            "subject_ref": "a completely different entity name",
            "predicate": "berths_suspended",
            "object_value": None,
            "object_unit": None,
            "predicate_class": "berth_or_facility_availability",
        }
    )
    event = _event(operator_or_entity="NODE-SYNTH-NGT")
    claims_by_id = {"CLM-EXISTING-0001": _existing_claim()}
    decision = decide_attachment(claim, [event], claims_by_id)
    assert decision.outcome == "auto_attach"
    assert decision.rule_id == "rule_3"
