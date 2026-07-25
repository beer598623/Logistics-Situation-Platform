# Dashboard user guide

**Work Order:** WO-010 Gate K, corrected by WO-010-R1 · **Status:** implemented
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

## 2. Read the banner

The red banner at the top of the page states the platform's live coverage. It
currently reads **insufficient**: no source is enabled, none has completed a
controlled live validation, and the platform therefore holds no live-retrieved
or human-reviewed evidence at all.

If a payload fails to load, the banner switches to the same pessimistic reading
rather than leaving a section silently blank.

## 3. The seven sections

### 1 — Thailand Logistics Situation
The overview: data cutoff, overall direction, evidence coverage, how many lanes need
attention, how many operational events are verified, how many external drivers are admitted
versus merely contextual, how many discovery leads are open, a cost-pressure table with
per-series freshness, key changes, and the major data gaps.

**Overall direction** is a transparent roll-up of the lane directions, not a composite
score. **Attention level** is derived from domain directions and open events.

### 2 — Ocean Logistics
Thailand port and maritime indicators, the eleven lane cards, chokepoint exposure, official
operational notices, and capacity/service evidence.

Every port series is labelled **volume only**. Rising throughput means more cargo moved; it
is not congestion. No congestion, berth-delay, yard-congestion or truck-delay statement is
made anywhere on this page.

Each lane card shows its **resolution** — a regional lane is never displayed as a port-pair
lane — and expands to show all nine domain assessments with the threshold rule behind each,
the selection evidence with its own evidence class, and the lane's limitations.

### 3 — Trade and Flow
Thailand import and export value by lane group, each with a chart, a full period table,
month-over-month and year-over-year change, rolling average, revision status and freshness.
Trade value is an all-mode total; it is not ocean freight volume.

### 4 — Cost and Freight Pressure
Fuel, crude, freight benchmark and FX. Every series states its `benchmark_class`, its
quotation claim, its route scope and its Thailand applicability. The freight series is a
**route proxy for a third route**, published as a directional indicator only. No Thailand
freight average is published anywhere. No surcharge series is published, and the page says
why.

### 5 — Events and External Drivers
Four separate lists: direct operational events, external drivers with a stated transmission
mechanism, contextual external drivers with none, and discovery leads.

Each event shows its transmission chain link by link, with missing links marked `×` and
"not established". Expandable panels carry lane relevance, the nine-area impact assessment,
the evidence with claim type and role, conflicting evidence, and limitations.

Where Thailand relevance is `none established`, the card says the platform found no basis to
assess an effect — which is different from finding there is none.

### 6 — AI Outlook and Preparedness
Shows **only human-approved AI assessments**. It is currently empty, and says so in words
rather than showing a blank panel: the workflow is implemented and tested, but producing an
assessment requires a human to run a package through ChatGPT out-of-band.

Below it, under its own heading, are the **deterministic lane outlooks** — base,
deterioration and improvement cases generated from the documented threshold rules, open
events and data gaps. These are explicitly labelled as not being an AI assessment. Each
case carries its horizon, confidence, data gaps and a trigger table stating what would have
to be observed and where.

Conditional preparedness options appear per lane. They are organization-neutral and always
carry a trigger and an exit condition.

### 7 — Sources and Methodology
Every source: owner, class, landing page, endpoint, access method, machine-readable status,
licence status, terms, access cost, reuse and redistribution status, publication cadence,
observed freshness, data period, logistics role, prototype eligibility, live-validation
status, enabled flag, required-for-publication flag, health status, **enablement blockers**
and known limitations.

Also capability coverage, the historical-validation summary, and the methodology document
list.

## 4. How to read a value that is not there

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

## 5. Freshness

Every reading carries its own freshness pill with its age in days. Two vocabularies are
used, and they do not overlap.

| Vocabulary | Statuses | Applies to |
|---|---|---|
| Real-world | `fresh`, `stale`, `very_stale`, `no_data`, `disabled`, `error` | Records actually retrieved from a publisher, or transcribed by a named human |
| Fixture | `fixture_not_live`, `historical_validation`, `not_applicable` | Everything in the demonstration panels |

A generated number has no publisher who could have fallen behind, so it is never called
"fresh" and never called "stale". Stale real data is labelled stale. Nothing on the page
implies that an old reading — or a generated one — is current.

## 6. Accessibility and device support

- Semantic HTML with a skip link, labelled sections, table captions and scoped headers.
- Status is never conveyed by colour alone; every pill carries its text.
- Every chart has an `aria-label` describing what it shows including how many periods are
  missing, and is paired with a table containing the identical numbers.
- Wide tables scroll inside their own container; the page body never scrolls horizontally.
  Verified at 390px width.
- A print stylesheet expands collapsed panels.

## 7. What the Dashboard will not do

- It will not tell any specific organization what to do. It holds no shipment, booking,
  quotation or capacity data and cannot know anyone's exposure.
- It will not publish a number where it has none.
- It will not claim real-time conditions it does not measure.
- It will not publish an AI conclusion no human approved.
- It will not present a synthetic or historical fixture as a current condition. Fixtures
  appear only in their own labelled panels, and never contribute to a current direction,
  attention level, active event, chokepoint notice or freshness reading.
