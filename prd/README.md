# ARVIS Console — Product Requirement Documents

Self-contained design + engineering briefs for every screen in the ARVIS operator console.

## Audience

- **Product designers** with no prior ARVIS context — read `*/designer.md`
- **Frontend engineers** with no prior ARVIS context — read `*/engineer.md`

Each file is **standalone**. It teaches the ARVIS basics it needs in a 30-second primer at the top, then deep-dives into the feature. You do not need to read other files to start work on yours.

## Structure

```
prd/
  README.md                    — this file
  _shared/                     — optional reference, deeper detail
    arvis_primer.md            — what ARVIS is and does
    design_system.md           — colors, type, components, motion
    data_model.md              — the nouns the UI manipulates
    api_contracts.md           — REST + streaming endpoint shapes
  shell/                       — top bar, nav, auth, mode toggle
  live_view/                   — home screen, schematic, alarms, advisories
  advisory_detail/             — the trust screen (agent trace + verifier gates + counterfactual)
  equipment_detail/            — per-machine deep dive with physics overlay
  memory_knowledge/            — searchable past incidents, patterns, skillbook
  compliance_gsas/             — GSAS sustainability scoring + audit package
  audit_replay/                — debug any past advisory
  simulation_cockpit/          — demo controls (scenarios, personas, clock)
  onboarding_wizard/           — new building setup, BACnet mapping, shadow toggle
  operator_actions/            — approve / reject / snooze / feedback flows
  notifications/               — bell, toast, email, pager rules
  exec_kpi/                    — owner roll-up dashboard
  settings_roles/              — permissions, building config, integrations
```

## Picking up a feature

1. Open `prd/<feature>/designer.md` or `prd/<feature>/engineer.md`
2. Read the 30-second ARVIS primer at top
3. Read the scope + non-goals
4. Read the per-screen / per-component section
5. Open `_shared/` only if you need deeper reference

## Versioning

All PRDs are v1. Date: 2026-05-23. Updates land per-file with a changelog block at the bottom.

## Naming conventions

- **Advisory** — ARVIS's recommendation to the operator (the core artifact)
- **Risk Tier** — T1 info / T2 diagnostic / T3 actionable
- **Agent Trace** — reasoning record of which AI agents voted what
- **Evidence Ledger** — every fact ARVIS used, with its source
- **Verifier Gates** — three automated checks (Claim / Faithfulness / Physics) every advisory must pass
- **Mode** — SIM (synthetic) / PILOT (real building, shadow) / PROD (real building, live)
- **Operator** — building operator (the primary user)
- **Equipment** — chiller, AHU, pump, etc.

These terms appear across every feature. Designer and engineer use them identically.

## Open questions across all PRDs

If you find yourself blocked because a PRD says "depends on X" — check `_shared/api_contracts.md` first, then ask the product owner before guessing. Don't fabricate.
