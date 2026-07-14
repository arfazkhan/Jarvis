# ARVIS Knowledge Compiler — Implementation Plan

**Status**: Design proposal. Pre-implementation.
**Scope**: Integration of vectorless structural document parsing (PageIndex-style) + active wiki compilation (OpenKB-style) + skill factory into the ARVIS Commercial Building Management System (BMS) advisory platform.
**Reader assumption**: None. Document is self-contained for a developer with no ARVIS context.

---

## 0. What ARVIS is, in one paragraph

ARVIS is an advisory AI for commercial building operations. It ingests live BMS (Building Management System) telemetry — chillers, AHUs (Air Handling Units), VAVs (Variable Air Volume boxes), FCUs (Fan Coil Units), cooling towers, energy meters, water meters — from BACnet/Modbus protocols. It runs a multi-agent "swarm" architecture (Queen orchestrator + specialized worker nodes) on AWS Bedrock to answer operator questions, raise alarms, recommend maintenance, and produce GSAS (Global Sustainability Assessment System, used for green-building certification in Qatar and the Gulf) compliance reports. Marina Heights Tower (32 floors, 78,000 m², West Bay Doha, ~12,386 BMS points, 4×800TR chillers, 142 AHUs) is the pilot deployment.

---

## 1. Problem Statement

ARVIS today handles live telemetry well but is weak on **static building knowledge**: equipment manuals, commissioning reports, GSAS compliance dossiers, vendor SLAs, FM playbooks, building codes. Current ingestion uses standard vector-RAG (`agent_commercial/document_ingestion.py`, `agent_commercial/skillbook.py` with `BMSChunker(chunk_size=600)`, ChromaDB embeddings). This pattern has four documented failure modes for industrial BMS use:

1. **Structural destruction** — Fixed-token chunking shreds tables, sequence diagrams, refrigerant charge charts, GSAS scoring rubrics. A Carrier 30XA chiller manual page-71 "Refrigerant Charge by Ambient Temperature" table gets split into three context-broken fragments.
2. **No citation** — Vector search returns "approximately similar" text. GSAS audits require exact clause + page citations. Hallucinated compliance numbers are a liability.
3. **No cross-document synthesis** — Operator asks "AHU-19 static pressure setpoint vs design intent" → needs to fuse Johnson Controls manual + commissioning TAB report + live telemetry. Flat vector RAG returns disconnected chunks.
4. **No skill compilation** — Onboarding 200 PDFs (manuals, codes, SOPs) for a single building produces ~20k embedded chunks but zero executable decision rules. Every operator query reparses raw text instead of inheriting prebuilt logic.

This plan introduces a **knowledge compiler subsystem** that:
- Parses long PDFs by their native structure (Table of Contents tree), not arbitrary token windows.
- Synthesizes per-domain concept pages across documents.
- Distills the synthesis into compact, validated executable skills.
- Provides audit-grade citations on every claim.

---

## 2. Architectural Position Within ARVIS

```
                 ┌───────────────────────────────────────────────────┐
                 │              ARVIS Operator Surface               │
                 │       (chat REPL, dashboard, mobile alerts)       │
                 └─────────────────────────┬─────────────────────────┘
                                           │
                 ┌─────────────────────────┴─────────────────────────┐
                 │        ARVIS Cognitive Layer (existing)           │
                 │  bms_llm_agent.py  +  swarm.queen  +  worker nodes│
                 └─────┬──────────────────┬──────────────────────┬───┘
                       │                  │                      │
                       ▼                  ▼                      ▼
              ┌────────────────┐  ┌──────────────────┐  ┌────────────────────┐
              │  Live BMS      │  │ Memory           │  │  KNOWLEDGE         │
              │  State Engine  │  │ Orchestrator     │  │  COMPILER          │
              │  (telemetry)   │  │  T1/T2/T3        │  │  (NEW — this plan) │
              └────────────────┘  └──────────────────┘  └────────────────────┘
                                                                  │
                       ┌──────────────────────────────────────────┴──────┐
                       │                                                 │
                       ▼                                                 ▼
              ┌────────────────────┐                          ┌────────────────────┐
              │  T0 Static Layer   │                          │   Skill Factory    │
              │  (Active Wiki)     │                          │  (compiled rules)  │
              │  sources/          │  ◄────  bidirectional   ►│  validator +       │
              │  summaries/        │       backlinks           │  dual-pass eval    │
              │  concepts/         │                          │  → skillbook       │
              └──────────┬─────────┘                          └────────────────────┘
                         │
                         │ long PDF fork
                         ▼
              ┌────────────────────┐
              │  ArvisPageIndex    │
              │  (TOC parser +     │
              │  page extraction)  │
              └────────────────────┘
```

**Key positioning decisions**:
- The compiler is a **new memory tier T0** in `arvis_core/memory/`. Existing T1 (working memory), T2 (episodic), T3 (long-term episodic) keep their semantics. T0 is **static building dossier** — never decays, only updated on `onboard` / `re-onboard` events.
- The skill factory writes into the **existing skillbook** (`agent_commercial/skillbook.py`). No parallel registry. Existing tool handlers and queen routing continue to work; they just see richer skills.
- PageIndex is **vendored, not pip-installed**. We fork it into `arvis_core/ingestion/pageindex/` because we need to (a) wire it to Bedrock instead of OpenAI/Volcengine, (b) extend it for BMS-specific document types, (c) avoid external dependency drift.

---

## 3. Component Inventory

| Component | New / Existing | Module path | Purpose |
|---|---|---|---|
| `ArvisPageIndex` | New (vendored fork) | `arvis_core/ingestion/pageindex/` | Long-PDF TOC tree + page-range extraction |
| `DocumentRouter` | New | `arvis_core/ingestion/router.py` | Long vs short fork, format detection, hashing |
| `MarkdownConverter` | New | `arvis_core/ingestion/converters.py` | PDF (short), DOCX, PPTX, XLSX, HTML → Markdown |
| `WikiCompiler` | New | `arvis_core/knowledge/compiler.py` | 5-step cache-optimized pipeline: summary → concept plan → concept generation → backlinks → index |
| `WikiStore` | New | `arvis_core/knowledge/store.py` | Filesystem-backed `wiki/sources/`, `wiki/summaries/`, `wiki/concepts/` + SQLite index |
| `ConceptLinker` | New | `arvis_core/knowledge/linker.py` | Fuzzy wikilink normalization, ghost link stripping, bidirectional reference maintenance |
| `SkillFactory` | New | `arvis_core/knowledge/skill_factory.py` | Distill concept pages → executable skillbook entries |
| `SkillValidator` | New | `arvis_core/knowledge/validator.py` | Zero-LLM static analysis (frontmatter, links, AST scan) |
| `SkillEvaluator` | New | `arvis_core/knowledge/evaluator.py` | Dual-pass LLM eval: trigger accuracy + body coverage |
| `T0StaticAdapter` | New | `arvis_core/memory/adapters/t0_static.py` | Memory orchestrator adapter exposing wiki to queen |
| `OnboardCLI` | New | `arvis_commands/onboard.py` | CLI entrypoint: `arvis onboard <building_id> <dossier_dir>` |
| Existing `document_ingestion.py` | Modify | `agent_commercial/document_ingestion.py` | Add long-doc fork (>=20pp → PageIndex path) |
| Existing `skillbook.py` | Modify | `agent_commercial/skillbook.py` | Accept skills from `SkillFactory` source-tagged with `compiled_from_wiki=true` |
| Existing `bms_llm_agent.py` | Modify | `agent_commercial/bms_llm_agent.py` | Queen consults T0 adapter for static knowledge lookups before memory tiers |

---

## 4. PageIndex Fork — `ArvisPageIndex`

### 4.1 Why fork instead of dependency

The published PageIndex is OpenAI/Volcengine-oriented. ARVIS uses AWS Bedrock with Anthropic Claude models. Three reasons to vendor:
1. Replace OpenAI client with `arvis_core.llm.BedrockClient` (already exists, handles Bedrock auth + retry + prompt-caching).
2. Add BMS-specific output schema: PageIndex emits generic TOC nodes; ARVIS needs `equipment_models`, `point_references`, `fault_codes` extracted as structured side outputs during indexing.
3. Strip the OpenAI Agents SDK runtime — we wire PageIndex's tool functions directly into ARVIS's existing Bedrock tool-use loop.

### 4.2 Module layout

```
arvis_core/ingestion/pageindex/
├── __init__.py
├── parser.py           # PDF text extraction (pymupdf wrapper)
├── toc_detector.py     # Heuristic + LLM-assisted TOC discovery
├── offset_estimator.py # Statistical mode of printed-vs-physical page deltas
├── interpolator.py     # Bound interpolation for missing TOC entries
├── monte_carlo.py      # Sampling verification loop + accuracy gating
├── tree_builder.py     # Flat TOC list → hierarchical node tree
├── subdivider.py       # Recursive split of oversized leaf nodes
├── thinner.py          # Merge undersized children into parents (Markdown)
├── extractor.py        # BMS-domain extraction: equipment models, point refs
├── client.py           # Top-level: index_document() + get_page_content() + get_structure()
└── store.py            # SQLite persistence: pageindex.db
```

### 4.3 Indexing algorithm (detailed)

**Inputs**: PDF file path, building_id, doc_name (slug).

**Outputs**:
- `pageindex.db` row in `documents` table with TOC tree JSON
- `wiki/sources/{doc_name}.json` per-page text array
- `wiki/summaries/{doc_name}.md` TOC skeleton with YAML frontmatter

**Pipeline**:

1. **Text extraction**: pymupdf walks every page, captures plain text + page bounding boxes. Tables detected via line-density heuristic and preserved as inline pseudo-Markdown tables.
2. **TOC detection**:
   - First pass: heuristic scan for "Table of Contents", "Contents", numeric/dotted indent patterns on pages 1–10.
   - Fallback: LLM call with first 15 pages, prompt "extract printed TOC entries if present".
3. **Offset estimation**:
   - For each TOC entry `(title, printed_page)`: locate title text in body via fuzzy match (Levenshtein ratio ≥ 0.85).
   - Compute `D_i = physical_page(title) − printed_page`.
   - Global offset `O = mode({D_i})`. If mode confidence < 60%, fall back to "no printed pages" path.
4. **Bound interpolation**: For TOC entries the title-locator missed, bracket between nearest located neighbors and run LLM-targeted page search within the bracket range only.
5. **Monte Carlo verification**:
   - Sample `N = min(20, len(toc_nodes))` random nodes.
   - For each: send `(title, predicted_page_text[:1500])` to LLM with prompt "does this title appear here? yes/no".
   - Accuracy `A = correct / sampled`.
   - **A = 100%** → accept.
   - **60% ≤ A < 100%** → run `fix_incorrect_toc_with_retries` (bounded local search per failed node).
   - **A < 60%** → degrade mode: TOC-with-pages → TOC-no-pages → synthetic-tree-from-scratch.
6. **Tree construction**: Convert flat list `[(level, title, start_page, end_page), ...]` to nested tree via stack-based grouping on heading level.
7. **Recursive subdivision** for oversized leaves:
   - If `(end_page − start_page > 10) AND (total_token_count > 20,000)`:
   - Slice that page range, send to LLM as "generate sub-TOC for this section", insert returned children as sub-nodes. Recurse until leaves are small enough.
8. **Tree thinning** (Markdown only): Merge children with `token_count < 5000` into parent. Keeps tree dense, avoids hundred-leaf bloat.
9. **Enrichment**:
   - For each leaf, LLM generates one-paragraph summary.
   - BMS extraction pass: regex + LLM hybrid extracts:
     - Equipment models mentioned (`Carrier 30XA`, `Johnson Controls JC-50`)
     - BMS point references (`CHWST`, `MAT`, `STATIC_PA`)
     - Fault codes (`A301`, `E1.4`)
     - Setpoint references (`SP = 6.5°C`)
   - These land in side tables `pageindex_equipment_models`, `pageindex_point_refs`, `pageindex_fault_codes` keyed by `(doc_name, node_id)`.

### 4.4 SQLite schema (pageindex.db)

```sql
CREATE TABLE documents (
    doc_name         TEXT PRIMARY KEY,
    building_id      TEXT NOT NULL,
    file_hash        TEXT NOT NULL,
    page_count       INTEGER NOT NULL,
    indexed_at       TEXT NOT NULL,
    tree_json        TEXT NOT NULL,        -- full TOC tree
    monte_carlo_acc  REAL NOT NULL,
    mode_used        TEXT NOT NULL,        -- pages | no_pages | synthetic
    notes            TEXT
);

CREATE TABLE document_pages (
    doc_name         TEXT NOT NULL,
    page_idx         INTEGER NOT NULL,     -- physical page (1-indexed)
    printed_page     TEXT,                  -- printed marker, may be roman
    text_content     TEXT NOT NULL,
    has_tables       INTEGER DEFAULT 0,
    has_figures      INTEGER DEFAULT 0,
    PRIMARY KEY (doc_name, page_idx)
);

CREATE TABLE pageindex_equipment_models (
    doc_name         TEXT NOT NULL,
    node_id          TEXT NOT NULL,
    model            TEXT NOT NULL,        -- "Carrier 30XA", "Johnson Controls JC-50"
    manufacturer     TEXT,
    section_pages    TEXT,                  -- "67-82"
    PRIMARY KEY (doc_name, node_id, model)
);

CREATE TABLE pageindex_point_refs (
    doc_name         TEXT NOT NULL,
    node_id          TEXT NOT NULL,
    point_type       TEXT NOT NULL,        -- "CHWST", "MAT"
    page_idx         INTEGER NOT NULL,
    context_snippet  TEXT,
    PRIMARY KEY (doc_name, node_id, point_type, page_idx)
);

CREATE TABLE pageindex_fault_codes (
    doc_name         TEXT NOT NULL,
    node_id          TEXT NOT NULL,
    code             TEXT NOT NULL,
    description      TEXT,
    page_idx         INTEGER NOT NULL,
    PRIMARY KEY (doc_name, node_id, code)
);
```

### 4.5 Public API used downstream

```python
# arvis_core/ingestion/pageindex/client.py

class ArvisPageIndex:
    def __init__(self, db_path: Path, llm_client: BedrockClient): ...

    async def index_document(
        self,
        pdf_path: Path,
        doc_name: str,
        building_id: str,
        force: bool = False,
    ) -> IndexResult:
        """One-shot: parse + verify + write. Idempotent if file_hash unchanged."""

    async def get_structure(self, doc_name: str, strip_text: bool = True) -> dict:
        """Return TOC tree. strip_text=True is the default and keeps it tiny."""

    async def get_page_content(self, doc_name: str, page_spec: str) -> str:
        """page_spec accepts '42', '42-45', '42,47,50-52'."""

    async def get_metadata(self, doc_name: str) -> dict:
        """Pages, indexed_at, monte_carlo_acc, equipment_models[], fault_codes[]."""

    async def list_documents(self, building_id: str) -> list[dict]: ...
    async def remove_document(self, doc_name: str) -> None: ...
```

---

## 5. Document Router & Converters

### 5.1 Routing logic

```python
# arvis_core/ingestion/router.py

LONG_PDF_THRESHOLD = 20          # pages
HASH_REGISTRY = ".arvis/hashes.json"

async def route_document(path: Path, building_id: str) -> DocResult:
    # 1. Hash-based dedupe
    file_hash = sha256(path.read_bytes()).hexdigest()
    if hash_already_registered(file_hash, building_id):
        return DocResult(status="skipped_dedup", doc_name=...)

    # 2. Format sniffing
    fmt = sniff_magic_bytes(path)  # pdf | docx | pptx | xlsx | csv | html | md | txt

    # 3. Fork
    if fmt == "pdf":
        page_count = quick_count_pages(path)
        if page_count >= LONG_PDF_THRESHOLD:
            return await pageindex_path(path, building_id)
        else:
            return await short_pdf_path(path, building_id)
    elif fmt in ("docx", "pptx", "xlsx", "csv", "html"):
        return await markitdown_path(path, fmt, building_id)
    elif fmt in ("md", "txt"):
        return await direct_copy_path(path, fmt, building_id)
    else:
        raise UnsupportedFormatError(fmt)
```

### 5.2 Short-PDF path

Uses `pymupdf` to extract full text + base64 inline images. Writes one Markdown file to `wiki/sources/{doc_name}.md` with `doc_type: short` frontmatter. Images extracted to `wiki/sources/images/{doc_name}/`.

### 5.3 MarkItDown path

DOCX/PPTX/XLSX/HTML use Microsoft's `markitdown` library (already pip-available, no Rust). Output is Markdown + extracted media. Same `doc_type: short` frontmatter as short-PDF.

### 5.4 URL ingestion

Optional: `arvis onboard <building_id> --url https://...` fetches via `httpx`, sniffs Content-Type, routes accordingly. For HTML, uses `trafilatura` to strip nav/ads and keep article body. Useful for vendor product pages, code-of-practice URLs.

---

## 6. Wiki Layer — Active Wiki Foundation

### 6.1 Filesystem layout per building

```
data/buildings/{building_id}/wiki/
├── index.md                            # global catalog: all docs + concepts
├── log.md                              # ingestion/removal/query history (audit)
├── AGENTS.md                           # tool dictionary, schema invariants for query agents
├── pageindex.db                        # ArvisPageIndex SQLite
├── sources/
│   ├── carrier_30xa_chiller_manual.json    # PageIndex page array
│   ├── carrier_30xa_chiller_manual.md      # human-readable summary view
│   ├── tab_balancing_2024.md               # short doc, full text
│   ├── images/
│   │   └── carrier_30xa_chiller_manual/
│   │       ├── p67_fig4-1.png
│   │       └── p71_table4-2.png
│   └── ...
├── summaries/
│   ├── carrier_30xa_chiller_manual.md      # TOC skeleton + YAML frontmatter
│   ├── tab_balancing_2024.md
│   └── ...
└── concepts/
    ├── refrigerant-charging.md             # cross-doc synthesis
    ├── ahu-static-pressure-setpoints.md
    ├── gsas-energy-conservation.md
    ├── chiller-staging-strategy.md
    ├── marina-vav-zoning.md
    └── ...
```

### 6.2 Schema invariants (machine-traversable)

Every page has YAML frontmatter. Strict allowed-key sets per type.

**Short document summary**:
```yaml
---
doc_type: short
full_text: sources/tab_balancing_2024.md
building_id: marina-heights
ingested_at: 2026-05-25T14:00:00Z
file_hash: 8f3a...
tags: [commissioning, balancing, AHU]
---
```

**PageIndex (long PDF) summary**:
```yaml
---
doc_type: pageindex
full_text: sources/carrier_30xa_chiller_manual.json
building_id: marina-heights
ingested_at: 2026-05-25T14:00:00Z
file_hash: 9d2b...
page_count: 320
monte_carlo_acc: 1.0
mode_used: pages
equipment_models: [Carrier 30XA-080, Carrier 30XA-100]
tags: [chiller, manual, vendor]
---

# Carrier 30XA Chiller Manual

## Table of Contents

- [1. Safety](pages:1-12) — General safety, PPE, lockout-tagout
- [2. Installation](pages:13-66) — Mounting, piping, electrical
  - [2.1 Piping](pages:24-45)
  - [2.2 Electrical](pages:46-66)
- [3. Operation](pages:67-180)
  - [3.1 Startup Procedure](pages:67-82)
  - [3.2 Refrigerant Management](pages:83-110)
    - [3.2.1 Refrigerant Charging](pages:83-95) — **table p87, fig p91**
...
```

**Concept page** (cross-doc synthesis):
```yaml
---
type: concept
brief: Refrigerant charging procedures across all chiller models installed in this building. Used when operator asks about charge level, leak diagnosis, or service operations.
sources:
  - summaries/carrier_30xa_chiller_manual.md
  - summaries/tab_balancing_2024.md
  - summaries/maintenance_history_2024.md
building_id: marina-heights
applies_to_equipment: [CH-01, CH-02, CH-03, CH-04]
related_concepts:
  - chiller-leak-detection
  - chiller-startup-procedure
last_compiled: 2026-05-25T14:30:00Z
---

# Refrigerant Charging

Marina Heights has four Carrier 30XA chillers (CH-01 through CH-04). Refrigerant charging procedure derives from manufacturer manual §3.2.1 with site-specific adjustments documented in the 2024 commissioning report.

## Decision Rules

- **When operator suspects undercharge**: check sight glass per [[summaries/carrier_30xa_chiller_manual]] §3.2.3 (p89) before adding refrigerant. Bubbles indicate undercharge; clear glass with high discharge pressure indicates overcharge.
- **Target charge by ambient**: see Carrier 30XA Table 4-2 (p87). At 38°C ambient, target 145–155 kg R134a per circuit.
- **Never exceed**: 220 PSI suction pressure ([[summaries/carrier_30xa_chiller_manual]] p93).

## Cross-references

- TAB 2024 baseline (commissioning balance): [[summaries/tab_balancing_2024]] p34, showed CH-01 at 152 kg, CH-02 at 148 kg, CH-03 at 150 kg, CH-04 at 149 kg post-commissioning.
- Maintenance log: [[summaries/maintenance_history_2024]] records CH-02 top-off of 3.5 kg on 2025-08-14 after annual leak check.

## Related Documents

- [[summaries/carrier_30xa_chiller_manual]]
- [[summaries/tab_balancing_2024]]
- [[summaries/maintenance_history_2024]]
```

---

## 7. Wiki Compiler — 5-Step Cache-Optimized Pipeline

The compiler is the engine that converts one freshly-routed document into wiki updates. It runs after `DocumentRouter` and is the primary LLM cost driver. Designed to maximize Bedrock prompt-cache hits.

### 7.1 Pipeline steps

For each new document `D`:

**Step 1 — Base context construction** (no LLM, deterministic):
- Read current `wiki/index.md` + list of existing concept brief lines.
- Read raw text of `D` (full for short docs, summary skeleton + first/last chapters for long PageIndex docs).
- Bundle schema instructions + concept whitelist + document text into a single prefix string.
- Mark **cache breakpoint #1** at the end of this prefix.

**Step 2 — Summary generation** (LLM call, cache miss only on first call per doc):
- Prompt: "Read this document. Produce a YAML-fronted Markdown summary capturing structure and key concepts."
- Output: draft `wiki/summaries/{doc_name}.md`.
- For long PageIndex docs, the TOC tree skeleton replaces the raw text portion of the prefix.

**Step 3 — Concept planning** (LLM call, cache hit on prefix):
- Prompt: "Given this summary, decide which existing concepts to update and which new concepts to create. Output JSON plan."
- Plan schema:
  ```json
  {
    "concepts_to_create": [
      {"slug": "refrigerant-charging", "brief": "...", "applies_to": [...]}
    ],
    "concepts_to_update": [
      {"slug": "chiller-staging-strategy", "reason": "..."}
    ],
    "related": [
      {"from": "refrigerant-charging", "to": "chiller-leak-detection"}
    ]
  }
  ```
- Mark **cache breakpoint #2** at end of plan (now also cached for step 4 fan-out).

**Step 4 — Parallel concept generation** (multiple LLM calls in parallel, all cache hits on shared prefix):
- For each `concept_to_create`: LLM generates full concept page Markdown.
- For each `concept_to_update`: LLM reads existing file + new doc context, produces rewritten page.
- Use `asyncio.gather` bounded by semaphore (concurrency=8) to respect Bedrock rate limits.

**Step 5 — Post-processing** (deterministic + one LLM call):
- LLM call rewrites the summary's wikilinks to point only to concepts that actually got written (whitelist alignment).
- Deterministic linter:
  - Strips ghost wikilinks (links to non-existent concepts).
  - Normalizes link slugs (NFKC unicode, lowercase, kebab-case).
  - Writes bidirectional backlinks to `## Related Documents` and `## Related Concepts` sections of touched pages.
  - Updates `wiki/index.md` catalog.

### 7.2 Cache breakpoint strategy on Bedrock

Bedrock's Claude prompt caching uses `cache_control: {type: "ephemeral"}` markers. Tokens before a cache marker remain warm for ~5 minutes. Across steps 2–5 (typically completing within 30–60 seconds), every step after step 2 hits the cache for the document-text portion. For a 200-page chiller manual, this saves ~80% of input tokens on steps 3–5.

```python
# arvis_core/knowledge/compiler.py (skeleton)

class WikiCompiler:
    async def compile(self, doc_name: str, building_id: str) -> CompileResult:
        prefix = await self._build_base_prefix(doc_name, building_id)
        cache_msg = {"role": "user", "content": prefix, "cache_control": {"type": "ephemeral"}}

        # Step 2
        summary = await self.llm.complete(
            messages=[cache_msg, {"role": "user", "content": SUMMARY_PROMPT}]
        )
        await self._write_summary_draft(doc_name, summary)

        # Step 3
        plan = await self.llm.complete_json(
            messages=[cache_msg,
                      {"role": "user", "content": summary},
                      {"role": "user", "content": PLAN_PROMPT,
                       "cache_control": {"type": "ephemeral"}}]
        )

        # Step 4 — fan out
        await asyncio.gather(
            *[self._generate_concept(c, cache_msg, summary, plan) for c in plan["concepts_to_create"]],
            *[self._update_concept(c, cache_msg, summary, plan) for c in plan["concepts_to_update"]],
        )

        # Step 5
        await self._post_process(doc_name, plan, cache_msg, summary)
        return CompileResult(...)
```

---

## 8. ConceptLinker — Self-Healing Reference Layer

### 8.1 Why

LLM-emitted wikilinks drift. They reference concepts that don't exist, or use slightly different slug formatting (`[[refrigerant-charging]]` vs `[[Refrigerant_Charging]]`). Left unchecked, the wiki accumulates dead links that waste consumer tokens.

### 8.2 Operations

**Slug normalization**:
```python
def normalize_slug(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw)
    s = s.lower()
    s = s.replace("_", "-")
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s
```

**Ghost link stripping** runs after every concept write and as a periodic `arvis lint --fix`:
- For each `[[target]]` or `[[target|alias]]`:
  - If `target` exists on disk → keep.
  - Else if `normalize_slug(target)` matches some existing target's normalized form → rewrite to canonical form.
  - Else (true ghost) → strip the brackets, keep the alias (or render the slug stem as readable words: `refrigerant-charging` → `refrigerant charging`).

**Bidirectional backlinks**:
- When `concept_A.md` contains `[[summaries/doc_X]]`, ensure `summaries/doc_X.md` has a `## Related Concepts` section listing `- [[concepts/concept_A]]`.
- Maintained on every compiler run + on `arvis lint --fix`.

**Cascading deletion** (on `arvis remove <doc>`):
- Walk every concept page. Remove `<doc>` from frontmatter `sources` list. Remove related-doc bullets pointing to it.
- If a concept's `sources` list becomes empty → delete the concept entirely (unless `--keep-empty-concepts`), prune from `index.md`, then re-run lint on touched files to clean any newly-orphaned links.

---

## 9. Skill Factory — Distillation of Concepts into Executable Rules

### 9.1 Why

Concepts are still text. ARVIS skillbook needs **executable decision rules**: triggers, conditions, actions, citations. The Skill Factory converts each concept (or concept-cluster) into one or more skillbook entries.

### 9.2 Target skill format

ARVIS skillbook already exists. We add a new source-tagged record type. Schema:

```yaml
---
name: refrigerant_charging_carrier_30xa
description: Use when operator asks about refrigerant charge, leak, or service on Carrier 30XA chillers (CH-01 through CH-04). Triggers on keywords charge, leak, refrigerant, sight glass, low cooling capacity, high discharge pressure.
building_id: marina-heights
compiled_from_wiki: true
source_concepts:
  - refrigerant-charging
  - chiller-leak-detection
applies_to_equipment: [CH-01, CH-02, CH-03, CH-04]
applies_to_models: [Carrier 30XA-080, Carrier 30XA-100]
compiled_at: 2026-05-25T15:00:00Z
compiler_version: 1.0
---

# Refrigerant Charging — Carrier 30XA

## When to use this skill
- Operator asks about chiller refrigerant level, charge, or leak.
- Not for: water-side issues (use chiller-cooling-water skill instead).

## Core decision rules
- When you see bubbles in sight glass and high discharge pressure together → undercharge likely. Refer to Carrier 30XA manual §3.2.3 p89 before adding.
- Target charge by ambient (Carrier 30XA Table 4-2 p87): At 38°C → 145–155 kg per circuit.
- Never exceed 220 PSI suction; abort if reached.
- TAB 2024 baseline shows CH-01=152 kg, CH-02=148 kg, CH-03=150 kg, CH-04=149 kg post-commissioning.
- If charge has dropped > 5% from baseline → investigate leak before topping off.

## Approach
1. Pull live discharge pressure, suction pressure, sight glass status (if instrumented).
2. Compare current charge estimate (from compressor amp draw) to TAB baseline.
3. If within tolerance → no action; reassure operator.
4. If undercharge suspected → recommend leak test before charging. Cite Carrier manual §3.2.3.
5. If overcharge → recommend recovery to baseline; cite Table 4-2.

## References
- Carrier 30XA Manual §3.2.1, §3.2.3, Table 4-2 (pages 83–95)
- TAB Balancing Report 2024 (page 34)
- Maintenance log entry 2025-08-14 (CH-02 top-off)

## Known gaps
- No live refrigerant level sensors installed; charge inferred from indirect signals.
- Sight glass observation requires physical inspection; ARVIS cannot read it remotely.
```

### 9.3 Distillation algorithm

```python
class SkillFactory:
    async def distill_concept(self, concept_slug: str, building_id: str) -> list[Skill]:
        concept_md = read(f"wiki/concepts/{concept_slug}.md")
        sources = parse_frontmatter(concept_md)["sources"]
        applies_to = parse_frontmatter(concept_md).get("applies_to_equipment", [])

        # Pull reference excerpts via PageIndex / sources reader
        ref_excerpts = await self._collect_reference_excerpts(concept_md, sources)

        # LLM distillation pass
        prompt = build_distill_prompt(concept_md, ref_excerpts, applies_to)
        raw_skill = await self.llm.complete_json(prompt)

        # One concept may yield multiple skills (e.g. charging + leak detection)
        skills = self._split_into_skills(raw_skill)

        # Validate + evaluate before persisting
        for skill in skills:
            v_result = self.validator.validate(skill)
            if v_result.has_errors:
                logger.warning(f"Skill {skill.name} failed validation: {v_result.errors}")
                continue
            e_result = await self.evaluator.evaluate(skill)
            if e_result.trigger_accuracy < 0.7 or e_result.body_coverage < 0.7:
                logger.warning(f"Skill {skill.name} failed eval: {e_result}")
                continue
            await self.skillbook.upsert_compiled_skill(skill)
        return skills
```

### 9.4 When the factory runs

Three triggers:
1. **After each `WikiCompiler.compile()`** for touched concepts (incremental).
2. **`arvis distill --building <id>` CLI** for full rebuild after large changes.
3. **Nightly** via `OpsCopilot._calibration_loop` neighbor (`_skill_distillation_loop`) — checks if any concept's modification time is newer than its derived skill's `compiled_at`, re-distills.

---

## 10. SkillValidator — Zero-LLM Static Analysis

The validator is pure Python. No LLM calls. Fast, free, deterministic. Runs on every skill before promotion to skillbook.

### 10.1 Rules

| Rule | Severity | Check |
|---|---|---|
| `R1` | Error | `SKILL.md` exists at expected path |
| `R2` | Error | File size ≤ 50 KB |
| `R3` | Error | Valid YAML frontmatter present |
| `R4` | Warning | Frontmatter keys all in allowed-set |
| `R5` | Error | `name` matches `^[a-z][a-z0-9_]*$` AND matches directory name |
| `R6` | Error | `description` length ≤ 1024 chars |
| `R7` | Warning | `description` length ≥ 20 chars |
| `R8` | Error | `description` contains no `<` or `>` (would break XML parsers downstream) |
| `R9` | Error | No wikilinks in body pointing to `concepts/`, `summaries/`, `sources/` (skills must be self-contained, redistributable) |
| `R10` | Error | All `[[references/X]]` resolve to existing files in same skill bundle |
| `R11` | Error | Each `references/*.md` ≤ 100 KB |
| `R12` | Warning (strict mode) | `scripts/*.py` AST imports only Python stdlib |
| `R13` | Error | `applies_to_equipment` references known equipment IDs (validated against state engine registry) |
| `R14` | Error | `source_concepts` references existing concepts in wiki |
| `R15` | Warning | At least one `Core decision rule` bullet present |
| `R16` | Warning | At least one citation in body referencing `sources` doc page |

Rules R13, R14, R16 are ARVIS-specific extensions beyond OpenKB's generic validator.

### 10.2 GSAS-specific extensions

When skill frontmatter has `domain: gsas_compliance`:
- `R-GSAS-1` (Error): Body must cite at least one specific GSAS clause (regex `[A-Z]\.\d+(\.\d+)*`).
- `R-GSAS-2` (Error): Each decision rule must end with a page citation `(p\d+)`.
- `R-GSAS-3` (Error): `assessment_category` frontmatter key must be one of `[energy, water, materials, indoor_environment, management, urban_connectivity, site, cultural_economic]`.
- `R-GSAS-4` (Warning): If `score_weight` declared, must sum across same `assessment_category` skills ≤ 1.0.

---

## 11. SkillEvaluator — Dual-Pass LLM Quality Gate

Validator catches structure. Evaluator catches semantic emptiness.

### 11.1 Two passes

**Pass 1 — Trigger accuracy** (description-only grader):
- LLM sees only the skill's `description` frontmatter + a test query.
- Returns binary verdict: `TRIGGER` or `NO-TRIGGER`.
- Run against test suite of:
  - `should_trigger`: queries that match this skill's intent.
  - `should_not_trigger`: queries on adjacent topics that should fire different skills.
- Metric: `(true positives + true negatives) / total`.

**Pass 2 — Body coverage** (full-skill grader):
- LLM sees the full `SKILL.md` body + reference excerpts + a query that should trigger this skill.
- Returns structured verdict:
  ```json
  {
    "verdict": "SUPPORTED|UNSUPPORTED",
    "reason": "...",
    "missing_substance": [...]
  }
  ```
- Metric: fraction of `should_trigger` queries where the body actually contains the answer.

### 11.2 Test suite generation

Test queries are generated by a third LLM call from the skill description + concept body:

```python
async def generate_test_suite(skill: Skill, concept: ConceptPage) -> TestSuite:
    prompt = TEST_GEN_PROMPT.format(
        skill_description=skill.description,
        concept_body=concept.body,
        related_concepts=concept.related,
    )
    raw = await self.llm.complete_json(prompt)
    return TestSuite(
        should_trigger=raw["positive_queries"],     # 10 queries
        should_not_trigger=raw["adjacent_queries"], # 10 queries on related-but-distinct topics
    )
```

### 11.3 Promotion gate

Both metrics must clear thresholds for skill to be promoted to active skillbook:

| Metric | Threshold |
|---|---|
| Trigger accuracy | ≥ 0.85 |
| Body coverage | ≥ 0.85 |
| For GSAS skills | both ≥ 0.95 (audit-grade) |

Failed skills are written to `wiki/skills_quarantine/` with eval report attached for human review. Not visible to operators.

### 11.4 Cost control

Eval is the most expensive step. Mitigations:
- Run **only on first compile** of a skill and on **content change**, not on every wiki compile.
- Cache eval results keyed by `(skill_name, content_hash)`.
- Reuse test suite across re-evals when only minor edits made.
- Concurrency=8 semaphore on Bedrock calls.
- Budget per building per month logged to `calibration_runs`-style ledger.

---

## 12. Memory Adapter — T0 Static Tier

ARVIS's `MemoryOrchestrator` already manages T1 (working), T2 (episodic), T3 (long-term). We add T0 (static building dossier).

### 12.1 Adapter contract

```python
# arvis_core/memory/adapters/t0_static.py

class T0StaticAdapter(MemoryAdapter):
    """Read-only adapter exposing the wiki to the cognitive layer."""

    def __init__(self, wiki_root: Path, pageindex: ArvisPageIndex): ...

    async def retrieve(self, query: str, context: dict) -> RetrievalResult:
        """
        Hierarchical retrieval:
          1. Read index.md, identify candidate documents and concepts.
          2. Read top-3 concept pages (cheap, summary level).
          3. For each concept, follow citations to specific pages via PageIndex.
          4. Assemble result with citations preserved.
        Returns ranked nodes + raw text excerpts + citation metadata.
        """

    async def list_equipment_docs(self, equipment_id: str) -> list[DocRef]:
        """Quick lookup: which docs apply to CH-01?"""

    async def list_gsas_clauses(self, category: str) -> list[GsasClauseRef]:
        """GSAS-domain helper: pull all wiki citations for category."""
```

### 12.2 Queen integration

`Swarm.Queen` consults T0 **before** T2/T3 episodic memory when:
- Query mentions equipment model number or known doc name.
- Query is a static-knowledge question (procedural, design, compliance).
- Query asks for citations.

Live telemetry queries (T1 state) still go direct to `state_engine`.

```python
# agent_commercial/bms_llm_agent.py (modification)

async def _route_query(self, query: str, intent: dict) -> dict:
    routes = []
    if intent.get("needs_live_data"):
        routes.append(("T1", self.memory.t1.retrieve(query)))
    if intent.get("needs_static_knowledge") or intent.get("needs_citation"):
        routes.append(("T0", self.memory.t0.retrieve(query)))
    if intent.get("needs_history"):
        routes.append(("T2", self.memory.t2.retrieve(query)))
        routes.append(("T3", self.memory.t3.retrieve(query)))
    results = await asyncio.gather(*[r for _, r in routes])
    return self._merge_routed(routes, results)
```

---

## 13. CLI Surface

### 13.1 New commands

```
# Bulk onboarding
arvis onboard <building_id> <dossier_dir> [--dry-run] [--force]
    Walks dossier_dir, hashes each file, routes per format, compiles wiki,
    distills skills, runs validator + evaluator, writes summary report.

# Single doc
arvis ingest <building_id> <file_or_url> [--force] [--no-compile] [--no-distill]
    Add one document.

# Removal
arvis remove <building_id> <doc_name> [--keep-empty-concepts]
    Cascading removal: deletes sources, summaries, prunes concept references,
    deletes orphaned concepts, re-runs lint.

# Manual skill regeneration
arvis distill <building_id> [--concept <slug>] [--all]
    Force re-distillation. Useful after manual concept edits.

# Wiki maintenance
arvis lint <building_id> [--fix]
    Run ghost-link stripping, slug normalization, bidirectional backlink check.

# Query (REPL or one-shot)
arvis ask <building_id> "<question>"
    Issues query against T0+T1+T2+T3 with citations.

# Skill registry inspection
arvis skills <building_id> [--list | --show <name> | --eval <name>]

# GSAS-specific shortcut
arvis gsas-report <building_id> [--category <cat>] [--format pdf|md]
    Produces audit-grade report using compiled GSAS skills.
```

### 13.2 Onboarding wizard output (terminal)

```
ARVIS Onboarding — marina-heights
==================================================================
Dossier dir: /buildings/marina/dossier/
Files detected: 47

[1/47] Carrier 30XA Chiller Manual (carrier_30xa_chiller_manual.pdf)
       Format: PDF, 320 pages → PageIndex path
       Hashing... new file
       Indexing... TOC detected. Offset: +4. Monte Carlo accuracy: 100%
       Equipment models found: Carrier 30XA-080, 30XA-100
       Fault codes extracted: 24
       Compiling wiki...
         - Created concept: refrigerant-charging
         - Created concept: chiller-startup-procedure
         - Updated concept: chiller-staging-strategy
       Distilling skills...
         - refrigerant_charging_carrier_30xa  [validator: PASS] [trigger acc: 0.92]
         - chiller_startup_carrier_30xa       [validator: PASS] [trigger acc: 0.88]
         - chiller_alarm_diagnosis_30xa       [validator: PASS] [trigger acc: 0.81]
       Done. 12s.

[2/47] Johnson Controls AHU Manual ...

...

[47/47] Floor 23 Tenant Requirements ...

==================================================================
Summary
==================================================================
  Documents indexed:        47
  Pages parsed:           5,832
  Concepts created:          63
  Concepts updated:          12
  Skills compiled:          108
  Skills quarantined:        14   (see wiki/skills_quarantine/)
  Total wall time:        18m 42s
  Bedrock tokens:      ~4.2M in / 380K out
  Estimated cost:          $42
==================================================================
```

---

## 14. Per-Use-Case Implementation Detail

Twelve concrete use cases, each with: input docs, compiled artifacts, skill examples, ARVIS-side wiring.

### 14.1 Equipment Manuals

**Input**: Carrier 30XA chiller manual, Johnson AHU manual, Titus VAV manual, Trane CT (cooling tower) manual, KMC/Distech controller manuals.

**Pipeline**: PageIndex for any manual ≥ 20pp. Equipment-model extraction tags each manual to specific Marina equipment via `applies_to_equipment` frontmatter.

**Concepts** generated examples:
- `chiller-staging-strategy`
- `refrigerant-charging`
- `ahu-static-pressure-setpoints`
- `vav-airflow-calibration`
- `cooling-tower-water-treatment`
- `controller-point-mapping`

**Skills**:
- `chiller_alarm_diagnosis_30xa`
- `ahu_low_static_pressure_diagnosis`
- `vav_airflow_below_setpoint`
- `cooling_tower_blowdown_schedule`

**ARVIS wiring**: When operator asks "CH-01 is alarming, what now" → Queen routes intent `equipment_diagnosis` → consults T0 → finds skill `chiller_alarm_diagnosis_30xa` → fires with live alarm context.

### 14.2 Commissioning + TAB Reports

**Input**: TAB (Test, Adjust, Balance) reports per HVAC system, commissioning agent final reports, equipment startup logs.

**Pipeline**: Mixed — TAB reports are often 50–100 pp PDFs (PageIndex); commissioning checklists may be DOCX (MarkItDown).

**Concepts**:
- `marina-as-built-baselines` — per-equipment commissioning numbers
- `commissioning-deviation-history` — where as-built differs from design

**Skills**:
- `baseline_drift_detection` — fires when live values diverge > X% from commissioning baseline
- `commissioning_citation` — supplies as-built values when operator asks "what was it set to originally"

**Cross-link**: Each piece of equipment in state engine gets a `commissioning_baseline` field populated from compiled TAB data.

### 14.3 GSAS Compliance Dossier

**Input**: GSAS Assessment Manual (~480pp), GSAS Calculation Methodology (~220pp), addenda, certification certificates, meter calibration certs.

**Pipeline**: PageIndex with GSAS-aware extractor: every clause number `[A-Z]\.\d+(\.\d+)*` indexed with its page.

**Concepts** (one per scoring category):
- `gsas-energy-conservation`
- `gsas-water-conservation`
- `gsas-indoor-environment`
- `gsas-materials`
- `gsas-management`
- `gsas-urban-connectivity`
- `gsas-site`
- `gsas-cultural-economic`

**Skills** (with strict GSAS validator extensions from §10.2):
- `gsas_energy_score_audit`
- `gsas_water_score_audit`
- `gsas_indoor_air_score_audit`
- ...one per scoring category
- Each cites exact clauses + pages on every claim
- Dual-pass eval thresholds raised to 0.95 for these skills

**ARVIS wiring**: `agent_commercial/gsas_optimizer.py` already exists. Modify to consult T0 first, use compiled GSAS skills for all numeric scoring, fall back to vector-RAG only for explanatory text. New tool `arvis gsas-report` outputs audit-grade Markdown/PDF.

### 14.4 Vendor SLA Contracts

**Input**: Maintenance contracts for chillers, lifts, fire systems, BMS itself.

**Pipeline**: Usually DOCX or scanned PDF. MarkItDown for DOCX, OCR-fallback for scans (use `pytesseract` integration in `arvis_core/ingestion/converters.py`).

**Concepts**:
- `sla-response-times` — table of SLA response by severity
- `sla-vendor-contacts` — phone, email, on-call rotation

**Skills**:
- `sla_compliance_check` — fires on each alarm; checks alarm timestamp vs SLA window; auto-drafts vendor ticket if window approaching breach
- `vendor_dispatch_recommendation` — when fault diagnosed, recommend vendor per contract

**Wiring**: Hooked into `agent_commercial/alarm_engine.py` — each alarm fires through `sla_compliance_check` to compute time-to-breach.

### 14.5 Operator SOPs / FM Playbooks

**Input**: Building handover documents, FM team Word SOPs, scanned binders, daily operational checklists.

**Pipeline**: Mix. OCR scans, MarkItDown DOCX.

**Concepts**:
- `daily-rounds-procedure`
- `monthly-maintenance-schedule`
- `emergency-response-procedures`
- `shift-handover-protocol`

**Skills**:
- `friday_plant_rotation` — fires Thursday end-of-shift, prompts operator with weekend rotation steps
- `night_mode_setbacks` — fires at occupancy-change events

**Value**: Captures institutional knowledge that disappears with staff turnover.

### 14.6 Incident Postmortem Corpus

**Input**: Existing ARVIS T2 episodic memory (closed investigations) + manually-written postmortem reports from FM team.

**Pipeline**: This is the only use case where input is *internal* to ARVIS. A nightly job exports T2 records older than 30 days as Markdown into `wiki/sources/incidents/{incident_id}.md`, then runs the compiler.

**Concepts**:
- `recurring-fault-patterns-ch-01` — pattern recognition across CH-01 history
- `summer-load-stress-patterns` — multi-incident synthesis
- `false-alarm-signatures` — known nuisance alarm patterns

**Skills**:
- `prior_incident_match` — when new symptoms match a past incident, surfaces it with link to resolution
- `nuisance_alarm_filter` — suppresses likely false alarms based on historical signatures

**Result**: ARVIS becomes building-specific over time. The longer it runs, the smarter it gets — but in a *compiled, auditable* way, not via opaque vector-memory recall.

### 14.7 Building Codes & Standards

**Input**: ASHRAE 62.1 (ventilation), ASHRAE 90.1 (energy), Qatar Construction Specifications (QCS), Doha Municipality building code, NFPA 70/72 (electrical/fire alarm).

**Pipeline**: All large PDFs → PageIndex. Domain extractor: clause numbers + section titles.

**Concepts**:
- `ashrae-621-ventilation-requirements`
- `ashrae-901-energy-standards`
- `qcs-mep-requirements`
- `nfpa-72-fire-alarm-zones`

**Skills**:
- `ventilation_compliance_check` — verifies OA fraction per ASHRAE 62.1 with citation
- `lighting_power_density_audit` — verifies LPD per ASHRAE 90.1

**Updates**: Codes change yearly. `arvis ingest` with new version automatically re-compiles, runs lint to update cross-refs. Version-pinned in `frontmatter.code_version`.

### 14.8 Tenant Floor Manuals

**Input**: Per-tenant lease addenda specifying temperature ranges, schedules, special requirements (data centers, restaurants, retail).

**Pipeline**: DOCX/PDF, short docs.

**Concepts**:
- `tenant-comfort-requirements` — per-floor table

**Skills**:
- `floor_specific_comfort_advice` — when operator handles a complaint, fires with the tenant's contractual range and SLA

**Wiring**: State engine extended with `tenant_profile` per equipment grouped by floor.

### 14.9 Energy Benchmarks

**Input**: CIBSE TM46 (UK), ASHRAE benchmark datasets, Qatar Green Building Council benchmarks, industry surveys.

**Pipeline**: Mix of PDFs and XLSX. PageIndex for long; XLSX → MarkItDown.

**Concepts**:
- `peer-tower-benchmarks-doha`
- `cibse-energy-benchmarks`

**Skills**:
- `comparative_energy_position` — answers "are we good?" with peer benchmark percentile
- `efficiency_opportunity_finder` — when current performance lags benchmark, suggests measures

### 14.10 Maintenance History Archive

**Input**: 4 years of vendor service tickets, work orders, parts replacements (often in CSV / Excel exports from CAFM systems).

**Pipeline**: XLSX → MarkItDown → compiler. Or direct DB import if CAFM provides API (existing `arvis_core/integrations/cafm_adapter.py`).

**Concepts**:
- `ch-01-lifetime-history`
- `recurring-component-failures`
- `vendor-performance-track-record`

**Skills**:
- `predictive_part_warning` — when failure history shows component MTBF approaching, flag
- `vendor_recommendation` — recommends vendors based on past response quality

### 14.11 Sensor Calibration Certificates

**Input**: Annual calibration certificates per BACnet point (PDFs from cal labs).

**Pipeline**: Short PDFs, but **structured extraction matters**. Custom extractor pulls: `point_id`, `cal_date`, `cal_expiry`, `accuracy_class`, `cal_lab`.

**Concepts**:
- `sensor-trust-registry`

**Skills**:
- `sensor_trust_score` — decays each sensor's confidence as cal expiry approaches
- `data_quality_caveat` — when ARVIS uses a sensor whose cal is expired, prepends advice with confidence caveat

**Wiring**: Critical for anti-hallucination. ARVIS already has `GroundingGuard`. This skill feeds GroundingGuard with sensor-level trust scores.

### 14.12 Insurance / Fire Safety Manuals

**Input**: Sprinkler design docs, smoke control sequences, MOE (Means of Egress) plans, fire alarm zone maps.

**Pipeline**: PageIndex; usually long PDFs.

**Concepts**:
- `smoke-control-sequences`
- `fire-evacuation-zones`
- `stair-pressurization-logic`

**Skills**:
- `fire_alarm_response` — on fire alarm event, cites exact smoke control sequence + stair pressurization mode for the zone
- `evacuation_guidance` — surfaces MOE plan for the alarmed floor

**Life safety class**: These skills are tagged `safety_critical: true`. Validator requires `evaluator.body_coverage ≥ 0.95`, and `arvis distill` blocks promotion if eval fails (no quarantine — explicit human sign-off required).

---

## 15. Database & Persistence Schema (Consolidated)

Three new SQLite databases per building:

### 15.1 `pageindex.db`
Schemas in §4.4.

### 15.2 `knowledge_index.db` (compiled-wiki metadata)

```sql
CREATE TABLE wiki_documents (
    doc_name        TEXT PRIMARY KEY,
    building_id     TEXT NOT NULL,
    doc_type        TEXT NOT NULL,           -- short | pageindex
    file_hash       TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    summary_path    TEXT NOT NULL,
    ingested_at     TEXT NOT NULL,
    last_compiled_at TEXT,
    tags            TEXT                      -- JSON array
);

CREATE TABLE wiki_concepts (
    slug            TEXT PRIMARY KEY,
    building_id     TEXT NOT NULL,
    brief           TEXT NOT NULL,
    body_path       TEXT NOT NULL,
    last_compiled_at TEXT NOT NULL,
    domain          TEXT                      -- gsas | equipment | safety | ...
);

CREATE TABLE wiki_concept_sources (
    slug            TEXT NOT NULL,
    source_doc      TEXT NOT NULL,            -- doc_name
    PRIMARY KEY (slug, source_doc)
);

CREATE TABLE wiki_concept_related (
    from_slug       TEXT NOT NULL,
    to_slug         TEXT NOT NULL,
    relation        TEXT,                     -- see_also | parent | child | conflict
    PRIMARY KEY (from_slug, to_slug)
);

CREATE TABLE wiki_compile_runs (
    run_id          TEXT PRIMARY KEY,
    building_id     TEXT NOT NULL,
    trigger         TEXT NOT NULL,            -- ingest | re_compile | manual
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    docs_processed  INTEGER,
    concepts_created INTEGER,
    concepts_updated INTEGER,
    skills_compiled INTEGER,
    skills_quarantined INTEGER,
    cost_estimate_usd REAL,
    notes           TEXT
);
```

### 15.3 `skill_audit.db` (skill factory ledger)

```sql
CREATE TABLE compiled_skills (
    skill_name          TEXT PRIMARY KEY,
    building_id         TEXT NOT NULL,
    body_path           TEXT NOT NULL,
    source_concepts     TEXT NOT NULL,            -- JSON array of slugs
    compiled_at         TEXT NOT NULL,
    compiler_version    TEXT NOT NULL,
    validator_status    TEXT NOT NULL,            -- pass | warn | fail
    validator_errors    TEXT,                      -- JSON
    eval_trigger_acc    REAL,
    eval_body_coverage  REAL,
    eval_test_count     INTEGER,
    eval_passed         INTEGER NOT NULL,         -- 0 | 1
    promoted            INTEGER NOT NULL,         -- 0 = quarantine, 1 = active
    domain              TEXT,                      -- gsas | equipment | safety | sop | ...
    safety_critical     INTEGER DEFAULT 0
);

CREATE TABLE skill_eval_runs (
    run_id              TEXT PRIMARY KEY,
    skill_name          TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    test_suite_hash     TEXT,
    trigger_results     TEXT,                      -- JSON per-query verdicts
    coverage_results    TEXT,                      -- JSON per-query verdicts
    cost_usd            REAL
);
```

---

## 16. Build Sequencing (Concrete Order)

Plan organized into 6 implementation phases. Phase boundaries are content-driven (each phase delivers a usable subset).

### Phase A — Foundation
- Vendor PageIndex into `arvis_core/ingestion/pageindex/`
- Replace OpenAI client with `BedrockClient`
- Wire `ArvisPageIndex.index_document()` against three test PDFs of varying length and quality
- SQLite schema for `pageindex.db`
- CLI `arvis ingest <building> <pdf>` works end-to-end for one long PDF
- Unit tests: TOC offset, Monte Carlo verification, recursive subdivision
- **Exit criterion**: Index a 200-page Carrier manual; `arvis ask` against just that one doc returns cited answers via PageIndex tools

### Phase B — Wiki Compiler
- `WikiCompiler` 5-step pipeline
- Filesystem layout under `data/buildings/{building_id}/wiki/`
- `knowledge_index.db` schema
- `ConceptLinker` (slug normalize, ghost strip, bidirectional backlinks)
- Bedrock prompt-cache integration with explicit breakpoints
- `arvis lint --fix` command
- **Exit criterion**: Onboard 5 PDFs; produces correct concept synthesis; lint --fix is idempotent

### Phase C — Short Docs + Multi-Format
- MarkItDown integration for DOCX/PPTX/XLSX/HTML/CSV
- `pymupdf` short-PDF path
- URL ingestion via `httpx` + `trafilatura`
- OCR fallback (`pytesseract`) for scanned PDFs
- Hash registry / dedup
- **Exit criterion**: `arvis onboard` walks a mixed-format dossier dir without errors

### Phase D — Skill Factory
- `SkillFactory.distill_concept()`
- `SkillValidator` with all rules R1–R16 + GSAS extensions R-GSAS-1..4
- `SkillEvaluator` dual-pass with test-suite generator
- `skill_audit.db` ledger
- Modify existing `agent_commercial/skillbook.py` to accept `compiled_from_wiki=True` source-tagged skills
- Quarantine path for failed-eval skills
- **Exit criterion**: 20+ skills compiled from existing wiki; validator + eval gate working; quarantine for failures

### Phase E — Memory Adapter + Cognitive Integration
- `T0StaticAdapter` implements `MemoryAdapter` interface
- Register with `MemoryOrchestrator` alongside existing T1/T2/T3
- Modify `bms_llm_agent.py` query router to consult T0 for static-knowledge intents
- Update Queen's evidence assembly to include T0 citations in advisory output
- Wire `GroundingGuard` to require T0 citation when skill body claims a specific value
- **Exit criterion**: Operator asks "what's the refrigerant charge for CH-01" → ARVIS answers with citation to Carrier manual p87

### Phase F — Use-Case Domain Specializations
- GSAS validator extensions + GSAS skill domain
- Sensor cal cert extractor + GroundingGuard trust integration
- Incident postmortem nightly export from T2
- Fire safety `safety_critical` gating
- Tenant profile per-floor wiring
- Code-update workflow (ASHRAE/QCS yearly revisions)
- **Exit criterion**: Marina pilot can demo (a) chiller maintenance Q&A with citation, (b) GSAS audit-grade report, (c) incident-pattern match on new alarm

---

## 17. Test Strategy

### 17.1 Unit tests
- `pageindex.offset_estimator`: synthetic TOC with known offset; assert mode detected.
- `pageindex.monte_carlo`: mock LLM verifier; assert degradation triggers at < 60%.
- `compiler.ConceptLinker.normalize_slug`: NFKC + lowercase + kebab cases.
- `compiler.ConceptLinker.strip_ghost`: dead links removed, alias preserved.
- `validator`: each rule R1–R16 has positive and negative cases.

### 17.2 Integration tests
- `test_e2e_carrier_manual`: ingest real Carrier 30XA PDF (vendored test fixture), assert ≥ 1 concept created, ≥ 1 skill compiled, validator passes.
- `test_e2e_gsas_audit`: ingest GSAS spec excerpt; query `arvis gsas-report --category energy`; assert output contains specific clause numbers from input.
- `test_cascading_removal`: onboard 3 docs sharing 2 concepts, remove 1 doc, assert concepts kept (still have other sources); remove second doc, assert orphan concept deleted.
- `test_lint_idempotent`: run `arvis lint --fix` twice, assert no diff on second run.

### 17.3 Eval-suite regression
- Maintain a `tests/eval_golden/marina/queries.yaml` of 50 operator questions with expected citation patterns.
- Run nightly. Track trigger accuracy + body coverage over time. Block merges that regress > 5%.

### 17.4 Performance benchmarks
- Index 320pp PDF: target < 90s end-to-end.
- Full Marina dossier onboard (~50 docs, ~5,000pp total): target < 30 min.
- Single operator query end-to-end (T0 hit, citation rendered): target < 4s.

---

## 18. Cost & Capacity Model

**Per-document one-time cost** (Bedrock Claude Sonnet pricing as anchor):

| Doc type | Avg pages | Bedrock in / out | Est. cost |
|---|---|---|---|
| Short PDF / DOCX (≤ 20pp) | 10 | 30k / 5k | $0.30 |
| Medium PDF (20–100pp) | 60 | 200k / 25k | $1.80 |
| Long PDF (100–300pp) | 200 | 600k / 50k | $5.00 |
| Very long PDF (300+pp) | 480 | 1.5M / 100k | $11 |

**Per-building dossier (~50 mixed docs)**: $40–$80 one-time. Trivial vs annual ARVIS license.

**Per-skill compile + eval**: $0.40 (distillation) + $0.80 (eval with 20 test queries) ≈ $1.20. For 100 skills per building → $120.

**Steady-state per-month**:
- Incremental ingest (new SOPs, code updates): ~5 docs/month × $2 = $10
- Skill re-eval on changes: ~10 skills/month × $1.20 = $12
- Operator queries against T0: cache-hot, ~$0.05/query, ~10k queries/month = $500
- Total: ~$520/month per building

Set budget cap in `OpsCopilot._calibration_loop`-style neighbor → halt with warning if monthly Bedrock spend on knowledge subsystem exceeds threshold.

---

## 19. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OCR errors corrupt extracted text (scanned manuals) | High | High | Hybrid OCR (`pytesseract` + LLM correction pass); manual review queue for low-confidence extractions |
| Monte Carlo accuracy < 60% on poorly-structured PDFs | Medium | Medium | Degradation to synthetic-tree mode + flag for human review; expose `arvis ingest --review` mode |
| Bedrock prompt cache expiration mid-compile | Low | Medium | Compile completes in < 60s typical; long compiles split into multiple cache windows |
| Skill validator false-positive blocks good skills | Medium | Low | Quarantine + human override flag `--force-promote` with audit log |
| Concept-page bloat over time | Medium | Low | Auto-thinning of small concepts on lint; periodic `arvis prune` command |
| Hallucinated citations | Medium | High | GroundingGuard cross-checks every cited page number against `pageindex.db` source text via fuzzy match; reject if not found |
| GSAS skill scores wrong number | Low | Critical | GSAS eval threshold raised to 0.95; safety_critical block on promotion; human sign-off required for audit reports |
| Code update breaks downstream skills | Medium | Medium | Pin skill `code_version` to compiled-against revision; flag drift; re-distill before next audit |
| Multi-building deployment requires schema split | Low | Medium | All schemas already include `building_id`; no refactor needed |
| Vendor PageIndex code drifts from upstream | Low | Low | Fork with documented divergence points; periodic upstream rebase or replace |

---

## 20. Open Decisions Before Build Starts

These must be resolved before Phase A starts; defaults are recommended values:

1. **Wiki storage location**: per-building dir under `data/buildings/{building_id}/wiki/` (default) vs central + per-building schemas in shared DB. **Recommend per-building dir** — matches existing ARVIS isolation pattern.
2. **Bedrock model for compiler**: Claude Sonnet (cheap, fast) vs Claude Opus (better synthesis). **Recommend Sonnet for compile + Opus for GSAS-domain distill only**.
3. **Eval concurrency**: 8 default. May need lowering for Bedrock rate limits. Configurable via env `ARVIS_EVAL_CONCURRENCY`.
4. **OCR engine**: `pytesseract` (free, mediocre) vs AWS Textract (paid, good). **Recommend Textract for scanned PDFs** because Marina has historical scanned binders; cost is small.
5. **Image extraction**: extract to disk vs base64-embed in JSON. **Recommend disk** — keeps `sources/*.json` small, enables direct image tool.
6. **Skill promotion authority**: auto-promote on eval pass vs human-review every skill. **Recommend auto-promote except `safety_critical=true`** — human review for those.
7. **Snapshot retention**: how long to keep prior versions of wiki/concepts after re-compile? **Recommend 30 days in `wiki/.history/` + git-style diff**, then prune.
8. **GSAS version**: pin to GSAS v2.1 (current Qatar standard) or auto-detect from doc? **Recommend explicit pin in building config** to avoid surprise rule changes.
9. **CLI vs API surface**: Phase A delivers CLI only. API endpoints in Phase F (via existing FastAPI in `agent_commercial/api/`). **Recommend CLI-first; expose endpoints after wiki stable**.
10. **Multi-language docs**: Marina docs are English. Other Gulf deployments may have Arabic GSAS docs. **Recommend defer until non-English deployment commits**; PageIndex assumes English heading detection.

---

## 21. Glossary

| Term | Meaning |
|---|---|
| **AHU** | Air Handling Unit — central air conditioner for a floor or zone |
| **BACnet** | Standard protocol for BMS device communication |
| **BMS** | Building Management System — controls and monitors HVAC, lighting, etc. |
| **CAFM** | Computer-Aided Facility Management — vendor ticketing systems |
| **CHWST** | Chilled Water Supply Temperature |
| **Concept page** | Synthesized cross-document Markdown page in `wiki/concepts/` |
| **FCU** | Fan Coil Unit — terminal HVAC device, typically per-room |
| **GroundingGuard** | ARVIS anti-hallucination layer requiring claims be backed by retrieved evidence |
| **GSAS** | Global Sustainability Assessment System — Qatar/Gulf green certification |
| **MAT** | Mixed Air Temperature — AHU sensor |
| **MarkItDown** | Microsoft library converting DOCX/PPTX/XLSX/HTML to Markdown |
| **MOE** | Means of Egress — fire/safety evacuation plan |
| **PageIndex** | Vectorless RAG project that parses PDF TOCs into navigable trees |
| **SAT** | Supply Air Temperature — AHU sensor |
| **Skill** | Compact executable decision rule in ARVIS skillbook |
| **Skillbook** | ARVIS registry of named skills with triggers, rules, and bodies |
| **TAB report** | Test, Adjust, Balance — commissioning document with as-built performance |
| **TOC** | Table of Contents |
| **T0 / T1 / T2 / T3** | ARVIS memory tiers: static / working / episodic / long-term |
| **VAV** | Variable Air Volume box — zone-level air controller |
| **Wiki** | Active knowledge filesystem (`sources/`, `summaries/`, `concepts/`) per building |

---

## 22. Document Status

| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-05-25 | Initial complete plan covering 12 use cases, 6 phases, all components, schemas, CLI, costs, risks |

Next action: review against open decisions in §20, lock answers, then begin Phase A vendor of PageIndex into `arvis_core/ingestion/pageindex/`.
