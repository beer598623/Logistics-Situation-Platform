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
    run_id: str
    source_id: str
    started_at: str
    completed_at: str
    status: RunStatus
    workflow_sha: str | None
    adapter_version: str
    request_url: str | None
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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def dry_run(
        cls, source_id: str, adapter_version: str, request_url: str | None
    ) -> "CollectionRun":
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
    records: list[dict[str, Any]]
    run: CollectionRun
    health: SourceHealth
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
