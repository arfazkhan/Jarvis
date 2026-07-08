# fbq — WhatsApp AI Project Manager for Interior Vendors

AI agent inside **hosted WhatsApp groups** (official Business Cloud API) for interior
contractors: reads the group (text / voice / photos / PDFs), writes structured records to a
**plan-driven backend**, surfaces intelligence back into chat. See the PRD (v2.0) — this
package is the agent + plan engine, built on the ArvisX substrate.

**Discipline carried over from ArvisX (non-negotiable):**
- Grounding is law — the LLM never states a fact a tool didn't return; "don't know" over fabrication.
- Risk-routed writes — Lane A (whitelisted auto + undo) · Lane B (confirm-in-chat) · Lane C (structured forms). The LLM proposes; only deterministic executors mutate state.
- Deterministic floor — every feature degrades to a deterministic path without an LLM.

## Capability map (PRD §5 → build strategy)

| ID | Capability | Strategy |
|----|------------|----------|
| C1 | Message ingestion & store | NEW adapter (Cloud API webhook) → reuse ArvisX event/store patterns |
| C2 | Speech-to-text (HI/KN/EN) | NEW (provider adapter; week-1 benchmark is blocking) |
| C3 | Image understanding | NEW-ish (ArvisX vision pipeline pattern exists; caption+classify V1) |
| C4 | Document parsing | REUSE `arvisx.manual_skills.extract_text` (pypdf) |
| C5 | NLU extraction engine | PARTIAL reuse (decision/lesson capture pattern) → typed taxonomy is new |
| C6 | Task-matching layer | NEW (adjacent to ArvisX fuzzy matching) |
| C7 | Risk router + write lanes | REUSE ArvisX propose→confirm→execute + deterministic commands |
| C8 | Domain/Plan API | NEW endpoints on the ArvisX FastAPI pattern |
| C9 | **Workflow/plan engine** | **NEW — this package, `plan_engine.py` (built first)** |
| C10 | Outbound messaging | REUSE ArvisX notifier/queue pattern (swap Baileys → Cloud API sender) |
| C11 | Retrieval & grounding | REUSE ArvisX grounding guard + semantic recall (per-group isolation added) |
| C12 | Identity & role mapping | REUSE ArvisX roster + lid_map lessons |
| C13 | Event log & replay | PARTIAL reuse (chat_log) → formal replayable event store |
| C14 | Consent & privacy (DPDP) | NEW |
| C15 | Composition engine | REUSE ArvisX digest/report/PDF composition |

## Layout
- `models.py` — plan/task/template dataclasses (PRD-typed)
- `plan_engine.py` — C9: template instantiation, dependency scheduler, date recompute,
  slip/shift reporting (feeds F14 dependency-impact alerts), next-task triggers (F15)
- `seeds/phase3_manufacturing.json` — starter Phase-3 plan template
- `tests/` — hermetic engine tests
