"""Development-level evidence_grade computation and situation_state
transitions (WO-049 / Issue #92 items 3 and 7).

Design: Issue #91 comment (WO-048 design part 1) Sections 2.6-2.8 for
``evidence_grade``; Issue #91 comment (WO-048 design part 2) Section 3.7 for
``situation_state`` transitions.

Everything here is a pure function over a claim set, exactly like
``analysis/events.py`` and ``analysis/claims.py``: nothing writes a file,
nothing is authored directly by a human or AI (``evidence_grade`` is
"computed, never authored" per ``logistics_event.schema.json``'s own field
description; ``situation_state`` transitions other than the two
autonomous/gated ones named below are proposals a human record approves).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from analysis.claim_evidence_adapter import (
    authority_covers,
    freshness_state,
    item_strength,
    strength_basis_of,
)

#: The four user-facing grades, strongest first, plus "no grade" (None) as
#: the weakest possible value -- matches logistics_event.schema.json's own
#: evidence_grade enum. Used both to compute the Development-level grade and
#: to check a grade_override's direction (GRADE_RANK below).
GRADES = ("CONFIRMED", "CORROBORATED", "REPORTED", "ANALYTICAL_INFERENCE")

#: Rank for evidence_grade, weakest to strongest, so grade_override's
#: direction is checkable -- the same pattern as
#: scripts/manual_intake.py::_EVIDENCE_LAYER_RANK, applied to the
#: Development-level grade instead of the Document-level evidence_layer.
GRADE_RANK: dict[str | None, int] = {
    None: -1,
    "ANALYTICAL_INFERENCE": 0,
    "REPORTED": 1,
    "CORROBORATED": 2,
    "CONFIRMED": 3,
}

#: claim_type values design part 1 Section 2.6's REPORTED rule accepts.
_REPORTED_CLAIM_TYPES = frozenset(
    {
        "verified_fact",
        "official_notice",
        "official_forecast",
        "reported_claim",
        "historical_fact",
        "denial_or_correction",
    }
)

#: claim_type values that can never, on their own, support CORROBORATED
#: (design part 1 Section 2.6: "none of type analytical_inference /
#: structural_finding / discovery_lead").
_NON_CORROBORATING_CLAIM_TYPES = frozenset(
    {"analytical_inference", "structural_finding", "discovery_lead"}
)

#: contradiction_type values that cap the grade and force situation_state
#: UNCERTAIN (design part 1 Section 2.7 / part 2 Section 3.6). The other six
#: values are recorded and displayed but never degrade the assessment.
_GRADE_CAPPING_CONTRADICTION_TYPES = frozenset({"existence", "status_change"})


def _source_of(document: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    for source in (registry or {}).get("sources", []):
        if source.get("id") == document.get("source_id"):
            return dict(source)
    return {}


def eligible_claims(
    event: Mapping[str, Any],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """``Q(E)``: the claim set a Development's grade is computed from.

    Design part 1 Section 2.6: every claim in ``event.claim_ids`` where
    ``dataset == current_publication``, ``review_status == approved``, the
    claim's Document's source has ``governance.enabled_for_public_claims:
    true``, ``strength_basis == verified``, and the claim is not
    ``superseded_by`` anything. A claim whose ``claim_id`` or ``document_id``
    does not resolve is silently excluded -- it cannot be proven eligible.
    """
    eligible: list[dict[str, Any]] = []
    for claim_id in event.get("claim_ids", []) or []:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        if claim.get("dataset") != "current_publication":
            continue
        if claim.get("review_status") != "approved":
            continue
        if claim.get("superseded_by"):
            continue
        document = documents_by_id.get(claim.get("document_id"))
        if document is None:
            continue
        source = _source_of(document, registry)
        governance = source.get("governance") or {}
        if not governance.get("enabled_for_public_claims"):
            continue
        if strength_basis_of(document) != "verified":
            continue
        eligible.append(claim)
    return eligible


def independent_group_count(
    claims: Sequence[Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    """Distinct ``independence_group`` values over ``claims``' Documents.

    A best-effort count, not the full design: the S7 attribution-chain
    collapse (two independence_group values that should merge because one
    Document syndicates the other) is out of this Work Order's scope --
    ``analysis/claims.py::corroboration_independence_problems`` already
    checks that a *claim marked* ``corroborated_independent`` is honest
    about a syndication pair; this counter does not re-derive that check,
    it simply counts the frozen ``independence_group`` values present, which
    is correct whenever no syndication pair is silently mismarked.
    """
    excluded_duplicates = {
        claim.get("document_id")
        for claim in claims
        if (documents_by_id.get(claim.get("document_id")) or {}).get("duplicate_of")
    }
    groups = {
        claim.get("independence_group")
        for claim in claims
        if claim.get("document_id") not in excluded_duplicates and claim.get("independence_group")
    }
    return len(groups)


def _modal_assertion_group(claims: Sequence[Mapping[str, Any]]) -> str | None:
    """The most common non-null ``assertion_group_id`` over ``claims``, or
    ``None`` when no claim carries one (the entirely-legitimate WO-049
    starting state: ``assertion_group_id`` is new and optional)."""
    counts: dict[str, int] = {}
    for claim in claims:
        group = claim.get("assertion_group_id")
        if group:
            counts[group] = counts.get(group, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _has_capping_contradiction(event: Mapping[str, Any]) -> bool:
    for entry in event.get("conflicting_evidence", []) or []:
        if (
            entry.get("resolution_status") == "unresolved"
            and entry.get("contradiction_type") in _GRADE_CAPPING_CONTRADICTION_TYPES
        ):
            return True
    return False


def compute_evidence_grade(
    event: Mapping[str, Any],
    claims_by_id: Mapping[str, Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[str | None, list[str]]:
    """Compute one Development's ``evidence_grade``, per design part 1
    Sections 2.6-2.7.

    Returns ``(grade, basis)`` where ``basis`` is a list of human-readable
    strings explaining the winning rule -- the same style
    ``is_active_at``'s ``ActivityDecision.reason`` uses. Evaluated in order;
    first match wins. Caps (freshness, contradiction) are applied after the
    base grade is chosen, per Section 2.7 ("two independent clocks, worse
    result wins").
    """
    now = now or datetime.now(UTC)
    claims = eligible_claims(event, claims_by_id, documents_by_id, registry)
    if not claims or all(claim.get("claim_type") == "discovery_lead" for claim in claims):
        return None, ["Q(E) is empty, or every eligible claim is a discovery_lead: not gradable."]

    def _doc(claim: Mapping[str, Any]) -> Mapping[str, Any]:
        return documents_by_id.get(claim.get("document_id")) or {}

    capping_contradiction = _has_capping_contradiction(event)

    grade: str | None = None
    basis: list[str] = []

    confirming = [
        claim
        for claim in claims
        if item_strength(claim, _doc(claim), registry, now=now) == "A"
        and claim.get("claim_type") in {"verified_fact", "official_notice"}
        and authority_covers(claim, _doc(claim))
        and freshness_state(_doc(claim), registry, now=now) == "fresh"
        and not capping_contradiction
    ]
    if confirming:
        grade = "CONFIRMED"
        basis = [
            f"{confirming[0]['claim_id']}: primary, authoritative, fresh, uncontradicted "
            f"strength-A claim of type {confirming[0].get('claim_type')!r} establishes the "
            "assertion directly."
        ]

    if grade is None:
        modal_group = _modal_assertion_group(claims)
        core_set = (
            [claim for claim in claims if claim.get("assertion_group_id") == modal_group]
            if modal_group
            else claims
        )
        ig_count = independent_group_count(core_set, documents_by_id)
        strong_enough = any(
            item_strength(claim, _doc(claim), registry, now=now) in {"A", "B"} for claim in core_set
        )
        no_disqualifying_type = not any(
            claim.get("claim_type") in _NON_CORROBORATING_CLAIM_TYPES for claim in core_set
        )
        if ig_count >= 2 and strong_enough and no_disqualifying_type and not capping_contradiction:
            grade = "CORROBORATED"
            basis = [
                f"{ig_count} distinct independence groups corroborate the modal assertion "
                f"group {modal_group!r} at strength A or B."
            ]

    if grade is None:
        reported = [
            claim
            for claim in claims
            if claim.get("claim_type") in _REPORTED_CLAIM_TYPES
            and _doc(claim).get("evidence_layer") in {"current_evidence", "context"}
        ]
        if reported and independent_group_count(reported, documents_by_id) >= 1:
            grade = "REPORTED"
            basis = [
                f"{reported[0]['claim_id']}: reporting-class claim from a current_evidence- or "
                "context-layer Document, at least one independence group."
            ]

    if grade is None:
        grade = "ANALYTICAL_INFERENCE"
        basis = [
            "No claim in Q(E) reaches REPORTED's entry rule; treated as the platform's own "
            "reasoning."
        ]

    # --- caps: two independent clocks, worse result wins (Section 2.7) -----
    if capping_contradiction and grade in {"CONFIRMED", "CORROBORATED"}:
        grade = "REPORTED"
        basis.append(
            "Capped at REPORTED: an unresolved existence/status_change contradiction on the "
            "core assertion."
        )

    freshness_states = {freshness_state(_doc(claim), registry, now=now) for claim in claims}
    if "expired" in freshness_states or ("unknown" in freshness_states and grade == "CONFIRMED"):
        basis.append(
            "At least one contributing claim's Document is expired/unknown freshness; the "
            "Development should not contribute to mode_situation (Gate 0 condition 7)."
        )
    elif "stale" in freshness_states and grade in {"CONFIRMED", "CORROBORATED"}:
        grade = "REPORTED"
        basis.append("Capped at REPORTED: freshness clock -- oldest contributing claim is stale.")
    elif "ageing" in freshness_states and grade == "CONFIRMED":
        grade = "CORROBORATED"
        basis.append(
            "Capped at CORROBORATED: freshness clock -- oldest contributing claim is ageing."
        )

    return grade, basis


def grade_override_problems(events: Sequence[Mapping[str, Any]]) -> list[str]:
    """``grade_override`` may only downgrade, never upgrade (design part 1
    Section 2.8; mirrors ``scripts/manual_intake.py``'s
    ``evidence_layer_override`` directional check via ``_EVIDENCE_LAYER_RANK``).

    An override's ``to`` must rank strictly below the event's own
    (computed) ``evidence_grade``, on :data:`GRADE_RANK`'s order. An upward
    or lateral override is a validation failure, not a convention.
    """
    problems: list[str] = []
    for event in events:
        override = event.get("grade_override")
        if not override:
            continue
        event_id = event.get("event_id", "<unknown>")
        to = override.get("to")
        computed = event.get("evidence_grade")
        if GRADE_RANK.get(to, 99) >= GRADE_RANK.get(computed, -1):
            problems.append(
                f"{event_id}: grade_override.to {to!r} is not strictly weaker than the "
                f"computed evidence_grade {computed!r}; an override may only downgrade"
            )
    return problems


# ---------------------------------------------------------------------------
# situation_state transitions (item 7; design part 2 Section 3.7)
# ---------------------------------------------------------------------------

#: The five situation_state values this Work Order's pilot can actually
#: reach, per the recommendation comment: EMERGING, ACTIVE, DEVELOPING,
#: UNCERTAIN, and RESOLVED (behind the existing G-13 gate,
#: analysis/claims.py::resolved_situation_state_problems). STABLE and EASING
#: are shipped on the schema (WO-047) but their transition triggers are not
#: implemented here -- explicitly out of this Work Order's scope.
SITUATION_STATES_IN_SCOPE = ("EMERGING", "ACTIVE", "DEVELOPING", "UNCERTAIN", "RESOLVED")


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def compute_situation_state(
    event: Mapping[str, Any],
    claims: Sequence[Mapping[str, Any]],
    documents_by_id: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    grade: str | None,
    now: datetime | None = None,
) -> tuple[str | None, str]:
    """Propose a ``situation_state`` for one Development from its claim set.

    A *proposal* in every case: design part 2 Section 3.7 gates every
    transition except UNCERTAIN behind a human POST/BLOCKING review, and
    RESOLVED additionally stays behind the existing G-13 gate
    (``analysis/claims.py::resolved_situation_state_problems``), which this
    function does not bypass -- a caller that wants to *author*
    ``situation_state: RESOLVED`` on a record must still satisfy that gate.
    Returns ``(state, basis)``; ``state`` is ``None`` when no rule fires
    (the record should keep its existing/absent situation_state).
    """
    now = now or datetime.now(UTC)

    # UNCERTAIN is the one autonomous, gate-free transition -- it can only
    # ever increase caution (design part 2 Section 3.7's stated invariant).
    if _has_capping_contradiction(event):
        return "UNCERTAIN", (
            "Unresolved existence/status_change contradiction: only ever increases caution."
        )
    freshness_states = {
        freshness_state(documents_by_id.get(claim.get("document_id")) or {}, registry, now=now)
        for claim in claims
    }
    if freshness_states & {"stale", "expired", "unknown"}:
        return "UNCERTAIN", "Freshness clock: a contributing claim is stale, expired or unknown."

    active_as_of = _as_datetime(event.get("active_as_of"))
    if grade in {"CONFIRMED", "CORROBORATED"} and active_as_of and event.get("active_basis"):
        widening = [
            claim
            for claim in claims
            if _as_datetime(claim.get("event_start_at"))
            and _as_datetime(claim.get("event_start_at")) > active_as_of  # type: ignore[operator]
            and (
                set(claim.get("node_ids") or []) - set(event.get("node_ids") or [])
                or (
                    claim.get("event_end_at")
                    and (
                        event.get("event_end_date") is None
                        or str(claim.get("event_end_at"))[:10] > str(event.get("event_end_date"))
                    )
                )
            )
        ]
        if widening:
            return "DEVELOPING", (
                f"{widening[0].get('claim_id')}: a claim newer than active_as_of widens scope "
                "or extends duration."
            )
        return "ACTIVE", "Grade CONFIRMED/CORROBORATED with active_as_of/active_basis present."

    # RESOLVED is checked ahead of the generic EMERGING catch-all and
    # deliberately narrowly: the design's actual trigger ("a claim stating
    # termination") is a free-text judgement no structured field carries.
    # Widening this to every official_notice/verified_fact claim
    # (analysis/claims.py::RESOLVING_CLAIM_TYPES, used by the *authoring*
    # gate once a human has already asserted RESOLVED) would make an
    # ordinary confirming notice constantly propose RESOLVED, which is the
    # opposite of conservative. This proposal function only fires on
    # claim_type: denial_or_correction -- the one type whose very existence
    # is itself a correction of something previously asserted -- and even
    # then only as a proposal a human still has to approve, and which
    # analysis/claims.py::resolved_situation_state_problems (G-13) still
    # gates before RESOLVED may actually be authored on the record.
    resolving = [
        claim
        for claim in claims
        if claim.get("claim_type") == "denial_or_correction"
        and claim.get("contradiction_status") != "unresolved"
    ]
    if resolving:
        return "RESOLVED", (
            f"{resolving[0].get('claim_id')}: a denial_or_correction, uncontradicted claim -- "
            "proposal only; stays behind G-13's gate to actually stand."
        )

    first_seen_at = _as_datetime(event.get("first_seen_at"))
    approved_current = [
        claim
        for claim in claims
        if claim.get("evidence_layer") == "current_evidence"
        and claim.get("review_status") == "approved"
    ]
    if approved_current and grade in {"REPORTED", None}:
        if first_seen_at is None or (now - first_seen_at).total_seconds() <= 48 * 3600:
            return "EMERGING", (
                "First approved current_evidence claim within 48h of first_seen_at, grade "
                f"{grade!r}."
            )

    return None, "No transition rule fires; leave situation_state as recorded."
