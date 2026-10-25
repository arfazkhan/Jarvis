# Connecting a building to ARVIS

Any building can be connected, whatever it has. Work down this ladder. Most sites use several rungs at once, listed together as `sources:` in the site config (see `config/sources.example.yaml`).

ARVIS is **read-only** on every rung: it never writes to a building system.

| Rung | What it covers | How | Guide |
|---|---|---|---|
| 1. The BMS | Everything the BMS already sees (HVAC, often lifts and fire panels through their gateways) | BACnet/IP, Modbus TCP, OPC UA | [bms.md](bms.md) |
| 2. Serial devices | Meters, gensets, drives and controllers with RS-485 and no Ethernet | Modbus RTU, and BACnet MS/TP through a router | [bms.md](bms.md) |
| 3. Dumb equipment | Anything with a relay contact, a 4–20 mA transmitter or a pulse output | A Modbus I/O module, about $100–200 | [io_modules.md](io_modules.md) |
| 4. IoT, retrofit sensors, IT room | Current clamps, vibration, leak, air quality, LoRaWAN; UPS, PDUs, CRAC | MQTT (local broker), SNMP | [iot.md](iot.md) |
| 5. People | Gauges, mechanical meters, anything read by eye | WhatsApp readings, gauge photos, reading rounds, logbooks | [people.md](people.md) |
| 6. Events | Access control, people counters, room bookings | Webhook, CSV, calendar files | [events.md](events.md) |
| 7. History and vendors | Trend exports, utility bills, vendor cloud APIs | Import, REST | [history_vendors.md](history_vendors.md) |
| 8. Meters, lighting, rooms | BTU / water / electricity meters on M-Bus; KNX lighting, blinds, room controllers; DALI through its gateway | M-Bus, KNX (listen-only) | [knx_mbus.md](knx_mbus.md) |
| — | EV chargers | the CSMS's API, Modbus, the circuit meter — not OCPP ([why](ev_chargers.md)) | [ev_chargers.md](ev_chargers.md) |

## Systems with only a vendor cloud

Some systems, such as lifts, VRF, solar or access control, only offer data through the vendor's cloud.

- **By default**, staff report on WhatsApp ("lift 2 is down").
- **When the vendor offers an API**, ARVIS polls it. The vendor's host must be enabled for that site in `ARVIS_EGRESS_ALLOW`, signed off by the site and logged.

Once connected, see [coverage.md](coverage.md) for what ARVIS can see, what to add next, and how any point can raise an alarm.
