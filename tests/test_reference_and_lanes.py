"""Reference dimensions, lane membership and mode neutrality.

The last group of tests here is the extensibility guarantee: no shared entity
may encode an Ocean-only assumption, because the Air and Land modules reuse
these same records.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

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


def test_ocean_lane_count_is_within_the_authorised_range():
    assert 8 <= len(lanes_for_mode("sea")) <= 12


def test_air_lane_count_is_within_the_authorised_range():
    """Air is deliberately smaller than Ocean: it has less structural
    grounding, and padding it under analytical_inference is the failure
    mode docs/air_lane_selection.md §1 exists to prevent."""
    assert 3 <= len(lanes_for_mode("air")) <= 6


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
    assert len(lanes_for_mode("air")) == 5  # WO-039 delivered the Air foundation


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


# ---------------------------------------------------------------------------
# Air foundation — WO-039
# ---------------------------------------------------------------------------


def _air_lanes():
    return [lane for lane in lanes() if lane["mode"] == "air"]


def test_every_air_lane_is_mode_tagged_provisional_and_undated():
    for lane in _air_lanes():
        assert lane["lane_id"].startswith("LANE-AIR-TH-")
        assert lane["status"] == "provisional"
        assert lane["data_period_used"] is None
    for lane in lanes():
        if lane["lane_id"].startswith("LANE-AIR-"):
            assert lane["mode"] == "air"


def test_no_air_lane_claims_a_resolution_it_does_not_have():
    for lane in _air_lanes():
        assert lane["resolution"] in {"country", "regional", "corridor"}
        assert lane["resolution"] not in {"port_pair", "port_group"}
    schema = json.loads((ROOT / "schemas/lane.schema.json").read_text(encoding="utf-8"))
    assert "airport_pair" not in schema["properties"]["resolution"]["enum"]


def test_every_air_lane_states_the_no_ranking_and_no_airport_pair_limitations():
    for lane in _air_lanes():
        limitations = [item.lower() for item in lane["known_limitations"]]
        assert any("no quantitative" in item for item in limitations)
        assert any("airport-pair" in item for item in limitations)


def test_no_air_lane_claims_a_measured_ranking():
    for lane in _air_lanes():
        for item in lane["selection_evidence"]:
            if item["criterion"] == "trade_value_or_volume":
                assert item["evidence_class"] == "insufficient_evidence"
            if item["source_reference"] is None:
                assert item["evidence_class"] in {"analytical_inference", "insufficient_evidence"}


def test_air_chokepoint_exposure_is_inference_not_verified_fact():
    for lane in _air_lanes():
        for item in lane["selection_evidence"]:
            if item["criterion"] == "chokepoint_exposure":
                assert item["evidence_class"] == "analytical_inference"


def test_no_air_lane_cites_an_unusable_air_candidate_as_a_source_reference():
    unusable = {
        "air-freight-pass",
        "aerothai",
        "datagov.mot.go.th",
        "aot_traffic",
        "airports-dataset",
        "caat",
    }
    for lane in _air_lanes():
        for item in lane["selection_evidence"]:
            reference = (item["source_reference"] or "").lower()
            assert not any(term in reference for term in unusable)


def test_no_air_lane_uses_superlative_ranking_language():
    superlatives = {"largest", "busiest", "top ", "main ", "most important", "principal", "primary"}
    for lane in _air_lanes():
        for item in lane["selection_evidence"]:
            statement = item["statement"].lower()
            assert not any(term in statement for term in superlatives)


def test_the_airspace_chokepoint_is_registered_and_air_only():
    chokepoint = chokepoint_index()["CHK-SASIA-AIRSPACE"]
    assert chokepoint["chokepoint_type"] == "airspace"
    assert chokepoint["modes"] == ["air"]
    assert chokepoint["operating_authority"] is None
    assert chokepoint["authority_notice_source_ids"] == []
    assert chokepoint["thailand_relationship"] == "transit_or_chokepoint"
    assert chokepoint["known_limitations"]


def test_only_the_europe_air_lane_transits_the_airspace_chokepoint():
    assert lanes_for_chokepoint("CHK-SASIA-AIRSPACE") == ["LANE-AIR-TH-EUR"]


def test_every_air_lane_anchors_only_on_registered_air_nodes():
    nodes = node_index()
    for lane in _air_lanes():
        assert lane["node_ids"] == ["NODE-THBKKAIR"]
        for node_id in lane["node_ids"]:
            assert "air" in nodes[node_id]["modes"]


def test_no_ocean_lane_gained_an_air_reference_record():
    for lane in lanes():
        if lane["mode"] == "sea":
            assert "NODE-THBKKAIR" not in lane.get("node_ids", [])
            assert "CHK-SASIA-AIRSPACE" not in lane.get("chokepoint_ids", [])


def test_lane_relevance_respects_the_event_modes():
    sea_only = resolve_lane_relevance(country_ids=["TH"], modes=["sea"])
    assert sea_only
    assert all(lane_by_id(lane_id)["mode"] == "sea" for lane_id in sea_only)

    air_only = resolve_lane_relevance(country_ids=["TH"], modes=["air"])
    assert air_only
    assert all(lane_by_id(lane_id)["mode"] == "air" for lane_id in air_only)

    multimodal = resolve_lane_relevance(country_ids=["TH"], modes=["sea", "road", "multimodal"])
    assert not any(lane_by_id(lane_id)["mode"] == "air" for lane_id in multimodal)

    mode_blind = resolve_lane_relevance(country_ids=["TH"])
    assert any(lane_by_id(lane_id)["mode"] == "sea" for lane_id in mode_blind)
    assert any(lane_by_id(lane_id)["mode"] == "air" for lane_id in mode_blind)


def test_the_air_module_stays_planned_while_no_air_source_is_enabled():
    assert mode_index()["air"]["module_status"] == "planned"
    assert "air" not in implemented_modes()


def test_no_air_reference_record_names_a_registered_source():
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    registered_ids = {source["id"] for source in registry["sources"]}
    for lane in _air_lanes():
        for item in lane["selection_evidence"]:
            assert item["source_reference"] not in registered_ids
    chokepoint = chokepoint_index()["CHK-SASIA-AIRSPACE"]
    assert not set(chokepoint["authority_notice_source_ids"]) & registered_ids


# ---------------------------------------------------------------------------
# Land foundation (Road, Rail, Border) — WO-041
# ---------------------------------------------------------------------------

_LAND_MODES = {"road", "rail", "border"}
_LAND_CHOKEPOINTS = ("CHK-THSDK-BKH", "CHK-THNKI-TNL")


def _land_lanes():
    return [lane for lane in lanes() if lane["mode"] in _LAND_MODES]


def test_every_land_lane_is_mode_tagged_provisional_and_undated():
    for lane in _land_lanes():
        assert lane["mode"] in _LAND_MODES
        assert lane["status"] == "provisional"
        assert lane["data_period_used"] is None
    for lane in lanes():
        if lane["lane_id"].startswith(("LANE-ROAD-", "LANE-RAIL-", "LANE-BORDER-")):
            assert lane["mode"] in _LAND_MODES


def test_no_land_lane_claims_a_resolution_it_does_not_have():
    for lane in _land_lanes():
        assert lane["resolution"] == "corridor"
    schema = json.loads((ROOT / "schemas/lane.schema.json").read_text(encoding="utf-8"))
    resolution_enum = set(schema["properties"]["resolution"]["enum"])
    assert resolution_enum == {"port_pair", "port_group", "country", "regional", "corridor"}


def test_every_land_lane_states_the_no_ranking_limitation():
    for lane in _land_lanes():
        limitations = [item.lower() for item in lane["known_limitations"]]
        assert any("no quantitative" in item for item in limitations)


def test_no_land_lane_claims_a_measured_ranking():
    for lane in _land_lanes():
        for item in lane["selection_evidence"]:
            if item["criterion"] == "trade_value_or_volume":
                assert item["evidence_class"] == "insufficient_evidence"
            if item["source_reference"] is None:
                assert item["evidence_class"] in {"analytical_inference", "insufficient_evidence"}


def test_land_chokepoint_exposure_is_inference_not_verified_fact():
    for lane in _land_lanes():
        for item in lane["selection_evidence"]:
            if item["criterion"] == "chokepoint_exposure":
                assert item["evidence_class"] == "analytical_inference"


def test_no_land_lane_claims_a_source_backed_criterion():
    for lane in _land_lanes():
        criteria = {item["criterion"] for item in lane["selection_evidence"]}
        assert "source_backed_analysis_support" not in criteria


def test_the_land_chokepoints_are_registered_and_land_only():
    chokepoints = chokepoint_index()
    sadao = chokepoints["CHK-THSDK-BKH"]
    assert sadao["chokepoint_type"] == "border_corridor"
    assert set(sadao["modes"]) <= _LAND_MODES
    assert sadao["authority_notice_source_ids"] == []

    gauge_break = chokepoints["CHK-THNKI-TNL"]
    assert gauge_break["chokepoint_type"] == "rail_gauge_break"
    assert set(gauge_break["modes"]) <= _LAND_MODES
    assert gauge_break["operating_authority"] is None
    assert gauge_break["authority_notice_source_ids"] == []
    assert gauge_break["known_limitations"]


def test_only_the_relevant_lanes_transit_each_land_chokepoint():
    assert set(lanes_for_chokepoint("CHK-THSDK-BKH")) == {
        "LANE-ROAD-TH-MY",
        "LANE-BORDER-TH-CROSSINGS",
    }
    assert set(lanes_for_chokepoint("CHK-THNKI-TNL")) == {
        "LANE-RAIL-TH-LA",
        "LANE-BORDER-TH-CROSSINGS",
    }


def test_every_land_lane_anchors_only_on_registered_land_nodes():
    nodes = node_index()
    for lane in _land_lanes():
        assert lane["node_ids"], lane["lane_id"]
        for node_id in lane["node_ids"]:
            assert set(nodes[node_id]["modes"]) & _LAND_MODES, lane["lane_id"]


def test_no_ocean_or_air_lane_gained_a_land_reference_record():
    for lane in lanes():
        if lane["mode"] in {"sea", "air"}:
            assert not set(lane.get("node_ids", [])) & {
                "NODE-THNKI",
                "NODE-THARY",
                "NODE-THMST",
                "NODE-THLKB",
            }
            assert not set(lane.get("chokepoint_ids", [])) & set(_LAND_CHOKEPOINTS)


def test_lane_relevance_respects_land_event_modes():
    road_only = resolve_lane_relevance(country_ids=["TH"], modes=["road"])
    assert road_only
    assert all(lane_by_id(lane_id)["mode"] == "road" for lane_id in road_only)

    rail_only = resolve_lane_relevance(country_ids=["TH"], modes=["rail"])
    assert rail_only
    assert all(lane_by_id(lane_id)["mode"] == "rail" for lane_id in rail_only)

    border_only = resolve_lane_relevance(country_ids=["TH"], modes=["border"])
    assert border_only
    assert all(lane_by_id(lane_id)["mode"] == "border" for lane_id in border_only)

    sea_only = resolve_lane_relevance(country_ids=["TH"], modes=["sea", "multimodal"])
    assert not any(lane_by_id(lane_id)["mode"] in _LAND_MODES for lane_id in sea_only)

    mode_blind = resolve_lane_relevance(country_ids=["TH"])
    assert any(lane_by_id(lane_id)["mode"] == "road" for lane_id in mode_blind)


def test_the_three_new_country_geographies_resolve():
    geographies = geography_index()
    for geo_id, country_id in (
        ("GEO-CTY-KH", "KH"),
        ("GEO-CTY-LA", "LA"),
        ("GEO-CTY-MM", "MM"),
    ):
        record = geographies[geo_id]
        assert record["level"] == "country"
        assert record["parent_geography_id"] == "GEO-RGN-SEASIA"
        assert record["country_ids"] == [country_id]
        assert record["thailand_relationship"] == "direct_trade_partner"


def test_road_rail_and_border_modules_stay_planned_while_no_source_is_enabled():
    modes = mode_index()
    for mode_id in ("road", "rail", "border"):
        assert modes[mode_id]["module_status"] == "planned"
        assert mode_id not in implemented_modes()


def test_no_land_reference_record_names_a_registered_source():
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    registered_ids = {source["id"] for source in registry["sources"]}
    for lane in _land_lanes():
        for item in lane["selection_evidence"]:
            assert item["source_reference"] not in registered_ids
    for chokepoint_id in _LAND_CHOKEPOINTS:
        chokepoint = chokepoint_index()[chokepoint_id]
        assert not set(chokepoint["authority_notice_source_ids"]) & registered_ids


def test_no_land_rail_or_border_source_is_registered_yet():
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    tokens = {
        "road",
        "rail",
        "border",
        "truck",
        "trucking",
        "crossing",
        "checkpoint",
        "inland",
        "highway",
        "customs",
    }
    fields: list[str] = []
    for source in registry["sources"]:
        fields.extend(source.get("purposes", []))
        fields.extend((source.get("qualification") or {}).get("logistics_role", []))
    lowered = [field.lower() for field in fields]
    words_seen = {word for field in lowered for word in re.split(r"[_\s]+", field)}
    hits = words_seen & tokens
    assert not hits, hits


def test_event_type_enum_still_lacks_a_mode_neutral_restriction_value():
    """WO-040 identified a real gap this Work Order deliberately does not
    close: port_restriction/canal_restriction are Ocean-worded, and no
    mode-neutral 'facility_or_corridor_restriction' value exists for a
    road, rail or border restriction as distinct from a full closure.
    Recorded in docs/known_data_gaps.md §9. A trip-wire: the day someone
    closes this gap, this test forces the documentation to keep up."""
    schema = json.loads((ROOT / "schemas/logistics_event.schema.json").read_text(encoding="utf-8"))
    event_type_enum = set(schema["properties"]["event_type"]["enum"])
    assert {"port_restriction", "canal_restriction"} <= event_type_enum
    assert "facility_or_corridor_restriction" not in event_type_enum
