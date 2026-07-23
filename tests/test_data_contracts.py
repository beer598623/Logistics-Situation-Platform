from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from collectors.event_identity import compute_content_signature
from collectors.http_client import ResilientHttpClient
from collectors.models import CollectionRun
from collectors.registry import load_registry, validate_registry

ROOT = Path(__file__).resolve().parents[1]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_source_registry_contract_is_valid() -> None:
    registry = load_registry()
    assert validate_registry(registry) == []
    assert all(source["enabled"] is False for source in registry["sources"])


def test_collection_run_dry_run_is_schema_valid() -> None:
    registry = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    source = registry["sources"][0]
    run = CollectionRun.dry_run(source["id"], source["parser"], source["endpoint"]).to_dict()
    validator = Draft202012Validator(
        load_schema("collection_run.schema.json"), format_checker=FormatChecker()
    )
    assert list(validator.iter_errors(run)) == []
    assert run["records_received"] is None


def test_source_status_does_not_claim_all_clear() -> None:
    status = json.loads((ROOT / "data" / "source_status" / "latest.json").read_text())
    assert status["overall_status"] == "insufficient"
    assert status["sources"]
    assert all(source["status"] == "disabled" for source in status["sources"])


def test_evidence_has_reproducibility_fields() -> None:
    data = json.loads((ROOT / "data" / "reviewed" / "current_events.json").read_text())
    evidence = data["events"][0]["evidence"][0]
    assert len(evidence["content_sha256"]) == 64
    assert evidence["retrieved_at"].endswith("Z")
    assert evidence["parser_version"] == "manual_review_v1"


def test_sha256_is_deterministic() -> None:
    assert (
        ResilientHttpClient.sha256(b"logistics")
        == "8880894de4fc1864c60ed6af5dc8afb16fd41c113688bc2620950259515e610e"
    )


def test_candidate_and_reviewed_event_share_canonical_identity() -> None:
    candidates = json.loads((ROOT / "data" / "candidates" / "latest.json").read_text())
    reviewed = json.loads((ROOT / "data" / "reviewed" / "current_events.json").read_text())
    candidate = candidates["candidates"][0]
    event = reviewed["events"][0]

    assert candidate["canonical_event_id"] == event["canonical_event_id"]
    assert candidate["event_fingerprint"] == event["event_fingerprint"]
    assert candidate["canonical_event_id"].startswith("CEVT-")
    assert len(candidate["event_fingerprint"]) == 64
    assert event["merge_status"] in {
        "unmatched",
        "matched_external_id",
        "matched_fingerprint",
        "merge_suggested",
        "merged_approved",
        "split_required",
    }
    assert candidate["supersedes"] == []
    assert event["supersedes"] == []


def test_source_status_capabilities_are_purpose_aware() -> None:
    status = json.loads((ROOT / "data" / "source_status" / "latest.json").read_text())
    assert status["capabilities"]
    for capability in status["capabilities"]:
        assert capability["supporting_sources"]
        assert capability["status"] in {"sufficient", "limited", "insufficient"}


def test_content_signature_matches_its_documented_source_fields() -> None:
    """The persisted ``content_signature`` on each fixture must be
    reproducible from exactly the fields documented in
    docs/source_health_and_event_identity.md: title + raw_claims (+
    headline_summary) for a candidate, title + verified_facts +
    reported_claims for a reviewed event. This is what lets
    ``last_changed_at`` recompute correctly after a real JSON round trip."""
    candidates = json.loads((ROOT / "data" / "candidates" / "latest.json").read_text())
    reviewed = json.loads((ROOT / "data" / "reviewed" / "current_events.json").read_text())
    candidate = candidates["candidates"][0]
    event = reviewed["events"][0]

    assert len(candidate["content_signature"]) == 64
    assert candidate["content_signature"] == compute_content_signature(
        title=candidate["title"],
        text_fields=[candidate["headline_summary"], *candidate["raw_claims"]],
    )

    assert len(event["content_signature"]) == 64
    assert event["content_signature"] == compute_content_signature(
        title=event["title"],
        text_fields=[*event["verified_facts"], *event["reported_claims"]],
    )
