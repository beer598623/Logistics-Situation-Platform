# Thailand-Centric Multimodal Logistics — MVP Roadmap

**Work Order:** WO-009A (roadmap corrected by WO-009A-R1)
**Authorized baseline:** `7039b0b4513f3469a6ce649cb1e845a36e359a2a`
**Execution type:** Architecture, governance and documentation reset only

This roadmap records the approved architectural phases and delivery-bundling policy for
`docs/thailand_multimodal_logistics_intelligence_scope.md`. **WO-009A authorized Phase 0
only.** WO-009A-R1 corrects the delivery-sequencing policy below without authorizing any
implementation: no Phase 1 (or later) implementation is authorized until this scope reset
receives independent review and acceptance.

## Architectural phases versus delivery bundles

Two distinct concepts govern how this roadmap is executed:

- **Architectural phases** are logical capability milestones and dependency boundaries —
  they define *what depends on what*, not how work is packaged into Work Orders or pull
  requests.
- **Delivery bundles** are how phases are actually implemented and reviewed. One Work Order
  and one PR may implement multiple adjacent phases, or a coherent subset of phases, when
  they form one reviewable capability.

**Delivery-bundling rules:**

- One PR should normally deliver one major end-to-end capability.
- Documentation, schema, implementation, tests, and Dashboard outputs belonging to that
  capability should remain in the same PR.
- Review corrections and regression tests remain on the same PR.
- A PR may combine adjacent phases when prerequisites and acceptance gates are explicit.
- Separate PRs remain appropriate for live-source authorization, security boundaries, risky
  migrations, licensing decisions, or independently reversible modules.
- Reducing PR count must not produce an unreviewable mega-PR — a bundle is scoped to one
  coherent capability, not to "everything that is currently ready."
- Acceptance gates may occur sequentially inside one Work Order and one PR: a bundle can
  satisfy its component phases' gates one after another within a single review cycle,
  rather than requiring a separate Work Order and PR per gate.

This supersedes any prior wording requiring every phase to receive a separate Work Order and
PR before work on the next phase can begin. No such requirement remains in force.

## Approved architectural phases

### Phase 0 — Scope reset

Architecture and governance documentation. This is what WO-009A delivers: the scope
document, this roadmap, the source-priority framework, and the Issue #15 TMD disposition
comment. No source ingestion, live collection, AI automation, or Dashboard code.

### Phase 1 — Common data foundation

Source registry, freshness, geography, Logistics nodes, modes, lanes, events, costs, and
assessment history — implementing the conceptual entities listed in
`docs/thailand_multimodal_logistics_intelligence_scope.md` Section 8.

### Phase 2 — Ocean MVP

Thailand ports, trade flows, initial Ocean lanes, chokepoints, cost context, operational
notices, and Ocean outlook. This phase selects the 8–12 high-priority Lane groups referenced
in the scope document Section 7 (not selected by WO-009A or WO-009A-R1).

### Phase 3 — Air Cargo

Air-cargo indicators, airports, airspace, route events, and Air Lane assessments.

### Phase 4 — Land, Rail and Border

Cross-border corridors, road, rail, border, and customs operational intelligence.

### Phase 5 — News and external drivers

Official-notice ingestion, public news discovery, event clustering, verification, and
lifecycle management, at whatever depth a given delivery bundle requires. Official
operational notices required by an earlier module (e.g. a port-authority notice needed for
Phase 2) may begin before a full Phase 5 build-out — Phase 5 governs the general
news/external-driver capability, not every operational notice that an earlier phase needs.

### Phase 6 — AI Intelligence Package

Human-triggered structured assessment packages, scenario outputs, and preparedness options,
built on the AI role and Human Review boundary in
`docs/thailand_multimodal_logistics_intelligence_scope.md` Section 10.

### Phase 7 — Private Decision Overlay

Local-only organization-specific data and decision support, per the Public Core / Private
Overlay boundary in `docs/thailand_multimodal_logistics_intelligence_scope.md` Section 4.
Private data is never committed to the public repository.

## Approved delivery bundles

Architectural phases above define capability boundaries. The following delivery bundles
define how those phases are actually grouped into Work Orders and PRs. **None of these
bundles are implemented by WO-009A or WO-009A-R1** — both remain documentation-only.

### Bundle 1 — Common Foundation + Ocean Logistics Intelligence MVP (first implementation bundle)

This is the approved first implementation delivery bundle. It combines Phase 1 (Common data
foundation), Phase 2 (Ocean MVP), the minimum slice of Phase 5 (News and external drivers)
needed for the Ocean use case, and the minimum slice of Phase 6 (AI Intelligence Package)
needed to produce a usable outlook — because the product's core intelligence value (a
source-backed, evidence-linked, scenario-based Ocean/Thailand outlook) requires all four
working together, not Logistics data alone. Splitting these across separate Work Orders
would leave every intermediate PR unable to demonstrate the product's actual value.

**Common foundation** (from Phase 1):

- Shared source and freshness contracts
- Geography, country, mode, Logistics node, chokepoint and Lane entities
- Indicator, cost, trade, event, evidence and assessment history models
- Validation and auditability
- Free-only source qualification fields

**Ocean operational module** (from Phase 2):

- Thailand port and trade foundations
- Initial 8–12 Ocean Lane groups
- Chokepoints
- Public freight benchmarks or proxies, with explicit limitations
- Fuel and FX context
- Official port, canal and carrier operational notices
- Ocean Lane and Thailand relevance assessment

**Minimum News and External Driver capability** (minimum slice of Phase 5, scoped to Ocean):

- Free public discovery sources
- Official-source verification
- Story/event clustering at the minimum level required for the Ocean use case
- Geopolitical, economic, energy, regulatory and weather events admitted only when a
  Logistics transmission mechanism exists (scope document Section 3.4/9)
- Evidence states and event lifecycle
- No paid-source dependency

**Minimum ChatGPT Intelligence capability** (minimum slice of Phase 6):

- Human-triggered structured review package
- Current situation summary
- Verified facts, reported claims, inference and conflicting evidence
- Transmission chains
- Base, deterioration and improvement scenarios
- Time horizon, triggers, evidence strength, confidence and data gaps
- Conditional preparedness options
- Human Review for High or Critical conclusions

**Minimum Dashboard output** (scoped subset of the full information architecture in the
scope document Section 11):

- Thailand Logistics Situation
- Ocean Logistics
- Trade and Flow
- Cost and Freight Pressure
- Events and External Drivers relevant to Ocean
- AI Outlook and Preparedness
- Sources and Methodology

The first implementation bundle does not need to provide complete Air, Road, Rail, or Border
operations. The shared architecture (common foundation entities, source-priority framework,
evidence model) must remain extensible to them — nothing in Bundle 1 may hard-code an
Ocean-only assumption into a shared entity.

### Later delivery bundles (capability groupings, not fixed PR boundaries)

The following are anticipated major future delivery bundles. Each may itself span multiple
PRs, or be combined with an adjacent bundle, depending on what forms a coherent reviewable
capability at the time it is authorized — these names are capability groupings, not mandatory
one-file or one-component PR boundaries:

1. **Air Cargo Intelligence** — Phase 3, plus any News/AI extension specific to Air.
2. **Land, Rail and Border Intelligence** — Phase 4, plus any News/AI extension specific to
   those modes.
3. **Cross-modal News and AI hardening** — broadening Phase 5/6 beyond the Ocean-scoped
   minimum in Bundle 1 to cover all modes together (e.g. shared clustering across Ocean,
   Air, and Land events; cross-modal scenario comparison).
4. **Private Decision Overlay** — Phase 7, local-only organization-specific data and
   decision support.

## MVP acceptance criteria

The future MVP must eventually demonstrate all of the following. **WO-009A and WO-009A-R1 do
not claim any of these capabilities are implemented; this is a target checklist for later
delivery bundles.**

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

**First usable Ocean MVP (Bundle 1) criteria** — in addition to the general criteria above,
the first usable Ocean MVP must:

- combine Logistics data with related operational news and external drivers;
- produce a human-triggered ChatGPT assessment package;
- generate source-backed Ocean and Thailand outlooks;
- show transmission mechanisms and alternative scenarios;
- produce conditional preparedness options;
- remain free-only and organization-neutral.

## Sequencing notes

- Each delivery bundle's acceptance is a separate future Work Order decision; this roadmap
  records approved architectural sequencing and bundling policy, not approved execution.
- A delivery bundle may not begin implementation until its prerequisite phases (or the
  specific prerequisite it depends on, e.g. an official operational notice needed inside
  Bundle 1) are reviewed and accepted at the bundle level — acceptance gates for the
  phases inside one bundle may occur sequentially within that same Work Order and PR,
  rather than requiring separate Work Orders per phase.
- TMD_CAP and GDACS remain governed by their existing, unchanged dispositions (Issue #15;
  `config/sources.yaml`) independent of this roadmap's phase or bundle structure — see
  `docs/thailand_multimodal_logistics_intelligence_scope.md` Section 13.
