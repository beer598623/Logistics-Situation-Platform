from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from collectors.adapters.cap import parse_cap_alert
from collectors.adapters.tmd_cap import TmdCapAdapter, normalize_tmd_alert, resolve_endpoint
from collectors.adapters.xml_envelope import RSS
from collectors.registry import load_registry, source_by_id
from tests.conftest import FakeHttpClient

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "cap"
RSS_FIXTURES = ROOT / "tests" / "fixtures" / "rss"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _read_rss(name: str) -> bytes:
    return (RSS_FIXTURES / name).read_bytes()


@pytest.fixture
def tmd_contract() -> dict:
    registry = load_registry()
    return source_by_id(registry, "TMD_CAP")


@pytest.fixture
def staging_record_validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "schemas" / "staging_record.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


# --- Primary and alternate endpoint resolution -------------------------------


def test_primary_endpoint_is_the_english_cap_url(tmd_contract: dict) -> None:
    assert resolve_endpoint(tmd_contract) == "https://www.tmd.go.th/en/api/xml/CAP"


def test_alternate_endpoint_resolves_the_thai_cap_url(tmd_contract: dict) -> None:
    assert (
        resolve_endpoint(tmd_contract, language="thai_language_cap")
        == "https://www.tmd.go.th/api/xml/CAP"
    )


def test_unknown_alternate_endpoint_label_raises(tmd_contract: dict) -> None:
    with pytest.raises(ValueError):
        resolve_endpoint(tmd_contract, language="french_language_cap")


def test_no_url_is_hardcoded_in_the_adapter_module() -> None:
    import inspect

    from collectors.adapters import tmd_cap

    source = inspect.getsource(tmd_cap)
    assert "tmd.go.th" not in source


# --- TMD remains unverified / pending review / disabled ----------------------


def test_tmd_contract_remains_unverified_pending_review_and_disabled(tmd_contract: dict) -> None:
    assert tmd_contract["machine_readable_status"] == "unverified"
    assert tmd_contract["licence_status"] == "pending_review"
    assert tmd_contract["enabled"] is False
    assert tmd_contract["required_for_publication"] is False


# --- Multilingual info blocks preserved independently as separate records ---


def test_each_info_block_becomes_its_own_staging_record(staging_record_validator) -> None:
    alert, _ = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    records, warnings = normalize_tmd_alert(
        alert, content_sha256="a" * 64, source_url="https://www.tmd.go.th/en/api/xml/CAP"
    )
    assert warnings == []
    assert len(records) == 2

    languages = {record["source_signal"]["language"] for record in records}
    assert languages == {"en-US", "th-TH"}

    # Both records share the same CAP identifier (source_external_id) but
    # are otherwise independent -- neither's title/geography is merged into
    # the other's.
    assert {record["source_external_id"] for record in records} == {"synthetic-tmd-cap-0001"}
    titles = {record["title"] for record in records}
    assert len(titles) == 2

    for record in records:
        errors = list(staging_record_validator.iter_errors(record))
        assert errors == []


def test_geography_falls_back_to_thailand_when_no_area_given() -> None:
    xml = b"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-no-area</identifier>
  <sent>2026-07-20T14:39:01+07:00</sent>
  <info>
    <language>en-US</language>
    <event>Synthetic alert with no area element</event>
    <headline>Synthetic alert with no area element</headline>
  </info>
</alert>"""
    alert, _ = parse_cap_alert(xml, max_bytes=1_000_000)
    records, warnings = normalize_tmd_alert(alert, content_sha256="b" * 64, source_url=None)
    assert records[0]["candidate_identity_inputs"]["geography"] == ["Thailand"]
    assert any("fell back to 'Thailand'" in warning for warning in warnings)


def test_alert_with_no_info_blocks_yields_no_records_and_a_warning() -> None:
    xml = b"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-no-info</identifier>
</alert>"""
    alert, _ = parse_cap_alert(xml, max_bytes=1_000_000)
    records, warnings = normalize_tmd_alert(alert, content_sha256="c" * 64, source_url=None)
    assert records == []
    assert any("no <info> blocks" in warning for warning in warnings)


# --- msgType / references preserved for later Update/Cancel association ----


def test_update_message_preserves_msgtype_and_dedicated_source_references(
    staging_record_validator,
) -> None:
    """Regression for the ChatGPT review: CAP <references> triples belong in
    a dedicated, typed source_references field (source_revision has no
    single-value equivalent for CAP and stays null)."""
    alert, _ = parse_cap_alert(_read("update_references_prior_alert.xml"), max_bytes=1_000_000)
    records, _ = normalize_tmd_alert(alert, content_sha256="d" * 64, source_url=None)
    assert records[0]["source_signal"]["msgType"] == "Update"
    assert records[0]["source_revision"] is None
    assert "references" not in records[0]["source_signal"]
    assert "synthetic-tmd-cap-0001" in records[0]["source_references"][0]
    assert list(staging_record_validator.iter_errors(records[0])) == []


def test_alert_with_no_references_omits_source_references_field() -> None:
    alert, _ = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    records, _ = normalize_tmd_alert(alert, content_sha256="f" * 64, source_url=None)
    assert "source_references" not in records[0]


# --- source_url is always the safe contract endpoint, never a source-provided deep link ---


def test_source_url_is_never_the_source_provided_cap_web_deep_link() -> None:
    """Regression for the ChatGPT review: while TMD's deep-link permission
    question remains pending_review, a source-provided CAP <web> URL must
    never surface as source_url -- only the safe, already-public contract
    endpoint."""
    xml = b"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-web-deep-link</identifier>
  <info>
    <language>en-US</language>
    <event>Synthetic alert with a web deep link</event>
    <headline>Synthetic alert with a web deep link</headline>
    <web>https://www.tmd.go.th/internal/deep/link/should-not-surface</web>
    <area><areaDesc>Synthetic area</areaDesc></area>
  </info>
</alert>"""
    alert, _ = parse_cap_alert(xml, max_bytes=1_000_000)
    records, _ = normalize_tmd_alert(
        alert, content_sha256="a" * 64, source_url="https://www.tmd.go.th/en/api/xml/CAP"
    )
    assert records[0]["source_url"] == "https://www.tmd.go.th/en/api/xml/CAP"
    assert "should-not-surface" not in (records[0]["source_url"] or "")


# --- publication_date comes only from CAP <sent>, never onset/effective ----


def test_publication_date_stays_null_when_sent_is_absent_even_with_onset() -> None:
    """Regression for the ChatGPT review: publication_date must come only
    from CAP <sent> (a verified message-publication timestamp). It must not
    fall back to onset/effective (the hazard period) when <sent> is
    missing -- that would mislabel the event date as a publication date."""
    xml = b"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>synthetic-no-sent</identifier>
  <info>
    <language>en-US</language>
    <event>Synthetic alert with no sent timestamp</event>
    <headline>Synthetic alert with no sent timestamp</headline>
    <onset>2026-07-20T10:00:00+07:00</onset>
    <effective>2026-07-20T11:00:00+07:00</effective>
    <area><areaDesc>Synthetic area</areaDesc></area>
  </info>
</alert>"""
    alert, _ = parse_cap_alert(xml, max_bytes=1_000_000)
    assert alert["sent"] is None
    records, _ = normalize_tmd_alert(alert, content_sha256="a" * 64, source_url=None)
    assert records[0]["candidate_identity_inputs"]["event_date"] == "2026-07-20"
    assert records[0]["candidate_identity_inputs"]["publication_date"] is None
    assert records[0]["source_publication_time"] is None


def test_publication_date_comes_from_sent_when_present() -> None:
    alert, _ = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    records, _ = normalize_tmd_alert(alert, content_sha256="b" * 64, source_url=None)
    assert alert["sent"].startswith("2026-07-20")
    assert records[0]["candidate_identity_inputs"]["publication_date"] == "2026-07-20"


# --- A TMD warning never becomes an observed logistics impact ---------------


def test_staging_record_never_asserts_operational_impact() -> None:
    alert, _ = parse_cap_alert(_read("valid_bilingual_alert.xml"), max_bytes=1_000_000)
    records, _ = normalize_tmd_alert(alert, content_sha256="e" * 64, source_url=None)
    for record in records:
        assert "operational_disruption_status" not in record
        assert "impact_assessments" not in record
        assert record["transport_modes"] if "transport_modes" in record else True
        assert record["candidate_identity_inputs"]["transport_modes"] == []
        assert any(
            "does not by itself establish observed transport" in limitation
            for limitation in record["known_limitations"]
        )


# --- collect() end-to-end without network access ----------------------------


def test_collect_end_to_end_with_fake_http(tmd_contract: dict) -> None:
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.status.value == "success"
    assert result.run.records_emitted == 2
    assert result.errors == []


def test_collect_surfaces_security_rejection_as_a_run_error_not_a_crash(tmd_contract: dict) -> None:
    fake_http = FakeHttpClient(
        body=_read("dtd_entity_attack.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.status.value == "error"
    assert result.records == []
    assert any("CapSecurityError" in error for error in result.errors)


def test_collect_rejects_an_unexpected_content_type_like_an_html_error_page(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=b"<html><body>Not Found</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.status.value == "error"
    assert result.records == []
    assert any("UnexpectedContentTypeError" in error for error in result.errors)


def test_collect_retains_etag_last_modified_and_workflow_sha(
    tmd_contract: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"),
        headers={
            "content-type": "application/xml",
            "etag": '"tmd-etag-1"',
            "last-modified": "Mon, 20 Jul 2026 07:39:01 GMT",
        },
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.etag == '"tmd-etag-1"'
    assert result.run.last_modified == "Mon, 20 Jul 2026 07:39:01 GMT"
    assert result.run.workflow_sha == "deadbeef"


def test_collect_retains_response_url_distinct_from_request_url_on_redirect(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"),
        headers={"content-type": "application/xml"},
        response_url="https://mirror.tmd.example/api/xml/CAP?redirected=1",
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.request_url == "https://www.tmd.go.th/en/api/xml/CAP"
    assert result.run.response_url == "https://mirror.tmd.example/api/xml/CAP?redirected=1"
    assert result.run.request_url != result.run.response_url


def test_collect_retains_content_type_on_success(tmd_contract: dict) -> None:
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"),
        headers={"content-type": "application/cap+xml"},
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.content_type == "application/cap+xml"


def test_collect_handles_304_safely_for_response_url_and_content_type(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(body=b"", status=304, headers={"etag": '"same"'})
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.status.value == "not_modified"
    assert result.run.response_url is not None
    assert result.run.content_type is None


# --- collect() diagnostic enrichment: envelope classification on rejection --


def test_collect_still_rejects_rss_content_and_appends_envelope_classification_warning(
    tmd_contract: dict,
) -> None:
    """Regression matching WO-003's observed live evidence: an RSS envelope
    served at a recorded CAP endpoint must still be rejected by the strict
    CAP parser (Scope A untouched), with the envelope classification
    surfaced only as an additional diagnostic warning."""
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.status.value == "error"
    assert result.records == []
    assert any("MalformedCapAlertError" in error for error in result.errors)
    assert any("envelope_classification: kind=rss" in warning for warning in result.warnings)


# --- discover_rss(): exactly one network request, structural metadata only --


def test_discover_rss_makes_exactly_one_http_call(tmd_contract: dict) -> None:
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    adapter.discover_rss()
    assert fake_http.call_count == 1


def test_discover_rss_classifies_an_rss_envelope_and_extracts_candidates(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.errors == []
    assert outcome.envelope_classification is not None
    assert outcome.envelope_classification["envelope_kind"] == RSS
    assert outcome.discovery is not None
    assert outcome.discovery["channel_item_count"] == 1


def test_discover_rss_on_a_cap_alert_response_performs_no_discovery(
    tmd_contract: dict,
) -> None:
    """A direct CAP response is classified but never run through the RSS
    discovery parser -- discovery only ever applies to an RSS envelope."""
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.errors == []
    assert outcome.envelope_classification["envelope_kind"] == "cap_alert"
    assert outcome.discovery is None
    assert any("no RSS discovery performed" in warning for warning in outcome.warnings)


def test_discover_rss_surfaces_security_rejection_as_an_error_not_a_crash(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=_read("dtd_entity_attack.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.discovery is None
    assert any("EnvelopeSecurityError" in error for error in outcome.errors)


def test_discover_rss_retains_workflow_sha_and_response_metadata(
    tmd_contract: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "cafef00d")
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"),
        headers={
            "content-type": "text/xml",
            "etag": '"tmd-etag-2"',
            "last-modified": "Thu, 23 Jul 2026 09:00:00 GMT",
        },
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.workflow_sha == "cafef00d"
    assert outcome.etag == '"tmd-etag-2"'
    assert outcome.last_modified == "Thu, 23 Jul 2026 09:00:00 GMT"
    assert outcome.http_status == 200
