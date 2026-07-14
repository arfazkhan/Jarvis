# Fix Plan — All Phases Pass + ML Online Task List

## CHUNK A — Infra & Guardrails
- [ ] 1. SQLite WAL serialization
  - [ ] Implement write-lock serialization (`asyncio.Lock`) inside `BMSDatabase._execute` in `agent_commercial/database.py`.
  - [ ] Verify standard WAL / synchronous NORMAL connection parameters.
- [ ] 2. Context-budget Guardrail (Pre-truncate Evidence Ledger)
  - [ ] Implement `evidence_ledger` pre-truncation (~80k tokens) inside synthesis assembly in `arvis_core/swarm/queen.py`.
  - [ ] Prioritise cited evidence and drop oldest ones to satisfy Bedrock context limits.

## CHUNK B — ML Pipeline Online
- [ ] 3. FDD VAE Bootstrap During P1 Distiller
  - [ ] Add unsupervised VAE autoencoder training logic for `chiller`, `ahu`, and `cooling_tower` at the end of the P1 observation window in `agent_commercial/main.py`.
  - [ ] Confirm FDD `.train()` and `.save()` operations trigger successfully.
- [ ] 4. MLFacade & ModelRegistry Persistence
  - [ ] Update `ModelRegistry` in `model_registry.py` to persist trained models to a shared stable folder (`data/models/`).
  - [ ] Handle model loading and singletons gracefully at startup.
- [ ] 5. pgmpy Causal Fallback for Root Cause
  - [ ] Add pgmpy static topology fallbacks (Chiller ➔ Tower, etc.) in `causal_inference.py` to gracefully return `ml_status: structural_only` or valid structural confidence rather than `0.0`.

## CHUNK C — Per-Phase Scorer & Grounding Fixes
- [ ] 6. P1 — Silent-phase suppressor
  - [ ] Implement the `silent_mode` responder to concise-confirm query turns during the P1 silent window.
- [ ] 7. P3 — Short-cycling Grounding Facts
  - [ ] Build a deterministic facts dictionary (`MUST_RESPECT_FACTS`) before synthesis in `queen.py`.
  - [ ] Enforce the facts table in `NumericAudit` to strip assertions (short-cycling, surge) that mismatch actual telemetry.
- [ ] 8. P7 — Citation Count Enforcement
  - [ ] Enforce count-to-citation match rules in the synthesis prompt in `queen.py`.
  - [ ] Add a regex check to verify that numeric counts are backed by at least N inline citation IDs.
- [ ] 9. P_AUTO — Watchdog Threshold learned ceiling
  - [ ] Limit anomaly watchdog learned thresholds to a max of `3σ` of physical sensor spec in `anomaly_watchdog.py`.
- [ ] 10. P6 — Confidence Calibration
  - [ ] Ban free-form percentage narratives unless backed by a source, forcing strictly structured `Confidence: High/Medium/Low` based on active corroboration.
- [ ] 11. Agentic Judge Calibration
  - [ ] Apply a strict anti-inflation cap (max 5.0) in the judge rubric if any stripped hallucinations or H4 faithfulness failures are registered.
