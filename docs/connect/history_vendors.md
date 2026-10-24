# History and vendors: trend exports, utility bills, vendor APIs

## Trend exports: months of history on day one

Every BMS can export trend logs. Importing them means ARVIS knows what "normal"
looks like (thresholds, baselines, the 28-day learning) without waiting four weeks.

```
POST /api/v1/import/trends     (admin)
  file     the export, CSV or XLSX
  tz       the timezone the export is in, e.g. Asia/Qatar, or "local" for this box (required)
  columns  optional JSON: {"AHU-01 Supply Air Temp (°C)": "AHU-01/SAT"}
```

Two shapes are understood:

| Shape | Columns |
|---|---|
| wide | `timestamp, AHU-01/SAT, AHU-01/RAT, ...` (one column per point) |
| long | `timestamp, point_id, value[, unit]` (one row per reading) |

- **Timezone.** It must be stated. Exports rarely say which one they use, and a wrong guess shifts every reading by hours.
- **Values.** `ON`/`OFF` and `true`/`false` become 1/0. Blanks and `#N/A` are skipped and counted.
- **History only.** Imported rows go straight into history with source `import`:
  - they never pass through the live building, so a value from last August can't raise an alarm today or replace a current reading;
  - coverage reports a point that has only imported data as **imported**, not connected.
- **XLSX** needs `openpyxl` (in `requirements-connectors.txt`). Otherwise export CSV.

## Utility bills

What the utility charged is the ground truth that the building's own meters are checked against. In a building with no meters, it is the only consumption figure.

Each bill becomes points dated the bill's last day:

| Point | Meaning |
|---|---|
| `<METER>/BILL_KWH` | electricity consumed in the period |
| `<METER>/BILL_M3` | water consumed in the period |
| `<METER>/BILL_COST` | amount charged (QAR) |

```
POST /api/v1/import/bills      (admin, operator)
  file     CSV: meter,period,kwh,m3,cost      (period = YYYY-MM; meter defaults to MAIN)
```

**A bill document** (photo or PDF, through GSAS ingestion) is read by the model:
- When the model reads it, the bill is recorded.
- When no model is available, a pattern match pulls out kWh, QAR and period, but the result waits for a person to confirm it.
- When the document can't be read at all, nothing is filled in. Nothing is ever made up from the filename.

## Vendor APIs (`kind: rest`)

Some systems, such as lifts, VRF, solar portals, access control and some gateways, only offer data through the vendor's API.

**By default**, staff report on WhatsApp ([people.md](people.md), [events.md](events.md)). **When the vendor offers an API**, ARVIS reads it:

```yaml
sources:
  - id: lifts
    kind: rest
    required: false
    base_url: https://api.lift-vendor.example
    headers_env: {Authorization: ARVIS_LIFT_API_AUTH}    # header values come from the environment
    push_token_env: ARVIS_LIFT_PUSH_TOKEN                 # only if the vendor pushes
    poll_interval: 120
    points:
      - {point_id: LIFT-2/INSVC, path: /v1/units/2/status, value: "$.inService"}
      - {point_id: LIFT-2/FAULT, path: /v1/units/2/status, value: "$.fault",
         alarm_when: {op: "==", value: 1, severity: high, message: "Lift 2 in fault"}}
      - {point_id: PV-1/KW, path: /v2/plants/77/now, value: "$.power_kw", unit: kW}
```

**How it reads**
- **GET only.** ARVIS never sends anything to the vendor. A test enforces this.
- Points that share a path are read with one request.
- `value` and `ts` are JSON paths (`$.a.b[0]`); `scale` and `offset` are optional.

**Approval and secrets**
- **Approved hosts only.** A cloud API means traffic leaves the site, so the host must be on the site's approved list (`ARVIS_EGRESS_ALLOW`), signed off by the site. Without that, the source refuses to start. A host on the site LAN needs no approval.
- **Secrets stay in the environment.** An inline `headers:`, `password:` or `token:` in the YAML is rejected.

**Vendors that push** post JSON to `POST /api/v1/push/<source id>` with the header `x-arvis-push-token`. The same mapping applies to points marked `push: true`. A source with no push token configured refuses every push.

Mappings for specific vendors are written when a real site needs them, against that vendor's documented API.
