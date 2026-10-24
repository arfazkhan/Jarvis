# What ARVIS sees, what's missing, and alarms from any source

## Coverage
`config/equipment_catalog.yaml` says what each kind of equipment needs. It covers HVAC (AHU, VAV, FCU, chiller, pumps, cooling towers, transfer stations, meters) and the rest of the building (lifts, escalators, generators, UPS, transformers, ATS, tanks, booster/sump/fire pumps, STP, cold rooms, CRAC, EV chargers, solar, fire panels, gas detection, doors, people counters).

ARVIS compares the catalog with the building and classes each need as:

- **connected**: an instrument reads it;
- **manual**: a person reads it;
- **imported**: only historical data was imported;
- **missing**: nothing gives ARVIS this yet.

| Level | Meaning |
|---|---|
| **Full** | ≥ 90 % of needs read by instruments |
| **Partial** | ≥ 40 % by instruments |
| **Limited** | some instruments, or ≥ 40 % covered including readings taken by people |
| **Manual** | no instruments, but people read some of it |

**What to add next.** Missing needs are ranked by how many fault checks each one would switch on. Each comes with the plain-words way to connect it: "wire its contact to a Modbus I/O module", "add it to a reading round", and so on.

**Where to see it:**
- `GET /api/v1/coverage`;
- on WhatsApp ("what can't you see?");
- a line in the owner's weekly brief.

**Naming equipment.** Equipment kinds come from the equipment type, or from the ID prefix: `GEN-`, `DG-`, `LIFT-`, `UPS-`, `TANK-`, `FP-`, `JP-`, `SUMP-`, `STP-`, `CRAC-`, `COLD-`, `PV-`, `EV-`, `FACP-`, `GD-`, `DOOR-`, … Equipment that matches no kind is listed as unrecognised. Give it a `type:` in commissioning.

## What feeds what
In the commissioning spec, `serves: [...]` on an equipment, or `fed_by: [...]` on the one it feeds, builds the topology ARVIS uses to say what a failure affects downstream.

## Alarms from any source
BACnet devices report their own alarms. For everything else (Modbus, I/O modules, OPC UA, MQTT, SNMP, readings taken by people), put a rule on the point:

```yaml
- {point_id: LIFT-1/FAULT, ..., alarm_when: {op: "==", value: 1, severity: high, message: "Lift 1 is in fault"}}
- {point_id: TX-1/TEMP,   ..., alarm_when: {op: ">", value: 110, for_s: 300, clear_below: 100, severity: high}}
- {point_id: GEN-1/FUEL,  ..., alarm_when: {op: "<", value: 25, clear_above: 35, severity: medium}}
```

- **Delay (`for_s`):** the condition must hold for that long before the alarm is raised.
- **Hysteresis (`clear_below` / `clear_above`):** the alarm clears at a different threshold from the one that raised it, so it doesn't flap.
- **Dead sensors don't count:** a reading with BAD or STALE quality never raises an alarm.
- **Same path as BMS alarms:** raised alarms follow the same route as BMS alarms, so WhatsApp, escalation and the brief handle them unchanged.
