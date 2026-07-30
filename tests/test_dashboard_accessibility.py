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


_RULE_PATTERN = re.compile(r"([^{}]+)\{([^{}]*)\}")
_HEX_LITERAL = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_VAR_REFERENCE = re.compile(r"^var\(--([\w-]+)\)$")


def _parse_css_rules(css_text: str) -> dict[str, dict[str, str]]:
    """Maps each exact selector text to its declared properties. Later rules
    for the same selector text overwrite earlier ones, matching how a real
    stylesheet's cascade would resolve a repeated selector."""
    rules: dict[str, dict[str, str]] = {}
    for selector, body in _RULE_PATTERN.findall(css_text):
        declarations: dict[str, str] = {}
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            prop, _, value = declaration.partition(":")
            declarations[prop.strip()] = value.strip()
        rules[selector.strip()] = declarations
    return rules


def _resolve_colour(value: str | None, variables: dict[str, str]) -> str | None:
    if value is None:
        return None
    var_match = _VAR_REFERENCE.match(value)
    if var_match:
        return variables.get(var_match.group(1))
    if _HEX_LITERAL.match(value):
        return value
    return None


def _declared_colour(
    rules: dict[str, dict[str, str]], selector: str, variables: dict[str, str]
) -> str:
    assert selector in rules, f"expected a '{selector}' rule in styles.css"
    colour = _resolve_colour(rules[selector].get("color"), variables)
    assert colour, f"'{selector}' has no resolvable 'color' declaration"
    return colour


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
    assert abs(_contrast_ratio("#000000", "#ffffff") - 21.0) < 1e-9


def test_every_self_contained_text_colour_pairing_meets_wcag_aa() -> None:
    """A rule is 'self-contained' when it sets both `color` and a background
    (`background`/`background-color`) on the same selector -- the pairing is
    unambiguous from the rule alone, no cascade knowledge needed. This covers
    every pill/badge, the skip link, the site header, and body text, and
    reads both colours from the actual declarations rather than a copied
    literal, so a changed pill colour cannot silently stop being tested."""
    css = (PUBLIC / "assets" / "styles.css").read_text(encoding="utf-8")
    variables = _extract_root_css_variables(css)
    rules = _parse_css_rules(css)

    self_contained: dict[str, tuple[str, str]] = {}
    for selector, declarations in rules.items():
        colour = _resolve_colour(declarations.get("color"), variables)
        background = _resolve_colour(
            declarations.get("background") or declarations.get("background-color"), variables
        )
        if colour and background:
            self_contained[selector] = (colour, background)

    # Guards this test against becoming vacuous if styles.css is ever
    # restructured so no rule sets both properties together.
    assert self_contained, "expected at least one rule to set both color and a background"
    for expected in (".pill-critical", ".pill-warning", ".pill-ok", ".pill-note", ".pill-demo"):
        assert expected in self_contained, f"expected '{expected}' to set both color and background"

    failures = {
        selector: round(_contrast_ratio(fg, bg), 2)
        for selector, (fg, bg) in self_contained.items()
        if _contrast_ratio(fg, bg) < _WCAG_AA_NORMAL_TEXT_RATIO
    }
    assert not failures, (
        f"these self-contained colour pairings fall below the WCAG AA "
        f"{_WCAG_AA_NORMAL_TEXT_RATIO}:1 normal-text threshold: {failures}"
    )


def test_every_cascaded_text_colour_pairing_meets_wcag_aa() -> None:
    """A 'cascaded' pairing is a selector whose `color` rule does not also
    set its own background -- the background it actually renders against
    comes from an ancestor element and can't be derived from the stylesheet
    alone without a real cascade/layout engine. The associations below were
    verified by reading styles.css's actual selector structure (every one of
    these selectors sits inside `section { background: var(--surface) }`,
    confirmed by grepping for any closer override and finding none), but
    each foreground colour is still read from its own rule -- only the
    background side is hand-verified, not both."""
    css = (PUBLIC / "assets" / "styles.css").read_text(encoding="utf-8")
    variables = _extract_root_css_variables(css)
    rules = _parse_css_rules(css)
    surface = variables["surface"]

    # selector -> background it actually renders against (all --surface: none
    # of these selectors, or any ancestor between them and <section>, sets a
    # closer background override).
    cascaded_backgrounds = {
        "a": surface,
        ".missing": surface,
        ".card .label": surface,
        ".card .note": surface,
        ".section-intro": surface,
        "caption": surface,
        ".figure .label": surface,
        ".lane-card .meta": surface,
        ".series .series-meta": surface,
        ".gap-list li::marker": surface,
        ".chain li.absent": surface,
    }

    failures = {}
    for selector, background in cascaded_backgrounds.items():
        colour = _declared_colour(rules, selector, variables)
        ratio = _contrast_ratio(colour, background)
        if ratio < _WCAG_AA_NORMAL_TEXT_RATIO:
            failures[selector] = round(ratio, 2)

    assert not failures, (
        f"these cascaded colour pairings fall below the WCAG AA "
        f"{_WCAG_AA_NORMAL_TEXT_RATIO}:1 normal-text threshold: {failures}"
    )


# WO-016: current total is ~1.1 MB (ocean.json alone is ~460 KB), using
# decimal megabytes throughout (1 MB = 1,000,000 bytes) to match
# docs/dashboard_user_guide.md's wording exactly. These ceilings are
# documented there alongside the justification for the headroom, and are a
# payload *budget*, not a reflection of what's currently shipped -- they
# should stay well above the current size rather than track it exactly.
_MAX_TOTAL_SITE_BYTES = 3_000_000
_MAX_SINGLE_PAYLOAD_BYTES = 1_000_000


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
