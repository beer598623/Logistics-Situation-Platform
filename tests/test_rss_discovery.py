from __future__ import annotations

from pathlib import Path

import pytest

from collectors.adapters.rss_discovery import (
    CROSS_HOST,
    MALFORMED,
    NON_HTTP,
    SAME_HOST,
    NotAnRssEnvelopeError,
    RssSecurityError,
    discover_rss_candidates,
)

ROOT = Path(__file__).resolve().parents[1]
CAP_FIXTURES = ROOT / "tests" / "fixtures" / "cap"
RSS_FIXTURES = ROOT / "tests" / "fixtures" / "rss"

FEED_HOST = "feed.example.test"


def _read(directory: Path, name: str) -> bytes:
    return (directory / name).read_bytes()


# --- Deterministic same-host / cross-host / non-http / malformed grouping ---


def test_same_host_link_and_guid_are_grouped_same_host() -> None:
    payload = _read(RSS_FIXTURES, "same_host_link.xml")
    result, warnings = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    assert warnings == []
    assert result.channel_item_count == 1
    assert result.items_considered == 1
    groups = {candidate.group for candidate in result.candidates}
    assert groups == {SAME_HOST}
    fields = {candidate.source_field for candidate in result.candidates}
    assert fields == {"link", "guid"}


def test_cross_host_link_is_grouped_cross_host() -> None:
    payload = _read(RSS_FIXTURES, "cross_host_link.xml")
    result, _ = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    link_candidates = [c for c in result.candidates if c.source_field == "link"]
    assert len(link_candidates) == 1
    assert link_candidates[0].group == CROSS_HOST
    assert link_candidates[0].host == "other.example.test"


def test_malformed_link_is_grouped_malformed_not_a_crash() -> None:
    payload = _read(RSS_FIXTURES, "malformed_link.xml")
    result, _ = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    link_candidates = [c for c in result.candidates if c.source_field == "link"]
    assert len(link_candidates) == 1
    assert link_candidates[0].group == MALFORMED
    assert link_candidates[0].host is None


def test_non_http_scheme_is_grouped_non_http() -> None:
    xml = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://{FEED_HOST}/</link>
    <item>
      <link>ftp://{FEED_HOST}/warnings/item-007</link>
      <guid isPermaLink="false">item-007</guid>
    </item>
  </channel>
</rss>""".encode()
    result, _ = discover_rss_candidates(xml, max_bytes=1_000_000, feed_host=FEED_HOST)
    link_candidates = [c for c in result.candidates if c.source_field == "link"]
    assert len(link_candidates) == 1
    assert link_candidates[0].group == NON_HTTP
    assert link_candidates[0].scheme == "ftp"


# --- Enclosure URL/type retention ---------------------------------------------


def test_enclosure_url_and_media_type_are_retained() -> None:
    payload = _read(RSS_FIXTURES, "enclosure_media_type.xml")
    result, _ = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    enclosure_candidates = [c for c in result.candidates if c.source_field == "enclosure"]
    assert len(enclosure_candidates) == 1
    assert enclosure_candidates[0].media_type == "application/cap+xml"
    assert enclosure_candidates[0].group == SAME_HOST
    data = result.to_dict()
    assert "application/cap+xml" in data["candidate_media_types"]


# --- Canary: free-text title/description are never retained -----------------


def test_title_and_description_canary_never_appears_in_discovery_output() -> None:
    payload = _read(RSS_FIXTURES, "long_title_description_canary.xml")
    result, warnings = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    data = result.to_dict()
    import json

    serialized = json.dumps(data)
    assert "CANARY-MARKER-DO-NOT-RETAIN" not in serialized
    assert "CANARY-MARKER-DO-NOT-RETAIN" not in json.dumps(warnings)


# --- pubDate parsing / bounding ------------------------------------------------


def test_parseable_pub_date_is_normalized_to_iso8601_utc() -> None:
    payload = _read(RSS_FIXTURES, "same_host_link.xml")
    result, _ = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    assert result.item_publication_times == {0: "2026-07-23T10:00:00Z"}


def test_unparseable_pub_date_is_dropped_not_retained_as_raw_text() -> None:
    xml = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://{FEED_HOST}/</link>
    <item>
      <link>https://{FEED_HOST}/item-008</link>
      <pubDate>not a real date</pubDate>
    </item>
  </channel>
</rss>""".encode()
    result, _ = discover_rss_candidates(xml, max_bytes=1_000_000, feed_host=FEED_HOST)
    assert result.item_publication_times == {}


# --- Channel/item counts and MAX_ITEMS bound -----------------------------------


def test_item_count_exceeding_max_items_is_bounded_with_a_warning() -> None:
    items = "".join(f"<item><link>https://{FEED_HOST}/item-{i}</link></item>" for i in range(60))
    xml = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://{FEED_HOST}/</link>
    {items}
  </channel>
</rss>""".encode()
    result, warnings = discover_rss_candidates(xml, max_bytes=10_000_000, feed_host=FEED_HOST)
    assert result.channel_item_count == 60
    assert result.items_considered == 50
    assert any("only the first 50" in warning for warning in warnings)


# --- Non-RSS envelope is never reinterpreted as RSS ----------------------------


def test_atom_root_raises_not_an_rss_envelope_error() -> None:
    payload = _read(RSS_FIXTURES, "atom_feed.xml")
    with pytest.raises(NotAnRssEnvelopeError):
        discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)


def test_unrelated_xml_root_raises_not_an_rss_envelope_error() -> None:
    payload = _read(RSS_FIXTURES, "unrelated_xml.xml")
    with pytest.raises(NotAnRssEnvelopeError):
        discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)


def test_cap_alert_root_raises_not_an_rss_envelope_error() -> None:
    payload = _read(CAP_FIXTURES, "valid_bilingual_alert.xml")
    with pytest.raises(NotAnRssEnvelopeError):
        discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)


# --- Security: DTD/XXE and oversized payloads are rejected before parsing ------


def test_dtd_entity_payload_is_rejected_and_never_echoed() -> None:
    payload = _read(CAP_FIXTURES, "dtd_entity_attack.xml")
    with pytest.raises(RssSecurityError) as excinfo:
        discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    assert payload.decode("utf-8", errors="ignore") not in str(excinfo.value)


def test_oversized_payload_is_rejected_before_parsing() -> None:
    payload = _read(RSS_FIXTURES, "same_host_link.xml")
    with pytest.raises(RssSecurityError) as excinfo:
        discover_rss_candidates(payload, max_bytes=10, feed_host=FEED_HOST)
    assert "10-byte" in str(excinfo.value)


# --- URL length bound -----------------------------------------------------------


def test_overlong_url_is_bounded_not_retained_in_full() -> None:
    long_path = "a" * 2000
    xml = f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Synthetic</title>
    <link>https://{FEED_HOST}/</link>
    <item>
      <link>https://{FEED_HOST}/{long_path}</link>
    </item>
  </channel>
</rss>""".encode()
    result, _ = discover_rss_candidates(xml, max_bytes=10_000_000, feed_host=FEED_HOST)
    link_candidates = [c for c in result.candidates if c.source_field == "link"]
    assert len(link_candidates) == 1
    assert len(link_candidates[0].url) < len(long_path)
    assert "chars omitted" in link_candidates[0].url


# --- to_dict() grouping shape ----------------------------------------------------


def test_to_dict_groups_candidates_by_bucket() -> None:
    payload = _read(RSS_FIXTURES, "cross_host_link.xml")
    result, _ = discover_rss_candidates(payload, max_bytes=1_000_000, feed_host=FEED_HOST)
    data = result.to_dict()
    assert data["cross_host_urls"]
    assert data["same_host_urls"] == []
    assert data["malformed_urls"] == []
    assert data["non_http_values"] == []
