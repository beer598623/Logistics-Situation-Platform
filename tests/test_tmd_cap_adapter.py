from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from collectors.adapters.cap import parse_cap_alert
from collectors.adapters.tmd_cap import (
    CANDIDATE_MAX_RESPONSE_BYTES,
    TmdCapAdapter,
    normalize_tmd_alert,
    resolve_endpoint,
)
from collectors.adapters.xml_envelope import RSS
from collectors.http_client import DnsResolutionError
from collectors.registry import load_registry, source_by_id
from tests.conftest import FakeHttpClient, fake_resolve_pinned

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
    surfaced both as a diagnostic warning and (review round 1, finding 4)
    as a structured field."""
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.run.status.value == "error"
    assert result.records == []
    assert any("MalformedCapAlertError" in error for error in result.errors)
    assert any("envelope_classification: kind=rss" in warning for warning in result.warnings)
    assert result.error_code == "MalformedCapAlertError"
    assert result.error_category == "parse"
    assert result.envelope_classification is not None
    assert result.envelope_classification["envelope_kind"] == RSS


# --- collect(): structured error_code/error_category on other failures -----


def test_collect_security_rejection_carries_structured_error_category(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=_read("dtd_entity_attack.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.error_code == "CapSecurityError"
    assert result.error_category == "security"
    assert result.envelope_classification is None


def test_collect_unexpected_content_type_carries_structured_error_category(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=b"<html><body>Not Found</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.error_code == "UnexpectedContentTypeError"
    assert result.error_category == "content_type"


def test_collect_success_leaves_error_code_and_category_none(tmd_contract: dict) -> None:
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    result = adapter.collect()
    assert result.error_code is None
    assert result.error_category is None
    assert result.envelope_classification is None


# --- review round 2, finding 3: ResponseTooLargeError classified consistently --


def test_collect_response_too_large_via_tiny_contract_cap_is_classified_security(
    tmd_contract: dict,
) -> None:
    """Uses a real (not merely simulated) ResponseTooLargeError, raised by
    FakeHttpClient.get()'s own oversized-body check -- the same exception
    type ResilientHttpClient.get() raises for a real oversized response."""
    tiny_contract = json.loads(json.dumps(tmd_contract))
    tiny_contract["http"]["max_response_bytes"] = 10
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tiny_contract, http=fake_http)
    result = adapter.collect()
    assert result.error_code == "ResponseTooLargeError"
    assert result.error_category == "security"
    assert any("ResponseTooLargeError" in error for error in result.errors)


def test_discover_rss_response_too_large_is_classified_security(tmd_contract: dict) -> None:
    from collectors.http_client import ResponseTooLargeError

    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    fake_http.raise_on_get_no_redirect = ResponseTooLargeError("oversized")
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.error_code == "ResponseTooLargeError"
    assert outcome.error_category == "security"


# --- collect(): retry policy is unchanged (regression) ----------------------


def test_collect_still_uses_the_contract_retry_attempts(tmd_contract: dict) -> None:
    """Regression: only discover_rss() is pinned to attempts=1 (review
    round 1, finding 1); collect()'s existing retry policy must be
    unaffected."""
    fake_http = FakeHttpClient(
        body=_read("valid_bilingual_alert.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    adapter.collect()
    assert fake_http.last_attempts == int(tmd_contract["retry"]["attempts"])
    assert fake_http.last_attempts != 1


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


# --- discover_rss(): review round 2, finding 1 -- no-redirect transport, not just attempts=1 --


def test_discover_rss_uses_get_no_redirect_exclusively(tmd_contract: dict) -> None:
    """Superseded round-1 fix (attempts=1 on get()) was insufficient: get()
    still transparently follows redirects regardless of attempts. discover_rss()
    must call get_no_redirect() -- which has no attempts/retry concept at
    all -- and never call get() even once."""
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    adapter.discover_rss()
    assert fake_http.no_redirect_call_count == 1
    assert fake_http.call_count == 1
    assert fake_http.last_attempts is None  # get() (the attempts-based method) was never called


def test_discover_rss_propagates_a_rejected_redirect_as_a_security_error(
    tmd_contract: dict,
) -> None:
    from collectors.http_client import DiscoveryRedirectError

    fake_http = FakeHttpClient(body=b"", headers={})
    fake_http.raise_on_get_no_redirect = DiscoveryRedirectError(
        "refused to follow HTTP 302 redirect"
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.discovery is None
    assert outcome.error_code == "DiscoveryRedirectError"
    assert outcome.error_category == "security"


# --- discover_rss(): review round 2, finding 1 -- grouping uses the requested endpoint host --


def test_discover_rss_groups_candidates_by_the_requested_endpoint_host_not_response_url(
    tmd_contract: dict,
) -> None:
    """Since get_no_redirect() never follows a redirect, a successful
    (non-raised) response was necessarily served directly by the requested
    endpoint's own host -- grouping must use that host, never response.url,
    even if a test double's response_url claims otherwise."""
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"),
        headers={"content-type": "text/xml"},
        response_url="https://not-the-requested-host.example.test/rss",
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    # The fixture's item link is on feed.example.test, which is neither
    # the TMD contract's real host (www.tmd.go.th) nor the fake
    # response_url host above -- so it must land in cross_host_urls,
    # proving grouping used the requested endpoint's host and not
    # response_url.
    assert outcome.discovery["cross_host_urls"]
    assert outcome.discovery["same_host_urls"] == []


# --- discover_rss(): review round 1, finding 4 -- structured error category --


def test_discover_rss_security_rejection_carries_structured_error_category(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=_read("dtd_entity_attack.xml"), headers={"content-type": "application/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.error_code == "EnvelopeSecurityError"
    assert outcome.error_category == "security"


def test_discover_rss_malformed_xml_carries_structured_parse_category(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=b"<rss><channel><title>unterminated", headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.error_code == "EnvelopeParseError"
    assert outcome.error_category == "parse"
    assert "unterminated" not in json.dumps(outcome.to_dict())


def test_discover_rss_success_leaves_error_code_and_category_none(
    tmd_contract: dict,
) -> None:
    fake_http = FakeHttpClient(
        body=_read_rss("same_host_link.xml"), headers={"content-type": "text/xml"}
    )
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.error_code is None
    assert outcome.error_category is None


# --- discover_rss(): review round 3, finding 1 -- 304 fails closed, not silently ---


def test_discover_rss_304_is_a_non_zero_structured_failure_not_a_silent_success(
    tmd_contract: dict,
) -> None:
    """discover_rss() sends no ETag/Last-Modified and keeps no cached
    prior body, so a 304 cannot establish the envelope kind. It must never
    exit as a quiet success with null classification/discovery."""
    fake_http = FakeHttpClient(body=b"", status=304, headers={"etag": '"same"'})
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.error_code == "UnexpectedNotModifiedError"
    assert outcome.error_category == "unexpected"
    assert outcome.errors != []
    assert outcome.envelope_classification is None
    assert outcome.discovery is None
    # Response metadata gathered before the 304 check is still preserved.
    assert outcome.http_status == 304
    assert outcome.etag == '"same"'


# --- discover_rss(): review round 3, finding 2 -- malformed credential-like text --


def test_discover_rss_malformed_http_credential_like_link_never_leaks_at_adapter_level(
    tmd_contract: dict,
) -> None:
    """A single-slash 'https:/user:pass@host' link is malformed (no parsed
    authority component), so redact_url_userinfo cannot reach it -- the
    adapter's discover_rss() outcome must still never surface the raw
    credential-like text anywhere."""
    canary_user = "adaptercanaryuser"
    canary_pass = "adaptercanarysecret"  # noqa: S105 -- synthetic test canary
    body = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <link>https:/{canary_user}:{canary_pass}@feed.example.test/path</link>
    </item>
  </channel>
</rss>""".encode()
    fake_http = FakeHttpClient(body=body, headers={"content-type": "text/xml"})
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.errors == []
    assert outcome.discovery["malformed_urls"]
    serialized = json.dumps(outcome.to_dict())
    assert canary_user not in serialized
    assert canary_pass not in serialized
    assert outcome.discovery["malformed_urls"][0].startswith("<malformed value:")


def test_discover_rss_malformed_non_http_credential_like_link_never_leaks_at_adapter_level(
    tmd_contract: dict,
) -> None:
    """A value with no scheme separator recognized as an authority at all
    (not merely a single-slash http(s) variant) must also never surface
    raw credential-like text in the adapter's outcome."""
    canary_user = "adapternonhttpuser"
    canary_pass = "adapternonhttpsecret"  # noqa: S105 -- synthetic test canary
    body = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <link>{canary_user}:{canary_pass}@feed.example.test/path</link>
    </item>
  </channel>
</rss>""".encode()
    fake_http = FakeHttpClient(body=body, headers={"content-type": "text/xml"})
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.errors == []
    assert outcome.discovery["malformed_urls"]
    serialized = json.dumps(outcome.to_dict())
    assert canary_user not in serialized
    assert canary_pass not in serialized


def test_discover_rss_malformed_credential_bearing_guid_never_leaks_at_adapter_level(
    tmd_contract: dict,
) -> None:
    """Review round 4: a guid beginning with 'https://' but with an
    invalid IPv6 authority (urlsplit/urlparse raise ValueError) must not
    surface raw credential-like text in the adapter's outcome either."""
    canary_user = "adapterguidcanaryuser"
    canary_pass = "adapterguidcanarysecret"  # noqa: S105 -- synthetic test canary
    body = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://feed.example.test/</link>
    <item>
      <guid isPermaLink="true">https://{canary_user}:{canary_pass}@[bad</guid>
    </item>
  </channel>
</rss>""".encode()
    fake_http = FakeHttpClient(body=body, headers={"content-type": "text/xml"})
    adapter = TmdCapAdapter(tmd_contract, http=fake_http)
    outcome = adapter.discover_rss()
    assert outcome.errors == []
    assert outcome.discovery["malformed_urls"]
    assert outcome.discovery["malformed_urls"][0].startswith("<malformed value:")
    serialized = json.dumps(outcome.to_dict())
    assert canary_user not in serialized
    assert canary_pass not in serialized


# --- WO-006 Scope A-D/G: validate_candidate() ---------------------------------


def _candidate_adapter(tmd_contract: dict, fake_http: FakeHttpClient, **kwargs) -> TmdCapAdapter:
    resolve_pinned = kwargs.pop("resolve_pinned", None) or fake_resolve_pinned()
    return TmdCapAdapter(tmd_contract, http=fake_http, resolve_pinned=resolve_pinned, **kwargs)


def test_validate_candidate_accepts_an_exact_cap_1_2_alert(tmd_contract: dict) -> None:
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="30028391246",
        evidence_item_index=0,
    )

    assert outcome.errors == []
    assert outcome.http_status == 200
    assert outcome.envelope_classification["envelope_kind"] == "cap_alert"
    assert outcome.connected_ip_matches_selected is True
    assert outcome.cap_info_count == 2
    assert outcome.cap_languages == ["en-US", "th-TH"]
    assert outcome.cap_reference_count == 0
    assert outcome.cap_area_count == 2
    assert outcome.cap_status == "Actual"
    assert outcome.cap_msg_type == "Alert"
    assert outcome.cap_scope == "Public"
    assert fake_http.pinned_call_count == 1
    assert fake_http.call_count == 1


def test_validate_candidate_never_retains_the_raw_identifier(tmd_contract: dict) -> None:
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )

    assert outcome.cap_identifier_length == len("synthetic-tmd-cap-0001")
    assert len(outcome.cap_identifier_sha256) == 64
    serialized = json.dumps(outcome.to_dict())
    assert "synthetic-tmd-cap-0001" not in serialized


def test_validate_candidate_never_retains_free_text_cap_content(tmd_contract: dict) -> None:
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )

    serialized = json.dumps(outcome.to_dict())
    for canary in (
        "Synthetic severe thunderstorm warning",
        "Synthetic hazard description",
        "Synthetic instruction text",
        "https://example.test/synthetic-warning-0001",
        "synthetic-contact@example.test",
        "Synthetic Test Province",
        "15.0,100.0",
        "TH-10",
    ):
        assert canary not in serialized


def test_validate_candidate_never_creates_a_staging_record(tmd_contract: dict) -> None:
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert not hasattr(outcome, "records")
    assert "records" not in outcome.to_dict()


@pytest.mark.parametrize(
    ("fixture_name", "expected_category"),
    [
        ("dtd_entity_attack.xml", "security"),
        ("missing_identifier.xml", "parse"),
    ],
)
def test_validate_candidate_strict_cap_failures_are_categorized(
    tmd_contract: dict, fixture_name: str, expected_category: str
) -> None:
    body = _read(fixture_name)
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.errors
    assert outcome.error_category == expected_category


def test_validate_candidate_rejects_an_rss_envelope(tmd_contract: dict) -> None:
    body = _read_rss("same_host_link.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "text/xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_code == "CandidateEnvelopeMismatchError"
    assert outcome.error_category == "parse"
    assert outcome.envelope_classification["envelope_kind"] == RSS


def test_validate_candidate_unexpected_content_type_is_rejected(tmd_contract: dict) -> None:
    body = b"<html>not xml</html>"
    fake_http = FakeHttpClient(body=body, headers={"content-type": "text/html"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_category == "content_type"


def test_validate_candidate_missing_content_type_is_rejected(tmd_contract: dict) -> None:
    """ChatGPT review round 1, finding 3: unlike collect()/discover_rss(),
    a missing Content-Type header must fail candidate validation outright
    -- never merely a warning -- and before any XML parsing."""
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_code == "UnexpectedContentTypeError"
    assert outcome.error_category == "content_type"
    assert outcome.envelope_classification is None


def test_validate_candidate_unexpected_content_type_message_is_bounded(
    tmd_contract: dict,
) -> None:
    """ChatGPT review round 1, finding 7: the raw Content-Type header
    value must be bounded before it ever reaches an exception message,
    not only relying on the final report sanitizer."""
    overlong_type = "text/x-" + ("a" * 500)
    fake_http = FakeHttpClient(body=b"not-xml", headers={"content-type": overlong_type})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_category == "content_type"
    assert overlong_type not in outcome.errors[0]
    assert len(outcome.errors[0]) < len(overlong_type)


def test_validate_candidate_never_leaks_parser_warnings_with_identifier_or_geometry(
    tmd_contract: dict,
) -> None:
    """ChatGPT review round 1, finding 4: parse_cap_alert()'s own warning
    strings embed the raw CAP <identifier> and bounded-but-real invalid
    timestamp/polygon/circle source values -- none of that may reach the
    outcome, only a warning count."""
    body = _read("invalid_geometry_and_timestamps.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.errors == []
    assert outcome.cap_parser_warning_count is not None
    assert outcome.cap_parser_warning_count > 0
    serialized = json.dumps(outcome.to_dict())
    for canary in (
        "synthetic-tmd-cap-invalid-0003",
        "not-a-real-timestamp",
        "999.0,999.0",
        "15.0,100.0",
    ):
        assert canary not in serialized


def test_validate_candidate_bounds_etag_and_last_modified_at_extraction(
    tmd_contract: dict,
) -> None:
    """ChatGPT review round 1, finding 7: ETag/Last-Modified are bounded
    when extracted onto the outcome, independent of the final report
    sanitizer."""
    body = _read("valid_bilingual_alert.xml")
    overlong_etag = '"' + ("e" * 500) + '"'
    fake_http = FakeHttpClient(
        body=body,
        headers={"content-type": "application/cap+xml", "etag": overlong_etag},
    )
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.etag is not None
    assert len(outcome.etag) < len(overlong_etag)


def test_validate_candidate_construction_never_resolves_the_contract_endpoint(
    tmd_contract: dict,
) -> None:
    """ChatGPT review round 1, finding 6: candidate validation must never
    depend on config/sources.yaml's endpoint/alternate_endpoints -- proven
    here with a contract whose endpoint is deliberately poisoned/missing,
    which would raise if resolve_endpoint() were ever called."""
    poisoned_contract = dict(tmd_contract)
    poisoned_contract["endpoint"] = None
    poisoned_contract.pop("alternate_endpoints", None)

    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    # Construction itself must not raise despite the poisoned endpoint.
    adapter = _candidate_adapter(poisoned_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.errors == []
    assert outcome.request_url == "https://www.tmd.go.th/uploads/CAP/en/CAPTMD20260723155032_2.xml"

    with pytest.raises(ValueError):
        _ = adapter.endpoint


def test_validate_candidate_oversized_response_fails_before_parsing(tmd_contract: dict) -> None:
    body = b"x" * (CANDIDATE_MAX_RESPONSE_BYTES + 1)
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_category == "security"
    assert outcome.envelope_classification is None


def test_validate_candidate_304_fails_closed(tmd_contract: dict) -> None:
    fake_http = FakeHttpClient(body=b"", status=304, headers={"etag": '"abc"'})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_code == "UnexpectedNotModifiedError"
    assert outcome.http_status == 304


def test_validate_candidate_reference_error_never_reaches_the_network(tmd_contract: dict) -> None:
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="../etc/passwd",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_code == "CandidateReferenceError"
    assert outcome.error_category == "validation"
    assert fake_http.pinned_call_count == 0
    assert fake_http.call_count == 0


def test_validate_candidate_dns_rejection_never_reaches_the_transport(tmd_contract: dict) -> None:
    def _raise_dns(hostname, port):
        raise DnsResolutionError("simulated failure")

    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http, resolve_pinned=_raise_dns)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.error_code == "DnsResolutionError"
    assert outcome.error_category == "security"
    assert fake_http.pinned_call_count == 0


def test_validate_candidate_connected_ip_mismatch_fails_closed(tmd_contract: dict) -> None:
    """ChatGPT review round 1, finding 2: a peer mismatch is now enforced
    by the transport itself, before any request is sent -- the fake
    mirrors that by raising PinnedConnectionError from inside
    get_pinned_candidate, so validate_candidate never reaches the line
    that would otherwise set connected_ip_matches_selected; it stays
    None, not False, reflecting that no partial state was ever recorded."""
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    fake_http.connected_ip_override = "10.0.0.99"
    adapter = _candidate_adapter(tmd_contract, fake_http)

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert isinstance(outcome.error_code, str)
    assert outcome.error_code == "PinnedConnectionError"
    assert outcome.error_category == "security"
    assert outcome.connected_ip_matches_selected is None
    assert outcome.http_status is None


def test_validate_candidate_derives_the_thai_url_and_ignores_the_contract_endpoint(
    tmd_contract: dict,
) -> None:
    body = _read("valid_bilingual_alert.xml")
    fake_http = FakeHttpClient(body=body, headers={"content-type": "application/cap+xml"})
    adapter = _candidate_adapter(tmd_contract, fake_http, language="thai_language_cap")

    outcome = adapter.validate_candidate(
        candidate_filename="CAPTMD20260723155032_2.xml",
        evidence_run_id="1",
        evidence_item_index=0,
    )
    assert outcome.request_url == "https://www.tmd.go.th/uploads/CAP/CAPTMD20260723155032_2.xml"
