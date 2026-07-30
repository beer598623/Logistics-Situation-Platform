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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
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


_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _parsed_timestamp(value: Any) -> datetime | None:
    """A parsed timestamp, or ``None`` when ``value`` is absent or cannot be
    parsed (WO-010-R7-R1).

    ``schemas/collection_run.schema.json``'s ``format: "date-time"`` is an
    annotation the ``jsonschema`` version this repository pins does not
    assert (its ``FormatChecker`` has no ``date-time``/``uri`` checker
    registered), so a malformed timestamp currently passes schema
    validation and would otherwise reach ``datetime.fromisoformat`` and
    raise, crashing a build instead of failing one run or one binding
    closed. Every caller that needs "is this timestamp present and valid"
    goes through this helper instead of calling
    :func:`analysis.build_context.parse_timestamp` directly.
    """
    if not value or not isinstance(value, str):
        return None
    # Imported locally: analysis.build_context imports from this module, so
    # a module-level import here would be circular.
    from analysis.build_context import parse_timestamp

    try:
        return parse_timestamp(value)
    except (ValueError, TypeError):
        return None


def output_manifest_problems(
    emitted_records: Sequence[Mapping[str, Any]], *, label: str
) -> list[str]:
    """Internal identity consistency of one output manifest's own entries
    (WO-010-R7 §3), independent of any run-level status rule.

    Canonical hashing (:func:`compute_output_manifest_hash`) is order
    independent by design -- two manifests listing the same records in a
    different order must hash identically. That must never be read as
    "duplicate record IDs are fine as long as the hash comes out
    deterministic": a manifest is rejected outright if the same
    ``record_id`` appears twice (whether or not its repeated entries agree
    with each other), if any entry's ``content_sha256`` is missing or not a
    64-hex-digit SHA-256, or if a ``source_record_id`` recorded for one
    ``record_id`` disagrees with a different occurrence of the same ID (a
    non-deterministic source-record identity).
    """
    problems: list[str] = []
    seen_hashes: dict[str, str | None] = {}
    seen_source_ids: dict[str, Any] = {}
    duplicates: set[str] = set()

    for entry in emitted_records:
        record_id = str(entry.get("record_id"))
        content_hash = entry.get("content_sha256")
        source_record_id = entry.get("source_record_id")

        if (
            not content_hash
            or not isinstance(content_hash, str)
            or not _SHA256_PATTERN.match(content_hash)
        ):
            problems.append(
                f"{label}: output manifest entry {record_id!r} has a missing or malformed "
                f"content_sha256 ({content_hash!r})"
            )

        if record_id in seen_hashes:
            duplicates.add(record_id)
            if seen_hashes[record_id] != content_hash:
                problems.append(
                    f"{label}: output manifest lists record_id {record_id!r} more than once "
                    f"with disagreeing content_sha256 values ({seen_hashes[record_id]!r} and "
                    f"{content_hash!r})"
                )
            if seen_source_ids.get(record_id) != source_record_id:
                problems.append(
                    f"{label}: output manifest lists record_id {record_id!r} more than once "
                    f"with disagreeing source_record_id values ({seen_source_ids.get(record_id)!r} "
                    f"and {source_record_id!r}); a source-record identity must be deterministic"
                )
        else:
            seen_hashes[record_id] = content_hash
            seen_source_ids[record_id] = source_record_id

    for record_id in sorted(duplicates):
        problems.append(f"{label}: output manifest lists record_id {record_id!r} more than once")

    return problems


def collection_run_problems(run: Mapping[str, Any]) -> list[str]:
    """Whether one collection run's own document is internally consistent
    with the status-dependent contract WO-010-R7 §1 defines, tightened by
    WO-010-R7-R1.

    Independent of any record and of any other run: this checks the run
    document against itself. Most of the structural shape (which fields must
    be null versus present for each status) is already enforced by
    ``schemas/collection_run.schema.json``'s status-keyed ``if``/``then``
    rules before this function is ever reached from
    :func:`collectors.collection_runs.load_collection_runs`; what remains
    here is what a JSON Schema cannot express: run-interval validity,
    cross-field count agreement, manifest-internal identity
    (:func:`output_manifest_problems`), and hash correctness.

    * every status -- ``started_at`` and ``completed_at`` must each be
      present and a parseable timestamp, and ``started_at`` must not be
      after ``completed_at`` (WO-010-R7-R1: a run cannot complete before it
      started). ``schemas/collection_run.schema.json``'s ``format:
      "date-time"`` is an annotation the installed ``jsonschema`` does not
      assert, so a malformed timestamp is caught here, not by the schema.
    * ``success`` -- ``records_emitted`` must be a non-null integer
      (WO-010-R7-R1: previously a ``success`` run with ``records_emitted``
      omitted or ``null`` silently skipped the count-agreement check below)
      and must equal ``len(emitted_records)`` (including the zero-output
      case, where both are ``0`` and ``emitted_records`` is ``[]``); every
      entry must be internally consistent; the declared
      ``output_manifest_sha256`` must equal
      :func:`compute_output_manifest_hash` of the declared records.
    * ``not_modified`` -- ``records_emitted`` must be exactly ``0``, never
      ``null`` (WO-010-R7-R1: previously ``null`` was accepted alongside
      ``0``).
    * ``error``/``disabled``/``dry_run`` -- ``records_emitted`` must be
      ``null``, never a number (WO-010-R7-R1: previously unconstrained here;
      a positive value only failed because the schema's per-status
      ``emitted_records``/``output_manifest_sha256`` rules happened to
      reject the run for other reasons). ``0`` is reserved for a
      ``success`` run whose manifest genuinely has zero entries -- a status
      that never produced a manifest at all records ``null``, not a count.
    * every status -- a declared ``output_manifest_sha256`` (only possible
      for ``success``, per the schema) must match the computed hash.
    """
    problems: list[str] = []
    run_id = run.get("run_id", "<run>")
    status = run.get("status")
    emitted_records = run.get("emitted_records")
    declared_hash = run.get("output_manifest_sha256")

    started_at = run.get("started_at")
    completed_at = run.get("completed_at")
    started_ts = _parsed_timestamp(started_at)
    completed_ts = _parsed_timestamp(completed_at)
    if started_ts is None:
        problems.append(
            f"collection run {run_id!r} records no valid started_at ({started_at!r}); a run's "
            "start time is required and must be a parseable timestamp"
        )
    if completed_ts is None:
        problems.append(
            f"collection run {run_id!r} records no valid completed_at ({completed_at!r}); a "
            "run's completion time is required and must be a parseable timestamp"
        )
    if started_ts is not None and completed_ts is not None and started_ts > completed_ts:
        problems.append(
            f"collection run {run_id!r} started at {started_at!r} but completed at "
            f"{completed_at!r}; a run cannot complete before it started"
        )

    records_emitted = run.get("records_emitted")
    is_plain_int = isinstance(records_emitted, int) and not isinstance(records_emitted, bool)
    if status == "success" and not is_plain_int:
        problems.append(
            f"collection run {run_id!r} has status 'success' but records "
            f"records_emitted={records_emitted!r}; a successful run must record an integer "
            "count (0 for a zero-output run)"
        )
    elif status == "not_modified" and (not is_plain_int or records_emitted != 0):
        problems.append(
            f"collection run {run_id!r} has status 'not_modified' but records "
            f"records_emitted={records_emitted!r}; a not_modified run emits nothing and must "
            "record exactly 0"
        )
    elif status in ("error", "disabled", "dry_run") and records_emitted is not None:
        problems.append(
            f"collection run {run_id!r} has status {status!r} but records "
            f"records_emitted={records_emitted!r}; a run that emitted nothing records a null "
            "count, never a number (0 means an empty manifest was produced and hashed, which "
            "only a successful run can claim)"
        )

    if emitted_records is not None:
        records_emitted = run.get("records_emitted")
        if records_emitted is not None and records_emitted != len(emitted_records):
            problems.append(
                f"collection run {run_id!r} records records_emitted={records_emitted}, which "
                f"disagrees with the {len(emitted_records)} entries in emitted_records"
            )
        problems.extend(
            output_manifest_problems(emitted_records, label=f"collection run {run_id!r}")
        )
        computed = compute_output_manifest_hash(emitted_records)
        if declared_hash is not None and declared_hash != computed:
            problems.append(
                f"collection run {run_id!r} declares output_manifest_sha256 {declared_hash!r}, "
                f"which disagrees with the computed hash {computed!r} of its emitted_records"
            )
        if status == "success" and declared_hash is None:
            problems.append(
                f"collection run {run_id!r} has status 'success' with an output manifest but no "
                "output_manifest_sha256; a successful run's manifest must be hashed"
            )

    return problems


def resolve_governing_run(
    run: Mapping[str, Any],
    *,
    runs_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], Mapping[str, Any] | None, list[str], list[str]]:
    """The confirming/governing run model (WO-010-R6 §1, formalised
    WO-010-R7 §4).

    A record's ``collection_run_id`` names the **confirming run** -- the
    run actually cited, which may itself have succeeded, or may be a
    ``not_modified`` run that merely reconfirms an earlier one is still
    current. The **governing run** is the run whose own output manifest
    actually backs the record: the confirming run itself when it succeeded,
    or -- walking ``supersedes_run_id`` -- the nearest ancestor that
    succeeded, when the confirming run is ``not_modified``.

    Returns ``(confirming_run, governing_run, supersedes_chain, problems)``.
    ``confirming_run`` is always ``run`` itself. ``governing_run`` is
    ``None``, and ``problems`` explains why, when the chain cannot resolve
    one: a missing link, a cycle, a hop across source boundaries, a
    non-chronological hop, a chain terminating at a status other than
    ``success``, or a governing run with no valid output-manifest hash.
    ``supersedes_chain`` lists every run_id actually visited, confirming run
    first, governing run last when one was found.

    Fails closed: an empty or partially-walked chain (any ``problems``)
    means ``governing_run`` is ``None``, never a best-effort guess.

    WO-010-R7-R1: every run visited (confirming, every intermediate
    ``not_modified`` hop, and the governing run itself) must carry its own
    valid, non-inverted ``started_at``..``completed_at`` interval -- checked
    here directly rather than relying on the caller having already run
    :func:`collection_run_problems` on every run, so this chain boundary is
    independently fail-closed.
    """
    problems: list[str] = []
    chain: list[str] = []
    visited: set[str] = set()
    confirming = run
    confirming_id = confirming.get("run_id")
    source_id = confirming.get("source_id")
    current = run

    while True:
        current_id = current.get("run_id")
        chain.append(str(current_id))
        if current_id in visited:
            problems.append(
                f"supersedes chain from {confirming_id!r} contains a cycle at {current_id!r}"
            )
            return confirming, None, chain, problems
        visited.add(str(current_id))

        if current.get("source_id") != source_id:
            problems.append(
                f"supersedes chain from {confirming_id!r} crosses source boundaries: "
                f"{current_id!r} belongs to source {current.get('source_id')!r}, not "
                f"{source_id!r}"
            )
            return confirming, None, chain, problems

        current_started = current.get("started_at")
        current_completed = current.get("completed_at")
        current_started_ts = _parsed_timestamp(current_started)
        current_completed_ts = _parsed_timestamp(current_completed)
        if (
            current_started_ts is None
            or current_completed_ts is None
            or current_started_ts > current_completed_ts
        ):
            problems.append(
                f"supersedes chain from {confirming_id!r} includes run {current_id!r} with a "
                f"missing, malformed or inverted started_at..completed_at interval "
                f"({current_started!r}..{current_completed!r})"
            )
            return confirming, None, chain, problems

        status = current.get("status")
        if status == "success":
            output_hash = current.get("output_manifest_sha256")
            if not output_hash or current.get("emitted_records") is None:
                problems.append(
                    f"supersedes chain from {confirming_id!r} terminates at successful run "
                    f"{current_id!r}, which has no valid, non-null output-manifest hash"
                )
                return confirming, None, chain, problems
            return confirming, current, chain, problems

        if status != "not_modified":
            problems.append(
                f"supersedes chain from {confirming_id!r} terminates at run {current_id!r} "
                f"with status {status!r}, not 'success'"
            )
            return confirming, None, chain, problems

        supersedes_id = current.get("supersedes_run_id")
        if not supersedes_id:
            problems.append(
                f"supersedes chain from {confirming_id!r} is broken: {current_id!r} names no "
                "supersedes_run_id"
            )
            return confirming, None, chain, problems
        prior = runs_by_id.get(supersedes_id)
        if prior is None:
            problems.append(
                f"supersedes chain from {confirming_id!r} is broken: {current_id!r} names "
                f"supersedes_run_id {supersedes_id!r}, which does not resolve to a persisted "
                "run for this source"
            )
            return confirming, None, chain, problems

        # WO-010-R7 §1: "every prior run occurs before the later run". prior's
        # own interval was already validated by this loop's next iteration's
        # interval check; parsed again here only for the pairwise comparison.
        current_ts, prior_ts = current.get("completed_at"), prior.get("completed_at")
        current_completed_parsed = _parsed_timestamp(current_ts)
        prior_completed_parsed = _parsed_timestamp(prior_ts)
        if prior_completed_parsed is None:
            problems.append(
                f"supersedes chain from {confirming_id!r} is broken: {current_id!r} names "
                f"supersedes_run_id {supersedes_id!r}, which records no valid completed_at"
            )
            return confirming, None, chain, problems
        chronological_violation = (
            current_completed_parsed is not None
            and prior_completed_parsed > current_completed_parsed
        )
        if chronological_violation:
            problems.append(
                f"supersedes chain from {confirming_id!r} is not chronological: "
                f"{supersedes_id!r} (completed {prior_ts}) is later than {current_id!r} "
                f"(completed {current_ts})"
            )
            return confirming, None, chain, problems

        current = prior


def resolve_live_record_binding(
    record: Mapping[str, Any],
    *,
    collection_runs_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    as_of: Any = None,
) -> tuple[list[str], dict[str, Any] | None]:
    """Core acquisition-binding resolution for one ``live_retrieved`` record
    (WO-010-R6 §1, formalised into the confirming/governing model by
    WO-010-R7 §4/§5).

    Returns ``(problems, binding)``. ``binding`` is ``None`` whenever
    ``problems`` is non-empty (fails closed); otherwise it is::

        {
            "record_id": ...,
            "confirming_run_id": ...,   # the run collection_run_id actually cites
            "governing_run_id": ...,    # the successful run whose manifest backs it
            "output_manifest_sha256": ...,  # the governing run's own hash, never null
            "supersedes_chain": [...],  # every run_id walked, confirming run first
        }

    Every field of the record must agree *exactly* with the governing run's
    own manifest entry: the record ID, the source-record ID (including null
    versus non-null), the content hash, the parser/adapter version, and the
    record's ``retrieved_at`` falling within the governing run's own
    ``started_at``..``completed_at`` interval -- not the confirming run's,
    since a ``not_modified`` run's own timestamps describe when it was
    reconfirmed, not when the record was actually produced.

    WO-010-R7-R1: enforced here, at the acquisition-binding boundary itself,
    not only by repository-level validation (:func:`provenance_problems`)
    or the publication boundary (:func:`qualifies_for_current_publication`):
    the record's own ``retrieval_status`` must be ``'retrieved'`` and its
    ``retrieved_at`` must be present and a parseable timestamp before any
    run is even looked up; the governing run's own ``started_at`` and
    ``completed_at`` must each be present and parseable before the interval
    containment check runs. Every timestamp comparison in this function
    fails closed on a missing or malformed value rather than silently
    skipping the check (as a bare ``if value and other_value:`` guard would)
    or raising (as an unguarded :func:`analysis.build_context.parse_timestamp`
    call would).
    """
    label = _record_label(record)
    provenance = _provenance(record)
    source_id = record_source_id(record)

    retrieval_status = record_retrieval_status(record)
    if retrieval_status != "retrieved":
        return [
            f"{label}: live_retrieved record records retrieval_status {retrieval_status!r}, "
            "not 'retrieved'; a record nothing was retrieved for cannot be bound to an "
            "acquisition"
        ], None
    retrieved_ts = _parsed_timestamp(provenance.get("retrieved_at"))
    if retrieved_ts is None:
        return [
            f"{label}: live_retrieved record records no valid retrieved_at "
            f"({provenance.get('retrieved_at')!r}); a retrieved record must record when it was "
            "retrieved"
        ], None

    run_id = provenance.get("collection_run_id")
    if not run_id:
        return [f"{label}: live_retrieved record carries no collection_run_id"], None
    runs = (collection_runs_by_source or {}).get(source_id or "", ())
    run = next((candidate for candidate in runs if candidate.get("run_id") == run_id), None)
    if run is None:
        return [
            f"{label}: collection_run_id {run_id!r} matches no persisted collection run "
            f"for source {source_id!r}"
        ], None
    if run.get("source_id") != source_id:
        return [
            f"{label}: collection_run_id {run_id!r} belongs to source "
            f"{run.get('source_id')!r}, not {source_id!r}"
        ], None
    if run.get("status") not in {"success", "not_modified"}:
        return [
            f"{label}: collection run {run_id!r} has status {run.get('status')!r}, not "
            "'success' or 'not_modified'"
        ], None

    runs_by_id = {candidate.get("run_id"): candidate for candidate in runs}
    confirming_run, governing_run, supersedes_chain, chain_problems = resolve_governing_run(
        run, runs_by_id=runs_by_id
    )
    if chain_problems or governing_run is None:
        return [f"{label}: {problem}" for problem in chain_problems] or [
            f"{label}: collection run {run_id!r} could not resolve a governing successful run"
        ], None

    confirming_completed_at = confirming_run.get("completed_at")
    confirming_completed_ts = _parsed_timestamp(confirming_completed_at)
    if confirming_completed_ts is None:
        return [
            f"{label}: collection run {run_id!r} records no valid completed_at "
            f"({confirming_completed_at!r})"
        ], None
    if as_of is not None and confirming_completed_ts > as_of:
        return [f"{label}: collection run {run_id!r} completed after this build's as-of time"], None
    retrieved_at = provenance.get("retrieved_at")
    if as_of is not None and retrieved_ts > as_of:
        return [f"{label}: retrieved_at is after this build's as-of time"], None

    # WO-010-R7 §5: retrieval time must be consistent with the *governing*
    # run's own interval, not the confirming run's.
    governing_started_at = governing_run.get("started_at")
    governing_completed_at = governing_run.get("completed_at")
    governing_started_ts = _parsed_timestamp(governing_started_at)
    governing_completed_ts = _parsed_timestamp(governing_completed_at)
    if governing_started_ts is None or governing_completed_ts is None:
        return [
            f"{label}: governing collection run {governing_run.get('run_id')!r} records no "
            f"valid started_at..completed_at interval ({governing_started_at!r}.."
            f"{governing_completed_at!r})"
        ], None
    if not (governing_started_ts <= retrieved_ts <= governing_completed_ts):
        return [
            f"{label}: retrieved_at {retrieved_at!r} falls outside governing collection "
            f"run {governing_run.get('run_id')!r}'s started_at..completed_at interval "
            f"({governing_started_at!r}..{governing_completed_at!r})"
        ], None

    # WO-010-R7 §4: parser version is compared against the *governing* run's
    # adapter_version, not the confirming run's -- a not_modified run's own
    # adapter_version describes the confirmation attempt, not the parser
    # that actually produced the record.
    parser_version = provenance.get("parser_version")
    governing_adapter_version = governing_run.get("adapter_version")
    if parser_version != governing_adapter_version:
        return [
            f"{label}: parser_version {parser_version!r} disagrees with governing collection "
            f"run {governing_run.get('run_id')!r}'s adapter_version "
            f"{governing_adapter_version!r}"
        ], None

    emitted_records = governing_run.get("emitted_records") or []
    record_id = provenance.get("record_id") or record.get("evidence_id")
    manifest_entry = next(
        (entry for entry in emitted_records if entry.get("record_id") == record_id), None
    )
    if manifest_entry is None:
        return [
            f"{label}: record ID {record_id!r} does not appear in the output manifest of "
            f"governing collection run {governing_run.get('run_id')!r}"
        ], None

    # WO-010-R7 §5: exact agreement, not "agree when both happen to be set" --
    # a record's null source_record_id must not match a manifest entry that
    # records a non-null one, and vice versa.
    record_content_hash = provenance.get("content_sha256")
    manifest_content_hash = manifest_entry.get("content_sha256")
    if record_content_hash != manifest_content_hash:
        return [
            f"{label}: content_sha256 {record_content_hash!r} disagrees with the governing "
            f"output manifest's recorded hash {manifest_content_hash!r} for this record"
        ], None
    record_source_record_id = provenance.get("source_record_id")
    manifest_source_record_id = manifest_entry.get("source_record_id")
    if record_source_record_id != manifest_source_record_id:
        return [
            f"{label}: source_record_id {record_source_record_id!r} disagrees with the "
            f"governing output manifest's recorded source_record_id "
            f"{manifest_source_record_id!r}"
        ], None

    return [], {
        "record_id": str(record_id),
        "confirming_run_id": confirming_run.get("run_id"),
        "governing_run_id": governing_run.get("run_id"),
        "output_manifest_sha256": governing_run.get("output_manifest_sha256"),
        "supersedes_chain": supersedes_chain,
    }


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
    exactly agrees with the record on every field WO-010-R7 §5 names. The
    ``live_retrieved`` path is :func:`resolve_live_record_binding`.

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
        problems, _binding = resolve_live_record_binding(
            record, collection_runs_by_source=collection_runs_by_source, as_of=as_of
        )
        return problems

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
    live_record_bindings: list[dict[str, Any]] = []
    # WO-010-R7 §4: confirming_run_id -> the governing run's own hash, never
    # a null placeholder for the cited run while silently relying on
    # another one.
    collection_run_manifest_hashes: dict[str, str | None] = {}

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
        provenance = _provenance(record)

        if origin == LIVE_RETRIEVED:
            problems, binding = resolve_live_record_binding(
                record, collection_runs_by_source=collection_runs_by_source, as_of=as_of
            )
            if problems or binding is None:
                excluded += 1
                return
            record_id = binding["record_id"]
            included_record_ids.add(record_id)
            confirming_id = str(binding["confirming_run_id"])
            run_ids.add(confirming_id)
            collection_run_manifest_hashes[confirming_id] = binding["output_manifest_sha256"]
            live_record_bindings.append(binding)
            confirming_run = runs_by_id.get(binding["confirming_run_id"])
            if confirming_run and confirming_run.get("completed_at"):
                timestamps.append(parse_timestamp(confirming_run["completed_at"]))
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
        record_id = provenance.get("record_id") or record.get("evidence_id")
        if record_id:
            included_record_ids.add(str(record_id))

        if origin == HUMAN_REVIEWED_MANUAL:
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
        # WO-010-R7 §4: per-record confirming/governing detail, so a not
        # modified binding is fully traceable rather than collapsed into a
        # single confirming-run-id -> hash mapping.
        "live_record_bindings": sorted(live_record_bindings, key=lambda entry: entry["record_id"]),
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
