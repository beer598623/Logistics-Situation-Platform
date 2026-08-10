"""``scripts/validate.py`` rules for WO-049 (Issue #92) item 10, plus item
6's status-change-vs-contradiction rule.

Mirrors the house style of ``analysis/claims.py`` and ``analysis/events.py``:
pure functions returning lists of human-readable problem strings, each
exercised by a passing and a failing fixture in
``tests/test_validate_situation_rules.py``. Every check here is checked
against *stored* fields (what a record actually says), not merely against a
recomputation of the same pure function that would have produced it -- so a
hand-edited or drifted record is genuinely catchable, not just a restatement
of a guarantee the adapter already enforces by construction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from analysis.claim_evidence_adapter import authority_covers

#: claim_type values eligible to establish a status change (design part 2
#: Section 3.6's hardest rule).
_STATUS_CHANGE_CLAIM_TYPES = frozenset({"official_notice", "verified_fact", "denial_or_correction"})


def _source_of(document: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    for source in (registry or {}).get("sources", []):
        if source.get("id") == document.get("source_id"):
            return dict(source)
    return {}


# ---------------------------------------------------------------------------
# Item 10, rule 1: the explainability walk
# ---------------------------------------------------------------------------


def explainability_walk_problems(
    situations: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry_source_ids: set[str],
) -> list[str]:
    """``status -> event -> grade -> claims -> document -> source ->
    canonical URL`` has no null link, for any ``mode_situation`` record
    with a non-``insufficient_current_evidence`` status (design part 2
    Section 3.10).
    """
    problems: list[str] = []
    for situation in situations:
        if situation.get("status") == "insufficient_current_evidence":
            continue
        situation_id = situation.get("situation_id", "<unknown>")
        for entry in situation.get("status_basis", []) or []:
            event_id = entry.get("event_id")
            event = events_by_id.get(event_id)
            if event is None:
                problems.append(f"{situation_id}: status_basis names unresolved event {event_id!r}")
                continue
            if not event.get("evidence_grade"):
                problems.append(f"{situation_id}/{event_id}: event has no evidence_grade")
            claim_ids = event.get("claim_ids") or []
            if not claim_ids:
                problems.append(f"{situation_id}/{event_id}: event has no claim_ids")
                continue
            for claim_id in claim_ids:
                claim = claims_by_id.get(claim_id)
                if claim is None:
                    problems.append(
                        f"{situation_id}/{event_id}: claim_ids names unresolved claim {claim_id!r}"
                    )
                    continue
                document_id = claim.get("document_id")
                document = documents_by_id.get(document_id)
                if document is None:
                    problems.append(
                        f"{situation_id}/{event_id}/{claim_id}: document_id {document_id!r} "
                        "does not resolve"
                    )
                    continue
                source_id = document.get("source_id")
                if source_id not in registry_source_ids:
                    problems.append(
                        f"{situation_id}/{event_id}/{claim_id}: document {document_id!r}'s "
                        f"source_id {source_id!r} does not resolve in the source registry"
                    )
                if not document.get("canonical_url"):
                    problems.append(
                        f"{situation_id}/{event_id}/{claim_id}: document {document_id!r} has no "
                        "canonical_url"
                    )
    return problems


# ---------------------------------------------------------------------------
# Item 10, rule 3: authority_covers required for grade A
# ---------------------------------------------------------------------------


def confirmed_requires_authority_coverage_problems(
    events: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """A ``logistics_event`` recorded ``evidence_grade: CONFIRMED`` must have
    at least one contributing claim whose Document's ``publisher_authority``
    actually covers it (design part 1 Section 2.6's CONFIRMED entry rule
    requires a strength-A claim, and A requires ``authority_covers``).
    Checked against the event's own *stored* ``evidence_grade`` -- a
    genuine cross-record consistency check, not a re-derivation of the same
    computation that would have produced it.
    """
    problems: list[str] = []
    for event in events:
        if event.get("evidence_grade") != "CONFIRMED":
            continue
        event_id = event.get("event_id", "<unknown>")
        covered = False
        for claim_id in event.get("claim_ids", []) or []:
            claim = claims_by_id.get(claim_id)
            if claim is None:
                continue
            document = documents_by_id.get(claim.get("document_id"))
            if document is None:
                continue
            if authority_covers(claim, document):
                covered = True
                break
        if not covered:
            problems.append(
                f"{event_id}: evidence_grade is CONFIRMED but no contributing claim's document "
                "publisher_authority covers it (authority_covers is False for all of them)"
            )
    return problems


def item_strength_a_requires_authority_coverage_problems(
    evidence_records: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """An ``event_evidence`` record's stored ``strength: A`` must agree with
    a fresh ``authority_covers`` computation on the claim/document it was
    projected from (``evidence_id`` -> ``claim_id`` via the ``EVD-``/``CLM-``
    prefix convention ``analysis/claim_evidence_adapter.py`` uses). A record
    with no resolvable claim is skipped -- this rule cannot evaluate a
    pre-Document-model legacy fixture, and does not claim to.
    """
    problems: list[str] = []
    for record in evidence_records:
        if record.get("strength") != "A":
            continue
        claim_id = "CLM-" + str(record.get("evidence_id", "")).removeprefix("EVD-")
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        document = documents_by_id.get(claim.get("document_id"))
        if document is None:
            continue
        if not authority_covers(claim, document):
            problems.append(
                f"{record.get('evidence_id')}: strength is 'A' but authority_covers is False "
                f"for claim {claim_id!r} / document {claim.get('document_id')!r}"
            )
    return problems


# ---------------------------------------------------------------------------
# Item 10, rule 4: the conduit rule
# ---------------------------------------------------------------------------


def conduit_authority_gate_problems(
    claims: Sequence[Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
) -> list[str]:
    """A ``channel_role: conduit`` source's Document must carry a non-null,
    human-decided ``publisher_authority`` before its claims can reach a
    grade above B/CORROBORATED (design part 1 Section 2.3).

    Checked against two *stored*, independently-authored fields: a claim's
    own ``corroboration_status`` and any attached event's own
    ``evidence_grade`` -- both real, catchable inconsistencies distinct
    from a recomputation of item-level strength (see
    :func:`item_strength_a_requires_authority_coverage_problems` for that
    check).
    """
    problems: list[str] = []
    for claim in claims:
        document = documents_by_id.get(claim.get("document_id"))
        if document is None:
            continue
        source = _source_of(document, registry)
        channel_role = (source.get("governance") or {}).get("channel_role", "originator_channel")
        if channel_role != "conduit" or document.get("publisher_authority"):
            continue
        claim_id = claim.get("claim_id", "<unknown>")
        if claim.get("corroboration_status") == "officially_confirmed":
            problems.append(
                f"{claim_id}: corroboration_status is 'officially_confirmed' but document "
                f"{claim.get('document_id')!r} is from a conduit source with no "
                "publisher_authority recorded"
            )
        for event_id in claim.get("event_ids", []) or []:
            event = events_by_id.get(event_id)
            if event is not None and event.get("evidence_grade") == "CONFIRMED":
                problems.append(
                    f"{claim_id}: attached to {event_id!r} whose evidence_grade is CONFIRMED, "
                    f"but document {claim.get('document_id')!r} is from a conduit source with "
                    "no publisher_authority recorded"
                )
    return problems


# ---------------------------------------------------------------------------
# Item 10, rule 5: no shared derived independence_group without a basis
# ---------------------------------------------------------------------------


def shared_independence_group_without_basis_problems(
    documents: Sequence[Mapping[str, Any]],
) -> list[str]:
    """No two distinct publishers may share a derived ``independence_group``
    without an explicit ``independence_basis`` recorded on every document in
    that shared group."""
    problems: list[str] = []
    by_group: dict[str, list[Mapping[str, Any]]] = {}
    for document in documents:
        group = document.get("independence_group")
        if group:
            by_group.setdefault(group, []).append(document)
    for group, group_documents in by_group.items():
        publishers = {document.get("publisher") for document in group_documents}
        if len(publishers) <= 1:
            continue
        for document in group_documents:
            if not document.get("independence_basis"):
                problems.append(
                    f"{document.get('document_id')}: shares independence_group {group!r} with a "
                    "document from a distinct publisher, but independence_basis is not recorded"
                )
    return problems


# ---------------------------------------------------------------------------
# Item 10, rule 6: mode_situation.status_basis non-empty
# ---------------------------------------------------------------------------


def status_basis_required_problems(situations: Sequence[Mapping[str, Any]]) -> list[str]:
    """``mode_situation.status_basis`` must be non-empty for every status
    except ``insufficient_current_evidence``."""
    problems: list[str] = []
    for situation in situations:
        status = situation.get("status")
        if status != "insufficient_current_evidence" and not situation.get("status_basis"):
            problems.append(
                f"{situation.get('situation_id', '<unknown>')}: status {status!r} requires a "
                "non-empty status_basis"
            )
    return problems


# ---------------------------------------------------------------------------
# Item 8: the impact_assessment basis fields, made a genuine checked rule
# ---------------------------------------------------------------------------

#: status -> the basis field schemas/impact_assessment.schema.json's own
#: description already claims is "required (non-null), by scripts/validate.py
#: convention" whenever that status is set. That convention had no actual
#: check behind it until this function -- see the schema field descriptions
#: this rule now makes true rather than aspirational.
_IMPACT_STATUS_BASIS_FIELD = {
    "elevated_watch": "watch_trigger",
    "no_material": "no_material_basis",
    "not_relevant": "not_relevant_basis",
}


def impact_assessment_basis_problems(events: Sequence[Mapping[str, Any]]) -> list[str]:
    """WO-049 (Issue #92) item 8: ``watch_trigger``/``no_material_basis``/
    ``not_relevant_basis`` must be non-null whenever the corresponding
    ``impact_assessment.status`` is set, per each field's own schema
    description -- but **only for a ``current_publication``-dataset event**.

    Checked against ``event.get("dataset")`` rather than every event,
    deliberately: nine of the 90 assessments WO-047 already committed use
    ``status: no_material`` with no ``no_material_basis`` (all on
    ``EVT-20240614-002``, a ``historical_validation``-dataset fixture
    authored before this field existed). Scoping this rule to
    ``current_publication`` is the same discipline every other
    dataset-sensitive rule in this module and ``analysis/grading.py`` already
    uses (e.g. :func:`analysis.grading.eligible_claims`) -- a pre-existing
    historical fixture is not retroactively held to a convention it predates,
    while every assessment this platform could actually publish today is.
    All three fields stay optional and nullable on the schema itself either
    way, so no committed record is put at risk of failing schema validation;
    this rule only strengthens what ``scripts/validate.py`` additionally
    checks on the live surface.
    """
    problems: list[str] = []
    for event in events:
        if event.get("dataset") != "current_publication":
            continue
        event_id = event.get("event_id", "<unknown>")
        for impact in event.get("impact_assessments", []) or []:
            status = impact.get("status")
            field = _IMPACT_STATUS_BASIS_FIELD.get(status)
            if field and not impact.get(field):
                problems.append(
                    f"{event_id}/{impact.get('area', '<unknown>')}: status {status!r} requires "
                    f"a non-null {field}"
                )
    return problems


# ---------------------------------------------------------------------------
# Item 6: the status-change-vs-contradiction rule
# ---------------------------------------------------------------------------


def _newest_claim(
    claim_ids: Sequence[str], claims_by_id: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    resolved = [claims_by_id[cid] for cid in claim_ids if cid in claims_by_id]
    resolved = [claim for claim in resolved if claim.get("event_start_at")]
    if not resolved:
        return None
    return max(resolved, key=lambda claim: str(claim.get("event_start_at")))


def is_status_change(
    older_claim_ids: Sequence[str],
    newer_claim_ids: Sequence[str],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Design part 2 Section 3.6's hardest rule: a newer claim opposing an
    older one is a *status change*, not a contradiction, iff all of: it is
    strictly newer by ``published_at``; its ``claim_type`` is one of
    :data:`_STATUS_CHANGE_CLAIM_TYPES`; and its publisher's authority scope
    covers the assertion (``authority_covers``). Otherwise it is a
    contradiction. A simplification of "covers at least as well as the
    older claim's" to "covers the assertion at all" -- the full superset
    comparison needs no new data this Work Order does not already have, but
    is not built here; see the module docstring's honesty note.
    """
    newer = _newest_claim(newer_claim_ids, claims_by_id)
    older = _newest_claim(older_claim_ids, claims_by_id)
    if newer is None:
        return False
    newer_document = documents_by_id.get(newer.get("document_id"))
    if newer_document is None:
        return False
    newer_published_at = newer_document.get("published_at")
    if older is None:
        # No side-A claim carries an event_start_at baseline (_newest_claim
        # returned None): the strictly-newer-by-published_at requirement
        # cannot be established at all. Fail closed -- never classify as
        # status_change -- rather than silently skipping the check as though
        # it were satisfied.
        return False
    older_document = documents_by_id.get(older.get("document_id"))
    older_published_at = (older_document or {}).get("published_at")
    if not newer_published_at or (older_published_at and newer_published_at <= older_published_at):
        return False
    if newer.get("claim_type") not in _STATUS_CHANGE_CLAIM_TYPES:
        return False
    return authority_covers(newer, newer_document)


def status_change_classification_problems(
    events: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """An entry marked ``contradiction_type: status_change`` must actually
    satisfy :func:`is_status_change`. Checked in one direction only
    (mislabelled-as-status_change is caught; a structurally-qualifying pair
    left under a different type is not, since a simplified classifier
    cannot safely assert the reviewer's intent was wrong) -- see
    :func:`is_status_change`'s docstring.
    """
    problems: list[str] = []
    for event in events:
        event_id = event.get("event_id", "<unknown>")
        for index, entry in enumerate(event.get("conflicting_evidence", []) or []):
            if entry.get("contradiction_type") != "status_change":
                continue
            side_a = entry.get("claim_ids_side_a") or []
            side_b = entry.get("claim_ids_side_b") or []
            if not side_a or not side_b:
                continue
            if not is_status_change(side_a, side_b, claims_by_id, documents_by_id):
                problems.append(
                    f"{event_id}/conflicting_evidence[{index}]: marked contradiction_type "
                    "'status_change' but the newest side_b claim does not satisfy the "
                    "status-change-vs-contradiction rule (strictly newer, a resolving claim "
                    "type, and authority_covers)"
                )
    return problems


# ---------------------------------------------------------------------------
# conflicting_evidence.resolution_basis (item 6, additive field rule)
# ---------------------------------------------------------------------------


def conflicting_evidence_resolution_basis_problems(
    events: Sequence[Mapping[str, Any]],
) -> list[str]:
    """``resolution_basis`` must be non-empty whenever ``resolution_status``
    is not ``unresolved`` -- already schema-enforced (an ``allOf`` on
    ``logistics_event.schema.json#/properties/conflicting_evidence/items``),
    restated here as a named, independently-testable rule per item 10's
    convention, matching how ``document.schema.json``'s rights fail-closed
    composition is proven both by schema and by a named test.
    """
    problems: list[str] = []
    for event in events:
        event_id = event.get("event_id", "<unknown>")
        for index, entry in enumerate(event.get("conflicting_evidence", []) or []):
            if entry.get("resolution_status") != "unresolved" and not entry.get("resolution_basis"):
                problems.append(
                    f"{event_id}/conflicting_evidence[{index}]: resolution_status "
                    f"{entry.get('resolution_status')!r} requires a non-empty resolution_basis"
                )
    return problems
