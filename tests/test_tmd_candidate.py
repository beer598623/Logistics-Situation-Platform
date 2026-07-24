"""WO-006 Scope A/G: candidate reference validation and fixed-policy URL
derivation. Pure functions -- no network, no DNS, no filesystem I/O."""

from __future__ import annotations

import pytest

from collectors.adapters.rss_discovery import MAX_ITEMS
from collectors.adapters.tmd_candidate import (
    CANDIDATE_HOSTNAME,
    CANDIDATE_PORT,
    CANDIDATE_SCHEME,
    CandidateReferenceError,
    build_candidate_reference,
    derive_candidate_request,
)

VALID_FILENAME = "CAPTMD20260723155032_2.xml"
VALID_RUN_ID = "30028391246"


def _build(**overrides):
    kwargs = {
        "language": "primary",
        "candidate_filename": VALID_FILENAME,
        "evidence_run_id": VALID_RUN_ID,
        "evidence_item_index": 0,
    }
    kwargs.update(overrides)
    return build_candidate_reference(**kwargs)


# --- Exact fixed-policy URL derivation ---------------------------------------


def test_english_candidate_derives_the_exact_fixed_policy_url() -> None:
    reference = _build(language="primary")
    derived = derive_candidate_request(reference)
    assert derived.scheme == CANDIDATE_SCHEME == "https"
    assert derived.hostname == CANDIDATE_HOSTNAME == "www.tmd.go.th"
    assert derived.port == CANDIDATE_PORT == 443
    assert derived.path == f"/uploads/CAP/en/{VALID_FILENAME}"
    assert derived.url == f"https://www.tmd.go.th/uploads/CAP/en/{VALID_FILENAME}"


def test_thai_candidate_derives_the_exact_fixed_policy_url() -> None:
    reference = _build(language="thai_language_cap")
    derived = derive_candidate_request(reference)
    assert derived.path == f"/uploads/CAP/{VALID_FILENAME}"
    assert derived.url == f"https://www.tmd.go.th/uploads/CAP/{VALID_FILENAME}"


# --- Accepted filename grammar -----------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "CAPTMD20260723155032_2.xml",
        "CAPTMD00000000000000_1234567890.xml",
        "CAPTMD20260723155032_0.xml",
    ],
)
def test_accepted_filename_grammar(filename: str) -> None:
    reference = _build(candidate_filename=filename)
    assert reference.candidate_filename == filename


# --- Rejections: unknown language, never an arbitrary host/port -------------


def test_unknown_language_label_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(language="chinese_language_cap")


def test_empty_language_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(language="")


# --- Rejections: filename grammar, before any DNS/network activity ----------


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "CAPTMD20260723155032_2.XML",  # wrong case extension
        "CAPTMD2026072315503_2.xml",  # 13 digits, not 14
        "CAPTMD20260723155032.xml",  # missing "_<digits>"
        "captmd20260723155032_2.xml",  # lowercase prefix
        "CAPTMD20260723155032_2.xml.exe",  # extra suffix
        " CAPTMD20260723155032_2.xml",  # leading space
        "CAPTMD20260723155032_2.xml ",  # trailing space
    ],
)
def test_grammar_invalid_filenames_are_rejected(filename: str) -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename=filename)


def test_full_url_input_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="https://www.tmd.go.th/uploads/CAP/en/" + VALID_FILENAME)


def test_alternate_host_embedded_in_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="evil.test/" + VALID_FILENAME)


def test_alternate_port_shaped_value_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="www.tmd.go.th:8443/" + VALID_FILENAME)


def test_userinfo_in_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="user:pass@" + VALID_FILENAME)


def test_query_string_in_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename=VALID_FILENAME + "?x=1")


def test_fragment_in_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename=VALID_FILENAME + "#frag")


def test_slash_in_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="sub/" + VALID_FILENAME)


def test_backslash_in_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="sub\\" + VALID_FILENAME)


def test_dot_segment_traversal_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="../../etc/passwd")


def test_percent_encoded_separator_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="%2e%2e%2fCAPTMD20260723155032_2.xml")


def test_percent_encoded_traversal_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="CAPTMD20260723155032_2.xml%00")


def test_control_characters_are_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="CAPTMD20260723155032_2.xml\x00")


def test_unicode_lookalike_digits_are_rejected() -> None:
    # U+FF10 FULLWIDTH DIGIT ZERO in place of an ASCII '0'.
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="CAPTMD2026072315503２_2.xml")


def test_unicode_lookalike_hostname_free_text_is_rejected() -> None:
    # Cyrillic 'а' (U+0430) homoglyph, not the ASCII CAPTMD prefix.
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename="CАPTMD20260723155032_2.xml")


def test_overlong_filename_is_rejected() -> None:
    overlong = "CAPTMD20260723155032_" + ("1" * 200) + ".xml"
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename=overlong)


def test_non_string_filename_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(candidate_filename=None)  # type: ignore[arg-type]


# --- Rejections: evidence fields are bounded, never authorization ----------


def test_evidence_item_index_at_upper_bound_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_item_index=MAX_ITEMS)


def test_evidence_item_index_within_bound_is_accepted() -> None:
    reference = _build(evidence_item_index=MAX_ITEMS - 1)
    assert reference.evidence_item_index == MAX_ITEMS - 1


def test_negative_evidence_item_index_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_item_index=-1)


def test_non_integer_evidence_item_index_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_item_index="0")  # type: ignore[arg-type]


def test_boolean_evidence_item_index_is_rejected() -> None:
    # bool is a subclass of int in Python; explicitly rejected so True/False
    # can never silently pass as 1/0.
    with pytest.raises(CandidateReferenceError):
        _build(evidence_item_index=True)  # type: ignore[arg-type]


def test_empty_evidence_run_id_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_run_id="")


def test_non_numeric_evidence_run_id_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_run_id="not-a-run-id")


def test_url_shaped_evidence_run_id_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_run_id="https://evil.test/x")


def test_overlong_evidence_run_id_is_rejected() -> None:
    with pytest.raises(CandidateReferenceError):
        _build(evidence_run_id="1" * 64)
