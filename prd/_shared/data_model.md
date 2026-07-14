# ARVIS Data Model

Common types referenced across all features. Designer skims for the nouns; engineer treats as schema spec.

## Building

```
Building {
  id: uuid
  display_name: string         // "Marina Heights Tower"
  spec_version: string         // "1.0.0"
  timezone: string             // "Asia/Qatar"
  floor_area_m2: number
  occupancy_density: number
  mode: "SIM" | "PILOT" | "PROD"
  shadow_mode: boolean         // PILOT only; true means non-actionable
}
```

## Equipment

```
Equipment {
  id: string                   // "CH-1", "AHU-3"
  kind: "chiller" | "ahu" | "pump" | "fan" | "vav" | "valve"
  display_name: string
  model: string                // "Carrier 30XA"
  design_capacity_kw: number?
  design_cop: number?
  parent_id: string?
  children_ids: string[]
  status: "running" | "stopped" | "fault" | "unknown"
}
```

## Point

```
Point {
  id: string                   // "CH-1/EVAP_LWT"
  equipment_id: string
  kind: "temperature" | "pressure" | "flow" | "power" | "status" | "command"
  unit: string                 // "C", "kPa", "kW", "lps", "bool"
  current_value: number | boolean
  current_value_ts: iso8601
  is_stale: boolean            // true if last update > expected interval
}
```

## Alarm

```
Alarm {
  id: string                   // "ALM-AHU7-014"
  equipment_id: string
  raised_at: iso8601
  cleared_at: iso8601?
  severity: "info" | "warning" | "critical"
  category: string             // "SAT_DEVIATION", "CHW_VALVE_SATURATION"
  message: string
  acked_by: string?
  acked_at: iso8601?
}
```

## Advisory

The central artifact. Designer reads top-down; engineer reads carefully.

```
Advisory {
  id: uuid
  building_id: uuid
  equipment_ids: string[]      // can target multiple
  created_at: iso8601
  status: "pending" | "approved" | "rejected" | "snoozed" | "auto_withdrawn"
  shadow: boolean
  risk_tier: "T1" | "T2" | "T3"
  
  summary: string              // one-sentence headline
  recommendation: {
    action: string             // "schedule_inspection", "adjust_setpoint"
    target_equipment_id: string?
    target_setpoint?: { point_id: string, value: number, unit: string }
    target_window_hours: number?
    expected_savings_kwh_per_day: number?
    expected_mtbf_delta_days: number?
  }
  
  plan: InvestigationPlan
  evidence_ledger: Evidence[]
  swarm_votes: AgentVote[]
  verifier_gates: VerifierGates
  counterfactual: Counterfactual
  operator_context: OperatorContext
}
```

## InvestigationPlan

```
InvestigationPlan {
  plan_id: uuid
  investigation_steps: PlanStep[]
  shared_call_sigs: string[]
  budget: {
    max_tokens: number
    tokens_used: number
    max_seconds: number
    seconds_used: number
  }
}

PlanStep {
  step_id: number
  agent: string                // "Maintenance_Agent"
  tool: string                 // "get_point_history"
  call_sig: string
  status: "ok" | "error" | "timeout"
  duration_ms: number
}
```

## Evidence

```
Evidence {
  evidence_id: uuid
  call_sig: string             // joins to plan step
  source_type: "historian" | "live_sensor" | "physics_simulator" | "memory" | "ml_model" | "operator_input" | "external_doc"
  source_ref: string           // human-readable
  value_summary: string        // "min=2.1, max=2.8, avg=2.4 over 24h"
  is_ml_fallback: boolean
  ml_lineage: object?          // model id, training date, confidence
  ingested_at: iso8601
}
```

## AgentVote

```
AgentVote {
  agent: string                // "Energy_Agent"
  verdict: "APPROVE" | "APPROVE_WITH_CONDITION" | "VETO" | "ABSTAIN"
  confidence: number | null    // 0-1; null when ABSTAIN
  conditions: string[]
  reasoning_summary: string
}
```

## VerifierGates

```
VerifierGates {
  h2_claim: {
    status: "pass" | "fail"
    score: number              // 0-1
    blocked_claims: string[]
  }
  h4_faithfulness: {
    status: "pass" | "fail"
    score: number
    contradictions: string[]
    regen_attempts: number
  }
  h6_physics: {
    status: "pass" | "fail" | "skipped"
    deviation_pct: number?
    threshold_pct: number
  }
  abstention_gate: {
    fired: boolean
    signals: {
      data_coverage: number
      truth_score: number
      ml_fallback_ratio: number
      max_drift: number
    }
  }
}
```

## Counterfactual

```
Counterfactual {
  without_action: {
    horizon_hours: number
    predicted_failure_probability: number
    predicted_kwh_overage: number
  }
  with_action: {
    horizon_hours: number
    predicted_failure_probability: number
    predicted_kwh_overage: number
  }
}
```

## OperatorContext

```
OperatorContext {
  recent_actions_5min: OperatorAction[]
  attributed_to_operator: boolean   // true when advisory cause traces to recent operator change
}

OperatorAction {
  operator_id: string
  action_type: "setpoint_change" | "alarm_ack" | "override"
  point_id: string?
  prev_value: any?
  new_value: any?
  ts: iso8601
}
```

## Memory entries

```
MemoryEntry {
  id: uuid
  tier: "T3" | "T7"            // T3 = procedural pattern, T7 = resolution outcome
  bucket: "primary" | "shadow"
  title: string
  body: string
  embedding: float[]
  linked_advisory_ids: uuid[]
  created_at: iso8601
  last_used_at: iso8601
}
```

## GSAS

```
GSASCriterion {
  id: string                   // "ENE-01"
  category: "Energy" | "Water" | "IndoorEnv" | "Materials" | "Waste" | "Site" | "Management" | "CulturalEcon"
  name: string
  benchmark: { value: number, unit: string, operator: "<=" | ">=" | "==" }
  current_value: number
  status: "met" | "at_risk" | "failed"
  points_earned: number
  points_max: number
  evidence_ids: uuid[]
  recovery_actions: RecoveryAction[]
}

GSASScore {
  building_id: uuid
  rating_period_id: string     // "2026-Annual"
  total_points: number
  total_max: number
  star_rating: 1 | 2 | 3 | 4 | 5 | 6
  star_projected: 1 | 2 | 3 | 4 | 5 | 6
  trajectory: { date: iso8601, points: number }[]
  by_category: { category: string, earned: number, max: number, status: string }[]
}
```

## Streaming envelopes

```
StreamEvent {
  event_type: "advisory_published" | "advisory_state_change" | "alarm_new" | "alarm_cleared" | "point_update" | "trace_event"
  event_id: string
  ts: iso8601
  building_id: uuid
  payload: object              // type-specific
}
```

## IDs

- Building / Advisory / Plan / Evidence / OperatorAction: UUIDv4
- Equipment / Point / Alarm: human-readable strings ("CH-1", "AHU-7/MAT")
- Timestamps: ISO-8601 UTC
- Money: USD/QAR minor units (cents/dirhams) where applicable
