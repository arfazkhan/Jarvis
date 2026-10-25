# EV chargers: why ARVIS does not speak OCPP to them

## The review

OCPP is how chargers talk to their management system (the CSMS). The CSMS:
- accepts each charger's connection;
- **answers its authorisation requests** ("may this card charge?");
- starts and stops transactions;
- can reconfigure and reset the charger.

A charger points at exactly one CSMS. For ARVIS to receive OCPP directly, it would have to *be* that CSMS. Even the bare minimum means answering BootNotification, Authorize and StartTransaction. Those answers decide whether the charger is accepted and **who may charge**. That is control of the building's equipment, not reading it.

Most sites also already have a CSMS for billing and access. Re-pointing chargers to ARVIS would take that away.

The other option is an OCPP relay between charger and CSMS that only observes. It is still **in-line**: if ARVIS is down, the chargers lose their CSMS. A read-only product must never sit in the path of the systems it watches.

**Decision:** ARVIS does not implement OCPP, as CSMS or as relay. Reopen this only for a site whose owner explicitly wants ARVIS as the CSMS. That is a different product with different liability.

## How EV chargers are connected instead (all read-only, none in-line)

| Path | When |
|---|---|
| The CSMS's API (`kind: rest`, [history_vendors.md](history_vendors.md)) | Most sites. Power, status and faults per charger, from the system that already has them |
| Modbus TCP on the charger (`kind: modbus`) | Many commercial chargers expose read registers for power, energy and state. Use the register map from the charger's manual |
| The charger circuit's meter (Modbus / M-Bus / I/O module pulse) | No API and no Modbus: at least the energy and power drawn |
| WhatsApp (`kind: manual` / events) | Nothing else: staff report "charger 3 is out of order" |

In coverage, an EV charger needs `electric-power`, and `fault-status` is optional.
