# AllGud — Prompt-Hardening Plan ("the steals")

Distilled from a prompt-architecture review. Philosophy: **prompt = persona + task contract; everything else (routing, authz, business rules, formatting) lives in code/config.** Most of that is already true in AllGud — this plan closes the four gaps worth closing *now* for a single-building, rate-limited pilot.

Build order: **#4 → #1 → #2 → #3**.

---

## #4 — Structured extractor outputs *(quick de-risk, do first)*
**Current:** `extract_action` / `extract_decision` / `lesson_from_issue` already use `ask_json`, but `ask_json._call()` sends no `response_format`; it scrapes JSON out of prose via `_extract_json()` and returns `{}` on failure (logged warning). Chatty models → silent empty extraction.
**Change:** pass `response_format={"type":"json_object"}` on the `create()` call, with try/except fallback to the current prose-scrape for providers that reject it (K2Think/nvidia). Optional strict JSON-schema for `extract_action`'s slots.
**Files:** `llm_client.py`. **Effort:** S · **Risk:** Low (fallback already exists).

## #1 — Unified phrasing sandbox + widened invariance check *(the primitive)*
**Current:** `phrase_line()` + `_PHRASE_SYS` + `_numbers_grounded()` warm alert wording, but invariance = numbers only, and only alerts route through it. Busy-message, confirmations, digests, lapse/recognition are separate.
**Change:** generalize `phrase_line` → `render_message(llm, template, *, facts="", locks=None)`; replace `_numbers_grounded` with `_invariants_preserved(out, template, extra)` locking **numbers, `*bold*` spans, leading emoji, names, IDs/dates** verbatim (else return template). Route the safe-to-warm templates through it: `_LLM_BUSY_MSG`, `_lapse_message` / `recognition_message`, action confirmations, report/digest intros. **Q&A answers keep their own `verify_grounded` — different contract.**
**Files:** `checklist_skills.py`, `checklist_intel.py`, `api.py`. **Effort:** M · **Risk:** Low (always degrades to template).

## #2 — Golden eval set + CI gate *(locks in #1 and #3)*
**Current:** 24 arvisx test files run only locally; `ci.yml` covers only the legacy `agent/` tree — arvisx has **zero CI coverage**.
**Change:** `arvisx/tests/test_golden_qa.py` — ~30 real messages, assert **invariants not exact strings** (correct route, grounded, role-scoped, fallback fires when `llm=None`). Offline mode always in CI; `@pytest.mark.online` for manual live runs. Seed `fixtures/golden_messages.json` (grow from production misroutes). New `arvisx-test` CI job: `pytest arvisx/tests/ -m "not online"`. Leave the legacy job untouched.
**Files:** new test + fixtures, `ci.yml`. **Effort:** M · **Risk:** Low.

## #3 — Shift business rules → config *(cleanup)*
**Current:** "morning ≈ Shift I, afternoon/evening ≈ Shift II, night ≈ Shift III" hardcoded in `_QA_SYSTEM`. Brittle — assumes every building names shifts I/II/III.
**Change:** derive shift synonyms from real template timings via `shift_synonyms(building)`, consumed as data by the agent; trim the hardcoded prompt line. Cover with a golden test.
**Files:** `checklist_intel.py` (+ trim `checklist_skills.py`). **Effort:** S · **Risk:** Low-Med.

---

## Explicitly OUT (deferred — needs volume/budget)
- Tier-1 classifier as a **second** LLM call per message (doubles token burn while rate-limited; revisit at multi-building with a cheap/distilled classifier).
- Fine-tune from production labels (no volume at 1 building — harvest into the eval set instead).
- 20-intent taxonomy (start ~6, grow from misroutes).

## Ship/verify
`pytest arvisx/tests/` green → #4/#1 are API-image-only → same build→GHCR→droplet flow. #3 wants a live WhatsApp shift-word smoke.
