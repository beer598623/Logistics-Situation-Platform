"""The Claim x Document -> event_evidence adapter (WO-047 / Issue #89; item-level
grading extended to full A-D by WO-049 / Issue #92 item 2).

Design: Issue #88 comment 2 Section 6.6
(https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235496493)
for the original heuristic; Issue #91 comment (WO-048 design part 1) Section
2 for the full A-D grading this module now also implements.

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
* :func:`_relation` and :func:`_strength`/:func:`_strength_basis` -- A-D
  grading per design part 1 Section 2.4. :func:`_strength` dispatches
  between two implementations, and the split matters: :func:`_full_strength`
  is the full heuristic WO-049 adds -- it now reads three inputs the WO-047
  placeholder never did (:func:`authority_covers`, :func:`freshness_state`,
  ``claim.contradiction_status``) -- and applies to every real (non-fixture)
  document; :func:`_legacy_strength` is the original WO-047 placeholder,
  unchanged, and applies only to a fixture-context document
  (``evidence_origin`` in :data:`_FIXTURE_ORIGINS`), which is what keeps
  the three round-trip fixtures below grading exactly as they did before
  this Work Order (see :func:`_strength`'s own docstring for why).

See ``tests/test_claim_evidence_adapter.py`` for the round-trip proof
(acceptance criterion A-2) and a precise list of the handful of fields that
cannot be byte-identical between a legacy authored fixture and this
adapter's output, with the reason for each.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

#: Item-level evidence strength grades, weakest first. Used only for
#: readability in this module; the schema is the source of truth.
_STRENGTHS = ("A", "B", "C", "D")

#: predicate_class values a claim's assertion may carry (WO-049 / Issue #92
#: item 1), reused verbatim from document.schema.json's
#: publisher_authority.authority_scope.predicate_classes and
#: claim.schema.json's assertion.predicate_class enums -- kept here too as
#: the single set both :func:`authority_covers` and any caller iterate over.
PREDICATE_CLASSES = frozenset(
    {
        "berth_or_facility_availability",
        "transit_or_passage",
        "service_schedule",
        "capacity_or_equipment",
        "customs_or_clearance",
        "tariff_or_fee",
        "sanction_or_regulation",
        "hazard_or_security",
        "labour_action",
        "structural_finding",
    }
)

#: claim.contradiction_status values that mean the claim's own core assertion
#: is still actively disputed. Full grading (Issue #91/#92, WO-048 design
#: part 1 Section 2.4) treats only 'unresolved' as disqualifying for grade A;
#: a claim that was contradicted and has since been resolved, superseded or
#: had its confidence reduced is not blocked from A on that basis alone.
_UNRESOLVED_CONTRADICTION = "unresolved"

#: Freshness states, weakest (most stale) last. Mirrors design part 1 Section
#: 2.5's table exactly: fresh <= 1x window, ageing <= 2x, stale <= 4x, expired
#: beyond that (or unknown, treated the same as stale/expired for grading).
FRESHNESS_STATES = ("fresh", "ageing", "stale", "expired", "unknown")

#: Item-level freshness cap on :func:`_full_strength`'s otherwise-computed
#: grade, per design part 1 Section 2.5's table exactly: fresh -- no cap;
#: ageing -- "A -> B" (equivalent to a cap at B, since nothing ranks above A);
#: stale -- cap at C; expired -- cap at D. ``unknown`` is grouped with
#: ``expired`` in that same table's State column ("age > 4x window, or
#: unknown"), so it takes the same D cap -- never treated more leniently than
#: a state we can positively identify.
_FRESHNESS_ITEM_CAP: dict[str, str] = {
    "fresh": "A",
    "ageing": "B",
    "stale": "C",
    "expired": "D",
    "unknown": "D",
}

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


def authority_covers(
    claim: Mapping[str, Any],
    document: Mapping[str, Any],
) -> bool:
    """Does the document's publisher_authority cover this claim's assertion?

    WO-049 (Issue #92) item 2 / design part 1 Section 2.3's two-part set
    test, with no string matching: the claim's ``assertion.predicate_class``
    must be in the authority scope's ``predicate_classes``, AND the claim
    must share a node or chokepoint with the scope, or -- only when the claim
    names neither -- share a country.

    Fail-closed by construction: a document with no ``publisher_authority``
    (the default for every conduit-sourced document until a human records
    one -- document.schema.json's own field description) covers nothing, so
    a claim from it can never satisfy this and can never reach grade A.
    """
    publisher_authority = document.get("publisher_authority")
    if not publisher_authority:
        return False
    scope = publisher_authority.get("authority_scope") or {}
    predicate_class = (claim.get("assertion") or {}).get("predicate_class")
    if predicate_class is None or predicate_class not in (scope.get("predicate_classes") or []):
        return False

    claim_nodes = set(claim.get("node_ids") or [])
    claim_chokepoints = set(claim.get("chokepoint_ids") or [])
    claim_countries = set(claim.get("country_ids") or [])
    scope_nodes = set(scope.get("node_ids") or [])
    scope_chokepoints = set(scope.get("chokepoint_ids") or [])
    scope_countries = set(scope.get("country_ids") or [])

    if claim_nodes & scope_nodes:
        return True
    if claim_chokepoints & scope_chokepoints:
        return True
    if not claim_nodes and not claim_chokepoints and (claim_countries & scope_countries):
        return True
    return False


def _reference_instant(document: Mapping[str, Any]) -> datetime | None:
    for field in ("published_at", "retrieved_at", "updated_at"):
        value = document.get(field)
        if value:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def freshness_state(
    document: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """fresh / ageing / stale / expired / unknown, per design part 1 Section 2.5.

    No new field: ``window_minutes`` is the source's registry
    ``max_stale_minutes``, which is required and populated on all 18
    sources. The reference instant is the document's ``published_at``,
    falling back to ``retrieved_at``, falling back to ``updated_at``; when
    none is set, or the source does not resolve, the answer is ``unknown``,
    which grading treats exactly as ``stale``/``expired``.
    """
    source_entry = _source_entry(registry, document.get("source_id"))
    window_minutes = source_entry.get("max_stale_minutes")
    if not window_minutes:
        return "unknown"
    reference = _reference_instant(document)
    if reference is None:
        return "unknown"
    reference_now = now or datetime.now(UTC)
    age_minutes = (reference_now - reference).total_seconds() / 60.0
    if age_minutes < 0:
        age_minutes = 0.0
    if age_minutes <= window_minutes:
        return "fresh"
    if age_minutes <= 2 * window_minutes:
        return "ageing"
    if age_minutes <= 4 * window_minutes:
        return "stale"
    return "expired"


def _legacy_strength(claim: Mapping[str, Any]) -> str:
    """The WO-047 placeholder heuristic, kept verbatim for fixture-context records.

    See :func:`_strength`'s docstring for why this path still exists and
    exactly which records take it.
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


def _weaker_strength(left: str, right: str) -> str:
    """The weaker (higher-index on :data:`_STRENGTHS`) of two item-level
    grades -- used to apply a cap: capping can only ever make a grade worse,
    never better."""
    return left if _STRENGTHS.index(left) >= _STRENGTHS.index(right) else right


def _full_strength(
    claim: Mapping[str, Any],
    document: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    now: datetime | None,
) -> str:
    """A/B/C/D in full, per design part 1 Sections 2.4 and 2.5.

    Three inputs the WO-047 placeholder lacked: :func:`authority_covers`,
    :func:`freshness_state`, and ``claim.contradiction_status``. The base
    grade (A/B/C) is computed first from everything *except* freshness --
    Section 2.4's table, keyed off ``authority_covers``, attribution and
    claim type/primacy -- evaluated in order, first match wins. The
    freshness clock (Section 2.5) is then applied as an independent cap on
    top of that base grade via :func:`_weaker_strength`: ``ageing`` caps at
    B, ``stale`` at C, ``expired`` (and ``unknown``, grouped with it by the
    Section 2.5 table) at D. This mirrors the "two independent clocks,
    worse result wins" discipline :func:`analysis.grading.compute_evidence_grade`
    already applies at Development level (Section 2.7) -- freshness must cap
    the grade a claim would otherwise reach, not just the one path to A.
    """
    if claim.get("claim_type") == "discovery_lead":
        return "D"
    if claim.get("evidence_layer") == "structural_research":
        return "D"
    source_entry = _source_entry(registry, document.get("source_id"))
    if _is_discovery_source(source_entry):
        return "D"
    if document.get("paywall_encountered"):
        return "D"
    if document.get("retrieval_status") == "retrieval_failed":
        return "D"

    primary = bool(claim.get("primary_for_this_claim"))
    claim_type = claim.get("claim_type")
    layer = claim.get("evidence_layer")
    attributed_to = claim.get("attributed_to")
    named = bool(attributed_to) and attributed_to.get("is_named") is True
    unnamed = bool(attributed_to) and attributed_to.get("is_named") is False

    covers = authority_covers(claim, document)
    freshness = freshness_state(document, registry, now=now)
    contradicted = claim.get("contradiction_status") == _UNRESOLVED_CONTRADICTION
    verified_basis = _strength_basis(document) == "verified"
    strongest_claim_type = claim_type in {"verified_fact", "official_notice"}

    near_a = (
        primary
        and layer == "current_evidence"
        and strongest_claim_type
        and not contradicted
        and verified_basis
        and not unnamed
    )
    if near_a and covers:
        base = "A"
    elif near_a:
        # near_a but authority_covers doesn't hold -- the A conditions minus
        # authority coverage, per design part 1 Section 2.4's B row (the
        # freshness half of that row's "exactly one of" is now handled
        # uniformly by the Section 2.5 cap below instead of being folded in
        # here).
        base = "B"
    elif layer == "current_evidence" and named:
        base = "B"
    elif primary and not strongest_claim_type:
        base = "B"
    else:
        base = "C"

    return _weaker_strength(base, _FRESHNESS_ITEM_CAP[freshness])


def _strength(
    claim: Mapping[str, Any],
    document: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """A/B/C/D, dispatching between the full and legacy heuristics.

    Full grading (:func:`_full_strength`, design part 1 Section 2.4) applies
    to every real (non-fixture) document -- one where ``evidence_origin`` is
    ``live_retrieved`` or ``human_reviewed_manual``. A fixture-context
    document (``evidence_origin`` in :data:`_FIXTURE_ORIGINS` --
    ``synthetic_test_fixture`` / ``historical_validation_fixture``) instead
    takes the WO-047 placeholder heuristic (:func:`_legacy_strength`)
    unchanged.

    This split is deliberate, not incidental, and mirrors a distinction the
    module already drew for ``strength_basis`` (:func:`_strength_basis`): a
    fixture-context record was authored before the publisher-identity plane
    existed, has no ``publisher_authority`` and no meaningful freshness
    window relative to *today's* wall clock (a historical-validation fixture
    is deliberately dated years in the past), so subjecting it to the full
    heuristic would silently downgrade the three round-trip fixtures already
    committed to ``event_evidence.json`` -- exactly the "if your new
    strength logic changes what those 3 specific committed records would
    grade to, you have a bug" case the round-trip test guards against. Real
    evidence (the case this Work Order actually adds capability for) always
    takes the full heuristic.
    """
    if document.get("evidence_origin") in _FIXTURE_ORIGINS:
        return _legacy_strength(claim)
    return _full_strength(claim, document, registry, now=now)


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


def strength_basis_of(document: Mapping[str, Any]) -> str:
    """Public wrapper over :func:`_strength_basis`, for the same reason as
    :func:`item_strength`."""
    return _strength_basis(document)


def item_strength(
    claim: Mapping[str, Any],
    document: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """Public wrapper over :func:`_strength`, for callers outside this module
    (WO-049 / Issue #92 item 3: :mod:`analysis.grading`'s Development-level
    ``evidence_grade`` computation reads item-level strength per claim
    without duplicating the A-D heuristic).
    """
    return _strength(claim, document, registry, now=now)


def project_event_evidence(
    claim: Mapping[str, Any],
    document: Mapping[str, Any],
    event_id: str,
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
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
    time, or otherwise non-reproducible -- ``now`` is the one exception
    (WO-049 / Issue #92 item 2's freshness clock, :func:`freshness_state`),
    and defaults to the wall clock only when the caller omits it; a caller
    that wants reproducibility (a test, a build script) should always pass
    it explicitly.
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
        "strength": _strength(claim, document, registry, now=now),
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
