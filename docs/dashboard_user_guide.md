# Dashboard user guide

**Work Order:** WO-010 Gate K, corrected by WO-010-R1, restructured into seven
routed views by WO-030, extended to eight by WO-039 · **Status:** implemented
**Source:** `dashboard/public/` · **Build:** `python scripts/build_dashboard.py`

## 1. The page has two kinds of panel, and they are not the same thing

Since WO-010-R1 every section is split in two, and the split is the most
important thing to understand about this page.

**Current Logistics Intelligence** is what the platform asserts about
conditions now. It rests exclusively on evidence that was either retrieved
from a publisher or transcribed by a named human. No source is enabled today,
so there is no such evidence, and every current reading is
`insufficient_evidence`.

**Technical demonstration** and **Historical validation** panels are driven by
fixtures this repository generated or authored. They exist to exercise the
analysis engine and to replay documented past cases. They describe no
real-world condition, and nothing in them feeds a current reading.

Each demonstration panel carries its own marker — a bordered panel, a heading
pill, or a label along the top of the card — not only the page-level banner.
A reader who deep-links to one section, or prints one panel, still sees what
they are looking at. Historical cases additionally show the assessment cutoff
they were assessed at.

An empty current panel is a **coverage gap, not an all-clear**. The page says
so in those words wherever a current list is empty.

Every current panel is **derived by filtering**, not written as an empty list.
The same code that produces today's empty result would publish a reading the
moment a qualifying record existed — that is what
`tests/test_current_positive_path.py` demonstrates, by pushing real qualifying
records through the production code and watching them arrive. Nothing about the
empty state is special-cased.

## 2. Read the banner

The red banner at the top of the page states the platform's live coverage. It
currently reads **insufficient**: no source is enabled, none has completed a
controlled live validation, and the platform therefore holds no live-retrieved
or human-reviewed evidence at all.

If a payload fails to load, the banner switches to the same pessimistic reading
rather than leaving a section silently blank. The same reading also drives a
persistent chip in the navbar (§3), so coverage stays visible no matter which
view is open. Once a payload fails, the chip stays at its most pessimistic
reading for the rest of the page's life — a later view that happens to load
cleanly does not relax it back.

## 3. Navigating the eight views

WO-030 split the page from one long scroll into seven separate views; WO-039
added an eighth. Each view has its own `#/<route>` address:

| Route | View |
|---|---|
| `#/overview` | Thailand Logistics Situation |
| `#/ocean` | Ocean Logistics |
| `#/air` | Air Cargo |
| `#/trade` | Trade and Flow |
| `#/cost` | Cost and Freight Pressure |
| `#/events` | Events and External Drivers |
| `#/outlook` | AI Outlook and Preparedness |
| `#/sources` | Sources and Methodology |

Only one view is visible at a time; the other seven sit behind the HTML
`hidden` attribute rather than being scrolled past. The nav bar at the top is
sticky and always shows the current view (an underline on the active link)
and the coverage chip described above. Switching views moves keyboard focus
to the new view's heading, updates the page title, and announces the change
to screen readers through a live region — nothing about the change is silent.

**Old links keep working.** The pre-WO-030 anchors (`#situation`, `#ocean`,
`#trade`, `#cost`, `#events`, `#outlook`, `#sources`) still resolve to the
right view; the address bar quietly rewrites itself to the `#/<route>` form
without adding an extra Back-button step.

**Deep links into a view work too**, in two forms: `#/<route>/<element-id>`
or a bare `#<element-id>` matching any id on the page. Either form scrolls to
and focuses that element, expanding its containing demonstration region or
expandable table row first if it was collapsed. A link like this can be
pasted, bookmarked, or shared, and reopens exactly the same place.

**An address that matches nothing** — a typo, a stale bookmark to a removed
id — never substitutes silently. The page falls back to the Overview view and
shows a visible notice naming the address it couldn't match.

**Browser Ctrl+F only searches the visible view.** Because the other seven
views are hidden rather than merely scrolled off-screen, the browser's
built-in find-in-page will not match text in a view you haven't opened. If
you're looking for something and aren't sure which view it's in, check
Sources & Methodology's payload list (§4) for the underlying JSON, or open
each view in turn.

## 4. The eight views

Within every view below, current material always comes first, in its own
region. Demonstration and historical material — where the view has any —
follows in a single collapsed **"Demonstration & historical material"**
disclosure, closed by default, labelled with what it contains and how many
items before you open it. The two kinds of content are never mixed inside
one card, table or list; a current row that has a corresponding
demonstration reading carries only a neutral note pointing at it, never the
demonstration value itself.

### 1 — Thailand Logistics Situation
The overview: data cutoff, overall direction, evidence coverage, how many lanes need
attention, how many operational events are verified, how many external drivers are admitted
versus merely contextual, how many discovery leads are open, a cost-pressure table with
per-series freshness, key changes, and the major data gaps.

**Overall direction** is a transparent roll-up of the lane directions, not a composite
score. **Attention level** is derived from domain directions and open events.

### 2 — Ocean Logistics
Thailand port and maritime indicators, the eleven-lane table, chokepoint exposure, official
operational notices, and capacity/service evidence.

Every port series is labelled **volume only**. Rising throughput means more cargo moved; it
is not congestion. No congestion, berth-delay, yard-congestion or truck-delay statement is
made anywhere on this page.

Lanes and, on Sources & Methodology, sources are **expandable-row tables**: a small button
in the first column expands that one row in place to show the full record, rather than
navigating to a separate card or page. A lane's blocker or limitation is reachable in a
single click from its own view, and in a click plus a view switch from anywhere else. Each
lane states its **resolution** — a regional lane is never displayed as a port-pair lane —
and its expanded row shows all nine domain assessments with the threshold rule behind each,
the selection evidence with its own evidence class, and the lane's limitations. Where a lane
also has a technical-demonstration assessment, the current row carries a plain-text
cross-reference into the demonstration region below — never the demonstration attention
level, direction or any other value.

### 3 — Air Cargo
The provisional Air lane set (WO-039), the registered air node (`NODE-THBKKAIR`) and airspace
chokepoint (`CHK-SASIA-AIRSPACE`), and one historical validation case. States
`live_coverage: insufficient` and `module_status: planned` explicitly: no Air source is
registered or enabled, no Air observation or indicator series exists, and **no lane carries a
current assessment** — every lane's current row shows `insufficient_evidence` rather than a
fabricated attention level or direction. A lane's expanded row shows its selection evidence,
evidence class, data period used (always none) and its known limitations, mirroring how the
Ocean lane table's expandable rows work. Below the current material, a labelled historical
region shows `HVC-009` (the 2019 Pakistan airspace closure), replayed through the same
analysis code as every Ocean case.

### 4 — Trade and Flow
Thailand import and export value by lane group, each with a chart, a full period table,
month-over-month and year-over-year change, rolling average, revision status and freshness.
Trade value is an all-mode total; it is not ocean freight volume. This view covers Ocean
lanes only — Air carries no trade-value series of any kind.

### 5 — Cost and Freight Pressure
Fuel, crude, freight benchmark and FX. Every series states its `benchmark_class`, its
quotation claim, its route scope and its Thailand applicability. The freight series is a
**route proxy for a third route**, published as a directional indicator only. No Thailand
freight average is published anywhere, for Ocean or for Air. No surcharge series is
published, and the page says why.

### 6 — Events and External Drivers
Four separate lists: direct operational events, external drivers with a stated transmission
mechanism, contextual external drivers with none, and discovery leads.

Each event shows its transmission chain link by link, with missing links marked `×` and
"not established". Expandable panels carry lane relevance, the nine-area impact assessment,
the evidence with claim type and role, conflicting evidence, and limitations.

Where Thailand relevance is `none established`, the card says the platform found no basis to
assess an effect — which is different from finding there is none.

### 7 — AI Outlook and Preparedness
Shows **only human-approved AI assessments**. It is currently empty, and says so in words
rather than showing a blank panel: the workflow is implemented and tested, but producing an
assessment requires a human to run a package through ChatGPT out-of-band.

Below it, under its own heading, are the **deterministic lane outlooks** — base,
deterioration and improvement cases generated from the documented threshold rules, open
events and data gaps. These are explicitly labelled as not being an AI assessment. Each
case carries its horizon, confidence, data gaps and a trigger table stating what would have
to be observed and where. This roll-up covers Ocean lanes only (`subject: thailand_ocean`);
Air lanes carry no scenario outlook, because no Air observation or event feed exists to
derive one from.

Conditional preparedness options appear per lane. They are organization-neutral and always
carry a trigger and an exit condition.

### 8 — Sources and Methodology
Every source: owner, class, landing page, endpoint, access method, machine-readable status,
licence status, terms, access cost, reuse and redistribution status, publication cadence,
observed freshness, data period, logistics role, prototype eligibility, live-validation
status, enabled flag, required-for-publication flag, health status, **enablement blockers**
and known limitations.

Also capability coverage, the historical-validation summary, and the methodology document
list.

**Machine-readable payloads.** This view also lists every JSON file the build publishes
under `data/`, including `indicators.json` and `source_status.json`, which the page itself
does not fetch. These are **generated static artifacts, not a supported public API** —
schema stability is not guaranteed unless a specific data contract says otherwise. They are
published for inspection and reproducibility, not as an integration point.

## 5. How to read a value that is not there

| Display | Meaning |
|---|---|
| *not available* | No usable observation. **Not zero** |
| *not computable* | The comparison needs a period that is missing |
| *missing — not zero* | In a period table: the source published nothing for that period |
| *no baseline defined* | Deviation is not publishable for this series |
| `insufficient_evidence` | The rule's inputs were missing or too few |
| `none_established` | No basis to assess was found. **Not** a finding of no effect |
| An empty "Current" list | No qualified evidence exists. **Not** a finding that nothing is happening |
| A break in a chart line | A missing period. Gaps are drawn as gaps, never interpolated or zeroed |

## 6. Freshness

Every reading carries its own freshness pill with its age in days. Two vocabularies are
used, and they do not overlap.

| Vocabulary | Statuses | Applies to |
|---|---|---|
| Real-world | `fresh`, `stale`, `very_stale`, `no_data`, `disabled`, `error` | Records actually retrieved from a publisher, or transcribed by a named human |
| Fixture | `fixture_not_live`, `historical_validation`, `not_applicable` | Everything in the demonstration panels |

A generated number has no publisher who could have fallen behind, so it is never called
"fresh" and never called "stale". Stale real data is labelled stale. Nothing on the page
implies that an old reading — or a generated one — is current.

## 7. Accessibility and device support

- Semantic HTML with a skip link, labelled sections, table captions and scoped headers.
- Status is never conveyed by colour alone; every pill carries its text.
- Every chart has an `aria-label` describing what it shows including how many periods are
  missing, and is paired with a table containing the identical numbers, plus a text line
  giving the min, max, latest value and period range so the chart is never the only way to
  read a series's shape.
- Every horizontally scrollable table container is independently keyboard-focusable
  (`tabindex="0"`, `role="region"`, labelled by the table's own caption), so its last column
  is reachable without a mouse.
- Every table — including the source-detail table, which previously had none — has a
  `<caption>` and a `<thead>` with scoped header cells. The header row is sticky, offset
  below the sticky nav bar so it never overlaps the row beneath it.
- With scripting disabled, all eight views render in full, in document order, as one long
  page; a banner states that JavaScript is disabled and that coverage should be treated as
  insufficient, before any other content.
- Wide tables scroll inside their own container; the page body never scrolls horizontally.
  Verified at 1280×720, 1440×900 and 1920×1080, and at a 640px-wide proxy for 200% zoom on a
  1280px viewport (see the evidence note below for how the proxy was constructed).
- Printing expands every collapsed demonstration/historical region and every expandable
  table row before rendering, and restores their previous state afterward — see the
  `beforeprint`/`afterprint` note below for how this is verified.

**Test-enforced (WO-016, extended by WO-030):** the properties above that a static test can
check without rendering the page are enforced by `tests/test_dashboard_accessibility.py` and
`tests/test_dashboard_routing_and_regions.py` on every PR — a single `<h1>`, no heading-level
skip **in the static markup, checked both across the whole document and independently within
each view** (see the caveat below), `lang` present, the skip link's target exists, every
`nav`/`section`/`role="region"` landmark has an accessible name, every `.table-wrap` carries
`tabindex="0"`/`role="region"`/`aria-labelledby`, every table carries a caption and a scoped
`<thead>`, every `href` this page emits passes a URL-scheme allowlist before it reaches the
DOM, and current material never follows non-current material in a view's DOM order.

Colour contrast is checked in two tiers, both against the WCAG AA 4.5:1 normal-text ratio:
every rule in `assets/styles.css` that sets both a text colour and its own background in the
same selector (every pill/badge, the skip link, the site header, body text) is checked
automatically, with both colours read from the actual declaration — a changed pill colour
cannot silently stop being tested. A second, smaller set of selectors (links, `.missing`,
table captions, muted labels) sets only a text colour and relies on an ancestor element for
its background; for these, the foreground colour is still read from the actual CSS rule, but
which background it renders against was verified by hand against the stylesheet's selector
structure, not derived automatically — a rework of the page layout that changes an ancestor's
background could invalidate that hand-verified mapping without the test itself changing.
(WO-030 replaced the table zebra-stripe colour with one that is actually visible against the
page background — the previous value was close enough to white to be functionally invisible
— and re-verified the hand-checked `.missing` pairing against both the new stripe and hover
colours, recording the stricter of the two.)

**Printing.** A `beforeprint` handler expands every collapsed demonstration/historical region
and every expandable table row, makes all eight views visible, and fills in a print-only
header (title, coverage state, data cutoff, the page's URL) before the browser renders the
page; an `afterprint` handler restores whatever was open or hidden beforehand. This was
verified with a real print-to-PDF in Chromium — not simulated, not inferred from the
stylesheet — confirming the events fire and the expansion actually happens; the PDF is
committed under `docs/evidence/`. This paragraph previously credited a CSS-only
`@media print` rule (`details { display: block }`) with the same effect; that rule is inert
for a *closed* `<details>` element in current browser engines, so the earlier wording
described behaviour that had never actually been checked in a browser. It has been replaced
with the mechanism that was shown to work. The stylesheet rule still exists as a documented
fallback, not as the primary mechanism.

**WO-018:** the heading-level checks above parse the *committed* `index.html` only, so they could
not see that `assets/app.js` injected `<h4>` content directly under the `<h2>` in the Trade, Cost
and Outlook sections at runtime (Issue #32) — the Outlook instance was latent, invisible only
because its backing fixture data happened to be empty. Fixed by adding five static `<h3>`
headings and a data-independent regression test,
`test_dynamically_injected_headings_never_skip_a_level`, that statically resolves which heading
level(s) each `app.js` container injects (including through a named helper like `seriesBlock`,
by reading that helper's own source rather than hardcoding its level) and checks it against the
nearest preceding heading actually present in `index.html`.

**Known gap:** that new test resolves only the `el('literal-id').innerHTML = ...` assignment
pattern. The six `events-*` containers in `renderEvents` are populated through a different
pattern — a loop over an array literal — and are not covered by it; they were manually verified
correct (each already sits under its own static `<h3>`) at the time this was written, and a
regression there would not be caught by this test suite.

This is a set of narrow, specific checks, not a substitute for a full accessibility audit or
manual screen-reader testing.

## 8. Payload budget (WO-016)

The Dashboard loads no external font, stylesheet, or script (§7), so its own payload is the
entire download cost. `tests/test_dashboard_accessibility.py` enforces two budgets, using
decimal megabytes (1 MB = 1,000,000 bytes) throughout:

- **Total published site:** ≤ 3 MB. Current size is ~1.1 MB (mostly `data/ocean.json` at
  ~460 KB, the largest single payload — the 11-lane Ocean model with its full observation
  history). The 3 MB ceiling is a little under triple the current size: enough headroom for the
  Ocean dataset to keep growing and for a future mode's lane data to land without immediately
  tripping the test, while still catching a genuine regression (e.g. an accidentally
  unbounded export, or a raw response leaking into a payload it doesn't belong in).
- **Any single JSON payload:** ≤ 1 MB. Set above the current largest file (`ocean.json`,
  ~460 KB) with a little over double the room, which is a more meaningful per-file signal than
  the total budget alone — a single payload doubling in size while the rest of the site stays
  flat is a different kind of regression than the whole site growing together.

Neither number is a target to grow into; both exist to catch an unbounded payload before it
ships, not to describe how large the Dashboard is expected to become.

## 9. What the Dashboard will not do

- It will not tell any specific organization what to do. It holds no shipment, booking,
  quotation or capacity data and cannot know anyone's exposure.
- It will not publish a number where it has none.
- It will not claim real-time conditions it does not measure.
- It will not publish an AI conclusion no human approved.
- It will not present a synthetic or historical fixture as a current condition. Fixtures
  appear only in their own labelled panels, and never contribute to a current direction,
  attention level, active event, chokepoint notice or freshness reading.
- It will not publish a value a source's terms do not permit it to republish. Each source
  records what may be published from it, and enablement alone is not that permission.
- It will not show an AI assessment that was produced from a demonstration package. The
  ChatGPT package built for the current view excludes demonstration and historical data
  entirely, every approval is bound to its input package by hash, and publication re-checks
  that binding independently. A demonstration assessment is withheld and listed, never
  shown as current.
