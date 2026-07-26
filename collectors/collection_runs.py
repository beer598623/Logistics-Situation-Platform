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
from pathlib import Path
from typing import Any

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
) -> dict[str, list[dict[str, Any]]]:
    """Every recorded manual-intake review event, grouped by ``source_id``.

    Not schema-validated against a shared platform schema: a manual review
    event is intentionally a much smaller, source-specific shape (who
    reviewed, when, how many bounded records) than a network collection
    manifest, and forcing it through ``collection_run.schema.json`` would
    require inventing null values for fields -- request URL, HTTP status,
    content hash -- that a manual transcription genuinely has none of.
    """
    target = directory if directory is not None else MANUAL_REVIEW_EVENTS_DIR
    events_by_source: dict[str, list[dict[str, Any]]] = {}
    if not target.exists():
        return events_by_source
    for path in sorted(target.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document.get("events", []):
            events_by_source.setdefault(event["source_id"], []).append(event)
    return events_by_source
