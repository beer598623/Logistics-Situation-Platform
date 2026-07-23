from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from collectors.event_identity import (
    MalformedEventRecordError,
    compute_content_signature,
    event_date_from_candidate,
    event_date_from_reviewed_event,
    known_event_from_candidate,
    resolve_event_identity,
)
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
    assert candidate["identity_date_bucket"] == event["identity_date_bucket"]


def test_reviewed_event_promotion_from_candidate_resolves_via_explicit_mapping() -> None:
    """Regression for review finding #3: the candidate ``event_date`` /
    reviewed ``event_start`` mapping must be exercised end-to-end through
    ``resolve_event_identity``, not just asserted equal as literal values.

    This replays what a real candidate -> reviewed promotion would do:
    build a ``known_events`` entry from the stored candidate via
    ``known_event_from_candidate`` (which maps its own ``event_date``), then
    resolve the reviewed event's identity using its ``event_start`` mapped
    through ``event_date_from_reviewed_event``. The result must land on the
    same canonical event the fixtures already share.
    """
    candidates = json.loads((ROOT / "data" / "candidates" / "latest.json").read_text())
    reviewed = json.loads((ROOT / "data" / "reviewed" / "current_events.json").read_text())
    candidate = candidates["candidates"][0]
    event = reviewed["events"][0]

    known = [known_event_from_candidate(candidate)]
    resolved = resolve_event_identity(
        source_id=event.get("source_id"),
        external_event_id=event.get("external_event_id"),
        primary_category=event["primary_category"],
        geography=event["geography"],
        event_date=event_date_from_reviewed_event(event),
        publication_date=candidate["publication_date"],
        transport_modes=event["modes"],
        segments=event["segments"],
        content_signature=event["content_signature"],
        known_events=known,
    )
    assert resolved.canonical_event_id == event["canonical_event_id"]
    assert resolved.canonical_event_id == candidate["canonical_event_id"]
    assert resolved.merge_status == "matched_fingerprint"


def test_candidate_missing_event_date_fails_schema_validation() -> None:
    """Regression for the final data-contract review: ``event_date`` is a
    required (nullable) field on ``candidate_event.schema.json``, so a
    candidate that omits the key entirely — as opposed to one that carries
    ``event_date: null`` for a genuinely unknown date — must fail schema
    validation, not silently pass as if the date were merely unknown."""
    schema = load_schema("candidate_event.schema.json")
    candidates = json.loads((ROOT / "data" / "candidates" / "latest.json").read_text())
    valid_candidate = candidates["candidates"][0]
    assert "event_date" in valid_candidate

    malformed = dict(valid_candidate)
    del malformed["event_date"]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(malformed))
    assert errors
    assert any(list(error.path) == [] and "event_date" in error.message for error in errors)


def test_candidate_with_explicit_null_event_date_passes_schema_validation() -> None:
    """The nullable contract still allows a genuinely unknown date: a
    candidate with ``event_date: null`` (key present, value null) remains
    schema-valid, distinguishing "unknown" from "malformed/omitted"."""
    schema = load_schema("candidate_event.schema.json")
    candidates = json.loads((ROOT / "data" / "candidates" / "latest.json").read_text())
    candidate_with_unknown_date = dict(candidates["candidates"][0])
    candidate_with_unknown_date["event_date"] = None

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(candidate_with_unknown_date)) == []
    assert event_date_from_candidate(candidate_with_unknown_date) is None


def test_known_event_from_candidate_rejects_a_record_missing_event_date() -> None:
    """Regression for the final data-contract review: a malformed record
    (the ``event_date`` key omitted, not set to ``null``) must not be able
    to enter the unknown-date-promotion path through
    ``known_event_from_candidate`` — it must raise instead of silently
    producing ``{"event_date": None, ...}``, which would make a record
    that never passed schema validation look identical to one that
    legitimately recorded an unknown date."""
    candidates = json.loads((ROOT / "data" / "candidates" / "latest.json").read_text())
    malformed_candidate = dict(candidates["candidates"][0])
    del malformed_candidate["event_date"]

    with pytest.raises(MalformedEventRecordError):
        known_event_from_candidate(malformed_candidate)


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
