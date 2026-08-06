"""WO-017: keep docs/bundle2_air_cargo_scope.md's factual claims honest.

The scope document cites specific schema/data facts as the evidence base for
what Bundle 2 (Air Cargo) would build on. These tests assert those facts are
still true, so a future schema change either updates the doc in the same PR
or this test catches the drift -- the same discipline
test_documentation_registry_coverage.py applies to the source registry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _load_dimensions() -> dict:
    return json.loads((ROOT / "data" / "reference" / "dimensions.json").read_text(encoding="utf-8"))


def _load_registry() -> dict:
    return yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))


def test_bundle2_scope_doc_exists_and_is_non_empty() -> None:
    path = ROOT / "docs" / "bundle2_air_cargo_scope.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip()


def test_the_registered_airport_node_matches_the_docs_description() -> None:
    dimensions = _load_dimensions()
    nodes = {node["node_id"]: node for node in dimensions["logistics_nodes"]}
    assert "NODE-THBKKAIR" in nodes
    airport = nodes["NODE-THBKKAIR"]
    assert airport["node_type"] == "airport"
    assert airport["modes"] == ["air"]


def test_air_transport_mode_is_registered_as_planned() -> None:
    dimensions = _load_dimensions()
    modes = {mode["mode_id"]: mode for mode in dimensions["transport_modes"]}
    assert "air" in modes
    assert modes["air"]["module_status"] == "planned"


def test_port_transport_observation_metric_enum_covers_air_metrics() -> None:
    schema = _load_schema("port_transport_observation.schema.json")
    metric_enum = schema["properties"]["metric"]["enum"]
    assert "aircraft_movements" in metric_enum
    assert "capacity_deployed" in metric_enum


def test_cost_observation_benchmark_class_is_mode_agnostic() -> None:
    schema = _load_schema("cost_observation.schema.json")
    benchmark_enum = schema["properties"]["benchmark_class"]["enum"]
    assert {"market_benchmark", "route_proxy", "directional_indicator"} <= set(benchmark_enum)


def test_chokepoint_type_enum_already_covers_airspace() -> None:
    schema = _load_schema("reference_dimensions.schema.json")
    chokepoint_type_enum = schema["$defs"]["chokepoint"]["properties"]["chokepoint_type"]["enum"]
    assert "airspace" in chokepoint_type_enum


def test_event_type_enum_covers_the_mode_agnostic_types_the_doc_cites() -> None:
    """The doc claims these four are already directly usable for Air without a
    schema change -- distinct from port_or_terminal_closure/canal_restriction,
    which it documents as needing a small additive extension."""
    schema = _load_schema("logistics_event.schema.json")
    event_type_enum = schema["properties"]["event_type"]["enum"]
    already_usable = {
        "capacity_withdrawal",
        "service_suspension",
        "carrier_rerouting",
        "customs_or_system_outage",
    }
    assert already_usable <= set(event_type_enum)


def test_event_type_enum_covers_non_ocean_closure_events() -> None:
    """WO-035: the doc's §1 originally documented a gap -- no exact-fit event_type
    value for an airport/cargo-terminal closure or an airspace closure, since
    port_or_terminal_closure/canal_restriction are Ocean-worded. Closed by a
    purely additive extension; this locks the gap closed."""
    schema = _load_schema("logistics_event.schema.json")
    event_type_enum = schema["properties"]["event_type"]["enum"]
    assert {"airspace_closure", "terminal_or_facility_closure"} <= set(event_type_enum)
    assert {"port_or_terminal_closure", "canal_restriction"} <= set(event_type_enum)


def test_no_air_source_is_registered_yet() -> None:
    """Locks in the doc's §4 claim that config/sources.yaml has zero air-cargo
    candidates today. This is expected to start failing the moment a real
    Bundle 2 implementation WO adds one -- that's the trip-wire, not a bug:
    it means docs/bundle2_air_cargo_scope.md §4 needs updating in that PR.

    Tokenises on underscores as well as whitespace so a realistic snake_case
    name (e.g. a purpose or logistics_role value like
    'air_freight_benchmark') is caught -- a bare 'air' or 'aviation'
    substring check alone would miss it. Combined with a plain substring
    check for the less ambiguous 'aviation'/'aircraft'/'airport' terms,
    which also catches a hyphenated or glued form ('airport-throughput')
    the token check alone would not."""
    registry = _load_registry()
    fields: list[str] = []
    for source in registry["sources"]:
        fields.extend(source.get("purposes", []))
        qualification = source.get("qualification", {})
        fields.extend(qualification.get("logistics_role", []))

    lowered = [field.lower() for field in fields]
    words = {word for field in lowered for word in re.split(r"[_\s]+", field)}
    air_related = {word for word in words if word == "air"}
    substring_hits = {
        field for field in lowered for term in ("aviation", "aircraft", "airport") if term in field
    }
    assert not air_related and not substring_hits, (
        f"found air-related tokens {air_related} or substrings {substring_hits} "
        "in source purposes/logistics_role"
    )


def test_fbx_public_is_documented_as_ocean_route_scoped_only() -> None:
    """Backs the doc's §4 claim that FBX_PUBLIC cannot stand in for an air
    freight reading, quoting the registry's own known_limitations."""
    registry = _load_registry()
    fbx = next(source for source in registry["sources"] if source["id"] == "FBX_PUBLIC")
    limitations = " ".join(fbx["known_limitations"])
    assert "container routes" in limitations
    assert "Thailand-origin route" in limitations
