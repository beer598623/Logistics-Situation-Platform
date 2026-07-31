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
        # WO-018: the heading level in effect at the moment each id is seen,
        # in document order -- i.e. the level of the nearest heading that
        # precedes it. Recorded for every id, not just container ids, since
        # the parser doesn't know in advance which ids app.js will target.
        self.preceding_heading_level: dict[str, int] = {}
        self._current_heading_level = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: (value or "") for key, value in attrs}
        if tag == "html":
            self.html_attrs = attrs_dict
        if "id" in attrs_dict:
            self.ids.add(attrs_dict["id"])
            self.preceding_heading_level[attrs_dict["id"]] = self._current_heading_level
        if tag in _HEADING_LEVELS:
            self.heading_levels.append(_HEADING_LEVELS[tag])
            self._current_heading_level = _HEADING_LEVELS[tag]
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


_EL_INNERHTML_ASSIGNMENT = re.compile(r"el\('(?P<id>[\w-]+)'\)\.innerHTML\s*=\s*")
_FUNCTION_DEF = re.compile(r"function\s+(\w+)\s*\([^)]*\)\s*\{")
_JS_HEADING_LITERAL = re.compile(r"<h([1-6])>")


def _js_function_bodies(js_text: str) -> dict[str, str]:
    """Maps each top-level named function in app.js to its balanced-brace
    body text, by counting braces from the opening one -- app.js has no
    strings or comments containing an unmatched brace, so this is sufficient
    without a real JS parser."""
    bodies: dict[str, str] = {}
    for match in _FUNCTION_DEF.finditer(js_text):
        depth = 1
        i = match.end()
        while depth > 0 and i < len(js_text):
            if js_text[i] == "{":
                depth += 1
            elif js_text[i] == "}":
                depth -= 1
            i += 1
        bodies[match.group(1)] = js_text[match.end() : i - 1]
    return bodies


def _js_statement_after(js_text: str, start: int) -> str:
    """Returns the text from `start` up to the terminating semicolon of the
    statement, tracking bracket depth so a `;` inside a nested function body
    or array literal doesn't end the statement early."""
    depth = 0
    i = start
    while i < len(js_text):
        ch = js_text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth <= 0:
            return js_text[start:i]
        i += 1
    raise AssertionError("unterminated statement while scanning app.js")


def test_dynamically_injected_headings_never_skip_a_level() -> None:
    """WO-018 / Issue #32. ``test_heading_levels_never_skip`` above only
    parses the *committed* index.html; content app.js injects into an empty
    container at runtime was invisible to it. That gap let the Trade, Cost
    and Outlook sections skip from h2 straight to h4 -- Trade and Cost had no
    static <h3> in the section at all, and the Outlook instance was latent
    only because its backing fixture data happened to be empty, not because
    the code differed.

    This test resolves, for every ``el('literal-id').innerHTML = ...``
    assignment in app.js, which heading level(s) that statement can inject --
    either a literal ``<hN>`` in the statement text itself, or (one level of
    indirection) a call to a named app.js function whose own body contains a
    literal, resolved by reading that function's actual source rather than
    hardcoding which helper emits which level (the WO-016 review found a
    hardcoded-literal version of a different check silently stopped tracking
    its target). It then checks the *shallowest* level found against the
    nearest preceding heading actually present in the committed index.html.
    This is deliberately independent of any JSON payload: it would have
    caught the Outlook containers even while ``ai_outlook.json`` was empty,
    and it catches the whole class of defect, not just today's instances.

    Known gap: the six ``events-*`` containers in ``renderEvents`` are
    populated via ``el(entry[0]).innerHTML = ...`` inside a loop over an
    array literal, not a literal ``el('id')`` call, so this regex-based scan
    does not resolve them. They were manually verified correct (each is
    already preceded by its own static <h3>) at the time this test was
    written; a regression there would not be caught here.

    A second, narrower known gap in the indirection step itself: a helper's
    levels are credited to a statement on any textual mention of its name,
    not on confirming that mention is actually a call/reference the runtime
    would execute. Every heading literal in app.js today is <h4>, so this
    can't currently produce a false pass -- crediting a level that already
    equals the correct expectation changes nothing -- but it would stop
    being inert if a helper ever emitted a different level."""
    js_text = (PUBLIC / "assets" / "app.js").read_text(encoding="utf-8")
    html_text = (PUBLIC / "index.html").read_text(encoding="utf-8")

    function_levels = {
        name: {int(n) for n in _JS_HEADING_LITERAL.findall(body)}
        for name, body in _js_function_bodies(js_text).items()
    }
    function_levels = {name: levels for name, levels in function_levels.items() if levels}
    assert function_levels, "expected at least one app.js function to contain a heading literal"

    html_parser = _DashboardHtmlParser()
    html_parser.feed(html_text)

    checked = 0
    failures: dict[str, dict[str, object]] = {}
    for match in _EL_INNERHTML_ASSIGNMENT.finditer(js_text):
        container_id = match.group("id")
        if container_id not in html_parser.preceding_heading_level:
            continue
        statement = _js_statement_after(js_text, match.end())

        levels = {int(n) for n in _JS_HEADING_LITERAL.findall(statement)}
        for name, name_levels in function_levels.items():
            if re.search(r"\b" + re.escape(name) + r"\b", statement):
                levels |= name_levels
        if not levels:
            continue

        checked += 1
        expected = html_parser.preceding_heading_level[container_id] + 1
        shallowest = min(levels)
        if shallowest != expected:
            failures[container_id] = {
                "emits": sorted(levels),
                "expected_shallowest": expected,
                "preceded_by_heading_level": html_parser.preceding_heading_level[container_id],
            }

    # Guards against the scan becoming vacuous if app.js is restructured away
    # from the el('literal-id').innerHTML pattern this regex expects. 15
    # containers resolve today (Ocean 5, Trade 2, Cost 3, Outlook 4, Sources
    # 1); the floor is set one below that, not at the six containers this WO
    # fixed, so losing coverage over most of the resolved set would still
    # fail here even though six alone would keep passing.
    assert checked >= 14, (
        "expected to statically resolve heading levels for at least 14 of the 15 containers "
        f"this test currently covers (Trade/Cost/Outlook plus the already-correct others); "
        f"resolved {checked}"
    )
    assert not failures, (
        "these app.js-injected containers emit a heading level that is not exactly one level "
        f"deeper than the nearest preceding static heading in index.html: {failures}"
    )


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
    """Maps each exact selector text to its declared properties, merging
    declarations across repeated occurrences of the same selector text (a
    later declaration for the same property overwrites an earlier one) --
    closer to how a real cascade resolves a repeated selector than simply
    replacing the whole rule would be. Comments are stripped first so a
    selector immediately after a `/* ... */` block isn't captured as part of
    its own key."""
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    rules: dict[str, dict[str, str]] = {}
    for selector, body in _RULE_PATTERN.findall(css_text):
        declarations = rules.setdefault(selector.strip(), {})
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            prop, _, value = declaration.partition(":")
            declarations[prop.strip()] = value.strip()
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
    verified by reading styles.css's actual selector structure and, where a
    selector can render in more than one context (e.g. inside an even table
    row, or inside a `.demo-panel`), the stricter (lower-contrast) of the
    real backgrounds it actually appears against was used -- not just the
    common case. This mapping is hand-verified and not exhaustive: a new
    colour-only rule added to styles.css would not automatically appear
    here. Each foreground colour is still read from its own CSS rule; only
    the background side is hand-verified, not both."""
    css = (PUBLIC / "assets" / "styles.css").read_text(encoding="utf-8")
    variables = _extract_root_css_variables(css)
    rules = _parse_css_rules(css)
    surface = variables["surface"]

    # selector -> background it actually renders against. Most sit directly
    # inside `section { background: var(--surface) }` with no closer
    # override. Two exceptions render in a context with a slightly different
    # (still light) background; the stricter one is used:
    #   .missing appears in table cells, including even rows where
    #     `tbody tr:nth-child(even)` sets `background: #fafbfc`.
    #   .lane-card .meta can render inside `.demo-panel`
    #     (`background: var(--demo-bg)`) via the demoPanel() helper.
    cascaded_backgrounds = {
        "a": surface,
        ".missing": "#fafbfc",
        ".card .label": surface,
        ".card .note": surface,
        ".section-intro": surface,
        "caption": surface,
        ".figure .label": surface,
        ".lane-card .meta": variables["demo-bg"],
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
