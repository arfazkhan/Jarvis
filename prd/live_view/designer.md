# Live View — Product Designer Brief

**Feature**: The home screen — building schematic, active alarms, open advisories feed, KPI strip.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial building operators. It watches large chiller plants (Marina Heights: 32 floors, 4 chillers, 142 air handlers) and recommends fixes. Operators sit at a BMS room desk. They open ARVIS at shift start and check this screen first. ARVIS produces **Advisories** — recommendations with risk tier T1 (info), T2 (diagnostic), T3 (actionable). Modes: SIM (synthetic), PILOT (shadow), PROD (live).

---

## Why this exists

Bilal (operator) starts shift at 18:00. He needs to know in 30 seconds:
- What's broken right now? (alarms)
- What does ARVIS recommend I do? (advisories feed)
- Is the building burning energy? (KPIs)
- What does the plant look like right now? (schematic)

Without Live View, operator hunts across 6 different BMS screens. ARVIS collapses these into one view.

---

## Users

- **Operator (Bilal)** — primary, opens this every 5-15 min
- **Facility manager (Ahmed)** — checks at start of day, walks floor with tablet
- **Demo / sales** — first impression for any customer demo

---

## Scope

**In**:
- Building schematic (60% of canvas)
- Active alarms strip (top, ~80px)
- Open advisories feed (right column, ~360px)
- KPI strip (bottom, ~60px)

**Out**:
- Per-equipment deep dive (lives in Equipment Detail)
- Past advisories (lives in Audit & Replay)
- GSAS / compliance widgets (lives in Compliance)

---

## Layout (1920×1080 desktop default)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Active alarms strip — chronological, ~6 visible, scroll for more   │
├──────────────────────────────────────────────┬──────────────────────┤
│                                              │ Open Advisories      │
│                                              │ ┌──────────────────┐ │
│                                              │ │ T2 · 2 min ago   │ │
│              BUILDING SCHEMATIC              │ │ AHU-7 cascade    │ │
│           (clickable equipment)              │ │ [Approve][Reject]│ │
│                                              │ └──────────────────┘ │
│                                              │ ┌──────────────────┐ │
│                                              │ │ T1 · 14 min ago  │ │
│                                              │ │ Plant COP -3%    │ │
│                                              │ │ [View]           │ │
│                                              │ └──────────────────┘ │
├──────────────────────────────────────────────┴──────────────────────┤
│ KPI strip — kW now · plant COP · GSAS · advisories closed today    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Zones

### Active alarms strip

- Horizontal scroll list
- Each alarm: severity icon, time-since chip, equipment id, message, dismiss button
- Sorted: critical → warning → info, then newest first
- Empty state: "No active alarms" with subtle illustration
- Click alarm → modal with alarm detail + linked advisory if any

### Building schematic

- 2D SVG (P0). 3D isometric P2 stretch.
- Equipment rendered with custom icons (chiller, AHU, pump, valve)
- Equipment color = health:
  - Green outline: normal
  - Amber outline: at-risk
  - Red fill: alarm active
  - Gray: offline/unknown
- Hover equipment → tooltip with id + status + key live values
- Click equipment → navigate to Equipment Detail
- Two view modes:
  - **Schematic mode**: iconographic, all equipment same scale
  - **P&ID mode** (P1 stretch): traditional engineering drawing style

### Open advisories feed (right column)

- Vertical scroll list of cards
- Each card:
  - Risk tier chip (T1 / T2 / T3 with color)
  - Time-since chip (e.g., "2 min ago")
  - Shadow badge if PILOT-shadow
  - One-sentence summary
  - Equipment targeted (small chip)
  - Quick actions: Approve (primary), Reject (secondary), View (tertiary)
- Sort: by time desc (newest top); by risk tier (T3 first) as toggle
- Empty state: "No open advisories. 12 closed today." with celebration micro-illustration
- New card appears: subtle slide-in from top + 1s highlight glow (no aggressive motion)

### KPI strip

- 4 equal-width tiles:
  - Building power now (kW, with sparkline)
  - Plant COP (current, vs design)
  - GSAS score projected (with star count)
  - Advisories closed today (count + delta)
- Tile click → corresponding detail screen
- Compact: 60px tall

---

## States

- **Loading**: skeleton with shape hints, not spinners
- **Empty (first deploy, no data yet)**: "ARVIS is observing — first analysis in ~4 hours"
- **All clear**: alarms 0, advisories 0, KPIs nominal → soft "All clear" illustration in alarm strip
- **Critical alarm raised**: alarm strip flashes once (200ms), bell pings (top bar)
- **Stale data**: amber banner above schematic if data >5min stale: "Last update 14:22"
- **Disconnected**: replace KPI strip values with "—" + reconnect indicator

---

## Flows

### Flow A — Operator opens at shift start

1. Land on Live View
2. Scan alarm strip (left to right)
3. Scan advisory feed (top to bottom)
4. Glance KPI strip (sanity check)
5. Click first advisory → Advisory Detail

Time budget: <15 seconds.

### Flow B — New advisory mid-shift

1. Subtle bell ping
2. Card slides in top of advisory feed with 1s highlight
3. Operator clicks → Advisory Detail

### Flow C — Investigating equipment from schematic

1. Operator sees AHU-7 red
2. Hovers → tooltip shows "Cascade alarm cluster, 14 alarms"
3. Clicks → Equipment Detail for AHU-7

---

## Design principles

1. **The schematic is the canvas**. Alarms + advisories overlay it. Don't bury it.
2. **Red/amber only for problems**. Schematic green outlines are quiet, not celebratory.
3. **One screen, no scrolling required** for default 1920×1080 view. Scrolling allowed within zones.
4. **Information density wins**. Operators want everything visible.
5. **No animations on schematic equipment**. They should not pulse, glow, breathe. The state IS the value.
6. **Advisory feed is the conversion surface**. Every advisory must be one click from action.

---

## Edge cases

- 100+ active alarms: strip caps at 10 visible, "+ N more" chip opens full alarm list overlay
- 50+ open advisories: feed virtualized, infinite scroll
- Building with no equipment yet (first onboarding): schematic shows "Upload building.yaml" placeholder
- Operator clicks Approve on T3 they don't have permission for: modal "Requires Facility Manager. Escalate?"
- Schematic on 1080p vs 1440p vs 4K: schematic responsive; equipment icons stay ≥24px

---

## Open questions

1. **Schematic style**: iconographic (subway map) vs P&ID (engineering drawing)? Operators understand P&ID natively, customers in demos prefer iconographic. Likely toggle, default iconographic.
2. **Alarm severity sort vs time sort**: which is default? Operator preference; default severity desc.
3. **Quick approve in feed vs require Advisory Detail open**: P0 allow quick approve for T1/T2; T3 must open detail.
4. **Sparklines in KPI tiles**: how far back? 24h baseline. Configurable later.
5. **Multi-building Live View** (P3): tabbed within Live View or separate selector?

---

## Success criteria

- Operator decides what to investigate in <15 seconds from Live View
- New advisory visible in feed within 3 seconds of engine publish
- Sales demo: customer sees full state of building in one glance, asks intelligent questions

## What designer needs from engineering

- Building topology shape (for schematic layout)
- Marina Heights specific equipment list and approximate physical layout
- KPI definitions: which 4 KPIs?
- Schematic icon set (custom icons needed)
