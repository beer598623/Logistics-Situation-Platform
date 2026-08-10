"""Claim/Document/Event semantic checks (WO-047 / Issue #89, item 7).

Design: Issue #88 comment 2
(https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235496493),
Sections 3.2 (the L3 firewall) and 6.5 (corroboration_status entry rules).

Mirrors the house style of ``analysis/events.py``: pure functions returning
lists of human-readable problem strings, called from ``scripts/validate.py``
and asserted against in tests. Nothing here writes a file or raises -- a
caller decides what a non-empty problem list means.

Every check here is deliberately conservative about what it can prove absent
real committed Claim/Document data (``data/documents/`` and
``data/claims/`` are empty scaffolds under this Work Order -- see
``scripts/manual_intake.py``): a check with no claims/documents to look at
returns no problems, not a spurious failure. Each function's docstring says
so explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: The three claim_type values Issue #88 comment 2 Section 7.3 names as
#: capable of establishing that a Development has actually terminated. A
#: forecast, an inference or a bare report is not enough to silence an
#: event -- only a primary-ish statement of resolution is.
RESOLVING_CLAIM_TYPES = frozenset({"official_notice", "verified_fact", "denial_or_correction"})

#: extraction_method values that mean an AI proposed the claim (Issue #88
#: comment 2 Section 6.2's extraction_method table).
AI_EXTRACTION_METHODS = frozenset({"ai_proposed_human_approved", "ai_proposed_unreviewed"})


def l3_firewall_problems(
    events: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """The L3 (structural_research) firewall, as two concrete, testable rules.

    1. A claim whose ``evidence_layer`` is ``structural_research`` must never
       appear in an event's ``verified_facts`` array -- L3 material is
       context, never a verified current fact, however the claim's own
       ``claim_type`` happens to read.
    2. An event whose entire (non-empty) ``claim_ids`` set is L3-only must
       not carry a ``situation_state`` other than absent (``None``) or
       ``UNCERTAIN`` -- structural research alone can never make a
       Development ``ACTIVE``, ``RESOLVED``, or any other "this is
       happening" state (Issue #88 comment 2 Section 8.8: ANALYTICAL
       INFERENCE-grade evidence "may not contribute to mode Current
       Situation").

    A claim_id referenced by an event but absent from ``claims_by_id`` is
    silently skipped for rule 1 (nothing to check an unresolved reference
    against) but is NOT treated as L3 for rule 2 -- an event with any
    unresolved claim reference cannot be proven "L3-only", so rule 2 does
    not fire on it. This keeps the rule fail-quiet (not fail-open) on
    incomplete data rather than fail-closed on a reference it cannot
    actually evaluate: :func:`resolved_situation_state_problems` and
    ordinary claim-id-integrity checks are where an unresolved reference is
    itself flagged.
    """
    problems: list[str] = []
    for event in events:
        event_id = event.get("event_id", "<unknown>")

        for claim_id in event.get("verified_facts", []) or []:
            claim = claims_by_id.get(claim_id)
            if claim is not None and claim.get("evidence_layer") == "structural_research":
                problems.append(
                    f"{event_id}: verified_facts includes {claim_id!r}, whose evidence_layer "
                    "is 'structural_research'; L3 material may never appear as a verified fact "
                    "(the L3 firewall)"
                )

        claim_ids = event.get("claim_ids", []) or []
        if not claim_ids:
            continue
        resolved = [claims_by_id[cid] for cid in claim_ids if cid in claims_by_id]
        if len(resolved) != len(claim_ids):
            continue  # cannot prove L3-only with an unresolved reference present
        layers = {claim.get("evidence_layer") for claim in resolved}
        if layers != {"structural_research"}:
            continue
        situation_state = event.get("situation_state")
        if situation_state not in (None, "UNCERTAIN"):
            problems.append(
                f"{event_id}: every claim in claim_ids is evidence_layer "
                f"'structural_research', but situation_state is {situation_state!r}; an "
                "L3-only claim set may not carry an active situation_state (the L3 firewall)"
            )
    return problems


def independence_confirmation_problems(claims: Sequence[Mapping[str, Any]]) -> list[str]:
    """A claim cannot be ``officially_confirmed`` unless it is
    ``primary_for_this_claim`` (Issue #88 comment 2 Section 6.5's
    ``officially_confirmed`` entry rule: "primary_for_this_claim: true and
    the registry's authoritative_for covers the assertion"). This checks the
    half of that rule verifiable purely from the claim record itself.

    Purely per-claim: no document or registry lookup needed, so this check
    is meaningful the moment even one claim exists.
    """
    problems: list[str] = []
    for claim in claims:
        if claim.get("corroboration_status") == "officially_confirmed" and not claim.get(
            "primary_for_this_claim"
        ):
            problems.append(
                f"{claim.get('claim_id', '<unknown>')}: corroboration_status is "
                "'officially_confirmed' but primary_for_this_claim is not true; official "
                "confirmation requires the claim to be primary for its own assertion"
            )
    return problems


def corroboration_independence_problems(
    claims: Sequence[Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """A claim marked ``corroborated_independent`` must actually have a
    corroborating claim from a distinct ``independence_group`` that is not a
    syndication of it (Issue #88 comment 2 Section 6.5: "corroborated_independent:
    >=2 documents from >=2 distinct independence_group values, neither a
    syndication of the other" -- "corroborated_dependent: ... all trace to
    one originator_document_url. This is not corroboration").

    Cluster membership is approximated by shared ``event_ids`` -- the only
    structural link between claims this Work Order provides; a full
    assertion-similarity clustering engine (matching two claims as being
    about the very same fact rather than merely the same Development) is out
    of scope. A claim with no ``event_ids`` has no cluster to check against
    and is reported, not silently passed: a claim cannot honestly claim
    independent corroboration while naming nothing it is corroborated
    against.

    Two documents "trace to one originator_document_url" when either names
    the other's ``canonical_url`` as its ``originator_document_url`` -- a
    syndication pair collapses to one origin regardless of which one is
    treated as "the" originator in the pair.
    """

    def _origin_url(document: Mapping[str, Any] | None) -> str | None:
        if document is None:
            return None
        return document.get("originator_document_url") or document.get("canonical_url")

    problems: list[str] = []
    for claim in claims:
        if claim.get("corroboration_status") != "corroborated_independent":
            continue
        claim_id = claim.get("claim_id", "<unknown>")
        event_ids = set(claim.get("event_ids", []) or [])
        if not event_ids:
            problems.append(
                f"{claim_id}: corroboration_status is 'corroborated_independent' but the claim "
                "has no event_ids, so no corroborating cluster can be identified"
            )
            continue

        this_document = documents_by_id.get(claim.get("document_id"))
        this_group = claim.get("independence_group")
        this_origin = _origin_url(this_document)

        found_independent_corroborator = False
        for other in claims:
            if other is claim:
                continue
            if not (set(other.get("event_ids", []) or []) & event_ids):
                continue
            other_group = other.get("independence_group")
            if other_group == this_group:
                continue  # same independence_group: dependent, not independent
            other_document = documents_by_id.get(other.get("document_id"))
            other_origin = _origin_url(other_document)
            if this_origin is not None and other_origin == this_origin:
                continue  # traces to the same originator_document_url: a syndication
            found_independent_corroborator = True
            break

        if not found_independent_corroborator:
            problems.append(
                f"{claim_id}: corroboration_status is 'corroborated_independent' but no other "
                "claim sharing an event_id comes from a distinct independence_group that is not "
                "a syndication of this claim's document; this is at most corroborated_dependent"
            )
    return problems


def ai_date_invention_problems(claims: Sequence[Mapping[str, Any]]) -> list[str]:
    """No AI-invented dates (Issue #88 comment 2 Section 7.4: "AI may never
    infer a date. Precision must degrade, not be invented").

    Checkable purely from one claim record: for any claim whose
    ``extraction_method`` is one of the two ``ai_*`` values,

    * a null ``event_start_at`` must be paired with
      ``event_date_precision: 'unknown'`` -- "no date given" is a fine
      AI-extracted answer, but a null date paired with a *specific*
      precision (``date``/``datetime``/``month``) is an internally
      inconsistent claim: precision describes a date that, per the record,
      does not exist.
    * a non-null ``event_start_at`` must be paired with a precision other
      than ``'unknown'`` -- a stated date whose own precision is 'unknown'
      is the same inconsistency in the other direction.

    This does not (and structurally cannot) verify that a *present* date is
    actually correct -- only that the record is not self-contradictory about
    whether it has one. Full source-grounding of an AI-extracted date is a
    review-time judgement call, not a schema-adjacent check.
    """
    problems: list[str] = []
    for claim in claims:
        if claim.get("extraction_method") not in AI_EXTRACTION_METHODS:
            continue
        claim_id = claim.get("claim_id", "<unknown>")
        start_at = claim.get("event_start_at")
        precision = claim.get("event_date_precision")
        if start_at is None and precision != "unknown":
            problems.append(
                f"{claim_id}: AI-extracted claim has a null event_start_at but "
                f"event_date_precision {precision!r}, not 'unknown'; an absent AI-extracted "
                "date must be recorded as unknown precision, never invented"
            )
        if start_at is not None and precision == "unknown":
            problems.append(
                f"{claim_id}: AI-extracted claim states event_start_at {start_at!r} but "
                "event_date_precision 'unknown'; a stated date must carry a real precision"
            )
    return problems


def resolved_situation_state_problems(
    events: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """``situation_state: RESOLVED`` requires a qualifying, uncontradicted
    claim (Issue #88 comment 2 Section 7.3: "An event never becomes RESOLVED
    by timing out").

    An event with ``situation_state == 'RESOLVED'`` must have ``claim_ids``
    containing at least one claim whose ``claim_type`` is one of
    :data:`RESOLVING_CLAIM_TYPES` AND whose ``contradiction_status`` is not
    ``'unresolved'`` -- a claim the platform itself still records as
    unresolved-contradicted cannot be the evidence that settles an event
    (Issue #89 item 9(b)). This is a cross-record check: it needs the
    actual claim records ``claim_ids`` names, not just the ID strings, so it
    only bites once real events reference real claims (``data/claims/`` is
    an empty scaffold under this Work Order -- see docs/known_data_gaps.md).
    With an empty ``claims_by_id`` and any RESOLVED event that names
    claim_ids, this fails closed (an unresolved reference is reported, not
    silently ignored) rather than passing vacuously.
    """
    problems: list[str] = []
    for event in events:
        if event.get("situation_state") != "RESOLVED":
            continue
        event_id = event.get("event_id", "<unknown>")
        claim_ids = event.get("claim_ids", []) or []
        if not claim_ids:
            problems.append(
                f"{event_id}: situation_state is 'RESOLVED' but claim_ids is empty; RESOLVED "
                f"requires at least one claim of type {sorted(RESOLVING_CLAIM_TYPES)}"
            )
            continue
        unresolved = [cid for cid in claim_ids if cid not in claims_by_id]
        if unresolved:
            problems.append(
                f"{event_id}: situation_state is 'RESOLVED' but claim_ids references claims "
                f"that do not resolve: {sorted(unresolved)}"
            )
        qualifying = [
            cid
            for cid in claim_ids
            if cid in claims_by_id and claims_by_id[cid].get("claim_type") in RESOLVING_CLAIM_TYPES
        ]
        if not qualifying:
            problems.append(
                f"{event_id}: situation_state is 'RESOLVED' but none of claim_ids "
                f"{sorted(claim_ids)} has a claim_type in {sorted(RESOLVING_CLAIM_TYPES)}"
            )
            continue
        uncontradicted_qualifying = [
            cid
            for cid in qualifying
            if claims_by_id[cid].get("contradiction_status") != "unresolved"
        ]
        if not uncontradicted_qualifying:
            problems.append(
                f"{event_id}: situation_state is 'RESOLVED' but every qualifying claim in "
                f"claim_ids {sorted(qualifying)} has contradiction_status 'unresolved'; an "
                "event cannot be settled on the strength of a claim the platform itself still "
                "records as unresolved-contradicted"
            )
    return problems


def regional_scope_thailand_relevance_problems(
    claims: Sequence[Mapping[str, Any]],
) -> list[str]:
    """A ``region``-scope claim does not, by itself, allow
    ``thailand_relevance_asserted: asserted_by_source`` to stand unchallenged
    (Issue #88 comment 2 Section 6.2: "A region-scope claim can never alone
    support a Thailand-scope conclusion").

    A source can assert facts about a region; it cannot, from a region-scope
    assertion alone, be treated as having asserted a Thailand-specific
    effect -- that requires either a narrower scope (``country``/``lane``/
    ``node``/... naming Thailand specifically) or the platform's own
    inference (``inferred_by_platform``), which is exactly what
    ``thailand_relevance_asserted`` exists to keep distinct.
    """
    problems: list[str] = []
    for claim in claims:
        if (
            claim.get("claim_scope") == "region"
            and claim.get("thailand_relevance_asserted") == "asserted_by_source"
        ):
            problems.append(
                f"{claim.get('claim_id', '<unknown>')}: claim_scope is 'region' but "
                "thailand_relevance_asserted is 'asserted_by_source'; a region-scope claim "
                "cannot by itself support an asserted-by-source Thailand relevance -- use "
                "'inferred_by_platform' or narrow the scope"
            )
    return problems


def claim_document_consistency_problems(
    claims: Sequence[Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Every claim's ``document_id`` must resolve, and ``source_id`` /
    ``evidence_layer`` / ``independence_group`` must agree with the
    Document they were frozen from (Issue #88 comment 2 Section 6.2:
    evidence_layer and independence_group are "copied from the Document and
    frozen on the claim"). Also checks ``quotation_used.used`` against the
    Document's ``rights.quotation_allowed`` -- ``claim.schema.json``'s own
    field description says this cross-record agreement "is checked in
    scripts/validate.py, not this schema".
    """
    problems: list[str] = []
    for claim in claims:
        claim_id = claim.get("claim_id", "<unknown>")
        document_id = claim.get("document_id")
        document = documents_by_id.get(document_id)
        if document is None:
            problems.append(
                f"{claim_id}: document_id {document_id!r} does not resolve in the document set"
            )
            continue
        if claim.get("source_id") != document.get("source_id"):
            problems.append(
                f"{claim_id}: source_id {claim.get('source_id')!r} disagrees with document "
                f"{document_id!r}'s source_id {document.get('source_id')!r}"
            )
        if claim.get("evidence_layer") != document.get("evidence_layer"):
            problems.append(
                f"{claim_id}: evidence_layer {claim.get('evidence_layer')!r} disagrees with "
                f"document {document_id!r}'s evidence_layer {document.get('evidence_layer')!r}"
            )
        if claim.get("independence_group") != document.get("independence_group"):
            problems.append(
                f"{claim_id}: independence_group {claim.get('independence_group')!r} disagrees "
                f"with document {document_id!r}'s independence_group "
                f"{document.get('independence_group')!r}"
            )
        quotation_used = claim.get("quotation_used") or {}
        if quotation_used.get("used") and not (document.get("rights") or {}).get(
            "quotation_allowed"
        ):
            problems.append(
                f"{claim_id}: quotation_used.used is true but document {document_id!r}'s "
                "rights.quotation_allowed is not true; a quotation may only be used when the "
                "Document's rights explicitly permit it"
            )
    return problems
