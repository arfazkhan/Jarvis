# ARVIS — What It Is

**ARVIS is an AI advisor for commercial building operators.** It watches large chiller plants 24/7 (Marina Heights Tower, Doha: 32 floors, 4×800TR Carrier chillers, 142 air handlers), spots problems, explains them, recommends fixes, and shows its work so operators can trust it.

## Who uses it

- **Building operators** (sit at the BMS desk, watch alarms, dispatch technicians)
- **Facility managers** (review trends, sign off recovery actions)
- **Owners / executives** (quarterly KPI view)
- **AI engineers / auditors** (debug why ARVIS said something)
- **Sales / demo pilots** (run customer demos)

## What it produces

Every interaction with ARVIS produces or relates to an **Advisory** — a single recommendation card with:
- A risk tier: **T1** (info), **T2** (diagnostic, investigate), **T3** (actionable, change setpoint or dispatch)
- A summary + recommendation
- An **Agent Trace** — multiple AI agents (Energy, Maintenance, Comfort, etc.) voted on this. Each vote is one of: APPROVE / APPROVE_WITH_CONDITION / VETO / ABSTAIN, with confidence and reasoning.
- An **Evidence Ledger** — every fact used, with its source (live sensor, history, physics simulation, memory).
- **Verifier Gates** — 3 pass/fail checks every advisory must pass: Claim, Faithfulness, Physics.
- A **Counterfactual** — predicted outcome with vs without the recommended action.

## How it sits in a building

ARVIS is a **layer on top of** the existing BMS (Building Management System, e.g. Siemens Desigo CC). The BMS is the actual control system. ARVIS is **read-only advisory** — it observes, recommends, but does not (yet) write setpoints or actuate equipment. The operator (a human) decides whether to execute the recommendation.

## Modes

Same UI, three modes:
- **SIM** — fully simulated building. Events come from a persona generator. For sales demos and internal regression tests.
- **PILOT** — real building, shadow mode. Advisories render but no notifications fire, no BACnet writes occur. Default for first 30 days of any deployment.
- **PROD** — real building, live. Notifications fire, BACnet writes go through (when permitted).

A **mode badge** in the top bar of the UI shows which mode is active. Color-coded (gray / amber / green).

## The moats — what makes ARVIS different from a chatbot

These must be visible in the UI; they are the trust story:

1. **Multi-agent debate** — competitors have one model. ARVIS has multiple specialist agents that vote.
2. **Verifier gates** — every advisory passes 3 automated checks before reaching the operator. Visible.
3. **Physics simulation overlay** — equipment readings shown alongside what a physics model predicts they should be.
4. **Cross-incident memory** — "this looks like the issue from 2026-03-04, here's what worked."
5. **Counterfactual** — "with this action: outcome X. Without: outcome Y."
6. **Operator action attribution** — "you changed setpoint 4 min ago, that's why."

## Glossary

- **BMS** — Building Management System; the existing control software
- **BACnet** — industry protocol for building points
- **Point** — single sensor or actuator reading (temperature, pressure, command)
- **Equipment** — chiller, AHU, pump, fan
- **Alarm** — raw event from BMS
- **Advisory** — ARVIS's interpretation of alarms + readings into a recommendation
- **PLR** — Part Load Ratio (how loaded a chiller is, 0-1)
- **COP** — Coefficient of Performance (chiller efficiency = cooling out / electricity in)
- **CHW** — Chilled Water
- **OAT** — Outdoor Air Temperature
- **GSAS** — Qatar's green building rating system; renewed annually based on operations
- **Skillbook** — ARVIS's accumulated patterns from past incidents
- **Setpoint** — operator-set target value (e.g., "cool zone to 22°C")
- **Risk Tier** — T1 / T2 / T3 (see above)

## What ARVIS does NOT do (today)

- Write to BACnet (planned, gated by approval — not in P0)
- Replace the BMS — sits beside it, doesn't supplant
- Run autonomously without operator visibility — every advisory presented for human decision
- Train its own models — uses pre-built physics + LLM stack
- Provide HVAC training to operators — focused on monitoring + recommendation

## Production status

- Pilot target: Marina Heights Tower, West Bay Doha
- Marina pass rate at time of writing: 33% (3/9 simulation phases) — engine fixes in progress
- UI is greenfield; this PRD set is the start
