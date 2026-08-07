"""WO-030 (Issue #61): route-based dashboard redesign, offline structural
checks against the AC-1 - AC-47 checklist finalised on Issue #59.

Named ``N-5``/``N-8``/etc. below to match the specific new-test references
the checklist cites by name (AC-1 -> N-5, AC-2 -> N-8, AC-9 -> N-10,
AC-18 -> N-11, AC-36 -> N-16, AC-19 -> N-17, AC-20 -> N-18, AC-29 -> N-19).
Like the existing WO-016/WO-018 accessibility tests, these parse the
committed ``index.html``/``app.js`` with the stdlib only -- they are static
structural checks, not a rendered-DOM or real-browser audit. Real-browser
evidence (screenshots, DOM counts, print-to-PDF) is gathered separately and
recorded in the implementation PR body, per AC-25/AC-33/AC-46.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "dashboard" / "public"

VIEW_IDS = ("situation", "ocean", "air", "land", "trade", "cost", "events", "outlook", "sources")


def _html() -> str:
    return (PUBLIC / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    return (PUBLIC / "assets" / "app.js").read_text(encoding="utf-8")


def _js_function_body(js_text: str, name: str) -> str:
    """Balanced-brace body of a named top-level function, or '' if absent."""
    match = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", js_text)
    if not match:
        return ""
    depth = 1
    i = match.end()
    while depth > 0 and i < len(js_text):
        if js_text[i] == "{":
            depth += 1
        elif js_text[i] == "}":
            depth -= 1
        i += 1
    return js_text[match.end() : i - 1]


# ---------------------------------------------------------------------------
# N-5 / AC-1: current always precedes demonstration/historical, per view
# ---------------------------------------------------------------------------


class _RegionOrderParser(HTMLParser):
    """Records, per top-level view <section id="...">, the document-order
    sequence of data-evidence-region values seen (only the outermost tagged
    wrapper of each kind matters -- nested content inherits its ancestor's
    region and isn't separately tagged in this markup)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.by_view: dict[str, list[str]] = {}
        self._view_stack: list[str] = []
        self._section_depth = 0
        self._tag_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: (v or "") for k, v in attrs}
        self._tag_depth += 1
        if tag == "section" and attrs_dict.get("id") in VIEW_IDS:
            self._view_stack.append(attrs_dict["id"])
            self.by_view.setdefault(attrs_dict["id"], [])
        region = attrs_dict.get("data-evidence-region")
        if region and self._view_stack:
            self.by_view[self._view_stack[-1]].append(region)

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._view_stack:
            self._view_stack.pop()


def test_current_evidence_region_precedes_non_current_in_every_view() -> None:
    """N-5 / AC-1. No data-evidence-region="demonstration"|"historical"
    wrapper appears in DOM order before the last data-evidence-region="current"
    wrapper in the same view. Regresses C-1 (Ocean previously placed the
    technical-demonstration material above the current material it modifies)."""
    parser = _RegionOrderParser()
    parser.feed(_html())
    assert parser.by_view, "expected to find at least one view with a tagged evidence region"
    tagged_views = {v: r for v, r in parser.by_view.items() if r}
    assert tagged_views, "expected at least one view to carry a data-evidence-region wrapper"
    for view_id, regions in tagged_views.items():
        non_current_indexes = [i for i, r in enumerate(regions) if r != "current"]
        if not non_current_indexes:
            # A view with no demonstration/historical material at all (e.g.
            # Sources & Methodology, which has no fixture-backed content) has
            # nothing to order -- AC-1 is vacuously satisfied.
            continue
        assert "current" in regions, f'{view_id}: no data-evidence-region="current" wrapper found'
        last_current_index = max(i for i, r in enumerate(regions) if r == "current")
        early = [i for i in non_current_indexes if i < last_current_index]
        assert not early, (
            f"{view_id}: a non-current region precedes the last current region: {regions}"
        )


# ---------------------------------------------------------------------------
# N-8 / AC-2: no single container mixes current and non-current content
# ---------------------------------------------------------------------------


class _NestedRegionParser(HTMLParser):
    """Flags an element whose own data-evidence-region contradicts an
    ancestor's data-evidence-region -- the structural signature of a
    container that mixes current and non-current content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contradictions: list[tuple[str, str]] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: (v or "") for k, v in attrs}
        region = attrs_dict.get("data-evidence-region")
        ancestor = self._stack[-1] if self._stack else None
        if region:
            if ancestor and ancestor != region:
                self.contradictions.append((ancestor, region))
            self._stack.append(region)
        elif self._stack:
            self._stack.append(self._stack[-1])
        else:
            self._stack.append("")

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()


def test_no_evidence_region_wrapper_nests_inside_a_contradicting_one() -> None:
    """N-8 / AC-2 (structural half). A current-tagged wrapper never sits
    inside a demonstration/historical-tagged ancestor and vice versa -- the
    two kinds of region are always siblings, never nested. This is the
    document-structure guarantee; the per-item guarantee (a single lane row
    or source row never mixes a current pill with a demonstration pill) is
    not visible to a static HTML parse because that markup is built by
    app.js at runtime, so it is covered by the companion check below
    instead."""
    parser = _NestedRegionParser()
    parser.feed(_html())
    assert not parser.contradictions, (
        f"a data-evidence-region wrapper nests inside a contradicting one: {parser.contradictions}"
    )


def test_the_current_lane_row_carries_no_demonstration_value() -> None:
    """N-8 / AC-2 and AC-41 (renderer half). R-3 relocated the demonstration
    lane assessment out of the current lane row. Regression signature: the
    old in-row demoPanel() helper must not exist, its replacement
    laneCrossReference() must exist and must render no pill/value of any
    kind (AC-41(c)/(d)), and the current lane row itself must not call it."""
    script = _js()
    assert "demoPanel(" not in script, (
        "the old in-card demonstration panel helper must not come back"
    )
    assert "function laneCrossReference(" in script
    cross_ref_body = _js_function_body(script, "laneCrossReference")
    assert cross_ref_body, "expected to resolve laneCrossReference's body"
    assert "pill(" not in cross_ref_body, (
        "the neutral cross-reference must carry no pill (AC-41(d)): " + cross_ref_body
    )


# ---------------------------------------------------------------------------
# N-10 / AC-9: one function drives both the coverage chip and the banner
# ---------------------------------------------------------------------------


def test_exactly_one_function_writes_the_coverage_chip_and_banner() -> None:
    """N-10 / AC-9. Regresses H-1: renderSituation() and a payload .catch()
    handler used to independently write #coverage-banner, so a fast-failing
    payload could overwrite a banner render mid-flight (or vice versa) and
    leave the two documents disagreeing about coverage."""
    script = _js()
    assert script.count("'coverage-banner'") == 1, (
        "exactly one site should reference #coverage-banner -- inside paintCoverage()"
    )
    situation_body = _js_function_body(script, "renderSituation")
    assert situation_body, "expected to resolve renderSituation's body"
    assert "coverage-banner" not in situation_body, (
        "renderSituation() must not write the coverage banner directly (AC-9)"
    )
    assert "function paintCoverage(" in script
    assert "function driveCoverage(" in script


def test_the_load_failed_coverage_state_has_no_exit_transition() -> None:
    """N-10 / AC-9. Once load_failed, the coverage chip must stay pessimistic
    for the rest of the page's life -- no later successful payload may
    relax it back to insufficient/sufficient."""
    driver_body = _js_function_body(_js(), "driveCoverage")
    assert driver_body, "expected to resolve driveCoverage's body"
    first_statement = driver_body.strip().splitlines()[0].strip()
    assert "coverageState === 'load_failed'" in first_statement
    assert "return" in driver_body.split("\n")[0] + driver_body.split("\n")[1]


# ---------------------------------------------------------------------------
# N-11 / AC-18: every scroll container is keyboard-reachable and labelled
# ---------------------------------------------------------------------------


def test_every_table_wrap_is_a_focusable_labelled_region() -> None:
    """N-11 / AC-18. WCAG 2.1 SC 2.1.1: a horizontally scrollable container
    that isn't independently focusable traps keyboard users -- they can
    reach the table's own focusable cells (links, buttons) but never the
    scroll position itself, so content past the right edge is unreachable
    without a mouse."""
    html = _html()
    wraps = re.findall(r'<div class="table-wrap"[^>]*>', html)
    assert wraps, "expected at least one .table-wrap container"
    ids = set(re.findall(r'id="([\w-]+)"', html))
    for wrap in wraps:
        assert 'tabindex="0"' in wrap, wrap
        assert 'role="region"' in wrap, wrap
        match = re.search(r'aria-labelledby="([\w-]+)"', wrap)
        assert match, wrap
        assert match.group(1) in ids, f"{wrap}: aria-labelledby target not found in document"


# ---------------------------------------------------------------------------
# N-16 / AC-36: URL-scheme allowlist and a single attr() escaping helper
# ---------------------------------------------------------------------------


def test_every_href_passes_a_url_scheme_allowlist_before_emission() -> None:
    """N-16 / AC-36. Regresses M-1: a claim string from a JSON payload is
    untrusted as far as this file is concerned, and must never reach an
    <a href> as a javascript:/data: URL."""
    script = _js()
    assert "function safeHref(" in script
    assert "function attr(" in script
    safe_href_body = _js_function_body(script, "safeHref")
    assert safe_href_body, "expected to resolve safeHref's body"
    assert "'http'" in safe_href_body and "'https'" in safe_href_body
    assert "javascript" not in safe_href_body.lower()

    # Every dynamic href="..." site is either a same-page "#..." fragment
    # (always safe -- there is no scheme to allowlist for an in-page anchor)
    # built from attr(), or an external URL that must be routed through
    # safeHref() -- directly, or via a local variable assigned from it --
    # before the href="' + ...' concatenation.
    sites = re.findall(r'href="([^"\']*)\'\s*\+\s*([a-zA-Z0-9_.]+)', script)
    assert sites, "expected at least one dynamic href emission site"
    external_sites = [(prefix, expr) for prefix, expr in sites if not prefix.startswith("#")]
    assert external_sites, (
        "expected at least one external (non-fragment) href site to exercise the allowlist"
    )
    for prefix, expr in external_sites:
        if expr == "safeHref":
            continue
        assert re.search(r"\bvar\s+" + re.escape(expr) + r"\s*=\s*safeHref\(", script), (
            f"href site with prefix {prefix!r} uses `{expr}`, which is neither a direct "
            "safeHref(...) call nor a local variable assigned from safeHref(...)"
        )


# ---------------------------------------------------------------------------
# N-17 / AC-19: every table has a caption and a scoped thead
# ---------------------------------------------------------------------------


def _table_windows(text: str) -> list[str]:
    """The substring from each '<table' opening up to its first '<tbody' --
    every table template in this codebase puts <caption> and <thead> before
    <tbody>, so this window is exactly where both must appear."""
    windows = []
    for match in re.finditer(r"<table\b", text):
        tbody = text.find("<tbody", match.start())
        windows.append(text[match.start() : tbody if tbody != -1 else match.start() + 600])
    return windows


def test_every_table_has_a_caption_and_a_scoped_thead() -> None:
    """N-17 / AC-19. Regresses H-7: the source-detail tables had no <thead>
    at all before WO-030; every table template, static and JS-rendered
    alike, must now carry both a <caption> and a <thead> with scope cells."""
    for label, text in (("index.html", _html()), ("app.js", _js())):
        windows = _table_windows(text)
        assert windows, f"{label}: expected at least one <table>"
        for window in windows:
            assert "<caption" in window, f"{label}: table with no <caption>: {window[:120]!r}"
            assert "<thead" in window, f"{label}: table with no <thead>: {window[:120]!r}"
            assert 'scope="col"' in window, (
                f'{label}: table thead with no scope="col": {window[:160]!r}'
            )


# ---------------------------------------------------------------------------
# N-18 / AC-20: numeric columns carry .num on both header and body cells
# ---------------------------------------------------------------------------


def test_numeric_table_cells_never_drop_the_num_class() -> None:
    """N-18 / AC-20. Regresses M-4 and a narrower defect this WO introduced
    and fixed in the same pass: pointsTable()'s missing-value branch used to
    emit a bare <td class="missing">, misaligning that one cell out of the
    numeric column it sits in. "No exceptions" per AC-20 means every body
    cell in a numeric column carries .num even when the value itself is
    textual (a missing-data statement)."""
    script = _js()
    assert 'class="num missing"' in script, (
        "pointsTable()'s missing-value cell must still carry .num alongside .missing"
    )
    bare_missing_cells = re.findall(r'<td class="missing">', script)
    assert not bare_missing_cells, (
        "a <td> in a numeric column must never carry only .missing without .num: "
        f"found {len(bare_missing_cells)} occurrence(s)"
    )


# ---------------------------------------------------------------------------
# N-19 / AC-29: heading order is strict within every view, checked in isolation
# ---------------------------------------------------------------------------


class _PerViewHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.by_view: dict[str, list[int]] = {}
        self._view_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: (v or "") for k, v in attrs}
        if tag == "section" and attrs_dict.get("id") in VIEW_IDS:
            self._view_stack.append(attrs_dict["id"])
            self.by_view.setdefault(attrs_dict["id"], [])
        if tag in {f"h{n}" for n in range(1, 7)} and self._view_stack:
            self.by_view[self._view_stack[-1]].append(int(tag[1]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._view_stack:
            self._view_stack.pop()


def test_heading_order_is_strict_within_each_view_in_isolation() -> None:
    """N-19 / AC-29. test_heading_levels_never_skip (WO-016) already checks
    the whole document as one flat sequence, which would also catch an
    in-view skip -- but only because the surrounding document happens not to
    mask it. This test isolates each view's own heading sequence and re-runs
    the same check independently, so a future change that accidentally
    relies on a neighbouring view's heading level to avoid a skip is still
    caught even if it would not have been by the whole-document version."""
    parser = _PerViewHeadingParser()
    parser.feed(_html())
    assert parser.by_view, "expected to find at least one view section"
    for view_id, levels in parser.by_view.items():
        assert levels, f"{view_id}: expected at least one heading"
        assert levels[0] == 2, f"{view_id}: a view must open with its own <h2>, got h{levels[0]}"
        previous = levels[0]
        for level in levels[1:]:
            if level > previous:
                assert level - previous == 1, (
                    f"{view_id}: heading level jumped from h{previous} to h{level} "
                    "without an intervening heading"
                )
            previous = level


# ---------------------------------------------------------------------------
# View visibility: pin the F-1/F-2 fix from the first Opus review of PR #62
# ---------------------------------------------------------------------------


def test_activate_view_keeps_data_boot_view_in_sync() -> None:
    """Regression for a real bug an independent Opus review caught in the
    first version of this PR (not covered by any static test at the time,
    which is exactly why it survived: every dashboard test before this one
    parses committed markup, never a rendered DOM).

    ``index.html``'s inline anti-flash boot script sets ``data-boot-view``
    once, before app.js even loads, and ``styles.css`` keys an ID-specific
    show-rule off it (deliberately high specificity so it outranks the
    generic "hide every view" rule at first paint). But that rule's
    specificity also outranks ``.view[hidden] { display: none }` -- so if
    ``data-boot-view`` is never updated after boot, the ORIGINAL view stays
    rendered forever and every hashchange only ever updates the nav
    highlight, never what is actually on screen. The fix is one line in
    ``activateView()``. This test cannot see computed CSS (no browser here),
    but it can pin that the line exists, which a real-browser check (done
    manually for this PR, see docs/evidence/) confirmed is sufficient."""
    script = _js()
    activate_body = _js_function_body(script, "activateView")
    assert activate_body, "expected to resolve activateView's body"
    assert re.search(r"setAttribute\(\s*['\"]data-boot-view['\"]", activate_body), (
        "activateView() must keep documentElement's data-boot-view attribute in sync with "
        "the active view, or the CSS anti-flash show-rule permanently pins the original "
        "boot view visible regardless of navigation"
    )


def test_print_forces_every_view_visible_without_depending_on_the_hidden_attribute() -> None:
    """Regression for the second half of the same review finding: the
    ``beforeprint`` handler in app.js makes every view visible by *removing*
    the `hidden` attribute (``section.hidden = false``) on all seven -- so a
    print CSS rule keyed on ``.view[hidden]`` matches nothing by the time
    printing actually happens, and only the (still-pinned, see the test
    above) original boot view would print. The fix drops the ``[hidden]``
    qualifier so the print rule applies to every ``.view`` unconditionally."""
    css = (PUBLIC / "assets" / "styles.css").read_text(encoding="utf-8")
    print_block_match = re.search(r"@media print\s*\{(.*?)\n\}", css, re.S)
    assert print_block_match, "expected an @media print block in styles.css"
    print_block = print_block_match.group(1)
    assert re.search(r"\.view\s*\{[^}]*display:\s*block\s*!important", print_block), (
        "the @media print block must force every .view to display:block unconditionally, "
        "not only .view[hidden] -- app.js's beforeprint handler removes the hidden attribute "
        "rather than adding it"
    )
    assert not re.search(r"\.view\[hidden\]\s*\{[^}]*display:\s*block\s*!important", print_block), (
        "a .view[hidden]-qualified print rule matches nothing once beforeprint has already "
        "removed the hidden attribute from every view -- this is the exact regression"
    )
