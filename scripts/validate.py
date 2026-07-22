#!/usr/bin/env python3
"""Validate repository schemas and cross-record policy constraints."""

from __future__ import annotations

import json
import sys
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
        schema, registry=schema_registry(), format_checker=FormatChecker()
    )


def validate_item(item: Any, schema_name: str, label: str) -> bool:
    errors = sorted(validator(schema_name).iter_errors(item), key=lambda error: list(error.path))
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
        if (
            impact.get("severity") in {"high", "critical"}
            and impact.get("evidence_strength") not in {"A", "B"}
        ):
            problems.append(f"{impact.get('area')}: high/critical impact lacks primary-grade evidence")
        if (
            impact.get("status") in {"observed", "potential"}
            and impact.get("severity") != "none"
            and not impact.get("transmission_mechanism")
        ):
            problems.append(f"{impact.get('area')}: missing transmission mechanism")

    if (
        event.get("publication_status") == "No material impact detected"
        and not event.get("negative_operational_evidence")
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
                problems.append(f"{source.get('id')}: enabled source is not machine-readable verified")
            if source.get("licence_status") != "reviewed":
                problems.append(f"{source.get('id')}: enabled source licence has not been reviewed")
            if not source.get("endpoint"):
                problems.append(f"{source.get('id')}: enabled source has no endpoint")
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
        registry, "source_contract.schema.json", "source_contract_registry"
    )
    for problem in source_contract_checks(registry):
        print(f"[FAIL] source_contract_registry semantic: {problem}")
        registry_ok = False
    ok &= registry_ok

    source_status = load_json(ROOT / "data/source_status/latest.json")
    ok &= validate_item(source_status, "source_status.schema.json", "source_status")
    if source_status.get("overall_status") == "sufficient" and any(
        source.get("status") in {"no_data", "error"}
        and source.get("required_for_publication")
        for source in source_status.get("sources", [])
    ):
        print("[FAIL] source_status semantic: required source gap cannot be sufficient")
        ok = False

    print("Validation successful." if ok else "Validation failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
