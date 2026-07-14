# ARVIS — IP Filing Report v2

**Status:** Consolidated pre-filing strategic + technical specification for patent counsel
**Prepared:** 2026-05-21
**Codebase:** `commercial-bms` branch
**Scope:** Three US utility patent provisional filings + trade-secret register + 30-month execution roadmap

**Supersedes:** IP_FILING_REPORT.md (v1, 2026-05-21)

**Document structure:**
- Part I — Strategic Frame (2026 §101 landscape, filing sequencing, counsel selection)
- Part II — Patent Applications (3 apps, revised claims reflecting 2025-2026 prior art)
- Part III — Trade Secret Moat (12 assets + isolation protocols)
- Part IV — Execution (CIIAA hygiene, open-source audit, AI-tool security, SMED, 30-month roadmap)
- Appendices — Code citations, glossary, prior art reference table

---

# Part I — Strategic Frame

## 1. Executive Summary

ARVIS is a production-grade agentic AI advisory system for commercial Building Management Systems (BMS). Architectural review identified **three independently patentable inventions** plus **twelve trade-secret-worthy assets**. The 2026 US patent landscape under USPTO Director Squires provides a uniquely favorable window for AI software patents via the binding *Ex parte Desjardins* (Sep 2025) precedent.

Recommended action:
- **File three US provisional patents within 60 days** ($7-12K total via offshore drafting partnership)
- **Lock priority date** on the strongest novelty claims before any public disclosure
- **Hold sensitive domain encoding as trade secret** (prompts, equipment curves, GSAS algorithms)
- **Pivot Qatar commercial pilot into empirical-data generation** to support Subject Matter Eligibility Declarations (SMEDs) at non-provisional stage

Three patents designed as mutually reinforcing: each blocks a different competitor approach to AI-driven industrial advisory.

## 2. The 2026 USPTO Eligibility Landscape

### 2.1 Ex parte Desjardins (Sep 2025) — binding precedent

Appeals Review Panel (ARP) decision in Appeal No. 2024-000567, designated binding precedent for all examination and PTAB appeals. Key holding:

Under MPEP Step 2A Prong 2 (Integration into Practical Application), computing a mathematical algorithm becomes patent-eligible when applied to a concrete technological improvement — including improvements to **computational performance, system complexity, learning storage, data sets, or algorithmic structures**. Relies on Federal Circuit *Enfish, LLC v. Microsoft Corp.* lineage.

**Application to ARVIS:** all three patents target specific structural improvements to AI-system functioning (multi-signal abstention fusion, closed-loop physics verification, BFT consensus with graded votes) — not generic "LLM applied to BMS." This aligns with the safe harbor.

### 2.2 Squires Memoranda (Dec 4-5, 2025)

Two USPTO examination guideline memoranda issued by Director John Squires materially alter §101 drafting requirements:

- **Dec 4 memo:** examiners must apply "preponderance of evidence" standard (>50% probability) before issuing §101 rejection. Eliminates reflexive borderline rejections.
- **Dec 5 memo:** codifies the drafting formula:
  > **"Specification disclosed improvement + reflected in claims = Patent-Eligible"**
- Examiners cannot expand the "mental process" exception to limitations practically impossible for humans to perform mentally.
- Subject Matter Eligibility Declarations (SMEDs) under 37 C.F.R. § 1.132 formalized as voluntary mechanism.

**Drafting impact:** every novel mechanism in the ARVIS specification must appear *in the claims*, not buried in background or dependent claims.

### 2.3 Recentive Analytics v. Fox (Federal Circuit, April 2025) — defensive warning

Federal Circuit ruled that applying conventional ML to a new data environment is insufficient for patentability. AI inventions are not inherently abstract, but **"simply reciting use of machine learning to automate processes humans traditionally performed manually is insufficient."**

**ARVIS implication:** claims must center on **novel connective architectures** — closed-loop simulator constraint injection, fail-safe BFT routing, multi-signal abstention fusion — not "we apply LLMs to buildings."

### 2.4 USPTO 2025 Inventorship Guidance

Agentic AI systems cannot be listed as inventors. Patentability requires **significant human contribution to conception**. Mere AI operation or ownership is insufficient.

**Action required:** ARVIS engineering team must maintain rigorous, **timestamped documentation** proving human conception of:
- Multi-Signal Abstention Gate logic (fusion algorithm + ML-fallback→drift mapping)
- Physics verification simulator architecture (DOE-2 curves, NTU coupling, regen control flow)
- BFT consensus protocol (opposing-agent quorum, graded votes, fail-safe veto default)

Git history alone may not suffice — supplement with engineering design docs, whiteboard photos, design-review notes, dated email threads.

## 3. Filing Strategy at a Glance

| # | Application | Strength | Provisional Order | Estimated Cost (with offshore draft) |
|---|---|---|---|---|
| 1 | **Multi-Signal Abstention Gate** | HIGHEST | Week 1-2 | $2-3K |
| 2 | **Closed-Loop Physics Verification** | HIGH (after simulator build) | Week 3-4 (post-simulator) | $2-4K |
| 3 | **BFT Multi-Agent Consensus for Industrial Control** | HIGH (with revised differentiators) | Week 5-6 | $3-5K |
| | **Total provisional cost** | | | **$7-12K** |

### Jurisdiction sequencing

| Stage | Action | Timing | Estimated Cost |
|---|---|---|---|
| Priority lock | US provisional filings | Month 0-2 | $7-12K |
| GCC commercial protection | Qatar national filing (Al Tamimi) | Month 6-9 | $5-8K |
| Non-provisional decision | US conversion (each app) | Month 11-12 | $30-45K (3 apps) |
| International coverage | PCT filing | Month 11 | $30-50K |
| National phase entry | EU + UK + Singapore + Japan | Month 30 | $5-10K each |

Conservative US + Qatar + selective PCT total over 30 months: **$60-90K**.
Full international (US + EU + UK + Qatar + JP + SG): **$120-180K**.

### Critical pre-filing constraint

**No public disclosure** of these methods until provisional filed:
- No blog posts
- No conference talks
- No papers (arXiv, peer-reviewed)
- No customer demos without NDA
- No GitHub commits to public-facing repos describing the methods
- No tweet threads, podcasts, investor decks mentioning specifics

Any such disclosure creates §102(a)(1) prior art barring patentability. **Audit existing public materials (blog, conference history, social media) before filing.**

## 4. Counsel Selection — Three-Tier Structure

### 4.1 US Lead Counsel

**Primary recommendation: Torrey Pines Law Group**
- Chambers Spotlight 2025 leading California IP firm
- Deep history in AI patent prosecution: unsupervised ML, neural networks, deep learning CV, SaMD clearances
- FDA-regulated industrial-control experience translates to safety-critical BMS context
- Strategic governance fit for complex AI claims

**Alternate: Seed IP** (boutique)
- Specializes in software, ML, knowledge systems
- Forward-looking on telecommunications, embedded systems, automated inference
- Strong USPTO examiner-communication track record

Engagement model: lead counsel provides strategic governance, claim review, prosecution. Offshore drafting partner does heavy lifting.

### 4.2 GCC Regional Counsel

**Definitive recommendation: Al Tamimi & Company — Innovation, Patents & Industrial Property (3IP) practice**

Lead partner: **Ahmad Saleh**
- Canadian-trained, electrical & computer engineer
- MIT Sloan Executive Program: AI for Business Strategies
- 15+ years managing advanced tech portfolios across UAE, Qatar, broader GCC
- Dual legal + engineering competency ensures US-prosecution-to-GCC-enforcement alignment

Alternative regional firms (Jahcoip, Abu Naja) are competent for trademarks/registrations but lack AI-specific engineering depth.

Engagement timing: Month 6-9, parallel to US prosecution and aligned with Qatar pilot.

### 4.3 Offshore Drafting Partner

**Primary recommendation: Khurana & Khurana (K&K) / IIPRD**

- 330+ professionals; Chambers and Legal 500 ranked
- Integrated patent-prosecution + search-analytics workflow (sister firm IIPRD)
- IIPRD US client representation office staffed by US-EP-trained attorneys
- Equipped for dense algorithmic claim drafting on Abstention Gate, Physics, BFT applications

Engagement model: K&K drafts under US lead counsel supervision. Reduces per-application cost by 50-70%. US lead counsel reviews, finalizes, files.

Alternative options (Anand & Anand, Lakshmikumaran & Sridharan) excel at litigation but lack the integrated drafting + analytics wing K&K offers.

---

# Part II — Patent Applications

---

# Application 1 — Multi-Signal Abstention Gate for Agentic AI Systems

## Technical Field

Artificial intelligence safety, autonomous decision systems, large-language-model (LLM) advisory systems, calibrated uncertainty in safety-critical industrial control, MLOps drift detection.

## Problem Solved

LLM-driven advisory systems face a binary failure mode: either they answer every query (hallucinating when blind) or refuse on single-threshold confidence (refusal cascade). Industrial deployments require **calibrated abstention** — recognition of *when not to advise* based on multiple orthogonal signals.

Existing approaches:
1. Single-threshold confidence gates — brittle; one signal type dominates
2. RLHF refusal training — generic, not domain-specific, no lineage trace
3. Run without abstention — hallucinates under data gaps
4. Verbalized uncertainty prompting — empirically poor calibration, stochastic

None integrate **data coverage + verification score + ML availability + model drift** into a single fused decision with structured machine-readable reason-code output.

## 2025-2026 Prior Art Landscape

| Reference | Mechanism | Why Not Anticipating |
|---|---|---|
| MM-AQA Benchmark (April 2026) | Multimodal "verify-then-abstain" with generic thresholds | Benchmark, not deterministic external-ledger fusion gate |
| LLM Lens (April 2026) | Distillation of grounding signals into transformer hidden states | Internal hidden-state probing, not external evidence ledger |
| Verbalized Uncertainty methods (multiple) | LLM self-reports confidence to gate refusal | Stochastic; pure self-critique unreliable |
| Military AI Drift Detection (IEEE) | Concept drift fusion with human-in-loop for YOLO object detection | Treats model unavailability and concept drift as separate; no LLM advisory integration |
| AbstentionBench (OpenReview) | Evaluation framework for refusal behavior | Benchmark, not architecture |

**Differentiator that survives novelty search:** ML-fallback evidence deterministically mapped to `drift_score = 1.0`, unifying "unmeasured" and "unhealthy" through external evidence-ledger lineage. No public prior art performs this specific fusion.

## Solution

A multi-signal abstention gate that fuses four orthogonal signals:

1. **Data coverage** — fraction of investigation-plan tasks with associated evidence entries
2. **Verification (truth) score** — verifier score on draft advisory
3. **ML fallback ratio** — fraction of evidence entries with `is_ml_fallback=True`
4. **Maximum drift score** — highest observed drift across active ML models, **with ML-fallback evidence contributing drift=1.0**

Gate fires under any condition:
- `coverage < 0.3 AND truth_score < 0.8` (data gap + uncertain verification)
- `ml_fallback_ratio > 0.5` (majority of ML evidence is fallback)
- `max_drift > 0.7` (any active model is stale)

On fire, system emits structured abstention output with machine-readable reason code (`data_gap | ml_fallback | drift_stale`), distinct from advisory output, carrying lineage trace to contributing evidence IDs and model IDs.

## Independent Claims (drafting language)

**Claim 1.** A computer-implemented method for calibrated abstention in an artificial-intelligence advisory system, comprising:
- (a) maintaining an evidence ledger of tool-result and document-chunk entries associated with an active investigation, each entry carrying provenance metadata including a source-tool identifier and a machine-learning-fallback flag;
- (b) computing a data-coverage score as the fraction of investigation-plan tasks having at least one associated evidence entry;
- (c) computing an ML-fallback-ratio as the fraction of evidence entries having the machine-learning-fallback flag set true;
- (d) computing a maximum-drift score across all evidence entries, **wherein evidence entries having the machine-learning-fallback flag set true contribute a drift value of 1.0 regardless of any explicit drift measurement**;
- (e) applying a fused abstention rule that emits an abstention signal when any of the following conditions hold: (i) the data-coverage score is below a first threshold and a verification score for a draft advisory is below a second threshold; (ii) the ML-fallback-ratio exceeds a third threshold; (iii) the maximum-drift score exceeds a fourth threshold;
- (f) upon emitting the abstention signal, producing a structured abstention output comprising (i) a machine-readable reason-code identifying which condition triggered abstention and (ii) a lineage trace referencing the contributing evidence identifiers and contributing machine-learning-model identifiers.

**Claim 2.** The method of Claim 1, wherein the machine-learning-fallback flag is set responsive to a tool handler receiving a structured "ML unavailable" sentinel from a downstream model facade indicating one of: (a) required model library not loaded, (b) trained model artifact unavailable, (c) inference service exception, said sentinel carrying a structured reason field distinguishing among said conditions.

**Claim 3.** The method of Claim 1, further comprising: continuing investigation execution under the abstention signal up to a budget limit, but substituting the draft advisory output with the structured abstention output before delivery to an operator interface.

**Claim 4.** The method of Claim 1, wherein the four thresholds are independently configurable, and the rule is monotonic such that tightening any single threshold cannot cause abstention to *not* fire when a looser threshold would.

**Claim 5.** The method of Claim 1, wherein the structured abstention output is rendered to an operator-facing user interface with a machine-readable severity tag enabling downstream telemetry classification, while the underlying advisory generation pipeline continues to record completed investigation tasks to the evidence ledger.

**Claim 6.** A system comprising at least one processor and a non-transitory computer-readable medium storing instructions which, when executed, cause the processor to perform the method of any of Claims 1-5.

**Claim 7.** A non-transitory computer-readable storage medium containing instructions which, when executed by a processor, cause the processor to perform the method of any of Claims 1-5.

## Code Mapping

| Claim Element | File:line |
|---|---|
| Evidence ledger with provenance | `arvis_core/evidence.py:Evidence`, `:EvidenceLedger` |
| ML-fallback flag | `arvis_core/evidence.py` — `is_ml_fallback` attribute |
| Coverage computation | `arvis_core/plan.py:219 coverage` property |
| Fallback ratio computation | `agent_commercial/bms_llm_agent.py:1152-1158` |
| **Maximum drift w/ fallback→1.0 mapping (Claim 1(d))** | `agent_commercial/bms_llm_agent.py:1161-1170` |
| Fused abstention rule | `agent_commercial/bms_llm_agent.py:1173-1180` |
| Structured ML_UNAVAILABLE sentinel | `agent_commercial/tools/handlers/ml.py:67-75`, `arvis_core/ml_facade.py:106+` |
| Reason-code in abstention output | `agent_commercial/bms_llm_agent.py:1175-1180` |
| Lineage trace via evidence_ids | `arvis_core/plan.py:audit_trail`, `arvis_core/evidence.py:Evidence.id` |

## Prior Art Defense (Hierarchical)

- **vs Single-threshold confidence gates**: Claim 1 requires multi-signal fusion (4 distinct signals); single-threshold is not anticipating.
- **vs RLHF refusal**: trained behavior, not deterministic external-ledger gate; produces text refusal, not machine-readable reason-code.
- **vs MM-AQA**: benchmark, not architecture; lacks Claim 1(d) fallback→drift mapping.
- **vs LLM Lens**: internal hidden-state probing; Claim 1 requires external evidence ledger.
- **vs MLOps drift monitoring**: standalone; lacks coupling to agent abstention gate via structured fallback evidence.
- **vs Verbalized Uncertainty**: pure LLM self-critique; Claim 1 requires deterministic code-enforced fusion.

**Key differentiator:** Claim 1(d) — ML-fallback-as-max-drift mapping. No public prior art performs this unification. This is the strongest defensive claim element.

## Why This Filing Is Highest Priority

- Strongest novelty hook (no clear prior art on Claim 1(d) mapping)
- Broadest applicability (any safety-critical agentic AI deployment, not just BMS)
- Cross-domain defensibility (medical advisory, industrial control, autonomous systems, financial advisory)
- Clean code mapping (claims map directly to identifiable code blocks)
- No build dependency — file immediately

---

# Application 2 — Closed-Loop Physics Verification System for Generative Building Operations Advisories

## Technical Field

Industrial control systems, thermodynamic modeling, generative AI output verification, building energy management, safety-guarded automation, real-time operational advisory systems.

## Problem Solved

LLMs generate fluent natural-language recommendations and identify patterns but cannot reliably perform thermodynamic mathematics within their context windows (Wang et al., 2025). They frequently suggest physically impossible operational changes (chiller setpoints violating second law of thermodynamics, mass-balance-violating air flows, simultaneous heating + cooling, COP outside physically achievable bounds).

Existing approaches:
1. PLC-level mechanical safeties (freeze-stats, high-pressure cutouts) — hardware retroactive
2. Schema validation (JSON parse, regex) — structural only
3. Generic LLM output filtering — no physical model
4. Pure LLM self-critique — same hallucination vulnerability as generation

None wrap a non-deterministic generative model in a **deterministic thermodynamic constraint layer** with closed-loop regeneration and bounded abstention.

## 2025-2026 Prior Art Landscape

| Reference | Mechanism | Why Not Anticipating |
|---|---|---|
| AutoChemSchematic AI (May 2025) | Closed-loop, physics-aware agentic framework integrating small language models for chemical process diagram generation | Operates **offline for static PFD/PID generation**; not real-time operational advisory on live industrial assets |
| SimuPhy (2025) | Vision-language closed-loop verification evaluating physical-law simulated rollouts based on generated code | Focuses on educational video generation + code validation; lacks industrial equipment bounds integration |
| PHYSGYM (2025) | Simulation platform benchmarking LLM scientific reasoning via interactive physics environments | Evaluation benchmark for scientific discovery, not deterministic safety constraint for live control |
| Using LLMs for Thermodynamic Problems (Wang et al. 2025, arXiv) | Documents LLM analytical-physics limitations | Establishes problem; provides no closed-loop verification solution |

**Differentiator that survives novelty search:** Real-time operational constraint on live industrial assets with closed-loop regen-or-abstain — distinct from AutoChemSchematic's offline diagram generation, SimuPhy's video/code evaluation, and PHYSGYM's benchmark posture.

## Solution

Closed-loop verification system that intercepts LLM advisory output, extracts physical parameters, simulates against localized deterministic thermodynamic engine, and either passes, regenerates, or hard-abstains.

System architecture:

```
[LLM Synthesis] → [Advisory Parameter Extractor] → [Localized Physics Simulator]
                                                          │
                                              ┌───────────┴───────────┐
                                              ▼                       ▼
                                       [Validation Pass]        [Violation Ledger]
                                              │                       │
                                              ▼                       ▼
                                     [Active-to-Passive       [Constraint-Injection
                                      Verb Sanitization]       Regeneration Prompt]
                                              │                       │
                                              ▼                       ▼
                                       [Deliver to FM]         [LLM Regenerate]
                                                                      │
                                                                ┌─────┴─────┐
                                                                ▼           ▼
                                                            [Re-verify]  [Hard Abstain
                                                                          structured]
```

Thermodynamic simulation engine comprises:
- **Chiller capacity-and-efficiency model** parameterized by DOE-2 bi-quadratic CAP-FT and EIR-FT curves, per equipment (e.g., Carrier 30XA coefficients)
- **Cooling-coil heat-transfer model** using NTU-effectiveness method (ASHRAE standard)
- **Building thermal-mass model** using lumped-capacitance forward-Euler prediction
- **Chilled-water hydraulic model** relating flow, temperature differential, pumping power

Simulator outputs (predicted SAT, COP, energy, zone temperature) validated against:
- Physics bounds dictionary
- Equipment operating envelopes from manufacturer specifications and ASHRAE standards
- Energy conservation (load ≤ available capacity × n_chillers × tolerance)
- Causal-chain hop count (over-reasoned LLM explanation detection)

On violation: structured `ViolationLedger` compiled with per-violation code, severity, expected vs cited values, component, and law-invoked. Ledger injected into regeneration prompt as **mandatory constraints**. Regenerated output re-verified. On second failure, system hard-abstains with structured fallback advisory.

Final **active-to-passive verb transformation** scans synthesized advisory and replaces active-execution verbs (e.g., "submitted", "adjusted", "shut down", "restarted") with passive advisory phrases (e.g., "recommend submitting", "recommend adjusting") — enforcing read-only operational stance via **three independent layers**: system-prompt rule + deterministic verb-map substitution + post-generation regex scan.

## Independent Claims

**Claim 1.** A computer-implemented method for verifying generative-AI advisories against thermodynamic constraints in **real-time operational control** of live industrial assets, comprising:
- (a) receiving a structured advisory output from a generative language model proposing one or more operational changes to a live industrial system;
- (b) parsing the advisory to extract proposed physical parameters including setpoints, flow rates, and equipment states;
- (c) feeding the extracted parameters into a localized deterministic thermodynamic simulation engine, said engine comprising at least: (i) a chiller capacity-and-efficiency model parameterized by bi-quadratic temperature-dependent curves of DOE-2 form, (ii) a cooling-coil heat-transfer model using the NTU-effectiveness method, (iii) a building thermal-mass lumped-capacitance model with forward-Euler step prediction, and (iv) a chilled-water flow-vs-temperature-differential hydraulic model;
- (d) computing predicted equipment-output values from the simulation and comparing each to (i) absolute physics bounds and (ii) equipment manufacturer envelopes loaded from a per-equipment configuration registry;
- (e) generating a structured violation ledger containing per-violation entries identifying code, severity, expected and cited values, component identifier, and physical law invoked;
- (f) responsive to the violation ledger containing one or more hard-severity violations: (i) compiling the ledger into a constraint-injection prompt, (ii) submitting the prompt with the original advisory to a generative model for regeneration, (iii) re-verifying the regenerated output through steps (b)-(e);
- (g) responsive to the regenerated output also containing hard-severity violations: emitting a structured fallback advisory comprising a system-notice severity level and a retry recommendation, without delivering the unverified advisory text to the operator;
- (h) responsive to the verification passing: scanning the verified advisory for active-execution verbs and replacing each with a corresponding passive advisory phrase via a deterministic verb-substitution mapping before delivery.

**Claim 2.** The method of Claim 1, wherein the chiller efficiency model comprises a DOE-2-form bi-quadratic capacity-as-function-of-temperature (CAP-FT) curve and a bi-quadratic energy-input-ratio-as-function-of-temperature (EIR-FT) curve, with coefficients loaded from a per-equipment configuration registry indexed by equipment manufacturer and model number.

**Claim 3.** The method of Claim 1, wherein the violation ledger structure further comprises a `law_invoked` field tagging each violation with the underlying physical principle, said tags drawn from at least: energy conservation, chiller lift envelope, cooling-coil NTU capacity, mass balance, causal-chain hop bound.

**Claim 4.** The method of Claim 1, wherein the regeneration step (f) is bounded to a single regeneration attempt before progressing to step (g), thereby bounding LLM cost and preventing infinite regeneration loops.

**Claim 5.** The method of Claim 1, wherein step (h) is performed in addition to two independent enforcement layers: (i) a system-prompt rule instructing the generative model to use advisory language, and (ii) a regex-based post-generation scan, providing three-layer defense against active-execution language leakage.

**Claim 6.** The method of Claim 1, wherein the simulation engine outputs are registered as evidence entries in an investigation-evidence ledger and the regenerated advisory must cite numerical values from said ledger, said requirement enforced by a downstream evidence-grounding verifier.

**Claim 7.** The method of Claim 1, wherein the simulation engine operates in a quasi-steady-state mode returning predictions in under 100 milliseconds per advisory check, enabling real-time interposition between generative model output and operator delivery without introducing perceptible latency.

**Claim 8.** A system comprising at least one processor and a non-transitory computer-readable medium storing instructions which, when executed, perform the method of any of Claims 1-7.

**Claim 9.** A non-transitory computer-readable storage medium containing instructions which, when executed by a processor, perform the method of any of Claims 1-7.

## Pre-Filing Build Requirement (Critical)

🔴 **Claim 1(c) requires the simulator to actually exist.**

Current `PhysicsVerifier` (`agent_commercial/verifiers/physics.py`) implements bounds checking + simple relations — not full thermodynamic simulation matching Claim 1(c)(i)-(iv).

**Build the simulator before filing** (estimated 2 weeks, one engineer) or Claim 1(c) faces a fatal 35 U.S.C. § 112 written description rejection. The code must enable a person of ordinary skill in the art to make and use the claimed simulator.

Required new code (see separate Simulator Build Plan):
- `agent_commercial/verifiers/simulator/engine.py` (orchestrator)
- `agent_commercial/verifiers/simulator/chiller.py` (DOE-2 curves)
- `agent_commercial/verifiers/simulator/cooling_coil.py` (NTU-effectiveness)
- `agent_commercial/verifiers/simulator/ahu.py` (AHU steady-state balance)
- `agent_commercial/verifiers/simulator/building.py` (lumped thermal mass)
- `agent_commercial/verifiers/simulator/loop.py` (chilled-water hydraulics)
- `agent_commercial/verifiers/violations.py` (`ViolationLedger`, `PhysicalViolation`)
- `data/equipment_curves/carrier_30xa_curves.yaml` (Carrier 30XA coefficients sourced from manufacturer or AHRI database)
- `data/buildings/marina_heights.yaml` (per-building parameters)

## Code Mapping (Existing Components)

| Claim Element | File:line |
|---|---|
| Closed-loop regen-or-abstain control flow | `arvis_core/swarm/queen.py:405-466` |
| Constraint-injection prompt | `arvis_core/swarm/queen.py:413-419` |
| Hard-abstain fallback JSON | `arvis_core/swarm/queen.py:435-448` |
| Structured violation list (current bounds form) | `agent_commercial/verifiers/physics.py:VerificationResult` |
| Verb-substitution map | `arvis_core/swarm/queen.py:34-51 _VERB_REPLACEMENTS` |
| Deterministic verb enforcement | `arvis_core/swarm/queen.py:671-690 _enforce_read_only` |
| Causal chain hop validation | `agent_commercial/verifiers/physics.py:80-98 verify_causal_chain` |
| Three-layer read-only enforcement | system_prompt at `queen.py:402-406` + verb map (above) + regex (above) |

## Prior Art Defense

- **vs AutoChemSchematic AI**: offline static-diagram generation (PFDs/PIDs); Claim 1 limits to "real-time operational control of live industrial assets" — explicitly distinct domain and timing.
- **vs SimuPhy**: educational-video VLM rollout; not real-time industrial constraint.
- **vs PHYSGYM**: scientific-discovery benchmark; Claim 1 is industrial safety-constraint pipeline, not evaluation.
- **vs PLC mechanical safeties**: hardware retroactive; Claim 1 is software-interposed between LLM and operator.
- **vs JSON schema validation**: structural only; Claim 1 requires thermodynamic simulation engine.
- **vs LLM self-critique**: same hallucination vector; Claim 1 requires deterministic external simulator.

**Key differentiators:** (1) real-time operational advisory context (not offline design); (2) closed-loop regen-or-abstain with bounded retry (Claim 4); (3) three-layer read-only enforcement (Claim 5); (4) sub-100ms quasi-steady-state operation (Claim 7).

## Why This Filing Is Priority 2

- Strong novelty post-simulator-build
- Industrial-domain anchoring (helps §101 defense)
- High commercial value (any AI BMS competitor must invent around this)
- **Blocked until simulator built**: 2 weeks of implementation work required first

---

# Application 3 — Byzantine Fault-Tolerant Multi-Agent Consensus for Industrial Asset Control

## Technical Field

Multi-agent artificial intelligence systems, decentralized consensus protocols, large-language-model orchestration, safety-guarded industrial automation, fault-tolerant distributed systems, real-time operational advisory.

## Problem Solved

General-purpose LLM controllers applied to industrial assets represent single points of failure. A single API exception or hallucination → undefined dangerous system state. Existing approaches:

- **LangChain / LangGraph linear chains** — no fault tolerance, single-LLM crash bricks runtime
- **Classical BFT (Paxos, Raft, PBFT)** — state-machine replication, binary votes, no LLM/domain integration
- **Multi-LLM majority voting** — no opposing-goal structure, no conditional approval, no veto-driven re-routing
- **Static rule-based BMS alarms** — no learning, no LLM, no consensus

None implement **fault-tolerant consensus voting coupled to opposing physical/operational constraints** in industrial environments with graded vote semantics and condition propagation.

## 2025-2026 Prior Art Landscape

🔴 **Critical published prior art identified** (both predate ARVIS filing):

### Six Sigma Agent (Patel, January 2026)

Architecture: micro-agent sampling with `n` parallel diverse LLMs, consensus voting via output clustering, dynamic scaling up to 13 parallel agents. Mathematical demonstration: sampling `n` outputs with base error `p` achieves system error `O(p^⌈n/2⌉)`. Achieves 3.4 DPMO (Six Sigma reliability), 14,700× single-agent improvement.

**Why this is a hazard:** broad claim on "BFT for LLM agents using consensus voting" is **§102 anticipated** by Six Sigma.

**ARVIS differentiator:** Six Sigma uses *probabilistic redundancy* — same query to *identical* models, majority vote. ARVIS uses *opposing-priority* domain specialization — agents represent *opposing* operational goals (energy vs comfort vs safety), enabling adversarial evaluation rather than redundancy-based error dilution.

### PBFT-Backed Semantic Voting for Multi-Agent Memory Pruning (Bach, June 2025)

Architecture: PBFT consensus over gRPC for distributed memory pruning. DistilBERT assesses semantic relevance. Tolerates `f` malicious nodes in `N≥3f+1` system. 52% memory reduction, 92% PBFT success rate under simulated Byzantine conditions.

**Why this is a hazard:** broad claim on "PBFT applied to LLM agent systems" is **§102 anticipated** by Bach.

**ARVIS differentiator:** Bach's protocol is binary (retain/forget) over shared memory. ARVIS has **graded votes** (`APPROVE / APPROVE_WITH_CONDITION / VETO`) over **operational proposals**, with condition extraction and **mandatory injection into downstream synthesis**, and veto-constraint re-routing to disjoint alternate nodes.

### Architecture comparison (must appear in spec)

| Feature | ARVIS | Six Sigma Agent | PBFT-Semantic Voting |
|---|---|---|---|
| Consensus objective | Resolve opposing domain goals | Stochastic error reduction via redundant sampling | Distributed memory sync / pruning |
| Voting semantics | Graded: APPROVE / APPROVE_WITH_CONDITION / VETO | Binary clustering via majority | Binary: retain / forget |
| Fault handling | Fail-safe deterministic VETO mapping on any exception | Error dilution `O(p^⌈n/2⌉)` | Tolerate `f` malicious in `N≥3f+1` |
| Constraint injection | Veto-reason extraction + injection into alternate-node re-route | Task decomposition stops error propagation | Multi-scale temporal decay |
| Adversarial structure | Opposing physical priorities | Identical-model redundancy | Identical-objective consensus |
| Output | Operational advisory satisfying conditions | Majority-cluster answer | Memory state |

**Differentiators that survive novelty search:** opposing-agent quorum + graded vote with condition propagation + fail-safe veto default + veto-constraint re-routing + cross-agent evidence sharing + per-vote task-lifecycle binding + pre-vote outcome prediction soft signal.

## Solution

Decentralized consensus protocol for industrial-AI advisory in which specialized **opposing-priority** LLM agents participate in fault-tolerant voting:

1. **Risk-tier classification** (T1/T2/T3) using both LLM classifier AND deterministic safety-keyword floor that overrides LLM toward higher tier on any safety term match.
2. **Opposing-agent quorum spawning** — T3 (actionable) queries reviewed by at least one agent with operational priorities **opposing** the proposer (e.g., energy proposer reviewed by comfort + safety guardians).
3. **Graded vote semantics** — `APPROVE`, `APPROVE_WITH_CONDITION`, `VETO` — with confidence + conditions list per vote.
4. **Conditions extracted from APPROVE_WITH_CONDITION** and **injected as mandatory constraints into final synthesis prompt**.
5. **Fail-safe veto default** — any execution timeout, connection error, JSON parse exception, invalid-vote-string maps deterministically to `VETO`. System never approves on agent failure.
6. **Cross-agent evidence sharing** — proposer's tool results injected into quorum's reviewing context as `cross_agent_findings`. Reviewers verify against same observations proposer used.
7. **Veto-constraint re-routing** — on rejection, qualitative debate arguments extracted, appended as explicit negative constraints, re-routed to disjoint set of alternate nodes.
8. **Per-vote task lifecycle binding** — vote outcomes map deterministically to externalized investigation-plan task status (APPROVE/APPROVE_WITH_CONDITION → mark_complete; VETO/error → mark_failed). Enables deterministic audit replay.
9. **Cross-node tool-call deduplication** — per-investigation shared signature set prevents redundant expensive tool executions across parallel reviewing agents.
10. **Pre-vote outcome prediction soft signal** — XGBoost outcome predictor scores proposer's draft before BFT debate; if predicted-poor at high confidence, `PREDICTED_NEGATIVE_OUTCOME` soft annotation injected into reviewer context (advisory, not vetoing).

## Independent Claims

**Claim 1.** A computer-implemented method for fault-tolerant consensus in a multi-agent artificial-intelligence advisory system for industrial control, comprising:
- (a) receiving an operational query and classifying it into a risk tier using both (i) a language-model-judged tier classifier and (ii) a deterministic keyword-set floor that overrides the language-model judgment toward a higher tier when any safety-related term is matched in the query;
- (b) responsive to the risk tier being a designated actionable tier, instantiating a quorum of at least two specialized agent nodes wherein **at least one agent represents an operational priority opposing the proposer's primary objective**;
- (c) executing the quorum's voting round in parallel, each agent running an independent tool-call loop and returning a structured vote selected from the set `{APPROVE, APPROVE_WITH_CONDITION, VETO}`, each vote accompanied by a numeric confidence value and, in the case of conditional approval, a list of conditions;
- (d) deterministically mapping any execution timeout, connection error, JSON parse exception, or invalid vote string to a fail-safe `VETO` verdict;
- (e) responsive to the voting outcome containing at least one VETO: (i) extracting all veto reasoning, (ii) compiling the extracted reasoning as explicit constraint text, (iii) re-routing the original query, prefixed with the constraints, to a set of alternate agent nodes disjoint from the original quorum;
- (f) responsive to the voting outcome containing conditional approvals with no vetoes: (i) extracting all conditions, (ii) injecting the conditions into a synthesis prompt as **mandatory** constraints, (iii) generating a final advisory satisfying each condition;
- (g) deterministically mapping each vote outcome to the status of a corresponding task in an externalized investigation plan, wherein APPROVE and APPROVE_WITH_CONDITION map to a complete status and VETO and error outcomes map to a failed status.

**Claim 2.** The method of Claim 1, further comprising **injecting the proposer agent's tool-result observations into the quorum's reviewing context as a cross-agent-findings data block prior to voting**, enabling each reviewing agent to verify the proposal against the same observations the proposer used.

**Claim 3.** The method of Claim 1, further comprising maintaining a per-investigation shared signature set indexed by `(tool_name, arguments_hash)`, and when any agent attempts a tool invocation whose signature is already in the set, returning the previously-cached evidence rather than re-executing the tool, thereby deduplicating tool calls across the quorum.

**Claim 4.** The method of Claim 1, further comprising, prior to the voting round: (i) submitting the proposer's draft proposal to a classification model trained on prior advisory outcomes, (ii) responsive to the classifier predicting a negative outcome with confidence exceeding a threshold, injecting a soft-signal annotation into the voting context indicating predicted negative outcome, **said annotation being advisory rather than vetoing**.

**Claim 5.** The method of Claim 1, wherein when a vote string returned by an agent is not in the predefined set of valid verdicts, the verdict is normalized to VETO via a sanitization step ensuring the fail-safe default applies even on adversarial or malformed agent output.

**Claim 6.** The method of Claim 1, wherein the opposing-priority specialization comprises at least one of: an energy-conservation-priority agent paired with at least one of a comfort-priority agent or a safety-priority agent; or a maintenance-priority agent paired with at least one of an energy-priority or operations-priority agent.

**Claim 7.** A system comprising at least one processor and a non-transitory computer-readable medium storing instructions which, when executed, perform the method of any of Claims 1-6.

**Claim 8.** A non-transitory computer-readable storage medium containing instructions which, when executed by a processor, perform the method of any of Claims 1-6.

## Code Mapping

| Claim Element | File:line |
|---|---|
| Risk-tier classification | `arvis_core/swarm/queen.py:513-548 _classify_risk_tier` |
| Safety-keyword floor | `arvis_core/swarm/queen.py:521-547 _SAFETY_KEYWORDS_RE` |
| Opposing-agent quorum spawning for T3 | `arvis_core/swarm/queen.py:184-216` |
| Parallel quorum voting | `arvis_core/swarm/consensus.py:121-122 asyncio.gather` |
| Graded vote enum | `arvis_core/swarm/consensus.py:18-21 VoteVerdict` |
| Vote result with conditions | `arvis_core/swarm/consensus.py:24-30 VoteResult` |
| Fail-safe VETO on exception | `arvis_core/swarm/consensus.py:142-149` |
| Vote-string sanitization to VETO | `arvis_core/swarm/consensus.py:126-127` |
| Veto-constraint re-routing | `arvis_core/swarm/queen.py:204-242` |
| Condition extraction from APPROVE_WITH_CONDITION | `arvis_core/swarm/consensus.py:163-166`, `queen.py:320-324` |
| Mandatory condition injection into synthesis | `arvis_core/swarm/queen.py:444-455 BFT_CONDITIONS block` |
| Cross-agent findings injection | `arvis_core/swarm/queen.py:222-231 proposer_kb` |
| Per-vote task lifecycle binding | `arvis_core/swarm/queen.py:305-313` |
| Cross-node tool dedup via shared sig set | `arvis_core/plan.py:176-186 _shared_call_sigs`, `arvis_core/swarm/node.py:187-205` |
| Pre-BFT outcome prediction soft signal | `arvis_core/swarm/queen.py:295-311 PREDICTED_NEGATIVE_OUTCOME` |
| Opposing-priority agent role definitions | `agent_commercial/swarm_nodes.py` (Comfort_Agent, Energy_Agent, Safety_Agent, Maintenance_Agent role prompts) |

## Prior Art Defense (Hierarchical)

### vs Six Sigma Agent (Patel 2026) — most-cited prior art

Six Sigma uses **stochastic redundancy** — same query to identical models, majority-vote error dilution. ARVIS Claim 1(b) requires "**at least one agent represents an operational priority opposing the proposer's primary objective**." This is structural adversarial evaluation, not redundancy. Six Sigma also lacks graded vote semantics (Claim 1(c)), condition propagation (Claim 1(f)), veto-constraint re-routing (Claim 1(e)), and per-vote task-lifecycle binding (Claim 1(g)).

### vs PBFT-Backed Semantic Voting (Bach 2025)

Bach's protocol is binary (retain/forget) over distributed shared memory. ARVIS Claim 1(c) requires three-state graded votes over **operational proposals**, not memory items. Condition extraction (Claim 1(f)) and veto re-routing (Claim 1(e)) have no analogue in Bach. Bach lacks Claim 4 pre-vote outcome prediction.

### vs Classical BFT (Paxos, Raft, PBFT)

State-machine replication, binary votes, no LLM coupling, no domain semantics. All ARVIS claim elements (graded votes, condition propagation, veto re-route, fail-safe default, opposing priorities) absent.

### vs LangChain / LangGraph

Linear orchestration, no parallel fault-tolerant voting, no veto-on-error default, no opposing-priority structure.

### vs LLM Ensemble Voting (Self-Consistency, Tree-of-Thoughts)

Aggregation strategies; not consensus with veto + condition propagation + cross-agent evidence sharing.

### vs Rule-Based BMS Alarms (Honeywell EBI, Schneider EcoStruxure)

Static rules, no AI, no consensus.

**Key novelty differentiators (must center Claim 1):**
1. Opposing-priority specialization (Claim 1(b)) — not present in Six Sigma's identical-model redundancy
2. Graded vote semantics with condition propagation (Claim 1(c, f)) — not present in Bach's binary memory voting
3. Fail-safe veto default on any agent failure (Claim 1(d) and Claim 5) — defensive default unique to safety-critical industrial context
4. Veto-constraint re-routing to disjoint alternate nodes (Claim 1(e)) — extracted veto reasoning as explicit constraints
5. Cross-agent evidence sharing (Claim 2)
6. Pre-vote outcome prediction as soft signal (Claim 4) — cost-aware filtering
7. Per-vote task-lifecycle binding (Claim 1(g)) — enables deterministic audit replay

## Why This Filing Is Priority 3

- Strong novelty across multiple claim elements after differentiator carving
- **Most claim-drafting work** due to prior-art density (Six Sigma + Bach + classical BFT all require carving)
- Industrial-domain anchoring (helps §101 defense)
- Highest risk if claims drafted too broadly — direct §102 anticipation by Six Sigma or Bach
- Counsel must invest heaviest effort here

---

# Part III — Trade Secret Moat

## 5. Trade Secrets Register

12 unpatentable assets, governed in US by Defend Trade Secrets Act (DTSA), in GCC by equivalent commercial confidentiality laws. Legal protection requires reasonable secrecy measures + dissolves on independent discovery or reverse engineering.

### Category A — Domain Encoding and Regulatory Expertise

| # | Asset | Why Trade Secret |
|---|---|---|
| TS1 | **55-tool BMS surface** (`tools/definitions/*`) | 18+ months engineering; reveals operational scope and integration depth |
| TS2 | **GSAS optimizer + scoring algorithms** (`gsas_*.py`) | Qatar GSAS/GORD regulatory specificity; certified compliance path |
| TS3 | **ASHRAE RP-1312 rule encoding** | Codified decades of standards work in BMS fault detection |

### Category B — Operational Tuning and Cost Optimization

| # | Asset | Why Trade Secret |
|---|---|---|
| TS4 | **Physics bounds dictionary** `_BOUNDS` (`verifiers/physics.py`) | Qatar-commercial-tuned thresholds; calibration insights |
| TS5 | **Bedrock channel cost map** (`agent_unified/llm.py BEDROCK_MODEL_MAP`) | Per-task model selection, cost-optimized by usage data |
| TS6 | **Tool cost classification** (`_TOOL_COST_MAP`) | Per-tool cost class, calibrated by measured usage |

### Category C — Site-Specific Physics and Evaluation Parameters

| # | Asset | Why Trade Secret |
|---|---|---|
| TS7 | **Carrier 30XA bi-quadratic curve coefficients** (post-simulator build) | Manufacturer data + commissioning refinement |
| TS8 | **Per-building physics parameters** (envelope UA, thermal mass, occupancy schedules) | Months of building-specific commissioning |
| TS9 | **BFT prompt templates** (proposer/quorum/synthesis system prompts) | Months of prompt-engineering iteration; reveals reasoning approach |
| TS10 | **Distilled rules schema + TTL strategy** | Specific table design + retention policy |
| TS11 | **Skillbook Bayesian update curves** | Domain memory IP tuned for BMS context-drift |
| TS12 | **Marina adversarial test suite** (`scratch/marina_*`) | Eval methodology; adversarial scenario design |

## 6. Trade-Secret Isolation Protocols

### 6.1 Repository Access Controls

- **TS1, TS9** (BMS tools + BFT prompts): move into private permissioned submodule. Access restricted to core engineering team (≤6 named individuals).
- **TS2, TS3** (GSAS + ASHRAE encoding): isolated under `agent_commercial/regulatory/` with read-access audit logging.
- **TS7, TS8** (equipment curves + building params): per-building configs encrypted at rest using AWS KMS me-south-1 keys.

### 6.2 Audit Logging

- Mandatory access logging on TS5, TS6, TS9 (cost-sensitive operational data and prompt templates).
- Quarterly access review by IP officer.

### 6.3 Contractor and Pilot Customer Controls

- **Mandatory NDA template** signed before any TS exposure.
- Pilot customers receive **redacted documentation** — no TS contents in customer-facing materials.
- All external consultants sign DTSA-compliant NDAs with **misappropriation indemnity** clauses.

### 6.4 Departure Protocol

- Departing employees / contractors must return all materials.
- Final exit interview confirms no copies retained (cloud, personal repo, USB).
- Post-departure access tokens revoked within 24 hours.
- Distinct list of TS items reviewed against departing party's known access.

### 6.5 Independent Discovery / Reverse Engineering Defense

Trade secret protection dissolves on independent discovery. Mitigation:
- **Patent the structure**, **trade-secret the values** — competitors can independently rediscover bound values but cannot rediscover the patented method.
- **Defensive publications** for derivative concepts (lower-priority trade secrets) to prevent competitor patents while not requiring secrecy.

---

# Part IV — Execution

## 7. IP Hygiene — Confidential Information and Invention Assignment Agreements (CIIAA)

🔴 **Critical pre-filing requirement.**

### 7.1 "Hereby Assigns" Language Requirement

All employee, contractor, and consultant agreements must contain **present-tense assignment language**:

✅ **CORRECT:** *"Employee hereby assigns to Company all right, title, and interest in and to all Inventions..."*

❌ **WRONG:** *"Employee will assign..."* or *"Employee agrees to assign..."*

Future-tense language (per US patent doctrine and state laws) **severs chain of title**. Patents may be rendered unenforceable during litigation; venture capital due diligence will flag the gap.

### 7.2 Required CIIAA Components

1. **Present-tense assignment** ("hereby assigns") of all IP — patents, copyrights, trade secrets, mask works
2. **Prior inventions schedule** — employee lists pre-employment inventions to preempt later disputes
3. **Proprietary information definition** explicitly including:
   - Source code (including BFT prompt templates per TS9)
   - Specifications, designs, algorithms
   - Equipment configuration data (per TS7-TS8)
   - Customer/operator data
   - Marina adversarial test methodology (TS12)
4. **Non-disclosure obligations** surviving employment termination (typically 3-5 years)
5. **Return-of-materials clause** triggered on departure
6. **Cooperation clause** requiring departing party to execute additional documents for patent prosecution

### 7.3 Audit Action (Pre-Filing)

Before any provisional patent filing:

1. Inventory all current and past contributors to the `commercial-bms` branch (git log)
2. Verify executed CIIAA on file for each
3. Confirm "hereby assigns" present-tense language in each
4. Replace any defective agreements; obtain new signed copies
5. Document the audit + completion in IP officer log

**Risk if not done:** patents face chain-of-title challenges during litigation or VC diligence. Could render entire portfolio uneconomic.

## 8. Open-Source License Audit

Comprehensive dependency audit of `commercial-bms` branch confirms favorable permissive licensing posture.

| Dependency | Function | License | Status | Notes |
|---|---|---|---|---|
| **ChromaDB** | Vector DB for embedding storage/retrieval | Apache 2.0 | ✅ Safe | Express patent grant. **Caveat:** open-core hybrid-search restricted to Chroma Cloud — see § 8.1 |
| **XGBoost** | Outcome prediction, ML scoring | Apache 2.0 | ✅ Safe | Express patent grant from contributors |
| **pgmpy** | Causal Bayesian inference | MIT | ✅ Safe | Highly permissive |
| **lifelines** | Weibull survival analysis | MIT | ✅ Safe | Highly permissive |
| **PyTorch / TensorFlow** | VAE inference (if enabled) | BSD-3-Clause / Apache 2.0 | ✅ Safe | Verify if either enabled in production |
| **scikit-learn** | IsolationForest, preprocessing | BSD-3-Clause | ✅ Safe | |
| **pydantic** | Schema validation | MIT | ✅ Safe | |
| **fastapi** | API framework | MIT | ✅ Safe | |
| **anthropic / boto3** | Bedrock client | Apache 2.0 | ✅ Safe | |

### 8.1 ChromaDB Open-Core Architectural Risk

🟡 ChromaDB operates an "open core" commercial model:
- Vector database: Apache 2.0 ✅
- **Hybrid search (sparse + dense vectors): restricted to Chroma Cloud proprietary environment**

Architectural risk: routing sensitive evidence/skillbook/prompt data through Chroma Cloud APIs could:
1. Expose trade-secret prompts (TS9) to third-party infrastructure
2. Compromise trade-secret status if data residency / training-use clauses not contractual
3. Lock ARVIS into vendor dependency

**Mitigation:** keep ARVIS on **self-hosted ChromaDB** (Apache 2.0 core). If hybrid search needed, build internally on Apache 2.0 components or evaluate alternatives (Weaviate, Qdrant, pgvector).

### 8.2 Copyleft Audit

Verified **no GPL / AGPL / LGPL dependencies** in production paths. Any future dependency addition requires license review by IP counsel.

## 9. AI-Assisted Patent Prosecution — Tools and Risks

### 9.1 Recommended Tools

For accelerating drafting under offshore counsel supervision:

| Tool | Function | Recommended Use |
|---|---|---|
| **Solve Intelligence** | AI-assisted patent drafting + Office Action responses | Spec drafting under counsel review |
| **DeepIP** | AI-assisted claim drafting + chart generation | Claim drafting + chart preparation |
| **PatentCAM** | Prior art semantic search (USPTO + WIPO) | Novelty searches |
| **PQAI** | Vector-based prior art search | Supplementary novelty validation |
| **XLSCOUT** | Patent analytics + landscape mapping | Competitive landscape monitoring |

### 9.2 Critical Confidentiality Risks

🔴 **Feeding ARVIS specs into AI drafting tools creates trade-secret destruction risk.**

Mitigations required **before** tool use:

1. **Enterprise-tier subscription only** — never consumer/free tier
2. **Contractual data-residency** with the tool vendor
3. **No-training-use clause** — vendor cannot use ARVIS inputs to train models
4. **Encryption at rest + in transit**
5. **Deletion-on-request** with audit confirmation
6. **NDA between ARVIS and tool vendor**
7. **Counsel approval** before any tool ingests ARVIS content

**Trade secrets at risk if tools mishandle data:**
- TS5 Bedrock channel map values
- TS6 tool cost classification
- TS7 Carrier 30XA coefficients
- TS9 BFT prompt templates
- TS11 Skillbook Bayesian curves

If a tool inadvertently exposes ARVIS content publicly (e.g., via model training, breach, or improper output sharing), trade secret status is **permanently lost** and creates public §102 prior art that could bar patentability.

## 10. Subject Matter Eligibility Declaration (SMED) Preparation

37 C.F.R. § 1.132 SMED mechanism formalized by Squires Dec 4, 2025 memo.

### 10.1 Purpose

If examiner issues §101 rejection at non-provisional stage, ARVIS submits sworn expert declaration with empirical evidence demonstrating technological improvement.

### 10.2 Pre-Pilot Empirical Data Plan

Qatar commercial pilot (anticipated month 6-9) must be instrumented to generate SMED-supporting data:

| Metric | Used For | Capture Method |
|---|---|---|
| Hallucination rate (fabricated numbers caught) | All 3 apps | Hallucination test set CI + production telemetry |
| Reduction in physically impossible advisories | App 2 | Pre-deployment baseline + post-deployment count |
| BFT consensus latency vs single-LLM baseline | App 3 | Per-investigation latency log |
| Abstention rate vs operator-confirmed data gaps | App 1 | Operator feedback loop |
| False-positive rate (vs traditional rule-based BMS) | All 3 | A/B against baseline BMS alarms |
| Detection rate of confirmed faults | All 3 | Match against BMS-confirmed fault log |
| Cost per investigation | All 3 | Bedrock + compute log |
| Operator acceptance rate | All 3 | Feedback widget telemetry |

### 10.3 SMED Triggers

Pre-plan SMED if rejection appears on any of:
- §101 abstract-idea (most likely for AI claims pre-Desjardins assimilation)
- §102 anticipation (especially App 3 vs Six Sigma / Bach)
- §103 obviousness

### 10.4 SMED Expert Pool

Identify 2-3 potential expert declarants now:
- Industrial control systems professor (US R1 university preferred)
- BMS / HVAC veteran with multi-vendor BFT consensus experience
- Patent-experienced AI safety researcher (preferably with prior SMED experience)

Pre-engage during month 9-12 to ensure availability when needed.

## 11. 30-Month Execution Roadmap

### Phase 1 — Days 1-15: Priority Lock

| Day | Action |
|---|---|
| 1-3 | Retain US lead counsel (Torrey Pines or Seed IP); engage K&K offshore drafting partner |
| 1-5 | CIIAA audit: inventory all `commercial-bms` contributors, verify present-tense assignment, replace defective |
| 4-7 | Open-source dependency final audit + license verification |
| 5-10 | App 1 (Multi-Signal Abstention Gate) provisional drafting w/ K&K |
| 10-15 | App 1 provisional review by US counsel + filing |

**Deliverable end of Phase 1:** App 1 provisional filed with USPTO. Priority date locked.

### Phase 2 — Days 15-45: Simulator Build + App 2 + App 3

| Day | Action |
|---|---|
| 15-29 | Build thermodynamic simulator (parallel to App 2 drafting): `chiller.py`, `cooling_coil.py`, `ahu.py`, `building.py`, `loop.py`, `violations.py`, `engine.py`. Source Carrier 30XA coefficients (manufacturer or AHRI). |
| 15-25 | App 2 provisional drafting (claim 1(c) language locked to simulator code) |
| 25-30 | App 2 provisional review + filing (post-simulator-build) |
| 25-40 | App 3 (BFT Consensus) provisional drafting — most claim-drafting effort due to Six Sigma + Bach differentiator carving |
| 40-45 | App 3 provisional review + filing |

**Deliverable end of Phase 2:** All 3 provisionals filed. Simulator code in production. Trade-secret isolation protocols active.

### Phase 3 — Months 2-6: Pilot Preparation + Trade-Secret Hardening

| Month | Action |
|---|---|
| 2 | Begin pilot infrastructure: BACnet/Modbus to Marina Heights, point map verified |
| 2-3 | Operator UX completion: live plan checklist, evidence drill-down, feedback widget |
| 3 | Trade-secret isolation protocols active (TS1, TS9 in permissioned submodule; TS7-TS8 encrypted at rest) |
| 4 | Pilot agreement framework drafted (legal + commercial) |
| 4-5 | Read-only certification (legal sign-off, plant manager) |
| 5-6 | Shadow deploy on Marina Heights begins (read-only, no operator UI) |

### Phase 4 — Months 6-12: Commercial Pilot + Empirical Data

| Month | Action |
|---|---|
| 6 | Limited operator pilot launches (Noor-equivalent, 1 shift) |
| 6-9 | Qatar national patent filing via Al Tamimi & Co (parallel to US prosecution) |
| 6-12 | Empirical data capture per SMED plan (§ 10.2) |
| 9-12 | Full pilot expansion (24/7, multi-operator) |
| 11 | PCT international filing decision point (per app) — based on commercial traction |
| 12 | US non-provisional conversion for filed provisionals — cost $30-45K total |

### Phase 5 — Months 12-30: Prosecution + International + Continuation

| Month | Action |
|---|---|
| 12-18 | First Office Actions expected — counsel responds, SMED-ready if needed |
| 18 | PCT international publication (if filed) |
| 18-24 | Continuation-in-part filings for any improvements during pilot year |
| 24-30 | Decision points for national-phase entry (EU, UK, Singapore, Japan) |
| 30 | National-phase entry deadline for PCT applications |

## 12. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **§101 abstract-idea rejection** | Medium | Frame per Desjardins; SMED-ready (§ 10); industrial-domain anchoring; data-structure specificity |
| **§102 anticipation by Six Sigma / Bach (App 3)** | High | Differentiator carving in Claim 1 (opposing-priority + graded vote + condition propagation); prior-art table in spec |
| **§102 anticipation by AutoChemSchematic (App 2)** | Low-Medium | Real-time operational + sub-100ms claim limits (Claims 1, 7); industrial-asset domain limit |
| **§112 written description (App 2)** | High | **Build simulator before filing**; ensure enabling disclosure of DOE-2 curves + NTU + lumped capacitance |
| **§103 obviousness combination rejections** | Medium | Prior-art differentiator tables in spec; expert SMED if needed |
| **Public disclosure before filing** | Critical | **No external talks/blog/papers before provisional filing**; audit existing public materials |
| **CIIAA chain-of-title** | Critical | **Pre-filing audit + remediation** (§ 7.3); replace future-tense agreements |
| **Trade-secret leakage via AI drafting tools** | High | Enterprise-tier only + contractual safeguards (§ 9.2); counsel approval per ingestion |
| **Open-source contamination** | Low | License audit confirmed permissive (§ 8); ongoing review on dependency additions |
| **ChromaDB vendor lock-in** | Medium | Self-hosted Apache 2.0 core; avoid Chroma Cloud for sensitive data |
| **Inventorship — AI-assisted invention** | Medium | Maintain human-conception documentation (§ 2.4); timestamped design docs |
| **Competitor files first** | Medium | File provisionals within 60 days; continuation-in-part for improvements |
| **Customer-contract IP transfer clauses** | Medium | Review pilot agreements — ensure inventions remain ARVIS-assigned, not work-for-hire |

## 13. Cost Summary

### Conservative Path (US-only with selective PCT, Qatar)

| Item | Cost (USD) |
|---|---|
| 3 US provisional filings (with offshore drafting) | $7-12K |
| 3 US non-provisional conversions (month 12) | $30-45K |
| Qatar national filing (month 6-9) | $5-8K |
| PCT international (selective, month 11) | $30-50K |
| **Total over 30 months (conservative)** | **$72-115K** |

### Full International Path (US + PCT + EU + UK + JP + SG)

Add national-phase entries at month 30: $30-50K incremental.
**Total over 30 months: $100-165K.**

### Additional ongoing costs

- Trade-secret operational protection (audit logs, encryption infrastructure): $5-10K/year
- AI drafting tool subscriptions (enterprise tier): $10-30K/year
- Counsel ongoing fees (responses, continuations): $20-40K/year

## 14. Summary Recommendations

1. **File 3 US provisionals within 60 days.** App 1 first (week 1-2), App 2 after simulator build (week 3-4), App 3 with revised differentiators (week 5-6). Total cost $7-12K via K&K offshore drafting.

2. **Build the physics simulator before filing App 2.** Two weeks engineering, prevents §112 fatal rejection.

3. **CIIAA audit is non-negotiable pre-filing.** "Hereby assigns" present-tense language across every contributor.

4. **Hold the 12 trade-secret assets closed** with isolation protocols active. They are the deepest moat; patents are insurance, trade secrets compound.

5. **No public disclosure of these methods until provisionals filed.** Single highest-risk action item.

6. **Engage Torrey Pines + Al Tamimi + Khurana & Khurana early.** Three-tier counsel model balances cost and quality.

7. **Instrument Qatar pilot for SMED data capture from day one.** Empirical evidence preempts §101 rejections.

8. **Long-term moat is non-patentable**: accumulated operator interactions, per-building skillbook, ML training data, audit trails. Patents protect the method; data builds the durable advantage.

---

# Appendix A — Code Citation Index

For patent counsel reference, all code paths cited in claims:

```
arvis_core/
├── evidence.py                      # App 1 — Evidence + EvidenceLedger, is_ml_fallback attribute
├── plan.py                          # App 1 — coverage; App 3 — _shared_call_sigs, task lifecycle
├── ml_facade.py                     # App 1 — MLResult with fallback=True + reason
└── swarm/
    ├── consensus.py                 # App 3 — VoteVerdict, run_debate, fail-safe veto, sanitization
    ├── node.py                      # App 3 — spin dedup, cross-node check
    └── queen.py                     # App 2 — regen-or-abstain, verb map, three-layer enforcement
                                     # App 3 — risk tier, BFT, conditions, opposing-priority spawning

agent_commercial/
├── bms_llm_agent.py                 # App 1 — abstention gate (lines 1042-1180)
├── grounding_guard.py               # App 2 — supports (background context)
├── tools/handlers/
│   └── ml.py                        # App 1 — structured ML_UNAVAILABLE sentinel
├── swarm_nodes.py                   # App 3 — opposing-priority agent definitions
└── verifiers/
    ├── physics.py                   # App 2 — current bounds-check; extends to invoke simulator
    └── simulator/                   # App 2 — TO BE BUILT
        ├── engine.py                # Claim 1(c) orchestrator
        ├── chiller.py               # Claim 2 DOE-2 curves
        ├── cooling_coil.py          # Claim 1(c)(ii) NTU-effectiveness
        ├── ahu.py                   # AHU steady-state balance
        ├── building.py              # Claim 1(c)(iii) lumped capacitance
        ├── loop.py                  # Claim 1(c)(iv) hydraulic model
        └── violations.py            # Claim 1(e) ViolationLedger

agent_cognitive/
└── prediction_engine.py             # App 1 — drift_score generation; App 3 — supporting

agent_advisory/
└── ml_models/
    └── outcome_predictor.py         # App 3 — Claim 4 outcome predictor

data/
├── equipment_curves/
│   └── carrier_30xa_curves.yaml     # App 2 — TO BE CREATED; TS7
└── buildings/
    └── marina_heights.yaml          # App 2 — TO BE CREATED; TS8
```

---

# Appendix B — Glossary

- **Abstention Gate**: code-enforced decision point that suppresses LLM advisory output when multi-signal confidence is insufficient.
- **APRP**: Appeals Review Panel (USPTO panel that designated *Ex parte Desjardins* as binding precedent).
- **BFT (Byzantine Fault-Tolerant)**: consensus protocol class where the system functions correctly despite up to a bounded fraction of nodes failing in arbitrary ways.
- **CAP-FT**: Capacity-as-Function-of-Temperature curve (DOE-2 standard, bi-quadratic in chilled-water leaving temperature and condenser entering temperature).
- **CIIAA**: Confidential Information and Invention Assignment Agreement.
- **DOE-2**: US Department of Energy building energy simulation standard whose bi-quadratic chiller curves are widely used in commercial HVAC engineering.
- **DPMO**: Defects Per Million Opportunities (Six Sigma metric).
- **Drift score**: numeric measure of how far an ML model's predictions deviate from observed reality.
- **DTSA**: Defend Trade Secrets Act (US, 18 U.S.C. § 1836).
- **EIR (Energy Input Ratio)**: inverse of COP; energy consumed per unit cooling delivered.
- **EIR-FT**: EIR-as-Function-of-Temperature curve (DOE-2 standard).
- **Evidence Ledger**: structured per-investigation store of tool-result and document-chunk entries with provenance metadata.
- **GSAS / GORD**: Global Sustainability Assessment System / Gulf Organisation for Research & Development — Qatar's green-building certification system.
- **InvestigationPlan**: externalized code-state object representing the active investigation, with tasks, evidence, budget, audit trail.
- **NTU-effectiveness method**: standard ASHRAE/textbook method for predicting cooling-coil heat-transfer effectiveness as function of fluid heat capacity ratio and number of transfer units.
- **PBFT**: Practical Byzantine Fault Tolerance (Castro & Liskov, 1999).
- **PCT**: Patent Cooperation Treaty (international patent filing framework).
- **PLR (Part-Load Ratio)**: chiller operating ratio (current load / rated capacity).
- **PTAB**: Patent Trial and Appeal Board (USPTO).
- **Recentive**: Federal Circuit precedent (*Recentive Analytics v. Fox Corp.*, April 2025) — "ML applied to new domain" alone insufficient for patentability.
- **SaMD**: Software as a Medical Device (FDA regulatory category).
- **§101 (Section 101)**: 35 U.S.C. § 101, US patent statute defining patent-eligible subject matter.
- **§102**: 35 U.S.C. § 102, novelty requirement.
- **§103**: 35 U.S.C. § 103, non-obviousness requirement.
- **§112**: 35 U.S.C. § 112, written description and enablement requirements.
- **SMED**: Subject Matter Eligibility Declaration (37 C.F.R. § 1.132) — sworn declaration to overcome §101 rejection.
- **T1/T2/T3 risk tier**: ARVIS's three-level query classification (lookup / diagnostic / actionable).
- **TS1-TS12**: Trade Secret items 1 through 12 in the Trade Secrets Register (§ 5).
- **Veto-Constraint Re-routing**: ARVIS-specific pattern of extracting veto reasoning from BFT debate and submitting it as explicit constraints to alternate nodes.

---

# Appendix C — Prior Art Reference Table

For Information Disclosure Statement (IDS) submission with each provisional:

## App 1 — Multi-Signal Abstention Gate

| Reference | Citation | Notes |
|---|---|---|
| MM-AQA Benchmark | "Knowing When Not to Answer: Evaluating Abstention in Multimodal Reasoning Systems," arXiv April 2026 | Multimodal verify-then-abstain benchmark |
| LLM Lens | "Weakly Supervised Distillation of Hallucination Signals into Transformer Representations," arXiv April 2026 | Internal hidden-state probing |
| AbstentionBench | OpenReview 2025 | Evaluation framework for refusal |
| Military AI Drift | "Detecting Concept Drift in Object Detection Models," IEEE Xplore 2025 | YOLO + human-in-loop drift fusion |
| Adaptive AI Retraining patent | Google Patents, US Patent App | Drift-detected retraining (separate from abstention) |
| Model Drift Background | "When AI Goes Astray," ASHP 2024-2025 | Concept drift background |

## App 2 — Closed-Loop Physics Verification

| Reference | Citation | Notes |
|---|---|---|
| AutoChemSchematic AI | arXiv May 2025 + Semantic Scholar | Closed-loop physics-aware for offline chem PFD/PID |
| SimuPhy | OpenReview 2025 | VLM closed-loop physical-law evaluation |
| PHYSGYM | KAUST Repository 2025 | LLM scientific reasoning benchmark |
| Using LLMs for Thermodynamic Problems | Wang et al., arXiv 2025 | Documents LLM analytical-physics limitations |

## App 3 — BFT Multi-Agent Consensus

| Reference | Citation | Notes |
|---|---|---|
| Six Sigma Agent | Patel, "The Six Sigma Agent," arXiv January 2026 + ResearchGate + Semantic Scholar | **Primary §102 anticipation risk** |
| PBFT-Semantic Voting | Bach, "PBFT-Backed Semantic Voting for Multi-Agent Memory Pruning," arXiv June 2025 + Opast Publishing | **Primary §102 anticipation risk** |
| Co-Forgetting Protocol | GitHub: DngBack/co-forget-protocol | Companion to Bach 2025 |
| Multi-Agent Coordination Strategies | Galileo AI 2025 | Architecture survey |
| Compounding Errors Multi-Agent | Zartis Research 2025 | Multi-agent failure modes |

## Federal Circuit / USPTO References (All Apps)

| Reference | Citation | Notes |
|---|---|---|
| Ex parte Desjardins | USPTO ARP Appeal No. 2024-000567, Sep 26 2025 | Binding precedent — favorable §101 |
| Recentive Analytics v. Fox | Federal Circuit, April 2025 | "ML applied to new domain" insufficient |
| Squires Memo (Dec 4, 2025) | USPTO Examination Memorandum | Preponderance standard + SMED formalization |
| Squires Memo (Dec 5, 2025) | USPTO Examination Memorandum | "Specification disclosed improvement + reflected in claims = Patent-Eligible" |
| Enfish v. Microsoft | Federal Circuit | Software improvements to computer functioning eligible |
| Alice Corp v. CLS Bank | Supreme Court 2014 | Two-part eligibility framework |
| 2025 USPTO Inventorship Guidance | USPTO | Human-conception requirement for AI-assisted inventions |

---

*Document prepared for patent counsel engagement. Not legal advice. Patentability requires formal novelty search and counsel review. Final claim language must be drafted by registered patent practitioners.*

*Supersedes IP_FILING_REPORT.md (v1, 2026-05-21).*
