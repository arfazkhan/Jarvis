# Rung 5: readings taken by people

Gauges, mechanical meters, sight glasses, a standalone split's display: no protocol reaches them, but a technician does. Declare what gets read and how often. ARVIS then asks for the readings on time, takes them over WhatsApp, and treats them like any other data point: it trends them, learns from them and alarms on them.

```yaml
sources:
  - id: rounds
    kind: manual
    points:
      - {point_id: TANK-1/LVL, name: Tank 1 level, equipment_id: TANK-1, unit: "%",
         min: 0, max: 100, expected_interval_h: 12, aliases: [roof tank]}
      - {point_id: CHWP-1/DP, name: CHW pump 1 discharge, equipment_id: CHWP-1, unit: bar,
         min: 0, max: 10, capture: photo}
    rounds:
      - {name: Morning plant round, at: ["07:30"], to: "+97455501234", points: [TANK-1/LVL, CHWP-1/DP]}
```

## How readings arrive

| How | Example | Trust |
|---|---|---|
| Reading round reply | "tank 1 62", one per line | 0.9 |
| Typed in conversation | "fyi the roof tank is at 58%" | 0.9 |
| Gauge photo | ARVIS reads the dial, the person confirms ("From the photo I read 4.2 bar for CHW pump 1 discharge — is that right?") | 0.85 once confirmed |
| Logbook CSV | `POST /api/v1/readings/import` with columns `point_id,value[,unit][,observed_at][,technician]` | 0.85 |
| API | `POST /api/v1/points/{id}/readings` (send an `Idempotency-Key` header) | 0.9 |

## Rules
- **Doubtful readings wait.** A reading outside `min`/`max`, a big jump from the last one, or anything read off a photo is not used until someone confirms it with "yes", "no", or the right number.
- **Units convert.** For example, "420 kPa" is stored as 4.2 bar. A unit that can't apply is refused.
- **Instrument points are never overwritten.** A hand-taken reading of a point an instrument already reads is kept as a check on that sensor, together with the difference between the two.
- **Overdue readings appear in the facilities manager's morning brief.**
- **Rounds go to a phone number, or `to: group` for the ops group.** They run in building local time (`ARVIS_TZ`) and go out at most once per slot, even after a restart.
