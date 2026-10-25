# Meters on M-Bus, lighting and rooms on KNX, DALI lighting

## M-Bus: heat / cooling (BTU), water and electricity meters

Tenant BTU meters and water meters very often sit on an M-Bus. A level converter, usually with an Ethernet port (a "TCP gateway"), makes the bus reachable.

```yaml
sources:
  - id: btu
    kind: mbus
    required: false
    transport: tcp              # or serial: serial_port: COM4 (needs pyserial), baudrate: 2400
    host: 10.10.0.80
    port: 10001
    poll_interval: 900          # meters update slowly; every 15 min is plenty
    meters:
      - {address: 1, equipment_id: MTR-BTU-T1, type: cooling}   # cooling | heat | water | electricity | gas
      - {address: 2, equipment_id: MTR-W-01, type: water}
```

**What ARVIS reads.** Each meter's present values become points:

| Point | Unit |
|---|---|
| `ENERGY` | kWh |
| `VOLUME` | m³ |
| `POWER` | kW |
| `FLOW` | m³/h |
| `FLOW_TEMP`, `RETURN_TEMP` | °C |
| `TEMP_DIFF` | K |
| `OP_HOURS` | h |
| `VOLTAGE` | V |
| `CURRENT` | A |
| `STATUS_ERR` | 1 when the meter reports an error |

- **Roles follow `type`.** On a cooling meter, ENERGY is thermal energy and FLOW_TEMP is chilled-water supply. On an electricity meter, ENERGY is electric energy.
- **Errors.** While a meter reports an error, its values are marked *uncertain*.
- **What is left out.** Last month's stored values, tariff registers and min/max are not points. A record the decoder doesn't understand is skipped and counted (`records_skipped`), never guessed.

**Read-only.** ARVIS sends a meter only a link reset and a data request. It never sends data to a meter. A test enforces this.

**Primary addresses only (1–250).** Secondary addressing selects a meter by writing to the bus, so ARVIS doesn't do it. Give each meter a primary address at commissioning; that's the normal practice for a fixed installation.

**Not yet verified on a real meter.** The decoder follows EN 13757-3 and is tested on telegrams built to it. The first real gateway on site is its first live test. Check one meter's values against its display before relying on the rest.

## KNX: lighting, blinds, room controllers (listen-only)

KNX devices announce their state on the bus. ARVIS listens and never sends a telegram.

```yaml
sources:
  - id: knx
    kind: knx
    required: false
    mode: routing               # the KNX IP router's multicast — ARVIS sends nothing at all
    # mode: tunnelling          # an IP interface: host: 10.10.0.90 — ARVIS only keeps the tunnel open
    points:
      - {point_id: RM-501/TEMP, ga: 3/1/10, dpt: "9.001", unit: "°C", role: zone-temp, max_silence_s: 3600}
    devices:
      - {template: room_climate, equipment_id: FCU-501, ga: {TEMP: 3/1/10, SETPOINT: 3/2/10, VALVE: 3/3/10}}
```

**Choosing a mode**
- **Routing** is preferred whenever the installation has an IP *router*: it is pure listening.
- **Tunnelling** uses one of the IP interface's tunnels, which are usually limited to 1–4. Make sure the integrator's ETS session isn't left needing it.

**Group addresses and DPTs**
- The installation's ETS project lists the group addresses and their datapoint types (DPT).
- Supported DPTs: 1 (switch / status / alarm), 5 (percent, counter), 6, 7, 8, 9 (temperature, humidity, CO₂, lux), 12, 13, 14.

**When values arrive.** A value arrives when a device sends it: on change, or cyclically if the integrator set it up that way. Listening never asks, so a point shows nothing until its first telegram.

**Staleness.** `max_silence_s` marks a point stale when a device that should send cyclically goes quiet.

**Not supported.** KNX Secure (encrypted) installations.

**Not yet verified on a real installation.** The protocol is tested against a simulated interface in tests only, not a real router.

## DALI lighting

ARVIS reads DALI through the gateway the lighting system already has. It never talks DALI directly.

| Gateway | How |
|---|---|
| KNX-DALI (ABB DG/S, MDT, Siemens N 141, ...) | KNX source + template `dali_light`: STATUS, LEVEL, FAULT (lamp / driver failure, raises an alarm), POWER |
| BACnet-DALI | the BMS source: add the gateway's objects to the BACnet point list |
| Modbus-DALI | the Modbus source: add the gateway's registers from its manual |

The template only creates points for the objects you give a group address. Gateways differ in what they expose.

```yaml
devices:
  - {template: dali_light, equipment_id: LGT-L5-01, ga: {STATUS: 1/4/3, LEVEL: 1/2/3, FAULT: 1/7/3}}
```

Lighting shows up in coverage as its own kind (`LGT-`, `LTG-`, `DALI-`). It needs a status or a level, and lamp failures are optional.
