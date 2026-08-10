"""The Claim x Document -> event_evidence adapter (WO-047 / Issue #89).

Design: Issue #88 comment 2 Section 6.6
(https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235496493).

``event_evidence.schema.json`` is **REUSE WITH ADAPTER**, not replaced. This
module is the deterministic projection: one :func:`project_event_evidence`
call turns one ``(Claim, Document, event_id, registry)`` tuple into exactly
one ``event_evidence``-schema-conformant dict. Nothing here writes a file or
mutates its inputs -- this is a pure function, matching the style of
``analysis/provenance.py`` and ``analysis/events.py``.

Consequence (the point of building it this way): ``analysis/``,
``scripts/build_dashboard.py``, ``scripts/validate.py`` and every existing
test keep working unchanged while the Document/Claim plane is built and
validated offline. Nothing downstream needs to know a Claim or a Document
exists.

Two fields are heuristic rather than a table lookup, and both are
documented precisely because they are the parts of the mapping most likely
to need revisiting once real (non-synthetic) documents exist:

* :func:`_evidence_role` -- discovery-source detection, L2/L3 contextual
  demotion, is_named-false contextual demotion, else confirming.
* :func:`_relation` and :func:`_strength`/:func:`_strength_basis` -- a
  simple, real (not placeholder) A-D grading per Issue #88 comment 2
  Section 8.2, deliberately conservative: nothing here can grade a claim A
  unless it is primary, current-evidence-layer, and one of
  ``verified_fact``/``official_notice``. Full multi-signal grading
  (registry ``authoritative_for`` coverage, freshness-window checks,
  contradiction-clock interaction) is deferred to a later phase; this
  heuristic is what Issue #89's item 7 calls "the simple correct version".

See ``tests/test_claim_evidence_adapter.py`` for the round-trip proof
(acceptance criterion A-2) and a precise list of the handful of fields that
cannot be byte-identical between a legacy authored fixture and this
adapter's output, with the reason for each.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Item-level evidence strength grades, weakest first. Used only for
#: readability in this module; the schema is the source of truth.
_STRENGTHS = ("A", "B", "C", "D")

#: Registry qualification.logistics_role / purposes values that mark a
#: source as a discovery-only channel (Issue #88 comment 2 Section 6.6:
#: "discovery source => discovery_only").
_DISCOVERY_MARKERS = frozenset({"news_discovery"})

#: Claim contradiction_status values that mean this specific claim is
#: actively disputing something, for relation derivation.
_CONTRADICTING_STATUSES = frozenset(
    {"unresolved", "resolved_by_primary_source", "confidence_reduced"}
)

#: Fixture evidence origins. A record with one of these origins can never
#: claim strength_basis 'verified', matching the existing rule already
#: documented on event_evidence.schema.json#/properties/strength_basis.
_FIXTURE_ORIGINS = frozenset({"synthetic_test_fixture", "historical_validation_fixture"})


def _source_entry(registry: Mapping[str, Any], source_id: str | None) -> dict[str, Any]:
    """The registry entry for ``source_id``, or ``{}`` if it does not resolve.

    Empty dict rather than ``None`` so every caller below can use ``.get``
    without a separate null check; a registry lookup miss degrades every
    derived field to its safest default instead of raising.
    """
    for source in (registry or {}).get("sources", []):
        if source.get("id") == source_id:
            return dict(source)
    return {}


def _is_discovery_source(source_entry: Mapping[str, Any]) -> bool:
    purposes = set(source_entry.get("purposes") or [])
    logistics_role = set((source_entry.get("qualification") or {}).get("logistics_role") or [])
    return bool((purposes | logistics_role) & _DISCOVERY_MARKERS)


def _evidence_role(claim: Mapping[str, Any], source_entry: Mapping[str, Any]) -> str:
    """confirming / contextual / discovery_only.

    Order matters: a discovery source is discovery_only regardless of the
    claim's own evidence_layer (a discovery lead from a current_evidence-
    layer news source is still only a lead). Otherwise, anything not at the
    current_evidence layer (context / structural_research), or attributed to
    an unnamed party, is demoted to contextual -- the L3 firewall and the
    "unnamed attribution never exceeds REPORTED" rule (Issue #88 comment 2
    Sections 3.2 and 6.2), both read at the evidence-role boundary.
    """
    if _is_discovery_source(source_entry):
        return "discovery_only"
    attributed_to = claim.get("attributed_to")
    unnamed = bool(attributed_to) and attributed_to.get("is_named") is False
    if claim.get("evidence_layer") != "current_evidence" or unnamed:
        return "contextual"
    return "confirming"


def _relation(claim: Mapping[str, Any]) -> str:
    """supports / contradicts / contextual / supersedes, from the claim's own stance.

    A denial_or_correction claim, or one already carrying an active
    contradiction_status, contradicts. A claim not at the current_evidence
    layer is contextual (mirrors _evidence_role's L2/L3 demotion -- a
    context-layer claim contextualises rather than confirms). Everything
    else supports, which is the correct default: the overwhelming majority
    of claims agree with, rather than dispute, what they describe.
    """
    if claim.get("supersedes") or claim.get("superseded_by"):
        return "supersedes"
    if (
        claim.get("claim_type") == "denial_or_correction"
        or claim.get("contradiction_status") in _CONTRADICTING_STATUSES
    ):
        return "contradicts"
    if claim.get("evidence_layer") != "current_evidence":
        return "contextual"
    return "supports"


def _strength(claim: Mapping[str, Any]) -> str:
    """A/B/C/D per Issue #88 comment 2 Section 8.2, simplified.

    Deliberately conservative and independent of retrieval/fixture status
    (strength grades the source's authority and naming, not whether this
    particular instance was actually retrieved -- that is strength_basis's
    job, computed separately by :func:`_strength_basis`):

    * D -- a discovery lead, or an L3 structural-research claim used as
      context.
    * A -- primary for this claim, current-evidence layer, and one of the
      two claim types the design reserves for a directly-established fact
      (verified_fact, official_notice).
    * B -- attributed to a *named* party, or primary but outside the
      strict A criteria above (e.g. primary but not itself the
      current-evidence layer's strongest claim type).
    * C -- everything else: an unnamed/uncharacterised secondary claim.

    Full grading (registry authoritative_for coverage, freshness-window
    checks) is deferred; this is the "simple correct version" Issue #89's
    item 7 asks for in preference to a placeholder, with the placeholder
    fallback (C for anything not clearly A/B/D) built in as the safe
    default.
    """
    if claim.get("claim_type") == "discovery_lead":
        return "D"
    if claim.get("evidence_layer") == "structural_research":
        return "D"
    primary = bool(claim.get("primary_for_this_claim"))
    if (
        primary
        and claim.get("claim_type") in {"verified_fact", "official_notice"}
        and claim.get("evidence_layer") == "current_evidence"
    ):
        return "A"
    attributed_to = claim.get("attributed_to")
    if attributed_to and attributed_to.get("is_named"):
        return "B"
    if primary:
        return "B"
    return "C"


def _strength_basis(document: Mapping[str, Any]) -> str:
    """verified / expected_at_cutoff, from the Document's own acquisition truth.

    A fixture-origin Document (synthetic_test_fixture or
    historical_validation_fixture) can never claim 'verified' -- the exact
    rule already documented on event_evidence.schema.json's own
    strength_basis field. Otherwise 'verified' only when content was
    actually retrieved or a human reviewed it directly; anything else
    (not yet retrieved, retrieval failed) is 'expected_at_cutoff'.
    """
    if document.get("evidence_origin") in _FIXTURE_ORIGINS:
        return "expected_at_cutoff"
    if document.get("retrieval_status") == "retrieved":
        return "verified"
    if document.get("evidence_origin") == "human_reviewed_manual":
        return "verified"
    return "expected_at_cutoff"


def _date_only(value: str | None) -> str | None:
    return value[:10] if value else None


def _merged_known_limitations(document: Mapping[str, Any], claim: Mapping[str, Any]) -> list[str]:
    """Document's limitations first (they describe the acquisition), then
    any claim-only limitations not already listed, deduplicated by
    first-seen order rather than sorted, so the merge is deterministic and
    reads as prose rather than a shuffled set.
    """
    merged = list(document.get("known_limitations") or [])
    for item in claim.get("known_limitations") or []:
        if item not in merged:
            merged.append(item)
    return merged


def project_event_evidence(
    claim: Mapping[str, Any],
    document: Mapping[str, Any],
    event_id: str,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministically build one event_evidence.schema.json-conformant dict.

    ``event_id`` must be one of ``claim["event_ids"]`` -- the caller
    chooses which attachment is being projected, since a claim may be
    attached to more than one event after a split (Issue #88 comment 2
    Section 6.2). ``claim["document_id"]`` and ``claim["source_id"]`` must
    agree with ``document``'s own ``document_id``/``source_id`` -- this is
    the traceability guarantee at the adapter boundary, checked here rather
    than silently trusted.

    Raises ``ValueError`` on any of those three consistency failures. Every
    other field is computed deterministically from ``claim``, ``document``
    and a registry lookup; nothing here is random, timestamped at call
    time, or otherwise non-reproducible.
    """
    if claim.get("document_id") != document.get("document_id"):
        raise ValueError(
            f"claim {claim.get('claim_id')!r} names document_id "
            f"{claim.get('document_id')!r}, which disagrees with the supplied document "
            f"{document.get('document_id')!r}"
        )
    if claim.get("source_id") != document.get("source_id"):
        raise ValueError(
            f"claim {claim.get('claim_id')!r} names source_id {claim.get('source_id')!r}, "
            f"which disagrees with document {document.get('document_id')!r}'s source_id "
            f"{document.get('source_id')!r}"
        )
    if event_id not in (claim.get("event_ids") or []):
        raise ValueError(
            f"event_id {event_id!r} is not in claim {claim.get('claim_id')!r}'s event_ids "
            f"{claim.get('event_ids')!r}"
        )

    source_entry = _source_entry(registry, document.get("source_id"))
    claim_id = str(claim["claim_id"])
    evidence_id = "EVD-" + claim_id.removeprefix("CLM-")

    return {
        "evidence_id": evidence_id,
        "event_id": event_id,
        "source_id": document.get("source_id"),
        "source_name": document.get("publisher"),
        "source_class": source_entry.get("source_class"),
        "source_url": document.get("canonical_url"),
        "source_record_id": None,
        "claim": claim.get("claim_text"),
        "claim_type": claim.get("claim_type"),
        "evidence_role": _evidence_role(claim, source_entry),
        "relation": _relation(claim),
        "strength": _strength(claim),
        "scope_supported": claim.get("claim_scope"),
        "event_date": _date_only(claim.get("event_start_at")),
        "publication_date": _date_only(document.get("published_at")),
        "retrieval_status": document.get("retrieval_status"),
        "retrieved_at": document.get("retrieved_at"),
        "revised_at": document.get("updated_at"),
        "evidence_origin": document.get("evidence_origin"),
        "dataset": document.get("dataset"),
        "content_sha256": document.get("content_sha256"),
        "content_hash_scope": document.get("content_hash_scope"),
        "strength_basis": _strength_basis(document),
        # Registry-derived, not carried on the Document itself: a Document
        # in this design has no per-record parser_version field, so the
        # adapter reads the source's currently registered parser. A
        # legacy authored fixture that used a different, fixture-specific
        # parser_version (e.g. "historical_case_v1") will therefore not
        # round-trip on this one field -- see the adapter module docstring
        # and tests/test_claim_evidence_adapter.py.
        "parser_version": source_entry.get("parser"),
        "source_revision": None,
        # Registry-derived for the same reason as parser_version. A rights
        # snapshot's own redistribution_status (below) is the field that
        # actually governs republication; licence_status here mirrors the
        # registry's current determination for the source and can validly
        # disagree with a licence_status a legacy fixture was authored
        # with at an earlier point in the registry's history.
        "licence_status": source_entry.get("licence_status"),
        "redistribution_status": (document.get("rights") or {}).get("redistribution_status"),
        "raw_snapshot_path": None,
        "known_limitations": _merged_known_limitations(document, claim),
        "collection_run_id": document.get("collection_run_id"),
        "manual_review_event_id": document.get("manual_review_event_id"),
    }
