# Exec KPI Roll-up — Product Designer Brief

**Feature**: Owner / executive dashboard. $ saved, MTBF, GSAS score, advisory accuracy. Quarterly snapshot.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. The product saves energy, prevents failures, improves compliance. Building owners care about $ saved + asset value + ESG progress. This screen rolls up all of ARVIS's daily output into an executive view.

---

## Why this exists

Owners (Noor type) check ARVIS quarterly. They don't want sensor data or alarm details — they want one number: "is this paying off?"

Without this screen, ARVIS looks like an operations tool. With it, ARVIS becomes an ROI story for ownership.

---

## Users

- **Owner (Noor)** — primary, opens 1-4× per quarter
- **Facility manager (Ahmed)** — reviews before owner meeting
- **Sales prospect** — sees this in customer pitch as "what your owner will see"

---

## Scope

**In**:
- Hero KPI strip (4-6 big numbers)
- Energy trend chart (12-month)
- GSAS trajectory
- Advisory accuracy + adoption rate
- Top wins (success stories from past quarter)
- Top concerns (open big risks)
- Export to PDF (board pack)

**Out**:
- Real-time monitoring (lives in Live View)
- Equipment-level detail (Equipment Detail)
- Operator action history (Audit & Replay)

---

## Layout (presentation-mode density, airy)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Marina Heights Tower · Q2 2026                       [Export PDF]   │
├─────────────────────────────────────────────────────────────────────┤
│ Hero KPIs                                                           │
│ ┌────────────┬────────────┬────────────┬────────────┬────────────┐│
│ │ $ Saved    │ kWh Avoided│ GSAS Score │ MTBF       │ Approval % ││
│ │ $187,420   │ 1.42 GWh   │ ★★★★☆      │ 4,820 hrs  │ 82%        ││
│ │ ▲ 23% YoY  │ ▲ 18% YoY  │ ▲ 1 star   │ ▲ 12% YoY  │ → flat     ││
│ └────────────┴────────────┴────────────┴────────────┴────────────┘│
├─────────────────────────────────────────────────────────────────────┤
│ Energy Trend (12 months, kWh vs baseline)                           │
│   [chart: baseline dashed, actual solid, savings shaded green]     │
├─────────────────────────────────────────────────────────────────────┤
│ GSAS Trajectory (3 years)                                           │
│   [chart: yearly score with star bands]                            │
├─────────────────────────────────────────────────────────────────────┤
│ Top Wins (Q2)                                                       │
│ • Caught CH-4 refrigerant migration before failure — saved $40k    │
│ • Recommissioned 3 AHUs — 14% efficiency improvement                │
│ • GSAS Energy category improved from 78% to 87%                     │
├─────────────────────────────────────────────────────────────────────┤
│ Top Concerns (Open)                                                 │
│ • Chiller plant resilience: CH-4 reliability declining              │
│ • IAQ survey response rate below 30%                                │
│ • 14 critical advisories still pending operator action              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component details

### Hero KPI tile

- Large mono number (3xl)
- Label below
- YoY delta with arrow + percent
- Optional sparkline (12m mini)

KPIs (P0):
1. **$ Saved** (cumulative this period, vs baseline)
2. **kWh Avoided** (cumulative)
3. **GSAS Score** (current, with stars)
4. **MTBF** (mean time between failures, hours)
5. **Approval %** (operator approval rate)

KPIs (P1 stretch):
6. **Carbon Saved** (tCO₂ equivalent)
7. **GSAS Compliance Streak** (consecutive years at ≥4 Star)

### Energy trend chart

- 12-month line chart
- Baseline (pre-ARVIS or design) as dashed line
- Actual usage as solid line
- Area between shaded green where actual < baseline (savings)
- Annotations for major events (heatwave, equipment outage)
- Hover → tooltip with values + delta

### GSAS trajectory

- Multi-year chart, yearly final ratings
- Star bands as background shaded areas
- Current period projection (dotted forward line)

### Top wins

- Curated by ARVIS (algorithmic) + facility manager confirms
- Each: one-line description, attributed equipment, $ or % value
- Source links to original advisory

### Top concerns

- Algorithmic + manager curation
- Each: concern + suggested response + linked advisories

---

## States

- **First quarter** (insufficient data): show what we have, banner "Less than 3 months data — comparisons unavailable"
- **Loading**: skeleton
- **Export in progress**: button shows spinner
- **PDF ready**: download link toast
- **Negative delta** (kWh up YoY): still shown honestly, with context "Heatwave summer"

---

## Flows

### Flow A — Owner quarterly review

1. Owner opens ARVIS (rare — usually via email link from manager)
2. Lands on Exec KPI page
3. Scans hero strip (3-5 seconds)
4. Reads Top Wins (positive framing)
5. Reads Top Concerns (decides if ownership intervention needed)
6. Closes or downloads PDF for board pack

Time: <2 min.

### Flow B — Manager prepares for board meeting

1. Manager opens Exec KPI for prior quarter
2. Reviews data accuracy
3. Edits Top Wins / Concerns (P1 — manager can curate)
4. Exports PDF
5. Attaches to board deck

### Flow C — Sales demo to prospect

1. Sales rep loads Marina Heights synthetic data
2. Opens Exec KPI in front of prospect's CFO
3. Walks through hero strip
4. Closes with "this is what your quarterly looks like"

---

## Design principles

1. **Big numbers, big context**. Owner reads numbers, not paragraphs.
2. **Honest deltas**. Negative numbers shown with context, not hidden.
3. **Story over data**. Top Wins / Top Concerns are narrative — like a CEO letter.
4. **Print-ready**. Every screen must export cleanly to PDF.
5. **Airy density**. This is the only ARVIS screen that's NOT a power-user surface. Whitespace welcome.
6. **Brand co-existence**. Customer logo top-left next to ARVIS chrome.

---

## Edge cases

- Building <12 months old: hide YoY deltas, show MoM instead with caveat
- GSAS not yet audited (year 1): show ARVIS-estimated with prominent caveat
- Negative savings (rare): show honestly with explanation
- Multiple buildings (P3): toggle between buildings or roll-up across portfolio

---

## Open questions

1. **Hero KPI count** — 5 (proposed) or 4? Density balance.
2. **Sparklines in tiles** — yes for all 5? Some KPIs don't have natural sparkline (GSAS).
3. **Top Wins curation** — algorithmic vs manager-edited? P0 algorithmic, P1 editable.
4. **PDF design** — branded with customer logo? White-label?
5. **Comparison group** (vs portfolio avg or industry avg) — P2.

---

## Success criteria

- Owner reads + understands in <2 min
- PDF export looks board-ready
- Top Wins surface real wins (not fluff metrics)

## What designer needs from product

- KPI definitions + formulas
- Sample data with 12 months of trend
- Customer brand assets for co-branding
- PDF export specification

## Changelog

- v1 2026-05-23: initial
