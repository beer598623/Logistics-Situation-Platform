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
