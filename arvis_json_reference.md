# ARVIS JSON Response Reference Guide

This document provides a detailed reference for the JSON response structures of the 41 BMS tools and the 12-agent cognitive swarm communication protocols.

---

## 1. BMS Tool Response Schemas (41 Tools)

Tools are grouped by domain. Most tools return a dictionary where keys are specific to the tool's function.

### 1.1 Equipment Tools
| Tool Name | Key Fields | Description |
| :--- | :--- | :--- |
| [get_equipment_status](file:///e:/Automation/agent_commercial/tools/handlers/equipment.py#31-47) | `equipment_id`, [status](file:///e:/Automation/agent_commercial/bms_llm_agent.py#608-650), `runtime`, `points` | Returns real-time state of a machine. |
| [list_equipment](file:///e:/Automation/agent_commercial/tools/handlers/equipment.py#48-75) | `count`, `equipment[]` | Paginated list with filters (type, floor). |
| [get_equipment_health](file:///e:/Automation/agent_commercial/tools/handlers/equipment.py#76-97) | `health_score`, `risk_factors[]`, `rul_days` | ML-driven health assessment. |
| [get_point_history](file:///e:/Automation/agent_commercial/tools/handlers/equipment.py#98-110) | `point_id`, `timestamps[]`, `values[]` | Time-series data for a sensor. |
| [get_equipment_specs](file:///e:/Automation/agent_commercial/tools/handlers/equipment.py#111-133) | `specs{}`, `manual_urls[]`, `rag_context` | Tech specs retrieved via GraphRAG. |
| [get_dashboard_overview](file:///e:/Automation/agent_commercial/tools/handlers/equipment.py#134-140) | `total_assets`, `critical_failures`, `efficiency` | Fleet-level summary. |

### 1.2 Energy & Sustainability Tools
| Tool Name | Key Fields | Description |
| :--- | :--- | :--- |
| [analyze_energy](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#30-35) | `total_kwh`, `peak_load`, `efficiency_index` | Building-wide energy summary. |
| [get_energy_anomalies](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#36-45) | `count`, `patterns[]` | Detected waste patterns (e.g., peak shift). |
| [check_cost_impact](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#46-55) | `qar_delta`, `kwh_delta`, `is_savings` | Financial impact of setpoint changes. |
| [get_burn_rate](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#56-62) | `qar_per_hour`, `projected_daily_cost` | Live building cost calculation. |
| [find_ghost_spaces](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#63-147) | `ghost_operations[]`, `daily_waste_qar` | Detects cooling in empty rooms. |
| [estimate_zone_occupancy](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#148-158) | `zone_id`, `probability`, [estimate](file:///e:/Automation/agent_commercial/tools/handlers/energy.py#148-158) | Virtual sensor occupancy detection. |

### 1.3 Alarm & Safety Tools
| Tool Name | Key Fields | Description |
| :--- | :--- | :--- |
| [get_active_alarms](file:///e:/Automation/agent_commercial/tools/handlers/alarms.py#29-48) | `count`, `alarms[]` | Returns prioritized alarm queue. |
| [explain_alarm](file:///e:/Automation/agent_commercial/tools/handlers/alarms.py#49-78) | `root_cause_id`, `causal_chain`, `high_fidelity_explanation` | Bayesian root cause analysis. |
| [acknowledge_alarm](file:///e:/Automation/agent_commercial/tools/handlers/alarms.py#79-87) | `success`, `alarm_id` | Marks an alarm as seen by the operator. |
| [analyze_cascade](file:///e:/Automation/agent_commercial/tools/handlers/alarms.py#88-107) | `root_cause_alarm`, `cascade_tree[]` | Groups related alarms into one incident. |

### 1.4 Predictive Maintenance Tools
| Tool Name | Key Fields | Description |
| :--- | :--- | :--- |
| `predict_maintenance` | `insights[]` | Array of equipment needing attention. |
| `predict_remaining_life` | `health_score`, `days_to_failure` | Regression-based life expectancy. |
| `verify_maintenance_work` | `verification_status`, `reason`, `measured_diff` | Detects "Ghost Maintenance". |

---

## 2. Sub-Agent Communication Protocol

The ARVIS Swarm uses a hierarchical tiered topology.

### 2.1 SwarmNode Response (`SwarmNode.process`)
Every sub-agent (e.g., `Energy_Agent`) returns this internal structure to the [QueenCoordinator](file:///e:/Automation/arvis_core/swarm/queen.py#18-321):
```json
{
  "response": {
    "role": "assistant",
    "content": "Narrative response or proposal text...",
    "tool_calls": []
  },
  "history": [
    {
      "role": "user",
      "content": "..."
    },
    {
      "role": "tool",
      "name": "get_burn_rate",
      "content": "{\"qar_per_hour\": 450.5}"
    }
  ]
}
```

### 2.2 Consensus Debate JSON (`ConsensusEngine`)
When an actionable change is proposed (e.g., "Reduce power in Zone A"), the swarm enters a debate:
```json
{
  "status": "APPROVED | REJECTED",
  "votes": [
    {
      "agent_name": "Safety_Agent",
      "vote": "YES | VETO",
      "reasoning": "Thermal comfort thresholds maintained.",
      "tool_observations": {
        "Comfort_Agent_get_equipment_status": "..."
      }
    }
  ]
}
```

### 2.3 Final Advisory JSON (Queen Synthesis)
This is the **"Gold Standard"** output pushed to the Frontend Dashboard:
```json
{
  "analysis": "Consensus reached: 11 agents approved, 1 abstained.",
  "advisories": [
    {
      "id": "auto-102",
      "type": "energy_waste",
      "severity": "high",
      "message": "[VIP_OVERRIDE_DETECTED] Chiller 2 is surging due to manual override...",
      "confidence": 0.95,
      "evidence": [
        {"source": "Energy_Agent", "finding": "Burn rate 22% above baseline."}
      ],
      "impact": {
        "timeframe": "24h",
        "energy_kwh": 450.0,
        "cost_qar": 22.5,
        "is_savings": true
      },
      "recommended_action": {"type": "auto_reset_setpoint"},
      "counterfactual_check": true
    }
  ]
}
```

---

## 3. SSE Stream Payloads (`/api/v1/stream/thoughts`)

The UI listens for these event types to show the AI's "brain":

| Event | Type | Payload Schema |
| :--- | :--- | :--- |
| `think` | Thought | `{"thought": "I need to check the chiller efficiency..."}` |
| [task](file:///e:/Automation/agent_commercial/bms_llm_agent.py#608-650) | Progress | `{"task": "Mapping alarm cascade to AHUs", "status": "active"}` |
| `tool_use` | Execution | `{"tool": "analyze_cascade", "args": {"alarm_ids": ["ALM-1"]}}` |
| [advisory](file:///e:/Automation/agent_commercial/bms_llm_agent.py#679-690) | Final | The **Final Advisory JSON** (see section 2.3). |
