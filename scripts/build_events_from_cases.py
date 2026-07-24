#!/usr/bin/env python3
"""Expand the authored historical cases into full event and evidence records.

``data/validation/historical_cases.json`` is the human-authored, reviewable
source: it states each case's core facts, its evidence, the impact areas that
were actually assessed, and what the platform is expected to conclude. This
script expands that compact form into the full contract shape --
all nine impact areas, the computed transmission completeness, the
deterministic cluster key, and resolved lane relevance -- and writes
``data/events/events.json`` and ``data/events/event_evidence.json``.

The expansion is deterministic and adds no judgement. Areas the author did
not assess become ``insufficient_evidence`` (or the case's declared default),
never ``no_material``: the difference between "we assessed this and found
nothing" and "we did not assess this" is the whole point.

Usage::

    python scripts/build_events_from_cases.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.events import (  # noqa: E402
    cluster_id_from_key,
    cluster_key,
    evaluate_transmission_chain,
)
from analysis.reference import geography_index, resolve_lane_relevance  # noqa: E402

CASES_PATH = ROOT / "data" / "validation" / "historical_cases.json"
EVENTS_PATH = ROOT / "data" / "events" / "events.json"
EVIDENCE_PATH = ROOT / "data" / "events" / "event_evidence.json"

IMPACT_AREAS = (
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

#: Relevance strength implied by how a lane was matched. A lane matched only
#: because it shares a country with the event is weaker than one matched on a
#: chokepoint it actually transits, and the two must not be reported alike.
_RELEVANCE_BY_REASON = {"chokepoint": "medium", "node": "medium", "country": "low"}


def _geographic_scope(event: dict[str, Any]) -> str:
    index = geography_index()
    names = [
        index[geography_id]["name"]
        for geography_id in event["geography_ids"]
        if geography_id in index
    ]
    return ", ".join(names) if names else "Scope not resolved from reference geography"


def _expand_impacts(case: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    default = case["default_impact"]
    overrides = case.get("impacts", {})
    impacts = []
    for area in IMPACT_AREAS:
        source = {**default, **overrides.get(area, {})}
        impacts.append(
            {
                "area": area,
                "status": source["status"],
                "severity": source["severity"],
                "relevance": source["relevance"],
                "geographic_scope": source.get("geographic_scope", scope),
                "time_horizon": source.get("time_horizon", "unknown"),
                "expected_duration": source.get("expected_duration", "unknown"),
                "transmission_mechanism": list(source.get("transmission_mechanism", [])),
                "evidence_ids": list(source.get("evidence_ids", [])),
                "evidence_strength": source["evidence_strength"],
                "confidence": source["confidence"],
                "known_limitations": list(source.get("known_limitations", [])),
            }
        )
    return impacts


def _lane_relevance(event: dict[str, Any], evidence_ids: list[str]) -> list[dict[str, Any]]:
    matches = resolve_lane_relevance(
        country_ids=event.get("country_ids", []),
        node_ids=event.get("node_ids", []),
        chokepoint_ids=event.get("chokepoint_ids", []),
    )
    entries = []
    for lane_id in sorted(matches):
        reasons = matches[lane_id]
        strength = "low"
        for reason in reasons:
            if "chokepoint" in reason:
                strength = _RELEVANCE_BY_REASON["chokepoint"]
                break
            if "node" in reason:
                strength = _RELEVANCE_BY_REASON["node"]
        entries.append(
            {
                "lane_id": lane_id,
                "relevance": strength,
                "basis": "; ".join(reasons),
                "evidence_ids": list(evidence_ids),
            }
        )
    return entries


def _expand_evidence(case: dict[str, Any]) -> list[dict[str, Any]]:
    event_id = case["event"]["event_id"]
    records = []
    for item in case["evidence"]:
        records.append(
            {
                "evidence_id": item["evidence_id"],
                "event_id": event_id,
                "source_id": item["source_id"],
                "source_name": item["source_name"],
                "source_class": item["source_class"],
                "source_url": item.get("source_url"),
                "source_record_id": item.get("source_record_id"),
                "claim": item["claim"],
                "claim_type": item["claim_type"],
                "evidence_role": item["evidence_role"],
                "relation": item["relation"],
                "strength": item["strength"],
                "scope_supported": item["scope_supported"],
                "event_date": case["event"].get("event_date"),
                "publication_date": item.get("publication_date"),
                "retrieved_at": case["assessment_cutoff"],
                "revised_at": None,
                "content_sha256": _evidence_hash(item),
                "parser_version": "historical_case_v1",
                "source_revision": None,
                "licence_status": "pending_review",
                "redistribution_status": "link_only",
                "raw_snapshot_path": None,
                "known_limitations": [
                    "Historical validation fixture. The publisher's content was NOT retrieved "
                    "under WO-010 because no source was reachable from the execution "
                    "environment; the original source URL is retained so the claim can be "
                    "verified independently.",
                    "The content hash covers this repository's record of the claim, not a "
                    "retrieved publisher response.",
                ],
            }
        )
    return records


def _evidence_hash(item: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps(item, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    events: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for case in cases:
        source = case["event"]
        evidence_records = _expand_evidence(case)
        evidence.extend(evidence_records)
        evidence_ids = [record["evidence_id"] for record in evidence_records]

        completeness, missing = evaluate_transmission_chain(
            source["event_class"], source["transmission_chain"]
        )
        key = cluster_key(
            {
                "event_type": source["event_type"],
                "event_date": source.get("event_date"),
                "geography_ids": source["geography_ids"],
                "operator_or_entity": source.get("operator_or_entity"),
                "title": source["title"],
            }
        )
        scope = _geographic_scope(source)

        event = {
            "event_id": source["event_id"],
            "canonical_event_id": f"CEVT-{key[:16]}",
            "title": source["title"],
            "event_class": source["event_class"],
            "event_type": source["event_type"],
            "lifecycle_status": source["lifecycle_status"],
            "event_date": source.get("event_date"),
            "event_end_date": source.get("event_end_date"),
            "publication_date": source.get("publication_date"),
            "retrieval_date": case["assessment_cutoff"],
            "geography_ids": source["geography_ids"],
            "country_ids": source.get("country_ids", []),
            "node_ids": source.get("node_ids", []),
            "chokepoint_ids": source.get("chokepoint_ids", []),
            "modes": source["modes"],
            "operator_or_entity": source.get("operator_or_entity"),
            "lane_relevance": _lane_relevance(source, evidence_ids),
            "thailand_relevance": source["thailand_relevance"],
            "thailand_relevance_basis": source.get("thailand_relevance_basis", []),
            "evidence_ids": evidence_ids,
            "conflicting_evidence": source.get("conflicting_evidence", []),
            "transmission_chain": {
                **source["transmission_chain"],
                "completeness": completeness,
                "missing_links": missing,
                "supporting_indicator_ids": source.get("supporting_indicator_ids", []),
            },
            "impact_assessments": _expand_impacts(case, scope),
            "event_severity": source.get("event_severity", "not_assessed"),
            "scenarios": None,
            "preparedness_options": source.get("preparedness_options", []),
            "negative_operational_evidence": bool(source.get("negative_operational_evidence")),
            "known_limitations": [
                f"Historical validation case {case['case_id']}, assessed at cutoff "
                f"{case['assessment_cutoff']}. Later knowledge is deliberately excluded.",
                case["expectations"]["hindsight_limitation"],
            ],
            "last_reviewed_at": case["assessment_cutoff"],
            "closure_basis": source.get("closure_basis"),
            "publication_status": source["publication_status"],
            "human_review": source["human_review"],
            "clustering": {
                "cluster_id": cluster_id_from_key(key),
                "cluster_key": key,
                "canonical_source_url": evidence_records[0].get("source_url")
                if evidence_records
                else None,
                "title_normalized": source["title"].lower(),
                "merge_status": "unmatched",
                "merged_event_ids": [],
            },
            "methodology_version": "0.8",
            "first_seen_at": case["assessment_cutoff"],
            "last_seen_at": case["assessment_cutoff"],
            "supersedes": [],
        }
        events.append(event)

    events.sort(key=lambda item: item["event_id"])
    evidence.sort(key=lambda item: item["evidence_id"])
    return events, evidence


def render(kind: str, records: list[dict[str, Any]]) -> str:
    return (
        json.dumps(
            {
                "version": "0.8",
                "generated_by": "scripts/build_events_from_cases.py",
                "source_note": (
                    "Expanded from data/validation/historical_cases.json. Evidence content "
                    "was not retrieved under WO-010; original publisher URLs are retained "
                    "for independent verification."
                ),
                "record_count": len(records),
                kind: records,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify without writing.")
    args = parser.parse_args()

    events, evidence = build()
    targets = [
        (EVENTS_PATH, render("events", events)),
        (EVIDENCE_PATH, render("evidence", evidence)),
    ]

    stale = []
    for path, rendered in targets:
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        written = len(events) if "events" in path.name else len(evidence)
        print(f"{path.relative_to(ROOT)}: {written} records")

    if args.check:
        if stale:
            print("Event records are out of date with the authored cases:")
            for path_name in stale:
                print(f"  - {path_name}")
            return 1
        print("Event records are up to date with the authored cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
