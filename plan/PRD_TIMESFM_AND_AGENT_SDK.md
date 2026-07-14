# PRD — TimesFM Foundation Model + Claude Agent SDK Pattern Adoption

**Status:** Implementation brief for engineer onboarding
**Audience:** New engineer joining the ARVIS team with no prior context
**Scope:** Two parallel adoption efforts — (1) integrate TimesFM time-series foundation model, (2) adopt three architectural patterns from the Claude Agent SDK
**Prerequisites:** Python 3.10+, AWS Bedrock access, familiarity with async Python and basic ML concepts

---

## 0. Read This First — Orientation

### What ARVIS is

ARVIS is an agentic AI advisory system for commercial building HVAC plants. It runs alongside a building's Building Management System (BMS), typically Siemens Desigo CC. The BMS controls equipment; ARVIS reads telemetry and produces operational advisories for the human facility manager. ARVIS does not write to the BMS — every recommendation is read-only and the operator decides whether to act.

Concretely: ARVIS reads sensor data via BACnet/Modbus (temperatures, pressures, energy consumption, equipment status) and answers operator questions like "why is AHU-07 underperforming?" or "what's the most efficient way to handle the afternoon peak load?" Answers are evidence-grounded — every claim traces to a tool call result, a model prediction, or a knowledge-base entry.

The system is targeted for deployment in commercial office towers in Qatar, aligned with Qatar GORD (Gulf Organisation for Research & Development) green building certification.

### Architecture summary

The system runs as a multi-agent swarm:

- A **Queen coordinator** receives operator queries, classifies risk tier (T1 lookup / T2 diagnostic / T3 actionable), and routes to specialized **swarm nodes** (Energy_Agent, Alarm_Agent, Comfort_Agent, Maintenance_Agent, Strategic_Agent, Memory_Agent, etc.)
- Each swarm node runs a **ReAct-style reasoning loop** with its own tool subset
- For high-risk (T3) actionable proposals, nodes participate in **Byzantine Fault-Tolerant consensus** — proposer presents, opposing-priority nodes vote APPROVE / APPROVE_WITH_CONDITION / VETO with confidence
- A **synthesis pass** combines node proposals into a final `ChatResponse` with evidence IDs
- Multiple **verification gates** run before delivery: evidence faithfulness, physics plausibility, claim verification against ledger, abstention if data coverage insufficient
- Every investigation is **archived** as an `InvestigationPlan` with full audit trail (tasks, evidence, tool calls, vote outcomes) — replayable

### Key code locations

| Path | Purpose |
|---|---|
| `agent_commercial/main.py` | `OpsCopilot` orchestrator entry point |
| `agent_commercial/bms_llm_agent.py` | Top-level chat interface; routes to Queen |
| `arvis_core/swarm/queen.py` | Queen coordinator, BFT consensus orchestration, verification gates |
| `arvis_core/swarm/node.py` | `SwarmNode` class — per-agent ReAct loop |
| `arvis_core/swarm/consensus.py` | BFT voting engine, graded votes |
| `arvis_core/plan.py` | `InvestigationPlan` data structure |
| `arvis_core/evidence.py` | `Evidence` + `EvidenceLedger` |
| `arvis_core/memory/` | Memory orchestrator + adapters (T1 working, T2 episodic, T5 institutional, etc.) |
| `agent_commercial/tools/definitions/` | Tool schemas (55 tools across 8 categories) |
| `agent_commercial/tools/handlers/` | Tool implementations (mixin pattern) |
| `agent_commercial/ml/` | ML modules (energy forecasting, fault detection, RUL prediction) |
| `agent_commercial/verifiers/physics.py` | Physics verifier (regen-or-abstain pipeline) |
| `agent_commercial/verifiers/simulator/` | Thermodynamic simulator for advisory validation |
| `scratch/marina_*.py` | End-to-end test suite simulating a Doha office tower |

### Critical existing concepts

- **`ChatResponse`** — Structured response from ARVIS. Fields include `text`, `confidence`, `truth_score`, `data_coverage`, `evidence_ids`, `_tool_calls`, `_tool_results`. Defined in `agent_commercial/bms_llm_agent.py:52`.
- **`Evidence`** — Single piece of grounded data. Has `id`, `source_tool`, `raw_payload`, `timestamp`, `freshness`, `is_ml_fallback` flag, `_ml_lineage` metadata. Defined in `arvis_core/evidence.py`.
- **`InvestigationPlan`** — Per-investigation root object. Holds `tasks`, `evidence` (ledger), `audit_trail`, `budget`, `status`. Defined in `arvis_core/plan.py`.
- **`MemoryOrchestrator`** — Single façade for 7-tier memory. Defined in `arvis_core/memory/orchestrator.py`.
- **Risk tiers** — T1 = single value lookup, T2 = diagnostic/trend/why query, T3 = actionable proposal requiring consensus.
- **Abstention gate** — Multi-signal gate that triggers structured "Insufficient data" output. Defined in `bms_llm_agent.py:1152-1180`. Signals: `data_coverage`, `truth_score`, `ml_fallback_ratio`, `max_drift`.

### Runtime stack

- Python 3.10+, asyncio throughout
- AWS Bedrock for LLM (Claude Sonnet 4.6 for synthesis, Nova Lite for cheap classify/depth-plan tasks, Kimi K2 for tool calls)
- SQLite for ARVIS internal DBs (investigation_plans, evidence_ledger, building_skills, distilled_rules, conversation_history)
- ChromaDB for vector memory (knowledge base, operator patterns)
- BACnet/Modbus adapters for live BMS integration (simulator mode for testing)
- pytest for testing

### How to run tests

```bash
# Smoke
pytest tests/test_simulator/ --no-header --noconftest -v

# Marina E2E (requires AWS credentials)
export BEDROCK_API_KEY=<your-key>
export AWS_BEDROCK_REGION=us-west-2
python scratch/marina_prove_it.py --scenario S1 --phase S1_P2
```

---

# Part 1 — TimesFM Adoption

## 1.1 Problem Statement

ARVIS currently uses multiple bespoke time-series models for forecasting, anomaly detection, and drift detection. These models have three production-breaking limitations:

1. **Per-building cold start** — Models require 14 days of meter history before producing useful forecasts. Every new deployment has a 2-week silent period.
2. **Per-asset maintenance overhead** — Separate trained models per building per equipment class. Drift retraining and version management is manual.
3. **No native uncertainty bands** — Outputs are point estimates with ad-hoc confidence values. The downstream evidence ledger, abstention gate, and faithfulness verifier all need calibrated probability bands but currently estimate them.

The strategic problem: ARVIS deployment time per building is bounded by the slowest ML model's warmup period. As ARVIS scales to multiple buildings, the per-asset ML overhead becomes a deployment bottleneck.

## 1.2 Current State

| Module | LOC | Purpose | Status |
|---|---|---|---|
| `agent_commercial/ml/energy_forecaster.py` | 725 | Prophet + LightGBM ensemble for energy demand forecasting | Wired, slow cold start |
| `agent_commercial/ml/fdd_autoencoder.py` | 790 | Variational autoencoder for fault detection | Silently degraded (TensorFlow not in requirements; falls back to ASHRAE rules) |
| `agent_commercial/ml/predictive_maintenance.py` | 1119 | XGBoost + Isolation Forest + Weibull for remaining useful life | Wired |
| `agent_cognitive/prediction_engine.py` | 799 | Drift detection, baseline establishment | Wired |
| `agent_commercial/ml/causal_inference.py` | 646 | Bayesian network (pgmpy) for fault root cause | Stub fallback if pgmpy missing |

## 1.3 What TimesFM Is

TimesFM is Google Research's open-source time-series foundation model.

- Decoder-only transformer architecture
- 200M parameters (model version 2.5)
- Pretrained on diverse time-series corpora; works zero-shot on any univariate series
- Accepts up to 16,384 context points; forecasts up to 1,024 horizon steps
- Outputs point forecast + 10 quantile bands (calibrated prediction intervals)
- Supports exogenous covariates via XReg extension
- Apache-2.0 license, self-hostable via HuggingFace
- Approximately 1 GB GPU VRAM or 1.5 GB CPU RAM

Source: `https://github.com/google-research/timesfm`

Critical for ARVIS: zero-shot operation eliminates the cold-start problem. Single model handles all buildings and all equipment classes without per-asset training. Quantile output provides calibrated uncertainty bands natively.

## 1.4 Target Architecture

### 1.4.1 TimesFM Service Layer

Create a single TimesFM service shared by all consumers:

```
agent_commercial/ml/timesfm_service.py
```

The service exposes:

```python
class TimesFMService:
    def __init__(self, model_path: str, device: str = "auto"): ...
    
    async def forecast(
        self,
        series: list[float],
        horizon: int,
        covariates: dict[str, list[float]] | None = None,
        return_quantiles: bool = True,
    ) -> ForecastResult: ...
    
    async def forecast_batch(
        self,
        series_dict: dict[str, list[float]],
        horizon: int,
        shared_covariates: dict[str, list[float]] | None = None,
    ) -> dict[str, ForecastResult]: ...

@dataclass
class ForecastResult:
    point_forecast: list[float]
    quantile_bands: dict[str, list[float]]  # "q10", "q25", "q50", "q75", "q90"
    model_id: str
    model_version: str
    context_length_used: int
    inference_time_ms: float
    covariates_used: list[str]
```

### 1.4.2 Consumer Integration Points

| Consumer | Change |
|---|---|
| `EnergyForecaster.forecast_energy()` | Replace Prophet+LightGBM internals with `TimesFMService.forecast()`. Keep external API identical. |
| `PredictionEngine.drift_score()` | Compute drift as `(observed - q50_forecast) / (q90_forecast - q10_forecast)`. Replaces 14-day baseline learning. |
| `Abstention gate` | Add signal: if observed value falls outside forecast q10-q90 band on critical points, increase ml_fallback_ratio. |
| `PhysicsVerifier` | Add check: if advisory cites a future value (e.g., "load will peak at 1200kW"), validate against TimesFM forecast band. |
| `PredictiveMaintenance.predict_remaining_life()` | Forecast vibration/COP trajectory with TimesFM, classify failure probability with existing XGBoost over the forecast tail. |

### 1.4.3 Tool Definition Updates

Update `agent_commercial/tools/definitions/ml.py`. The `forecast_energy` tool gets enriched response schema:

```python
"response_schema": {
    "type": "object",
    "properties": {
        "forecast": {"type": "array", "items": {"type": "number"}},
        "quantiles": {
            "type": "object",
            "properties": {
                "q10": {"type": "array"},
                "q25": {"type": "array"},
                "q50": {"type": "array"},
                "q75": {"type": "array"},
                "q90": {"type": "array"},
            },
        },
        "horizon_hours": {"type": "integer"},
        "_ml_lineage": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "model_version": {"type": "string"},
                "context_length_used": {"type": "integer"},
                "covariates_used": {"type": "array", "items": {"type": "string"}},
                "inference_time_ms": {"type": "number"},
            },
        },
    },
}
```

### 1.4.4 XReg Covariate Strategy

XReg lets a single TimesFM model produce per-building behaviour by feeding exogenous covariates. Define per-building covariate sets:

| Covariate type | Examples for Qatar deployment |
|---|---|
| Static | building_type, climate_zone, GORD_rating, building_age |
| Dynamic temporal | hour_of_day, day_of_week, ramadan_flag, friday_flag, holiday_flag |
| Dynamic environmental | OAT, humidity, solar_irradiance, wind_speed, sandstorm_flag |
| Dynamic operational | tariff_peak_flag, occupancy_pct, HVAC_mode |

Per-building covariate configuration lives in the existing building-profile YAML (per the building-onboarding framework). Same TimesFM model + different covariates = different forecasts per building, no retraining.

### 1.4.5 Deployment Topology

Two options. Pick one per environment.

**Option A — Self-hosted SageMaker endpoint (recommended for production)**

- Single shared endpoint across all ARVIS customer deployments
- AWS-native, low latency to Bedrock (same region)
- GPU instance (g4dn.xlarge or equivalent), approximately $0.50-1/hr
- Cost amortizes across the customer portfolio

**Option B — Local CPU inference (recommended for development and pilot)**

- Run on the ARVIS host
- No additional infrastructure
- Inference latency 3-5 seconds (vs sub-second on GPU)
- Acceptable for development and small pilots

**Option C — Vertex AI managed endpoint (not recommended)**

- Adds cross-cloud calls and GCP dependency
- Higher latency
- Avoid unless customer specifically requires GCP-hosted

## 1.5 Detailed Work Breakdown

### Workstream T1 — Spike validation

Validate TimesFM forecast accuracy on Marina-generated synthetic load data against the current EnergyForecaster ensemble. Compare on:

- Mean Absolute Percentage Error (MAPE)
- Quantile band calibration (does observed land inside q10-q90 90% of the time?)
- Inference latency at p50 and p95
- Memory footprint (CPU and GPU paths)

Deliverable: a short benchmark report. Decision gate: if TimesFM is within 110% of EnergyForecaster MAPE, proceed. If worse, hybrid plan (TimesFM for new buildings, ensemble for tuned ones).

### Workstream T2 — Service layer construction

Build `TimesFMService`. Key design constraints:

- Single instantiation per process (lazy load, cache model)
- Thread-safe async API
- Graceful fallback if model fails to load (returns structured `ML_UNAVAILABLE` sentinel matching existing pattern in `agent_commercial/tools/handlers/ml.py`)
- Telemetry hooks emit inference latency, context length, cache hit rate
- Per-call timeout enforcement (default 10 seconds)
- Battery of unit tests covering: simple forecast, batched forecast, with covariates, model unavailable, timeout exceeded, empty series, NaN handling

### Workstream T3 — EnergyForecaster replacement

Refactor `agent_commercial/ml/energy_forecaster.py`. Behaviour requirements:

- External API stays identical (`forecast_energy(hours, building_id, include_confidence)`)
- Internals call `TimesFMService.forecast()`
- Quantile bands populate the existing `confidence_lower` and `confidence_upper` fields, plus new `quantiles` dict
- Per-building XReg covariates loaded from building-profile YAML (use `q10` as lower bound, `q90` as upper bound for backward compatibility)
- All existing callers continue working without code change
- When TimesFM unavailable, falls back to current ensemble (do not delete ensemble code in Phase 1)
- Telemetry tags each forecast with backend used (timesfm or ensemble)

### Workstream T4 — Drift detection wire-up

Refactor `agent_cognitive/prediction_engine.py` drift detection:

- Replace baseline learning with TimesFM forecast at observation time
- Drift score = `|observed - q50| / max(q90 - q10, epsilon)`
- Drift > 1.0 means observed value outside the 80% prediction interval
- Plumb drift signal through to abstention gate via existing `Evidence.drift_score` field
- Remove 14-day baseline learning code (after one release of overlap to confirm no regressions)

### Workstream T5 — Predictive maintenance hybrid

Refactor `agent_commercial/ml/predictive_maintenance.py`:

- For each tracked equipment (vibration, COP, runtime), TimesFM forecasts the next 30-90 days of trajectory
- Existing XGBoost classifier consumes the forecast tail and emits failure probability
- RUL output: integer days to predicted threshold breach + confidence interval from quantile bands
- Weibull survival model stays for historical aggregate statistics

### Workstream T6 — XReg per-building covariates

Extend the building profile YAML schema (in `agent_commercial/verifiers/simulator/data/`) with a `covariates` section:

```yaml
covariates:
  static:
    building_type: "office_tower"
    climate_zone: "0B"
    gord_rating: "4_star"
  dynamic_temporal:
    enabled: ["hour_of_day", "day_of_week", "ramadan_flag", "friday_flag"]
  dynamic_environmental:
    enabled: ["oat", "humidity", "solar_irradiance"]
    sources:
      oat: "WEATHER/OAT"  # BACnet point ID
      humidity: "WEATHER/RH"
  dynamic_operational:
    enabled: ["tariff_peak_flag", "occupancy_pct"]
    sources:
      tariff_peak_flag: "computed.kahramaa_peak"
      occupancy_pct: "FLR/OCC_PCT_AVG"
```

The TimesFM service reads this config and pulls the corresponding points at forecast time. New buildings get a covariate config as part of onboarding.

### Workstream T7 — SageMaker deployment

Package TimesFM as a SageMaker endpoint:

- Custom Docker image with TimesFM 2.5 weights baked in
- HTTP endpoint exposing `/forecast` and `/batch_forecast`
- Auto-scaling configuration (start with 1 instance, scale to 3 at load)
- Health check endpoint
- CloudWatch metrics for latency, throughput, errors
- Per-customer authentication via API key (header)

`TimesFMService` gets a `RemoteTimesFMService` subclass for SageMaker, `LocalTimesFMService` for in-process.

## 1.6 Data Contracts

### 1.6.1 Service input contract

```python
@dataclass
class ForecastRequest:
    series_id: str                     # for telemetry and cache key
    values: list[float]                # historical observations, oldest first
    horizon: int                       # forecast steps
    frequency: str = "hourly"          # "5min", "hourly", "daily"
    covariates: dict[str, list[float]] | None = None
    quantile_levels: list[float] = (0.1, 0.25, 0.5, 0.75, 0.9)
    max_context: int = 1024            # cap context for latency
```

### 1.6.2 Service output contract

```python
@dataclass
class ForecastResponse:
    point_forecast: list[float]
    quantile_forecast: dict[str, list[float]]  # keyed by quantile string
    series_id: str
    inference_time_ms: float
    context_used: int
    lineage: ModelLineage

@dataclass
class ModelLineage:
    model_id: str = "timesfm-2.5-200m"
    model_version: str = "2.5.0"
    backend: str = "local"             # "local" | "sagemaker" | "vertex"
    weights_hash: str                  # SHA256 of loaded weights, for replay
    covariates_used: list[str]
    timestamp: datetime
```

### 1.6.3 Evidence Ledger contract

Existing `Evidence` schema already supports `_ml_lineage`. ML forecast results populate it:

```python
Evidence(
    id="ev_8a3f...",
    source_tool="forecast_energy",
    raw_payload={
        "forecast": [...],
        "quantiles": {...},
        "_ml_lineage": ModelLineage(...).to_dict(),
    },
    is_ml_fallback=False,
    drift_score=None,                  # filled when consumed by prediction_engine
)
```

### 1.6.4 Abstention gate contract

New signal flows into abstention computation. In `bms_llm_agent.py:_compute_abstention_signals()`, add:

```python
quantile_violations = sum(
    1 for ev in evidence_ledger.get_all()
    if ev.source_tool in TRACKED_FORECAST_TOOLS
    and ev.raw_payload.get("observed_value") is not None
    and _outside_quantile_band(ev)
)
```

Trigger condition: `quantile_violations / total_critical_evidence > 0.3` → boost abstention probability.

## 1.7 Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TimesFM forecast quality on Qatar BMS data unverified | Medium | High | T1 spike validates before commitment |
| GPU costs exceed budget | Low | Medium | Start with CPU inference; move to GPU only after pilot reveals latency need |
| TimesFM model versions break API | Low | Medium | Pin specific version in requirements; weights hash in lineage |
| XReg covariates require building-specific tuning | Medium | Low | Default covariate set works zero-shot; per-building tuning is enhancement |
| Inference latency unacceptable for interactive queries | Medium | Medium | Cache forecasts within session; pre-compute common horizons hourly |
| Operator distrust of foundation model output | Low | Medium | Quantile bands are interpretable; lineage in evidence trail is auditable |

## 1.8 Acceptance Criteria

The TimesFM adoption is complete when:

1. Every consumer of EnergyForecaster, PredictionEngine drift, and PredictiveMaintenance has been refactored to use TimesFMService
2. `forecast_energy` tool response schema includes `quantiles` and `_ml_lineage` fields, populated on every call
3. The abstention gate consumes the new quantile-violation signal and the change is covered by unit tests
4. A new building configured with only a covariate YAML produces forecasts on Day 1 (zero-shot validation test)
5. SageMaker endpoint deployed and serving traffic; CloudWatch dashboard tracks latency and error rate
6. The ensemble fallback path is exercised in CI (kill the TimesFM service and confirm forecasts still return)
7. Marina E2E test phases that previously required 14 days of warmup history now pass without warmup
8. All forecast outputs land in the evidence ledger with complete lineage

## 1.9 Out of Scope

- Replacing the Bayesian causal inference module (different problem class)
- Replacing fault classification (TimesFM is forecasting, not classification)
- Building a custom training pipeline (zero-shot only in Phase 1; fine-tuning is a separate effort)
- Multi-variate forecasting (TimesFM 2.5 is univariate + XReg covariates)
- Anomaly detection beyond quantile band check (existing FDDAutoencoder is separate work)

---

# Part 2 — Claude Agent SDK Pattern Adoption

## 2.1 Problem Statement

Three architectural smells in current ARVIS code:

### Problem A — Verification logic is scattered across the Queen

`arvis_core/swarm/queen.py` (~780 LOC) mixes orchestration with verification. The `execute_swarm` flow inline-calls GroundingGuard, PhysicsVerifier, faithfulness check, claim verification, read-only enforcement, and the abstention gate. Adding a new verifier (e.g., quantile band check from TimesFM) requires editing `queen.py` and reasoning about flow ordering. Removing a verifier requires careful cherry-picking.

### Problem B — Tools are dict-defined and mixin-implemented

55 tools live as Python dicts in `tools/definitions/` with handlers as mixin methods on `BMSToolHandler` in `tools/handlers/`. Adding a tool requires editing both files and understanding the mixin pattern. There is no introspection of "what tools exist?" outside the registry pattern that itself isn't used. External tools (customer-specific integrations, judge verification tools for the Marina test framework) have no clean integration path.

### Problem C — Read-only enforcement is regex post-processing

ARVIS is meant to be read-only — never writes to the BMS. Today this is enforced by a post-synthesis regex that catches action verbs ("submitted", "applied", "executed") and rewrites them to advisory phrases ("recommend submitting"). This is band-aid. The synthesis LLM still generates the action language and we keep firing read-only-violation warnings (14 per Marina S1 run). Structural prevention would be safer.

## 2.2 What the Claude Agent SDK Offers

Source: `https://github.com/anthropics/claude-agent-sdk-python`

The SDK is built around three patterns that solve exactly these three problems:

1. **Hook system** — Named events (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`) with registered Python functions returning structured decisions. Replaces inline flow control with declarative subscription.

2. **MCP-compatible tools** — Tools defined via `@tool` decorator with typed schemas. In-process MCP servers via `create_sdk_mcp_server`. External MCP servers via subprocess config. Standardized protocol for tool integration.

3. **Permission system** — `allowed_tools` allowlist, `disallowed_tools` blocklist, `permission_mode` (auto-accept, plan-only, prompt-for-decision), `can_use_tool` custom callback. Multi-stage decision pipeline with explicit precedence.

ARVIS cannot drop in the SDK wholesale because the SDK is built on the Claude Code CLI which depends on Anthropic API. ARVIS uses Bedrock. But the three patterns are portable and high-value.

## 2.3 Pattern A Target — Hook System

### 2.3.1 Architecture

Create `arvis_core/hooks/` package:

```
arvis_core/hooks/
├── __init__.py
├── registry.py         # HookRegistry class
├── events.py           # HookEvent enum + payload schemas
├── results.py          # HookResult contract
└── decorators.py       # @on_event registration sugar
```

### 2.3.2 HookEvent enum

```python
class HookEvent(Enum):
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_NODE_RUN = "pre_node_run"
    POST_NODE_RUN = "post_node_run"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_SYNTHESIS = "pre_synthesis"
    POST_SYNTHESIS = "post_synthesis"
    PRE_DELIVERY = "pre_delivery"
    POST_DELIVERY = "post_delivery"
```

### 2.3.3 HookResult contract

Every hook returns a `HookResult`:

```python
@dataclass
class HookResult:
    decision: Literal["continue", "modify", "deny", "abstain"]
    reason: str
    modified_payload: dict | None = None        # if decision == "modify"
    abstention_message: str | None = None       # if decision == "abstain"
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 2.3.4 Hook registration

Hooks register at startup. Each hook declares the event it subscribes to and optionally a matcher (e.g., only this tool name, only this risk tier):

```python
@on_event(HookEvent.POST_TOOL_CALL)
async def grounding_guard_post_tool(payload: PostToolCallPayload) -> HookResult:
    """Register tool result in GroundingGuard's evidence index."""
    GroundingGuard.register_tool_result(
        tool_name=payload.tool_name,
        result=payload.result,
    )
    return HookResult(decision="continue", reason="evidence_indexed")


@on_event(HookEvent.POST_SYNTHESIS, matcher=lambda p: p.risk_tier == "T3")
async def physics_verifier_post_synthesis(payload: PostSynthesisPayload) -> HookResult:
    """Block T3 advisories that violate physics."""
    verifier = PhysicsVerifier(payload.building_id)
    result = verifier.verify_advisory_text(payload.synthesis_text)
    if not result.passed:
        return HookResult(
            decision="modify",
            reason=f"physics_violation: {result.violations}",
            modified_payload={"trigger_regeneration": True, "violations": result.violations},
        )
    return HookResult(decision="continue", reason="physics_ok")
```

### 2.3.5 Refactor target

Every verification currently inline in `queen.py` becomes a registered hook:

| Current location | New hook |
|---|---|
| `queen.py` faithfulness check | `POST_SYNTHESIS` hook |
| `queen.py` physics verifier call | `POST_SYNTHESIS` hook |
| `queen.py` `_enforce_read_only` | `POST_SYNTHESIS` hook |
| `queen.py` claim verification | `POST_SYNTHESIS` hook |
| `queen.py` evidence ledger updates | `POST_TOOL_CALL` hook |
| `bms_llm_agent.py` abstention gate | `PRE_DELIVERY` hook |
| `bms_llm_agent.py` chat history append | `POST_DELIVERY` hook |
| `bms_llm_agent.py` skillbook write | `POST_DELIVERY` hook |
| `tools/handlers/base.py` stale sensor check | `PRE_TOOL_CALL` hook |
| `node.py` distilled rules load | `PRE_NODE_RUN` hook |

`queen.py` shrinks from ~780 LOC to approximately 400 LOC. Each verifier becomes a self-contained module that registers its own hooks.

### 2.3.6 Acceptance criteria

- `arvis_core/hooks/` package exists with registry, events, results, decorators
- All eight verification points listed above are converted to hooks
- `queen.py` no longer references PhysicsVerifier, GroundingGuard, faithfulness check, claim verification, or read-only enforcement directly
- Adding a new verifier (e.g., quantile band check from Part 1) requires only creating a new module and registering hooks; no `queen.py` changes
- Hook execution order is deterministic and documented
- Hook failures are isolated (one hook crash does not break the chain)
- Hook execution is observable via telemetry (event, hook name, decision, duration)
- All existing Marina test phases continue to pass

## 2.4 Pattern B Target — MCP-Compatible Tools

### 2.4.1 Architecture

Three new components:

```
arvis_core/mcp/
├── __init__.py
├── server.py           # SDK MCP server for ARVIS internal tools
├── decorators.py       # @arvis_tool decorator
└── adapters.py         # Convert existing tool defs to MCP schema
```

### 2.4.2 Tool definition pattern

Existing tool definitions migrate to a decorator-based pattern:

```python
@arvis_tool(
    name="get_equipment_status",
    description="Get current status of a piece of equipment by ID",
    input_schema={"equipment_id": {"type": "string", "required": True}},
    cost_class="cheap",
    requires=["bms_state_engine"],
)
async def get_equipment_status(args: dict, ctx: ToolContext) -> dict:
    equipment_id = args["equipment_id"]
    equipment = await ctx.bms_state.get_equipment(equipment_id)
    return equipment.to_dict()
```

The decorator handles registration, schema validation, cost class tagging, dependency declaration. Eliminates the dict-defined + mixin-implemented split.

### 2.4.3 MCP server creation

ARVIS exposes its toolset as an in-process MCP server. Two servers:

| Server | Tools | Consumers |
|---|---|---|
| `arvis-ops` | 55 operational tools (equipment, alarms, energy, GSAS, etc.) | Swarm nodes |
| `arvis-judge` | 14 verification tools (skillbook delta, plan introspection, etc.) | Agentic judge (for Marina test suite) |

```python
ops_server = create_arvis_mcp_server(
    name="arvis-ops",
    version="1.0.0",
    tools=load_tools_by_module("agent_commercial.tools.operational"),
)

judge_server = create_arvis_mcp_server(
    name="arvis-judge",
    version="1.0.0",
    tools=load_tools_by_module("agent_commercial.tools.verification"),
)
```

### 2.4.4 External MCP server support

Customer-specific integrations enter as external MCP servers:

```python
# Customer config
external_mcp_servers = {
    "customer_cmms": {
        "type": "stdio",
        "command": "/opt/customer-tools/cmms-mcp-server",
        "env": {"CMMS_API_KEY": "..."},
    },
    "kahramaa_tariff": {
        "type": "http",
        "url": "https://internal.example.com/kahramaa-mcp",
        "headers": {"Authorization": "Bearer ..."},
    },
}
```

ARVIS swarm nodes consume external tools the same way they consume internal ones — through the MCP protocol abstraction.

### 2.4.5 Migration approach

Phased migration to keep existing code working throughout:

1. Build decorator infrastructure
2. Migrate one tool category (Equipment) as proof
3. Verify Marina tests pass with mixed pattern (some decorated, some legacy)
4. Migrate remaining categories
5. Remove the legacy mixin pattern

### 2.4.6 Acceptance criteria

- `arvis_core/mcp/` package implements decorator, server, adapter
- All 55 operational tools migrated to `@arvis_tool` decorator
- `arvis-ops` and `arvis-judge` MCP servers ship as importable in-process servers
- External MCP server support documented and tested with at least one mock external server
- Legacy mixin pattern in `BMSToolHandler` removed
- Tool registration is introspectable: `arvis_tools_list()` returns the full inventory
- Schema validation runs on every tool call (input and output)
- Marina tests continue to pass with no functional regression

## 2.5 Pattern C Target — Permission System

### 2.5.1 Architecture

Per-node, per-tier permission policy. Replace verb-substitution post-processing with structural tool denial.

```python
@dataclass
class PermissionPolicy:
    allowed_tools: list[str] | None = None       # if None, all not in disallowed
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: PermissionMode = PermissionMode.READ_ONLY
    can_use_tool: Callable[[ToolCallContext], PermissionDecision] | None = None

class PermissionMode(Enum):
    READ_ONLY = "read_only"                     # only tools tagged read_only
    READ_WRITE_WITH_APPROVAL = "rw_with_approval"
    DRY_RUN = "dry_run"                         # simulate, never execute writes
    PLAN = "plan"                               # surface intent, no execution
```

### 2.5.2 Tool capability tagging

Every tool gets a `capabilities` tag in its decorator:

```python
@arvis_tool(
    name="get_equipment_status",
    capabilities=["read"],          # read-only
    ...
)

@arvis_tool(
    name="emergency_shutdown",
    capabilities=["write", "safety"],
    ...
)
```

### 2.5.3 ARVIS default policy

```python
ARVIS_DEFAULT_POLICY = PermissionPolicy(
    disallowed_tools=["*"],                       # deny everything by default
    allowed_tools=ALL_READ_TOOLS,                 # explicitly allow read tools
    permission_mode=PermissionMode.READ_ONLY,
    can_use_tool=enforce_read_only_capability,
)
```

Write tools are not denied by name — they are denied by capability tag. The synthesis LLM cannot request a write tool because no write tool is registered with the active node's policy. Removes the entire class of read-only-violation events.

### 2.5.4 Per-tier policies

| Risk tier | Permission policy |
|---|---|
| T1 lookup | Read-only operational tools (status, list, history) |
| T2 diagnostic | T1 tools + ML forecasts + analytics |
| T3 actionable | T2 tools + simulation tools + planning tools (still no write) |

### 2.5.5 Migration approach

Maintain backward compatibility:

1. Add `capabilities` tag to all 55 tools (in conjunction with Pattern B migration)
2. Implement `PermissionPolicy` and `PermissionMode` types
3. Wire `enforce_read_only_capability` into the tool dispatcher
4. Keep the legacy verb-substitution as a belt-and-suspenders second layer for one release
5. Remove verb-substitution after one release of zero read-only violation events

### 2.5.6 Acceptance criteria

- All 55 tools have `capabilities` tags
- `PermissionPolicy` and `PermissionMode` types exist with full documentation
- Per-tier policies defined and applied automatically by the risk tier classifier
- Tool dispatcher rejects tool calls violating active policy with structured error envelope (same shape as existing `ML_UNAVAILABLE` sentinel)
- Read-only enforcement runs at registration time, not post-synthesis
- Legacy regex-based verb-substitution removed after one release of clean operation
- Marina test suite shows zero read-only violation warnings after migration

## 2.6 Patterns That Are Out of Scope

The SDK provides several features ARVIS should not adopt:

- **`query()` simple iterator** — ARVIS returns structured `ChatResponse`, cannot downgrade
- **Claude Code CLI bundled binary** — ARVIS runs on Bedrock, no CLI compatibility
- **`permission_mode='acceptEdits'`** — ARVIS is read-only by construction
- **Built-in Bash/Read/Write/Edit tools** — domain wrong; ARVIS doesn't shell out or edit files
- **Slash commands** — ARVIS isn't operator's primary CLI
- **Session forking** — InvestigationPlan archive provides equivalent functionality

---

# Part 3 — Cross-Cutting Concerns

## 3.1 Interaction Between the Two Efforts

The two efforts overlap at one important point: TimesFM forecast outputs become new evidence types, which means new hooks consume them.

After both adoptions:

```
Tool call (forecast_energy via @arvis_tool decorator)
   ↓
PRE_TOOL_CALL hook: budget check, stale sensor guard
   ↓
TimesFMService produces forecast + quantile bands + ML lineage
   ↓
POST_TOOL_CALL hook: GroundingGuard registers result, EvidenceLedger writes typed Evidence row
   ↓
Synthesis composes advisory citing forecast values
   ↓
POST_SYNTHESIS hooks (parallel):
   - Faithfulness check: cited values within quantile bands?
   - Physics verifier: forecast plausible against thermodynamic model?
   - Read-only enforcement: no action verbs in advisory?
   - Quantile band check: NEW — observed values inside forecast q10-q90?
   ↓
If any hook returns decision="modify" with trigger_regeneration → regenerate
If any hook returns decision="abstain" → emit structured abstention
   ↓
PRE_DELIVERY hook: final abstention gate (multi-signal fusion)
   ↓
Deliver to operator
   ↓
POST_DELIVERY hook: skillbook write, plan archive
```

This integration is clean because TimesFM only appears in tool implementations and one new hook. The hook system makes adding the quantile band check a single-file change.

## 3.2 Combined Definition of Done

Both adoptions are complete when:

1. All Part 1 and Part 2 acceptance criteria are met
2. The combined system passes the Marina S1 and S2 test scenarios with no regressions
3. The integration scenario described in 3.1 is exercised by an end-to-end test
4. Performance benchmarks show no per-query latency regression beyond 10% vs the pre-adoption baseline
5. Operator documentation is updated to describe the new tool registration model and hook system
6. Engineering documentation is updated with the patterns and migration guides
7. The codebase has fewer total lines of code than before (specifically: `queen.py` smaller, ML modules collectively smaller after Prophet/LightGBM removal)
8. Patent claim coverage is preserved — the BFT consensus, abstention gate, and physics verification mechanisms continue to work as patented

## 3.3 Validation Against Marina

Marina is the existing end-to-end test simulating an office tower in Doha. It must serve as the integration test for both adoptions:

| Marina phase | What it validates after adoption |
|---|---|
| S1-P1 (silent observation) | Hooks fire correctly, abstention gate works |
| S1-P2 (AHU-7 cascade) | All verification hooks fire on T3 actionable; structural read-only enforcement |
| S1-P4 (COP drift over 4 months) | TimesFM zero-shot detects drift without 14-day baseline |
| S1-P6 (chiller bearing trajectory) | TimesFM forecasts trajectory; XGBoost classifies; RUL produces calibrated CI |
| S1-P7 (humidity pattern recall) | MCP tool registration enables skillbook tool to surface Ahmed's pattern |
| S2-P0 (bad data quality) | Abstention gate combines coverage, drift, ML fallback, quantile violations |
| S2-P5 (benign vibration) | Quantile band check distinguishes normal variation from drift |

A Marina run after adoption that matches or exceeds the pre-adoption pass rate is the canonical proof of done.

---

# Appendix A — Glossary

| Term | Definition |
|---|---|
| ARVIS | The advisory AI system being built |
| BACnet | Industry-standard building automation network protocol (point-based) |
| BMS | Building Management System (e.g., Siemens Desigo CC) |
| BFT | Byzantine Fault-Tolerant; consensus protocol class |
| ChatResponse | ARVIS's structured response object |
| EvidenceLedger | Per-investigation typed evidence store |
| GORD | Gulf Organisation for Research & Development (Qatar's green building certifying body) |
| GSAS | Global Sustainability Assessment System (Qatar's green building standard) |
| InvestigationPlan | ARVIS's externalized plan object with tasks, evidence, audit trail |
| MCP | Model Context Protocol (Anthropic's standardized agent tool protocol) |
| Modbus | Industry-standard serial/IP communication protocol |
| MemoryOrchestrator | ARVIS's 7-tier memory façade |
| Queen | The coordinator that orchestrates the swarm |
| ReAct | Reasoning + Acting; LLM agent loop pattern |
| Skillbook | Per-building institutional knowledge store (Bayesian-updated) |
| SwarmNode | A specialized agent within ARVIS (Energy_Agent, Alarm_Agent, etc.) |
| TimesFM | Google's time-series foundation model (this PRD's adoption target) |
| TMY3 | Typical Meteorological Year, third edition; standard weather dataset format |
| Tool capability | Tag on a tool indicating whether it reads, writes, or has safety implications |
| XReg | TimesFM's exogenous covariate extension |

# Appendix B — Reference Links

| Resource | URL |
|---|---|
| TimesFM repo | `https://github.com/google-research/timesfm` |
| TimesFM paper | `https://arxiv.org/abs/2310.10688` |
| TimesFM HuggingFace | `https://huggingface.co/google/timesfm-2.5-200m-pytorch` |
| Claude Agent SDK | `https://github.com/anthropics/claude-agent-sdk-python` |
| MCP specification | `https://modelcontextprotocol.io` |
| ARVIS internal architecture docs | `README.md`, `swarm_walkthrough.md` |
| AWS Bedrock docs | `https://docs.aws.amazon.com/bedrock/` |

# Appendix C — Test Setup

Local development:

```bash
# Clone repo
git clone <arvis-repo-url>
cd arvis

# Python 3.10+
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-bms.txt
pip install -r requirements-ml.txt
pip install timesfm[torch]                  # for TimesFM

# AWS credentials for Bedrock
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_BEDROCK_REGION=us-west-2

# TimesFM weights (downloaded on first use to ~/.cache/huggingface/)

# Run simulator tests
pytest tests/test_simulator/ --no-header --noconftest -v

# Run Marina E2E (single phase)
python scratch/marina_prove_it.py --scenario S1 --phase S1_P2

# Run full Marina S1
python scratch/marina_prove_it.py --scenario S1
```

# Appendix D — Open Questions for Tech Lead

These need decisions before implementation starts:

1. SageMaker endpoint approach: dedicated per customer, or shared multi-tenant?
2. TimesFM weights pinning policy: fix version, or allow drift with monthly review?
3. Hook execution order: strict declaration order, or topological based on dependencies?
4. External MCP server authentication: API key in header, mTLS, or both?
5. Permission policy file format: in YAML config, or Python module?
6. Backward compatibility window for legacy tools mixin pattern: one release, or two?
7. Telemetry destination: existing observability stack, or new dashboards?

Resolve these in a tech lead review meeting before workstream T2 (TimesFM service construction) and the first hook refactor.

---

*This PRD is self-contained. An engineer with Python experience and basic ML literacy can execute it without further context-gathering from the existing ARVIS team. Pre-implementation review by the tech lead is required to resolve the open questions in Appendix D.*
