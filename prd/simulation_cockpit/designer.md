# Simulation Cockpit — Product Designer Brief

**Feature**: Control panel for sales demos and internal regression. Persona toggles, scenario picker, clock scrubber, judge panel, building loader.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. The product has three modes: **SIM** (synthetic data), **PILOT** (real building, shadow), **PROD** (real building, live). The Simulation Cockpit is only visible in SIM mode — it lets sales reps and engineers drive a fake building through scripted scenarios while the rest of the UI renders identically to a live customer console.

Key insight: ARVIS UI is the SAME in SIM and PROD. The only difference is where events come from. Cockpit makes that difference controllable.

---

## Why this exists

- Sales demos need scripted scenarios that always work
- Engineers need to reproduce bugs deterministically
- Operators need training on rare incidents without breaking real building
- QA needs regression runs after engine changes

Without the cockpit, demos break, bugs aren't reproducible, training is theoretical.

---

## Users

- **Sales / demo pilot** — runs customer demos
- **AI engineer** — replays issues, validates fixes
- **QA** — regression suites
- **Training instructor** (P2) — guided incidents for new operators

---

## Scope

**In**:
- Scenario picker (preset scenarios with metadata)
- Persona toggles (Bilal / Ahmed / Noor / vendor / tech personas on/off)
- Clock scrubber (pause / play / jump / speed)
- Judge panel scores (when running validation runs)
- Building loader (pick which building.yaml is loaded)
- Reset state button (back to scenario start)

**Out**:
- Custom scenario authoring UI (P2 — engineers edit YAML directly)
- Multi-user collaborative simulation (P3)

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ Simulation Cockpit                                                  │
│ Status: SIM · Scenario: refrigerant_migration · Clock: Day 4, 14:23│
├─────────────────────────────────────────────────────────────────────┤
│ Building                                                            │
│ Loaded: marina_heights.yaml                                         │
│ [Change building]  [Reload]                                         │
├─────────────────────────────────────────────────────────────────────┤
│ Scenario                                                            │
│ ┌─────────────────────────────────────────┐  Refrigerant Migration │
│ │ ▸ Refrigerant Migration       ★ ACTIVE  │  Triggers gradual COP  │
│ │   Chiller Staging Fault                 │  decline over 4 days,  │
│ │   Compliance Audit Week                 │  ends in advisory      │
│ │   Heatwave                              │  cascade.              │
│ │   Phantom Setpoint Change               │                        │
│ │   Vendor Maintenance Visit              │  [Start scenario]      │
│ └─────────────────────────────────────────┘                        │
├─────────────────────────────────────────────────────────────────────┤
│ Personas                                                            │
│ [✓] Bilal (operator)      [✓] Ahmed (FM)     [ ] Noor (owner)      │
│ [✓] Maintenance vendor    [ ] Tenant feedback                       │
├─────────────────────────────────────────────────────────────────────┤
│ Clock                                                               │
│ [⏸ Pause]  [▶ Play]  Speed: [1x] [6x] [60x]                         │
│ Jump to: [event ▾] [Day ▾]                                          │
│ Current: Day 4, 14:23                                               │
├─────────────────────────────────────────────────────────────────────┤
│ Judge Panel (visible during validation runs)                        │
│ Run ID: 26a9b231                                                    │
│ S1_P0: PASS · S1_P1: PASS · S1_P2: PASS · S1_P3: FAIL · ...        │
│ Total: 3/9 PASS                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component details

### Scenario picker

- List of preset scenarios
- Each: name, brief description, expected duration, difficulty stars
- Active scenario chip
- Start / Stop / Restart buttons
- "Custom" link → opens external editor (P2 — opens YAML in IDE)

### Persona toggles

- Each persona: avatar + name + role + on/off switch
- Hover persona → description ("Bilal asks operator questions, expects T2 advisories")
- Bulk: "All on" / "All off"

### Clock scrubber

- Big pause/play button
- Speed selector: 1x (real-time), 6x, 60x
- Jump to event dropdown: picks predefined events in scenario timeline
- Jump to day picker
- Current sim time displayed prominently

### Judge panel

- Visible only when scenario is running with judge enabled
- Run ID
- Phase score table (P0 / P1 / P2 / P3 etc.)
- Total score
- Click phase → opens judge detail (verdicts per rubric criterion)

### Building loader

- Currently loaded building.yaml
- Change building → file picker or dropdown
- Reload → flush state, re-init with current building

---

## States

- **No scenario running**: scenario list visible, persona toggles disabled
- **Scenario running**: scenario row highlighted, controls active, judge panel may show
- **Scenario paused**: dimmed scenario indicator, prominent resume button
- **Scenario completed**: result summary banner ("Refrigerant Migration completed — judge passed 7/9")
- **Building reloading**: loading state for the entire app, "Booting building"
- **Cockpit hidden** (in PILOT/PROD): screen not accessible — sidebar nav item absent

---

## Flows

### Flow A — Sales demo

1. Sales rep arrives at customer meeting
2. Opens Sim Cockpit → loads Marina Heights
3. Picks "Refrigerant Migration" scenario
4. Enables Bilal persona only (simpler narrative)
5. Sets clock 6x speed, hits Play
6. Sales rep narrates while UI plays out
7. Pauses at advisory raise → walks customer through Advisory Detail
8. Resumes, scenario completes
9. Resets for next customer

### Flow B — Engineer debugs

1. Engineer reproducing a bug
2. Loads same building.yaml from prior failed run
3. Picks same scenario
4. Sets speed 1x, runs to failure point
5. Pauses, inspects state
6. Files fix
7. Reloads scenario from start, validates fix

### Flow C — QA regression

1. QA runs all scenarios in sequence with judge enabled
2. Judge panel populates as each phase scores
3. Final report exported (CSV) for tracking pass rate

---

## Design principles

1. **Cockpit doesn't change the main UI**. It only controls inputs. Main screens render identically.
2. **Cockpit is for power users**. Density and density. Not a hand-holding wizard.
3. **One mode badge in shell + this screen are the only SIM indicators**. Rest of UI must work indistinguishably.
4. **Judge panel is read-only**. Scores don't gate progress — they inform.
5. **Time scrubbing should not panic the engine**. Visual feedback ("Jumping to Day 4...") during heavy state moves.

---

## Edge cases

- Run scenario in PROD mode (impossible — feature gated to SIM)
- Scenario fails to start (missing data, model load): error toast + fallback to no-scenario state
- Persona toggle during running scenario: takes effect at next persona turn, not retroactive
- Clock at maximum speed during heavy compute: drops back to 6x automatically
- Building reload during running scenario: confirm modal "Discard scenario state?"

---

## Open questions

1. **Scenario authoring UI**: P2 nice-to-have or never (engineers edit YAML)?
2. **Judge panel always visible vs only on validation runs**: only on runs, but make explicit toggle.
3. **Mode badge in chrome already shows SIM** — duplicate label here OK or redundant?
4. **Scenario branching**: support multiple paths through same scenario? P3.
5. **Multi-tab demo**: same scenario, two views (operator + manager)? P3.

---

## Success criteria

- Sales rep runs demo solo within 1hr training
- Engineer reproduces bug in <5 min from failed run ID
- Judge panel populates within 1s of phase completion

## What designer needs from engineering

- Final scenario list with metadata
- Persona definitions (which personas exist, what they do)
- Judge rubric (per phase scoring criteria)
- Building.yaml schema preview

## Changelog

- v1 2026-05-23: initial
