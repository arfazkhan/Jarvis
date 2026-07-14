# ARVIS — IP Filing Report

**Status:** Pre-filing technical specification for patent counsel
**Prepared:** 2026-05-21
**Codebase:** `commercial-bms` branch
**Scope:** Three utility patent provisional filings + trade-secret register

---

## Executive Summary

ARVIS is a production-grade agentic AI advisory system for commercial Building Management Systems (BMS). Architectural review identified **three independently patentable inventions** plus **twelve trade-secret-worthy assets**.

Recommended action:
- **File three U.S. provisional patents** in the next 30 days, total estimated cost $9–15K USD
- **Lock priority date** on the strongest novelty claims before any public disclosure (papers, blog posts, pilot announcements)
- **Hold sensitive domain encoding as trade secret** (prompts, coefficients, GSAS algorithms)

The three patents are designed as **mutually reinforcing**: each blocks a different competitor approach to AI-driven industrial advisory. Together they protect the structural moat around ARVIS's agentic + hallucination-resistant + physics-grounded architecture.

---

## Filing Strategy at a Glance

| # | Application | Strength | Provisional File Order | Est. Cost (US Prov.) |
|---|---|---|---|---|
| 1 | **Multi-Signal Abstention Gate** | HIGHEST | Week 1–2 | $2–4K |
| 2 | **Closed-Loop Physics Verification** | HIGH (after simulator build) | Week 3–4 | $3–5K |
| 3 | **BFT Multi-Agent Consensus for Industrial Control** | HIGH | Week 5–6 | $3–5K |
| | **Total provisional cost** | | | **$8–14K** |

**Jurisdiction sequencing:**
- US first (broadest defensible jurisdiction, USPTO experienced w/ software/AI)
- Qatar / GCC national filings at 6–9 month mark (matches commercial pilot region)
- PCT international at month 11 if commercial traction warrants (~$30–50K)
- EU + UK + Singapore + Japan national phase at month 30 (if scaling)

**Critical constraint:** US patents require novelty-at-filing. **Any public disclosure (blog post, conference talk, customer demo without NDA) before filing creates §102 prior art that bars patentability.** File provisionals before any external communication of these methods.

---

# Application 1 — Multi-Signal Abstention Gate for Agentic AI Systems

## Technical Field
Artificial intelligence safety, autonomous decision systems, large-language-model (LLM) advisory systems, calibrated uncertainty in safety-critical industrial control.

## Problem Solved
LLM-driven advisory systems face a binary failure mode: either they answer every query (hallucinating when blind) or they refuse on a single low-confidence signal (refusal cascade). Industrial deployments need a third mode — **calibrated abstention** — where the system recognizes *when not to advise* based on multiple orthogonal signals.

Existing approaches either:
1. Use a single confidence threshold (brittle; one signal type can dominate)
2. Apply generic RLHF refusal training (not domain-specific, not lineage-traced)
3. Run the LLM without any abstention mechanism (hallucinates under data gaps)

None integrate **data coverage + verification score + ML availability + model drift** into a single fused abstention decision with structured reason-code output.

## Solution
A multi-signal abstention gate that fuses four orthogonal signals into a calibrated decision:

1. **Data coverage** — fraction of investigation tasks with associated evidence entries
2. **Verification (truth) score** — LLM-judge or deterministic verifier score on the draft answer
3. **ML fallback ratio** — fraction of evidence rows marked `is_ml_fallback=True`
4. **Maximum drift score** — highest observed drift across active ML models

The gate fires under any of these conditions:
- `coverage < 0.3 AND truth_score < 0.8` (data gap + uncertain verification)
- `ml_fallback_ratio > 0.5` (majority of ML evidence is fallback)
- `max_drift > 0.7` (any active model is stale)

**Key novel element:** ML fallback evidence is treated as `drift_score = 1.0` so the gate fires whether drift is measured or models are unavailable — unifying "unmeasured" and "unhealthy" into one signal.

When the gate fires, the system emits a structured abstention output with a machine-readable reason code (`data_gap | ml_fallback | drift_stale`), distinct from the advisory output and carrying lineage trace back to the contributing evidence IDs and model IDs.

## Independent Claims (drafting language)

**Claim 1.** A computer-implemented method for calibrated abstention in an artificial-intelligence advisory system, comprising:
- (a) maintaining an evidence ledger of tool-result and document-chunk entries associated with an active investigation, each entry carrying provenance metadata including a source-tool identifier and an ML-fallback flag;
- (b) computing a data-coverage score as the fraction of investigation-plan tasks having at least one associated evidence entry;
- (c) computing an ML-fallback-ratio as the fraction of evidence entries having the ML-fallback flag set true;
- (d) computing a maximum-drift score across all evidence entries, wherein evidence entries having the ML-fallback flag set true contribute a drift value of 1.0 regardless of any explicit drift measurement;
- (e) applying a fused abstention rule that emits an abstention signal when any of the following conditions hold: (i) the data-coverage score is below a first threshold and a verification score for a draft advisory is below a second threshold; (ii) the ML-fallback-ratio exceeds a third threshold; (iii) the maximum-drift score exceeds a fourth threshold;
- (f) upon emitting the abstention signal, producing a structured abstention output comprising (i) a machine-readable reason-code identifying which condition triggered abstention and (ii) a lineage trace referencing the contributing evidence identifiers.

**Claim 2.** The method of Claim 1, wherein the ML-fallback flag is set responsive to a tool handler receiving a structured "ML unavailable" sentinel from a downstream model facade indicating one of: (a) required model library not loaded, (b) trained model artifact unavailable, (c) inference service exception.

**Claim 3.** The method of Claim 1, further comprising: continuing investigation execution under the abstention signal up to a budget limit, but substituting the draft advisory output with the structured abstention output before delivery to the operator.

**Claim 4.** The method of Claim 1, wherein the four thresholds are independently configurable and the rule is monotonic — a stricter threshold cannot cause abstention to *not* fire when a looser threshold would.

**Claim 5.** A system comprising at least one processor and a non-transitory computer-readable medium storing instructions which, when executed, cause the processor to perform the method of any of Claims 1–4.

**Claim 6.** A non-transitory computer-readable storage medium containing instructions which, when executed by a processor, cause the processor to perform the method of any of Claims 1–4.

## Code Mapping
| Claim Element | File:line |
|---|---|
| Evidence ledger with provenance | `arvis_core/evidence.py:Evidence`, `:EvidenceLedger` |
| ML-fallback flag | `arvis_core/evidence.py` — `is_ml_fallback` attribute |
| Coverage computation | `arvis_core/plan.py:219 coverage` property |
| Fallback ratio computation | `agent_commercial/bms_llm_agent.py:1152-1158` |
| Maximum drift w/ fallback→1.0 mapping | `agent_commercial/bms_llm_agent.py:1161-1170` |
| Fused abstention rule | `agent_commercial/bms_llm_agent.py:1173-1180` |
| Structured ML_UNAVAILABLE sentinel | `agent_commercial/tools/handlers/ml.py:67-75`, `arvis_core/ml_facade.py:106+` |
| Reason-code in abstention output | `agent_commercial/bms_llm_agent.py:1175-1180` |

## Prior Art Defense
- **Single-threshold confidence gates** (common in classifiers): patent claims *multi-signal fusion*, not single threshold.
- **RLHF refusal training**: trained behavior, not deterministic gate; produces text refusal, not structured reason-code.
- **MLOps drift detection**: standalone systems that don't integrate with agent abstention; the novelty here is coupling drift to abstention through the evidence-ledger lineage.
- **Generic LLM safety filters (Anthropic Constitutional AI, OpenAI moderation)**: content-based filters, not signal-fusion gates on data coverage + verification + ML health.

**Key differentiator:** ML-fallback-as-max-drift mapping (Claim 1(d)). This unifies "unmeasured" and "unhealthy" into one signal — a specific algorithmic move not found in prior art systems.

## Why This Filing Is Highest Priority
- **Strongest novelty hook** (no clear prior art on multi-signal fused abstention with fallback-as-drift mapping)
- **Broadest applicability** (any safety-critical agentic AI deployment — not just BMS)
- **Cross-domain defensibility** (medical advisory, industrial control, autonomous systems, financial advisory)
- **Clean implementation** (lines of code that map directly to claims)

---

# Application 2 — Closed-Loop Physics Verification System for Generative Building Operations Advisories

## Technical Field
Industrial control systems, thermodynamic modeling, generative AI output verification, building energy management, safety-guarded automation.

## Problem Solved
LLMs generate fluent natural-language recommendations and identify patterns but cannot reliably perform thermodynamic mathematics within their context windows. They frequently suggest physically impossible operational changes (e.g., chiller setpoints that violate the second law of thermodynamics, air flow rates exceeding mass balance, simultaneous heating and cooling, COP values outside physically achievable bounds).

Existing approaches:
1. **PLC-level mechanical safeties (freeze-stats, high-pressure cutouts)**: hardware-level, slow, retroactive
2. **Schema validation (JSON parse, regex)**: structural only, no physics
3. **Generic LLM output filtering (regex moderation)**: no physical model
4. **Pure LLM self-critique**: subject to the same hallucination as generation

None **wrap a non-deterministic generative model in a deterministic thermodynamic constraint layer** with closed-loop regeneration and bounded abstention.

## Solution
A closed-loop verification system that intercepts generative AI advisory output, translates it into physical parameters, simulates the proposed change against a localized thermodynamic engine, and either passes, regenerates, or hard-abstains.

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
                                                            [Re-verify]  [Hard Abstain]
```

The thermodynamic simulation engine comprises:
- A **chiller capacity-and-efficiency model** parameterized by bi-quadratic CAP-FT and EIR-FT curves (DOE-2 standard form), per equipment
- A **cooling-coil heat-transfer model** using the NTU-effectiveness method
- A **building thermal-mass model** using lumped-capacitance forward-Euler prediction
- A **chilled-water hydraulic model** relating flow, temperature differential, and pumping power

Outputs of the simulator (predicted SAT, COP, energy consumption, zone temperature) are validated against:
- Physics bounds dictionary (COP, temperature ranges, vibration, filter DP, power factor)
- Equipment operating envelopes derived from manufacturer specifications and ASHRAE standards
- Energy conservation (load ≤ available chiller capacity × n_chillers × tolerance)
- Causal-chain hop count (preventing over-reasoned LLM explanations)

On violation, a structured `ViolationLedger` is compiled with per-violation code, severity, expected vs cited value, component, and law-invoked. This ledger is injected into a regeneration prompt as **mandatory constraints**. The regenerated output is re-verified. On second failure, the system hard-abstains with a structured fallback advisory (no retry text passed to operator as advice).

A final **active-to-passive verb transformation** layer scans the synthesized advisory and replaces active-execution verbs (e.g., "submitted", "adjusted", "shut down", "restarted") with passive advisory phrases (e.g., "recommend submitting", "recommend adjusting", "recommend shutting down"), enforcing the read-only operational stance via three independent layers (system-prompt rule + deterministic verb-map substitution + post-generation regex scan).

## Independent Claims

**Claim 1.** A computer-implemented method for verifying generative-AI advisories against thermodynamic constraints in industrial control systems, comprising:
- (a) receiving a structured advisory output from a generative language model proposing one or more operational changes;
- (b) parsing the advisory to extract proposed physical parameters including setpoints, flow rates, and equipment states;
- (c) feeding the extracted parameters into a localized deterministic thermodynamic simulation engine, said engine comprising at least: (i) a chiller capacity and efficiency model parameterized by bi-quadratic temperature-dependent curves, (ii) a cooling-coil heat-transfer model using the NTU-effectiveness method, (iii) a building thermal-mass lumped-capacitance model, and (iv) a chilled-water flow-vs-temperature-differential hydraulic model;
- (d) computing predicted equipment-output values from the simulation and comparing each to (i) absolute physics bounds and (ii) equipment manufacturer envelopes;
- (e) generating a structured violation ledger containing per-violation entries identifying code, severity, expected and cited values, component, and physical law invoked;
- (f) responsive to the violation ledger containing one or more hard-severity violations: (i) compiling the ledger into a constraint-injection prompt, (ii) submitting the prompt with the original advisory to a generative model for regeneration, (iii) re-verifying the regenerated output through steps (b)–(e);
- (g) responsive to the regenerated output also containing hard-severity violations: emitting a structured fallback advisory comprising a system-notice severity level and a retry recommendation, without delivering the unverified advisory text to the operator;
- (h) responsive to the verification passing: scanning the verified advisory for active-execution verbs and replacing each with a corresponding passive advisory phrase via a deterministic verb-substitution mapping before delivery.

**Claim 2.** The method of Claim 1, wherein the chiller efficiency model comprises a DOE-2-form bi-quadratic capacity-as-function-of-temperature (CAP-FT) curve and a bi-quadratic energy-input-ratio-as-function-of-temperature (EIR-FT) curve, with coefficients loaded from a per-equipment configuration registry.

**Claim 3.** The method of Claim 1, wherein the violation ledger structure further comprises a `law_invoked` field tagging each violation with the underlying physical principle (e.g., energy conservation, chiller lift envelope, cooling-coil NTU capacity, causal-chain bound).

**Claim 4.** The method of Claim 1, wherein the regeneration step (f) imposes a single regeneration attempt before progressing to step (g), bounding LLM cost and preventing infinite regeneration loops.

**Claim 5.** The method of Claim 1, wherein step (h) is performed in addition to two independent enforcement layers: (i) a system-prompt rule instructing the generative model to use advisory language, and (ii) a regex-based post-generation scan, providing three-layer defense against active-execution language leakage.

**Claim 6.** The method of Claim 1, wherein the simulation engine outputs are registered as evidence entries in an investigation-evidence ledger and the regenerated advisory must cite numerical values from said ledger.

**Claim 7.** A system comprising at least one processor and a non-transitory computer-readable medium storing instructions which, when executed, perform the method of any of Claims 1–6.

**Claim 8.** A non-transitory computer-readable storage medium containing instructions which, when executed by a processor, perform the method of any of Claims 1–6.

## Pre-Filing Build Requirement
**Claim 1(c) requires the simulator to actually exist.** Current `PhysicsVerifier` (`agent_commercial/verifiers/physics.py`) implements bounds checking + simple relations, not full thermodynamic simulation. **Build the simulator (~2 weeks, one engineer) before filing** or the claim is narrowed during prosecution and the patent loses breadth.

Required new code:
- `agent_commercial/verifiers/simulator/engine.py` (orchestrator)
- `agent_commercial/verifiers/simulator/chiller.py` (DOE-2 curves)
- `agent_commercial/verifiers/simulator/cooling_coil.py` (NTU-effectiveness)
- `agent_commercial/verifiers/simulator/ahu.py` (AHU steady-state balance)
- `agent_commercial/verifiers/simulator/building.py` (lumped thermal mass)
- `agent_commercial/verifiers/simulator/loop.py` (chilled water hydraulics)
- `agent_commercial/verifiers/violations.py` (`ViolationLedger`, `PhysicalViolation`)
- `data/equipment_curves/carrier_30xa_curves.yaml` (real Carrier 30XA coefficients)
- `data/buildings/marina_heights.yaml` (per-building params)

## Code Mapping (Existing)
| Claim Element | File:line |
|---|---|
| Closed-loop regen-or-abstain control flow | `arvis_core/swarm/queen.py:405-466` |
| Constraint-injection prompt | `arvis_core/swarm/queen.py:413-419` |
| Hard-abstain fallback JSON | `arvis_core/swarm/queen.py:435-448` |
| Structured violation list | `agent_commercial/verifiers/physics.py:VerificationResult` |
| Verb-substitution map | `arvis_core/swarm/queen.py:34-51 _VERB_REPLACEMENTS` |
| Deterministic verb enforcement | `arvis_core/swarm/queen.py:671-690 _enforce_read_only` |
| Causal chain hop validation | `agent_commercial/verifiers/physics.py:80-98 verify_causal_chain` |
| Three-layer read-only enforcement | system_prompt at `queen.py:402-406` + verb map (above) + regex (above) |

## Prior Art Defense
- **PLC-level safeties**: hardware retroactive, not generative AI-coupled.
- **JSON schema validation**: structural only, no thermodynamic model.
- **EnergyPlus / Modelica simulators**: standalone tools, not interposed between LLM and operator with regen-or-abstain feedback.
- **LLM self-critique**: subject to same hallucination, not deterministic.
- **Constitutional AI / RLHF refusal**: content-based, not physics-coupled.

**Key differentiator:** **Closed loop** — LLM output → physics simulator → violation ledger → constraint-injected regeneration → second physics check → hard abstain on second failure. The closed-loop structure is the novelty hook. Three-layer read-only enforcement (Claim 5) is a secondary differentiator.

## Why This Filing Is Priority 2
- Strong novelty (closed-loop simulator-LLM coupling)
- Industrial-domain anchoring (helps §101 abstract-idea defense)
- High commercial value (any AI BMS competitor must invent around this)
- **Blocked until simulator built**: 2 weeks of implementation work required first

---

# Application 3 — Byzantine Fault-Tolerant Multi-Agent Consensus for Industrial Asset Control

## Technical Field
Multi-agent artificial intelligence systems, decentralized consensus protocols, large-language-model orchestration, safety-guarded industrial automation, fault-tolerant distributed systems.

## Problem Solved
General-purpose LLM controllers applied to industrial assets are dangerous due to:
1. Single-point-of-failure architecture (one model, one decision)
2. No fault tolerance (API exception → undefined system state)
3. No domain conflict resolution (cutting ventilation to save energy → CO2 buildup)
4. Binary approval semantics (cannot express "approve with conditions")

Existing approaches:
- **LangChain / LangGraph linear chains**: no fault tolerance, single-LLM crashes the runtime
- **Classical BFT (Paxos, Raft, PBFT)**: designed for state-machine replication, binary votes, no domain semantics, no LLM integration
- **Multi-LLM ensembling (majority voting)**: no opposing-goal structure, no conditional approval, no veto-driven re-routing
- **Static rule-based BMS alarms**: not learning, no LLM, no consensus, no condition expression

None implement **fault-tolerant consensus voting directly coupled to opposing physical/operational constraints** in an industrial environment with graded vote semantics and condition propagation.

## Solution
A decentralized consensus protocol for industrial-AI advisory in which specialized single-domain LLM agents (each representing one operational priority — energy, comfort, safety, maintenance) participate in a fault-tolerant voting round, where:

1. **Risk-tier classification** routes each query to one of three execution paths (lookup, diagnostic, actionable) using both LLM classification and a deterministic safety-keyword floor that overrides the LLM toward higher safety tier.
2. **Opposing-agent quorum spawning** ensures any T3 (actionable) query is reviewed by at least one agent with operational priorities opposing the proposer.
3. **Graded vote semantics** — `APPROVE`, `APPROVE_WITH_CONDITION`, or `VETO` — replace binary approval, with conditions extracted from conditional approvals and **injected as mandatory constraints into the final synthesis prompt**.
4. **Fail-safe veto default** — any node-level execution timeout, connection error, JSON parse exception, or invalid vote string maps deterministically to a `VETO` verdict, ensuring the system never approves an action when an agent has failed.
5. **Cross-agent evidence sharing** — proposer's tool results are injected into the quorum's reviewing context as `cross_agent_findings`, allowing reviewers to verify against the same observations the proposer used.
6. **Veto-constraint re-routing** — on rejection, the qualitative debate arguments are extracted and appended as explicit negative constraints to a re-routed query sent to a disjoint set of alternate nodes.
7. **Per-vote task lifecycle binding** — each vote outcome maps deterministically to an externalized investigation-plan task status (APPROVE/APPROVE_WITH_CONDITION → mark complete, VETO/error → mark failed), enabling deterministic audit replay.
8. **Cross-node tool-call deduplication** — a per-investigation shared signature set prevents redundant tool executions across parallel reviewing agents.
9. **Pre-vote outcome prediction** — an XGBoost-based outcome predictor scores the proposer's draft before BFT debate; if predicted-poor at high confidence, a soft signal (`PREDICTED_NEGATIVE_OUTCOME`) is injected into reviewer context as advisory information (not hard veto), filtering low-quality proposals before they consume reviewer tokens.

## Independent Claims

**Claim 1.** A computer-implemented method for fault-tolerant consensus in a multi-agent artificial-intelligence advisory system for industrial control, comprising:
- (a) receiving an operational query and classifying it into a risk tier using both (i) a language-model-judged tier classifier and (ii) a deterministic keyword-set floor that overrides the language-model judgment toward a higher tier when any safety-related term is matched in the query;
- (b) responsive to the risk tier being a designated actionable tier, instantiating a quorum of at least two specialized agent nodes wherein at least one agent represents a goal opposing the proposer's primary objective;
- (c) executing the quorum's voting round in parallel, each agent running an independent tool-call loop and returning a structured vote selected from the set `{APPROVE, APPROVE_WITH_CONDITION, VETO}`, each vote accompanied by a numeric confidence value and, in the case of conditional approval, a list of conditions;
- (d) deterministically mapping any execution timeout, connection error, JSON parse exception, or invalid vote string to a fail-safe `VETO` verdict;
- (e) when the voting outcome contains at least one VETO: (i) extracting all veto reasoning, (ii) compiling the extracted reasoning as explicit constraint text, (iii) re-routing the original query, prefixed with the constraints, to a set of alternate agent nodes disjoint from the original quorum;
- (f) when the voting outcome contains conditional approvals with no vetoes: (i) extracting all conditions, (ii) injecting the conditions into a synthesis prompt as mandatory constraints, (iii) generating a final advisory satisfying each condition;
- (g) deterministically mapping each vote outcome to the status of a corresponding task in an externalized investigation plan, wherein APPROVE and APPROVE_WITH_CONDITION map to a complete status and VETO and error outcomes map to a failed status.

**Claim 2.** The method of Claim 1, further comprising injecting the proposer agent's tool-result observations into the quorum's reviewing context as a `cross_agent_findings` data block prior to voting, enabling each reviewing agent to verify the proposal against the same observations the proposer used.

**Claim 3.** The method of Claim 1, further comprising maintaining a per-investigation shared signature set indexed by `(tool_name, arguments_hash)`, and when any agent attempts a tool invocation whose signature is already in the set, returning the previously-cached evidence rather than re-executing the tool, thereby deduplicating tool calls across the quorum.

**Claim 4.** The method of Claim 1, further comprising, prior to the voting round: (i) submitting the proposer's draft proposal to a classification model trained on prior advisory outcomes, (ii) responsive to the classifier predicting a negative outcome with confidence exceeding a threshold, injecting a soft-signal annotation into the voting context indicating predicted negative outcome, said annotation being advisory rather than vetoing.

**Claim 5.** The method of Claim 1, wherein when a vote string returned by an agent is not in the predefined set of valid verdicts, the verdict is normalized to VETO via a sanitization step ensuring the fail-safe default applies even on adversarial or malformed agent output.

**Claim 6.** A system comprising at least one processor and a non-transitory computer-readable medium storing instructions which, when executed, perform the method of any of Claims 1–5.

**Claim 7.** A non-transitory computer-readable storage medium containing instructions which, when executed by a processor, perform the method of any of Claims 1–5.

## Code Mapping
| Claim Element | File:line |
|---|---|
| Risk-tier classification | `arvis_core/swarm/queen.py:513-548 _classify_risk_tier` |
| Safety-keyword floor | `arvis_core/swarm/queen.py:521-547 _SAFETY_KEYWORDS_RE` |
| Quorum spawning for T3 | `arvis_core/swarm/queen.py:184-216` |
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

## Prior Art Defense
- **Classical BFT (Paxos, Raft, PBFT)**: state-machine replication, binary votes, no LLM coupling, no domain semantics.
- **LangChain / LangGraph**: linear orchestration, no parallel fault-tolerant voting, no veto-on-error default.
- **LLM ensemble voting (Self-Consistency, Tree-of-Thoughts)**: aggregation strategies, not consensus with veto + condition propagation + cross-agent evidence sharing.
- **Rule-based BMS alarms**: no AI, no consensus.
- **Existing BMS expert systems (Honeywell EBI, Schneider EcoStruxure)**: rule-based, no multi-agent LLM, no graded-vote consensus.

**Key differentiators:**
1. **Graded vote semantics with condition propagation** (Claim 1(c) and 1(f)) — not present in classical BFT or LLM ensembling
2. **Fail-safe veto on any agent failure** (Claim 1(d) and Claim 5) — defensive default unique to safety-critical industrial context
3. **Cross-agent evidence sharing** (Claim 2) — proposer's tool results injected into reviewer context
4. **Veto-constraint re-routing** (Claim 1(e)) — extracted veto reasoning as constraints for alternate nodes
5. **Pre-vote outcome prediction soft signal** (Claim 4) — cost-aware filtering before reviewer tokens burn

## Why This Filing Is Priority 3
- Strong novelty across multiple claim elements
- Largest code surface to draft (most claim elements)
- Highest patent-attorney work to translate code → claims
- Industrial-anchored (helps §101 defense)
- Most directly blocks competitor BMS-AI implementations

---

# Trade Secrets Register

Items below should **not** be patented (would require disclosure) but should be protected via:
- Private repository access controls
- Contractor NDAs covering all team and consultants
- Customer data isolation per building
- Defensive publication of derivative concepts to prevent competitor patents

| # | Asset | Type | Why Trade Secret |
|---|---|---|---|
| TS1 | 55-tool BMS surface (`tools/definitions/*`) | Domain encoding | 18+ months of engineering to replicate; reveals operational scope |
| TS2 | GSAS optimizer + scoring algorithms (`gsas_*.py`) | Regulatory expertise | Qatar GSAS/GORD specificity, certified compliance path |
| TS3 | ASHRAE RP-1312 rule encoding | Codified domain knowledge | Specific to BMS fault detection, decades of standards work |
| TS4 | Physics bounds dictionary `_BOUNDS` (`verifiers/physics.py`) | Qatar-tuned thresholds | Conservative commercial-Qatar ranges, calibration insights |
| TS5 | Bedrock channel cost map (`agent_unified/llm.py BEDROCK_MODEL_MAP`) | Cost-optimization heuristic | Model selection per task type, tuned by experience |
| TS6 | Tool cost classification (`_TOOL_COST_MAP`) | Operational tuning | Per-tool cost class, calibrated by measured usage |
| TS7 | Carrier 30XA bi-quadratic curve coefficients (post-simulator build) | Manufacturer-data + tuning | Specific equipment curves, refined by commissioning data |
| TS8 | Per-building physics parameters (envelope UA, thermal mass) | Site-specific commissioning | Months of building-specific data gathering |
| TS9 | BFT prompt templates (proposer/quorum/synthesis system prompts) | Prompt engineering IP | Months of iteration; reveals reasoning approach |
| TS10 | Distilled rules schema + TTL strategy | Memory hygiene IP | Specific table design + retention policy |
| TS11 | Skillbook Bayesian update curves | Domain memory IP | Update functions tuned for BMS context-drift |
| TS12 | Marina adversarial test suite (`scratch/marina_*`) | Eval methodology IP | Adversarial scenario design, judge panel structure |

**Protection actions:**
- Move TS1, TS9 into a private submodule with access restricted to core team
- Encrypt TS7, TS8 at rest in per-building configuration
- Apply NDA template to all contractors before access to repo
- Add audit logging on access to TS5, TS6 (cost-sensitive operational data)
- Hold TS12 in private repo separate from open-source-able core components

---

# Cost & Timeline

## Patent Cost Estimate (US-Only, Provisional Only)

| Item | Low | High |
|---|---|---|
| App 1 provisional drafting + filing | $3,000 | $5,000 |
| App 2 provisional (post-simulator-build) | $3,000 | $5,000 |
| App 3 provisional (largest code surface) | $3,000 | $5,000 |
| **Total provisional filings (3)** | **$9,000** | **$15,000** |

## Conversion to Non-Provisional (Month 12)

| Path | Cost (US) | When |
|---|---|---|
| US non-provisional (each) | $10,000–15,000 | Month 11–12 |
| PCT international filing | $30,000–50,000 | Month 11 |
| EU national phase entry (per country) | $5,000–10,000 each | Month 30 |
| Qatar / GCC patent filing | $5,000–8,000 each | Month 6–9 (parallel) |

**Total program cost over 30 months** (3 patents, US + PCT + 3 EU + Qatar):
**~$120,000–180,000** if pursuing full international coverage.
**~$50,000–70,000** if US-only with selective PCT.

## Timeline

| Month | Milestone |
|---|---|
| 0 (today) | Patent counsel selected (software/AI/industrial-control experience required) |
| 0–1 | App 1 provisional filed |
| 1–2 | Simulator built (Application 2 prerequisite) |
| 2–3 | App 2 provisional filed |
| 3–4 | App 3 provisional filed |
| 6–9 | Qatar national filing (if pilot landing in Qatar) |
| 11 | PCT international filing decision point |
| 12 | US non-provisional conversion deadline |
| 18 | PCT publication |
| 30 | National-phase entry deadline (EU, UK, etc.) |

---

# Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **§101 abstract-idea rejection (US)** | Anchor every claim to concrete technical effect (preventing equipment damage, energy conservation violation, etc.). Industrial-domain framing. Specify data structures (`InvestigationPlan` schema, `EvidenceLedger` structure, `VoteVerdict` enum). Counsel with §101 experience post-Alice/Mayo. |
| **Public disclosure before filing** | **No external talks, blog posts, papers, or customer demos without NDA before provisional filing.** This is the single highest-risk item. |
| **Prior-art search inadequate** | Counsel must conduct novelty searches against 2025–2026 publications in agent-systems, MLOps, and industrial-AI spaces. Move fast — the field publishes constantly. |
| **Claim 2(c) of App 2 overstates current implementation** | Build the simulator before filing (2 weeks). Otherwise claim narrows during prosecution. |
| **Competitor files first** | File provisionals quickly (within 30 days). Establishes priority. Subsequent improvements covered in continuation-in-part filings. |
| **Open-source contamination** | Verify no patentable code path is derived from GPL/AGPL or copyleft sources. Audit licenses on `pgmpy`, `chromadb`, `xgboost`, `lifelines`, etc. — all MIT/Apache-compatible. Confirm by counsel. |
| **Customer-contract IP transfer clauses** | Review any existing customer or pilot agreements — ensure inventions remain ARVIS-assigned, not work-for-hire to customer. |
| **Employee/contractor IP assignment** | All contributors must have signed IP-assignment agreements before any code commit related to patentable methods. |

---

# Next Actions (Sequential)

## Week 0 (Now)
1. Engage patent counsel with software + AI prosecution experience (US + ideally GCC)
2. Confirm no public disclosures of these methods exist (audit blog, talks, papers, GitHub)
3. Confirm IP assignment agreements signed by all contributors
4. License audit of dependencies (verify all permissive)

## Week 1–2
5. Draft Application 1 provisional (highest priority, no build dependency)
6. File App 1 provisional, lock priority date
7. Begin simulator implementation (Application 2 prerequisite — see separate build plan)

## Week 3–4
8. Complete simulator build + integration tests
9. Draft Application 2 provisional with locked simulator code references
10. File App 2 provisional

## Week 5–6
11. Draft Application 3 provisional (largest claim surface, most code mapping)
12. File App 3 provisional

## Month 6–9
13. Pilot launches in Qatar (separate from patent track)
14. File Qatar national patents if commercial pilot validates
15. Begin PCT prep work

## Month 11–12
16. US non-provisional conversion + PCT decision
17. Continuation-in-part filings for any new improvements during the year

---

# Summary Recommendations

1. **File 3 US provisionals within 60 days.** Cost: $9–15K. Priority date locked.
2. **Application 1 (Abstention Gate) first** — strongest novelty, broadest applicability, no build dependency.
3. **Build the physics simulator (2 weeks) before filing Application 2.** Without it, Claim 2(c) is unsupported.
4. **Application 3 (BFT Consensus) requires the most claim drafting work** — engage counsel early for this one.
5. **Hold the 12 trade-secret assets closed.** They are the deepest moat; patents are insurance, trade secrets compound.
6. **No public disclosure of these methods until provisionals filed.** Single highest-risk action item.
7. **Audit IP-assignment agreements** for all contributors before counsel engagement.
8. **Long-term moat is non-patentable**: accumulated operator interactions, per-building skillbook, ML training data, audit trails. Patents protect the method; data builds the durable advantage.

---

# Appendix A — Code Citation Index

For patent counsel reference, all code paths cited in claims:

```
arvis_core/
├── evidence.py                      # App 1 — Evidence + EvidenceLedger
├── plan.py                          # App 1 — coverage; App 3 — _shared_call_sigs, task lifecycle
└── swarm/
    ├── consensus.py                 # App 3 — VoteVerdict, run_debate, fail-safe veto
    ├── node.py                      # App 3 — spin dedup, cross-node check
    └── queen.py                     # App 2 — regen-or-abstain, verb map; App 3 — risk tier, BFT, conditions

agent_commercial/
├── bms_llm_agent.py                 # App 1 — abstention gate (lines 1042-1180)
├── grounding_guard.py               # App 2 — supports (background context)
├── tools/handlers/
│   └── ml.py                        # App 1 — structured ML_UNAVAILABLE sentinel
└── verifiers/
    ├── physics.py                   # App 2 — current bounds-check; replace with simulator
    └── simulator/                   # App 2 — TO BE BUILT
        ├── engine.py
        ├── chiller.py
        ├── cooling_coil.py
        ├── ahu.py
        ├── building.py
        └── loop.py

agent_cognitive/
└── prediction_engine.py             # App 1 — drift_score generation
```

---

# Appendix B — Glossary

- **Abstention Gate**: a code-enforced decision point that suppresses LLM advisory output when multi-signal confidence is insufficient.
- **BFT (Byzantine Fault-Tolerant)**: consensus protocol class where the system functions correctly despite up to a bounded fraction of nodes failing in arbitrary ways.
- **DOE-2**: building energy simulation standard whose bi-quadratic chiller curves are widely used in commercial HVAC engineering.
- **Drift score**: numeric measure of how far an ML model's predictions deviate from observed reality, used as a freshness/health signal.
- **EIR (Energy Input Ratio)**: inverse of COP; energy consumed per unit cooling delivered.
- **Evidence Ledger**: structured per-investigation store of tool-result and document-chunk entries with provenance metadata.
- **GSAS / GORD**: Global Sustainability Assessment System / Gulf Organisation for Research & Development — Qatar's green-building certification system.
- **InvestigationPlan**: externalized code-state object representing the active investigation, with tasks, evidence, budget, and audit trail.
- **NTU-effectiveness method**: standard ASHRAE/textbook method for predicting cooling-coil heat-transfer effectiveness.
- **PLR (Part-Load Ratio)**: chiller operating ratio (current load / rated capacity).
- **§101 (Section 101)**: US patent statute defining patent-eligible subject matter; software/AI inventions face increased scrutiny post-Alice v. CLS Bank (2014).
- **T1/T2/T3 risk tier**: ARVIS's three-level query classification (lookup / diagnostic / actionable).
- **Veto-Constraint Re-routing**: ARVIS-specific pattern of extracting veto reasoning from BFT debate and submitting it as explicit constraints to alternate nodes.

---

*Document prepared for patent counsel engagement. Not legal advice. Patentability requires formal novelty search and counsel review.*
