"""Deterministic, validated loading of collection-run and manual-review history.

Source Health must never be evaluated against ``evaluate_registry_health(registry,
{})`` in a production path: an empty runs mapping is indistinguishable from "we
checked and found nothing" and from "we never looked" -- fine for a unit test
in isolation, wrong for the one path a reader actually trusts. This module is
the single place that resolves "what does this repository actually know
happened" from persisted, schema-validated JSON, so ``scripts/build_analysis.py``
never has to invent an empty mapping to stand in for real history.

Two kinds of history are loaded, because they are genuinely different kinds of
evidence:

* **Collection runs** (``data/collection_runs/<SOURCE_ID>.json``) -- one
  manifest per automated collection attempt, each validated against
  ``schemas/collection_run.schema.json``. A missing file or an empty ``runs``
  array both mean the same thing: no known run history for that source.
* **Manual review events** (``data/collection_runs/manual/<SOURCE_ID>.json``)
  -- one record per human-reviewed manual-intake transcription. These are
  deliberately *not* shaped like a collection run: nothing was fetched, so a
  manifest full of null network fields would misstate what happened. A manual
  review event instead just says who looked, when, and how many bounded
  records they recorded.

Today no source has ever run and no manual notice has ever been recorded, so
both loaders return empty mappings against the committed repository -- which
is the correct, honest answer, not a placeholder for one.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from analysis.build_context import parse_timestamp
from analysis.contracts import schema_errors

ROOT = Path(__file__).resolve().parents[1]

#: Where automated collection-run manifests are persisted, one file per source.
COLLECTION_RUNS_DIR = ROOT / "data" / "collection_runs"

#: Where manual-intake review events are persisted, one file per source.
MANUAL_REVIEW_EVENTS_DIR = COLLECTION_RUNS_DIR / "manual"


def load_collection_runs(
    directory: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Every known collection-run manifest, grouped by ``source_id``.

    Each record is validated against ``schemas/collection_run.schema.json``
    before being trusted -- an invalid manifest on disk is a build failure,
    not a record silently dropped from Source Health.

    A missing directory, and a source with no file at all, both resolve to no
    known history for that source: neither is treated as a successful run.
    """
    target = directory if directory is not None else COLLECTION_RUNS_DIR
    runs_by_source: dict[str, list[dict[str, Any]]] = {}
    if not target.exists():
        return runs_by_source
    for path in sorted(target.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for run in document.get("runs", []):
            errors = schema_errors(run, "collection_run.schema.json")
            if errors:
                raise ValueError(
                    f"{path}: invalid collection run manifest for "
                    f"{run.get('run_id', '<unknown>')}: {errors}"
                )
            runs_by_source.setdefault(run["source_id"], []).append(run)
    return runs_by_source


def load_manual_review_events(
    directory: Path | None = None,
    *,
    registry: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Every recorded manual-intake review event, grouped by ``source_id``.

    WO-010-R4 §7: validated against ``schemas/manual_review_event.schema.json``
    -- a deliberately different, smaller shape than a network collection
    manifest (``collection_run.schema.json``), since nothing was fetched over
    a network and a manifest full of null network fields would misstate what
    happened, but no longer an unvalidated shape. Beyond schema validity,
    every event must also pass checks a JSON Schema alone cannot express:

    * its ``source_id`` must match both the containing filename and an entry
      in ``registry`` that is an allowed manual-intake contract;
    * its ``event_id`` must be unique across every file in this directory;
    * it must not name a publisher-required source without recording one;
    * it must not be dated later than ``now`` (the build's as-of time).

    Any violation raises rather than silently dropping the event or the
    whole file -- a malformed manual-review event is a build failure, the
    same way an invalid collection-run manifest already is.

    ``registry`` and ``now`` are optional so the loader can still be
    exercised (e.g. in isolated schema tests) without a full registry or
    Build Context; every production call site passes both.
    """
    target = directory if directory is not None else MANUAL_REVIEW_EVENTS_DIR
    events_by_source: dict[str, list[dict[str, Any]]] = {}
    if not target.exists():
        return events_by_source

    sources_by_id = {source["id"]: source for source in (registry or {}).get("sources", [])}
    seen_event_ids: set[str] = set()

    for path in sorted(target.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document.get("events", []):
            errors = schema_errors(event, "manual_review_event.schema.json")
            if errors:
                raise ValueError(
                    f"{path}: invalid manual review event "
                    f"{event.get('event_id', '<unknown>')}: {errors}"
                )

            event_id = event["event_id"]
            if event_id in seen_event_ids:
                raise ValueError(f"{path}: duplicate manual review event_id {event_id!r}")
            seen_event_ids.add(event_id)

            source_id = event["source_id"]
            if path.stem != source_id:
                raise ValueError(
                    f"{path}: event {event_id!r} records source_id {source_id!r}, which does "
                    f"not match the containing filename {path.stem!r}"
                )

            if registry is not None:
                source = sources_by_id.get(source_id)
                if source is None:
                    raise ValueError(
                        f"{path}: event {event_id!r} names source_id {source_id!r}, which is "
                        "not in the source registry"
                    )
                qualification = source.get("qualification") or {}
                if (
                    source.get("access_method") != "manual"
                    or qualification.get("manual_intake_status") != "allowed"
                ):
                    raise ValueError(
                        f"{path}: event {event_id!r} names source_id {source_id!r}, which is "
                        "not an allowed manual-intake contract"
                    )
                if qualification.get("underlying_publisher_required") and not event.get(
                    "underlying_publisher"
                ):
                    raise ValueError(
                        f"{path}: event {event_id!r} is from a source whose contract requires "
                        "an underlying publisher, but none was recorded"
                    )

            if now is not None:
                reviewed_at = parse_timestamp(event["reviewed_at"])
                if reviewed_at > now:
                    raise ValueError(
                        f"{path}: event {event_id!r} has reviewed_at {event['reviewed_at']!r}, "
                        "which is later than this build's as-of time"
                    )

            events_by_source.setdefault(source_id, []).append(event)
    return events_by_source
