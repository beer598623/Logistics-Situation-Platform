# Thailand-Centric Multimodal Logistics — MVP Roadmap

**Work Order:** WO-009A
**Authorized baseline:** `7039b0b4513f3469a6ce649cb1e845a36e359a2a`
**Execution type:** Architecture, governance and documentation reset only

This roadmap records the approved implementation phases for
`docs/thailand_multimodal_logistics_intelligence_scope.md`. **WO-009A authorizes Phase 0
only.** No Phase 1 (or later) implementation is authorized until this scope reset receives
independent review and acceptance.

## Approved implementation phases

### Phase 0 — Scope reset

Architecture and governance documentation. This is what WO-009A delivers: the scope
document, this roadmap, the source-priority framework, and the Issue #15 TMD disposition
comment. No source ingestion, live collection, AI automation, or Dashboard code.

### Phase 1 — Common data foundation

Source registry, freshness, geography, Logistics nodes, modes, lanes, events, costs, and
assessment history — implementing the conceptual entities listed in
`docs/thailand_multimodal_logistics_intelligence_scope.md` Section 8. This phase would
introduce the first database migrations and shared implementation code; none exist yet.

### Phase 2 — Ocean MVP

Thailand ports, trade flows, initial Ocean lanes, chokepoints, cost context, operational
notices, and Ocean outlook. This phase selects the 8–12 high-priority Lane groups referenced
in the scope document Section 7 (not selected by WO-009A).

### Phase 3 — Air Cargo

Air-cargo indicators, airports, airspace, route events, and Air Lane assessments.

### Phase 4 — Land, Rail and Border

Cross-border corridors, road, rail, border, and customs operational intelligence.

### Phase 5 — News and external drivers

Official-notice ingestion, public news discovery, event clustering, verification, and
lifecycle management. Official operational notices required by an earlier module (e.g. a
port-authority notice needed for Phase 2) may begin before Phase 5 — Phase 5 governs
general news/external-driver discovery, not every operational notice.

### Phase 6 — AI Intelligence Package

Human-triggered structured assessment packages, scenario outputs, and preparedness options,
built on the AI role and Human Review boundary in
`docs/thailand_multimodal_logistics_intelligence_scope.md` Section 10.

### Phase 7 — Private Decision Overlay

Local-only organization-specific data and decision support, per the Public Core / Private
Overlay boundary in `docs/thailand_multimodal_logistics_intelligence_scope.md` Section 4.
Private data is never committed to the public repository.

## MVP acceptance criteria

The future MVP must eventually demonstrate all of the following. **WO-009A does not claim
any of these capabilities are implemented; this is a target checklist for later phases.**

- Thailand-centred analysis
- Sea, Air and Land extensibility
- Ocean as the first operational module
- Import, export and domestic-flow compatibility
- Lane-centred assessments
- Direct Logistics data as the analytical core
- External events admitted only through Logistics relevance
- Trade, port, capacity, cost and event integration
- Scenario-based outlooks
- Traceable evidence
- Explicit data freshness
- Free-only source and infrastructure dependency
- No missing-data-as-zero behavior
- No unsupported real-time claim
- No unsupported freight-average claim
- Human Review for material High/Critical conclusions

## Sequencing notes

- Each phase's acceptance is a separate future Work Order decision; this roadmap records
  approved sequencing, not approved execution.
- A phase may not begin implementation until the phase before it (or the specific
  prerequisite it depends on, e.g. an official operational notice under Phase 2) is
  reviewed and accepted.
- TMD_CAP and GDACS remain governed by their existing, unchanged dispositions (Issue #15;
  `config/sources.yaml`) independent of this roadmap's phase numbering — see
  `docs/thailand_multimodal_logistics_intelligence_scope.md` Section 13.
