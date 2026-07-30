# External-driver admission rules

**Work Order:** WO-010 Gate G · **Status:** implemented
**Logic:** `analysis/events.py::external_driver_admission`, `::evaluate_transmission_chain`

## 1. The rule

An external driver — war and security, economic change, energy shock, trade policy,
political decision, weather or natural hazard — **remains contextual until a Logistics
transmission mechanism is stated**.

Admission requires the full chain:

```
external driver → operational change → Logistics mechanism → observable indicator → outcome
```

If any link is missing, the item is recorded as contextual or as an unresolved hypothesis.
It is never presented as a Logistics impact.

## 2. Contextual is not excluded

An unadmitted driver is still displayed, in its own Dashboard sub-section headed
*Contextual external drivers — no transmission mechanism established*, with its chain shown
link by link and the missing links marked. A reader can see both what is being watched and
exactly why it does not yet support a conclusion.

What an unadmitted driver may not do is carry a material impact. `validate_event` rejects
that combination.

## 3. Worked example — admitted

**HVC-005, energy price shock:**

| Link | Content |
|---|---|
| External driver | A sharp rise in international crude and refined product prices |
| Operational change | Bunker fuel and domestic diesel prices rose alongside the benchmark |
| Logistics mechanism | Bunker cost is a direct input to ocean freight pricing and is commonly recovered through bunker surcharges; domestic diesel is a direct input to inland drayage cost |
| Observable indicator | Published crude benchmarks and Thailand retail diesel prices |
| Outcome | Potential cost pressure across Thailand ocean lanes, with no measured effect on any Thailand shipment price |

Complete → admitted → may carry `cost: potential, moderate`. Note the outcome states
*potential* pressure and explicitly disclaims a measured effect.

## 4. Worked example — not admitted

**HVC-006, Baltic Sea subsea cable damage:**

| Link | Content |
|---|---|
| External driver | Reported damage to subsea telecommunications cables and an associated investigation |
| Operational change | **not established** |
| Logistics mechanism | **not established** |
| Observable indicator | **not established** |
| Outcome | **not established** |

Incomplete → contextual only. Every impact area is `insufficient_evidence`, Thailand
relevance is `none_established`, and the event contributes to no lane assessment. This case
exists in the validation set specifically to check that a widely reported security event
with no stated Logistics mechanism does not acquire one by inference.

## 5. Geography is not relevance

An external driver's geography does not establish Thailand relevance. Relevance is resolved
through the reference dimensions — a country, node or chokepoint the lane actually lists —
and `thailand_relationship_for_geography` **fails closed**: an unrecognised geography
returns `none_established` rather than defaulting to relevant.

Lane relevance additionally records *why* each lane matched, and the strength differs by
match type: a chokepoint the lane actually transits is stronger evidence than a shared
country. `scripts/run_historical_validation.py` measures geography leakage across every
case; it is currently zero.

## 6. What admission still does not license

Admission means the driver may contribute to an impact assessment. It does not mean:

- that the impact is observed rather than potential — that needs its own evidence;
- that any specific lane is affected — lane relevance needs its own basis;
- that any organization is affected — the public core holds no company data and can never
  establish that;
- that a number can be attached — no point forecast is published for any driver.
