from __future__ import annotations

from pathlib import Path

import pytest

from collectors.adapters.cap import (
    CAP_NAMESPACE_1_2,
    CapSecurityError,
    MalformedCapAlertError,
    parse_cap_alert,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "cap"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- CAP namespace 1.2 -------------------------------------------------------


def test_cap_namespace_is_required() -> None:
    non_cap_xml = b'<alert xmlns="urn:example:not-cap"><identifier>x</identifier></alert>'
    with pytest.raises(MalformedCapAlertError):
        parse_cap_alert(non_cap_xml, max_bytes=10_000)


def test_valid_alert_is_recognized_in_the_cap_1_2_namespace() -> None:
    alert, warnings = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    assert warnings == []
    assert alert["identifier"] == "synthetic-tmd-cap-0001"
    assert CAP_NAMESPACE_1_2 == "urn:oasis:names:tc:emergency:cap:1.2"


# --- Required identifier handling --------------------------------------------


def test_missing_identifier_aborts_parsing() -> None:
    with pytest.raises(MalformedCapAlertError):
        parse_cap_alert(_read("missing_identifier.xml"), max_bytes=1_000_000)


# --- Multiple info language blocks -------------------------------------------


def test_multiple_info_blocks_are_preserved_independently() -> None:
    alert, _ = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    assert len(alert["info"]) == 2
    languages = {info["language"] for info in alert["info"]}
    assert languages == {"en-US", "th-TH"}
    en_info = next(info for info in alert["info"] if info["language"] == "en-US")
    th_info = next(info for info in alert["info"] if info["language"] == "th-TH")
    # Neither block's headline leaks into or overwrites the other.
    assert en_info["headline"] != th_info["headline"]
    assert "severe thunderstorm" in en_info["headline"].lower()
    assert th_info["headline"] not in en_info["headline"]


# --- Update and Cancel with references ----------------------------------------


def test_update_message_preserves_msgtype_and_references() -> None:
    alert, _ = parse_cap_alert(_read("update_references_prior_alert.xml"), max_bytes=1_000_000)
    assert alert["msgType"] == "Update"
    assert alert["references"] == [
        "synthetic-tmd@example.test,synthetic-tmd-cap-0001,2026-07-20T14:39:01+07:00"
    ]
    referenced_sender, referenced_identifier, referenced_sent = alert["references"][0].split(",")
    assert referenced_identifier == "synthetic-tmd-cap-0001"


# --- Polygon, circle, and geocode parsing -------------------------------------


def test_polygon_and_geocode_parse_from_the_valid_fixture() -> None:
    alert, _ = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    en_info = next(info for info in alert["info"] if info["language"] == "en-US")
    area = en_info["area"][0]
    assert area["polygon"] == [
        [[15.0, 100.0], [15.0, 101.0], [16.0, 101.0], [16.0, 100.0], [15.0, 100.0]]
    ]
    assert area["geocode"] == [{"valueName": "ISO3166_2", "value": "TH-10"}]
    assert area["altitude"] == 0.0
    assert area["ceiling"] == 1000.0


def test_circle_parses_lat_lon_radius() -> None:
    xml = b"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-circle-test</identifier>
  <sent>2026-07-20T14:39:01+07:00</sent>
  <status>Actual</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  <info>
    <category>Met</category>
    <event>Synthetic circle test</event>
    <urgency>Immediate</urgency>
    <severity>Severe</severity>
    <certainty>Likely</certainty>
    <area>
      <areaDesc>Synthetic circle area</areaDesc>
      <circle>32.85,-93.5 8.4</circle>
    </area>
  </info>
</alert>"""
    alert, warnings = parse_cap_alert(xml, max_bytes=1_000_000)
    assert warnings == []
    circle = alert["info"][0]["area"][0]["circle"][0]
    assert circle == {"lat": 32.85, "lon": -93.5, "radius_km": 8.4}


# --- Invalid timestamp/geometry handling --------------------------------------


def test_invalid_geometry_and_timestamp_are_dropped_with_warnings_not_a_crash() -> None:
    alert, warnings = parse_cap_alert(
        _read("invalid_geometry_and_timestamps.xml"), max_bytes=1_000_000
    )
    # The alert still parses; the malformed area contents are dropped, not fatal.
    assert alert["identifier"] == "synthetic-tmd-cap-invalid-0003"
    area = alert["info"][0]["area"][0]
    assert area["polygon"] == []
    assert area["circle"] == []
    assert alert["info"][0]["effective"] is None
    assert len(warnings) == 3
    assert any("polygon is not a closed ring" in warning for warning in warnings)
    assert any("circle out of range" in warning for warning in warnings)
    assert any("not a valid CAP timestamp" in warning for warning in warnings)


# --- DTD/XXE rejection ---------------------------------------------------------


def test_dtd_and_xxe_payloads_are_rejected() -> None:
    with pytest.raises(CapSecurityError):
        parse_cap_alert(_read("dtd_entity_attack.xml"), max_bytes=1_000_000)


def test_billion_laughs_style_internal_entities_are_rejected() -> None:
    payload = b"""<?xml version="1.0"?>
<!DOCTYPE alert [
  <!ENTITY a "spam">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
]>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-billion-laughs</identifier>
  <info><event>&b;</event></info>
</alert>"""
    with pytest.raises(CapSecurityError):
        parse_cap_alert(payload, max_bytes=1_000_000)


def test_security_error_never_echoes_the_raw_payload() -> None:
    canary_marker = "CANARY_PAYLOAD_MARKER_SHOULD_NOT_LEAK"
    payload = f"""<?xml version="1.0"?>
<!DOCTYPE alert [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>{canary_marker}</identifier>
</alert>""".encode()
    with pytest.raises(CapSecurityError) as excinfo:
        parse_cap_alert(payload, max_bytes=1_000_000)
    assert canary_marker not in str(excinfo.value)


# --- Oversized response rejection ---------------------------------------------


def test_oversized_payload_is_rejected_before_parsing() -> None:
    oversized_but_well_formed = (
        b'<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
        b"<identifier>synthetic-oversized</identifier>" + b"<!-- padding -->" * 10_000 + b"</alert>"
    )
    with pytest.raises(CapSecurityError):
        parse_cap_alert(oversized_but_well_formed, max_bytes=100)


# --- A missing operational-impact field never becomes numeric zero -----------


def test_parsed_alert_carries_no_operational_impact_field_at_all() -> None:
    """CAP parsing must never introduce an operational-impact conclusion --
    not even a zero/none placeholder. The parsed alert dict has no impact,
    severity-of-disruption, or logistics field of any kind; 'severity' here
    is always the CAP hazard-severity enum value, never a platform impact
    severity, and it is None (not 0 or 'none') when the source omits it."""
    xml = b"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-no-severity</identifier>
  <info>
    <event>Synthetic event with no severity/urgency/certainty</event>
  </info>
</alert>"""
    alert, _ = parse_cap_alert(xml, max_bytes=1_000_000)
    info = alert["info"][0]
    assert info["severity"] is None
    assert info["urgency"] is None
    assert info["certainty"] is None
    assert "impact" not in alert
    assert "operational_disruption_status" not in alert
