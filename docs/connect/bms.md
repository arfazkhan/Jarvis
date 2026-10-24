# Rungs 1–2: the BMS and serial devices

Each block below is one entry in the site config's `sources:` list. A single block under `bacnet:`, `modbus:` or `opcua:` also still works, as does `ARVIS_MODE`.

## BACnet/IP
```yaml
- {id: plant_bms, kind: bacnet, local_address: 10.10.0.50/24, points: [...], registries: [...]}
```
- `points` are read with ReadProperty and ReadPropertyMultiple.
- BACnet devices that are in alarm raise ARVIS alarms. The `inAlarm` flag must stay set on two reads in a row before ARVIS counts it.
- `registries` imports VOLTTRON registry CSVs.

## BACnet MS/TP (RS-485 field controllers)
MS/TP controllers sit behind a BACnet/IP router, which most BMS head-ends already have.

- **Listing points:** list the MS/TP devices' points with their device instance numbers, exactly like BACnet/IP points. The router forwards the requests.
- **Finding devices:** if ARVIS doesn't find them, check that the router's BBMD / network-number settings let ARVIS's subnet see the MS/TP network.

## Modbus TCP
```yaml
- {id: meters, kind: modbus, host: 10.10.0.60, port: 502, unit_id: 1, registers: [...]}
```

## Modbus RTU (RS-485, no Ethernet)
Energy meters, genset controllers, VFDs and I/O modules on a serial bus. Connect a USB–RS-485 adapter to the ARVIS box, or point ARVIS at an RS-485–to–TCP gateway, which then counts as Modbus TCP.

```yaml
- id: genset
  kind: modbus
  transport: rtu
  serial_port: /dev/ttyUSB0      # Windows: COM3
  baudrate: 9600                 # match the device: 9600 / 19200 / 38400
  parity: N                      # N | E | O
  stopbits: 1
  bytesize: 8
  unit_id: 1                     # each device on the bus has its own; per register: unit_id
  registers:
    - {point_id: GEN-1/FUEL, register_type: holding, address: 1027, unit: "%", equipment_id: GEN-1}
```
In Docker, pass the serial device through: `devices: ["/dev/ttyUSB0:/dev/ttyUSB0"]`.

## OPC UA
```yaml
- {id: lighting, kind: opcua, endpoint: opc.tcp://10.10.0.70:4840, points: [...]}
```
Credentials come from the environment only: `ARVIS_OPCUA_USERNAME` / `ARVIS_OPCUA_PASSWORD`.
