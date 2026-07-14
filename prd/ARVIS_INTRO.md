# ARVIS — Read This First

**Audience**: Anyone with zero prior context. Investor, journalist, new hire, QSTP reviewer, designer, engineer, friend of the founder.

**Reading time**: ~20 minutes if you read all of it. ~5 minutes if you skim the headings.

**Goal**: By the end of this document, you understand what ARVIS is, why it exists, how it works, what makes it different, and what stage it's at. No prior knowledge required.

---

## 1. What is ARVIS in one sentence?

ARVIS is an AI system that watches large commercial buildings — specifically their cooling and air-handling equipment — and tells building operators what's going wrong, why, and what to do about it.

Think of it as a senior engineer who never sleeps, never gets tired, and shows their work so the operator can trust them.

---

## 2. The 60-Second Picture

Office towers, malls, and hospitals run on massive cooling plants — giant chillers in the basement, pumps moving cold water through pipes, fans pushing conditioned air through ductwork. In Doha, where it gets to 50°C in summer, the air-conditioning system is the most expensive, most maintenance-intensive part of a building.

Today, **a human operator** sits in a control room and watches dashboards. When something goes wrong, an alarm beeps. The operator has to figure out what's happening — Is it a real problem or a false alarm? Which piece of equipment? What should I do? Should I call the vendor? — usually by looking through screens, checking sensor histories, and guessing from experience.

Most operators are good at this but **overwhelmed**. A typical large building generates 100+ alarms per day. Most are false. Many real problems hide inside the noise. Energy gets wasted. Equipment fails earlier than it should. Tenants complain. Compliance audits get failed.

**ARVIS sits beside the operator's existing control system.** It watches the same sensors the operator watches, but does it 24/7 without getting tired. When something looks off, ARVIS produces a small recommendation card on screen:

> "Chiller 4 is running 12% less efficiently than the physics says it should. Pattern matches refrigerant migration from past incident on March 4. Recommend scheduling vendor inspection within 48 hours. Without action: about $1,240 in extra energy over 30 days. With action: prevented. Confidence: 81%. Here's the evidence."

Then ARVIS shows its work. Which AI agents looked at this, what they voted, what evidence backs the claim, what physics says, what past incidents match. The operator decides whether to approve, reject, or snooze.

That's it. That's the product.

---

## 3. To understand ARVIS, first understand what's in a building

You probably don't think about how a 32-floor office tower stays cool. Here's the simplified picture for Marina Heights Tower in Doha — our first pilot customer:

### The chiller plant (in the basement)

- **4 chillers** — refrigerator-sized machines that produce cold water. Each one weighs more than a car and costs over $300,000. Each one cools ~2,800 kW worth of building. Brand: Carrier model 30XA.
- **Pumps** — push the cold water through pipes up the building.
- **Cooling towers** (on the roof) — dump waste heat to outside air.

### The air-handling system (per floor)

- **Air handlers (AHUs)** — 142 of them. Each one is a box that takes some fresh outside air, mixes it with returning air from the floor, passes the mix over a coil of cold water (which cools the air), and then a fan pushes the cool air into ductwork.
- **VAV boxes** — 800+. Little air boxes at each office area that fine-tune airflow per zone.
- **Sensors and valves** — thousands. Temperature, pressure, position, status.

### The control system (the "BMS")

- **BMS** = Building Management System. The existing software that controls everything. Marina Heights uses **Siemens Desigo CC**.
- The BMS reads **12,386 data points** every few seconds. (A "point" is a single number — temperature here, pressure there, motor running yes/no, etc.)
- The BMS can also write — turn things on, change setpoints. But it doesn't decide *what* to do. It just executes what the operator or the schedule says.

### The operator (the human)

- Sits in the BMS room. Watches screens. Reacts to alarms. Calls vendors. Walks the building. Hands over to next shift.

This is the world ARVIS plugs into.

---

## 4. What's wrong with how this works today?

Three big problems:

### Problem 1 — Information overload

The BMS shows everything but explains nothing. An operator looks at a wall of numbers, alarms, charts. When 14 alarms fire in a cascade, they have to mentally reconstruct what happened, in what order, what was probably the upstream cause, what the downstream symptoms are. This is hard. Humans are bad at it under stress.

### Problem 2 — Knowledge doesn't accumulate

The same fault might happen 3 times a year. Different operators handle it different ways. The successful resolution from March doesn't get written down anywhere the next operator can find it in November. Tribal knowledge walks out when staff leaves.

### Problem 3 — Energy and failures cost real money

A chiller running at 12% reduced efficiency for a month is tens of thousands of dollars in extra electricity. A predictable failure that surprises everyone costs $200,000 to fix instead of $5,000 to prevent. Compliance audits failed because the right evidence wasn't collected mean lost certification, lost premium rent.

Existing solutions don't really solve these:
- **Dashboards** — show more data. Operator still has to be the analyst.
- **Chatbots / copilots** — answer questions but make things up. No operator trusts them.
- **Closed vendor platforms** — proprietary, can't see how decisions are made, locked-in.
- **Predictive maintenance products** — single-model, single-vendor, often wrong, no transparency.

What's actually needed: an AI that **shows its reasoning**, **uses physics not just statistics**, **remembers what worked before**, and **gives the operator a real recommendation backed by evidence**. That's the ARVIS bet.

---

## 5. What does ARVIS actually do?

Three things, in this order:

### Thing 1 — Watch

ARVIS subscribes to the BMS's data feed. It receives every sensor reading, every alarm, every status change. It does this continuously, 24/7, across all 12,386 points at Marina Heights.

### Thing 2 — Think

When something interesting happens — an alarm fires, a sensor reading drifts, a pattern emerges over hours — ARVIS spins up an investigation. Behind the scenes, **multiple specialized AI agents** look at the data from different angles:

- The **Energy agent** asks: "Is this wasting electricity?"
- The **Maintenance agent** asks: "Is something about to fail?"
- The **Comfort agent** asks: "Are tenants going to complain?"
- The **Memory agent** asks: "Have we seen this before? What worked then?"
- The **Sensor Fusion agent** asks: "Are these readings even trustworthy?"
- And several more specialists.

Each agent uses its own toolkit — pulling sensor history, running physics simulations, recalling past incidents, querying alarm clusters. Each agent then votes: APPROVE the recommendation, APPROVE WITH CONDITION, VETO, or ABSTAIN (if it can't tell).

A coordinator called the **Queen** collects the votes, checks if there's consensus, runs three automated quality checks (more on these below), and synthesizes the final advisory.

### Thing 3 — Tell the operator

The advisory shows up as a card on the operator's screen. It has:

- **A risk tier** — T1 (just FYI), T2 (you should investigate this), T3 (we recommend changing a setpoint or dispatching maintenance)
- **A summary** — one sentence
- **A recommendation** — concrete action
- **A counterfactual** — "if you do this: outcome A. If you don't: outcome B." Numbers, dollars, kilowatt-hours.
- **The agent trace** — who voted what, with confidence percentages and reasoning
- **The evidence ledger** — every fact ARVIS used, with sources you can click to drill into
- **Verifier gates** — three pass/fail badges showing automated quality checks ran clean
- **Action buttons** — Approve, Reject, Snooze

The operator decides. ARVIS does NOT take action on its own.

---

## 6. Why this is hard — and what makes ARVIS different from chatbots

If you've used ChatGPT or Claude, you might think: "Couldn't a chatbot do this?"

Short answer: no.

Here's why building operators don't trust chatbots:

- Chatbots **make things up confidently**. They say "Chiller 4 has refrigerant migration" without knowing if Chiller 4 even exists in this building.
- Chatbots **can't see physics**. A chatbot might recommend cooling water to -5°C, which freezes the equipment.
- Chatbots **don't remember**. Every conversation starts fresh; the lesson from March is lost by November.
- Chatbots **can't explain why**. You ask "why?" and they generate plausible-sounding text, but it's not the actual reasoning.
- Chatbots **are easily wrong**. And when they're wrong, the operator can't tell.

ARVIS is **not a chatbot**. It's an **agentic system** built specifically to avoid these failures. The differences are concrete:

### The 6 Things ARVIS Does That Chatbots Can't

#### 1. Multi-agent debate (not single-model)

Instead of one AI making a recommendation, multiple specialist AIs debate and vote. The operator sees who voted what, with confidence levels and conditions. Like getting a panel of doctors instead of one. If three agents agree but one VETOes, that disagreement is visible — not hidden.

#### 2. Verifier gates

Every recommendation passes three automatic checks before reaching the operator:
- **Claim check** — every factual claim in the recommendation must be backed by an evidence record. No making things up.
- **Faithfulness check** — does the recommendation actually follow from the evidence, or did the AI make a leap? Catches the "5 historical incidents" claim when there's actually only 1.
- **Physics check** — does the recommendation respect physical laws? Catches "cool water to -5°C" before it ships.

If any gate fails, ARVIS regenerates or abstains. Operator never sees fabricated content.

#### 3. Physics simulation overlay

ARVIS doesn't just look at sensor data. It also runs a physics model of how each piece of equipment *should* be performing under current conditions. When the chiller's measured efficiency drops below what physics predicts, that gap IS the anomaly signature. Operators see both lines on the same chart: solid for observed, dotted for physics-predicted. The shaded gap is the story.

Patent claim: this is ARVIS's most defensible technical moat.

#### 4. Cross-incident memory

ARVIS remembers every past incident, every operator decision, every resolved fault. When something similar happens again, it surfaces the past resolution: "This looks like the issue from March 4. ACME HVAC topped up 8 lbs of refrigerant. Worked then." Operator decides whether to follow the same playbook.

#### 5. Counterfactual reasoning

Every recommendation shows side-by-side: *with action*, here's the predicted outcome; *without action*, here's what happens. Numbers, dollars, probability of failure, kilowatt-hours wasted. Operator sees the cost of inaction explicitly.

#### 6. Operator action attribution

If the apparent fault is actually because the operator changed a setpoint 4 minutes ago, ARVIS surfaces that fact in the advisory. "You changed Chiller 4 setpoint at 14:28. That's why these readings shifted." Prevents operators from chasing phantom faults of their own making.

These six things are visible on screen, in every advisory. Customer sees the moats; the demo is built around making them obvious.

---

## 7. How it actually works (without the jargon)

Picture five layers stacked:

```
┌─────────────────────────────────────────────────────┐
│  Layer 5: Operator's screen (Next.js web app)       │
│  What the human sees: schematic, advisories,        │
│  agent trace, evidence, approve/reject buttons      │
├─────────────────────────────────────────────────────┤
│  Layer 4: The Queen (coordinator)                   │
│  Routes incoming events to relevant agents,         │
│  collects votes, runs verifiers, synthesizes        │
├─────────────────────────────────────────────────────┤
│  Layer 3: Specialist agents (12 of them)            │
│  Energy, Maintenance, Comfort, Memory, etc.         │
│  Each has its own AI model + toolkit                │
├─────────────────────────────────────────────────────┤
│  Layer 2: Shared resources                          │
│  Physics simulator, memory database (past           │
│  incidents), evidence ledger, knowledge base        │
├─────────────────────────────────────────────────────┤
│  Layer 1: Connection to the building                │
│  BACnet adapter reads sensor data from the BMS      │
│  (or, in SIM mode, from a synthetic scenario)       │
└─────────────────────────────────────────────────────┘
```

When an alarm fires in the building, the data flows up: BACnet adapter → Queen → routed to relevant specialist agents → agents do their analysis → vote → Queen runs verifier gates → final advisory pushed up to the operator's screen.

When the operator clicks Approve / Reject, the data flows back down: button click → API → memory database records the outcome → ARVIS learns for next time.

That's the loop.

---

## 8. Three modes — same UI, different data source

ARVIS runs in three modes. The user interface is **identical** in all three. Only the data source differs:

### SIM (Simulation)

- Used for: sales demos, internal regression testing, training new operators
- Data: synthetic events generated by scripted scenarios
- Building: anything we want to simulate
- Writes: nothing real; just visible in UI
- Marker: gray "SIM" badge in top corner

### PILOT (Shadow)

- Used for: first 30 days of any new real building deployment
- Data: real BACnet from real BMS
- Building: real customer
- Writes: blocked. ARVIS makes recommendations, operator approves them, but no BMS changes happen. Notifications also suppressed.
- Marker: amber "PILOT — Shadow" badge

### PROD (Production)

- Used for: graduated pilots and rollouts
- Data: real BACnet
- Building: real customer
- Writes: enabled where permitted, gated by operator approval
- Notifications: active
- Marker: green "LIVE" badge

The genius of having three modes with one UI: customer demos show the same screens as production. There's no "demo theater" — what they see is what they get.

---

## 9. Who uses it

ARVIS targets five distinct user types:

### Building Operator

- Profile: 10+ years experience, sits at the BMS desk
- Frequency: every 5-15 minutes during shift
- Cares about: clear "do this, here's why" recommendations, audit trail to back up decisions
- Primary screen: **Live View** (home) + **Advisory Detail**

### Facility Manager

- Profile: runs the building, manages vendor relationships, reports to ownership
- Frequency: weekly check-in
- Cares about: trend reports, energy spending, compliance scores
- Primary screen: **Compliance** + **Energy trends**

### Owner / Executive

- Profile: owns or controls the building, quarterly review
- Cares about: dollar savings, asset value, ESG reporting, premium rent justification
- Primary screen: **Executive KPI roll-up**

### AI Engineer / Auditor

- Profile: ARVIS internal team, or customer's IT person during pilot
- Cares about: why did ARVIS say this? Debug.
- Primary screen: **Audit & Replay**

### Sales / Demo Pilot

- Profile: customer-facing, runs live demos
- Cares about: scripted scenarios that show off ARVIS's strengths
- Primary screen: **Simulation Cockpit**

---

## 10. A typical advisory walkthrough

To make this concrete, here's what happens when ARVIS catches a fault at Marina Heights.

**Time: 14:15 on a hot Tuesday afternoon. OAT 49°C.**

1. **14:15:32** — Air handler #7 sensor reports outdoor-air damper position dropped from 65% to 80%. (Sensor was already noisy in past.)
2. **14:15:35** — A few seconds later, the mixed-air temperature inside AHU-7 rises by 4°C.
3. **14:15:38** — Supply-air temperature starts climbing above setpoint.
4. **14:15:42** — Chilled-water valve at AHU-7 saturates at 100% (full open) trying to compensate.
5. **14:15:45** — Supply-air temp is now 2°C above target. Fan speed pinned at maximum VFD.
6. **14:15:48** — Alarm fires: "AHU-7 SAT deviation from setpoint."
7. **14:15:51** — 3 more cascade alarms fire as zones above AHU-7 detect they're too warm.

Without ARVIS: operator sees 4 alarms, opens 6 screens to figure out what's happening, calls vendor.

With ARVIS:

8. **14:15:53** — ARVIS's Queen receives the alarm cluster. Spins up an investigation.
9. **14:15:55** — Alarm_Agent identifies the 4 alarms as a cascade with AHU-7 as root. Maintenance_Agent pulls AHU-7's last 24h history. Memory_Agent searches past incidents. Comfort_Agent checks affected zones. Sensor_Fusion_Agent validates damper sensor reliability.
10. **14:16:08** — Agents finish reasoning. Vote tally:
    - Maintenance_Agent: APPROVE (0.86 confidence)
    - Energy_Agent: APPROVE_WITH_CONDITION (0.71) — "verify ambient not driving this"
    - Comfort_Agent: APPROVE (0.80)
    - Memory_Agent: ABSTAIN — transient model failure
11. **14:16:12** — Queen runs the three verifier gates:
    - Claim check ✓
    - Faithfulness check ✓ (caught one fabricated cluster reference, removed it)
    - Physics check ✓ (12.4% COP deviation, within warn band)
12. **14:16:14** — Advisory published.

Operator sees the card 14 seconds after the first cascade alarm. They click. Advisory Detail screen opens with:
- Summary
- Recommendation: schedule vendor inspection within 48h
- Counterfactual: $1,240 in 30 days if ignored, $0 with action
- Agent trace (4 votes)
- Verifier gates (3 green badges)
- Evidence ledger (6 chips, clickable)

Operator reads it in 30 seconds. Clicks Approve. Maintenance task created. End-to-end: 90 seconds from first alarm to closed-loop response.

That's ARVIS's value proposition rendered concretely.

---

## 11. The compliance angle — GSAS

In Qatar, large commercial buildings get annually rated for sustainability under **GSAS** (Global Sustainability Assessment System). It's like LEED in the US or BREEAM in the UK. Star rating 1 to 6, higher is better. Run by GORD (Gulf Organisation for Research and Development).

Every year, the sustainability officer at a building (Layla, in our personas) spends 3 months collecting evidence — energy meter reads, equipment logs, occupant surveys, policy documents — and submits to GORD for the annual audit. A 4-Star rating lets you charge premium rent, sign green leases, and meets the increasingly mandatory ESG requirements.

ARVIS has a dedicated **GSAS module** that computes the score continuously instead of annually:
- Every advisory ARVIS issues is auto-tagged to the relevant GSAS criterion
- Energy waste tracked daily against benchmarks
- Indoor environment monitored continuously
- Surveys triggered when needed
- Audit package generated with one click

For Doha buildings, this is a significant value-add. For other markets, the same architecture supports LEED / BREEAM / Estidama eventually.

---

## 12. What ARVIS is NOT

To prevent over-expectations:

### ARVIS does not control the building.

It's **advisory only** in version 1. The operator clicks Approve; the BMS does the work. ARVIS never reaches into the building and changes a setpoint autonomously. (Write capability is roadmap, gated by approval, planned for v2.)

### ARVIS does not replace the BMS.

It sits beside the existing control system. Siemens Desigo CC stays in place. ARVIS is the AI layer above it.

### ARVIS does not run unattended.

Every recommendation goes to a human. ARVIS doesn't take action on its own. (Notification systems wake the human if needed.)

### ARVIS does not train its own models from scratch.

Uses pre-built foundation models (Anthropic Claude, Amazon Nova, etc. via AWS Bedrock) and pre-published physics models (DOE-2, ASHRAE standards, AHRI). ARVIS's IP is in the **orchestration** — how these are combined, verified, and grounded in evidence. Not in inventing new ML algorithms.

### ARVIS does not handle non-HVAC systems (today).

No fire alarms. No security. No elevators. No lighting (much). Just HVAC: chillers, AHUs, pumps, fans, related equipment. (Other systems are roadmap.)

### ARVIS is not deployed at a real building yet.

Working prototype in simulation environment. Marina Heights is the first pilot target, Q3 2026.

---

## 13. Where things stand right now

To be totally honest about the stage:

### What's built and working

- The architecture: Queen + 12 specialist agents + verifier gates + evidence ledger — all coded, integrated, running
- Physics simulator: chiller, cooling coil, AHU, building thermal mass, hydraulic loop — built, tested, cross-validated against published references
- AWS Bedrock LLM routing across 12 model channels — working
- BACnet adapter — working for SIM, plumbed for PILOT
- Memory architecture (7 tiers) — built; only T1-T2 functioning, T3-T7 dormant pending write-side completion
- Simulation framework: drives synthetic scenarios through the engine for testing

### What's broken or partial

- Memory layer write side: ARVIS doesn't yet author skill entries from past incidents — the "write" half of the memory loop is incomplete (active fix in progress)
- Autonomous monitoring loop: today, advisories happen when the operator (or simulation) triggers them; planned autonomous "tick" agent that scans the building proactively isn't wired up yet
- Equipment runtime counters: not yet accumulating (database hook missing)
- Several tool response schemas: 5 tools return incomplete payloads — fixable in hours
- Bayesian network root cause analysis: dependency missing (`pip install pgmpy` fixes it)

### Test results

ARVIS runs a 9-phase regression test called "Marina S1" — simulates two weeks of building life and grades ARVIS on whether it makes good calls. **Current pass rate: 33% (3 of 9 phases passing).**

We know exactly what's wrong and why. We have a 7-blocker remediation list. **Target: 89% (8 of 9) by end of Q2 2026** before going to Marina pilot.

### Patents

Three patent applications drafted, in active prosecution:
1. **Multi-Signal Abstention Gate** — how ARVIS decides to refuse to answer
2. **Closed-Loop Physics Verification** — how ARVIS uses a physics simulator to verify its own recommendations
3. **BFT Multi-Agent Consensus** — how the graded voting with confidence and conditions handles agent failures

Patent counsel selection in progress (shortlist: US, Qatar, India firms).

---

## 14. What's coming next

### Q2 2026 (now)

- Fix the 7 remediation blockers → reach 90% pass rate
- Ship the 2-minute sales demo
- Submit QSTP application
- Sign Marina Heights pilot LOI

### Q3 2026

- Deploy at Marina Heights (PILOT shadow mode for 30 days, then graduate)
- Harden the GSAS module
- Ship operator UI screens beyond the demo (Equipment Detail, Memory browser)

### Q4 2026 - Q2 2027

- Second pilot building
- Audit & Replay, Notifications, Onboarding Wizard, Exec KPI screens
- Multi-building portfolio support
- Series A close (target Q2 2027)

---

## 15. Frequently Asked Questions

**Q: Is this just a wrapper around ChatGPT?**
A: No. ARVIS uses multiple AI models (Anthropic Claude, Amazon Nova, MoonShot Kimi, etc.) coordinated by an orchestrator that we built. The IP is in how they're combined: how agents vote, how recommendations are verified against physics, how evidence is tracked. A bare LLM would fail every operator trust test we apply.

**Q: Why advisory and not full control?**
A: Trust and liability. Direct control over critical building equipment requires utility-grade reliability — five 9s of uptime, formal verification, regulatory approval. Advisory builds operator trust + customer evidence over years, then transitions to write capability when both the technology and the customer are ready. Skipping that stage is how startups get sued.

**Q: How is this different from BrainBox AI / Akila / 75F / Bluefield?**
A: Those are closed-loop control vendors that take a portion of energy savings. ARVIS is an advisory layer for human operators. Different category, different sales motion. Closer competitors would be AI copilots in the HVAC space, which are rare.

**Q: Why Doha first?**
A: Founder is on the ground in Qatar; high cooling load makes ROI extremely visible; GSAS provides a standardized compliance story; Qatar government policy actively encourages building-tech innovation; QSTP funding ecosystem.

**Q: Is the simulation demo "fake"?**
A: No, if disclosed honestly. The simulation mode runs the **real ARVIS engine** against synthetic scenarios — it's not a scripted video. The architecture, agents, verifier gates, physics simulator — all real. Only the building events are scripted, and we show the "SIM" badge prominently to make this clear. Industry-standard practice for pre-pilot startups.

**Q: How much funding raised?**
A: Bootstrapped. QSTP application in progress. Series A target Q2 2027 after pilot evidence accumulates.

**Q: What's the business model?**
A: SaaS per building per year. Pricing tiered by building size and feature set. Pilot pricing aggressive (essentially at-cost). Production retail pricing TBD based on early pilot data.

**Q: Why should a building owner trust this?**
A: Three reasons: (1) Shadow mode for 30 days means zero risk during evaluation — ARVIS observes but doesn't act. (2) Every recommendation shows full reasoning and evidence — operator can override anything. (3) Verifier gates prevent the AI from fabricating, the most common reason operators dismiss AI tools. The trust story is the product.

**Q: Why hasn't someone done this already?**
A: Closed-loop control products exist (they trade transparency for "we do everything for you"). Advisory products exist as static dashboards (they trade decision-making for "you figure it out"). What's hard is doing both — being smart enough to actually recommend, transparent enough to be trusted. Solving that requires combining multi-agent systems, physics simulation, memory architecture, and verifier infrastructure — all simultaneously. The pieces existed individually; the integration didn't.

**Q: How big is the market?**
A: Globally, commercial HVAC operations + maintenance is ~$50B annual spend. Smart building / building analytics is ~$10B and growing 25%/yr. Doha alone has thousands of large commercial buildings. The first 100 buildings in MENA region is the realistic addressable wedge for years 1-3.

**Q: Can ARVIS be wrong?**
A: Yes. The verifier gates reduce hallucination, the physics simulator catches impossibilities, the multi-agent vote catches single-agent failures, the abstention gate refuses when data is insufficient. But ARVIS still makes mistakes — that's why every recommendation goes to a human, not directly to the equipment. The product is **decision support**, not decision automation.

**Q: What happens if ARVIS goes down?**
A: The BMS keeps running normally. ARVIS is a layer above; the underlying control system is independent. The operator loses ARVIS's recommendations during downtime but doesn't lose building functionality. Same as if a dashboard went offline.

**Q: Is the data secure / private?**
A: Yes — built that way from day one. Building data isolated per tenant. Cross-building learning happens only on patterns, not raw data. ARVIS doesn't see occupant identities. SOC 2 readiness planned for Series A.

---

## 16. Glossary

(Skip if you read straight through. Reference as needed.)

### Building / HVAC terms

- **HVAC** — Heating, Ventilation, Air Conditioning. The systems that keep buildings comfortable.
- **BMS** — Building Management System. The existing software that monitors and controls building equipment.
- **BACnet** — the industry standard protocol building equipment uses to communicate.
- **Chiller** — large machine that produces chilled water. Essentially a giant refrigerator.
- **AHU** — Air Handling Unit. Box that conditions air for a portion of the building.
- **VAV** — Variable Air Volume box. Local control of airflow per office area.
- **Coil** — heat exchanger where chilled water cools air (or hot water heats it).
- **Setpoint** — the target value an operator (or schedule) tells the system to maintain ("cool to 22°C").
- **OAT** — Outdoor Air Temperature.
- **CHW** — Chilled Water.
- **COP** — Coefficient of Performance — chiller efficiency, ratio of cooling output to electricity input.
- **PLR** — Part Load Ratio — how loaded a chiller is, 0 to 1.
- **MTBF** — Mean Time Between Failures — equipment reliability metric.
- **GSAS** — Qatar's annual building sustainability rating (1-6 stars).
- **GORD** — the authority that runs GSAS.

### AI / system terms

- **Advisory** — ARVIS's central output. A recommendation card.
- **Agent** — a specialized AI module with its own tools and area of expertise.
- **Queen** — the orchestrator that coordinates agents and runs verifier checks.
- **Vote** — each agent says APPROVE / APPROVE_WITH_CONDITION / VETO / ABSTAIN on a proposed advisory.
- **Verifier gates** — automated checks (Claim / Faithfulness / Physics) that every advisory must pass.
- **Abstention** — when ARVIS refuses to answer because data is insufficient. Better than fabrication.
- **Counterfactual** — predicted outcome with vs without taking the recommended action.
- **Evidence ledger** — record of every fact ARVIS used, with sources.
- **Memory tier** — different categories of stored knowledge (working memory through institutional knowledge).
- **Skillbook** — accumulated patterns from past incidents.
- **Mode** — SIM / PILOT / PROD.
- **Shadow mode** — PILOT first 30 days; ARVIS observes, recommends, but no writes.

### Business / patent terms

- **TRL** — Technology Readiness Level, 1 (idea) to 9 (deployed product). ARVIS is around TRL 5-6.
- **LOI** — Letter of Intent (from a building owner to pilot).
- **QSTP** — Qatar Science & Technology Park, the local innovation hub.
- **Tasmu** — Qatar's smart-city national program.
- **CIIAA** — Confidentiality, Invention Assignment Agreement (legal hygiene for IP ownership).
- **SMED** — Small and Micro-Enterprise Development (Qatar funding category).

---

## 17. Where to go next

Now that you have context:

- **Want the elevator pitch in 60 seconds?** Re-read Section 2.
- **Want to understand the technical architecture?** Read `prd/ARVIS_CONTEXT.md` (the deep version of this document, assumes you have context).
- **Want to design a screen?** Read `prd/<feature>/designer.md` for the feature you care about.
- **Want to build a screen?** Read `prd/<feature>/engineer.md`.
- **Want to ship the 2-minute sales demo?** Read `prd/DEMO.md`.
- **Want the API contracts?** Read `prd/_shared/api_contracts.md`.
- **Want the design system?** Read `prd/_shared/design_system.md`.

---

## 18. Contact

- **Founder / project lead**: Arfaz Khan — arfazkhan@gmail.com
- **Location**: Doha, Qatar
- **GitHub repo**: private; access by request
- **Pilot inquiries**: same email

---

## Changelog

- v1 2026-05-23: initial — written for zero-context readers
