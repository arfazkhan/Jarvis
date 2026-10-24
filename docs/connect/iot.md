# Rung 4: IoT and retrofit sensors (MQTT, LoRaWAN), and SNMP

## MQTT
Most retrofit sensors publish over MQTT, and so does every LoRaWAN network server: current clamps on pumps, vibration on motors, pipe and cold-room temperature, leak, air quality, tank level.

ARVIS **subscribes**. It never publishes.

```yaml
- id: iot
  kind: mqtt
  host: 127.0.0.1                  # the bundled broker (docker-compose.iot.yml) or the site's own
  username_env: ARVIS_MQTT_USERNAME
  password_env: ARVIS_MQTT_PASSWORD
  stale_after_s: 900
  points:
    - {point_id: CHWP-1/AMPS, topic: plant/chwp1/current, value: "$.amps", unit: A}
    - {point_id: TANK-1/LVL,  preset: chirpstack, device: a84041000181c45b, field: level, unit: "%"}
    - {point_id: LEAK-B2/WET, preset: ttn, device: leak-b2-01, field: water_leak,
       alarm_when: {op: "==", value: 1, severity: high, message: "Water leak, basement 2"}}
```
Each point takes:
- `value`: a JSON path into the payload (`$.a.b`, `$.list[0]`). Plain numbers and on/off payloads work without one.
- `ts`: the reading's own timestamp, when the payload has one.
- `scale` / `offset`: if the raw value needs converting.

**LoRaWAN presets.** `chirpstack` (v4) and `ttn` (v3) know the uplink topic and where the decoded fields sit. Give the `device` and the `field`.

**Freshness.** A sensor that goes silent for `stale_after_s` is marked STALE once, with its last value.

**Broker.** `docker-compose.iot.yml` runs a local Mosquitto with password auth only (no anonymous access), listening on loopback and on the IoT-side address.

## SNMP
UPS units, PDUs and server-room cooling usually have a network card that answers SNMP. ARVIS only reads them (GET); it never changes their settings (SET).

```yaml
- id: ups
  kind: snmp
  host: 10.10.0.30
  version: 2c
  community_env: ARVIS_SNMP_COMMUNITY        # the community string is a secret: never in the file
  devices:
    - {template: ups_mib, equipment_id: UPS-1}  # RFC 1628: charge, battery V, load, voltages, alarms
  points:
    - {point_id: CRAC-1/RAT, oid: 1.3.6.1.4.1.476.1.42.3.4.1.2.3.1.3.1, unit: "°C", scale: 0.1}
```
- **SNMPv3:** set `version: 3` with `user`, `auth_key_env` and `priv_key_env` (SHA/AES by default).
- **Templates:** they live in `config/templates/snmp/`. The UPS template already raises an alarm when the UPS reports one.

## Install
```bash
pip install -r requirements-connectors.txt
```
Each package is only needed on sites that use that source kind.
