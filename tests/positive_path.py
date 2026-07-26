"""Builders for records that *do* qualify for current publication (WO-010-R2 §6).

Every number this repository commits is a fixture, so the qualification
boundary has only ever been exercised from the negative side: nothing
qualifies, and the current view is empty. That proves the filter rejects, not
that it accepts, and a filter that rejects everything is indistinguishable
from a hard-coded empty list.

These builders construct records that satisfy every condition -- a
current-publication dataset, a live retrieval or a named human transcription,
an enabled source with compatible roles and reviewed terms -- so tests can
drive the positive path end to end.

They are **test objects only**. Nothing here is written to ``data/``, nothing
claims a real publisher was contacted, and the committed Dashboard is
unaffected. ``TEST_REGISTRY`` is a separate in-memory registry; the real
``config/sources.yaml`` still has zero enabled sources.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

CUTOFF = datetime(2026, 7, 24, tzinfo=UTC)
CUTOFF_ISO = "2026-07-24T00:00:00Z"
RETRIEVED_AT = "2026-07-20T06:00:00Z"

#: A fictitious enabled source, used only in tests. It is deliberately not one
#: of the seventeen registry IDs, so no test can accidentally assert that a
#: real source is enabled.
TEST_TRADE_SOURCE = "TEST_TRADE_SOURCE"
TEST_NOTICE_SOURCE = "TEST_MANUAL_NOTICE"
TEST_LINK_ONLY_SOURCE = "TEST_LINK_ONLY"
TEST_DERIVED_ONLY_SOURCE = "TEST_DERIVED_ONLY"

TEST_REGISTRY: dict[str, Any] = {
    "version": "0.8",
    "policy": "free_sources_only",
    "last_reviewed_at": "2026-07-24",
    "sources": [
        {
            "id": TEST_TRADE_SOURCE,
            "name": "Test trade statistics publisher",
            "owner": "Test",
            "source_class": "official",
            "access_method": "download",
            "format": "csv",
            "machine_readable_status": "verified",
            "licence_status": "reviewed",
            "endpoint": "https://example.org/trade.csv",
            "landing_url": "https://example.org/trade",
            "enabled": True,
            "required_for_publication": False,
            "max_stale_minutes": 105120,
            "expected_cadence_minutes": 44640,
            "known_limitations": ["Test source."],
            "qualification": {
                "access_cost": "free",
                "paywall_status": "none",
                "reuse_status": "permitted_with_attribution",
                "redistribution_status": "permitted",
                "publication_use": "raw_values_permitted",
                "publication_cadence": "monthly",
                "observed_freshness": "2026-07-20",
                "logistics_role": ["thailand_trade_flow"],
                "prototype_eligibility": "eligible",
                "rate_limit": "60 requests per hour",
            },
            "enablement": {"blockers": [], "schedule_justified": True},
        },
        {
            # The controlled manual intake path: a disabled source whose
            # human-reviewed records may still reach the current view.
            "id": TEST_NOTICE_SOURCE,
            "name": "Test manual notice intake",
            "owner": "Test",
            "source_class": "manual_human_review",
            "access_method": "manual",
            "format": "manual",
            "machine_readable_status": "not_applicable",
            "licence_status": "reviewed",
            "endpoint": None,
            "landing_url": "https://example.org/notices",
            "enabled": False,
            "required_for_publication": False,
            "max_stale_minutes": 20160,
            "expected_cadence_minutes": None,
            "known_limitations": ["Bounded claim and link only."],
            "qualification": {
                "access_cost": "free",
                "paywall_status": "none",
                "reuse_status": "permitted_with_attribution",
                "redistribution_status": "link_only",
                "publication_use": "bounded_claim_and_link_only",
                "manual_intake_status": "allowed",
                "underlying_publisher_required": True,
                "publication_cadence": "irregular",
                "observed_freshness": "2026-07-20",
                "logistics_role": ["official_operational_notice"],
                "prototype_eligibility": "eligible",
                "rate_limit": None,
            },
            "enablement": {"blockers": [], "schedule_justified": False},
        },
        {
            # Enabled, but its terms permit a link and nothing more. Used to
            # show that enablement alone does not authorise publishing values.
            "id": TEST_LINK_ONLY_SOURCE,
            "name": "Test link-only publisher",
            "owner": "Test",
            "source_class": "official",
            "access_method": "download",
            "format": "csv",
            "machine_readable_status": "verified",
            "licence_status": "reviewed",
            "endpoint": "https://example.org/link.csv",
            "landing_url": "https://example.org/link",
            "enabled": True,
            "required_for_publication": False,
            "max_stale_minutes": 105120,
            "expected_cadence_minutes": 44640,
            "known_limitations": ["Link only."],
            "qualification": {
                "access_cost": "free",
                "paywall_status": "none",
                "reuse_status": "permitted_with_attribution",
                "redistribution_status": "link_only",
                "publication_use": "metadata_link_only",
                "publication_cadence": "monthly",
                "observed_freshness": "2026-07-20",
                "logistics_role": ["thailand_trade_flow"],
                "prototype_eligibility": "eligible",
                "rate_limit": "60 requests per hour",
            },
            "enablement": {"blockers": [], "schedule_justified": True},
        },
        {
            # Enabled, and permitted to publish a derived reading -- but never
            # the raw current value or the raw chart points it was computed
            # from (WO-010-R3 §5).
            "id": TEST_DERIVED_ONLY_SOURCE,
            "name": "Test derived-only publisher",
            "owner": "Test",
            "source_class": "official",
            "access_method": "download",
            "format": "csv",
            "machine_readable_status": "verified",
            "licence_status": "reviewed",
            "endpoint": "https://example.org/derived.csv",
            "landing_url": "https://example.org/derived",
            "enabled": True,
            "required_for_publication": False,
            "max_stale_minutes": 105120,
            "expected_cadence_minutes": 44640,
            "known_limitations": ["Derived values only."],
            "qualification": {
                "access_cost": "free",
                "paywall_status": "none",
                "reuse_status": "permitted_with_attribution",
                "redistribution_status": "derived_only",
                "publication_use": "derived_values_only",
                "publication_cadence": "monthly",
                "observed_freshness": "2026-07-20",
                "logistics_role": ["thailand_trade_flow"],
                "prototype_eligibility": "eligible",
                "rate_limit": "60 requests per hour",
            },
            "enablement": {"blockers": [], "schedule_justified": True},
        },
    ],
}


def live_trade_observation(
    *,
    period_key: str,
    value: float | None,
    lane_id: str = "LANE-OCEAN-TH-NEUR",
    series_id: str = "th_export_value_neur",
    source_id: str = TEST_TRADE_SOURCE,
    dataset: str = "current_publication",
    evidence_origin: str = "live_retrieved",
    retrieval_status: str = "retrieved",
    retrieved_at: str | None = RETRIEVED_AT,
) -> dict[str, Any]:
    """One live-retrieved current trade observation.

    Truthful throughout: a retrieval status of ``retrieved`` with a retrieval
    timestamp, a real source identifier rather than the reserved synthetic
    one, and no ``intended_source_id`` -- it stands in for nothing because it
    is the thing itself.
    """
    year, month = (int(part) for part in period_key.split("-"))
    last_day = _MONTH_END[month]
    return {
        "series_id": series_id,
        "flow_direction": "export",
        "reporter_country_id": "TH",
        "partner_country_id": None,
        "partner_scope": "region_group",
        "partner_label": "Northern Europe",
        "commodity_scope": "all_commodities",
        "measure": "value",
        "provenance": {
            "record_id": f"OBS-{source_id}-{series_id}-{period_key}",
            "source_id": source_id,
            "source_record_id": None,
            "dataset": dataset,
            "evidence_origin": evidence_origin,
            "retrieval_status": retrieval_status,
            "content_hash_scope": "source_response",
            "intended_source_id": None,
            "fixture_created_at": None,
            "period_start": f"{year:04d}-{month:02d}-01",
            "period_end": f"{year:04d}-{month:02d}-{last_day:02d}",
            "period_type": "month",
            "published_at": f"{year:04d}-{month:02d}-{last_day:02d}T00:00:00Z",
            "retrieved_at": retrieved_at,
            "revised_at": None,
            "revision_number": 0,
            "content_sha256": "a" * 64,
            "parser_version": "test_v1",
            "source_revision": None,
            "evidence_class": "official_statistic",
            "known_limitations": [
                "Trade value is an all-mode total and is not an ocean-only figure."
            ],
        },
        "measurement": {
            "value": value,
            "value_status": "available" if value is not None else "missing",
            "unit": "THB_million" if value is not None else None,
            "currency": "THB",
        },
        "placement": {
            "geography_id": "GEO-CTY-TH",
            "country_id": "TH",
            "transport_mode": "not_applicable",
            "lane_id": lane_id,
            "node_id": None,
        },
    }


def live_trade_series(
    *,
    periods: int = 26,
    start_value: float = 100000.0,
    growth: float = 0.0,
    **overrides: Any,
) -> list[dict[str, Any]]:
    """A month-by-month series long enough to satisfy a threshold rule.

    ``TH-TRADE-YOY-V1`` needs 13 observations before it will produce any
    direction at all, so a shorter series is the natural way to test that
    inadequate history yields ``insufficient_evidence`` rather than a number.
    """
    records = []
    year, month = 2024, 6
    for index in range(periods):
        records.append(
            live_trade_observation(
                period_key=f"{year:04d}-{month:02d}",
                value=round(start_value * (1 + growth) ** index, 2),
                **overrides,
            )
        )
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return records


def manual_notice_evidence(
    *,
    evidence_id: str = "EVD-MANUAL-001",
    event_id: str = "EVT-20260720-001",
    dataset: str = "current_publication",
    source_id: str = TEST_NOTICE_SOURCE,
    evidence_origin: str = "human_reviewed_manual",
    retrieval_status: str = "not_applicable",
    claim_type: str = "official_notice",
) -> dict[str, Any]:
    """A human-reviewed official notice, transcribed rather than fetched.

    ``retrieval_status`` is ``not_applicable`` and ``retrieved_at`` is null:
    a person read the publisher's page, the platform fetched nothing, and
    claiming a retrieval would be false. The underlying publisher is named so
    the claim stays independently checkable.
    """
    return {
        "evidence_id": evidence_id,
        "event_id": event_id,
        "dataset": dataset,
        "source_id": source_id,
        "source_name": "Test manual notice intake",
        "source_class": "manual_human_review",
        "underlying_publisher": "Example Port Authority",
        "source_url": "https://example.org/notices/2026-07-20",
        "claim": (
            "The port authority published a notice on 2026-07-20 suspending berthing at "
            "one terminal until further notice."
        ),
        "claim_type": claim_type,
        "evidence_role": "confirming",
        "relation": "describes",
        "strength": "A",
        "strength_basis": "verified",
        "scope_supported": "facility",
        "event_date": "2026-07-20",
        "publication_date": "2026-07-20",
        "retrieval_status": retrieval_status,
        "retrieved_at": None,
        "evidence_origin": evidence_origin,
        "fixture_created_at": None,
        "revised_at": None,
        "content_sha256": "b" * 64,
        "content_hash_scope": "authored_claim_record",
        "parser_version": "manual_intake_v1",
        "source_revision": None,
        "licence_status": "reviewed",
        "redistribution_status": "link_only",
        "raw_snapshot_path": None,
        "known_limitations": [
            "Transcribed by a named human reviewer. The notice text itself is not "
            "republished; the claim is bounded and the publisher's page is linked."
        ],
    }


def current_operational_event(
    *,
    event_id: str = "EVT-20260720-001",
    evidence_ids: tuple[str, ...] = ("EVD-MANUAL-001",),
    dataset: str = "current_publication",
    lane_id: str = "LANE-OCEAN-TH-ASEAN-SG",
    chokepoint_ids: tuple[str, ...] = (),
    active_as_of: str | None = "2026-07-20T00:00:00Z",
    active_basis: str | None = "The authority's notice was re-checked on 2026-07-20.",
    lifecycle_status: str = "verified_event",
    impacts: dict[str, dict[str, Any]] | None = None,
    negative_operational_evidence: bool = False,
) -> dict[str, Any]:
    """A current direct operational event supported by the manual notice."""
    areas = (
        "warehouse",
        "logistics",
        "transport",
        "import_export",
        "inventory",
        "cost",
        "capacity",
        "service",
        "business_continuity",
    )
    base_impact = {
        "status": "insufficient_evidence",
        "severity": "none",
        "relevance": "none",
        "geographic_scope": "facility",
        "time_horizon": "unknown",
        "expected_duration": "unknown",
        "transmission_mechanism": [],
        "evidence_ids": [],
        "evidence_strength": "C",
        "confidence": "low",
        "known_limitations": [],
    }
    overrides = impacts or {}
    return {
        "event_id": event_id,
        "canonical_event_id": event_id,
        "dataset": dataset,
        "title": "Berthing suspended at one terminal",
        "event_class": "direct_operational_event",
        "event_type": "port_or_terminal_closure",
        "lifecycle_status": lifecycle_status,
        "event_date": "2026-07-20",
        "event_end_date": None,
        "publication_date": "2026-07-20",
        "retrieval_date": CUTOFF_ISO,
        "active_as_of": active_as_of,
        "active_basis": active_basis,
        "geography_ids": ["GEO-CTY-SG"],
        "country_ids": ["SG"],
        "node_ids": [],
        "chokepoint_ids": list(chokepoint_ids),
        "modes": ["sea"],
        "operator_or_entity": "Example Port Authority",
        "thailand_relevance": "asserted",
        "thailand_relevance_basis": [
            "The terminal serves a lane on which Thailand ocean cargo transships."
        ],
        "lane_relevance": [
            {"lane_id": lane_id, "relevance": "direct", "basis": "Transshipment node on this lane."}
        ],
        "transmission_chain": {
            "external_driver": None,
            "operational_change": "Berthing is suspended at one terminal.",
            "logistics_mechanism": "The terminal is removed from the vessel rotation.",
            "observable_indicator": "Port authority notice.",
            "outcome": "Observed suspension.",
            "completeness": "complete",
            "missing_links": [],
        },
        "event_severity": "moderate",
        "impact_assessments": [
            {"area": area, **base_impact, **overrides.get(area, {})} for area in areas
        ],
        "evidence_ids": list(evidence_ids),
        "conflicting_evidence": [],
        "negative_operational_evidence": negative_operational_evidence,
        "publication_status": "Watchlist",
        "human_review": {
            "required": False,
            "status": "not_required",
            "reviewer_record": None,
            "reviewed_at": None,
        },
        "clustering": {
            "cluster_key": "",
            "cluster_id": None,
            "canonical_source_url": None,
            "title_normalized": "berthing suspended terminal",
            "merge_status": "unmatched",
        },
        "closure_basis": None,
        "last_reviewed_at": CUTOFF_ISO,
        "known_limitations": [],
    }
