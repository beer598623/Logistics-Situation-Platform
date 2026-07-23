"""Generic CAP 1.2 parser (Scope C, WO-002 Implementation v0.2).

A hardened, source-agnostic parser for OASIS CAP 1.2 alert messages
(https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html). This module
only detects and normalizes hazard/context information from an official
CAP feed; an official warning must only ever become a hazard candidate or
context record here, never an observed transport, facility, or logistics
disruption. Source-specific configuration (e.g. TMD's endpoints) lives in a
thin profile module such as ``collectors/adapters/tmd_cap.py`` -- nothing
source-specific belongs in this file.

Security posture:

- The response-size limit is enforced *before* any parsing is attempted.
- ``defusedxml`` rejects any ``<!DOCTYPE ...>``, external entity, or
  internal entity-expansion ("billion laughs") attempt; this is not
  optional and is exercised directly by
  ``tests/test_cap_parser.py::test_dtd_and_xxe_payloads_are_rejected``.
- No exception raised by this module ever includes the raw payload text,
  so a parser failure cannot leak untrusted XML into logs or reports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import defusedxml.ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

CAP_NAMESPACE_1_2 = "urn:oasis:names:tc:emergency:cap:1.2"
_NS = {"cap": CAP_NAMESPACE_1_2}
_EXPECTED_ROOT_TAG = f"{{{CAP_NAMESPACE_1_2}}}alert"

#: Untrusted raw text is bounded to this length before it is embedded in
#: any warning string, so a single oversized or crafted XML text node
#: cannot inflate downstream logs/artifacts -- independent of and in
#: addition to the overall payload byte cap enforced before parsing.
_MAX_WARNING_VALUE_LENGTH = 120


class CapSecurityError(ValueError):
    """A payload was rejected before or during parsing for a security
    reason (oversized, DOCTYPE/DTD, external or internal entity). The
    message must never include the raw payload."""


class MalformedCapAlertError(ValueError):
    """The top-level <alert> element itself is unusable (wrong/missing CAP
    namespace, or missing the required <identifier>)."""


def _bounded(value: str) -> str:
    """Bound an untrusted raw value before embedding it in a warning
    string. Applied at warning-creation time (not just at the final report
    layer) so no single caller downstream needs to know a value was ever
    untrusted."""
    if len(value) <= _MAX_WARNING_VALUE_LENGTH:
        return repr(value)
    omitted = len(value) - _MAX_WARNING_VALUE_LENGTH
    return repr(value[:_MAX_WARNING_VALUE_LENGTH]) + f"...(+{omitted} chars omitted)"


def _text(element: Any, tag: str) -> str | None:
    child = element.find(f"cap:{tag}", _NS)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _texts(element: Any, tag: str) -> list[str]:
    return [
        node.text.strip()
        for node in element.findall(f"cap:{tag}", _NS)
        if node.text and node.text.strip()
    ]


def _space_delimited(element: Any, tag: str) -> list[str]:
    """CAP <addresses>/<incidents> are one element containing a
    whitespace-delimited list of (optionally quoted) tokens. Known
    limitation: this splits on plain whitespace and does not unescape
    quoted multi-word tokens -- acceptable for a hazard-context signal,
    documented in docs/gdacs_tmd_cap_pilot.md."""
    raw = _text(element, tag)
    return raw.split() if raw else []


def _parse_cap_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_references(raw: str | None) -> list[str]:
    """CAP <references> is 'sender,identifier,sent sender,identifier,sent
    ...' -- one triple per prior message, triples separated by whitespace.
    Preserved verbatim (not resolved) so Update/Cancel messages can later be
    associated with the alerts they reference."""
    return raw.split() if raw else []


def _parse_polygon(text: str | None, warnings: list[str], context: str) -> list[list[float]] | None:
    if not text or not text.strip():
        return None
    points: list[list[float]] = []
    for pair in text.strip().split():
        try:
            lat_str, lon_str = pair.split(",")
            lat, lon = float(lat_str), float(lon_str)
        except ValueError:
            warnings.append(f"{context}: invalid polygon coordinate rejected -- {_bounded(pair)}")
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            warnings.append(f"{context}: polygon coordinate out of range -- {_bounded(pair)}")
            return None
        points.append([lat, lon])
    if len(points) < 4 or points[0] != points[-1]:
        warnings.append(f"{context}: polygon is not a closed ring of at least 4 points; rejected")
        return None
    return points


def _parse_circle(text: str | None, warnings: list[str], context: str) -> dict[str, float] | None:
    if not text or not text.strip():
        return None
    stripped = text.strip()
    try:
        point, radius_str = stripped.rsplit(" ", 1)
        lat_str, lon_str = point.split(",")
        lat, lon, radius = float(lat_str), float(lon_str), float(radius_str)
    except ValueError:
        warnings.append(f"{context}: invalid circle geometry rejected -- {_bounded(stripped)}")
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or radius < 0:
        warnings.append(f"{context}: circle out of range -- {_bounded(stripped)}")
        return None
    return {"lat": lat, "lon": lon, "radius_km": radius}


def _parse_area(area_element: Any, warnings: list[str], context: str) -> dict[str, Any]:
    area_desc = _text(area_element, "areaDesc")
    if not area_desc:
        warnings.append(f"{context}: area is missing required areaDesc")

    polygons = []
    for index, polygon_el in enumerate(area_element.findall("cap:polygon", _NS)):
        parsed = _parse_polygon(polygon_el.text, warnings, f"{context} polygon[{index}]")
        if parsed is not None:
            polygons.append(parsed)

    circles = []
    for index, circle_el in enumerate(area_element.findall("cap:circle", _NS)):
        parsed = _parse_circle(circle_el.text, warnings, f"{context} circle[{index}]")
        if parsed is not None:
            circles.append(parsed)

    geocodes = []
    for geocode_el in area_element.findall("cap:geocode", _NS):
        value_name = _text(geocode_el, "valueName")
        value = _text(geocode_el, "value")
        if value_name and value:
            geocodes.append({"valueName": value_name, "value": value})

    altitude_raw = _text(area_element, "altitude")
    ceiling_raw = _text(area_element, "ceiling")
    altitude = None
    ceiling = None
    try:
        altitude = float(altitude_raw) if altitude_raw else None
    except ValueError:
        warnings.append(f"{context}: altitude {_bounded(altitude_raw)} is not numeric; dropped")
    try:
        ceiling = float(ceiling_raw) if ceiling_raw else None
    except ValueError:
        warnings.append(f"{context}: ceiling {_bounded(ceiling_raw)} is not numeric; dropped")

    return {
        "areaDesc": area_desc,
        "polygon": polygons,
        "circle": circles,
        "geocode": geocodes,
        "altitude": altitude,
        "ceiling": ceiling,
    }


def _parse_info(info_element: Any, warnings: list[str], context: str) -> dict[str, Any]:
    event_codes = []
    for code_el in info_element.findall("cap:eventCode", _NS):
        value_name = _text(code_el, "valueName")
        value = _text(code_el, "value")
        if value_name and value:
            event_codes.append({"valueName": value_name, "value": value})

    parameters = []
    for param_el in info_element.findall("cap:parameter", _NS):
        value_name = _text(param_el, "valueName")
        value = _text(param_el, "value")
        if value_name and value:
            parameters.append({"valueName": value_name, "value": value})

    for label in ("effective", "onset", "expires"):
        raw = _text(info_element, label)
        if raw and _parse_cap_timestamp(raw) is None:
            warnings.append(
                f"{context}: {label} {_bounded(raw)} is not a valid CAP timestamp; "
                "treated as unknown"
            )

    areas = [
        _parse_area(area_el, warnings, f"{context} area[{index}]")
        for index, area_el in enumerate(info_element.findall("cap:area", _NS))
    ]

    return {
        "language": _text(info_element, "language") or "en-US",
        "category": _texts(info_element, "category"),
        "event": _text(info_element, "event"),
        "responseType": _texts(info_element, "responseType"),
        "urgency": _text(info_element, "urgency"),
        "severity": _text(info_element, "severity"),
        "certainty": _text(info_element, "certainty"),
        "audience": _text(info_element, "audience"),
        "eventCode": event_codes,
        "effective": _parse_cap_timestamp(_text(info_element, "effective")),
        "onset": _parse_cap_timestamp(_text(info_element, "onset")),
        "expires": _parse_cap_timestamp(_text(info_element, "expires")),
        "senderName": _text(info_element, "senderName"),
        "headline": _text(info_element, "headline"),
        "description": _text(info_element, "description"),
        "instruction": _text(info_element, "instruction"),
        "web": _text(info_element, "web"),
        "contact": _text(info_element, "contact"),
        "parameter": parameters,
        "area": areas,
    }


def parse_cap_alert(payload: bytes, *, max_bytes: int) -> tuple[dict[str, Any], list[str]]:
    """Parse one CAP 1.2 <alert> document into a structured dict.

    Enforces ``max_bytes`` before any parsing occurs, and rejects any
    DOCTYPE/DTD or entity-expansion attempt during parsing
    (``CapSecurityError``). A malformed <area>, polygon, circle, or
    timestamp inside one <info> block is dropped with a warning rather than
    aborting the whole document; only a root element that is not *exactly*
    ``{urn:oasis:names:tc:emergency:cap:1.2}alert`` (e.g. a same-namespace
    ``<info>`` or ``<circle>`` document, not just any element in the CAP
    namespace) or a missing top-level <identifier> raises
    (``MalformedCapAlertError``), since ``identifier`` is CAP's mandatory
    external message ID and this parser has nothing safe to fall back to
    without it.
    """
    if len(payload) > max_bytes:
        raise CapSecurityError(
            f"CAP payload of {len(payload)} bytes exceeds the {max_bytes}-byte "
            "limit; rejected before parsing"
        )

    try:
        root = DefusedET.fromstring(
            payload,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException as exc:
        raise CapSecurityError(f"CAP payload rejected: {type(exc).__name__}") from None
    except Exception as exc:  # noqa: BLE001 -- never echo the raw payload back
        raise MalformedCapAlertError(
            f"CAP payload could not be parsed as XML: {type(exc).__name__}"
        ) from None

    if root.tag != _EXPECTED_ROOT_TAG:
        raise MalformedCapAlertError(
            f"root element must be {_EXPECTED_ROOT_TAG!r} (CAP 1.2 <alert>), not {root.tag!r}"
        )

    identifier = _text(root, "identifier")
    if not identifier:
        raise MalformedCapAlertError("alert is missing the required <identifier>")

    warnings: list[str] = []
    sent_raw = _text(root, "sent")
    sent = _parse_cap_timestamp(sent_raw)
    if sent_raw and sent is None:
        warnings.append(f"{identifier}: <sent> {_bounded(sent_raw)} is not a valid CAP timestamp")

    infos = [
        _parse_info(info_el, warnings, f"{identifier} info[{index}]")
        for index, info_el in enumerate(root.findall("cap:info", _NS))
    ]

    alert = {
        "identifier": identifier,
        "sender": _text(root, "sender"),
        "sent": sent,
        "status": _text(root, "status"),
        "msgType": _text(root, "msgType"),
        "source": _text(root, "source"),
        "scope": _text(root, "scope"),
        "restriction": _text(root, "restriction"),
        "addresses": _space_delimited(root, "addresses"),
        "code": _texts(root, "code"),
        "note": _text(root, "note"),
        "references": _parse_references(_text(root, "references")),
        "incidents": _space_delimited(root, "incidents"),
        "info": infos,
    }
    return alert, warnings
