"""Notice-feed adapter: bounded intake that never follows a discovered link."""

from __future__ import annotations

from pathlib import Path

import pytest

from collectors.adapters.notice_feed import (
    MAX_CLAIM_LENGTH,
    NoticeFeedError,
    NoticeSpec,
    build_manual_intake_record,
    parse_notice_feed,
    to_event_evidence,
)

FIXTURES = Path(__file__).parent / "fixtures" / "notice_feed"
RETRIEVED = "2026-07-24T00:00:00Z"

OFFICIAL = NoticeSpec(
    source_id="PAT_NOTICE",
    source_name="Example Port Authority",
    source_class="official",
    parser_version="notice_feed_v1",
    intake_kind="official_notice",
)
DISCOVERY = NoticeSpec(
    source_id="NEWS_DISCOVERY",
    source_name="Public news discovery",
    source_class="news",
    parser_version="news_discovery_v1",
    intake_kind="discovery",
)


def _parse(filename: str, spec: NoticeSpec, **kwargs):
    return parse_notice_feed(
        (FIXTURES / filename).read_bytes(), spec, retrieved_at=RETRIEVED, **kwargs
    )


def test_notice_feed_fixture_parses():
    records = _parse("official_notice_rss.xml", OFFICIAL)
    assert len(records) == 2
    first = records[0]
    assert first["source_id"] == "PAT_NOTICE"
    assert first["claim_type"] == "official_notice"
    assert first["evidence_role"] == "confirming"
    assert first["strength"] == "A"
    assert first["publication_date"] == "2026-07-06"
    assert first["source_record_id"] == "NOTICE-2026-014"


def test_atom_entries_parse():
    records = _parse("discovery_atom.xml", DISCOVERY)
    assert len(records) == 1
    assert records[0]["publication_date"] == "2026-07-15"
    assert records[0]["title"].startswith("Report of a possible labour dispute")


def test_discovery_records_are_discovery_only():
    """A discovery source can surface a lead; it can never confirm one."""
    records = _parse("discovery_atom.xml", DISCOVERY)
    assert records[0]["evidence_role"] == "discovery_only"
    assert records[0]["claim_type"] == "discovery_lead"
    assert records[0]["strength"] == "D"


def test_evidence_role_survives_promotion_to_event_evidence():
    record = _parse("discovery_atom.xml", DISCOVERY)[0]
    evidence = to_event_evidence(record, evidence_id="EVD-TEST-001", event_id="EVT-20260715-001")
    assert evidence["evidence_role"] == "discovery_only"
    assert evidence["raw_snapshot_path"] is None


def test_url_userinfo_is_stripped_from_retained_links():
    records = _parse("official_notice_rss.xml", OFFICIAL)
    second = records[1]
    assert "secret" not in second["source_url"]
    assert second["source_url"].startswith("https://example-authority.invalid/")


def test_retained_link_is_never_fetched(monkeypatch):
    """There is no fetch path in this module; assert that structurally.

    Any attempt to open a socket during parsing fails the test rather than
    reaching the network.
    """
    import socket

    def _forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the notice-feed parser attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    records = _parse("official_notice_rss.xml", OFFICIAL)
    assert records[0]["source_url"] is not None


def test_a_document_that_is_not_a_feed_is_rejected():
    """Wrong document and empty feed are different answers."""
    with pytest.raises(NoticeFeedError, match="not a notice feed"):
        _parse("not_a_feed.xml", OFFICIAL)


def test_malformed_xml_is_rejected():
    with pytest.raises(NoticeFeedError, match="not well-formed XML"):
        parse_notice_feed(b"<rss><channel><item>", OFFICIAL, retrieved_at=RETRIEVED)


def test_oversized_payload_is_rejected():
    with pytest.raises(NoticeFeedError, match="byte parser bound"):
        _parse("official_notice_rss.xml", OFFICIAL, max_bytes=50)


def test_too_many_entries_is_rejected():
    with pytest.raises(NoticeFeedError, match="entry bound"):
        _parse("official_notice_rss.xml", OFFICIAL, max_entries=1)


def test_entry_without_a_title_is_rejected():
    payload = b"<rss><channel><item><description>x</description></item></channel></rss>"
    with pytest.raises(NoticeFeedError, match="no title"):
        parse_notice_feed(payload, OFFICIAL, retrieved_at=RETRIEVED)


def test_claims_are_truncated_to_the_contract_bound():
    body = "word " * 400
    payload = (
        f"<rss><channel><item><title>Long notice</title>"
        f"<description>{body}</description></item></channel></rss>"
    ).encode()
    record = parse_notice_feed(payload, OFFICIAL, retrieved_at=RETRIEVED)[0]
    assert len(record["claim"]) <= MAX_CLAIM_LENGTH


def test_unrecognised_publication_date_becomes_null_not_a_guess():
    payload = (
        b"<rss><channel><item><title>Notice</title><pubDate>sometime last week</pubDate>"
        b"<description>x</description></item></channel></rss>"
    )
    record = parse_notice_feed(payload, OFFICIAL, retrieved_at=RETRIEVED)[0]
    assert record["publication_date"] is None


def test_manual_intake_record_is_bounded():
    record = build_manual_intake_record(
        publisher="Example Canal Authority",
        source_class="official",
        notice_reference="ADV-2026-07",
        landing_url="https://example-authority.invalid/advisories",
        publication_date="2026-07-01",
        claim="x" * 5000,
        recorded_at=RETRIEVED,
    )
    assert len(record["claim"]) <= MAX_CLAIM_LENGTH
    assert record["raw_snapshot_path"] is None
    assert record["evidence_role"] == "confirming"
    assert record["source_id"] == "MANUAL_NOTICE_INTAKE"
    assert record["source_name"] == "Example Canal Authority"


def test_manual_intake_requires_a_reference_and_a_claim():
    with pytest.raises(NoticeFeedError, match="notice reference"):
        build_manual_intake_record(
            publisher="P",
            source_class="official",
            notice_reference="   ",
            landing_url="https://example.invalid/",
            publication_date="2026-07-01",
            claim="something",
            recorded_at=RETRIEVED,
        )
    with pytest.raises(NoticeFeedError, match="requires a claim"):
        build_manual_intake_record(
            publisher="P",
            source_class="official",
            notice_reference="REF-1",
            landing_url="https://example.invalid/",
            publication_date="2026-07-01",
            claim="  ",
            recorded_at=RETRIEVED,
        )


def test_content_hashes_differ_between_distinct_notices():
    records = _parse("official_notice_rss.xml", OFFICIAL)
    assert records[0]["content_sha256"] != records[1]["content_sha256"]
