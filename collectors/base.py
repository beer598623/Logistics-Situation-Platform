"""Base interface for source-specific collection adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from .http_client import ResilientHttpClient
from .models import CollectionResult


class SourceAdapter(ABC):
    """A source adapter transforms one source contract into normalized records.

    Adapters must not infer operational impact. They may detect candidates and
    preserve source-provided classifications, but impact analysis belongs to the
    reviewed intelligence workflow.
    """

    adapter_version = "base_v1"

    def __init__(self, contract: Mapping[str, Any], http: ResilientHttpClient | None = None) -> None:
        self.contract = contract
        self.http = http or ResilientHttpClient()

    @property
    def source_id(self) -> str:
        return str(self.contract["id"])

    @abstractmethod
    def collect(self) -> CollectionResult:
        """Collect and normalize records without publishing them."""
