# Equipment Detail — Product Designer Brief

**Feature**: Per-machine deep dive with the physics prediction overlay (a key differentiator).

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. The building has equipment: chillers (big cooling machines), AHUs (air handling units), pumps, fans, valves. Each piece has live sensor readings (temperature, pressure, power) and a history. Operators investigate by drilling into one piece of equipment at a time. ARVIS adds a **physics-predicted line** alongside the live reading — the difference between predicted and actual is the anomaly signature.

---

## Why this exists

When an alarm fires on Chiller 4, operator needs to:
- See current live values
- Compare to 24-hour history
- See predicted-vs-actual (is this normal for this load + ambient temp?)
- See related advisories
- See maintenance history + MTBF
- Override / dispatch / acknowledge

Without this screen operator works from raw BMS terminal — slower, less context.

---

## Users

- **Operator (Bilal)** — investigates 5-10 times per shift
- **Engineer / vendor** — deep technical analysis
- **Facility manager** — health summary

---

## Scope

**In**:
- Header with equipment metadata
- Live readings panel
- 24-hour trend chart with **physics prediction overlay** (key feature)
- Related advisories (active + recent)
- Maintenance history + MTBF
- Override actions (gated)

**Out**:
- Full historical drill (P2)
- Cross-equipment correlation (P2)
- Bulk equipment view (Live View has the schematic)

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ Header                                                              │
│ CH-4 Carrier 30XA · 800 TR · Installed 2019 · 47,820 hrs            │
│ Status: Running · Last service: 2026-02-14 · MTBF: 4,200hrs         │
├─────────────────────────────────────────────────────────────────────┤
│ Live Readings (grid of tiles)                                       │
│ ┌──────────┬──────────┬──────────┬──────────┐                      │
│ │ CHWST    │ ECWT     │ Power    │ COP      │                      │
│ │ 6.7°C    │ 32.1°C   │ 421 kW   │ 3.61     │                      │
│ │ (steady) │ (steady) │ (rising) │ (-12%)   │                      │
│ └──────────┴──────────┴──────────┴──────────┘                      │
├─────────────────────────────────────────────────────────────────────┤
│ 24h Trend (multi-series chart with physics overlay)                 │
│                                                                     │
│      ┌─────────────────────────────────────────────────────┐       │
│      │                                                     │       │
│      │  COP line ─────────── (observed)                    │       │
│      │  COP line ··········· (predicted by physics)        │       │
│      │  Shaded delta where they diverge                    │       │
│      │                                                     │       │
│      └─────────────────────────────────────────────────────┘       │
│      Toggle series: ✓ COP  ✓ Power  ☐ Pressure  ✓ Predicted        │
├─────────────────────────────────────────────────────────────────────┤
│ Related Advisories (3 active)                                       │
│  • T2 · CH-4 refrigerant migration · 2 min ago                      │
│  • T1 · Plant COP -3% · 14 min ago                                  │
│  • T1 · CH-4 vibration baseline drift · yesterday                   │
├─────────────────────────────────────────────────────────────────────┤
│ Maintenance History                                                 │
│ Date       · Type        · By       · Notes                         │
│ 2026-02-14 · Inspection  · ACME HVAC · Coil cleaning, OK            │
│ 2025-11-20 · Refrigerant · ACME HVAC · Topped up R134a 8 lbs        │
│ ...                                                                 │
├─────────────────────────────────────────────────────────────────────┤
│ Actions                                                             │
│ [View on schematic] [Open active advisory] [Schedule inspection]   │
│ [Manual override ▾]  (gated, facility_manager only)                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component details

### Header

- Equipment id, model, capacity, install year, run hours, status chip
- MTBF (mean time between failures)
- Last service date
- "Open in schematic" link → Live View focused on this equipment

### Live Readings panel

- Grid of 4-8 tiles depending on equipment kind
- Each tile:
  - Label (top)
  - Big mono value (center)
  - Unit
  - Trend indicator (steady/rising/falling) with arrow
  - Delta vs baseline (e.g., "-12% vs design")
- Color tinting: subtle red if deviation severe; default neutral
- Tile click → opens point detail modal (P1)

### 24h Trend Chart — the patent showcase

**This is the most important visual.**

- Multi-series line chart (Recharts or ECharts)
- Default series for chiller: COP (observed), COP (predicted), Power, Suction Pressure
- Default series for AHU: SAT (observed), SAT (predicted), CHW valve, fan speed
- **Predicted lines are DOTTED, accent color (purple)**
- **Observed lines are SOLID, neutral color**
- **When observed deviates >threshold from predicted: shaded band between them**
- Time axis: last 24h, scrollable to 7d (P1)
- Hover any point: tooltip with all series values + ambient + load context
- Click anywhere on chart: drill into that timestamp (P1)
- Toggle series on/off via checkboxes below chart
- Annotations: vertical lines for events (advisory raised, maintenance performed, setpoint changed)

### Related Advisories

- List of advisories targeting this equipment
- Active first, then recent (last 7 days)
- Each row: risk tier chip, summary, time, click → Advisory Detail

### Maintenance History

- Table: date, type, performed by, notes
- Sortable by date desc default
- Click row → expand for full notes + attached docs

### Actions

- Standard actions: view in schematic, open active advisory
- T3-ish actions (manual override): gated by role
- Override modal: warning + confirm + audit log

---

## States

- **Loading**: skeleton matching layout
- **Stopped equipment**: live tiles muted, "Equipment stopped" banner
- **Offline equipment**: tiles show "—" + last-known timestamp + "Last seen at 14:22"
- **No physics model loaded** (e.g., generic equipment): chart shows observed only, banner "Physics prediction unavailable for this equipment model"
- **Stale data**: tiles + chart show staleness indicator
- **Major fault**: red banner across top: "Critical fault active — see advisory →"

---

## Flows

### Flow A — Operator investigates alarm

1. From Live View, clicks CH-4 (red on schematic)
2. Lands on Equipment Detail
3. Sees Live Readings — power up, COP down
4. Looks at chart — observed COP diverging from predicted starting 14:00
5. Sees Related Advisory pointing to refrigerant migration
6. Clicks advisory → Advisory Detail

### Flow B — Engineer audits physics model

1. Opens Equipment Detail
2. Toggles only Predicted and Observed series on chart
3. Sees they track perfectly except 14:00-now window
4. Opens point detail to verify sensor reading not bad
5. Confirms ARVIS prediction is valid

### Flow C — Manual override (facility_manager)

1. Click "Manual override"
2. Modal: pick point + new value + duration + reason
3. Warning: "This writes to BMS"
4. Confirm
5. Toast: "Override active for 4h"

---

## Design principles

1. **Physics overlay is the focal point**. The dotted line + shaded delta IS the story. Make it obvious.
2. **Chart over text**. Operators trust shapes more than numbers in tables.
3. **Live tiles for at-a-glance, chart for context, advisories for action**.
4. **MTBF + service history humanize the equipment**. Treat as a colleague with a record, not just an asset.
5. **Manual override is gated and warned**. T3 territory.

---

## Edge cases

- Equipment with sub-equipment (chiller plant → 4 chillers): show plant-level view with children navigable
- Equipment with no 24h history (just installed): chart empty state + "Collecting data — first prediction in ~4h"
- Multiple chillers selected for comparison (P2): split-screen mode
- Physics model error (curves missing): banner + "Report to engineering"

---

## Open questions

1. **Default chart series per equipment kind**: 4 series shown by default, rest hidden. Which 4 per kind?
2. **Trend window default**: 24h proposed; some operators want 8h (shift). Setting?
3. **Override scope**: which points override-able? Need engineering input on safe vs unsafe overrides.
4. **Maintenance history source**: comes from ARVIS or external CMMS? P0: ARVIS-managed.
5. **Per-tile sparklines**: include in live tiles or only in main chart? Recommendation: tiny sparkline in each tile (last hour).

---

## Success criteria

- Operator can confirm "this equipment is sick" or "this equipment is fine" in <60 seconds
- Engineer can audit physics prediction in <5 minutes
- Customer in demo points at dotted line and asks "what's that?" — sales rep answers with patent moat

## What designer needs from engineering

- List of equipment kinds in Marina Heights (chiller, AHU, pump, fan, VAV, valve, …)
- Default points per kind (for live tiles)
- Physics prediction availability matrix per kind (chillers yes, fans no)
- Override permission matrix per point type

## Changelog

- v1 2026-05-23: initial
