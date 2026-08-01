# CBI Manual→Skill Compiler — Build Plan (commercial-bms)

Scope: build the equipment-manual → `SKILL.md`+chapters compiler and chapter-level
router described in *Compiled Building Intelligence*, wired into the EXISTING
commercial-bms code. This is the one genuinely net-new artifact; everything else
in that document (grounding, cross-equipment RCA, fold-in, BACnet, GSAS) already
exists on this branch.

Branch: `commercial-bms` (HEAD `d1c4dfc` — dependency-graph cascade impact).

---

## 0. Decisions locked

- **Storage: files + registry.** Compiled static skills live on disk as
  `data/skills/<equipment_key>/{SKILL.md, chapters/*.md, patterns.md, glossary.md,
  cheatsheet.md, meta.json}`. A `compiled_skill` registry table in `arvis_bms.db`
  maps `equipment_id → skill_dir + source_hash + version + status`.
- **skillbook.py stays the fold-in / learned layer.** The compiler NEVER writes
  learned knowledge. Runtime overlays `skillbook.get_relevant_skills()` on top of
  the compiled manual lens. This is the guardrail against two-sources-of-truth.
- **First equipment: Otis Gen2 elevator.** Manual already on disk. NOTE: it is a
  228-page fully-scanned image PDF (0 extractable text) — so OCR/Docling is
  required in Phase 1 M1, not optional.

---

## 1. Architecture

```
COMPILE (offline)                           RUNTIME (online)
─────────────────                           ────────────────
manual.pdf                                  alarm / query
   │                                            │
   ▼                                            ▼
[extractor]  ── text + page markers        [skill_router]
   │            (OCR/Docling for scans)        │ 1. equipment resolve
   ▼                                            │ 2. topic classify
[skill_analyzer] ── LLM (frontier)             │ 3. chapter select
   │  SKILL.md + chapters + patterns            ▼
   │  + glossary + cheatsheet              load SKILL.md core (~4k)
   ▼                                        + chapter (~1k)
[grounding gate] ── every framework/param       │
   │  must cite source page or is flagged       ▼
   ▼                                        agent reasoning (cheap model)
[registry write] ── data/skills/<eq>/        + overlay skillbook.get_relevant_skills()
   arvis_bms.db: compiled_skill row              │  (building-specific learned reality)
                                                  ▼
                                             cross-equipment chain via BMSGraph
                                             get_all_upstream/downstream
```

Two-source-of-truth guardrail: compiled files = "what the manufacturer says";
skillbook = "what this building actually does". Router merges at read time only.

---

## 2. New files / touched files

| File | New? | Role |
|---|---|---|
| `agent_commercial/skills/skill_compiler.py` | new | orchestrator: extract→analyze→gate→write |
| `agent_commercial/skills/manual_extractor.py` | new | PDF→text w/ page markers; OCR/Docling for scans |
| `agent_commercial/skills/skill_analyzer.py` | new | LLM structural analysis → SKILL.md + chapters |
| `agent_commercial/skills/skill_registry.py` | new | registry table CRUD + source-hash freshness |
| `agent_commercial/skills/skill_router.py` | new | 3-stage runtime routing + fallback chain |
| `agent_commercial/document_ingestion.py` | edit | add `doc_type="manual"` branch → skill_compiler |
| `agent_commercial/main.py` | edit | watcher (~line 580) routes `.pdf` in manuals/ to compiler |
| `agent_commercial/bms_llm_agent.py` | edit | expose `load_equipment_skill` tool (~line 829 minimal-set) |
| `agent_commercial/grounding_guard.py` | reuse | compile-time citation gate (page-ref presence) |
| `agent_commercial/graph.py` (`BMSGraph`) | reuse | Phase-2 cross-equipment chaining |

---

## 3. Compiled skill on-disk format

```
data/skills/otis-gen2-elevator-e1/
  SKILL.md          # ~4k tok: named frameworks, critical params, chapter index, anti-patterns
  chapters/
    fault-codes.md  # ~1k tok each, one functional area
    startup.md
    maintenance.md
    control-logic.md
  patterns.md       # named fault patterns: signature→diagnose→root cause→resolution
  glossary.md       # terms + normal ranges + chapter xref
  cheatsheet.md     # if symptom X → check Y → do Z
  meta.json         # source_hash, source_pages, model, compiled_at, version, confidence
```

`meta.json` is the freshness anchor (source_hash) and the audit trail (every
framework carries `source_pages`).

## 4. Registry schema (in arvis_bms.db)

```sql
CREATE TABLE IF NOT EXISTS compiled_skill (
  equipment_key   TEXT PRIMARY KEY,   -- e.g. otis-gen2-elevator-e1
  equipment_id    TEXT,               -- BMS instance id, nullable until bound
  skill_dir       TEXT NOT NULL,
  source_file     TEXT NOT NULL,
  source_hash     TEXT NOT NULL,      -- sha256 of source PDF
  version         INTEGER DEFAULT 1,
  status          TEXT DEFAULT 'active', -- active|stale|flagged|compiling
  confidence      REAL,               -- min framework grounding confidence
  compiled_at     TEXT,
  model           TEXT
);
```

---

## 5. Phases & milestones

### Phase 1 — Compiler + single-equipment reasoning (~1.5 wk)
- **M1 Extractor**: `manual_extractor.py`. Text PDFs via pymupdf; scanned (Otis)
  via OCR/Docling. Output: page-marked text. Success: Otis 228pg → clean text,
  page refs preserved.
- **M2 Analyzer**: `skill_analyzer.py`. Frontier model → SKILL.md + chapters +
  patterns/glossary/cheatsheet. Success: domain-plausible fault frameworks with
  page cites.
- **M3 Grounding gate**: every framework/critical-param needs a `source_pages`
  ref; missing → skill flagged `status=flagged`, not published silently. Reuse
  GroundingGuard pattern. Success: ungrounded frameworks are caught.
- **M4 Registry + single-equipment query**: `skill_registry.py` + agent tool
  `load_equipment_skill`. Success: operator query about Otis answered from
  compiled skill, no manual dump, response grounded.

### Phase 2 — Router + cross-equipment (~1 wk)
- **M5 Router**: `skill_router.py` 3-stage (equipment resolve → topic classify →
  chapter select) + fallback → patterns.md → general ASHRAE skill.
- **M6 Cross-equipment chain**: chain via `BMSGraph.get_all_upstream`. Success:
  Floor-7-style multi-skill RCA under one token budget.
- **M7 Runtime overlay**: after loading compiled chapter, overlay
  `skillbook.get_relevant_skills(context)` so learned quirks win over stale manual.

### Phase 3 — Freshness + fleet (defer)
- Hash-check recompile on source change; preserve fold-in across recompiles.
- Fleet transfer: same-model equipment shares a compiled skill, per-instance
  learned layer stays separate.

---

## 6. Key risks

1. **Scanned-PDF extraction quality (Otis is the test).** 0 extractable text →
   OCR accuracy gates everything. Mitigate: Docling structure-aware + grounding
   gate flags low-confidence skills for human review rather than shipping garbage.
2. **Two sources of truth.** Prevented by the registry split — compiler writes
   files only, skillbook owns learned knowledge, router merges at read.
3. **Compile-time hallucinated frameworks baked as permanent knowledge.** The M3
   grounding gate (page-cite required) is the line. Non-negotiable.
4. **Equipment-instance resolution.** BACnet object-id → equipment_key map is a
   small new table; not blocking but needed before real alarm routing.

---

## 7. Explicitly NOT building (already exists)
- Fold-in / continuous learning → `skillbook.py` (Bayesian verify, context drift).
- Cross-equipment dependency graph → `graph.py` / HEAD `d1c4dfc`.
- Grounding / anti-hallucination → `grounding_guard.py`.
- BACnet/Modbus alarm ingest → `bacnet_adapter.py`.
- GSAS/energy/cost impact pricing → energy_analyzer / cost_engine / gsas_*.
