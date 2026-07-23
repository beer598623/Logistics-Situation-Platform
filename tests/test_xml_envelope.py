from __future__ import annotations

from pathlib import Path

import pytest

from collectors.adapters.xml_envelope import (
    ATOM,
    CAP_ALERT,
    OTHER_XML,
    RSS,
    EnvelopeParseError,
    EnvelopeSecurityError,
    classify_envelope,
)

ROOT = Path(__file__).resolve().parents[1]
CAP_FIXTURES = ROOT / "tests" / "fixtures" / "cap"
RSS_FIXTURES = ROOT / "tests" / "fixtures" / "rss"


def _read(directory: Path, name: str) -> bytes:
    return (directory / name).read_bytes()


# --- Correct classification per envelope kind --------------------------------


def test_classifies_a_cap_alert_document() -> None:
    payload = _read(CAP_FIXTURES, "valid_bilingual_alert.xml")
    classification = classify_envelope(payload, max_bytes=1_000_000, content_sha256="a" * 64)
    assert classification.envelope_kind == CAP_ALERT
    assert classification.root_local_name == "alert"
    assert classification.root_namespace == "urn:oasis:names:tc:emergency:cap:1.2"
    assert classification.content_length == len(payload)
    assert classification.content_sha256 == "a" * 64


def test_classifies_an_rss_document() -> None:
    payload = _read(RSS_FIXTURES, "same_host_link.xml")
    classification = classify_envelope(payload, max_bytes=1_000_000, content_sha256="b" * 64)
    assert classification.envelope_kind == RSS
    assert classification.root_local_name == "rss"
    assert classification.root_namespace is None


def test_classifies_an_atom_document() -> None:
    payload = _read(RSS_FIXTURES, "atom_feed.xml")
    classification = classify_envelope(payload, max_bytes=1_000_000, content_sha256="c" * 64)
    assert classification.envelope_kind == ATOM
    assert classification.root_local_name == "feed"
    assert classification.root_namespace == "http://www.w3.org/2005/Atom"


def test_classifies_an_unrelated_xml_document_as_other_xml() -> None:
    payload = _read(RSS_FIXTURES, "unrelated_xml.xml")
    classification = classify_envelope(payload, max_bytes=1_000_000, content_sha256="d" * 64)
    assert classification.envelope_kind == OTHER_XML
    assert classification.root_local_name == "catalog"
    assert classification.root_namespace is None


# --- Security: DTD/XXE and oversized payloads are rejected before/instead of parsing --


def test_dtd_entity_payload_is_rejected_and_never_echoed() -> None:
    payload = _read(CAP_FIXTURES, "dtd_entity_attack.xml")
    with pytest.raises(EnvelopeSecurityError) as excinfo:
        classify_envelope(payload, max_bytes=1_000_000, content_sha256="e" * 64)
    assert payload.decode("utf-8", errors="ignore") not in str(excinfo.value)


def test_oversized_payload_is_rejected_before_parsing() -> None:
    payload = _read(RSS_FIXTURES, "same_host_link.xml")
    with pytest.raises(EnvelopeSecurityError) as excinfo:
        classify_envelope(payload, max_bytes=10, content_sha256="f" * 64)
    assert "10-byte" in str(excinfo.value)
    assert payload.decode("utf-8", errors="ignore") not in str(excinfo.value)


def test_malformed_xml_is_rejected_without_echoing_the_payload() -> None:
    """Review round 1, finding 4: ordinary malformed (not well-formed) XML
    that raises no DTD/entity/external-reference concern must be a
    distinct EnvelopeParseError, not EnvelopeSecurityError, so a
    diagnostic report can categorize it as a parse failure rather than a
    security rejection."""
    payload = b"<not-valid-xml"
    with pytest.raises(EnvelopeParseError) as excinfo:
        classify_envelope(payload, max_bytes=1_000_000, content_sha256="g" * 64)
    assert "not-valid-xml" not in str(excinfo.value)
    assert not isinstance(excinfo.value, EnvelopeSecurityError)


# --- to_dict() shape ----------------------------------------------------------


def test_to_dict_contains_only_structural_metadata() -> None:
    payload = _read(RSS_FIXTURES, "same_host_link.xml")
    classification = classify_envelope(payload, max_bytes=1_000_000, content_sha256="h" * 64)
    data = classification.to_dict()
    assert set(data) == {
        "root_local_name",
        "root_namespace",
        "envelope_kind",
        "content_length",
        "content_sha256",
    }
