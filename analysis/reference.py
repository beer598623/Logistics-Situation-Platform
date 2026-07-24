"""Reference-dimension access and Lane logic.

Lane membership is resolved through explicit reference records only. Nothing
here infers that an event touches a Lane because the two share a word, a
region name, or a conflict: membership comes from a country, node or
chokepoint that the Lane record actually lists.

The module is mode-neutral. ``lanes_for_*`` never filters to ``sea``; an Air
or Road Lane added later is resolved by exactly the same code.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "data" / "reference"

#: Relationship values that mean "this geography has an established
#: relationship to Thailand logistics". ``none_established`` is deliberately
#: excluded: it is a real answer that must not be upgraded by inference.
THAILAND_RELATED = frozenset(
    {"is_thailand", "direct_trade_partner", "transit_or_chokepoint", "indirect_context"}
)

#: Relationships strong enough to support a material Thailand conclusion on
#: their own. ``indirect_context`` is excluded on purpose -- indirect context
#: needs a stated transmission mechanism before it can carry a conclusion.
THAILAND_MATERIAL = frozenset({"is_thailand", "direct_trade_partner", "transit_or_chokepoint"})


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_dimensions(path: str | None = None) -> dict[str, Any]:
    return _load(Path(path) if path else REFERENCE_DIR / "dimensions.json")


@lru_cache(maxsize=4)
def load_lanes(path: str | None = None) -> dict[str, Any]:
    return _load(Path(path) if path else REFERENCE_DIR / "lanes.json")


def lanes(dimension_source: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    data = dimension_source or load_lanes()
    return list(data.get("lanes", []))


def lane_by_id(lane_id: str, lane_source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    for lane in lanes(lane_source):
        if lane["lane_id"] == lane_id:
            return lane
    raise KeyError(f"Unknown lane: {lane_id}")


def index_by(records: Iterable[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(record[key]): dict(record) for record in records}


def geography_index(dimensions: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return index_by((dimensions or load_dimensions())["geographies"], "geography_id")


def country_index(dimensions: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return index_by((dimensions or load_dimensions())["countries"], "country_id")


def node_index(dimensions: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return index_by((dimensions or load_dimensions())["logistics_nodes"], "node_id")


def chokepoint_index(dimensions: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return index_by((dimensions or load_dimensions())["chokepoints"], "chokepoint_id")


def mode_index(dimensions: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return index_by((dimensions or load_dimensions())["transport_modes"], "mode_id")


def lanes_for_country(
    country_id: str,
    *,
    lane_source: Mapping[str, Any] | None = None,
) -> list[str]:
    return [lane["lane_id"] for lane in lanes(lane_source) if country_id in lane["country_ids"]]


def lanes_for_node(node_id: str, *, lane_source: Mapping[str, Any] | None = None) -> list[str]:
    return [lane["lane_id"] for lane in lanes(lane_source) if node_id in lane.get("node_ids", [])]


def lanes_for_chokepoint(
    chokepoint_id: str,
    *,
    lane_source: Mapping[str, Any] | None = None,
) -> list[str]:
    """Every Lane exposed to a chokepoint.

    This is the cross-lane linkage path: one chokepoint event legitimately
    touches several Lanes at once, and each of those Lanes must still record
    its own relevance and its own evidence rather than inheriting a verdict.
    """
    return [
        lane["lane_id"]
        for lane in lanes(lane_source)
        if chokepoint_id in lane.get("chokepoint_ids", [])
    ]


def lanes_for_mode(mode_id: str, *, lane_source: Mapping[str, Any] | None = None) -> list[str]:
    return [lane["lane_id"] for lane in lanes(lane_source) if lane["mode"] == mode_id]


def thailand_relationship_for_geography(
    geography_id: str,
    *,
    dimensions: Mapping[str, Any] | None = None,
) -> str:
    """Resolve a geography's Thailand relationship, walking up the hierarchy.

    An unknown geography returns ``none_established``. Failing closed matters
    here: an unrecognised place name must never default to "relevant".
    """
    index = geography_index(dimensions)
    seen: set[str] = set()
    current: str | None = geography_id
    while current and current not in seen:
        seen.add(current)
        record = index.get(current)
        if record is None:
            return "none_established"
        relationship = record.get("thailand_relationship", "none_established")
        if relationship != "none_established":
            return relationship
        current = record.get("parent_geography_id")
    return "none_established"


def resolve_lane_relevance(
    *,
    country_ids: Sequence[str] = (),
    node_ids: Sequence[str] = (),
    chokepoint_ids: Sequence[str] = (),
    lane_source: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Map each touched Lane to the concrete reasons it was matched.

    Returning the reasons rather than a bare Lane list is the point: a Lane
    that matched only because it shares a country with the event is weaker
    evidence than one matched on a chokepoint it actually transits, and the
    caller must be able to tell those apart.
    """
    matches: dict[str, list[str]] = {}
    for lane in lanes(lane_source):
        reasons: list[str] = []
        for country_id in country_ids:
            if country_id in lane["country_ids"]:
                reasons.append(f"lane includes country {country_id}")
        for node_id in node_ids:
            if node_id in lane.get("node_ids", []):
                reasons.append(f"lane includes node {node_id}")
        for chokepoint_id in chokepoint_ids:
            if chokepoint_id in lane.get("chokepoint_ids", []):
                reasons.append(f"lane transits chokepoint {chokepoint_id}")
        if reasons:
            matches[lane["lane_id"]] = reasons
    return matches


def implemented_modes(dimensions: Mapping[str, Any] | None = None) -> list[str]:
    return [
        mode["mode_id"]
        for mode in (dimensions or load_dimensions())["transport_modes"]
        if mode["module_status"] == "implemented"
    ]


def planned_modes(dimensions: Mapping[str, Any] | None = None) -> list[str]:
    return [
        mode["mode_id"]
        for mode in (dimensions or load_dimensions())["transport_modes"]
        if mode["module_status"] == "planned"
    ]
