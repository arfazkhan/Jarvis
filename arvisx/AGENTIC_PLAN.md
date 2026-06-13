# ArvisX Agentic Layer — Implementation Plan

The 11 AI layers on top of the Phase-0 digitized checklist. Built on machinery ArvisX
already has: native tool-calling (K2Think), a ReAct loop, the skillbook (institutional
memory), and the wake/sleep (idle/awake) scheduler.

## Guiding principles
1. **Deterministic floor first.** Counting / threshold / trend = code, not LLM. The LLM only reasons, summarizes, phrases.
2. **One agent, many skills.** A shared tool set + per-layer skill-prompts + triggers — not 11 agents.
3. **Grounding is law.** Every number traces to a tool output. Confidence is evidence-count-derived. Abstain on thin data. No fabricated %.
4. **No sensors needed now.** The checklist entries are the data substrate; the same engine lights up on telemetry in Phase 1.
5. **Each phase independently demoable.**

## The 11 layers, tiered
| Layer | Verdict |
|---|---|
| 1 Inspection Assistant | deterministic, now (drift on entry history) |
| 2 Supervisor (missing + contradiction) | deterministic, now (missing exists) |
| 5 PPM Planner (condition-based) | deterministic, now (needs PPM schedule) |
| 7 Asset Health Score | deterministic, now (needs asset tagging) |
| 8 Compliance Officer | deterministic, now (needs PPM schedule) |
| 9 Work-Order Agent | skillbook + light LLM |
| 3 Root-Cause Investigator | LLM — reuse commercial ARVIS grounded RCA |
| 4 Shift Handover | LLM summarize — first agent (highest value/lowest risk) |
| 11 Digital-Twin Q&A | LLM over asset-health |
| 10 Vision | multimodal; photos already exist; show + confirm |
| 6 Failure Prediction | DEFER — grounded watchlist (no %) until sensors |

## Phases
- **S — Substrate**: asset tagging on items → PPM scheduling (due/overdue + run-hours forecast) → asset history (`/assets/{id}/history`). The data spine; finishes 2 of the remaining core features.
- **A — Deterministic analyzers** (`analyzers.py`): L1, L2, L7, L8. No LLM. Surfaced via API + digest + WhatsApp alerts.
- **B — Agent core**: shared read-only tools (item/asset history, issues, health, ppm, baseline) + ReAct runner + skillbook + triggers + idle/awake scheduler + the fabricated-number guard.
- **C — LLM agents**: C1 L4 Handover, C2 L3 RCA (port commercial), C3 L9 Work-Order, C4 L11 Q&A.
- **D — Vision** (L10): OCR-the-gauge + condition detection; show photo + extracted value for one-tap confirm.
- **E — Failure prediction** (L6): grounded watchlist now; real probability + window when sensors land.

## Grounding / confidence model
- Numbers in any agent output MUST appear in a tool result, else fall back to deterministic text.
- Confidence band = number of independent evidence sources (existing `confidence_band`), never an LLM guess.
- Abstain (say "insufficient history") rather than fabricate.

## Cross-cutting
- Tests: hermetic for S/A; golden-transcript + grounding-guard unit test for C.
- WhatsApp: analyzers → issue alerts; L4 → assignee DM; L7/L8 → manager digest. Reuses the notification queue.
- One product line — "digitized ops today, agentic + sensor-fed tomorrow." Not a fork.

## Build order
S → A → B → C1(Handover) → C2(RCA) → C3 → C4 → D → E.
