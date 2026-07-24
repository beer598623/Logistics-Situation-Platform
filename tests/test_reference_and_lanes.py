"""Reference dimensions, lane membership and mode neutrality.

The last group of tests here is the extensibility guarantee: no shared entity
may encode an Ocean-only assumption, because the Air and Land modules reuse
these same records.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.reference import (
    THAILAND_MATERIAL,
    chokepoint_index,
    country_index,
    geography_index,
    implemented_modes,
    lane_by_id,
    lanes,
    lanes_for_chokepoint,
    lanes_for_country,
    lanes_for_mode,
    lanes_for_node,
    mode_index,
    node_index,
    planned_modes,
    resolve_lane_relevance,
    thailand_relationship_for_geography,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Lane set
# ---------------------------------------------------------------------------


def test_lane_count_is_within_the_authorised_range():
    assert 8 <= len(lanes()) <= 12


def test_every_lane_declares_the_resolution_it_actually_supports():
    for lane in lanes():
        assert lane["resolution"] in {"port_pair", "port_group", "country", "regional", "corridor"}


def test_no_lane_claims_port_pair_resolution_without_port_pair_data():
    """The platform holds no Thailand port-pair statistics, so no lane may claim it."""
    assert all(lane["resolution"] != "port_pair" for lane in lanes())


def test_every_lane_records_at_least_one_selection_criterion():
    for lane in lanes():
        assert lane["selection_evidence"], lane["lane_id"]


def test_selection_evidence_without_a_source_is_marked_as_inference_or_gap():
    for lane in lanes():
        for evidence in lane["selection_evidence"]:
            if evidence["source_reference"] is None:
                assert evidence["evidence_class"] in {
                    "analytical_inference",
                    "insufficient_evidence",
                }, f"{lane['lane_id']}: {evidence['criterion']}"


def test_every_lane_states_its_limitations():
    for lane in lanes():
        assert lane["known_limitations"], lane["lane_id"]


def test_unknown_lane_raises():
    with pytest.raises(KeyError, match="Unknown lane"):
        lane_by_id("LANE-DOES-NOT-EXIST")


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


def test_lane_membership_by_country():
    assert "LANE-OCEAN-TH-EASIA-CN" in lanes_for_country("CN")
    assert "LANE-OCEAN-TH-OCEANIA" not in lanes_for_country("CN")


def test_lane_membership_by_node():
    assert "LANE-OCEAN-TH-ASEAN-SG" in lanes_for_node("NODE-SGSIN")
    assert lanes_for_node("NODE-DOES-NOT-EXIST") == []


def test_chokepoint_linkage_reaches_every_exposed_lane():
    suez = lanes_for_chokepoint("CHK-SUEZ")
    assert {"LANE-OCEAN-TH-NEUR", "LANE-OCEAN-TH-MED", "LANE-OCEAN-TH-USEC"} <= set(suez)


def test_a_chokepoint_event_legitimately_touches_several_lanes():
    """Cross-lane linkage: one chokepoint, several lanes, each with its own basis."""
    matches = resolve_lane_relevance(chokepoint_ids=["CHK-MALACCA"])
    assert len(matches) >= 3
    for reasons in matches.values():
        assert any("chokepoint" in reason for reason in reasons)


def test_relevance_reasons_distinguish_a_chokepoint_match_from_a_country_match():
    matches = resolve_lane_relevance(country_ids=["SG"], chokepoint_ids=["CHK-SINGAPORE"])
    reasons = matches["LANE-OCEAN-TH-ASEAN-SG"]
    assert any("country SG" in reason for reason in reasons)
    assert any("chokepoint CHK-SINGAPORE" in reason for reason in reasons)


def test_an_event_touching_nothing_registered_resolves_to_no_lane():
    assert resolve_lane_relevance(country_ids=["ZZ"], node_ids=["NODE-NOWHERE"]) == {}


# ---------------------------------------------------------------------------
# Geography relevance
# ---------------------------------------------------------------------------


def test_thailand_relationship_walks_up_the_hierarchy():
    assert thailand_relationship_for_geography("GEO-ADM-TH-SONGKHLA") == "is_thailand"
    assert thailand_relationship_for_geography("GEO-CTY-CN") == "direct_trade_partner"
    assert thailand_relationship_for_geography("GEO-WTR-SUEZ") == "transit_or_chokepoint"


def test_unknown_geography_fails_closed():
    """An unrecognised place name must never default to relevant."""
    assert thailand_relationship_for_geography("GEO-NOWHERE") == "none_established"


def test_indirect_context_is_not_material_on_its_own():
    assert "indirect_context" not in THAILAND_MATERIAL


def test_every_country_with_a_relationship_records_why():
    for country in country_index().values():
        if country["thailand_relationship"] != "none_established":
            assert country["thailand_relevance_basis"], country["country_id"]


def test_reference_ids_are_unique():
    for index in (geography_index, country_index, node_index, chokepoint_index, mode_index):
        records = index()
        assert len(records) == len({key for key in records})


def test_every_lane_reference_resolves():
    geographies, countries, nodes, chokepoints = (
        geography_index(),
        country_index(),
        node_index(),
        chokepoint_index(),
    )
    for lane in lanes():
        for scope in ("origin_scope", "destination_scope"):
            for geography_id in lane[scope]["geography_ids"]:
                assert geography_id in geographies, f"{lane['lane_id']}: {geography_id}"
        assert all(country_id in countries for country_id in lane["country_ids"])
        assert all(node_id in nodes for node_id in lane.get("node_ids", []))
        assert all(cp in chokepoints for cp in lane.get("chokepoint_ids", []))


# ---------------------------------------------------------------------------
# Mode neutrality — the Air and Land extensibility guarantee
# ---------------------------------------------------------------------------


def test_the_mode_dimension_registers_air_road_rail_and_border():
    modes = mode_index()
    for mode_id in ("air", "road", "rail", "border", "inland_waterway"):
        assert mode_id in modes, mode_id
        assert modes[mode_id]["module_status"] == "planned"


def test_sea_is_the_only_implemented_operational_mode():
    assert "sea" in implemented_modes()
    assert {"air", "road", "rail", "border"} <= set(planned_modes())


def test_the_node_dimension_already_accepts_a_non_ocean_node():
    nodes = node_index()
    assert nodes["NODE-THBKKAIR"]["node_type"] == "airport"
    assert nodes["NODE-THBKKAIR"]["modes"] == ["air"]
    assert nodes["NODE-THSDK"]["node_type"] == "border_crossing"
    assert set(nodes["NODE-THSDK"]["modes"]) == {"road", "border"}


def test_the_chokepoint_dimension_already_accepts_a_non_ocean_corridor():
    corridor = chokepoint_index()["CHK-THSDK-BKH"]
    assert corridor["chokepoint_type"] == "border_corridor"
    assert set(corridor["modes"]) == {"road", "border"}


def test_the_lane_contract_is_mode_tagged_rather_than_ocean_hardcoded():
    """A lane carries its mode as data; adding an Air lane needs no schema change."""
    schema = json.loads((ROOT / "schemas/lane.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["mode"]["$ref"].endswith("transportMode")
    assert lanes_for_mode("sea")
    assert lanes_for_mode("air") == []  # no Air lane is delivered by WO-010


def test_shared_observation_contract_permits_every_mode():
    schema = json.loads(
        (ROOT / "schemas/observation_common.schema.json").read_text(encoding="utf-8")
    )
    permitted = set(schema["$defs"]["transportMode"]["enum"])
    assert {"sea", "air", "road", "rail", "border", "multimodal", "not_applicable"} <= permitted


def test_port_observation_contract_is_named_and_scoped_for_all_modes():
    schema = json.loads(
        (ROOT / "schemas/port_transport_observation.schema.json").read_text(encoding="utf-8")
    )
    metrics = set(schema["properties"]["metric"]["enum"])
    assert {"aircraft_movements", "border_crossings", "rail_movements"} <= metrics
