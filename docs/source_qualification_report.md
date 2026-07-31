# Source qualification report

<!-- registry-source-count: 18 -->

**Work Order:** WO-010 Gate C, extended by WO-011 · **Registry version:** 0.3 · **Reviewed:** 2026-07-24
**Policy:** `free_public_sources_only` · **Paid-source dependency:** 0

## 1. Headline finding

**No source was enabled. No source completed a controlled live validation.**

Outbound network access in the WO-010 execution environment was blocked by policy: two
independent public publisher landing pages both returned HTTP 403 through the environment's
proxy. Independently of that, this repository's own governance already requires live source
contact to run through the human-triggered `manual-live-source-test` workflow with artifact
retention, rather than from an automated executor.

Consequently every candidate below records:

- what was reviewed and what was not,
- its exact unresolved blockers, and
- `live_validation_status: not_performed`.

Technical accessibility is never treated as licensing permission. Where a publisher's terms
were not actually read, `reuse_status` and `redistribution_status` stay `unknown` — not
"probably fine".

## 2. Coverage against the Gate C target

| Required capability | Target | Delivered | Status |
|---|---|---|---|
| Thailand trade or flow | ≥ 1 qualified | 1 candidate (`TH_CUSTOMS`), not enabled | **Insufficient — live coverage absent** |
| Thailand port, maritime or transport | ≥ 1 qualified | 3 candidates (`IMF_PORTWATCH`, `UNCTAD_MARITIME`, `PAT_STATISTICS`), not enabled | **Insufficient** |
| Cost source | ≥ 1 qualified | 4 candidates (`EPPO_FUEL`, `WB_COMMODITY`, `BOT_FX`, `FBX_PUBLIC`), not enabled | **Insufficient** |
| Global baseline | ≥ 1 qualified | 1 candidate (`GSCPI`), not enabled | **Insufficient** |
| Official operational-notice channels | ≥ 2, or a bounded reviewed intake | 4 channels (`PAT_NOTICE`, `ACP_ADVISORY`, `SCA_CIRCULAR`, `MPA_SG_NOTICE`) **plus** the bounded reviewed intake (`MANUAL_NOTICE_INTAKE`) | **Registered; none enabled** |
| Free news discovery | ≥ 1 | 1 candidate (`NEWS_DISCOVERY`), not enabled | **Insufficient** |

The numeric candidate count is met in every category. The **qualification** target is not,
because qualification requires a controlled live validation that could not be performed. No
unqualified data was substituted to close the gap; the resulting coverage limitation is
stated on the Dashboard, in the source-health snapshot and in every lane assessment.

**WO-026 addition, outside the table above:** `MPA_SG_STATISTICS` (Singapore vessel/container
statistics via `data.gov.sg`) is registered with `licence_status: reviewed` — the platform's
first source whose reuse terms were actually read by a human against the primary licence text
(Singapore Open Data Licence v1.0), rather than left `unknown`. It is deliberately not counted
against the "Thailand port, maritime or transport" row above: it measures Singapore hub
activity, not Thailand, and is relevant only through the transshipment mechanism (see
`docs/mpa_sg_statistics_qualification.md`). Still `enabled: false`; no controlled live
validation has been performed.

## 3. Candidate register

Eighteen contracts. Full machine-readable detail is in `config/sources.yaml`.

### Bundle 1 candidates (10 new + 3 pre-existing)

| ID | Publisher | Logistics role | Access | Reuse | Redistribution | Fixture test | Live validation |
|---|---|---|---|---|---|---|---|
| `TH_CUSTOMS` | Thai Customs Department | Thailand trade flow | free | unknown | unknown | yes | not performed |
| `EPPO_FUEL` | Energy Policy and Planning Office | Domestic fuel cost | free | unknown | unknown | yes | not performed |
| `GSCPI` | Federal Reserve Bank of New York | Global baseline | free | unknown | unknown | yes | not performed |
| `BOT_FX` | Bank of Thailand | FX context | free with registration (**API key**) | unknown | unknown | yes | not performed |
| `WB_COMMODITY` | World Bank | Energy/commodity baseline | free | unknown | unknown | **no** | not performed |
| `IMF_PORTWATCH` | International Monetary Fund | Thailand port/maritime activity | free | unknown | unknown | yes | not performed |
| `UNCTAD_MARITIME` | UNCTAD | Maritime connectivity | free | unknown | unknown | yes | not performed |
| `PAT_NOTICE` | Port Authority of Thailand | Official notice | free | unknown | unknown | yes | not performed |
| `ACP_ADVISORY` | Panama Canal Authority | Official notice | free | unknown | unknown | yes | not performed |
| `SCA_CIRCULAR` | Suez Canal Authority | Official notice | free | unknown | unknown | yes | not performed |
| `MPA_SG_NOTICE` | Maritime and Port Authority of Singapore | Official notice | free | unknown | unknown | yes | not performed |
| `MANUAL_NOTICE_INTAKE` | Platform maintainers | Official notice intake | free | permitted with attribution | link only | yes | **not required** |
| `NEWS_DISCOVERY` | The GDELT Project | News discovery | free | unknown | link only | yes | not performed |

### WO-010-R1 additions (2)

| ID | Publisher | Logistics role | Access | Reuse | Redistribution | Fixture test | Live validation |
|---|---|---|---|---|---|---|---|
| `PAT_STATISTICS` | Port Authority of Thailand | Thailand port/maritime activity | free | unknown | unknown | yes | not performed |
| `FBX_PUBLIC` | Freightos | Freight market benchmark/proxy | free (partial paywall) | unknown | unknown | yes | not performed |

Both correct a provenance defect rather than add capability. WO-010 had published a synthetic
Thailand port-throughput series against `IMF_PORTWATCH` (a vessel-tracking estimate) and a
synthetic container freight benchmark against `EPPO_FUEL` (a domestic retail fuel publisher) —
neither mapping was true. WO-010-R1 registered these two contracts so each series has a
correctly scoped candidate to stand in for. Both are disabled.

### WO-026 addition (1)

| ID | Publisher | Logistics role | Access | Reuse | Redistribution | Fixture test | Live validation |
|---|---|---|---|---|---|---|---|
| `MPA_SG_STATISTICS` | Maritime and Port Authority of Singapore (data.gov.sg) | Regional hub / external driver context (Singapore, not Thailand) | free | **open licence (reviewed)** | **permitted** | yes | not performed |

The Ocean Minimum Live Core research pass (see Issue #54) found that this is the only
candidate in the whole registry whose reuse terms a human independently verified against the
primary licence text as unambiguously permitting redistribution — the Singapore Open Data
Licence v1.0. Every other entry in this table remains `unknown` because this environment's
`WebFetch` tool is blocked for external hosts and no one has yet read the underlying terms.
Still disabled: the endpoint and exact field names are unconfirmed, no controlled live
validation has run, and no human has yet approved a first live request. See
`docs/mpa_sg_statistics_qualification.md` for the full record.

### Outside the Bundle 1 source core

| ID | Disposition |
|---|---|
| `TMD_CAP` | **Disabled and unmodified.** Governed by Issue #15 and its existing contract. WO-010 added no qualification or enablement record to it. |
| `GDACS` | **Disabled and unmodified.** Same. |

`tests/test_derived_outputs.py::test_tmd_and_gdacs_remain_disabled_and_unqualified_by_this_bundle`
asserts both remain untouched.

## 4. Per-candidate notes

### `TH_CUSTOMS` — Thailand trade flow
The statistics portal is an interactive report builder; whether it exposes a stable CSV
export without session state is unresolved, and `endpoint` remains null. Published customs
figures are **all-mode totals** — attributing them to ocean freight without an explicit mode
dimension would be an invented precision, so every trade observation is recorded with
`transport_mode: not_applicable` and carries that limitation.

### `EPPO_FUEL` — domestic fuel cost
The page is client-rendered, so a machine-readable extraction path is unconfirmed. A retail
pump price is **domestic cost context, not a bunker price**, and is labelled as such.

### `GSCPI` — global baseline
Monthly, and the only series in the registry with an explicit published baseline (zero, the
publisher's own stated series average in standard-deviation units), which is why deviation
is publishable for it and for nothing else. A global index cannot establish a
Thailand-specific conclusion on its own.

### `BOT_FX` — FX context
**Requires an API key.** A key is a credential, and no credential-handling mechanism exists
in this repository. Enabling this source needs a separate secrets decision that WO-010 does
not make. A reference rate is cost context; it does not establish a change in any cost
actually paid.

### `WB_COMMODITY` — energy and commodity baseline
The published workbook is XLSX. **No XLSX parser exists in this repository and WO-010 adds
none**, so this is the one candidate with no fixture test. It is registered so the gap is
visible rather than silently absent.

### `IMF_PORTWATCH` — port activity
Model-derived estimates from vessel tracking, **not port-authority reported throughput**.
Must be labelled as estimates. Port-call counts are a volume measure and can never on their
own establish congestion, waiting time or berth delay.

### `UNCTAD_MARITIME` — connectivity
Quarterly-to-annual structural measures of liner network coverage. Not an operational
condition; cannot detect an event.

### Official notice channels — `PAT_NOTICE`, `ACP_ADVISORY`, `SCA_CIRCULAR`, `MPA_SG_NOTICE`
No machine-readable feed has been confirmed for any of them, and publication cadence is
unknown for all four — so **no automated collection schedule is justified and none is
configured** (`schedule_justified: false`). Canal advisories and circulars are commonly PDF,
and no PDF parser exists.

An official notice is evidence of the notice. It is not automatically evidence of an
operational effect on any particular lane, service or organization.

### `MANUAL_NOTICE_INTAKE` — bounded reviewed intake
The fallback for publishers with no machine-readable feed. A human records the publisher,
the notice reference, the publication date and a claim capped at 600 characters, from the
publisher's own page. **It makes no network request of any kind.** Full notice text is never
copied into this repository. Coverage is whatever a human recorded — absence of a notice
here is never evidence that none was published. No notice has yet been recorded, so this
path currently contributes zero coverage.

### `NEWS_DISCOVERY` — discovery only
Every record it produces carries `evidence_role: discovery_only` and is structurally barred
from being the sole evidence for a material impact conclusion — enforced in
`analysis/events.py` and asserted by tests. Only headline metadata and the publisher's own
URL are retained; article bodies are never fetched, stored or republished. Coverage skews to
English-language and heavily syndicated outlets, so absence of a lead is not evidence that
nothing happened.

### `PAT_STATISTICS` — Thailand port throughput (WO-010-R1)
Reported throughput published by the port authority is a different measure from
`IMF_PORTWATCH`'s model-derived vessel-tracking estimate; the two must never be presented as
the same series, which is the correction this contract records. Throughput is a volume
measure and can never on its own establish congestion, waiting time or berth delay. No
machine-readable statistics endpoint has been confirmed.

### `FBX_PUBLIC` — container freight benchmark (WO-010-R1)
A market benchmark for named east-west container routes. It is **not** a Thailand shipment
quotation, not a Thailand average, and not a rate paid by any shipper — no route in the index
is a Thailand-origin route, so any Thailand reading derived from it is directional context
only. Registered so the synthetic freight benchmark used by the Ocean MVP has a correctly
scoped candidate to stand in for, in place of `EPPO_FUEL` (a domestic retail fuel publisher,
which was wrong in both route scope and cost family). The index is a commercial product with
a free public display tier (`paywall_status: partial`); the free tier's coverage, history
depth and machine-readability are all unverified.

## 5. Enablement rule

A source may be enabled only when **all** of the following hold, checked by
`scripts/validate.py::source_contract_checks`:

- `machine_readable_status: verified`
- `licence_status: reviewed`
- a controlled endpoint is recorded
- `enablement.fixture_test_exists` is true
- `enablement.live_validation_status` is `completed` or `not_required`
- `enablement.parser_fails_closed`, `response_bounded`, `schedule_justified` and
  `public_repository_safe` are all true
- `enablement.blockers` is **empty**
- `qualification.access_cost` is not `paid`

No source currently satisfies this set. The validator would fail the build if one were
marked enabled while a blocker remained.

## 6. Excluded by policy

Paid freight-rate feeds, paid vessel tracking, paid news APIs and paid market intelligence
are excluded by the free-only principle. None is registered, none is referenced, and
`scripts/validate.py` rejects any source recorded with `access_cost: paid`.
