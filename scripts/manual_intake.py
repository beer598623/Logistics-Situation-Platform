#!/usr/bin/env python3
"""Manual curated intake: build a Document + Claim record set from
operator-supplied fields (WO-047 / Issue #89, item 6).

Design: Issue #88 comment 2 Sections 5 and 6
(https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235496493),
migration plan phase 2
(https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235531477).

This is the human-driven counterpart to the automated collectors under
``collectors/``: no network request is made, matching the existing
``MANUAL_NOTICE_INTAKE`` registry contract (``access_method: manual``). A
human reads a real, already-published, already-public notice at the
publisher's own site and records a bounded paraphrase of it here -- never the
full text.

:func:`build_manual_intake` is a pure function: given the operator's fields
and the source registry, it deterministically builds one Document dict and
one-or-more Claim dicts, validates every one of them against
``schemas/document.schema.json`` / ``schemas/claim.schema.json``, and raises
``ValueError`` if the source is not an allowed manual-intake source, if
``underlying_publisher_required`` is not satisfied, or if any built record
fails schema validation. It writes nothing.

:func:`write_intake` appends the built records to ``data/documents/documents.json``
and ``data/claims/claims.json`` (creating them, in the existing
``data/events/``-style single-combined-file layout, if they do not already
exist) and returns the two file paths. This repository's own governance
forbids writing real content into ``data/documents/`` from this Work Order;
that is a separate, human-directed exercise this tooling enables but does not
perform (see ``tests/test_manual_intake.py`` for coverage using only
synthetic/fixture data).

CLI usage (a thin wrapper; the function above is what should actually be
tested and reused)::

    python scripts/manual_intake.py --source-id MANUAL_NOTICE_INTAKE \\
        --document-type official_notice --title "..." --publisher "..." \\
        --canonical-url "https://..." --published-at 2026-08-10T08:00:00Z \\
        --published-at-precision datetime --reviewer-record "Jane Doe" \\
        --reviewed-at 2026-08-10T09:00:00Z \\
        --claim "claim text" --claim-type official_notice --claim-scope facility
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.contracts import schema_errors  # noqa: E402

DOCUMENTS_PATH = ROOT / "data" / "documents" / "documents.json"
CLAIMS_PATH = ROOT / "data" / "claims" / "claims.json"

_DOC_ID_RE = re.compile(r"^DOC-(\d{8})-(\d{3})$")
_CLM_ID_RE = re.compile(r"^CLM-(\d{8})-(\d{4})$")

#: Rank for evidence_layer, low to high strength, so an override's direction
#: is checkable: document.schema.json's evidence_layer_basis field documents
#: that an override "may be overridden DOWNWARD only" -- current_evidence
#: (L1) can be recorded as context (L2) or structural_research (L3) for a
#: specific document (e.g. an opinion piece from an otherwise-L1 publisher),
#: never the reverse, which would let intake quietly promote L3 material
#: into current-evidence status the L3 firewall exists to prevent.
_EVIDENCE_LAYER_RANK: dict[str, int] = {
    "current_evidence": 2,
    "context": 1,
    "structural_research": 0,
}

#: Default source_evidence_class per claim_type, for the three claim_type
#: values that have no exact counterpart in observation_common's evidenceClass
#: enum (which claim.schema.json's source_evidence_class reuses unchanged).
#: A caller may always override this via the claim spec's own
#: 'source_evidence_class' key.
_DEFAULT_EVIDENCE_CLASS_BY_CLAIM_TYPE: dict[str, str] = {
    "verified_fact": "verified_fact",
    "official_notice": "official_notice",
    "official_forecast": "official_forecast",
    "reported_claim": "reported_claim",
    "analytical_inference": "analytical_inference",
    "discovery_lead": "discovery_lead",
    "structural_finding": "analytical_inference",
    "historical_fact": "official_publication",
    "denial_or_correction": "official_notice",
}


def _next_id(
    existing_ids: Sequence[str], *, pattern: re.Pattern[str], date_part: str, width: int
) -> str:
    """Next sequence number for ``date_part`` among ``existing_ids`` matching ``pattern``.

    Scoped per calendar day, matching the ``-YYYYMMDD-NNN`` ID convention
    already used throughout this repository (``event_id``, ``COL-`` run IDs).
    """
    highest = 0
    for identifier in existing_ids:
        match = pattern.match(identifier)
        if match and match.group(1) == date_part:
            highest = max(highest, int(match.group(2)))
    return str(highest + 1).zfill(width)


def _source_entry(registry: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    for source in registry.get("sources", []):
        if source.get("id") == source_id:
            return dict(source)
    raise ValueError(f"source_id {source_id!r} is not in the source registry")


def _content_hash(*parts: Any) -> str:
    """Deterministic sha256 over the document's own authored identity.

    content_hash_scope 'authored_claim_record': this hashes this
    repository's own authored text, never a publisher's response.
    """
    canonical = json.dumps(list(parts), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_publisher_key(publisher: str) -> str:
    """Publisher name -> a stable IG-PUB-<NORMALISED> suffix.

    Upper-cases, collapses anything that is not [A-Z0-9] to a single hyphen,
    and strips leading/trailing hyphens -- deterministic and human-readable,
    matching the existing ``IG-<SOURCE_ID>`` convention's shape.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", publisher.strip()).strip("-").upper()
    return normalized or "UNKNOWN"


def build_manual_intake(
    *,
    source_id: str,
    document_type: str,
    title: str,
    publisher: str,
    canonical_url: str | None,
    published_at: str | None,
    published_at_precision: str,
    reviewer_record: str,
    reviewed_at: str,
    manual_review_event_id: str,
    claims: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    existing_document_ids: Sequence[str] = (),
    existing_claim_ids: Sequence[str] = (),
    publisher_is_originator: bool = True,
    originator_publisher: str | None = None,
    originator_document_url: str | None = None,
    access_url: str | None = None,
    language: str | None = None,
    geographies: Sequence[str] = (),
    transport_modes: Sequence[str] = (),
    topics: Sequence[str] = (),
    dataset: str = "technical_demo",
    known_limitations: Sequence[str] = (),
    evidence_layer_override: str | None = None,
    evidence_layer_basis: str | None = None,
    document_id: str | None = None,
    underlying_publisher_identity_key: str | None = None,
    publisher_authority: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build one Document and one-or-more Claim records. Writes nothing.

    ``claims`` is a sequence of operator-supplied specs, each requiring at
    least ``claim_text``, ``claim_type`` and ``claim_scope``; every other
    Claim field has a conservative default (see the body below) that a spec
    entry may override by including the same key.

    ``underlying_publisher_identity_key`` (WO-049 / Issue #92 item 1) is an
    optional operator-supplied stable identity for the underlying publisher
    -- used, when the source's ``governance.channel_role`` is ``conduit``,
    to derive ``independence_group`` instead of the already-required
    ``publisher`` display string. Two different display strings for the
    same real publisher (e.g. "Port Authority of Thailand" vs. "PAT") can
    then still collapse onto one independence group when the operator
    supplies the same key for both, without depending on exact string
    matching of the display name. ``publisher_authority`` is an optional
    ``document.schema.json``-shaped ``publisher_authority`` object (the
    D-12-style review act: what this underlying publisher is authoritative
    for); omitted, the built Document's ``publisher_authority`` stays
    ``null`` (fail-closed: no claim from it can exceed grade B).

    Raises ``ValueError`` when: the source is not a registered, allowed
    manual-intake source (``access_method: manual`` and
    ``qualification.manual_intake_status: allowed``); the registry's
    ``underlying_publisher_required`` is true and ``publisher`` is blank; or
    any built Document/Claim record fails schema validation (a fail-closed
    check redundant with, not a substitute for, the schema itself -- so a
    caller gets a precise Python exception rather than a downstream
    ``scripts/validate.py`` failure discovered later).
    """
    source = _source_entry(registry, source_id)
    if source.get("access_method") != "manual":
        raise ValueError(
            f"source_id {source_id!r} has access_method {source.get('access_method')!r}, not "
            "'manual'; the manual intake path is only for a genuinely manual, non-network source"
        )
    qualification = source.get("qualification") or {}
    if qualification.get("manual_intake_status") != "allowed":
        raise ValueError(
            f"source_id {source_id!r} does not have qualification.manual_intake_status "
            "'allowed'; manual intake is not permitted for this source"
        )
    if qualification.get("underlying_publisher_required") and not (publisher or "").strip():
        raise ValueError(
            f"source_id {source_id!r} requires the underlying publisher to be named "
            "(qualification.underlying_publisher_required is true), but publisher is blank"
        )
    if not claims:
        raise ValueError("at least one claim is required")

    governance = source.get("governance") or {}
    channel_role = governance.get("channel_role") or "originator_channel"
    registry_layer = governance.get("evidence_layer") or "context"
    layer = evidence_layer_override or registry_layer
    layer_basis = evidence_layer_basis
    if evidence_layer_override and evidence_layer_override != registry_layer:
        if _EVIDENCE_LAYER_RANK[evidence_layer_override] > _EVIDENCE_LAYER_RANK[registry_layer]:
            raise ValueError(
                f"evidence_layer_override {evidence_layer_override!r} is upward from the "
                f"registry default {registry_layer!r} for {source_id!r}; an override may only "
                "move downward (document.schema.json's evidence_layer_basis contract)"
            )
        layer_basis = layer_basis or (
            f"Manually overridden downward from the registry default "
            f"{registry_layer!r} for this specific document."
        )
    # WO-049 (Issue #92) item 1, the B-1 fix: a conduit source (governance.
    # channel_role: conduit) is not itself the publisher -- MANUAL_NOTICE_INTAKE
    # transcribes arbitrary underlying publishers, so every Document ingested
    # through it would otherwise carry the same IG-MANUAL_NOTICE_INTAKE
    # independence_group regardless of who actually published the notice,
    # making corroborated_independent structurally unreachable. For a conduit
    # source, independence_group is derived from the underlying publisher
    # identity instead: underlying_publisher_identity_key when the operator
    # supplies one (e.g. a stable slug distinct from the display name), else
    # the already-required, already-validated `publisher` string itself.
    if channel_role == "conduit":
        publisher_key = underlying_publisher_identity_key or publisher
        independence_group = f"IG-PUB-{_normalize_publisher_key(publisher_key)}"
        independence_basis = (
            f"Derived from the underlying publisher {publisher!r} because source_id "
            f"{source_id!r} has governance.channel_role: conduit -- never from source_id "
            "itself (WO-049 / Issue #92 item 1)."
        )
    else:
        independence_group = governance.get("independence_group") or f"IG-{source_id}"
        independence_basis = None

    date_part = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00")).strftime("%Y%m%d")

    if document_id is None:
        doc_sequence = _next_id(
            existing_document_ids, pattern=_DOC_ID_RE, date_part=date_part, width=3
        )
        document_id = f"DOC-{date_part}-{doc_sequence}"

    content_sha256 = _content_hash(
        document_id, source_id, title, publisher, canonical_url, published_at
    )

    rights_publication_use = qualification.get("publication_use", "publication_prohibited")
    rights_redistribution = qualification.get("redistribution_status", "unknown")

    document: dict[str, Any] = {
        "document_id": document_id,
        "source_id": source_id,
        "document_type": document_type,
        "evidence_layer": layer,
        "evidence_layer_basis": layer_basis,
        "title": title,
        "publisher": publisher,
        "publisher_is_originator": publisher_is_originator,
        "originator_publisher": originator_publisher,
        "originator_document_url": originator_document_url,
        "canonical_url": canonical_url,
        "access_url": access_url,
        "language": language,
        "published_at": published_at,
        "published_at_precision": published_at_precision,
        "updated_at": None,
        "retrieved_at": None,
        "retrieval_status": "not_applicable",
        "evidence_origin": "human_reviewed_manual",
        "content_sha256": content_sha256,
        "content_hash_scope": "authored_claim_record",
        "stored_content": "none",
        "stored_content_location": None,
        "rights": {
            "publication_use": rights_publication_use,
            "quotation_allowed": False,
            "quotation_max_words": None,
            "attribution_required": True,
            "redistribution_status": rights_redistribution,
            "decided_by": "registry_default",
            "decided_at": reviewed_at,
            "reviewer_record": None,
            "basis": (
                f"Registry default publication_use/redistribution_status recorded for "
                f"{source_id!r} at manual intake time."
            ),
        },
        "paywall_encountered": None,
        "geographies": list(geographies),
        "transport_modes": list(transport_modes),
        "topics": list(topics),
        "independence_group": independence_group,
        "independence_basis": independence_basis,
        "publisher_authority": dict(publisher_authority) if publisher_authority else None,
        "duplicate_of": None,
        "supersedes": [],
        "superseded_by": None,
        "correction_status": "none",
        "review_status": "accepted",
        "reviewer_record": reviewer_record,
        "reviewed_at": reviewed_at,
        "dataset": dataset,
        "known_limitations": list(known_limitations),
        "collection_run_id": None,
        "manual_review_event_id": manual_review_event_id,
    }
    errors = schema_errors(document, "document.schema.json")
    if errors:
        raise ValueError(f"built document {document_id} fails schema validation: {errors}")

    built_claims: list[dict[str, Any]] = []
    used_claim_ids = list(existing_claim_ids)
    for index, spec in enumerate(claims):
        claim_type = spec["claim_type"]
        claim_number = _next_id(used_claim_ids, pattern=_CLM_ID_RE, date_part=date_part, width=4)
        claim_id = spec.get("claim_id") or f"CLM-{date_part}-{claim_number}"
        used_claim_ids.append(claim_id)

        claim: dict[str, Any] = {
            "claim_id": claim_id,
            "source_id": source_id,
            "document_id": document_id,
            "event_ids": list(spec.get("event_ids", [])),
            "claim_text": spec["claim_text"],
            "claim_type": claim_type,
            "assertion": spec.get(
                "assertion",
                {
                    "subject_type": None,
                    "subject_ref": None,
                    "predicate": None,
                    "object_value": None,
                    "object_unit": None,
                },
            ),
            "event_start_at": spec.get("event_start_at"),
            "event_end_at": spec.get("event_end_at"),
            "event_date_precision": spec.get(
                "event_date_precision", "unknown" if not spec.get("event_start_at") else "date"
            ),
            "geography_ids": list(spec.get("geography_ids", [])),
            "country_ids": list(spec.get("country_ids", [])),
            "node_ids": list(spec.get("node_ids", [])),
            "chokepoint_ids": list(spec.get("chokepoint_ids", [])),
            "lane_ids": list(spec.get("lane_ids", [])),
            "measurement": spec.get(
                "measurement",
                {"value": None, "value_status": "missing", "unit": None, "currency": None},
            ),
            "source_evidence_class": spec.get(
                "source_evidence_class",
                _DEFAULT_EVIDENCE_CLASS_BY_CLAIM_TYPE.get(claim_type, "insufficient_evidence"),
            ),
            "corroboration_status": spec.get("corroboration_status", "not_assessed"),
            "contradiction_status": spec.get("contradiction_status", "none"),
            "confidence": spec.get("confidence", "low"),
            "extraction_method": spec.get("extraction_method", "human_transcription"),
            "review_status": spec.get("review_status", "approved"),
            "evidence_layer": layer,
            "primary_for_this_claim": bool(spec.get("primary_for_this_claim", False)),
            "independence_group": independence_group,
            "attributed_to": spec.get("attributed_to"),
            "thailand_relevance_asserted": spec.get("thailand_relevance_asserted", "not_asserted"),
            "claim_scope": spec["claim_scope"],
            "supersedes": list(spec.get("supersedes", [])),
            "superseded_by": spec.get("superseded_by"),
            "quotation_used": spec.get(
                "quotation_used", {"used": False, "word_count": None, "permitted_by": None}
            ),
            "dataset": dataset,
            "known_limitations": list(spec.get("known_limitations", [])),
            "extraction_prompt_version": spec.get("extraction_prompt_version"),
            "extraction_model": spec.get("extraction_model"),
        }
        errors = schema_errors(claim, "claim.schema.json")
        if errors:
            raise ValueError(
                f"built claim {claim_id} (index {index}) fails schema validation: {errors}"
            )
        built_claims.append(claim)

    return document, built_claims


def _load(path: Path, key: str) -> dict[str, Any]:
    if not path.exists():
        return {key: []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_intake(
    document: dict[str, Any],
    claims: list[dict[str, Any]],
    *,
    documents_path: Path = DOCUMENTS_PATH,
    claims_path: Path = CLAIMS_PATH,
) -> tuple[Path, Path]:
    """Append ``document`` and ``claims`` to the two combined record files.

    Matches the existing ``data/events/`` layout convention: one combined
    JSON file per record family (``events.json`` / ``event_evidence.json``),
    rather than one file per record. Raises ``ValueError`` on a duplicate
    ``document_id``/``claim_id`` rather than silently overwriting.
    """
    documents_payload = _load(documents_path, "documents")
    existing_document_ids = {item["document_id"] for item in documents_payload["documents"]}
    if document["document_id"] in existing_document_ids:
        raise ValueError(f"document_id {document['document_id']!r} already recorded")
    documents_payload["documents"].append(document)

    claims_payload = _load(claims_path, "claims")
    existing_claim_ids = {item["claim_id"] for item in claims_payload["claims"]}
    for claim in claims:
        if claim["claim_id"] in existing_claim_ids:
            raise ValueError(f"claim_id {claim['claim_id']!r} already recorded")
        existing_claim_ids.add(claim["claim_id"])
        claims_payload["claims"].append(claim)

    documents_path.parent.mkdir(parents=True, exist_ok=True)
    claims_path.parent.mkdir(parents=True, exist_ok=True)
    documents_path.write_text(json.dumps(documents_payload, indent=2) + "\n", encoding="utf-8")
    claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")
    return documents_path, claims_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--document-type", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--canonical-url", required=True)
    parser.add_argument("--published-at", default=None)
    parser.add_argument(
        "--published-at-precision",
        default="unknown",
        choices=["date", "datetime", "month", "unknown"],
    )
    parser.add_argument("--reviewer-record", required=True)
    parser.add_argument("--reviewed-at", default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--manual-review-event-id", required=True)
    parser.add_argument(
        "--claim",
        action="append",
        default=[],
        metavar="TEXT",
        help="Claim paraphrase text. Repeat --claim/--claim-type/--claim-scope together per claim.",
    )
    parser.add_argument("--claim-type", action="append", default=[])
    parser.add_argument("--claim-scope", action="append", default=[])
    parser.add_argument("--dataset", default="technical_demo")
    parser.add_argument(
        "--dry-run", action="store_true", help="Build and validate but do not write."
    )
    args = parser.parse_args()

    if not (len(args.claim) == len(args.claim_type) == len(args.claim_scope)):
        parser.error(
            "--claim, --claim-type and --claim-scope must be repeated the same number of times"
        )

    import yaml

    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    claims_spec = [
        {"claim_text": text, "claim_type": ctype, "claim_scope": scope}
        for text, ctype, scope in zip(args.claim, args.claim_type, args.claim_scope, strict=True)
    ]

    document, claims = build_manual_intake(
        source_id=args.source_id,
        document_type=args.document_type,
        title=args.title,
        publisher=args.publisher,
        canonical_url=args.canonical_url,
        published_at=args.published_at,
        published_at_precision=args.published_at_precision,
        reviewer_record=args.reviewer_record,
        reviewed_at=args.reviewed_at,
        manual_review_event_id=args.manual_review_event_id,
        claims=claims_spec,
        registry=registry,
        dataset=args.dataset,
    )

    print(f"Built document {document['document_id']} with {len(claims)} claim(s).")
    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0

    documents_path, claims_path = write_intake(document, claims)
    print(f"Wrote {documents_path.relative_to(ROOT)} and {claims_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
