# ARVIS — Complete Context Document

**Purpose**: Single reference for everything ARVIS is, does, and where it stands. Read this if you need full context fast.

**Status**: v1
**Date**: 2026-05-23
**Maintainer**: arfazkhan@gmail.com

---

## 1. Elevator Pitch

ARVIS is an agentic AI advisory system for commercial Building Management Systems (BMS). It sits on top of existing building control software (Siemens Desigo CC, Niagara, etc.), watches large chiller plants 24/7, spots problems before they cascade, recommends fixes with cost/benefit math, and shows its work so operators can trust it.

**First pilot target**: Marina Heights Tower, West Bay Doha. 32 floors. 78,000 m². 4 × 800 TR Carrier 30XA chillers. 142 air handlers. 12,386 BACnet points.

**Pre-Series A startup. Stage**: working prototype in simulation environment. Pilot deployment targeted Q3 2026.

---

## 2. The Building Operator Problem

Operators today:
- Read alarms on 2010s-era control screens
- 100+ false alarms per day
- Spend hours per shift hunting root cause
- Call vendors for issues vendors can't diagnose remotely
- Miss energy waste, fail compliance audits, blamed when systems fail

Existing solutions:
- **Dashboards** — show data, demand operator becomes analyst
- **Chatbots** — answer questions but hallucinate, no operator trusts them
- **Closed vendor systems** — black-box, no portability, no transparency
- **Predictive maintenance** — vendor-locked, single-model, often wrong

ARVIS sits beside the BMS as a "senior engineer who never sleeps." Tells the operator **what** is wrong, **why** it's wrong, **what to do**, and **how confident**.

---

## 3. Marina Heights Tower — Specs

```yaml
building_id: marina_heights
display_name: "Marina Heights Tower"
location: "West Bay, Doha, Qatar"
floors: 32
floor_area_m2: 78000
occupancy: 4500
bms: "Siemens Desigo CC"
chiller_plant:
  - id: CH-1
    model: "Carrier 30XA"
    capacity_tr: 800
    capacity_kw: 1409.6
    design_cop: 3.10
  - id: CH-2
    model: "Carrier 30XA"
    capacity_tr: 800
  - id: CH-3
    model: "Carrier 30XA"
    capacity_tr: 800
  - id: CH-4
    model: "Carrier 30XA"
    capacity_tr: 800
air_handlers: 142
vavs: 800+
total_points: 12386
gsas_target: "4 Star (current)"
energy_baseline_kwh_per_m2_yr: 250
```

Marina is the test laboratory. Every architectural decision, every patent claim, every demo references Marina.

---

## 4. Architecture Overview

```
                        ┌─────────────────────────┐
                        │       Operator UI       │
                        │  (Next.js console)      │
                        └────────────┬────────────┘
                                     │ REST + SSE
                        ┌────────────▼────────────┐
                        │      Queen (BFT         │
                        │     coordinator)        │
                        └────────────┬────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼               ▼            ▼            ▼               ▼
  ┌──────────┐   ┌──────────┐  ┌──────────┐  ┌──────────┐   ┌──────────┐
  │ Energy   │   │ Maint.   │  │ Comfort  │  │ Memory   │   │ ... 8    │
  │ Agent    │   │ Agent    │  │ Agent    │  │ Agent    │   │ more     │
  └────┬─────┘   └────┬─────┘  └────┬─────┘  └────┬─────┘   └────┬─────┘
       │              │             │             │              │
       └──────────────┴─────────────┼─────────────┴──────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │   Shared Knowledge      │
                       │   Base + Evidence       │
                       └────────────┬────────────┘
                                    │
                  ┌─────────────────┼─────────────────┐
                  ▼                 ▼                 ▼
            ┌──────────┐      ┌──────────┐      ┌──────────┐
            │ Physics  │      │ Memory   │      │ BACnet   │
            │ Sim      │      │ (7 tier) │      │ adapter  │
            │ engine   │      │          │      │          │
            └──────────┘      └──────────┘      └──────────┘
```

### Components

- **Queen** — orchestrator. Receives queries, routes to nodes, collects votes, runs BFT consensus, calls verifier gates, returns synthesized advisory.
- **SwarmNodes (12 agents)** — specialist agents, each with their own tool set and LLM channel. Vote on proposals.
- **Shared Knowledge Base** — cross-agent findings ledger during one investigation.
- **Evidence Ledger** — typed evidence per call signature, persisted.
- **Verifier Gates** — H2 (claims), H4 (faithfulness), H6 (physics), abstention gate. Run before publishing advisory.
- **Physics Simulator** — DOE-2 bi-quadratic curves, NTU-effectiveness, fan affinity, lumped-capacitance building model. Backs Patent App 2 Claim 2.
- **Memory Orchestrator** — 7 tiers (T1-T7), pgvector index, embedding-based recall.
- **BACnet adapter** — point ingest (PILOT/PROD), persona generator (SIM).

---

## 5. The 12 Agents (SwarmNodes)

| Agent | Tools | Specialty |
|---|---|---|
| **Energy_Agent** | 25 | Energy waste detection, kW/COP analysis, tariff optimization, demand peak management |
| **Alarm_Agent** | 6 | Alarm clustering, cascade analysis, root cause inference |
| **Maintenance_Agent** | 9 | Equipment health, MTBF, predictive maintenance, fault detection |
| **Comfort_Agent** | 7 | Zone temperature, IAQ, occupant complaints |
| **Sensor_Fusion_Agent** | 3 | Multi-sensor validation, drift detection |
| **Strategic_Agent** | 9 | Long-horizon planning, capex recommendations, retrofit advice |
| **Planning_Agent** | 4 | Schedule optimization, setpoint scheduling |
| **Memory_Agent** | 6 | Skillbook recall, past incident matching, pattern retrieval |
| **Briefing_Agent** | 4 | Daily/weekly briefings, dashboard summaries |
| **Voice_Agent** | 0 | Voice I/O (P2) |
| **Persona_Agent** | 0 | SIM-mode synthetic operator behavior |
| **Mission_Agent** | 2 | Long-running goal tracking |
| **System_Capability_Agent** | (implicit) | Capability boundary clarifications ("can ARVIS write to BMS?") |

Each agent runs on its own Bedrock channel — different LLMs optimized for the task (see §12).

---

## 6. The 4 Moats

ARVIS's defensible differentiation. Every product decision serves at least one moat.

### Moat 1 — Agentic + Hallucination

- Multi-agent debate with graded votes (APPROVE / APPROVE_WITH_CONDITION / VETO / ABSTAIN)
- BFT (Byzantine Fault Tolerant) consensus
- Multi-signal abstention gate (coverage + truth_score + ml_fallback_ratio + max_drift)
- Verifier gates H2/H4/H6 catch hallucinations pre-publish
- Closed-loop physics verification with regen-or-abstain

### Moat 2 — ML

- DOE-2 bi-quadratic chiller curves with calibration
- NTU-effectiveness cooling coil model (ASHRAE Ch 23)
- Lumped-capacitance building thermal model (Incropera §5.2)
- Bayesian Network root cause analysis (pgmpy — currently missing dependency)
- Embedding-based memory recall
- Anomaly detection via physics deviation

### Moat 3 — Tool Calling

- 12 agents × 0-25 tools each
- Type-validated tool schemas
- Call signature deduplication across agents (`_shared_call_sigs`)
- Budget enforcement (tokens, seconds)
- Tool result evidence ledger with ML lineage

### Moat 4 — Memory & Institutional Knowledge

- 7-tier memory architecture (T1 working → T7 resolution)
- Per-building skillbook
- Cross-incident pattern matching
- Operator feedback feeds T7 directly
- Embedding index (pgvector)

---

## 7. Risk Tiers

Every advisory has a tier. Tier drives UI treatment, permission gate, and verifier intensity.

| Tier | Meaning | Permission | Verifier intensity | UI behavior |
|---|---|---|---|---|
| **T1** | Info / lookup | All roles | H6 only (deterministic) | Quiet card, one-click approve |
| **T2** | Diagnostic / investigate | All roles | H4 always; H2 + H6 if safety-critical | Standard card, optional comment |
| **T3** | Actionable / write to BMS | Facility manager only | H2 + H4 + H6 all required | Confirm modal, audit log |

---

## 8. Verifier Gates

Three automated checks every advisory must pass before reaching operator.

### H2 — Claim Verification

LLM-as-judge: every factual claim in the advisory must be backed by an evidence_id in the ledger. Unsupported claims marked inline or blocked.

### H4 — Faithfulness

LLM-as-judge: does the advisory faithfully follow from the evidence, or does it make leaps not warranted by what was found? Catches the "5 operator_pattern entries" fabrication class (advisory says 5, evidence shows 1).

If contradictions found → regenerate with corrective prompt → re-verify (B5 fix: now re-checks after correction; if still unfaithful → abstain).

### H6 — Physics Verification

Deterministic check. Advisory recommendations evaluated against physics simulator. "Cool zone to -10°C" → physics rejects (freezing). Currently lightweight scan; full version regenerates on deviation.

### Abstention Gate

If 4 signals fall below thresholds → ARVIS publishes "insufficient evidence, abstaining" instead of advisory:
- `data_coverage` — % of expected points available
- `truth_score` — H2 + H4 aggregate
- `ml_fallback_ratio` — fraction of evidence from fallback heuristics
- `max_drift` — biggest physics deviation magnitude

---

## 9. Physics Simulator

Built to back Patent App 2 Claim 2 literally. 5 modules:

| Module | Math | Citations |
|---|---|---|
| **chiller.py** | DOE-2 bi-quadratic: CAP-FT, EIR-FT, EIR-FPLR + cubic COP fallback | ASHRAE 90.1-2022 Table 6.8.1-3; AHRI 550/590; Carrier 30XA datasheet |
| **cooling_coil.py** | NTU-effectiveness with counter-flow correlations | ASHRAE Handbook 2020 HVAC SE Ch 23 |
| **ahu.py** | Fan affinity (empirical exp 2.7), mixing box, coil, fan heat rise | ASHRAE Ch 21 §5 Table 2; AMCA 203 |
| **building.py** | Lumped-capacitance, forward-Euler, Biot validity | Incropera §5.1-5.2; CIBSE Guide A; ASHRAE Ch 18 |
| **loop.py** | Q = m·Cp·ΔT, pump affinity | ASHRAE Ch 22 |

Cross-validated against marina_physics.py reference (cubic COP, ±0.01 tolerance). AHRI 550/590 4-point test schedule + IPLV harmonic-mean.

Current calibration: IPLV deviates 37% from published target after correcting `design_cop` from incorrect 5.5 to actual 3.10. Forcing function tests (V2_TARGET 25%, V3_PRODUCTION 10%) xfail currently — calibration debt tracked.

---

## 10. Memory Layer — 7 Tiers

| Tier | Name | Lifespan | Content |
|---|---|---|---|
| **T1** | Working | Within-investigation | Active scratchpad during one Queen swarm cycle |
| **T2** | Episodic | Hours-days | Recent investigations, recent operator interactions |
| **T3** | Procedural | Months-years | Patterns, procedures, "this kind of fault → these tools" |
| **T4** | Semantic | Permanent | Equipment specs, building topology, standards |
| **T5** | Institutional | Permanent | Building-specific tribal knowledge, vendor relationships |
| **T6** | Identity | Permanent | ARVIS's role-specific personas, operator-specific tone |
| **T7** | Resolution | Permanent | What worked, what didn't — feedback loop |

**Current state**: T1-T2 functional. T3-T7 architecture present, **write side dead** — Memory_Agent only reads, no pattern_distiller writes skills. Marina runs show `max_relevance` always below citation threshold (0.34-0.59 vs 0.5+ needed). B8 blocker tracks fix.

---

## 11. LLM Routing (AWS Bedrock)

Different channels for different tasks. Cost + latency optimization.

| Channel | Model | Use |
|---|---|---|
| `synthesis` | `us.anthropic.claude-sonnet-4-6` | Advisory generation, complex reasoning |
| `chat` | `us.anthropic.claude-sonnet-4-6` | Operator-facing chat |
| `swarm` | `minimax.minimax-m2.5` | Agent-internal reasoning |
| `classify` | `us.amazon.nova-lite-v1:0` | Risk tier classification, depth planning (cheap) |
| `depth_plan` | `us.amazon.nova-lite-v1:0` | Per-agent investigation depth |
| `reflect` | `us.amazon.nova-lite-v1:0` | Memory recall reasoning |
| `tool` | `moonshotai.kimi-k2.5` | Tool-call decisions |
| `reasoning` | `moonshot.kimi-k2-thinking` | Heavy reasoning |
| `narrative` | `us.amazon.nova-lite-v1:0` | Briefings |
| `faithfulness` | `us.anthropic.claude-sonnet-4-6` | H4 verifier |
| `claim_verify` | `us.amazon.nova-lite-v1:0` (B6: was Sonnet, moved to Nova for latency) | H2 verifier |
| `audit` | `us.anthropic.claude-opus-4-6-v1` | Final judge in validation runs |

Region: `us-west-2`. All Bedrock-routed (legacy K2Think/Groq skipped).

---

## 12. Operating Modes

```
              SIM                PILOT                 PROD
              ───                ─────                 ────
Data source   personas           real BACnet           real BACnet
Clock         scrubbable         wall clock            wall clock
Building      marina_heights     real customer         real customer
BMS writes    none               none (shadow)         yes (gated)
Notifications none               none                  yes
Cockpit       visible            hidden                hidden
Mode badge    pill: "SIM"        pill: "PILOT"         pill: "LIVE"
```

**Shadow mode** (first 30 days of any PILOT): advisories render, operator can click approve/reject, but no BACnet writes, no notifications. Defense-in-depth: backend gates the writes regardless of UI state.

---

## 13. Compliance — GSAS Module

GSAS = Global Sustainability Assessment System (Qatar). GSAS-OP = Operations flavor, annual renewal. Categories: Energy, Water, Indoor Environment, Materials, Waste, Site, Management, Cultural & Economic Value. Star rating 1-6.

ARVIS computes continuous GSAS score from live data + operator inputs. Replaces annual binder-build scramble.

Capabilities (live):
- Continuous scoring across categories
- Deduction tracking with recovery actions
- Waste tracking
- Indoor environment monitoring
- Evidence collection (every advisory tagged to GSAS criteria)
- GSASgate-format export

Capabilities (partial):
- Survey administration (schema yes, UI no)
- Water tracking (sub-metering incomplete)
- Management category (PDF parse partial)

Capabilities (roadmap):
- Auditor mode (read-only external login)
- Predictive end-of-period score
- Peer-building benchmarking

---

## 14. Patent Strategy

Three applications in active prosecution.

### Patent App 1 — Multi-Signal Abstention Gate

Claim: a system that decides when an AI advisor refuses to answer vs answers with caveats vs answers confidently, based on multiple parallel signals (coverage, truth, ML-fallback ratio, drift) combined via configurable thresholds.

Patent counsel: under evaluation (Torrey Pines + Al Tamimi + Khurana & Khurana shortlist).

### Patent App 2 — Closed-Loop Physics Verification

Claim: an AI advisory system that verifies its own recommendations against a physics simulator built from equipment-class curves (DOE-2 bi-quadratic, NTU-effectiveness, fan affinity, lumped-capacitance), and refuses or regenerates when physical impossibility detected.

Claim 2 (literal): "the system comprises a thermodynamic simulation engine including chilled water plant curves, air handling unit thermal balance, cooling coil heat transfer, and building thermal mass."

**Backing built**: physics simulator (5 modules, ~2000 lines, tests pass v1).

### Patent App 3 — BFT Multi-Agent Consensus

Claim: a Byzantine Fault Tolerant consensus mechanism for graded AI agent votes (APPROVE / APPROVE_WITH_CONDITION / VETO / ABSTAIN) with confidence weighting and condition propagation, where transient agent failures map to ABSTAIN (not VETO) to prevent poisoning.

**B7 fix landed** wires this literally.

### Prior art landscape (2025-2026)

- Ex parte Desjardins (Sep 2025) — clarifies AI invention patentability
- Squires memoranda (Dec 2025) — USPTO guidance on AI/ML claims
- Recentive v. Fox (April 2025) — AI patent eligibility precedent
- Six Sigma Agent (Patel 2026) — competitor patent
- PBFT-Backed Semantic Voting (Bach 2025) — closest prior art for App 3
- AutoChemSchematic (May 2025) — adjacent

### CIIAA hygiene

"Hereby assigns" language confirmed in all employment/contractor agreements. SMED preparation underway.

---

## 15. Tech Stack

### Engine
- Python 3.11+
- AWS Bedrock (LLM routing, us-west-2)
- PostgreSQL + pgvector (memory)
- SQLite (audit / spans, dev)
- pgmpy (Bayesian network — dependency currently missing)
- NumPy + SciPy (physics)
- AsyncIO

### Frontend (planned)
- Next.js 14 App Router
- TypeScript
- Tailwind + shadcn/ui
- React Query (TanStack)
- Zustand
- ECharts (charts)
- SSE for streaming

### Auth (TBD)
- Cognito or Auth0 — decision pending

### Hosting
- Backend: AWS (EC2/ECS planned)
- Frontend: Vercel (planned)

### Observability
- audit_spans table (in-app audit trail)
- CloudWatch (planned)
- Sentry (planned)

---

## 16. Current State

### Marina S1 simulation pass rate

**3 of 9 phases passing (33%)**. Latest run: 2026-05-23 22:31.

| Phase | Test | Status | Score |
|---|---|---|---|
| S1_P0 | Write Gate + Baseline | PASS | (qualitative) |
| S1_P1 | Silent Observation (4 weeks) | PASS | 5.94/4.0 |
| S1_P2 | First Detections | PASS | 7.19/7.0 |
| S1_P3 | Regular Recommendations | FAIL | 4.14/7.0 |
| S1_P4 | Counterfactuals + Memory | FAIL | 3.93/7.0 |
| S1_P5 | Ghost Maintenance | FAIL | 5.17/8.0 |
| S1_P6 | Terminal Advisory (CH-4) | FAIL | 5.45/9.0 |
| S1_P6b | Knowledge Distillation | FAIL | 4.00/8.0 |
| S1_P7 | Institutional Memory | FAIL | 4.00/8.0 |

### Recent fixes landed (B1-B7 + C1 + B6)

- **B1** Timestamp isoformat fix (database.py:785)
- **B3** get_point_history schema alignment
- **B5** H4 faithfulness re-verification after correction
- **B7** BFT graceful Memory_Agent exclusion (ABSTAIN verdict added)
- **C1** OperatorActivityFeed for concurrent operator awareness
- **B6.1** Verifier pipelining (parallel H4 + H2)
- **B6.2** Haiku routing for verification channels (4-6x faster)
- **B6.3** BFT quorum timeout (bounds tail latency at 8s)

### Active blockers (B8-B14)

- **B8** Memory pipeline write-side dead — skillbook never authored, no pattern_distiller [P0, 2d]
- **B9** Autonomous monitoring loop missing — no proactive advisories [P0, 3d]
- **B10** Equipment runtime accumulator dead — runtime_hours never updated [P1, 1d]
- **B11** Schema violations on 5 tools — find_similar_skills, generate_briefing, check_goals, analyze_cascade, get_alarm_clusters [P0, 4h]
- **B12** pgmpy dependency missing — Bayesian RCA unavailable [P1, 30min]
- **B13** Synthesis read-only verb drift — sanitizer post-hoc instead of pre-LLM allowlist [P2, 4h]
- **B14** Marina probe coverage — no autonomous test phase, no skill recall test [P1, 2d]

**Forecast post-fix**: 7-8/9 pass rate (78-89%). Conservative target: 89% by Q2 close.

### What works well

- Read-only boundary enforced cleanly (Noor's write attempt declined on every run)
- Honest abstention when data missing
- Verifier gates catch fabrication (H4 found 6 contradictions in worst phase)
- Multi-agent vote graded correctly
- Physics simulator produces consistent COP within ±12% of observed
- Operator action attribution via C1 prevents phantom diagnoses
- SIM mode persona generator drives realistic scenarios

### What's broken

- Memory layer empty (write-side dead)
- Autonomous monitoring missing (everything user-driven)
- Several tool schemas violated
- Synthesis occasionally claims action verbs (sanitized post-hoc)
- pgmpy unavailable (Bayesian RCA degraded)
- Runtime hours never accumulate (B10)
- Building Patterns recall below citation threshold

---

## 17. What ARVIS Does NOT Do (Today)

- **Write to BACnet** (read-only by design for v1; planned but gated)
- **Replace the BMS** (sits beside, doesn't supplant)
- **Run fully autonomously** (every advisory presented for human decision)
- **Train its own models** (uses pre-built physics + LLM stack)
- **Provide HVAC training** to operators (focused on monitoring + recommendation)
- **Handle non-HVAC building systems** (no fire, security, elevator advisory)
- **Multi-tenant data sharing** (each building isolated)
- **Real-time control** (steady-state advisory, not closed-loop control)
- **Voice interface** (P2)
- **Mobile native app** (responsive web only)

---

## 18. Roadmap

### Q2 2026 (now)

- Fix Marina blockers B8-B14 → reach 90% pass rate
- Ship 2-min sales demo (Advisory Detail + Live View + Sim Cockpit + Shell + Operator Actions)
- Submit QSTP application (incubation track)
- Secure Marina LOI from building owner

### Q3 2026

- Marina pilot deployment (PILOT-shadow for 30 days, then graduate to PROD)
- GSAS module hardening (P0 + P1)
- Equipment Detail screen + physics overlay UI
- Memory Knowledge browser UI
- Operator UX studies at Marina

### Q4 2026

- Second pilot building (different vendor, different chiller class)
- Audit & Replay UI
- Exec KPI roll-up UI
- Notification system (in-app + email + SMS)
- Onboarding Wizard
- Patent App 1 + App 2 examination response

### Q1 2027

- Multi-building portfolio support
- Auditor mode for GSAS (read-only external)
- Predictive scoring
- Tasmu Smart Qatar partnership

### Q2 2027

- Series A close (target)
- 5-10 pilot buildings
- Patent App 3 examination
- Voice interface alpha

---

## 19. Operating Modes Glossary

| Mode | Where used | Data | Writes | Notifs | Cockpit |
|---|---|---|---|---|---|
| **SIM** | Sales demos, internal regression, training | Synthetic via persona generator | None | None | Visible |
| **PILOT-shadow** | First 30d of new pilot | Real BACnet | None | None | Hidden |
| **PILOT-live** | Pilot post-shadow graduation | Real BACnet | Gated | Yes | Hidden |
| **PROD** | Multi-tenant deployment | Real BACnet | Yes | Yes | Hidden |

---

## 20. Personas

### Internal (for FE design)

| Persona | Role | Frequency | Primary screen |
|---|---|---|---|
| **Bilal** | Building operator | Every 5-15 min | Live View + Advisory Detail |
| **Ahmed** | Facility manager | Weekly | Compliance + Energy Trends |
| **Noor** | Owner / executive | Quarterly | Exec KPI |
| **Layla** | Sustainability officer | Daily | GSAS Compliance |
| **Engineer / Auditor** | Debug, audit | As-needed | Audit & Replay |
| **Sales / Demo Pilot** | Customer demos | Per-meeting | Sim Cockpit + Advisory Detail |
| **GORD Auditor** (P2) | External annual audit | Yearly | Read-only auditor mode |

### SIM-mode synthetic (for Marina test)

Same personas above, generated by Persona_Agent. Each has a script style:
- Noor — skeptical, fast, technical depth
- Ahmed — pragmatic, budget-aware, weekly cadence
- Bilal — operator-focused, shift-handover style
- Maintenance vendor — ACME HVAC representative
- Tenant feedback — IAQ surveys

---

## 21. Glossary

### Domain
- **BMS** — Building Management System (Desigo CC, Niagara, etc.)
- **BACnet** — building protocol standard
- **Point** — single sensor/actuator reading
- **AHU** — Air Handling Unit
- **CHW** — Chilled Water
- **CHWST / CHWRT** — CHW Supply / Return Temp
- **CHWP** — CHW Pump
- **ECWT / LCWT** — Entering / Leaving Condenser Water Temp
- **OAT** — Outdoor Air Temp
- **MAT** — Mixed Air Temp
- **SAT** — Supply Air Temp
- **PLR** — Part Load Ratio (0-1)
- **COP** — Coefficient of Performance (cooling out / electric in)
- **IPLV** — Integrated Part Load Value (AHRI 550/590 harmonic mean)
- **TR** — Tons of Refrigeration (1 TR = 3.517 kW)
- **VAV** — Variable Air Volume box
- **VFD** — Variable Frequency Drive
- **OA** — Outdoor Air
- **MTBF** — Mean Time Between Failures
- **LPD** — Lighting Power Density
- **IAQ** — Indoor Air Quality
- **GSAS** — Global Sustainability Assessment System (Qatar)
- **GSAS-OP** — GSAS for Operations (annual)
- **GORD** — Gulf Organisation for Research and Development (GSAS authority)
- **GSASgate** — submission portal
- **ASHRAE** — American Society of Heating, Refrigerating and Air-Conditioning Engineers
- **AHRI** — Air-Conditioning, Heating, and Refrigeration Institute
- **TRL** — Technology Readiness Level (1-9)
- **QSTP** — Qatar Science & Technology Park

### ARVIS-specific
- **Advisory** — central artifact, AI recommendation
- **Risk Tier** — T1 / T2 / T3
- **Agent Trace** — reasoning record across agents
- **Evidence Ledger** — typed evidence per investigation
- **Verifier Gates** — H2 (claims) / H4 (faithfulness) / H6 (physics)
- **Abstention Gate** — multi-signal refusal threshold
- **InvestigationPlan** — typed plan with budget + audit trail
- **Call Sig** — deduplication key across agents
- **Skillbook** — accumulated patterns from past incidents
- **T1-T7** — memory tiers
- **Queen** — orchestrator
- **SwarmNode** — agent
- **BFT** — Byzantine Fault Tolerant consensus
- **Shadow Mode** — PILOT first 30d, advisories render no writes
- **OperatorActivityFeed** — C1 feature, ring buffer of recent operator actions

---

## 22. Document map

```
prd/
├── ARVIS_CONTEXT.md          ← you are here (master reference)
├── README.md                 (PRD directory index)
├── DEMO.md                   (2-min sales demo build spec)
├── _shared/
│   ├── arvis_primer.md       (30-sec primer for new joiners)
│   ├── design_system.md      (colors, typography, components)
│   ├── data_model.md         (common types)
│   └── api_contracts.md      (REST + SSE endpoints)
└── <feature>/
    ├── designer.md           (per-feature designer brief)
    └── engineer.md           (per-feature engineer brief)
```

13 features covered: shell, live_view, advisory_detail, equipment_detail, memory_knowledge, compliance_gsas, audit_replay, simulation_cockpit, onboarding_wizard, operator_actions, notifications, exec_kpi, settings_roles.

---

## 23. References (engineering)

### ASHRAE
- 90.1-2022 Table 6.8.1-3 — minimum chiller efficiency
- Handbook 2020 HVAC SE Ch 21 — fans + affinity laws
- Handbook 2020 HVAC SE Ch 22 — pumps
- Handbook 2020 HVAC SE Ch 23 — cooling coils (NTU-effectiveness)
- Handbook 2017 Fundamentals Ch 18 — non-residential loads

### Other standards
- AHRI 550/590 — chiller performance testing
- DOE Commercial Reference Buildings — Large Office archetype
- CIBSE Guide A — environmental design
- AMCA Publication 203 — fan field performance
- Incropera & DeWitt — Fundamentals of Heat and Mass Transfer (lumped capacitance)

### Equipment-specific
- Carrier 30XA datasheet — DOE-2 coefficients, AHRI ratings
- Siemens Desigo CC integration guide

### Patent precedent
- Ex parte Desjardins (Sep 2025)
- Squires memoranda (Dec 2025)
- Recentive v. Fox (April 2025)

---

## 24. People + Contacts

- **Project lead**: Arfaz Khan (arfazkhan@gmail.com)
- **Patent counsel**: shortlist evaluation (Torrey Pines, Al Tamimi, Khurana & Khurana)
- **Marina building owner**: LOI in progress
- **GORD relationship**: TBD
- **AWS support**: Bedrock us-west-2 region

---

## 25. Quick FAQ

**Q: Is ARVIS production-ready?**
A: No. Working prototype in simulation environment. 33% Marina pass rate today, targeting 90% before pilot.

**Q: Has ARVIS been deployed to a real building?**
A: No. Marina Heights is the first pilot target (Q3 2026).

**Q: Does ARVIS write to BMS?**
A: Not in v1. Read-only advisory. Write capability gated by approval, planned for v2.

**Q: How does ARVIS compare to BrainBox AI / Akila / Bluefield?**
A: Closed-loop control vendors. ARVIS is advisory-layer. Different category. Closer competitors are AI copilots (rare in HVAC).

**Q: Why advisory not control?**
A: Trust + liability. Control requires utility-grade reliability. Advisory builds operator trust + product evidence for years before assuming write authority.

**Q: What's the business model?**
A: SaaS per building per year. Tier by building size + features. Pilot pricing aggressive, retail TBD.

**Q: Why Doha first?**
A: Local network (founder), high cooling load makes ROI obvious, GSAS standardization helps, Qatar tech-friendly policy.

**Q: When series A?**
A: Q2 2027 target. Path: pilot Marina Q3 → second pilot Q4 → 5-10 pilots Q1-Q2 2027 → raise.

**Q: How much funded so far?**
A: Bootstrapped. QSTP application pending.

**Q: Patent status?**
A: 3 apps drafted. Counsel selection in progress. CIIAA hygiene confirmed. SMED preparation underway.

---

## Changelog

- v1 2026-05-23: initial — consolidates context from session history
