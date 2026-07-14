# Implementation Plan — All Phases Pass + ML Online

This plan hardens ARVIS BMS to ensure a 100% pass across all simulation phases (S1 + S2), resolves persistent database write locks, brings online unsupervised machine learning pipelines (FDD autoencoders, Bayesian network root causes, and model persistence), and fixes scoring inconsistencies.

---

## User Review Required

> [!IMPORTANT]
> **1. Serializing DB Writes & WAL Enforcement**
> We will introduce a single shared `asyncio.Lock` inside `BMSDatabase._execute` to completely serialize database writes during high-concurrency loops (like daily digest calibrations and background telemetry flushes). This guarantees that "database is locked" errors will drop to exactly 0.

> [!IMPORTANT]
> **2. Auto-Bootstrap FDD VAE During P1**
> The unsupervised Fault Detection and Diagnostic (FDD) VAE autoencoders will be actively trained at the end of the P1 28-day observation phase using actual telemetry. We will save them via `ModelRegistry` in a stable directory (`data/models/`) to survive run-specific sandboxing.

> [!IMPORTANT]
> **3. Grounding Cross-Check: SHORT_CYCLING Deterministic Facts**
> To prevent the LLM from hallucinating categorical assertions like "short-cycling detected" when actual cycle counts are exactly zero, we will construct a deterministic facts table (`MUST_RESPECT_FACTS`) before synthesis. If any categorical claims mismatch actual telemetry, `NumericAudit` will dynamically strip the claims.

---

## Proposed Changes

### CHUNK A — Infrastructure & Core Guardrails

#### 1. SQLite WAL serialization
* **[MODIFY] [database.py](file:///e:/Automation/agent_commercial/database.py)**
  * Introduce an `asyncio.Lock` shared instance within `BMSDatabase` for write transactions.
  * Wrap database execution in a serialization lock if the query is a write operation (e.g., `INSERT`, `UPDATE`, `DELETE`, or `REPLACE`).
  * Enforce standard WAL and synchronous NORMAL modes across all connection paths.

#### 2. Context-budget Guardrail (Pre-truncate Evidence Ledger)
* **[MODIFY] [queen.py](file:///e:/Automation/arvis_core/swarm/queen.py)**
  * Add a pre-truncation helper inside synthesis assembly: hard-truncate `evidence_ledger` to `~80,000` tokens (approximated by character count) before passing to the LLM.
  * Sort and select evidence packets prioritising cited ones and dropping oldest ones first to stay within strict Bedrock token ceilings.

---

### CHUNK B — ML Pipeline Online

#### 3. FDD VAE Bootstrap During P1 Distiller
* **[MODIFY] [main.py](file:///e:/Automation/agent_commercial/main.py)**
  * Inside `_calibration_loop()` or after ObservationDistiller runs, trigger VAE training loop for each equipment type (`chiller`, `ahu`, `cooling_tower`) using accumulated 28-day telemetry.
  * Call `fdd.train(df)` followed by `fdd.save()` to persist models.

#### 4. MLFacade & ModelRegistry Persistence
* **[MODIFY] [model_registry.py](file:///e:/Automation/agent_commercial/ml/model_registry.py)**
  * Point `ModelRegistry` storage path to `data/models/` (a stable path shared across run boundaries) instead of isolating within ephemeral `runs/<run_id>/` database sandboxes.
  * Load singletons safely at startup; fallback gracefully if not yet trained.

#### 5. Bayesian Network structural fallback
* **[MODIFY] [causal_inference.py](file:///e:/Automation/agent_commercial/ml/causal_inference.py)**
  * Hardcode a static pgmpy structural template fallback representing building topology cascades (e.g., Chiller ➔ Tower, AHU ➔ VAV) so that the engine returns `ml_status: structural_only` or valid structural confidence rather than `0.0` when telemetry is sparse.

---

### CHUNK C — Per-Phase Scorer & Grounding Fixes

#### 6. P1 — Silent-phase suppressor
* **[MODIFY] [queen.py](file:///e:/Automation/arvis_core/swarm/queen.py) & [main.py](file:///e:/Automation/agent_commercial/main.py)**
  * If a user query lands during the P1 silent window (observation phase), route to a highly constrained silent-mode responder that returns a concise 1-line confirmation and defers full advisory to prevent breaking the phase's silent criteria.

#### 7. P3 — Short-cycling Grounding Facts
* **[MODIFY] [queen.py](file:///e:/Automation/arvis_core/swarm/queen.py)**
  * Compile a deterministic facts dictionary (e.g., `{CH-01: {short_cycling: 0.0}, CH-02: {short_cycling: 0.0}}`) prior to synthesis.
  * Inject this dictionary as `MUST_RESPECT_FACTS` inside the synthesis system prompt.
  * In `NumericAudit`, scan for assertions of short-cycling, liquid slugging, or surge, and strip them if they mismatch the actual facts table.

#### 8. P7 — Citation Count Enforcement
* **[MODIFY] [queen.py](file:///e:/Automation/arvis_core/swarm/queen.py)**
  * Update synthesis instructions: *"If you state a count N, cite N evidence IDs inline. Otherwise say 'multiple documented cases (5 cited)'."*
  * Run a post-synthesis regex check to verify that paragraph numbers (e.g., "14 instances") are backed by at least `N` citation references.

#### 9. P_AUTO — Watchdog Threshold Ceiling
* **[MODIFY] [anomaly_watchdog.py](file:///e:/Automation/agent_commercial/anomaly_watchdog.py)**
  * Implement a hard ceiling on learned thresholds in `AnomalyWatchdog` (max `3σ` of physical sensor spec) to prevent daily calibration cycles from diluting sensitivity when synthetic noise is injected.

#### 10. P6 — Confidence Calibration
* **[MODIFY] [queen.py](file:///e:/Automation/arvis_core/swarm/queen.py)**
  * Ban inline percentage narratives (e.g., "73% conviction") unless explicitly backed by a source.
  * Force output format to use strictly structured `Confidence: High/Medium/Low` based on active corroboration levels.

#### 11. Agentic Judge Calibration
* **[MODIFY] [agentic_judge.py](file:///e:/Automation/agent_commercial/scoring/agentic_judge.py) (or scoring runner)**
  * Incorporate a strict anti-inflation rubric: if the response has any stripped hallucinations or H4 faithfulness warnings, cap the maximum possible judge score at `5.0`.

---

## Verification Plan

### Automated Tests
- Run `pytest tests/test_skillbook_ingestion.py`
- Run the full suite of BMS unit tests: `pytest tests/test_bms/`

### Manual Verification
- Deploy simulation runs using `marina_prove_it.py` and inspect logs to confirm:
  1. `database is locked` instances = 0.
  2. VAE training logs show `is_trained=True` at the end of P1.
  3. No `Context-length BadRequestError` or `ML UNAVAILABLE` errors.
  4. S1 + S2 simulator results show 100% Phase Passes.
