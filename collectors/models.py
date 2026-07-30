"""Typed collection and source-health records.

The collector layer returns records and provenance separately. No adapter may
write directly to published dashboard data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SourceStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    VERY_STALE = "very_stale"
    NO_DATA = "no_data"
    DISABLED = "disabled"
    ERROR = "error"


class RunStatus(StrEnum):
    SUCCESS = "success"
    NOT_MODIFIED = "not_modified"
    DISABLED = "disabled"
    ERROR = "error"
    DRY_RUN = "dry_run"


@dataclass(slots=True)
class SourceHealth:
    source_id: str
    status: SourceStatus
    last_checked_at: str | None
    last_success_at: str | None
    last_error: str | None
    item_count: int | None
    required_for_publication: bool
    max_stale_minutes: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(slots=True)
class CollectionRun:
    """WO-010-R7-R1: emitted_records/output_manifest_sha256/supersedes_run_id
    are now universally required by schemas/collection_run.schema.json, so
    every CollectionRun carries them. The None defaults are correct for
    dry_run() and for the error/disabled/dry_run branch of the schema's
    per-status rules -- records_emitted is null, never 0, for a status that
    produced no manifest at all, since 0 is reserved for a success run whose
    manifest genuinely has zero entries.

    They are NOT sufficient, on their own, to make a GDACS/TMD adapter's
    success or not_modified run schema-valid: neither adapter populates an
    output manifest, so a real success run from either still fails
    schema.collection_run.schema.json's 'success' allOf block (which
    requires non-null emitted_records/output_manifest_sha256), and a real
    not_modified (304) run still fails its own required records_emitted/
    supersedes_run_id. This predates WO-010-R7-R1 and is unchanged by it --
    no adapter output is validated against this schema or persisted to
    data/collection_runs/ by any current code path (scripts/collect.py and
    scripts/manual_live_source_test.py only print/report it); only
    dry_run() is schema-validated, by tests/test_data_contracts.py.
    """

    run_id: str
    source_id: str
    started_at: str
    completed_at: str
    status: RunStatus
    workflow_sha: str | None
    adapter_version: str
    request_url: str | None
    response_url: str | None
    content_type: str | None
    http_status: int | None
    etag: str | None
    last_modified: str | None
    content_sha256: str | None
    records_received: int | None
    records_emitted: int | None
    records_rejected: int | None
    data_cutoff_at: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    emitted_records: list[dict[str, Any]] | None = None
    output_manifest_sha256: str | None = None
    supersedes_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def dry_run(
        cls,
        source_id: str,
        adapter_version: str,
        request_url: str | None,
    ) -> CollectionRun:
        now = datetime.now(UTC).replace(microsecond=0)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        iso = now.isoformat().replace("+00:00", "Z")
        return cls(
            run_id=f"COL-{stamp}-{source_id}",
            source_id=source_id,
            started_at=iso,
            completed_at=iso,
            status=RunStatus.DRY_RUN,
            workflow_sha=None,
            adapter_version=adapter_version,
            request_url=request_url,
            response_url=None,
            content_type=None,
            http_status=None,
            etag=None,
            last_modified=None,
            content_sha256=None,
            records_received=None,
            records_emitted=None,
            records_rejected=None,
            data_cutoff_at=None,
            warnings=["Dry run validates contracts only; no network request was made."],
            errors=[],
        )


@dataclass(slots=True)
class CollectionResult:
    """Wraps one adapter run's records and provenance.

    ``error_code`` / ``error_category`` / ``envelope_classification`` are
    deliberately *not* part of ``CollectionRun`` or
    ``schemas/collection_run.schema.json`` -- that schema is shared with
    every adapter (including GDACS) and is intentionally frozen. These
    three fields are optional, script-facing diagnostics only (WO-004
    v0.2.1 review round 1, finding 4): a stable structured error
    code/category for an adapter-handled failure, and the structural
    envelope classification when one was computed, so the manual-test
    report can surface them without a schema change. They default to
    ``None`` and are left unset by every adapter that has no reason to
    populate them (e.g. GDACS, or a successful TMD run).
    """

    records: list[dict[str, Any]]
    run: CollectionRun
    health: SourceHealth
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_category: str | None = None
    envelope_classification: dict[str, Any] | None = None
