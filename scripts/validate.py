#!/usr/bin/env python3
"""Validate repository schemas and cross-record policy constraints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def schema_registry() -> Registry:
    registry = Registry()
    for schema_path in SCHEMAS.glob("*.schema.json"):
        schema = load_json(schema_path)
        registry = registry.with_resource(schema_path.as_uri(), Resource.from_contents(schema))
        registry = registry.with_resource(schema_path.name, Resource.from_contents(schema))
    return registry


def validator(schema_name: str) -> Draft202012Validator:
    schema_path = SCHEMAS / schema_name
    schema = load_json(schema_path)
    return Draft202012Validator(
        schema,
        registry=schema_registry(),
        format_checker=FormatChecker(),
    )


def validate_item(item: Any, schema_name: str, label: str) -> bool:
    errors = sorted(
        validator(schema_name).iter_errors(item),
        key=lambda error: list(error.path),
    )
    if errors:
        print(f"[FAIL] {label}")
        for error in errors:
            location = "/".join(map(str, error.path)) or "<root>"
            print(f"  - {location}: {error.message}")
        return False
    print(f"[PASS] {label}")
    return True


def semantic_checks(event: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    impacts = event.get("impact_assessments", [])
    areas = [impact.get("area") for impact in impacts]
    required = {
        "warehouse",
        "logistics",
        "transport",
        "import_export",
        "inventory",
        "cost",
        "capacity",
        "service",
        "business_continuity",
    }
    if set(areas) != required or len(areas) != 9:
        problems.append("impact_assessments must contain each of the nine areas exactly once")

    evidence_ids = {evidence["evidence_id"] for evidence in event.get("evidence", [])}
    for evidence in event.get("evidence", []):
        if len(evidence.get("content_sha256", "")) != 64:
            problems.append(f"{evidence.get('evidence_id')}: invalid content hash")
        if not evidence.get("retrieved_at"):
            problems.append(f"{evidence.get('evidence_id')}: missing retrieval timestamp")
        if not evidence.get("parser_version"):
            problems.append(f"{evidence.get('evidence_id')}: missing parser version")

    for impact in impacts:
        unknown = set(impact.get("evidence_ids", [])) - evidence_ids
        if unknown:
            problems.append(f"{impact.get('area')}: unknown evidence IDs {sorted(unknown)}")
        if impact.get("severity") in {"high", "critical"} and impact.get(
            "evidence_strength"
        ) not in {"A", "B"}:
            problems.append(
                f"{impact.get('area')}: high/critical impact lacks primary-grade evidence"
            )
        if (
            impact.get("status") in {"observed", "potential"}
            and impact.get("severity") != "none"
            and not impact.get("transmission_mechanism")
        ):
            problems.append(f"{impact.get('area')}: missing transmission mechanism")

    if event.get("publication_status") == "No material impact detected" and not event.get(
        "negative_operational_evidence"
    ):
        problems.append("no-material-impact status requires negative operational evidence")
    return problems


def source_contract_checks(registry: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    source_ids = [source.get("id") for source in registry.get("sources", [])]
    if len(source_ids) != len(set(source_ids)):
        problems.append("source IDs must be unique")
    for source in registry.get("sources", []):
        if source.get("enabled"):
            if source.get("machine_readable_status") != "verified":
                problems.append(
                    f"{source.get('id')}: enabled source is not machine-readable verified"
                )
            if source.get("licence_status") != "reviewed":
                problems.append(f"{source.get('id')}: enabled source licence has not been reviewed")
            if not source.get("endpoint"):
                problems.append(f"{source.get('id')}: enabled source has no endpoint")
    return problems


_LIVE_SOURCE_STATUSES = {"fresh", "stale"}


def source_status_checks(source_status: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    sources = source_status.get("sources", [])

    no_data_like = {"no_data", "error", "disabled"}
    for source in sources:
        if source.get("status") in no_data_like and source.get("item_count") == 0:
            problems.append(
                f"{source.get('source_id')}: a gap must never be represented as zero items"
            )

    # A required source that is anything other than fresh/stale is a
    # publication gap, matching collectors/source_health.py's
    # _required_source_gap precedence (checked ahead of "is anything live").
    required_gap_sources = [
        source.get("source_id")
        for source in sources
        if source.get("required_for_publication")
        and source.get("status") not in _LIVE_SOURCE_STATUSES
    ]
    if required_gap_sources and source_status.get("overall_status") != "insufficient":
        problems.append(
            "required source gap must force overall_status to insufficient, not "
            f"{source_status.get('overall_status')!r} (degraded required sources: "
            f"{sorted(required_gap_sources)})"
        )

    status_by_id = {source.get("source_id"): source.get("status") for source in sources}
    required_by_id = {
        source.get("source_id"): bool(source.get("required_for_publication")) for source in sources
    }
    for capability in source_status.get("capabilities", []):
        capability_name = capability.get("capability")
        supporting = capability.get("supporting_sources", [])
        has_live_source = any(status_by_id.get(sid) in _LIVE_SOURCE_STATUSES for sid in supporting)
        degraded_required = [
            sid
            for sid in supporting
            if required_by_id.get(sid) and status_by_id.get(sid) not in _LIVE_SOURCE_STATUSES
        ]

        if capability.get("status") == "sufficient":
            if not has_live_source:
                problems.append(
                    f"{capability_name}: sufficient coverage requires a fresh or stale "
                    "supporting source"
                )
            if degraded_required:
                problems.append(
                    f"{capability_name}: sufficient coverage cannot include a degraded "
                    f"required supporting source {sorted(degraded_required)}"
                )
        elif degraded_required and capability.get("status") != "insufficient":
            problems.append(
                f"{capability_name}: a degraded required supporting source "
                f"{sorted(degraded_required)} must make coverage insufficient, "
                f"not {capability.get('status')!r}"
            )

        if not supporting:
            problems.append(f"{capability_name}: capability has no supporting sources")

    return problems


def main() -> int:
    ok = True

    candidates = load_json(ROOT / "data/candidates/latest.json")
    for index, item in enumerate(candidates.get("candidates", [])):
        ok &= validate_item(item, "candidate_event.schema.json", f"candidate[{index}]")

    reviewed = load_json(ROOT / "data/reviewed/current_events.json")
    for index, item in enumerate(reviewed.get("events", [])):
        item_ok = validate_item(item, "reviewed_event.schema.json", f"reviewed_event[{index}]")
        for problem in semantic_checks(item):
            print(f"[FAIL] reviewed_event[{index}] semantic: {problem}")
            item_ok = False
        ok &= item_ok

    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    registry_ok = validate_item(
        registry,
        "source_contract.schema.json",
        "source_contract_registry",
    )
    for problem in source_contract_checks(registry):
        print(f"[FAIL] source_contract_registry semantic: {problem}")
        registry_ok = False
    ok &= registry_ok

    source_status = load_json(ROOT / "data/source_status/latest.json")
    ok &= validate_item(source_status, "source_status.schema.json", "source_status")
    for problem in source_status_checks(source_status):
        print(f"[FAIL] source_status semantic: {problem}")
        ok = False

    print("Validation successful." if ok else "Validation failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
