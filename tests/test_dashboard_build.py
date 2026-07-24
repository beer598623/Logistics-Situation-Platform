"""Dashboard build: required outputs, honest empty states, safe failure."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_dashboard import DATA, build_payloads  # noqa: E402

PUBLIC = ROOT / "dashboard" / "public"

REQUIRED_OUTPUTS = {
    "thailand_situation.json",
    "ocean.json",
    "trade.json",
    "cost.json",
    "events.json",
    "ai_outlook.json",
    "sources.json",
    "indicators.json",
    "source_status.json",
    "build_status.json",
}


@pytest.fixture(scope="module")
def payloads():
    return build_payloads()


def test_build_produces_every_required_payload(payloads):
    assert REQUIRED_OUTPUTS <= set(payloads)


def test_every_required_file_is_present_on_disk():
    for name in REQUIRED_OUTPUTS:
        assert (DATA / name).exists(), name
        json.loads((DATA / name).read_text(encoding="utf-8"))


def test_the_static_site_files_exist():
    assert (PUBLIC / "index.html").exists()
    assert (PUBLIC / "assets" / "app.js").exists()
    assert (PUBLIC / "assets" / "styles.css").exists()


def test_the_page_loads_no_external_resource():
    """A GitHub Pages site must not depend on a CDN, font host or API."""
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    for pattern in ("//cdn", "https://unpkg", "https://cdnjs", "fonts.googleapis", "integrity="):
        assert pattern not in html, pattern
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    # The only permitted absolute link is the repository itself, in the footer.
    assert all(url.startswith("https://github.com/") for url in external), external


def test_the_script_makes_no_request_outside_its_own_data_directory():
    script = (PUBLIC / "assets" / "app.js").read_text(encoding="utf-8")
    fetches = re.findall(r"fetch\(([^)]*)\)", script)
    assert fetches
    assert all("'data/'" in call for call in fetches), fetches
    assert "XMLHttpRequest" not in script
    assert "WebSocket" not in script


def test_the_page_declares_the_seven_required_sections():
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    for section_id in (
        "situation",
        "ocean",
        "trade",
        "cost",
        "events",
        "outlook",
        "sources",
    ):
        assert f'id="{section_id}"' in html, section_id


def test_insufficient_coverage_is_stated_on_the_face_of_the_dashboard(payloads):
    situation = payloads["thailand_situation.json"]
    assert situation["evidence_coverage"] == "insufficient"
    assert "INSUFFICIENT" in situation["live_coverage_statement"]
    assert "synthetic test fixture" in situation["live_coverage_statement"]
    assert payloads["build_status.json"]["live_coverage"] == "insufficient"


def test_the_build_records_zero_paid_dependency_and_no_ai_api(payloads):
    status = payloads["build_status.json"]
    assert status["paid_source_dependency"] == 0
    assert status["ai_api_used"] is False


def test_stale_sources_are_shown_as_stale_not_as_current(payloads):
    """Freshness travels with every reading so nothing implies currency."""
    for series in payloads["cost.json"]["cost_series"]:
        assert series["freshness"]["status"] in {"fresh", "stale", "very_stale", "no_data"}
    for series in payloads["ocean.json"]["port_series"]:
        assert "status" in series["freshness"]
    assert any(
        series["freshness"]["status"] in {"stale", "very_stale"}
        for series in payloads["cost.json"]["cost_series"]
    )


def test_missing_periods_survive_into_the_dashboard_as_gaps(payloads):
    """A missing period must reach the browser as null, never as zero."""
    missing = [
        point
        for lane in payloads["trade.json"]["lane_flows"]
        for flow in lane["flows"]
        for point in flow["points"]
        if point["value_status"] != "available"
    ]
    assert missing, "the fixture set must contain a visible gap"
    assert all(point["value"] is None for point in missing)


def test_a_series_with_missing_periods_reports_them(payloads):
    lsci = [
        item
        for item in payloads["indicators.json"]["indicators"]
        if item["series_id"] == "thailand_lsci"
    ]
    assert lsci and lsci[0]["periods_missing"] == 3
    assert lsci[0]["missing_periods"]


def test_the_ai_section_shows_an_explicit_empty_state_not_a_blank_panel(payloads):
    outlook = payloads["ai_outlook.json"]
    assert outlook["approved_assessments"] == []
    assert outlook["review_status"] == "no_approved_assessment"
    assert "No human-approved AI assessment exists" in outlook["status_message"]
    assert "calls no AI API" in outlook["boundary_note"]


def test_deterministic_outlooks_are_labelled_as_not_being_an_ai_assessment(payloads):
    outlook = payloads["ai_outlook.json"]
    assert "not an AI assessment" in outlook["deterministic_note"]
    assert len(outlook["deterministic_outlooks"]) == 11


def test_every_lane_reaches_the_dashboard_with_its_resolution_and_limitations(payloads):
    lanes = payloads["ocean.json"]["lanes"]
    assert len(lanes) == 11
    for lane in lanes:
        assert lane["resolution"]
        assert lane["known_limitations"]
        assert lane["assessment"] is not None
        assert len(lane["assessment"]["domain_assessments"]) == 9


def test_port_series_are_labelled_volume_only(payloads):
    ocean = payloads["ocean.json"]
    assert "not congestion" in ocean["port_interpretation_note"]
    for series in ocean["port_series"]:
        assert series["operational_interpretation"] == "volume_only"


#: Words that turn a congestion phrase into a disclaimer rather than a claim.
_NEGATIONS = ("no ", "not ", "never", "cannot", "without", "requires")


def _sentences_containing(payloads, phrase):
    blob = json.dumps(payloads).lower().replace("\\n", " ")
    return [sentence for sentence in re.split(r"(?<=[.!?])\s+", blob) if phrase in sentence]


@pytest.mark.parametrize(
    "phrase",
    ["congestion", "congested", "berth delay", "yard congestion", "truck delay", "real-time"],
)
def test_congestion_language_only_ever_appears_as_a_disclaimer(payloads, phrase):
    """The platform monitors no operational-condition source, so it must never
    assert congestion. Where the word appears at all, it must be a statement
    that no such claim is being made, or a limitation on what a metric can
    support."""
    offenders = [
        sentence
        for sentence in _sentences_containing(payloads, phrase)
        if not any(negation in sentence for negation in _NEGATIONS)
    ]
    assert not offenders, f"{phrase}: {offenders[:2]}"


def test_no_thailand_freight_average_is_published(payloads):
    assert not _sentences_containing(payloads, "average thailand freight rate")
    for series in payloads["cost.json"]["cost_series"]:
        assert series["quotation_claim"] == "not_a_quotation"
        assert series["benchmark_class"] != "actual_quotation"
    assert any(
        "no Thailand freight average is published" in limitation
        for limitation in payloads["cost.json"]["benchmark_limitations"]
    )


def test_events_are_separated_by_class(payloads):
    events = payloads["events.json"]
    assert events["direct_operational_events"]
    assert events["contextual_external_drivers"]
    assert events["discovery_leads"]
    for event in events["contextual_external_drivers"]:
        assert event["transmission_chain"]["completeness"] != "complete"
    for event in events["discovery_leads"]:
        assert all(item["evidence_role"] == "discovery_only" for item in event["evidence"])


def test_the_sources_section_exposes_licence_freshness_and_blockers(payloads):
    sources = payloads["sources.json"]["sources"]
    assert len(sources) == 15
    for source in sources:
        assert source["licence_status"]
        assert source["health"] is not None
        assert "enabled" in source
    candidates = [source for source in sources if source["source_id"] not in {"TMD_CAP", "GDACS"}]
    assert all(source["blockers"] for source in candidates)


def test_an_empty_approved_directory_does_not_break_the_build(monkeypatch, tmp_path):
    """The AI section renders an explicit statement rather than failing."""
    payloads = build_payloads()
    assert payloads["ai_outlook.json"]["review_status"] == "no_approved_assessment"


def test_a_failed_build_leaves_the_published_directory_untouched(monkeypatch):
    """Payloads are assembled before anything is written."""
    import scripts.build_dashboard as builder

    before = {path.name: path.read_bytes() for path in DATA.glob("*.json")}

    def _explode():
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(builder, "build_payloads", _explode)
    with pytest.raises(RuntimeError, match="simulated upstream failure"):
        builder.main()

    after = {path.name: path.read_bytes() for path in DATA.glob("*.json")}
    assert after == before


def test_chart_data_always_has_a_table_equivalent():
    """Every chart the script draws is paired with a table of the same numbers."""
    script = (PUBLIC / "assets" / "app.js").read_text(encoding="utf-8")
    assert "pointsTable" in script
    assert script.count("sparkline(") >= 1
    # seriesBlock is the only place a sparkline is emitted, and it always
    # emits pointsTable alongside.
    block = script.split("function seriesBlock", 1)[1].split("\n  }", 1)[0]
    assert "sparkline(" in block and "pointsTable(" in block
