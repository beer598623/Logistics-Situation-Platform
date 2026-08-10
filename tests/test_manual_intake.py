"""Tests for scripts/manual_intake.py (WO-047 / Issue #89, item 6).

Every test here uses only synthetic/fixture data and writes only to
``tmp_path`` -- never to the repository's real ``data/documents/`` or
``data/claims/``, matching the Work Order's explicit prohibition on writing
real content there. This module proves the capability; a human uses it later
for the real, D-2/D-6-gated intake exercise (Issue #89 item 8, out of scope
here).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.manual_intake import build_manual_intake, write_intake

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))


def _base_kwargs(registry: dict, **overrides) -> dict:
    base = dict(
        source_id="MANUAL_NOTICE_INTAKE",
        document_type="official_notice",
        title="STRUCTURAL EXAMPLE: berth suspension notice",
        publisher="Port Authority of Aurelia (STRUCTURAL EXAMPLE)",
        canonical_url="https://example.invalid/notices/1",
        published_at="2026-08-10T08:00:00Z",
        published_at_precision="datetime",
        reviewer_record="Jane Reviewer (STRUCTURAL EXAMPLE)",
        reviewed_at="2026-08-10T09:00:00Z",
        manual_review_event_id="MAN-20260810T090000Z-MANUAL_NOTICE_INTAKE",
        claims=[
            {
                "claim_text": "STRUCTURAL EXAMPLE: the authority states berths 3-5 are suspended.",
                "claim_type": "official_notice",
                "claim_scope": "facility",
                "primary_for_this_claim": True,
            }
        ],
        registry=registry,
    )
    base.update(overrides)
    return base


def test_builds_valid_document_and_claim(registry):
    document, claims = build_manual_intake(**_base_kwargs(registry))
    assert document["document_id"].startswith("DOC-20260810-")
    assert document["source_id"] == "MANUAL_NOTICE_INTAKE"
    assert document["evidence_origin"] == "human_reviewed_manual"
    assert document["rights"]["publication_use"] == "bounded_claim_and_link_only"
    assert len(claims) == 1
    claim = claims[0]
    assert claim["claim_id"].startswith("CLM-20260810-")
    assert claim["document_id"] == document["document_id"]
    assert claim["source_id"] == document["source_id"]
    assert claim["evidence_layer"] == document["evidence_layer"]
    assert claim["independence_group"] == document["independence_group"]


def test_multiple_claims_get_distinct_sequential_ids(registry):
    kwargs = _base_kwargs(
        registry,
        claims=[
            {
                "claim_text": "STRUCTURAL EXAMPLE: claim one.",
                "claim_type": "official_notice",
                "claim_scope": "facility",
            },
            {
                "claim_text": "STRUCTURAL EXAMPLE: claim two.",
                "claim_type": "reported_claim",
                "claim_scope": "facility",
                "attributed_to": {"name": None, "role": "operator", "is_named": False},
            },
        ],
    )
    _document, claims = build_manual_intake(**kwargs)
    ids = [claim["claim_id"] for claim in claims]
    assert len(ids) == len(set(ids))


def test_existing_ids_are_respected_for_sequencing(registry):
    kwargs = _base_kwargs(
        registry,
        existing_document_ids=["DOC-20260810-001", "DOC-20260810-002"],
        existing_claim_ids=["CLM-20260810-0001"],
    )
    document, claims = build_manual_intake(**kwargs)
    assert document["document_id"] == "DOC-20260810-003"
    assert claims[0]["claim_id"] == "CLM-20260810-0002"


def test_disallowed_source_is_refused(registry):
    """A manual-access-method source whose qualification does not (or no
    longer) mark manual_intake_status 'allowed' is refused -- distinct from,
    and checked after, the access_method gate covered below."""
    restricted_registry = json.loads(json.dumps(registry))
    for source in restricted_registry["sources"]:
        if source["id"] == "MANUAL_NOTICE_INTAKE":
            source["qualification"]["manual_intake_status"] = "not_allowed"
    kwargs = _base_kwargs(restricted_registry)
    with pytest.raises(ValueError, match="manual_intake_status"):
        build_manual_intake(**kwargs)


def test_non_manual_access_method_is_refused(registry):
    kwargs = _base_kwargs(registry, source_id="PAT_NOTICE")
    with pytest.raises(ValueError, match="access_method"):
        build_manual_intake(**kwargs)


def test_underlying_publisher_required_is_enforced(registry):
    kwargs = _base_kwargs(registry, publisher="   ")
    with pytest.raises(ValueError, match="underlying publisher"):
        build_manual_intake(**kwargs)


def test_downward_evidence_layer_override_is_accepted(registry):
    """MANUAL_NOTICE_INTAKE's registry default is current_evidence; recording
    one specific document as context (e.g. an opinion piece) is a legal
    downward override."""
    kwargs = _base_kwargs(registry, evidence_layer_override="context")
    document, _claims = build_manual_intake(**kwargs)
    assert document["evidence_layer"] == "context"
    assert document["evidence_layer_basis"] is not None


def test_upward_evidence_layer_override_is_refused(registry):
    """An override may only move downward (document.schema.json's
    evidence_layer_basis contract) -- promoting a document above its
    source's registry default would let intake quietly bypass the L3
    firewall for that document."""
    demoted_registry = json.loads(json.dumps(registry))
    for source in demoted_registry["sources"]:
        if source["id"] == "MANUAL_NOTICE_INTAKE":
            source["governance"]["evidence_layer"] = "context"
    kwargs = _base_kwargs(demoted_registry, evidence_layer_override="current_evidence")
    with pytest.raises(ValueError, match="upward"):
        build_manual_intake(**kwargs)


def test_no_claims_is_refused(registry):
    kwargs = _base_kwargs(registry, claims=[])
    with pytest.raises(ValueError, match="at least one claim"):
        build_manual_intake(**kwargs)


def test_write_intake_creates_combined_files(registry, tmp_path):
    document, claims = build_manual_intake(**_base_kwargs(registry))
    documents_path = tmp_path / "documents.json"
    claims_path = tmp_path / "claims.json"
    write_intake(document, claims, documents_path=documents_path, claims_path=claims_path)

    documents_payload = json.loads(documents_path.read_text(encoding="utf-8"))
    claims_payload = json.loads(claims_path.read_text(encoding="utf-8"))
    assert [item["document_id"] for item in documents_payload["documents"]] == [
        document["document_id"]
    ]
    assert [item["claim_id"] for item in claims_payload["claims"]] == [
        claim["claim_id"] for claim in claims
    ]


def test_write_intake_rejects_duplicate_document_id(registry, tmp_path):
    document, claims = build_manual_intake(**_base_kwargs(registry))
    documents_path = tmp_path / "documents.json"
    claims_path = tmp_path / "claims.json"
    write_intake(document, claims, documents_path=documents_path, claims_path=claims_path)

    document2, claims2 = build_manual_intake(
        **_base_kwargs(registry, document_id=document["document_id"])
    )
    with pytest.raises(ValueError, match="already recorded"):
        write_intake(document2, claims2, documents_path=documents_path, claims_path=claims_path)


# ---------------------------------------------------------------------------
# WO-049 / Issue #92 item 1: conduit-derived independence_group (the B-1 fix)
# ---------------------------------------------------------------------------


def test_conduit_source_derives_independence_group_from_publisher(registry):
    """MANUAL_NOTICE_INTAKE has governance.channel_role: conduit -- its
    independence_group must be derived from the underlying publisher, never
    from source_id (which used to make every Document from this source
    collapse onto IG-MANUAL_NOTICE_INTAKE, the B-1 bug this fix closes)."""
    document, claims = build_manual_intake(
        **_base_kwargs(registry, publisher="Port Authority of Aurelia (STRUCTURAL EXAMPLE)")
    )
    assert document["independence_group"] == "IG-PUB-PORT-AUTHORITY-OF-AURELIA-STRUCTURAL-EXAMPLE"
    assert document["independence_group"] != "IG-MANUAL_NOTICE_INTAKE"
    assert document["independence_basis"] is not None
    assert claims[0]["independence_group"] == document["independence_group"]


def test_two_distinct_publishers_through_the_conduit_yield_two_independence_groups(registry):
    """STRUCTURAL EXAMPLE (the B-1 regression, acceptance A-10): two
    Documents from two distinct underlying publishers, both ingested through
    the same conduit source (MANUAL_NOTICE_INTAKE), must NOT share an
    independence_group."""
    document_a, _claims_a = build_manual_intake(
        **_base_kwargs(
            registry,
            publisher="Port Authority of Aurelia (STRUCTURAL EXAMPLE)",
            document_id="DOC-20260810-101",
        )
    )
    document_b, _claims_b = build_manual_intake(
        **_base_kwargs(
            registry,
            publisher="Aurelia Maritime Register (STRUCTURAL EXAMPLE)",
            document_id="DOC-20260810-102",
        )
    )
    assert document_a["independence_group"] != document_b["independence_group"]


def test_underlying_publisher_identity_key_overrides_display_string(registry):
    """A stable identity key collapses two differently-worded display names
    for the same real publisher onto one independence group, without
    depending on exact string matching."""
    document_a, _claims_a = build_manual_intake(
        **_base_kwargs(
            registry,
            publisher="Port Authority of Aurelia",
            underlying_publisher_identity_key="PORT-AUTHORITY-OF-AURELIA",
            document_id="DOC-20260810-201",
        )
    )
    document_b, _claims_b = build_manual_intake(
        **_base_kwargs(
            registry,
            publisher="PAA (official notices)",
            underlying_publisher_identity_key="PORT-AUTHORITY-OF-AURELIA",
            document_id="DOC-20260810-202",
        )
    )
    assert document_a["independence_group"] == document_b["independence_group"]


def test_originator_channel_source_keeps_registry_default_independence_group(registry):
    """A non-conduit source (governance.channel_role: originator_channel,
    17 of the 18 registered sources) is unaffected: independence_group still
    comes from the registry default, exactly as WO-047 shipped it. Every
    real ``access_method: manual`` + ``manual_intake_status: allowed``
    source today is MANUAL_NOTICE_INTAKE itself (a conduit), so this test
    exercises the originator_channel branch against a synthetic
    STRUCTURAL EXAMPLE registry entry rather than a real source_id."""
    import copy

    synthetic_registry = copy.deepcopy(registry)
    synthetic_source = copy.deepcopy(
        next(s for s in synthetic_registry["sources"] if s["id"] == "MANUAL_NOTICE_INTAKE")
    )
    synthetic_source["id"] = "SYNTH_MANUAL_ORIGINATOR"
    synthetic_source["governance"]["channel_role"] = "originator_channel"
    synthetic_source["governance"]["independence_group"] = "IG-SYNTH_MANUAL_ORIGINATOR"
    synthetic_registry["sources"].append(synthetic_source)

    document, _claims = build_manual_intake(
        **_base_kwargs(
            synthetic_registry,
            source_id="SYNTH_MANUAL_ORIGINATOR",
            publisher="Port Authority of Aurelia (STRUCTURAL EXAMPLE)",
        )
    )
    assert document["independence_group"] == "IG-SYNTH_MANUAL_ORIGINATOR"
    assert document["independence_basis"] is None


def test_publisher_authority_passthrough(registry):
    authority = {
        "authority_scope": {
            "node_ids": ["NODE-THLCH"],
            "chokepoint_ids": [],
            "country_ids": [],
            "predicate_classes": ["berth_or_facility_availability"],
        },
        "decided_by": "document_review",
        "decided_at": "2026-08-10T09:00:00Z",
        "reviewer_record": "Jane Reviewer (STRUCTURAL EXAMPLE)",
        "basis": "STRUCTURAL EXAMPLE D-12-style review act.",
    }
    document, _claims = build_manual_intake(**_base_kwargs(registry, publisher_authority=authority))
    assert document["publisher_authority"] == authority


def test_publisher_authority_defaults_to_null(registry):
    document, _claims = build_manual_intake(**_base_kwargs(registry))
    assert document["publisher_authority"] is None


def test_repository_data_documents_directory_has_no_real_content():
    """Acceptance guard: WO-047 must not write real content into
    data/documents/. An empty scaffold (zero documents/claims) is fine; any
    populated record is not, since this Work Order's manual-intake exercise
    (Issue #89 item 8) is explicitly deferred pending D-2/D-6.
    """
    documents_path = ROOT / "data" / "documents" / "documents.json"
    if documents_path.exists():
        payload = json.loads(documents_path.read_text(encoding="utf-8"))
        assert payload.get("documents", []) == []
    claims_path = ROOT / "data" / "claims" / "claims.json"
    if claims_path.exists():
        payload = json.loads(claims_path.read_text(encoding="utf-8"))
        assert payload.get("claims", []) == []
