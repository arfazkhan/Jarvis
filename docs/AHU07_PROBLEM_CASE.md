# Field Diagnostic Challenge — AHU-07, Marina Heights Tower (Floor 28)

**Format:** blind, timed root-cause analysis.
**Goal:** you (the engineer) diagnose the fault from the data below; we separately run ARVIS on the *identical* data; we compare time-to-diagnosis, hypotheses, and the recommended verification steps.

> **Ground rule for the facilitator:** Give the engineer ONLY the data in Section 3 + the drawing in Section 5. Do **not** add chilled-water supply/return temps, coil pressure-drop, or humidity — ARVIS is **not** given those either. If you choose to add any datum, add it to ARVIS's input too, or the comparison is invalid.

---

## 1. Scenario / Context

- **Building:** Marina Heights Tower, West Bay, Doha, Qatar.
- **Unit:** AHU-07, serving **Floor 28** (open-plan office), zones **28A / 28B / 28C**.
- **Climate:** peak summer. Hot, humid outdoor conditions.
- **System type:** central chilled-water AHU (CHW cooling coil, 2-way modulating control valve), VAV distribution to the three zones. Economizer-capable mixing box (OA / RA / relief dampers).
- **Operating hours:** ~12 h/day occupied profile.
- **Complaint trigger:** tenants on Floor 28 reported it is too warm; the BMS raised alarms on AHU-07.

You have been dispatched (virtually) with the BMS readout below. Nearby AHUs on adjacent floors report **normal**.

---

## 2. Your Task

1. State your **most probable root cause**.
2. List **all competing hypotheses** you are holding, ranked, with rough likelihood.
3. For **each** hypothesis, name the **single discriminating test/measurement** that would confirm or rule it out.
4. State which checks you'd do **first on site** and in what order.
5. Note any datum you **distrust** and why.

**Timing:** the facilitator starts a clock when you first see Section 3 and stops it when you give your ranked answer (step 2). Think aloud; the facilitator records your reasoning order.

---

## 3. BMS Readout — exactly what the system shows (this is all ARVIS gets too)

### 3.1 AHU-07 air-side telemetry (live)
| Point | Tag | Value | Notes |
|---|---|---|---|
| Mixed Air Temp | `MAT` | **30.8 °C** | flagged anomalous; **z-score = 5.8** vs its own 35-sample rolling baseline (~24 °C) |
| Supply Air Temp | `SAT` | **16.5 °C** | downstream of cooling coil |
| Outdoor Air Temp | `OAT` | **42.0 °C** | rooftop sensor |
| Return Air Temp | `RAT` | **24.0 °C** | return plenum |
| OA Damper — **commanded** | `OA_DMPR_CMD` | **15 %** | what the BMS sequence is asking for |
| OA Damper — **position feedback** | `OA_DMPR` | **15 %** | actuator-shaft feedback **matches command** |
| Chilled-Water Valve | `CHW_VALVE` | **99 %** | modulating cooling valve, near full open |

> The supply-fan VFD reports no fault; filters report clean (no high-ΔP alarm). No chilled-water supply/return temperatures, coil pressure-drop, or RH are instrumented on this unit.
>
> ⚠️ **About `OA_DMPR`:** this is the **actuator position feedback**, which reports the motor-shaft angle — *not* a direct measurement of the physical damper-blade angle. Feedback reading 15% does **not** prove the blades are at 15%. The true blade angle is **not instrumented** — it can only be established by physical inspection.

### 3.2 Zone telemetry (Floor 28)
| Zone | Zone Temp | Setpoint | CO₂ | VAV Damper | Lights |
|---|---|---|---|---|---|
| 28A | 25.8 °C | 23.0 °C | 720 ppm | 85 % | ON |
| 28B | 26.1 °C | 23.0 °C | 720 ppm | 85 % | ON |
| 28C | 25.5 °C | 23.0 °C | 720 ppm | 85 % | ON |

All three zones are **2–3 °C above setpoint**; VAV boxes are driven wide open.

### 3.3 Active alarms (6)
| ID | Equipment / Point | Description | Severity |
|---|---|---|---|
| ALM-AHU07-002 | AHU-07 / SAT | Supply air 16.5 °C, 3.0 °C above 13.5 °C setpoint — unit cannot hold supply temperature | CRITICAL |
| ALM-AHU07-001 | AHU-07 / MAT | Mixed air temp 30.8 °C — high, z-score 5.8 vs rolling baseline | HIGH |
| ALM-AHU07-003 | AHU-07 / CHW_VALVE | CHW valve at 99% — cooling capacity exhausted | HIGH |
| ALM-Z28A | ZONE-28A | Zone 28A over-temp 25.8 vs 23.0 | MEDIUM |
| ALM-Z28B | ZONE-28B | Zone 28B over-temp 26.1 vs 23.0 | MEDIUM |
| ALM-Z28C | ZONE-28C | Zone 28C over-temp 25.5 vs 23.0 | MEDIUM |

### 3.4 Setpoints / design notes given
- SAT control setpoint: **13.5 °C** (unit is failing to hold it; actual 16.5 °C).
- Zone setpoint: **23.0 °C**.
- Minimum OA at this occupancy: **~15 %** (hence the 15% command).

---

## 4. Hint reference (math the engineer may want)

Sensible mixing balance:
```
MAT_expected = (OA% × OAT) + (RA% × RAT)
```
(left intentionally for the engineer to apply — do not pre-compute on the sheet.)

---

## 5. Drawing to prepare (hand to the engineer with Section 3)

Draw **one A4 single-line air-path schematic** of AHU-07, left→right, plus a small CHW inset. Label every sensor with its tag from Section 3 so the engineer can reason about placement, stratification, and bypass.

### 5.1 Air path (main drawing, left → right)
```
 OUTDOOR AIR ──▶[ OA Damper ]──┐
   (OAT 42°C)   (cmd 15% /      │
                 fb 15% / true  ▼
                 angle = ?)
 RETURN AIR ──▶[ RA Damper ]──▶( MIXING BOX )──▶[ Filter ]──▶[ CHW Cooling Coil ]──▶[ Supply Fan ]──▶ SUPPLY DUCT ──▶ VAV-28A/B/C ──▶ ZONES
   (RAT 24°C)                      │  (MAT 30.8°C)   (clean)        │   ▲                                    (SAT 16.5°C, setpoint 13.5°C)
                                   │                                │   │
 RELIEF/EXHAUST ◀─[ Relief Damper]─┘                         CHW supply │ CHW return
                                                              ─────[ 2-way modulating valve ]──── (CHW_VALVE 99%)
```
Mark sensor locations explicitly:
- **OAT** — outdoor air intake (before OA damper).
- **RAT** — return plenum.
- **MAT** — in the mixing box, **after** OA+RA mix, **before** the coil. (Call out that this is a single-point sensor in a mixing box — invites the stratification question.)
- **SAT** — **after** the coil and fan, in the supply duct.
- **OA_DMPR_CMD / OA_DMPR** — at the OA damper actuator (command vs reported position).
- **CHW_VALVE** — on the coil's 2-way control valve.

### 5.2 CHW inset (small, corner of the page)
```
 CHW SUPPLY ─────▶───[ Cooling Coil ]───▶───── CHW RETURN
                          ▲
                   [ 2-way valve 99% ]
   (no CHWS / CHWR temperature sensors, no coil ΔP gauge on this unit)
```
Explicitly write **"not instrumented"** on CHWS temp, CHWR temp, and coil ΔP — so the engineer knows those are unavailable (and will likely *ask* for them, which is itself a useful data point to record).

### 5.3 Floor 28 zone stub (optional small block)
Three boxes 28A/28B/28C off the supply duct via VAV terminals, each showing zone temp / setpoint / CO₂ / VAV% from Section 3.2.

> Keep the drawing **fault-neutral** — show the damper at its *reported* position ambiguously (e.g. blades drawn mid-travel with a "?" by the linkage). Do not pre-bias toward "stuck open."

---

## 6. Facilitator scoring sheet

| Metric | Engineer | ARVIS |
|---|---|---|
| Time to first hypothesis | ___ | ___ |
| Time to ranked answer | ___ | ___ |
| # hypotheses held | ___ | ___ (target: 2–4) |
| Leading hypothesis | ___ | ___ |
| Flagged "verify damper physically / feedback may lie"? (Y/N) | ___ | ___ |
| Flagged MAT sensor / stratification doubt? (Y/N) | ___ | ___ |
| Named discriminating test per hypothesis? (Y/N) | ___ | ___ |
| Committed to a single cause vs held differential | ___ | ___ |
| Estimated energy/cost impact given? | ___ | ___ (QAR/mo) |

### How to run ARVIS side
```
# start the demo backend, then:
POST /api/v1/demo/reasoning/trigger
   { "query": "AHU-07 OA damper reads 85% open vs 15% command, supply air running hot, Floor 28 tenants complaining — walk me through what's driving it and the downstream impact." }
# read investigation_result.hypotheses[], differential, cost_impact, metrics.elapsed_seconds
GET  /api/v1/demo/explain/advisory/{id}   # full ranked differential + discriminating tests
```
Record `metrics.elapsed_seconds` as ARVIS's time; `hypotheses[]` as its ranked answer.

---

## 7. What "good" looks like (facilitator's private key — do NOT show the engineer)

> Hidden. Read only after the engineer commits their answer.

- **The damper feedback (15%) is a trap** — it matches command, so nothing on the BMS *directly* points at the damper. The fault must be **inferred from the air balance**, not read off a sensor.
- The MAT math: `(0.15×42)+(0.85×24)=26.7 °C` expected at commanded 15%. Actual MAT **30.8 °C** is **~4 °C above** that → effective OA ≈ `(30.8−24)/(42−24)=38 %`, i.e. **more outdoor air than the 15% commanded** despite feedback reading 15% → **OA damper actuator/linkage slip (blades open ~85% while feedback lies)** is the leading inference.
- **Hidden ground truth (reveal only after they answer):** the physical blades are stuck ~85% open; the actuator-shaft feedback reads 15% because the linkage slipped. A visual inspection is the only way to see it.
- A defensible engineer also holds: **(a) cooling-coil capacity / CHW-flow limit** (valve 99% yet SAT 16.5 ≫ 13.5 — could be co-fault or primary; cannot rule out without CHW flow / coil ΔP, which aren't instrumented), and **(b) MAT sensor bias / mixing-box stratification** (single-point sensor reading high would mimic excess OA).
- **Best engineers refuse to "confirm" any single cause from this data** and demand the physical blade/linkage check + a CHW-flow measurement before committing. That epistemic restraint is the thing to score — not the leading guess alone.
- Strongest single discriminating action: **visually inspect the OA damper blades/linkage** (separates slip from coil/sensor causes in one look, and exposes the feedback lie).

This is exactly the differential ARVIS is built to produce: ranked hypotheses, each with its discriminating test, and `confirmed=false` while alternatives remain close.
