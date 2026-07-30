"""WO-016: offline structural accessibility and payload-budget checks.

``docs/dashboard_user_guide.md`` §6 makes several accessibility claims --
semantic headings, a working skip link, labelled landmarks, no color-only
status, and (implicitly, via the "no external font/script" boundary) a
bounded payload -- that were never machine-checked. These tests do not
render the page or run a real accessibility engine; they parse the
committed ``index.html``/``styles.css`` with the stdlib only (no new
dependency) and check the specific, narrow properties named above. A green
suite here is evidence those specific properties hold, not a general
accessibility audit.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "dashboard" / "public"

_HEADING_LEVELS = {f"h{n}": n for n in range(1, 7)}
_LANDMARK_TAGS = {"nav", "section"}

# WCAG 2.1 SC 1.4.3 (AA), normal text.
_WCAG_AA_NORMAL_TEXT_RATIO = 4.5


class _DashboardHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_attrs: dict[str, str] = {}
        self.heading_levels: list[int] = []
        self.ids: set[str] = set()
        self.landmarks: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: (value or "") for key, value in attrs}
        if tag == "html":
            self.html_attrs = attrs_dict
        if "id" in attrs_dict:
            self.ids.add(attrs_dict["id"])
        if tag in _HEADING_LEVELS:
            self.heading_levels.append(_HEADING_LEVELS[tag])
        if tag in _LANDMARK_TAGS or attrs_dict.get("role") == "region":
            self.landmarks.append(attrs_dict)


def _parse_index_html() -> _DashboardHtmlParser:
    parser = _DashboardHtmlParser()
    parser.feed((PUBLIC / "index.html").read_text(encoding="utf-8"))
    return parser


def test_the_page_has_exactly_one_h1() -> None:
    parser = _parse_index_html()
    assert parser.heading_levels.count(1) == 1


def test_heading_levels_never_skip() -> None:
    """A heading may drop to any shallower level (closing a subsection), but
    may only go one level deeper than the immediately preceding heading --
    e.g. h2 -> h3 is fine, h2 -> h4 is a skip a screen-reader user can't
    navigate past."""
    parser = _parse_index_html()
    previous_level = 0
    for level in parser.heading_levels:
        if level > previous_level:
            assert level - previous_level == 1, (
                f"heading level jumped from h{previous_level} to h{level} "
                "without an intervening heading"
            )
        previous_level = level


def test_html_lang_attribute_is_present() -> None:
    parser = _parse_index_html()
    assert parser.html_attrs.get("lang", "").strip()


def test_skip_link_target_exists() -> None:
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<a class="skip-link" href="#([\w-]+)"', html)
    assert match, "expected a 'skip-link' anchor with a same-page #target"
    target_id = match.group(1)

    parser = _parse_index_html()
    assert target_id in parser.ids, f"skip-link target '#{target_id}' has no matching id"


def test_every_landmark_has_an_accessible_name() -> None:
    parser = _parse_index_html()
    assert parser.landmarks, "expected at least one nav/section/role=region landmark"

    for attrs in parser.landmarks:
        aria_label = attrs.get("aria-label", "").strip()
        labelled_by = attrs.get("aria-labelledby", "").strip()
        if aria_label:
            continue
        assert labelled_by, f"landmark {attrs} has neither aria-label nor aria-labelledby"
        assert labelled_by in parser.ids, (
            f"landmark's aria-labelledby='{labelled_by}' has no matching id"
        )


def _extract_root_css_variables(css_text: str) -> dict[str, str]:
    root_block = re.search(r":root\s*\{([^}]*)\}", css_text)
    assert root_block, "expected a :root custom-property block in styles.css"
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", root_block.group(1)))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_channel_to_linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    r, g, b = (_srgb_channel_to_linear(c) for c in _hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.1 relative-luminance contrast formula (SC 1.4.3)."""
    luminance_a, luminance_b = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(luminance_a, luminance_b), min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_calculator_matches_a_known_wcag_reference_pair() -> None:
    """Regression for the calculator itself: black-on-white is the textbook
    21:1 case every WCAG contrast tool agrees on."""
    assert _contrast_ratio("#000000", "#ffffff") == 21.0


def test_every_text_colour_pairing_meets_wcag_aa_normal_text() -> None:
    """Every foreground/background colour pairing actually used together in
    styles.css for body text, links, pills and muted text -- read from the
    stylesheet's own :root custom properties plus the literal hex values
    used inline for pill/badge text, not a separately maintained palette."""
    css = (PUBLIC / "assets" / "styles.css").read_text(encoding="utf-8")
    variables = _extract_root_css_variables(css)

    def var(name: str) -> str:
        assert name in variables, f"expected --{name} in styles.css :root"
        return variables[name]

    pairs = {
        "body text on page background": (var("ink"), var("bg")),
        "link colour on page background": (var("accent"), var("bg")),
        "skip-link / header text on accent background": ("#ffffff", var("accent")),
        "pill-critical text on its background": ("#7a1a15", var("critical-bg")),
        "pill-warning text on its background": ("#5c4100", var("warning-bg")),
        "pill-ok text on its background": ("#14501f", var("ok-bg")),
        "pill-note text on its background": ("#0e3550", var("note-bg")),
        "pill-demo / demo-heading badge text on its background": ("#452a70", var("demo-bg")),
        "pill-muted text on its background": ("#46525f", "#eef0f3"),
        "muted text ('missing', captions, labels) on page background": (
            var("ink-muted"),
            var("bg"),
        ),
        "muted text on card surface": (var("ink-muted"), var("surface")),
    }

    failures = {
        name: round(_contrast_ratio(fg, bg), 2)
        for name, (fg, bg) in pairs.items()
        if _contrast_ratio(fg, bg) < _WCAG_AA_NORMAL_TEXT_RATIO
    }
    assert not failures, (
        f"these colour pairings fall below the WCAG AA {_WCAG_AA_NORMAL_TEXT_RATIO}:1 "
        f"normal-text threshold: {failures}"
    )


# WO-016: current total is ~1.1 MB (ocean.json alone is ~450 KB). These
# ceilings are documented in docs/dashboard_user_guide.md alongside the
# justification for the headroom, and are a payload *budget*, not a
# reflection of what's currently shipped -- they should stay well above the
# current size rather than track it exactly.
_MAX_TOTAL_SITE_BYTES = 3 * 1024 * 1024
_MAX_SINGLE_PAYLOAD_BYTES = 1024 * 1024


def test_total_published_site_stays_within_its_documented_budget() -> None:
    total_bytes = sum(path.stat().st_size for path in PUBLIC.rglob("*") if path.is_file())
    assert total_bytes <= _MAX_TOTAL_SITE_BYTES, (
        f"dashboard/public is {total_bytes:,} bytes, over the "
        f"{_MAX_TOTAL_SITE_BYTES:,}-byte documented budget"
    )


def test_no_single_data_payload_exceeds_its_documented_budget() -> None:
    data_dir = PUBLIC / "data"
    payloads = sorted(data_dir.glob("*.json"))
    assert payloads, f"expected at least one JSON payload under {data_dir}"

    oversized = {
        path.name: path.stat().st_size
        for path in payloads
        if path.stat().st_size > _MAX_SINGLE_PAYLOAD_BYTES
    }
    assert not oversized, (
        f"these payloads exceed the {_MAX_SINGLE_PAYLOAD_BYTES:,}-byte per-file budget: {oversized}"
    )
