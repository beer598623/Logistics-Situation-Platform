"""TMD candidate reference validation and fixed-policy URL derivation
(WO-006 Scope A, Implementation v0.2.2).

This module accepts ONLY a bounded, enumerable candidate reference --
language selector, candidate filename, evidence workflow run ID, evidence
item index -- never an arbitrary URL, host, port, path, query, or
fragment. There is no field anywhere in this module's input model that
could carry a full URL, user-info, query, or fragment, so those are
structurally impossible to inject, not merely rejected by a runtime check.

The fetch target (scheme, hostname, port, path prefix) is derived entirely
from the fixed policy constants below -- never from ``config/sources.yaml``
or any other caller-supplied value. Every rejection in this module happens
before any DNS or network activity; nothing here imports ``socket``,
``ssl``, or any HTTP client.

Candidate evidence fields (``evidence_run_id``, ``evidence_item_index``)
are retained as provenance only -- they do not themselves authorize a
fetch. A live workflow gate still requires a human to have selected a
candidate filename actually observed in a reviewed WO-005 discovery
artifact; this module has no way to verify that itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .rss_discovery import MAX_ITEMS

#: Fixed policy -- never read from a source contract or any caller input.
CANDIDATE_SCHEME = "https"
CANDIDATE_HOSTNAME = "www.tmd.go.th"
CANDIDATE_PORT = 443

#: Mirrors the ``language`` convention already used by
#: ``collectors/adapters/tmd_cap.py::resolve_endpoint`` ("primary" for the
#: English endpoint, an ``alternate_endpoints`` label such as
#: "thai_language_cap" for the Thai one) so the same language selector
#: means the same thing across both modules, even though this module never
#: reads the contract itself.
_LANGUAGE_PATH_PREFIXES = {
    "primary": "/uploads/CAP/en/",
    "thai_language_cap": "/uploads/CAP/",
}

#: CAPTMD + 14 ASCII digits (a YYYYMMDDHHMMSS-shaped timestamp, not
#: validated as a real date/time here -- that is not this module's job) +
#: "_" + one-or-more ASCII digits + ".xml". Deliberately built from
#: explicit ``[0-9]`` character classes rather than ``\d`` so no Unicode
#: digit variant can match regardless of any regex flag.
_FILENAME_RE = re.compile(r"^CAPTMD[0-9]{14}_[0-9]+\.xml$")
_MAX_FILENAME_LENGTH = 100

#: A GitHub Actions run ID is a bounded decimal integer in practice; this
#: bound is deliberately generous while still rejecting anything URL- or
#: path-shaped.
_RUN_ID_RE = re.compile(r"^[0-9]{1,32}$")


class CandidateReferenceError(ValueError):
    """Raised when a candidate reference fails structural validation,
    before any DNS or network activity (WO-006 Scope A). The message
    describes which rule was violated, never the full rejected value
    verbatim beyond what the caller already supplied as input."""


class CandidateUnexpectedStatusError(RuntimeError):
    """Raised by ``TmdCapAdapter.validate_candidate`` when a candidate
    fetch returns an HTTP status other than 200 (redirects and 304 are
    handled separately, before this check). Defined here rather than in
    ``tmd_cap.py`` -- where it is actually raised -- solely so
    ``collectors/error_classification.py`` can import it without a
    circular dependency (``tmd_cap.py`` itself imports
    ``classify_error``)."""


class CandidateEnvelopeMismatchError(ValueError):
    """Raised by ``TmdCapAdapter.validate_candidate`` when a candidate's
    classified envelope kind is not ``cap_alert``. Candidate validation
    never reinterprets an RSS, Atom, or other XML document as a CAP
    alert. Defined here for the same import-cycle reason as
    ``CandidateUnexpectedStatusError`` above."""


@dataclass(slots=True, frozen=True)
class CandidateReference:
    """A validated, bounded candidate reference. Every field has already
    passed structural validation by the time this is constructed --
    nothing downstream needs to re-validate these values, only derive a
    request from them."""

    language: str
    candidate_filename: str
    evidence_run_id: str
    evidence_item_index: int


@dataclass(slots=True, frozen=True)
class DerivedCandidateRequest:
    """The fetch target derived from fixed policy plus a validated
    reference's language and filename. Never constructed from, and never
    carries, any caller-supplied host/port/query/fragment -- there is no
    such field on this dataclass."""

    scheme: str
    hostname: str
    port: int
    path: str

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.hostname}{self.path}"


def _require_ascii(value: str, *, field: str) -> None:
    if not value.isascii():
        raise CandidateReferenceError(
            f"{field} must contain only ASCII characters (no Unicode lookalikes)"
        )


def validate_language(language: str) -> str:
    """Reject any language label not in the fixed, enumerable allowlist --
    this is the only place a caller-supplied string selects between the
    two fixed path prefixes; it is never used to build a host or port."""
    if not isinstance(language, str) or language not in _LANGUAGE_PATH_PREFIXES:
        raise CandidateReferenceError(
            f"unknown candidate language label; expected one of {sorted(_LANGUAGE_PATH_PREFIXES)}"
        )
    return language


def validate_candidate_filename(candidate_filename: str) -> str:
    """Reject anything that is not exactly a bare, grammar-valid CAP
    candidate filename. Checked in layers with distinct, specific error
    messages (path separators, percent-encoding, dot segments, control
    characters, then the full grammar) even though the final grammar
    check alone would already reject all of them, so that a test or a
    diagnostic report can describe precisely which rule a given rejected
    value violated."""
    if not isinstance(candidate_filename, str) or not candidate_filename:
        raise CandidateReferenceError("candidate_filename must be a non-empty string")
    if len(candidate_filename) > _MAX_FILENAME_LENGTH:
        raise CandidateReferenceError("candidate_filename exceeds the maximum allowed length")
    _require_ascii(candidate_filename, field="candidate_filename")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate_filename):
        raise CandidateReferenceError("candidate_filename must not contain control characters")
    if "/" in candidate_filename or "\\" in candidate_filename:
        raise CandidateReferenceError("candidate_filename must not contain a path separator")
    if "%" in candidate_filename:
        raise CandidateReferenceError("candidate_filename must not contain percent-encoding")
    if ".." in candidate_filename:
        raise CandidateReferenceError("candidate_filename must not contain a dot segment")
    if "?" in candidate_filename or "#" in candidate_filename:
        raise CandidateReferenceError(
            "candidate_filename must not contain a query or fragment separator"
        )
    if "@" in candidate_filename or "://" in candidate_filename:
        raise CandidateReferenceError(
            "candidate_filename must not contain a URL scheme or user-info separator"
        )
    if not _FILENAME_RE.fullmatch(candidate_filename):
        raise CandidateReferenceError(
            "candidate_filename does not match the required CAPTMD<14 digits>_<digits>.xml grammar"
        )
    return candidate_filename


def validate_evidence_run_id(evidence_run_id: str) -> str:
    """Provenance only -- a bounded, purely numeric GitHub Actions run
    ID. This is never used to construct a request; it exists solely so a
    candidate validation result can record which reviewed WO-005
    discovery artifact a human claims the candidate filename came from."""
    if not isinstance(evidence_run_id, str) or not evidence_run_id:
        raise CandidateReferenceError("candidate_evidence_run_id must be a non-empty string")
    _require_ascii(evidence_run_id, field="candidate_evidence_run_id")
    if not _RUN_ID_RE.fullmatch(evidence_run_id):
        raise CandidateReferenceError(
            "candidate_evidence_run_id must be a bounded numeric GitHub Actions run ID"
        )
    return evidence_run_id


def validate_evidence_item_index(evidence_item_index: int) -> int:
    """Bounded to the discovery parser's own item limit
    (``rss_discovery.MAX_ITEMS``) -- an index a discovery run could never
    actually have produced is rejected here, before any network activity,
    rather than merely being an inert, unverifiable number."""
    if isinstance(evidence_item_index, bool) or not isinstance(evidence_item_index, int):
        raise CandidateReferenceError("candidate_evidence_item_index must be an integer")
    if not (0 <= evidence_item_index < MAX_ITEMS):
        raise CandidateReferenceError(
            f"candidate_evidence_item_index must be within the discovery item bound "
            f"[0, {MAX_ITEMS})"
        )
    return evidence_item_index


def build_candidate_reference(
    *,
    language: str,
    candidate_filename: str,
    evidence_run_id: str,
    evidence_item_index: int,
) -> CandidateReference:
    """Validate every field of a candidate reference and return an
    immutable, already-validated result. Raises
    ``CandidateReferenceError`` before any DNS or network activity if any
    field fails structural validation."""
    return CandidateReference(
        language=validate_language(language),
        candidate_filename=validate_candidate_filename(candidate_filename),
        evidence_run_id=validate_evidence_run_id(evidence_run_id),
        evidence_item_index=validate_evidence_item_index(evidence_item_index),
    )


def derive_candidate_request(reference: CandidateReference) -> DerivedCandidateRequest:
    """Derive the fetch target entirely from fixed policy constants plus
    the validated reference's language (selects a fixed path prefix) and
    filename (appended verbatim, having already passed grammar
    validation). ``reference`` has no host/port/query/fragment field to
    read from in the first place."""
    path_prefix = _LANGUAGE_PATH_PREFIXES[reference.language]
    return DerivedCandidateRequest(
        scheme=CANDIDATE_SCHEME,
        hostname=CANDIDATE_HOSTNAME,
        port=CANDIDATE_PORT,
        path=f"{path_prefix}{reference.candidate_filename}",
    )
