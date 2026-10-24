# Rung 3: dumb equipment, through a Modbus I/O module

Most "unconnectable" equipment still has something electrical to tap:

| It has | Examples | Template |
|---|---|---|
| A volt-free (dry) contact | lift fault / in service, pump running auxiliary, generator running / common alarm, sump high-level float, fire-pump running, panel "common alarm" | `digital_inputs` |
| A 4–20 mA or 0–10 V signal | tank level transmitter, pressure transmitter, a BTU meter's analogue output | `analog_4_20ma` |
| A pulse output | water, gas, energy and BTU meters | `pulse_counters` |

1. Wire these to a Modbus I/O module, a DIN-rail box costing about $100–200 (TCP or RS-485).
2. Name the module's template and say what is on each channel. ARVIS works out the register addresses and the scaling.

```yaml
- id: plantroom_io
  kind: modbus
  host: 10.10.0.80          # or transport: rtu + serial_port
  io_modules:
    - template: digital_inputs
      unit_id: 3
      channels:
        0: {point_id: LIFT-1/FAULT,  equipment_id: LIFT-1}
        1: {point_id: LIFT-1/INSVC,  equipment_id: LIFT-1}
        2: {point_id: FP-1/RUN,      equipment_id: FP-1}
        3: {point_id: GEN-1/RUN,     equipment_id: GEN-1}
        4: {point_id: SUMP-1/HIGH,   equipment_id: SUMP-1}
    - template: analog_4_20ma
      unit_id: 4
      raw_range: [4000, 20000]   # this module's counts at 4 mA and 20 mA (from its manual)
      channels:
        0: {point_id: TANK-1/LVL, equipment_id: TANK-1, unit: "%",   range: [0, 100]}
        1: {point_id: CHWP-1/DP,  equipment_id: CHWP-1, unit: "kPa", range: [0, 250]}
    - template: pulse_counters
      unit_id: 5
      channels:
        0: {point_id: WM-1/TOTAL, equipment_id: WM-1, unit: m3, per_pulse: 0.01}
```

Every module is a little different, and its manual is the source of truth. Any field of a template can be overridden for one module:
- `address_base`: where the channels start;
- `register_type`: some modules expose inputs as coils;
- `raw_range`: the module's counts at 4 mA and 20 mA.

The templates live in `config/templates/io_modules/`. Add a file there for a module family you use often.

**Safety.** ARVIS only *reads* the module. Never wire a module output into a control or safety circuit for ARVIS's sake; ARVIS has no use for outputs.
