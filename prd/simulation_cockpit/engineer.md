# Simulation Cockpit — Frontend Engineer Brief

**Feature**: `/sim` — visible only in SIM mode. Controls scenarios, personas, clock, building loader, judge panel.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS has three runtime modes: SIM (synthetic), PILOT (real building shadow), PROD (live). In SIM mode, a backend persona generator drives synthetic events. The cockpit is the FE controller for that generator. Hidden in PILOT/PROD.

---

## What you're building

Route: `/sim`.

Sections:
- Building loader
- Scenario picker + start/stop
- Persona toggles
- Clock controls
- Judge panel

Sub-nav item hidden in PILOT/PROD via `me.mode !== 'SIM'` guard.

---

## Stack

Same as `shell/`. No special libs.

---

## File layout

```
app/(authed)/sim/
  page.tsx
  loading.tsx

components/sim/
  SimulationCockpit.tsx
  BuildingLoader.tsx
  ScenarioPicker.tsx
  ScenarioCard.tsx
  PersonaToggles.tsx
  PersonaToggle.tsx
  ClockControls.tsx
  JudgePanel.tsx
  JudgePhaseRow.tsx

lib/
  api/
    sim.ts
```

---

## Data dependencies

### Endpoints (SIM only)

```
GET  /api/v1/sim/scenarios                          → Scenario[]
POST /api/v1/sim/scenario/start                     → { run_id }
POST /api/v1/sim/scenario/pause
POST /api/v1/sim/scenario/resume
POST /api/v1/sim/scenario/reset
POST /api/v1/sim/persona/{name}/enable
POST /api/v1/sim/persona/{name}/disable
GET  /api/v1/sim/clock                              → { sim_time, speed, paused }
POST /api/v1/sim/clock/set                          → { sim_time?, speed?, paused? }
GET  /api/v1/sim/buildings                          → BuildingProfile[]
POST /api/v1/sim/building/load                      → loads building.yaml
GET  /api/v1/sim/judge-verdicts/{run_id}            → JudgeVerdicts
GET  /api/v1/sim/personas                           → Persona[]
GET  /api/v1/sim/state                              → { active_scenario, run_id, personas_enabled, clock }
```

### SSE

Topic: `sim_state`. Events:
- `sim_clock_tick` — clock advanced
- `sim_scenario_event` — scenario reached a defined event
- `sim_judge_phase_complete` — judge scored a phase

### Cache keys

```
['sim-scenarios']
['sim-state']
['sim-personas']
['sim-buildings']
['sim-judge', runId]
```

---

## Components

### `<SimulationCockpit>`

Root client component.

Guard: if `me.mode !== 'SIM'`, redirect to `/live-view`.

### `<BuildingLoader>`

```tsx
<div className="building-loader card">
  <span className="label">Loaded building</span>
  <span className="font-mono">{state.building_id}</span>
  <Button variant="secondary" onClick={() => setBuildingPickerOpen(true)}>Change</Button>
  <Button variant="ghost" onClick={reloadBuilding}>Reload</Button>
</div>
```

Building picker modal: list available buildings with metadata.

Load triggers full app re-init (route to `/live-view` after).

### `<ScenarioPicker>`

List of scenarios. Active scenario highlighted.

Selecting a scenario shows description + difficulty + duration in side panel.

Buttons: Start (if not running) / Stop (if running) / Reset.

### `<PersonaToggles>`

Grid of `<PersonaToggle>`. Each:
```tsx
<label className="persona-toggle">
  <Switch checked={enabled} onChange={(v) => toggle(persona.name, v)} />
  <Avatar src={persona.avatar} fallback={persona.initials} />
  <div>
    <span className="font-medium">{persona.display_name}</span>
    <span className="text-sm text-muted">{persona.role}</span>
  </div>
</label>
```

Tooltip with persona description on hover.

### `<ClockControls>`

```tsx
<div className="clock-controls">
  <Button onClick={togglePause}>{paused ? '▶ Play' : '⏸ Pause'}</Button>
  <SpeedSelector value={speed} onChange={setSpeed} options={[1, 6, 60]} />
  <span className="font-mono">{formatSimTime(simTime)}</span>
  <JumpToEventDropdown onJump={(eventId) => jumpToEvent(eventId)} />
  <JumpToDayDropdown onJump={(day) => jumpToDay(day)} />
</div>
```

Clock polls `/sim/clock` every 1s OR subscribes to SSE clock_tick (preferred).

### `<JudgePanel>`

Shows phase scores in a table.

```tsx
<table className="judge-table">
  <thead>
    <tr><th>Phase</th><th>Score</th><th>Verdict</th></tr>
  </thead>
  <tbody>
    {verdicts.phases.map(p => (
      <tr key={p.id}>
        <td>{p.id}</td>
        <td className="font-mono">{p.score}/{p.max}</td>
        <td><VerdictChip status={p.status} /></td>
      </tr>
    ))}
  </tbody>
</table>
<div className="total">
  Total: {verdicts.total_pass}/{verdicts.total_phases} PASS
</div>
```

Row click → modal with detail (per-rubric criterion scores).

---

## State management

- React Query for scenarios + personas + buildings + judge data
- SSE keeps sim_state cache live
- Zustand for: building picker modal open, scenario detail expanded

---

## Performance budgets

| Operation | Target |
|---|---|
| Cockpit load | <800ms |
| Start scenario click → first sim event | <2s |
| Speed change | <200ms |
| Persona toggle | <300ms |
| Judge panel update on phase complete | <500ms |

---

## Testing

### Unit

- Cockpit redirects when not SIM mode
- Persona toggle optimistic UI
- Clock speed selector

### Integration

- Start scenario → SSE event arrives → main UI shows expected response
- Reset clears state → main UI returns to baseline
- Mode change while in cockpit → redirected out

---

## Edge cases

- Backend in SIM but engine paused: clock shows paused, scenario list disabled
- Scenario start fails: error toast, no run created
- Building load timeout: show loading state, retry
- User changes mode during run: warn, then redirect

---

## Integration points

- `shell/` — mode badge confirms SIM
- All other screens — they observe sim state via existing endpoints; cockpit is just a controller
- Backend persona generator — owns events; FE just toggles

---

## Open questions

1. Building list endpoint exists? Confirm shape.
2. Judge verdicts shape — match what backend writes today?
3. Persona definitions — config-driven or hardcoded?

## Changelog

- v1 2026-05-23: initial
