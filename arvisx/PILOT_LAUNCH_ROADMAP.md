# ArvisX — Pilot Launch Roadmap

*Goal: one real residential community live on ArvisX, proving measurable value to a
committee, producing a referenceable case study. This is a design-partner pilot, not a
public SaaS launch — momentum comes from a proven building, not a Product Hunt spike.*

**Definition of a successful pilot (the bar we're launching toward):**
- A real community commissioned to OPERATIONAL on real telemetry.
- The committee acts on ArvisX (work orders raised + closed) — *action rate ≥ 50%*.
- One quantified win in money or readiness (e.g. "caught pump failure ~QAR X early").
- A signed quote/testimonial → the asset that sells building #2.

---

## Honest starting position (what's ready vs not)

**Ready:** backend (≈50 endpoints, role auth, SSE), deterministic floor + agentic layer,
WhatsApp ops layer, economics (money framing), commissioning + readiness gate, deploy +
commissioning runbooks, Docker stack. Frontend in progress (parallel).

**Not ready / pilot risk:**
- **No real edge hardware/firmware** — MQTT protocol path proven (paho/amqtt), zero
  physical devices. **This is the #1 pilot blocker** — gate Phase 0 on it.
- **No ground-truth track record** — first real building IS the proof; manage expectations.
- **Single-tenant, single-process** — fine for one pilot, not for the 2nd building in parallel.

---

## Phase 0 — Pre-pilot foundation (Weeks -3 to 0)

| Workstream | Action | Owner | Done when |
|---|---|---|---|
| **Design partner** | Sign ONE community as design partner. Best fit: 100–300 units, *active committee*, recent water/generator pain, a WhatsApp-literate FM. Free pilot in exchange for data + testimonial. | You | Signed pilot agreement (scope, data consent, success criteria) |
| **Hardware** | Source the edge gateway + sensors for the pilot's real assets (water level, pump power/CT, generator fuel/battery, fire-pump). Decide: off-the-shelf IoT vs a hacked-up gateway. Get telemetry onto the broker. | You + hardware | Real readings landing in `AssetStore` for ≥80% of assets |
| **Deploy** | Stand up the stack (`DEPLOY.md`): broker + API + WhatsApp bot on a LAN host. Set `ARVISX_API_KEY`, owner account, tariff/currency. | You | `/heartbeat/status` green; bot answers "how is the building?" |
| **Baseline expectations** | Walk the committee through what ArvisX will/won't do (advisory, read-only, fire = visibility only). Set the success criteria *with them*. | You | Written, agreed success metrics |

**Gate:** do NOT start Phase 1 until real telemetry flows. Sim is for demo, not the pilot.

---

## Phase 1 — Commission + Learn (Weeks 1–4)

| Action | Owner | Metric |
|---|---|---|
| Run the commissioning wizard with the FM (`COMMISSIONING_RUNBOOK.md`): assets → signals → dependencies → learning. Target half a day. | FM + you | Building reaches LEARNING state |
| Resolve commissioning anomalies (`/check-anomalies`) — unmapped devices, untyped/unsignaled assets, bad sensors. | You | Zero unresolved warning-level anomalies |
| Let the confidence gate run (`/evaluate-readiness`). It extends learning until baselines are trustworthy — don't force it. | ArvisX | `approved: true` → auto OPERATIONAL |
| **Quiet period** — no alerts yet. Use it to validate sensor health + tune with the FM via validation questions. | FM | Baselines settled, FM trusts the data |

*Narrative for the committee this phase: "ArvisX is learning your building's normal — it
won't cry wolf on day one."*

---

## Phase 2 — Go live + prove value (Weeks 5–8)

| Action | Owner | Metric |
|---|---|---|
| Operational. Daily WhatsApp digest to owner/committee; sparse Critical/Warning alerts. | ArvisX | Digest delivered daily; alerts ≤ a few/week |
| FM acts on alerts → raises work orders (`/workorders/from-risk`), closes with cause (feeds skillbook). | FM | **Action rate ≥ 50%** of pushed alerts |
| Track the money line on every risk; capture the first "what is this costing us" committee moment. | You | 1 quantified avoided-cost / waste figure |
| Weekly check-in: review readiness trend (`/heartbeat/history`), false-alarm rate, FM friction. | You + FM | False-alarm rate trending down |

**Launch moment (internal, not public):** the first committee meeting where ArvisX's
number drives a budget decision. That's the real "launch" — capture it on video/quote.

---

## Phase 3 — Capture + compound (Weeks 9–12)

- **Case study** — quantified: assets monitored, alerts acted on, money framed, one
  caught-early incident. Committee quote. (This is the borrowed-credibility asset.)
- **Pilot readout deck** — for the committee (renew/expand) AND for prospect #2.
- **Reference call** — offer the design-partner FM/chairman as a reference.
- **Decide GA gaps** — from real friction, prioritize: multi-building tenancy, frontend
  polish, hardware kit standardization, watch resume-on-boot.

---

## Channels (ORB, adapted for a residential pilot)

| Type | Channel | Tactic |
|---|---|---|
| **Owned** | WhatsApp (committee + FM), the dashboard, daily digest | The product IS the channel — value shows up where they already live |
| **Owned** | Pilot readout deck + case study | Built from real pilot data, reused for sales |
| **Rented** | Property-management / facility-management networks, Qatar/India society WhatsApp groups, RWA/HOA associations | Warm intro to community #2 via the design partner |
| **Borrowed** | Design-partner testimonial + reference call | The single most powerful asset — one believable committee saying "it caught X" |

*Public channels (LinkedIn post, Product Hunt) come AFTER a proven building — a pilot with
no track record posted publicly is noise. Sequence: prove → case study → then amplify.*

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hardware slips | Phase 0 gate; start with the 2–3 highest-value assets (water tank, generator) not all 12 |
| Alert fatigue kills trust | Severity-gated + deduped + learning-gate already enforce sparseness; watch the false-alarm rate weekly |
| Committee expects an "OS" | Frame as advisory intelligence, not control; under-promise |
| First building has no incident to "catch" | Lead with the money/efficiency + preventive-maintenance value, not just failure-catching |
| Single-tenant limits | Don't sign building #2 onto the same instance until tenancy is built |

---

## Success metrics (the scoreboard)

- **Activation:** commissioned → operational (binary).
- **Trust:** false-alarm rate < 1 per 2 weeks; FM "do you trust it?" = yes.
- **Action rate:** ≥ 50% of pushed alerts acted on (the north star).
- **Value:** ≥ 1 quantified money/readiness win.
- **Expansion signal:** committee renews + agrees to be a reference.

---

*One sentence to anchor the whole pilot: prove ArvisX makes ONE community measurably
better-run and the committee trusts it — everything else (tenancy, UI, GA, building #2)
follows from that proof.*
