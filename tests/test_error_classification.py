from __future__ import annotations

import pytest

from collectors.adapters.cap import CapSecurityError, MalformedCapAlertError
from collectors.adapters.rss_discovery import (
    NotAnRssEnvelopeError,
    RssParseError,
    RssSecurityError,
)
from collectors.adapters.xml_envelope import EnvelopeParseError, EnvelopeSecurityError
from collectors.error_classification import classify_error
from collectors.http_client import UnexpectedContentTypeError


@pytest.mark.parametrize(
    ("exc", "expected_category"),
    [
        (SystemExit("bad range"), "validation"),
        (CapSecurityError("boom"), "security"),
        (EnvelopeSecurityError("boom"), "security"),
        (RssSecurityError("boom"), "security"),
        (MalformedCapAlertError("boom"), "parse"),
        (NotAnRssEnvelopeError("boom"), "parse"),
        (EnvelopeParseError("boom"), "parse"),
        (RssParseError("boom"), "parse"),
        (UnexpectedContentTypeError("boom"), "content_type"),
        (ValueError("boom"), "validation"),
        (RuntimeError("boom"), "unexpected"),
    ],
)
def test_classify_error_maps_known_exception_types_to_a_stable_category(
    exc: BaseException, expected_category: str
) -> None:
    code, category = classify_error(exc)
    assert code == type(exc).__name__
    assert category == expected_category


def test_classify_error_never_raises_for_an_unrecognized_exception() -> None:
    code, category = classify_error(KeyError("unrecognized"))
    assert code == "KeyError"
    assert category == "unexpected"
