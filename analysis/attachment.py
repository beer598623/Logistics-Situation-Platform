"""The minimal claim -> Development attachment path (WO-049 / Issue #92 item
4; design part 1 Sections 1.3-1.4).

Deliberately the smallest useful slice, not the clustering engine: this
Work Order implements only decision-procedure rules 3, 6 and 7 of design
part 1 Section 1.4 -- "attach to the one existing Development, or leave
honestly unattached". Rules 1, 2, 4 and 5 (blocking rules B1-B8, the
official-identifier signal S1, the attribution-chain signal S7, and the
lexical-similarity signal S8) are **not implemented** here: they need new
fields (``external_reference``, ``cluster_decision``) and a document-level
audit trail this Work Order does not add. Building them now, before this
platform holds more than one real Document, would repeat the exact mistake
Issue #91's own design flagged in ``analysis/events.py::should_cluster`` --
a second clustering engine nothing calls.

What *is* implemented is the necessary gate (S2 geography overlap, S3
predicate-class family agreement, S4 time-window overlap) plus two simple,
literal tie-break signals (S5 entity-token equality, S6 predicate-class
agreement) needed to make rule 3 meaningful at all -- neither is fuzzy,
neither introduces a new field, and both are one-liners a reviewer can
recompute by hand. Confidence is categorical, never numeric, per design part
1 Section 1.4's closing note.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from collectors.event_identity import _normalize_token

#: predicate_class -> family, for S3 (design part 1 Section 2.3's table).
#: 'structural_finding' maps to no family (L3-only, never clusters into an
#: operational Development).
PREDICATE_CLASS_FAMILY: dict[str, str | None] = {
    "berth_or_facility_availability": "operational",
    "transit_or_passage": "operational",
    "service_schedule": "operational",
    "capacity_or_equipment": "operational",
    "customs_or_clearance": "regulatory",
    "tariff_or_fee": "commercial",
    "sanction_or_regulation": "regulatory",
    "hazard_or_security": "hazard",
    "labour_action": "operational",
    "structural_finding": None,
}

#: Slack applied to the time-window overlap test (S4), design part 1 Section
#: 1.3's table.
_WINDOW_SLACK = timedelta(hours=48)
_MONTH_PRECISION_SLACK = timedelta(days=7)


@dataclass(slots=True, frozen=True)
class AttachmentDecision:
    outcome: str  # auto_attach | auto_new | unattached
    event_ids: list[str] = field(default_factory=list)
    merge_status: str = "unmatched"
    rule_id: str = "rule_7"
    basis: str = ""


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _claim_window(claim: Mapping[str, Any]) -> tuple[datetime | None, datetime | None]:
    start = _as_datetime(claim.get("event_start_at"))
    end = _as_datetime(claim.get("event_end_at")) or start
    slack = (
        _MONTH_PRECISION_SLACK if claim.get("event_date_precision") == "month" else _WINDOW_SLACK
    )
    if start is not None:
        start = start - slack
    if end is not None:
        end = end + slack
    return start, end


def _event_window(event: Mapping[str, Any]) -> tuple[datetime | None, datetime | None]:
    start = _as_datetime(event.get("event_date"))
    end = _as_datetime(event.get("event_end_date")) or start
    return start, end


def _windows_overlap(
    left: tuple[datetime | None, datetime | None],
    right: tuple[datetime | None, datetime | None],
) -> bool:
    left_start, left_end = left
    right_start, right_end = right
    if left_start is None or right_start is None:
        return False
    if left_end is None:
        left_end = left_start
    if right_end is None:
        right_end = right_start
    return left_start <= right_end and right_start <= left_end


def _predicate_class_of(claim: Mapping[str, Any]) -> str | None:
    return (claim.get("assertion") or {}).get("predicate_class")


def _modal_predicate_class(
    event: Mapping[str, Any], claims_by_id: Mapping[str, Mapping[str, Any]]
) -> str | None:
    counts: dict[str, int] = {}
    for claim_id in event.get("claim_ids", []) or []:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        predicate_class = _predicate_class_of(claim)
        if predicate_class:
            counts[predicate_class] = counts.get(predicate_class, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def gate_matches(
    claim: Mapping[str, Any],
    event: Mapping[str, Any],
    claims_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    """S2 (geography overlap) AND S3 (predicate-class family agreement) AND
    S4 (time-window overlap), per design part 1 Section 1.3. Necessary, not
    sufficient: a caller still needs S5 or S6 before treating this as an
    attachment (rule 3).
    """
    claim_nodes = set(claim.get("node_ids") or [])
    claim_chokepoints = set(claim.get("chokepoint_ids") or [])
    event_nodes = set(event.get("node_ids") or [])
    event_chokepoints = set(event.get("chokepoint_ids") or [])
    if not (claim_nodes & event_nodes) and not (claim_chokepoints & event_chokepoints):
        return False

    claim_family = PREDICATE_CLASS_FAMILY.get(_predicate_class_of(claim) or "")
    event_modal = _modal_predicate_class(event, claims_by_id)
    event_family = PREDICATE_CLASS_FAMILY.get(event_modal or "")
    if claim_family is None or claim_family != event_family:
        return False

    if not _windows_overlap(_claim_window(claim), _event_window(event)):
        return False

    return True


def _entity_match(claim: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    """S5: normalised entity-token equality, reusing
    ``collectors/event_identity.py::_normalize_token`` verbatim per design."""
    subject_ref = (claim.get("assertion") or {}).get("subject_ref")
    operator = event.get("operator_or_entity")
    if not subject_ref or not operator:
        return False
    return _normalize_token(str(subject_ref)) == _normalize_token(str(operator))


def _predicate_class_agreement(
    claim: Mapping[str, Any],
    event: Mapping[str, Any],
    claims_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    """S6: the claim's predicate_class equals the modal predicate_class
    already established over the event's claim set."""
    predicate_class = _predicate_class_of(claim)
    if not predicate_class:
        return False
    return predicate_class == _modal_predicate_class(event, claims_by_id)


def decide_attachment(
    claim: Mapping[str, Any],
    candidate_events: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, Mapping[str, Any]],
) -> AttachmentDecision:
    """Rules 3, 6 and 7 of design part 1 Section 1.4 only.

    * Rule 3: the gate holds against exactly one candidate, and S5 or S6
      also holds against it -> ``auto_attach``.
    * Rule 6: no candidate passes the gate, but the claim carries at least
      one of node_ids/chokepoint_ids/lane_ids/country_ids -> ``auto_new``
      (the caller should seed a new Development from this claim).
    * Rule 7: no candidate, and the claim carries no geography of any kind
      -> ``unattached`` -- ``event_ids: []``, no Development is created.

    Rules 1, 2, 4 and 5 (blocking rules, S1/S7 exact-identifier attachment,
    multi-candidate proposals, lexical-only proposals) are out of scope --
    see the module docstring.
    """
    matching = [event for event in candidate_events if gate_matches(claim, event, claims_by_id)]
    if len(matching) == 1:
        event = matching[0]
        if _entity_match(claim, event) or _predicate_class_agreement(claim, event, claims_by_id):
            return AttachmentDecision(
                outcome="auto_attach",
                event_ids=[event["event_id"]],
                merge_status="matched_fingerprint",
                rule_id="rule_3",
                basis=(
                    f"Gate (S2 geography, S3 predicate-class family, S4 time window) holds "
                    f"against {event['event_id']!r} alone, and S5/S6 (entity or predicate-class "
                    "agreement) confirms it."
                ),
            )

    has_geography = bool(
        claim.get("node_ids")
        or claim.get("chokepoint_ids")
        or claim.get("lane_ids")
        or claim.get("country_ids")
    )
    if has_geography:
        if not matching:
            gate_basis = (
                "No candidate Development passes the gate; claim carries geography of its own."
            )
        elif len(matching) == 1:
            # Design part 1 Section 1.4 rule 5: exactly one candidate passes
            # the gate, but neither S5 (entity match) nor S6 (predicate-class
            # agreement) confirms it -- a gate-only match without tie-break
            # confirmation. Out of this Work Order's scope (Issue #92), so no
            # attachment is made; the basis says so honestly rather than
            # claiming no candidate passed the gate.
            gate_basis = (
                f"Exactly one candidate Development ({matching[0]['event_id']!r}) passes the "
                "gate, but neither S5 (entity match) nor S6 (predicate-class agreement) confirms "
                "it; a gate-only match without tie-break confirmation is out of this Work "
                "Order's scope (design part 1 Section 1.4 rule 5), so no attachment is made."
            )
        else:
            # Design part 1 Section 1.4 rule 4: the gate matched >=2
            # candidates -- an ambiguous, multi-candidate proposal. Also out
            # of this Work Order's scope.
            gate_basis = (
                f"{len(matching)} candidate Developments pass the gate "
                f"({sorted(event['event_id'] for event in matching)!r}); multi-candidate "
                "attachment is out of this Work Order's scope (design part 1 Section 1.4 rule "
                "4), so no attachment is made."
            )
        return AttachmentDecision(
            outcome="auto_new",
            event_ids=[],
            merge_status="unmatched",
            rule_id="rule_6",
            basis=gate_basis,
        )

    return AttachmentDecision(
        outcome="unattached",
        event_ids=[],
        merge_status="unmatched",
        rule_id="rule_7",
        basis=(
            "No candidate Development passes the gate, and the claim carries no node, "
            "chokepoint, lane or country of its own; left honestly unattached rather than "
            "creating a phantom Development."
        ),
    )
