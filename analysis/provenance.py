"""Record origin, retrieval status, publication use and the current-publication
boundary.

WO-010 delivered a working engine on labelled fixtures. WO-010-R1 added the
origin vocabulary that keeps a fixture out of the current view. WO-010-R2
completes it: qualification is a decision about a **whole record**, not about
its origin string alone, and it returns the reason it reached.

Facts recorded on every record, none of which can be inferred from another:

* **origin** -- where the record came from. A synthetic fixture and a retrieved
  publisher response are different kinds of thing even when they carry the
  same numbers.
* **retrieval status** -- whether anything was actually fetched. ``not_retrieved``
  forbids a ``retrieved_at`` timestamp, because a retrieval time on a record
  nothing was retrieved for is simply false.
* **dataset** -- which publication surface the record belongs to. Carried at
  record level, not only on the file that happens to contain it, so a record
  copied into a package takes its surface with it.
* **publication use** -- what the source's terms permit this platform to
  publish. A licence that permits reading is not a licence that permits
  republishing.

There is exactly one qualification function,
:func:`qualifies_for_current_publication`. It takes the record, optionally the
source registry and the intended publication use, and returns a
:class:`PublicationDecision` that is falsey when the record may not be
published. Keeping a second, origin-only predicate alongside it was the
obvious shortcut and the obvious way to end up with two answers that disagree.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Where a record came from.
LIVE_RETRIEVED = "live_retrieved"
HUMAN_REVIEWED_MANUAL = "human_reviewed_manual"
SYNTHETIC_TEST_FIXTURE = "synthetic_test_fixture"
HISTORICAL_VALIDATION_FIXTURE = "historical_validation_fixture"

EVIDENCE_ORIGINS = (
    LIVE_RETRIEVED,
    HUMAN_REVIEWED_MANUAL,
    SYNTHETIC_TEST_FIXTURE,
    HISTORICAL_VALIDATION_FIXTURE,
)

#: Origins that may carry current Logistics intelligence. Deliberately the two
#: origins where a human or a publisher actually stands behind the content.
PUBLISHABLE_ORIGINS = frozenset({LIVE_RETRIEVED, HUMAN_REVIEWED_MANUAL})

#: Origins that exist to exercise the engine and must stay out of the current
#: view entirely.
FIXTURE_ORIGINS = frozenset({SYNTHETIC_TEST_FIXTURE, HISTORICAL_VALIDATION_FIXTURE})

#: Whether anything was actually fetched from a publisher.
RETRIEVAL_STATUSES = ("retrieved", "not_retrieved", "retrieval_failed", "not_applicable")

#: Retrieval statuses a human-reviewed manual record may carry. A human read
#: the publisher's page; the platform fetched nothing, so there is no retrieval
#: to report and none may be claimed.
MANUAL_RETRIEVAL_STATUSES = frozenset({"not_applicable", "not_retrieved"})

#: What a content hash actually covers. A hash over this repository's own
#: authored text is not evidence about a publisher's response, and labelling it
#: as such was the defect R1 corrects.
CONTENT_HASH_SCOPES = ("source_response", "local_fixture_payload", "authored_claim_record")

#: Which publication surface a record belongs to.
CURRENT_PUBLICATION = "current_publication"
TECHNICAL_DEMO = "technical_demo"
HISTORICAL_VALIDATION = "historical_validation"

DATASETS = (CURRENT_PUBLICATION, TECHNICAL_DEMO, HISTORICAL_VALIDATION)

#: Reserved source identifier for records the platform generated itself. It is
#: deliberately NOT a registry entry: it is not a source, and giving it one
#: would be the same category error as attributing a fixture to a publisher.
SYNTHETIC_SOURCE_ID = "SYNTHETIC_FIXTURE"

#: Freshness statuses for records that are not live. Kept disjoint from the
#: real-world set (fresh / stale / very_stale) so a fixture can never be read
#: as a statement about how current a publisher's data is.
FIXTURE_NOT_LIVE = "fixture_not_live"
HISTORICAL_VALIDATION_FRESHNESS = "historical_validation"
FRESHNESS_NOT_APPLICABLE = "not_applicable"

NON_LIVE_FRESHNESS_STATUSES = frozenset(
    {FIXTURE_NOT_LIVE, HISTORICAL_VALIDATION_FRESHNESS, FRESHNESS_NOT_APPLICABLE}
)

#: Real-world freshness statuses. Reserved for records that were actually
#: retrieved or human-reviewed.
LIVE_FRESHNESS_STATUSES = frozenset({"fresh", "stale", "very_stale", "no_data", "error"})

_FRESHNESS_BY_ORIGIN = {
    SYNTHETIC_TEST_FIXTURE: FIXTURE_NOT_LIVE,
    HISTORICAL_VALIDATION_FIXTURE: HISTORICAL_VALIDATION_FRESHNESS,
}


# ---------------------------------------------------------------------------
# Publication use (WO-010-R2)
# ---------------------------------------------------------------------------

#: What a source's terms permit this platform to publish from it, recorded per
#: source under ``qualification.publication_use``. "May we read it" and "may we
#: republish it" are different questions, and a single ``reuse_status`` string
#: was answering only the first while the platform acted on the second.
RAW_VALUES_PERMITTED = "raw_values_permitted"
DERIVED_VALUES_ONLY = "derived_values_only"
BOUNDED_CLAIM_AND_LINK_ONLY = "bounded_claim_and_link_only"
METADATA_LINK_ONLY = "metadata_link_only"
INTERNAL_VALIDATION_ONLY = "internal_validation_only"
PUBLICATION_PROHIBITED = "publication_prohibited"

PUBLICATION_USES = (
    RAW_VALUES_PERMITTED,
    DERIVED_VALUES_ONLY,
    BOUNDED_CLAIM_AND_LINK_ONLY,
    METADATA_LINK_ONLY,
    INTERNAL_VALIDATION_ONLY,
    PUBLICATION_PROHIBITED,
)

#: What a caller intends to do with the record, passed to the qualification
#: function so the answer is specific to the use rather than a blanket yes.
PUBLISH_RAW_VALUE = "publish_raw_value"
PUBLISH_DERIVED_VALUE = "publish_derived_value"
PUBLISH_BOUNDED_CLAIM = "publish_bounded_claim"
PUBLISH_LINK_ONLY = "publish_link_only"

INTENDED_USES = (
    PUBLISH_RAW_VALUE,
    PUBLISH_DERIVED_VALUE,
    PUBLISH_BOUNDED_CLAIM,
    PUBLISH_LINK_ONLY,
)

#: The intended uses each disposition permits. Note that permitting a derived
#: value does not permit publishing the raw series it came from -- that is
#: exactly the distinction a derived-only licence draws.
_PERMITTED_USES: dict[str, frozenset[str]] = {
    RAW_VALUES_PERMITTED: frozenset(INTENDED_USES),
    DERIVED_VALUES_ONLY: frozenset(
        {PUBLISH_DERIVED_VALUE, PUBLISH_BOUNDED_CLAIM, PUBLISH_LINK_ONLY}
    ),
    BOUNDED_CLAIM_AND_LINK_ONLY: frozenset({PUBLISH_BOUNDED_CLAIM, PUBLISH_LINK_ONLY}),
    METADATA_LINK_ONLY: frozenset({PUBLISH_LINK_ONLY}),
    INTERNAL_VALIDATION_ONLY: frozenset(),
    PUBLICATION_PROHIBITED: frozenset(),
}

#: The most permissive ``publication_use`` each redistribution position allows.
#: ``link_only`` terms cannot be squared with publishing numbers, however those
#: numbers were derived.
REDISTRIBUTION_CEILING: dict[str, frozenset[str]] = {
    "permitted": frozenset(PUBLICATION_USES),
    "derived_only": frozenset(
        {
            DERIVED_VALUES_ONLY,
            BOUNDED_CLAIM_AND_LINK_ONLY,
            METADATA_LINK_ONLY,
            INTERNAL_VALIDATION_ONLY,
            PUBLICATION_PROHIBITED,
        }
    ),
    "link_only": frozenset(
        {
            BOUNDED_CLAIM_AND_LINK_ONLY,
            METADATA_LINK_ONLY,
            INTERNAL_VALIDATION_ONLY,
            PUBLICATION_PROHIBITED,
        }
    ),
    "prohibited": frozenset({INTERNAL_VALIDATION_ONLY, PUBLICATION_PROHIBITED}),
    "unknown": frozenset({INTERNAL_VALIDATION_ONLY, PUBLICATION_PROHIBITED}),
}

#: Logistics roles a source must declare for each observation family. This is
#: the check that catches a freight benchmark attributed to a fuel publisher:
#: the series' family and the source's declared role simply do not overlap.
SERIES_ROLE_REQUIREMENTS: dict[str, frozenset[str]] = {
    "trade_observations": frozenset({"thailand_trade_flow"}),
    "port_observations": frozenset({"thailand_port_or_maritime_activity"}),
    "cost_observations": frozenset(
        {
            "domestic_fuel_or_energy_cost",
            "freight_market_benchmark_or_proxy",
            "fx_context",
        }
    ),
    "indicator_observations": frozenset(
        {
            "fx_context",
            "global_supply_chain_baseline",
            "thailand_port_or_maritime_activity",
            "external_driver_context",
        }
    ),
}


def is_fixture(origin: str | None) -> bool:
    return origin in FIXTURE_ORIGINS


def fixture_freshness_status(origin: str | None) -> str:
    """Non-live freshness label for a fixture origin.

    Returns ``not_applicable`` for anything else, so a caller that reaches
    here with a publishable origin gets an obviously wrong-looking label
    rather than a plausible-looking one.
    """
    return _FRESHNESS_BY_ORIGIN.get(str(origin), FRESHNESS_NOT_APPLICABLE)


def _provenance(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """The block carrying provenance, whichever shape the record has.

    Observations nest it under ``provenance``; evidence items and events carry
    it at the top level.
    """
    nested = record.get("provenance")
    return nested if isinstance(nested, Mapping) else record


def record_origin(record: Mapping[str, Any]) -> str | None:
    return _provenance(record).get("evidence_origin")


def record_source_id(record: Mapping[str, Any]) -> str | None:
    """Read the source ID from a record of either shape.

    Source identity comes from the record's own provenance. Nothing in the
    platform maps a series name to a publisher through a side table any more:
    that is how a synthetic freight benchmark ended up attributed to a fuel
    publisher.
    """
    return _provenance(record).get("source_id")


def record_intended_source_id(record: Mapping[str, Any]) -> str | None:
    return _provenance(record).get("intended_source_id")


def record_retrieval_status(record: Mapping[str, Any]) -> str | None:
    return _provenance(record).get("retrieval_status")


def record_dataset(record: Mapping[str, Any]) -> str | None:
    """The publication surface this record belongs to.

    Read from the record's own provenance first. A record that only inherits a
    dataset from the file it happens to sit in loses it the moment it is copied
    into a package -- which is exactly how demo data reaches a current payload.
    """
    nested = record.get("provenance")
    if isinstance(nested, Mapping) and nested.get("dataset"):
        return nested["dataset"]
    return record.get("dataset")


def effective_source_id(record: Mapping[str, Any]) -> str | None:
    """The registry source a record relates to, whether or not it came from it.

    For a live record this is its actual source. For a fixture it is the
    production candidate the fixture stands in for -- useful for looking up a
    freshness contract, and never a claim that the fixture came from there.
    """
    source_id = record_source_id(record)
    if source_id == SYNTHETIC_SOURCE_ID:
        return record_intended_source_id(record)
    return source_id


def record_family(record: Mapping[str, Any]) -> str | None:
    """Which observation family a record belongs to, from its own shape.

    Used for source-to-series compatibility. Returns ``None`` for anything
    that is not an observation -- an evidence item, an event -- for which the
    role requirement does not apply.
    """
    if "indicator_id" in record:
        return "indicator_observations"
    if "flow_direction" in record:
        return "trade_observations"
    if "cost_family" in record:
        return "cost_observations"
    if "metric" in record and "operational_interpretation" in record:
        return "port_observations"
    return None


# ---------------------------------------------------------------------------
# The qualification decision
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class PublicationDecision:
    """Whether a record may enter the current view, and why not if not.

    Falsey when ineligible, so ``if qualifies_for_current_publication(...)``
    reads naturally while ``.reason`` stays available for the message a
    validator or a Dashboard panel needs to print.
    """

    eligible: bool
    reason: str
    record_id: str | None = None

    def __bool__(self) -> bool:
        return self.eligible


def _source_entry(
    registry: Mapping[str, Any] | None, source_id: str | None
) -> dict[str, Any] | None:
    if registry is None or source_id is None:
        return None
    for source in registry.get("sources", []):
        if source.get("id") == source_id:
            return dict(source)
    return None


def _record_label(record: Mapping[str, Any]) -> str:
    provenance = _provenance(record)
    return str(
        provenance.get("record_id")
        or record.get("evidence_id")
        or record.get("event_id")
        or "<record>"
    )


def qualifies_for_current_publication(
    record: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
    publication_use: str | None = None,
) -> PublicationDecision:
    """Decide whether one record may carry current Logistics intelligence.

    Every condition must hold. There is no second, looser path: a caller that
    wants a cheaper check gets this one, because a cheaper check is how a
    fixture ends up in a current payload.

    ``registry`` is optional only so the record-intrinsic rules can be
    exercised in isolation. Every production call site passes it; without it
    the registry-dependent conditions -- the source exists, is enabled or is an
    allowed manual intake, and its terms permit the intended use -- cannot be
    evaluated, and the decision is negative and says why rather than silently
    passing.

    ``publication_use`` names what the caller intends to do with the record and
    defaults to the most demanding use, :data:`PUBLISH_RAW_VALUE`. A caller
    that only needs a bounded claim and a link should say so, and will get a
    correspondingly wider answer.
    """
    label = _record_label(record)
    intended_use = publication_use or PUBLISH_RAW_VALUE
    if intended_use not in INTENDED_USES:
        return PublicationDecision(False, f"unknown publication use {intended_use!r}", label)

    dataset = record_dataset(record)
    if dataset != CURRENT_PUBLICATION:
        return PublicationDecision(
            False,
            f"record belongs to the {dataset!r} dataset, not {CURRENT_PUBLICATION!r}",
            label,
        )

    origin = record_origin(record)
    if origin not in EVIDENCE_ORIGINS:
        return PublicationDecision(
            False, f"evidence_origin {origin!r} is not a recognised origin", label
        )
    if origin in FIXTURE_ORIGINS:
        return PublicationDecision(
            False,
            f"a {origin} record cannot carry current intelligence, whatever dataset it claims",
            label,
        )

    retrieval_status = record_retrieval_status(record)
    if origin == LIVE_RETRIEVED and retrieval_status != "retrieved":
        return PublicationDecision(
            False,
            "a live-retrieved record must record retrieval_status 'retrieved', not "
            f"{retrieval_status!r}",
            label,
        )
    if origin == HUMAN_REVIEWED_MANUAL and retrieval_status not in MANUAL_RETRIEVAL_STATUSES:
        return PublicationDecision(
            False,
            "a human-reviewed manual record must record a manual, non-network retrieval "
            f"status, not {retrieval_status!r}",
            label,
        )

    source_id = record_source_id(record)
    if not source_id:
        return PublicationDecision(False, "the record records no source_id", label)
    if source_id == SYNTHETIC_SOURCE_ID:
        return PublicationDecision(
            False, "the record uses the reserved synthetic source identifier", label
        )

    if registry is None:
        return PublicationDecision(
            False,
            "no source registry was supplied, so the source's enablement and publication "
            "terms could not be checked",
            label,
        )

    source = _source_entry(registry, source_id)
    if source is None:
        return PublicationDecision(
            False, f"source_id {source_id!r} is not in the source registry", label
        )

    qualification = source.get("qualification") or {}
    if not source.get("enabled"):
        allowed_manual = (
            origin == HUMAN_REVIEWED_MANUAL
            and source.get("access_method") == "manual"
            and qualification.get("manual_intake_status") == "allowed"
        )
        if not allowed_manual:
            return PublicationDecision(
                False,
                f"source {source_id!r} is not enabled and is not an allowed human-reviewed "
                "manual intake",
                label,
            )

    family = record_family(record)
    required_roles = SERIES_ROLE_REQUIREMENTS.get(family or "")
    if required_roles is not None:
        roles = set(qualification.get("logistics_role") or [])
        if not roles & required_roles:
            return PublicationDecision(
                False,
                f"source {source_id!r} declares logistics role(s) {sorted(roles)}, which is "
                f"incompatible with a {family.replace('_', ' ')} record",
                label,
            )

    disposition = qualification.get("publication_use")
    if disposition not in PUBLICATION_USES:
        return PublicationDecision(
            False,
            f"source {source_id!r} records no reviewed publication_use disposition",
            label,
        )
    if intended_use not in _PERMITTED_USES[disposition]:
        return PublicationDecision(
            False,
            f"source {source_id!r} permits {disposition!r}, which does not cover {intended_use!r}",
            label,
        )

    if source.get("licence_status") != "reviewed":
        return PublicationDecision(
            False,
            f"source {source_id!r} has licence_status {source.get('licence_status')!r}; an "
            "unreviewed licence cannot authorise publication",
            label,
        )

    return PublicationDecision(True, f"qualified for {intended_use} from {source_id}", label)


def qualified_records(
    records: Sequence[Mapping[str, Any]],
    *,
    registry: Mapping[str, Any] | None = None,
    publication_use: str | None = None,
) -> list[dict[str, Any]]:
    """Filter to the records that may carry current intelligence."""
    return [
        dict(record)
        for record in records
        if qualifies_for_current_publication(
            record, registry=registry, publication_use=publication_use
        )
    ]


def record_publication_use(
    record: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> str | None:
    """The ``publication_use`` disposition recorded for one record's own
    source, or ``None`` if it cannot be resolved.

    A property of the *source*, not of the individual observation -- every
    record from the same source shares the same disposition. Reading it per
    record, rather than assuming "whatever the first record in the list
    says applies to the whole series", is what makes
    :func:`series_homogeneity_problems` possible (WO-010-R4 §5).
    """
    source_id = record_source_id(record)
    source = _source_entry(registry, source_id)
    if source is None:
        return None
    return (source.get("qualification") or {}).get("publication_use")


class SeriesHomogeneityError(ValueError):
    """Raised when a series derivation is attempted on a record set
    :func:`series_homogeneity_problems` rejects (WO-010-R5 §4).

    Raised by :func:`analysis.indicators.derive_series`-wrapping callers that
    guard themselves with it (``scripts.build_analysis.derive_current_series``,
    ``scripts.build_dashboard._current_series_payload``), so that a mixed
    series can never reach a derivation no matter which analytical path
    calls it -- the guard lives at the one place every current derivation
    passes through, not only at each caller's own pre-check.
    """


def series_homogeneity_problems(
    records: Sequence[Mapping[str, Any]],
    *,
    registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Whether every record in a proposed series derivation may honestly be
    combined into one reading (WO-010-R4 §5).

    A series derivation applies one freshness contract, one publication-use
    disposition and one current value to every record handed to it. That is
    only truthful when every record actually agrees on the source, the unit,
    the geography, the lane and the publication-use disposition it carries --
    otherwise "the current value" silently picks one record's answer while
    quietly discarding what a *different* record (with different terms, a
    different unit, or a different place) had to say. Never determined from
    ``records[0]`` alone: every record is checked against every other one, so
    a two-record series where only the second record disagrees is still
    caught.

    Returns an empty list when the records may be combined; otherwise a
    fail-closed list of what disagreed. There is no combination rule here --
    a caller seeing a non-empty list must exclude the series from that
    derivation rather than derive it from an inconsistent set.
    """
    if len(records) <= 1:
        return []

    problems: list[str] = []

    def _distinct(label: str, values: Sequence[Any]) -> None:
        unique = {value for value in values if value is not None}
        if len(unique) > 1:
            problems.append(f"records disagree on {label}: {sorted(map(str, unique))}")

    _distinct("source_id", [record_source_id(record) for record in records])
    _distinct(
        "publication_use",
        [record_publication_use(record, registry=registry) for record in records],
    )
    _distinct(
        "unit",
        [(record.get("measurement") or {}).get("unit") for record in records],
    )
    _distinct(
        "geography",
        [(record.get("placement") or {}).get("country_id") for record in records],
    )
    _distinct(
        "lane_id",
        [(record.get("placement") or {}).get("lane_id") for record in records],
    )

    return problems


def compute_output_manifest_hash(emitted_records: Sequence[Mapping[str, Any]] | None) -> str | None:
    """Deterministic hash over a collection run's output manifest (WO-010-R6 §1).

    ``None`` when there is no manifest to hash (a run persisted before
    WO-010-R6, or a status that never emits). Otherwise a sha256 over the
    manifest's entries sorted by ``record_id`` -- so two manifests that list
    the same records in a different order hash identically, but any change to
    which records were emitted, or to a record's ``source_record_id`` or
    ``content_sha256``, changes the hash.
    """
    if emitted_records is None:
        return None
    canonical = sorted(
        (
            {
                "record_id": str(entry.get("record_id")),
                "source_record_id": entry.get("source_record_id"),
                "content_sha256": entry.get("content_sha256"),
            }
            for entry in emitted_records
        ),
        key=lambda entry: entry["record_id"],
    )
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reviewed_record_summary(record_id: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical per-record summary hashed into ``reviewed_record_set_sha256``
    (WO-010-R6 §2). Every field the work order names, read from a
    :func:`build_record_index` entry.
    """
    return {
        "record_id": record_id,
        "source_id": entry.get("source_id"),
        "dataset": entry.get("dataset"),
        "evidence_origin": entry.get("evidence_origin"),
        "content_hash": entry.get("content_hash"),
        "timestamp": entry.get("timestamp"),
        "event_id": entry.get("event_id"),
    }


def compute_reviewed_record_set_hash(
    record_ids: Sequence[str],
    *,
    record_index: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Deterministic hash over the actual resolved record set a manual
    review event names (WO-010-R6 §2).

    ``None`` when any ``record_id`` does not resolve in ``record_index`` --
    there is no honest hash to compute over a record set that includes a
    reference to nothing. Otherwise a sha256 over each record's canonical
    summary (:func:`_reviewed_record_summary`), sorted by ``record_id`` so
    equivalent record sets in a different order hash identically, but any
    change to a member record's content, source, dataset or the set's
    membership itself changes the hash.
    """
    summaries = []
    for record_id in record_ids:
        entry = record_index.get(record_id)
        if entry is None:
            return None
        summaries.append(_reviewed_record_summary(str(record_id), entry))
    summaries.sort(key=lambda entry: entry["record_id"])
    encoded = json.dumps(summaries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def collection_run_problems(run: Mapping[str, Any]) -> list[str]:
    """Internal consistency of one collection run's own output manifest
    (WO-010-R6 §1).

    Independent of any record: this checks the run document against itself
    -- a ``not_modified`` run must never claim newly emitted records of its
    own, a run that declares ``emitted_records`` must declare a matching
    ``records_emitted`` count and a matching ``output_manifest_sha256``, and
    a declared ``output_manifest_sha256`` must actually match what
    :func:`compute_output_manifest_hash` returns for the declared records.
    """
    problems: list[str] = []
    run_id = run.get("run_id", "<run>")
    status = run.get("status")
    emitted_records = run.get("emitted_records")

    if status == "not_modified" and emitted_records:
        problems.append(
            f"collection run {run_id!r} has status 'not_modified' but declares "
            f"{len(emitted_records)} emitted_records; a not_modified run must not claim "
            "newly emitted records"
        )

    if emitted_records is not None:
        records_emitted = run.get("records_emitted")
        if records_emitted is not None and records_emitted != len(emitted_records):
            problems.append(
                f"collection run {run_id!r} records records_emitted={records_emitted}, which "
                f"disagrees with the {len(emitted_records)} entries in emitted_records"
            )
        computed = compute_output_manifest_hash(emitted_records)
        declared = run.get("output_manifest_sha256")
        if declared is not None and declared != computed:
            problems.append(
                f"collection run {run_id!r} declares output_manifest_sha256 {declared!r}, "
                f"which disagrees with the computed hash {computed!r} of its emitted_records"
            )

    return problems


def _resolve_output_manifest(
    run: Mapping[str, Any],
    *,
    runs_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]] | None]:
    """The run whose output manifest actually governs membership for
    ``run``, following a ``not_modified`` run's ``supersedes_run_id`` chain
    back to the nearest run that actually declares ``emitted_records``
    (WO-010-R6 §1).

    Returns ``(governing_run, emitted_records)``. ``emitted_records`` is
    ``None`` when the chain cannot resolve one -- a missing link, a cycle, or
    a governing run with no manifest at all -- so the caller fails closed
    rather than treating "we could not find the manifest" as "the manifest
    permits this".
    """
    visited: set[str] = set()
    current = run
    while True:
        current_id = current.get("run_id")
        if current_id in visited:
            return current, None
        visited.add(str(current_id))
        emitted_records = current.get("emitted_records")
        if current.get("status") != "not_modified":
            return current, emitted_records
        if emitted_records:
            # A not_modified run must not have its own records, but if one
            # does, fall through and let collection_run_problems() catch it
            # rather than silently trusting it here.
            return current, emitted_records
        supersedes_id = current.get("supersedes_run_id")
        if not supersedes_id:
            return current, None
        prior = runs_by_id.get(supersedes_id)
        if prior is None:
            return current, None
        current = prior


def acquisition_binding_problems(
    record: Mapping[str, Any],
    *,
    collection_runs_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    manual_events_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    as_of: Any = None,
) -> list[str]:
    """Whether a ``live_retrieved`` or ``human_reviewed_manual`` record is
    actually bound to a persisted acquisition event, not merely labelled as
    though it were (WO-010-R5 §1).

    A fixture claims no acquisition and is exempt (``[]``) -- this check
    exists only for the two origins that claim a real acquisition actually
    happened. For those, the record must carry the matching binding ID
    (``collection_run_id`` for ``live_retrieved``, ``manual_review_event_id``
    for ``human_reviewed_manual``), and that ID must resolve to a persisted
    run/event that: belongs to the same source, succeeded (or, for a manual
    event, was actually reviewed), completed at or before ``as_of``, and
    -- for a live record -- whose ``adapter_version`` is not positively
    contradicted by the record's own ``parser_version``.

    Fails closed by construction: a record whose origin claims acquisition
    but whose caller supplies no index at all (``collection_runs_by_source``/
    ``manual_events_by_source`` both ``None``) gets exactly the same rejection
    as one that supplies an index the ID does not appear in. There is no
    "skip this check" path for a publishable origin -- only "no index was
    given" as one particular way for the lookup to fail.
    """
    origin = record_origin(record)
    if origin not in PUBLISHABLE_ORIGINS:
        return []

    # Imported locally: analysis.build_context imports from this module, so a
    # module-level import here would be circular.
    from analysis.build_context import parse_timestamp

    label = _record_label(record)
    provenance = _provenance(record)
    source_id = record_source_id(record)

    if origin == LIVE_RETRIEVED:
        run_id = provenance.get("collection_run_id")
        if not run_id:
            return [f"{label}: live_retrieved record carries no collection_run_id"]
        runs = (collection_runs_by_source or {}).get(source_id or "", ())
        run = next((candidate for candidate in runs if candidate.get("run_id") == run_id), None)
        if run is None:
            return [
                f"{label}: collection_run_id {run_id!r} matches no persisted collection run "
                f"for source {source_id!r}"
            ]
        if run.get("source_id") != source_id:
            return [
                f"{label}: collection_run_id {run_id!r} belongs to source "
                f"{run.get('source_id')!r}, not {source_id!r}"
            ]
        if run.get("status") not in {"success", "not_modified"}:
            return [
                f"{label}: collection run {run_id!r} has status {run.get('status')!r}, not "
                "'success' or 'not_modified'"
            ]
        completed_at = run.get("completed_at")
        if as_of is not None and completed_at and parse_timestamp(completed_at) > as_of:
            return [f"{label}: collection run {run_id!r} completed after this build's as-of time"]
        retrieved_at = provenance.get("retrieved_at")
        if as_of is not None and retrieved_at and parse_timestamp(retrieved_at) > as_of:
            return [f"{label}: retrieved_at is after this build's as-of time"]
        parser_version = provenance.get("parser_version")
        adapter_version = run.get("adapter_version")
        if parser_version and adapter_version and parser_version != adapter_version:
            return [
                f"{label}: parser_version {parser_version!r} disagrees with collection run "
                f"{run_id!r}'s adapter_version {adapter_version!r}"
            ]

        # WO-010-R6 §1: the record must not merely cite a run that succeeded --
        # it must actually appear in that run's own output manifest, following
        # a not_modified run's supersedes_run_id chain back to the manifest
        # that actually governs it.
        runs_by_id = {candidate.get("run_id"): candidate for candidate in runs}
        governing_run, emitted_records = _resolve_output_manifest(run, runs_by_id=runs_by_id)
        if emitted_records is None:
            return [
                f"{label}: collection run {run_id!r} declares no output manifest "
                "(emitted_records), so record-level membership cannot be verified"
            ]
        record_id = provenance.get("record_id") or record.get("evidence_id")
        manifest_entry = next(
            (entry for entry in emitted_records if entry.get("record_id") == record_id), None
        )
        if manifest_entry is None:
            return [
                f"{label}: record ID {record_id!r} does not appear in the output manifest of "
                f"collection run {governing_run.get('run_id')!r}"
            ]
        record_content_hash = provenance.get("content_sha256")
        manifest_content_hash = manifest_entry.get("content_sha256")
        if (
            record_content_hash
            and manifest_content_hash
            and record_content_hash != manifest_content_hash
        ):
            return [
                f"{label}: content_sha256 {record_content_hash!r} disagrees with the output "
                f"manifest's recorded hash {manifest_content_hash!r} for this record"
            ]
        record_source_record_id = provenance.get("source_record_id")
        manifest_source_record_id = manifest_entry.get("source_record_id")
        if record_source_record_id and record_source_record_id != manifest_source_record_id:
            return [
                f"{label}: source_record_id {record_source_record_id!r} disagrees with the "
                f"output manifest's recorded source_record_id {manifest_source_record_id!r}"
            ]
        return []

    if origin == HUMAN_REVIEWED_MANUAL:
        event_id = provenance.get("manual_review_event_id")
        if not event_id:
            return [f"{label}: human_reviewed_manual record carries no manual_review_event_id"]
        events = (manual_events_by_source or {}).get(source_id or "", ())
        event = next(
            (candidate for candidate in events if candidate.get("event_id") == event_id), None
        )
        if event is None:
            return [
                f"{label}: manual_review_event_id {event_id!r} matches no persisted manual "
                f"review event for source {source_id!r}"
            ]
        if event.get("source_id") != source_id:
            return [
                f"{label}: manual_review_event_id {event_id!r} belongs to source "
                f"{event.get('source_id')!r}, not {source_id!r}"
            ]
        if event.get("status") != "reviewed":
            return [
                f"{label}: manual review event {event_id!r} has status "
                f"{event.get('status')!r}, not 'reviewed'"
            ]
        record_id = provenance.get("record_id") or record.get("evidence_id")
        if record_id not in (event.get("related_record_ids") or []):
            return [
                f"{label}: record ID {record_id!r} is not listed in manual review event "
                f"{event_id!r}'s related_record_ids"
            ]
        if not event.get("bounded_content_confirmed"):
            return [f"{label}: manual review event {event_id!r} does not confirm bounded content"]
        reviewed_at = event.get("reviewed_at")
        if as_of is not None and reviewed_at and parse_timestamp(reviewed_at) > as_of:
            return [
                f"{label}: manual review event {event_id!r} was reviewed after this build's "
                "as-of time"
            ]
        return []

    return []


def _record_timestamp(record: Mapping[str, Any]) -> str | None:
    """The best available dating for a record of either observation or
    evidence shape, for comparison against a manual review event's own date.
    """
    provenance = _provenance(record)
    return (
        provenance.get("retrieved_at")
        or provenance.get("published_at")
        or record.get("retrieved_at")
        or record.get("publication_date")
    )


def build_record_index(
    *,
    observations: Mapping[str, Sequence[Mapping[str, Any]]] = {},
    evidence: Sequence[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """A normalized ``record_id`` -> summary index spanning every observation
    family and every event-evidence item (WO-010-R5 §2).

    Built once and handed to :func:`collectors.collection_runs.
    load_manual_review_events`, which uses it to check a manual review
    event's ``related_record_ids`` against records that actually exist,
    rather than trusting the list on its own say-so. Each entry carries only
    what that check needs: the record's own ID, its source, whether it is a
    fixture, its dataset, and its best available timestamp.
    """
    index: dict[str, dict[str, Any]] = {}
    for records in observations.values():
        for record in records:
            provenance = _provenance(record)
            record_id = provenance.get("record_id")
            if not record_id:
                continue
            index[str(record_id)] = {
                "record_id": str(record_id),
                "source_id": record_source_id(record),
                "is_fixture": is_fixture(record_origin(record)),
                "dataset": record_dataset(record),
                "timestamp": _record_timestamp(record),
                "evidence_origin": record_origin(record),
                "content_hash": provenance.get("content_sha256"),
                "event_id": None,
            }
    for item in evidence:
        evidence_id = item.get("evidence_id")
        if not evidence_id:
            continue
        index[str(evidence_id)] = {
            "record_id": str(evidence_id),
            "source_id": record_source_id(item),
            "is_fixture": is_fixture(record_origin(item)),
            "dataset": record_dataset(item),
            "timestamp": _record_timestamp(item),
            "evidence_origin": record_origin(item),
            "content_hash": item.get("content_sha256"),
            "event_id": item.get("event_id"),
        }
    return index


def build_acquisition_summary(
    *,
    observations: Mapping[str, Sequence[Mapping[str, Any]]] = {},
    evidence: Sequence[Mapping[str, Any]] = (),
    collection_runs_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    manual_events_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    """What acquisition evidence actually backs a set of current records
    (WO-010-R5 §9).

    ``observations`` and ``evidence`` should already be qualified for
    current publication (:func:`qualified_records` / ``qualifies_for_
    current_publication``) -- this function only asks the acquisition
    question, not the publication-use question, so it can be layered onto
    any already-qualified set. Every ``live_retrieved`` or ``human_reviewed_
    manual`` record among them is checked against :func:`acquisition_binding_
    problems`; a record that fails is counted as excluded rather than
    silently omitted, and a record that passes contributes its binding ID
    and timestamp to the summary. Records of any other origin (a fixture
    that slipped through an upstream filter) are ignored rather than
    miscounted as excluded, since they were never claiming an acquisition to
    begin with.
    """
    # Imported locally: analysis.build_context imports from this module, so a
    # module-level import here would be circular.
    from analysis.build_context import parse_timestamp, to_iso

    run_ids: set[str] = set()
    event_ids: set[str] = set()
    timestamps: list[Any] = []
    excluded = 0
    included_record_ids: set[str] = set()

    runs_by_id = {
        run.get("run_id"): run
        for runs in (collection_runs_by_source or {}).values()
        for run in runs
    }
    events_by_id = {
        event.get("event_id"): event
        for events in (manual_events_by_source or {}).values()
        for event in events
    }

    def _consider(record: Mapping[str, Any]) -> None:
        nonlocal excluded
        origin = record_origin(record)
        if origin not in PUBLISHABLE_ORIGINS:
            return
        problems = acquisition_binding_problems(
            record,
            collection_runs_by_source=collection_runs_by_source,
            manual_events_by_source=manual_events_by_source,
            as_of=as_of,
        )
        if problems:
            excluded += 1
            return
        provenance = _provenance(record)
        record_id = provenance.get("record_id") or record.get("evidence_id")
        if record_id:
            included_record_ids.add(str(record_id))

        if origin == LIVE_RETRIEVED:
            run_id = provenance.get("collection_run_id")
            run_ids.add(str(run_id))
            run = runs_by_id.get(run_id)
            if run and run.get("completed_at"):
                timestamps.append(parse_timestamp(run["completed_at"]))
        elif origin == HUMAN_REVIEWED_MANUAL:
            event_id = provenance.get("manual_review_event_id")
            event_ids.add(str(event_id))
            event = events_by_id.get(event_id)
            if event and event.get("reviewed_at"):
                timestamps.append(parse_timestamp(event["reviewed_at"]))

    for records in observations.values():
        for record in records:
            _consider(record)
    for item in evidence:
        _consider(item)

    limitations: list[str] = []
    if excluded:
        limitations.append(
            f"{excluded} otherwise-qualified record(s) were excluded from this package "
            "because they carried no matching, valid acquisition binding."
        )

    # WO-010-R6 §4: per-run and per-event manifest/record-set hashes, so the
    # package's own acquisition_summary carries not just which runs/events
    # qualified but what they were bound to at the moment this summary was
    # built -- what acquisition_currency_problems (analysis.review_package)
    # and the approval-time acquisition-state hash both compare against.
    collection_run_manifest_hashes = {
        run_id: runs_by_id[run_id].get("output_manifest_sha256")
        for run_id in sorted(run_ids)
        if run_id in runs_by_id
    }
    manual_review_record_set_hashes = {
        event_id: events_by_id[event_id].get("reviewed_record_set_sha256")
        for event_id in sorted(event_ids)
        if event_id in events_by_id
    }

    return {
        "qualifying_collection_run_ids": sorted(run_ids),
        "qualifying_manual_review_event_ids": sorted(event_ids),
        "excluded_unbound_record_count": excluded,
        "latest_source_cutoff": to_iso(max(timestamps)) if timestamps else None,
        "acquisition_health_limitations": limitations,
        "collection_run_manifest_hashes": collection_run_manifest_hashes,
        "manual_review_record_set_hashes": manual_review_record_set_hashes,
        "included_current_record_ids": sorted(included_record_ids),
    }


#: Source Health statuses incompatible with a current live_retrieved record
#: actually being published from that source (WO-010-R5 §3).
_NON_PUBLISHING_HEALTH_STATUSES = frozenset({"no_data", "disabled"})


def source_health_publication_consistency_problems(
    source_status: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Whether Source Health and current publication agree (WO-010-R5 §3).

    A ``live_retrieved`` record must never be published while Source
    Health's own snapshot reports that record's source as ``no_data`` or
    ``disabled`` -- that combination asserts, in the same build, both "this
    source has no data" and "here is a value from it", and no honest build
    can say both. ``qualifies_for_current_publication`` already refuses a
    disabled source for a non-manual origin, and :func:`acquisition_binding_
    problems` already refuses a record whose collection run does not match
    Source Health's own view of what succeeded -- this is the second,
    independent check over the *final* set of records actually being
    published, in case those upstream filters and this build's Source
    Health snapshot were ever computed from data that had drifted apart.
    A ``no_data``/``disabled`` mismatch specifically for a
    ``human_reviewed_manual`` record is not checked here: a manual intake's
    own health already comes only from its recorded review event
    (``collectors.source_health._evaluate_manual_source_health``), so the
    same contradiction cannot arise for it the way it can for an automated
    collection.
    """
    problems: list[str] = []
    health_by_id = {str(item.get("source_id")): item for item in source_status.get("sources", [])}
    for record in records:
        if record_origin(record) != LIVE_RETRIEVED:
            continue
        source_id = record_source_id(record)
        health = health_by_id.get(str(source_id))
        status = health.get("status") if health else None
        if status in _NON_PUBLISHING_HEALTH_STATUSES:
            problems.append(
                f"{_record_label(record)}: published as live_retrieved from source "
                f"{source_id!r}, whose Source Health status is {status!r}"
            )
    return problems


def publication_use_problems(source: Mapping[str, Any]) -> list[str]:
    """Whether a source's publication_use is compatible with its own terms.

    Checked for every source, enabled or not, so a disposition that could not
    lawfully be acted on is caught while the source is still disabled rather
    than at the moment somebody enables it.
    """
    problems: list[str] = []
    source_id = source.get("id", "<source>")
    qualification = source.get("qualification") or {}
    disposition = qualification.get("publication_use")
    redistribution = qualification.get("redistribution_status")
    reuse = qualification.get("reuse_status")

    if disposition is None:
        problems.append(f"{source_id}: records no publication_use disposition")
        return problems
    if disposition not in PUBLICATION_USES:
        problems.append(f"{source_id}: publication_use {disposition!r} is not a recognised value")
        return problems

    ceiling = REDISTRIBUTION_CEILING.get(str(redistribution))
    if ceiling is None:
        problems.append(
            f"{source_id}: redistribution_status {redistribution!r} has no defined "
            "publication ceiling"
        )
    elif disposition not in ceiling:
        problems.append(
            f"{source_id}: publication_use {disposition!r} exceeds what redistribution_status "
            f"{redistribution!r} permits"
        )

    if reuse in {None, "unknown"} and disposition not in {
        INTERNAL_VALIDATION_ONLY,
        PUBLICATION_PROHIBITED,
        METADATA_LINK_ONLY,
    }:
        problems.append(
            f"{source_id}: reuse_status is {reuse!r}, so nothing beyond a metadata link may be "
            f"published, but publication_use is {disposition!r}"
        )

    if source.get("enabled") and disposition in {INTERNAL_VALIDATION_ONLY, PUBLICATION_PROHIBITED}:
        problems.append(
            f"{source_id}: is enabled but its publication_use is {disposition!r}, so nothing "
            "it provides could be published"
        )

    enablement = source.get("enablement") or {}
    unresolved_rate_limit = qualification.get("rate_limit") in {None, "unknown"}
    if (
        unresolved_rate_limit
        and source.get("access_method") not in {"manual", "download"}
        and enablement.get("schedule_justified")
    ):
        problems.append(
            f"{source_id}: rate limits are unresolved, so no collection schedule may be "
            "justified; record a manual-only or no-schedule disposition instead"
        )

    if (
        source.get("access_method") == "manual"
        and qualification.get("manual_intake_status") == "allowed"
        and not qualification.get("underlying_publisher_required")
    ):
        problems.append(
            f"{source_id}: an allowed manual intake must require every record to identify the "
            "underlying publisher it transcribes"
        )

    return problems


def dataset_of(record: Mapping[str, Any]) -> str | None:
    return record_dataset(record)


def in_dataset(records: Sequence[Mapping[str, Any]], dataset: str) -> list[dict[str, Any]]:
    return [dict(record) for record in records if record_dataset(record) == dataset]


def provenance_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A countable description of where a set of records came from.

    Carried in the review package so a reader -- and the approval gate -- can
    see the provenance mix without re-deriving it from every record.
    """
    origins: dict[str, int] = {}
    datasets: dict[str, int] = {}
    sources: dict[str, int] = {}
    for record in records:
        origin = str(record_origin(record))
        dataset = str(record_dataset(record))
        source_id = str(record_source_id(record))
        origins[origin] = origins.get(origin, 0) + 1
        datasets[dataset] = datasets.get(dataset, 0) + 1
        sources[source_id] = sources.get(source_id, 0) + 1
    return {
        "record_count": len(records),
        "origins": dict(sorted(origins.items())),
        "datasets": dict(sorted(datasets.items())),
        "source_ids": dict(sorted(sources.items())),
        "fixture_record_count": sum(1 for record in records if is_fixture(record_origin(record))),
    }


def provenance_problems(record: Mapping[str, Any], *, label: str) -> list[str]:
    """Truthfulness checks that apply to any record carrying provenance.

    These are the checks that catch a record claiming more than it can
    support: a retrieval time on something nothing was retrieved for, a
    fixture attributed to a real publisher, or a hash of this repository's own
    text presented as evidence about a publisher's response.
    """
    problems: list[str] = []
    origin = record_origin(record)
    provenance = _provenance(record)
    retrieval_status = provenance.get("retrieval_status")
    retrieved_at = provenance.get("retrieved_at")
    source_id = record_source_id(record)
    intended = record_intended_source_id(record)
    hash_scope = provenance.get("content_hash_scope")
    dataset = record_dataset(record)

    if origin not in EVIDENCE_ORIGINS:
        problems.append(f"{label}: evidence_origin {origin!r} is not a recognised origin")
    if retrieval_status not in RETRIEVAL_STATUSES:
        problems.append(
            f"{label}: retrieval_status {retrieval_status!r} is not a recognised status"
        )
    if dataset is not None and dataset not in DATASETS:
        problems.append(f"{label}: dataset {dataset!r} is not a recognised publication surface")

    if retrieval_status != "retrieved" and retrieved_at:
        problems.append(
            f"{label}: retrieval_status is {retrieval_status!r} but a retrieved_at timestamp "
            "is present; nothing was retrieved, so there is no retrieval time"
        )
    if retrieval_status == "retrieved" and not retrieved_at:
        problems.append(f"{label}: retrieval_status is 'retrieved' but no retrieved_at is recorded")

    if is_fixture(origin):
        if retrieval_status == "retrieved":
            problems.append(
                f"{label}: a {origin} record cannot be marked as retrieved from a publisher"
            )
        if source_id != SYNTHETIC_SOURCE_ID:
            problems.append(
                f"{label}: a {origin} record must record source_id "
                f"{SYNTHETIC_SOURCE_ID!r}, not {source_id!r}; attributing generated content "
                "to a real publisher misstates its provenance"
            )
        if not intended:
            problems.append(
                f"{label}: a fixture must record the intended_source_id it stands in for"
            )
        if hash_scope == "source_response":
            problems.append(
                f"{label}: content_hash_scope 'source_response' claims the hash covers a "
                "publisher response, but nothing was retrieved"
            )
        if dataset == CURRENT_PUBLICATION:
            problems.append(f"{label}: a {origin} record claims the current-publication dataset")
    else:
        if source_id == SYNTHETIC_SOURCE_ID:
            problems.append(
                f"{label}: origin {origin!r} is publishable but source_id is the reserved "
                "synthetic identifier"
            )
        if hash_scope == "authored_claim_record":
            problems.append(
                f"{label}: a publishable record should hash the source response or payload, "
                "not this repository's authored claim text"
            )

    return problems
