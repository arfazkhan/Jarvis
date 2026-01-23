# ARVIS Ops Copilot - Complete Technical Documentation

> **AI-Powered Building Management System Advisor for Qatar Commercial Buildings**
> 
> Version: 1.0 | Last Updated: January 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Core Components](#3-core-components)
4. [Data Models](#4-data-models)
5. [BACnet Integration](#5-bacnet-integration)
6. [Machine Learning Engines](#6-machine-learning-engines)
7. [LLM Agent & Tools](#7-llm-agent--tools)
8. [REST API](#8-rest-api)
9. [Database Persistence](#9-database-persistence)
10. [Titans Learning Loop](#10-titans-learning-loop)
11. [GSAS Compliance](#11-gsas-compliance)
12. [Running the System](#12-running-the-system)
13. [File Structure](#13-file-structure)

---

## 1. Overview

### What is ARVIS Ops Copilot?

ARVIS Ops Copilot is an **AI-powered Building Management System (BMS) advisor** designed specifically for commercial buildings in Qatar. It combines:

- **BACnet/IP protocol** for real-time building data
- **Machine Learning** for predictive maintenance and anomaly detection
- **Large Language Models (LLM)** for natural language interaction
- **GSAS Compliance** automation for Qatar green building certification
- **Titans Learning Loop** for continuous improvement from operator behavior

### Key Differentiators

| Feature | Description |
|---------|-------------|
| 🗣️ **Bilingual AI Chat** | English and Arabic natural language interface |
| 💰 **Cost of Comfort** | Real-time QAR/hour burn rate calculations |
| 👻 **Ghost Detector** | Virtual occupancy sensing without physical sensors |
| ✅ **Maintenance Verification** | Physics-based "did they actually do the work?" checks |
| 📊 **GSAS Automation** | Auto-generate GORD compliance reports |
| 🧠 **Titans Learning** | Learns from operator patterns to improve over time |

### Target Users

1. **Facility Managers (FM)** - Primary users, interact via chat
2. **Building Operators** - Monitor dashboards, acknowledge alarms
3. **Sustainability Officers** - Generate GSAS compliance reports
4. **Maintenance Teams** - Receive work orders, verify completion

---

## 2. Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ARVIS Ops Copilot                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    │
│  │   REST API      │    │   LLM Agent     │    │  Learning       │    │
│  │   (FastAPI)     │◄──►│   (BMSLLMAgent) │◄──►│  Engine         │    │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘    │
│           │                      │                      │              │
│           ▼                      ▼                      ▼              │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                      Tool Handler (18 Tools)                     │  │
│  └────────┬────────────────────┬────────────────────┬──────────────┘  │
│           │                    │                    │                  │
│           ▼                    ▼                    ▼                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐       │
│  │  State Engine   │  │  Alarm Engine   │  │ Energy Analyzer │       │
│  │  (Real-time)    │  │  (Clustering)   │  │ (Anomaly Det.)  │       │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘       │
│           │                    │                    │                  │
│           └────────────────────┼────────────────────┘                  │
│                                │                                       │
│                    ┌───────────┴───────────┐                          │
│                    │   BACnet Adapter      │                          │
│                    │   (Protocol Layer)    │                          │
│                    └───────────┬───────────┘                          │
│                                │                                       │
└────────────────────────────────┼───────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │   Real BACnet Network   │
                    │   or BMS Simulator      │
                    └─────────────────────────┘
```

### Component Layers

| Layer | Components | Purpose |
|-------|------------|---------|
| **Presentation** | REST API, WebSocket | External interface |
| **Intelligence** | LLM Agent, Learning Engine | AI/ML processing |
| **Business Logic** | Tool Handler, Engines | BMS operations |
| **Data** | State Engine, Database | Data management |
| **Protocol** | BACnet Adapter | Building communication |

---

## 3. Core Components

### 3.1 OpsCopilot (main.py)

The central orchestrator that initializes and manages all components.

```python
# Location: agent_bms/main.py

class OpsCopilot:
    """Main entry point for ARVIS Ops Copilot"""
    
    def __init__(self, mode="simulator", api_port=8000):
        # Core engines
        self.state_engine = BMSStateEngine()         # Real-time state
        self.alarm_engine = AlarmEngine()            # Alarm processing
        self.energy_analyzer = EnergyAnalyzer()      # Energy analysis
        self.predictive_engine = PredictiveMaintenanceEngine()  # ML predictions
        
        # Database persistence
        self.database = get_database()               # SQLite storage
        
        # Learning engine (Titans)
        self.learning_engine = get_learning_engine() # Pattern learning
        
        # Protocol adapter
        self.bacnet_adapter = None                   # BACnet/Simulator
```

**Operating Modes:**

| Mode | Description | Use Case |
|------|-------------|----------|
| `simulator` | Fake BMS data with realistic physics | Development, demos |
| `bacnet` | Real BACnet/IP network connection | Production |
| `api_only` | No BMS connection, API testing only | Testing |

**Startup Sequence:**
1. Initialize core engines
2. Connect to BACnet network or simulator
3. Register equipment and zones
4. Start API server (FastAPI + Uvicorn)
5. Start learning engine periodic loop
6. Begin simulation loop (if simulator mode)

---

### 3.2 BMS State Engine (bms_state_engine.py)

The central real-time state store for all BMS data.

```python
# Location: agent_bms/bms_state_engine.py

class BMSStateEngine:
    """Central state management for BMS data"""
    
    # Equipment registry
    equipment: Dict[str, Equipment]
    
    # Real-time data points
    data_points: Dict[str, BMSDataPoint]
    
    # Active alarms
    alarms: List[Alarm]
    
    # Point value history (rolling window)
    point_history: Dict[str, List[Tuple[datetime, float]]]
```

**Key Features:**
- Thread-safe updates via asyncio locks
- Rolling history window (configurable, default 24 hours)
- Equipment-to-point relationship management
- Point-in-time snapshots for reports

**Example Usage:**
```python
# Update a point value
await state_engine.update_point(BMSDataPoint(
    point_id="CH-01/CHWST",
    value=7.2,
    unit="°C",
    timestamp=datetime.now()
))

# Get equipment status
chiller = await state_engine.get_equipment("CH-01")
print(f"Chiller status: {chiller.status}")
```

---

### 3.3 Alarm Engine (alarm_engine.py)

Intelligent alarm processing with clustering and prioritization.

```python
# Location: agent_bms/alarm_engine.py

class AlarmEngine:
    """Alarm clustering, prioritization, and fatigue reduction"""
    
    # Pending alarms awaiting processing
    alarm_queue: List[Alarm]
    
    # Alarm clusters (related alarms grouped)
    clusters: Dict[str, AlarmCluster]
    
    # Suppression rules
    suppression_rules: List[SuppressionRule]
```

**Alarm Processing Pipeline:**

```
Raw Alarm → Deduplication → Severity Mapping → Clustering → Prioritization → Output
                                                    ↓
                                            Suppression Check
```

**Clustering Algorithm:**
- Groups alarms by equipment, time window, and message similarity
- Presents cluster summary instead of individual alarms
- Example: 50 "zone temp high" alarms → 1 "Multiple comfort alarms (50 zones)"

**Prioritization Factors:**
1. Alarm severity (critical > high > medium > low)
2. Equipment criticality (chiller > VAV)
3. Recurrence frequency
4. Time of day (after-hours = lower priority for comfort alarms)

---

### 3.4 Energy Analyzer (energy_analyzer.py)

Energy consumption analysis with anomaly detection.

```python
# Location: agent_bms/energy_analyzer.py

class EnergyAnalyzer:
    """Energy consumption analysis and anomaly detection"""
    
    # Isolation Forest model for anomaly detection
    anomaly_model: IsolationForest
    
    # Baseline consumption by hour/day
    baselines: Dict[str, float]
    
    # Rolling energy readings
    readings: List[EnergyReading]
```

**Key Features:**
- **Baseline Learning**: Learns normal consumption patterns by hour, day, season
- **Anomaly Detection**: Flags unusual consumption using Isolation Forest
- **Peak Detection**: Identifies demand peaks for load shedding
- **Waste Calculation**: Estimates energy waste from inefficiencies

**Anomaly Detection:**
```python
# How it works
1. Collect 30 days of hourly consumption data
2. Train Isolation Forest (contamination=0.05)
3. For each new reading:
   - Extract features (hour, day, value, delta)
   - Predict (-1 = anomaly, 1 = normal)
   - If anomaly: generate insight
```

---

### 3.5 Predictive Maintenance Engine (predictive_maintenance.py)

ML-based equipment failure prediction.

```python
# Location: agent_bms/predictive_maintenance.py

class PredictiveMaintenanceEngine:
    """Predictive maintenance using multiple ML models"""
    
    # XGBoost regression for failure probability
    xgb_model: XGBRegressor
    
    # Isolation Forest for anomaly detection  
    anomaly_model: IsolationForest
    
    # Weibull survival analysis
    weibull_params: Dict[str, Tuple[float, float]]
```

**Three-Model Approach:**

| Model | Purpose | Output |
|-------|---------|--------|
| **XGBoost** | Predict failure probability | 0-1 score |
| **Isolation Forest** | Detect operating anomalies | Normal/Anomaly |
| **Weibull** | Survival analysis (time to failure) | Days remaining |

**Feature Engineering:**
```python
features = [
    "runtime_hours",           # Total operating hours
    "starts_per_day",          # Cycling frequency  
    "avg_load_percent",        # Average load
    "max_temp_delta",          # Thermal stress
    "days_since_maintenance",  # Maintenance gap
    "vibration_rms",           # Mechanical health
    "efficiency_trend",        # Performance degradation
]
```

**Prediction Example:**
```python
prediction = pm_engine.predict_failure("CH-01")
# Returns:
{
    "equipment_id": "CH-01",
    "failure_probability": 0.23,
    "days_to_failure": 45,
    "risk_level": "moderate",
    "contributing_factors": [
        "High runtime hours (12,500)",
        "Declining efficiency (82% → 78%)"
    ],
    "recommended_action": "Schedule preventive maintenance within 30 days"
}
```

---

## 4. Data Models

### 4.1 Core Models (bms_data_model.py)

```python
# Location: agent_bms/bms_data_model.py

@dataclass
class Equipment:
    """Represents a piece of BMS equipment"""
    equipment_id: str                    # "CH-01"
    name: str                            # "Chiller 1"
    equipment_type: EquipmentType        # CHILLER, AHU, VAV, etc.
    location: str                        # "Central Plant"
    status: EquipmentStatus              # RUNNING, STOPPED, FAULT
    runtime_hours: float = 0             # Operating hours
    efficiency: float = 0.85             # Current efficiency
    last_maintenance: Optional[datetime] # Last service date
    parent_equipment_id: Optional[str]   # For hierarchy

@dataclass  
class BMSDataPoint:
    """Real-time sensor/actuator value"""
    point_id: str                        # "CH-01/CHWST"
    name: str                            # "Chilled Water Supply Temp"
    value: float                         # 7.2
    unit: str                            # "°C"
    timestamp: datetime                  # When read
    equipment_id: str                    # Parent equipment
    point_type: PointType                # SENSOR, SETPOINT, STATUS
    quality: PointQuality                # GOOD, UNCERTAIN, BAD

@dataclass
class Alarm:
    """BMS alarm event"""
    alarm_id: str                        # Auto-generated UUID
    equipment_id: str                    # Source equipment
    message: str                         # "High supply air temperature"
    severity: AlarmSeverity              # CRITICAL, HIGH, MEDIUM, LOW
    state: AlarmState                    # ACTIVE, ACKNOWLEDGED, CLEARED
    triggered_at: datetime               # When occurred
    acknowledged_at: Optional[datetime]  # When ack'd
    acknowledged_by: Optional[str]       # Who ack'd
```

### 4.2 Equipment Types

```python
class EquipmentType(Enum):
    CHILLER = "chiller"
    AHU = "ahu"                    # Air Handling Unit
    VAV = "vav"                    # Variable Air Volume
    FCU = "fcu"                    # Fan Coil Unit
    PUMP = "pump"
    COOLING_TOWER = "cooling_tower"
    BOILER = "boiler"
    VFD = "vfd"                    # Variable Frequency Drive
    METER_ELECTRIC = "meter_electric"
    METER_WATER = "meter_water"
    METER_GAS = "meter_gas"
    BMS_CONTROLLER = "bms_controller"
```

### 4.3 Point Types

```python
class PointType(Enum):
    SENSOR = "sensor"              # Read-only measurement
    SETPOINT = "setpoint"          # Adjustable target
    STATUS = "status"              # Binary state (on/off)
    COMMAND = "command"            # Write-only control
    CALCULATED = "calculated"      # Derived value
```

---

## 5. BACnet Integration

### 5.1 BACnet Adapter (bacnet_adapter.py)

```python
# Location: agent_bms/bacnet_adapter.py

class BACnetAdapter:
    """BACnet/IP adapter for building automation systems (READ-ONLY)"""
    
    # BAC0 network instance
    network: Optional[BAC0.lite]
    
    # Discovered devices
    devices: Dict[int, BACnetDevice]
    
    # Configured points
    points: Dict[str, BACnetPoint]
```

**Key Design Decisions:**
- **READ-ONLY**: No control commands for safety
- **Retry Logic**: 5s timeout, 3 retries with exponential backoff
- **Polling-Based**: Configurable interval per point

### 5.2 BACnet Point Configuration

```python
@dataclass
class BACnetPoint:
    """BACnet point mapping"""
    device_id: int           # BACnet device ID
    object_type: str         # "analogInput", "binaryOutput", etc.
    object_instance: int     # Object instance number
    property_name: str       # Usually "presentValue"
    point_id: str            # ARVIS internal ID
    equipment_id: str        # Parent equipment
    unit: str                # Engineering unit
    poll_interval: int       # Seconds between reads
```

**Example Point Mapping:**
```python
BACnetPoint(
    device_id=1001,
    object_type="analogInput",
    object_instance=1,
    point_id="CH-01/CHWST",
    equipment_id="CH-01",
    unit="°C",
    poll_interval=60
)
```

### 5.3 Simulator Adapter

For development without real BACnet hardware:

```python
class BACnetSimulatorAdapter:
    """Simulated BACnet adapter for testing"""
    
    # Realistic value generation
    _simulated_values = {
        "CH-01/CHWST": 7.0,      # Chilled water supply
        "CH-01/CHWRT": 12.0,     # Chilled water return
        "CH-01/KW": 250.0,       # Chiller power (kW)
        "AHU-01/SAT": 14.0,      # Supply air temp
        "METER-01/KW": 450.0,    # Building power
    }
```

**Physics-Based Simulation:**
- Temperature values drift ±0.5°C
- Power values vary ±5%
- Occasional alarm generation (2% chance per cycle)

---

## 6. Machine Learning Engines

### 6.1 Overview

| Engine | ML Models | Purpose |
|--------|-----------|---------|
| Predictive Maintenance | XGBoost, IsolationForest, Weibull | Equipment failure prediction |
| Energy Analyzer | Isolation Forest | Consumption anomaly detection |
| Alarm Clustering | DBSCAN (optional) | Group related alarms |

### 6.2 Model Training

**Predictive Maintenance:**
```python
# Trains on historical maintenance records
features = extract_equipment_features(equipment_history)
xgb_model.fit(features, failure_labels)

# Weibull parameters from survival analysis
weibull_params = fit_weibull(time_to_failure_data)
```

**Energy Analyzer:**
```python
# Trains on 30 days of consumption data
hourly_readings = aggregate_by_hour(energy_data)
anomaly_model.fit(hourly_readings)
```

### 6.3 Inference

```python
# Real-time prediction
async def predict_failure(equipment_id: str):
    equipment = await state_engine.get_equipment(equipment_id)
    features = extract_features(equipment)
    
    # XGBoost probability
    prob = xgb_model.predict_proba(features)[0][1]
    
    # Isolation Forest anomaly
    is_anomaly = anomaly_model.predict(features)[0] == -1
    
    # Weibull time-to-failure
    ttf = calculate_weibull_ttf(equipment.runtime_hours)
    
    return {
        "failure_probability": prob,
        "is_anomalous": is_anomaly,
        "days_to_failure": ttf
    }
```

---

## 7. LLM Agent & Tools

### 7.1 BMSLLMAgent (bms_llm_agent.py)

```python
# Location: agent_bms/bms_llm_agent.py

class BMSLLMAgent:
    """LLM Agent for natural language BMS interaction"""
    
    # Multi-provider support
    providers = ["groq", "openrouter", "openai", "gemini"]
    
    # Arabic language detection
    arabic_pattern = re.compile(r'[\u0600-\u06FF]')
```

**Provider Fallback Chain:**
```
1. Groq (fastest, preferred)
2. OpenRouter (backup)
3. OpenAI (backup)
4. Gemini (backup)
5. Fallback (rule-based, no LLM)
```

**Chat Flow:**
```
User Query → Language Detection → System Prompt Selection
                                         ↓
                                  Tool Generation
                                         ↓
                                  Tool Execution
                                         ↓
                                  Result Summarization
                                         ↓
                                  Response (EN/AR)
```

### 7.2 Tool Handler (tools_schema.py)

```python
# Location: agent_bms/tools_schema.py

class BMSToolHandler:
    """Executes LLM tool calls against BMS engines"""
    
    async def execute(self, tool_name: str, args: Dict) -> Dict:
        handler = self._handlers.get(tool_name)
        if handler:
            return await handler(args)
        return {"error": f"Unknown tool: {tool_name}"}
```

### 7.3 Available Tools (18 Total)

#### Core BMS Tools
| Tool | Description | Example Args |
|------|-------------|--------------|
| `get_equipment_status` | Get equipment details | `{"equipment_id": "CH-01"}` |
| `get_equipment_list` | List all equipment | `{"type_filter": "chiller"}` |
| `get_active_alarms` | Get current alarms | `{"severity": "critical"}` |
| `acknowledge_alarm` | Ack an alarm | `{"alarm_id": "abc123"}` |
| `get_energy_consumption` | Get energy data | `{"period": "today"}` |
| `get_data_point` | Read a point value | `{"point_id": "CH-01/CHWST"}` |

#### Predictive & Analytics Tools
| Tool | Description | Example Args |
|------|-------------|--------------|
| `predict_failures` | Get failure predictions | `{"equipment_id": "CH-01"}` |
| `get_equipment_health` | Get health score | `{"equipment_id": "AHU-01"}` |
| `get_energy_anomalies` | Find consumption anomalies | `{}` |

#### GSAS Compliance Tools
| Tool | Description | Example Args |
|------|-------------|--------------|
| `get_gsas_status` | Get GSAS scores | `{"building_id": "main"}` |
| `generate_gord_report` | Generate compliance PDF | `{}` |

#### Strategic "Killer" Tools
| Tool | Description | Example Args |
|------|-------------|--------------|
| `get_burn_rate` | Current QAR/hour cost | `{"total_kw": 450}` |
| `predict_setpoint_cost` | Cost of temp change | `{"zone_id": "Z1", "new_temp": 22}` |
| `find_ghost_spaces` | Find empty but conditioned rooms | `{"floor_filter": "1"}` |
| `estimate_zone_occupancy` | Virtual occupancy | `{"zone_id": "Z1"}` |
| `verify_maintenance_work` | Check if work was done | `{"work_order_id": "WO-123"}` |
| `create_work_order` | Create maintenance WO | `{"equipment_id": "CH-01"}` |

### 7.4 System Prompts

**English Prompt:**
```
You are ARVIS Ops Copilot, an AI-powered Building Management System advisor 
for commercial buildings in Qatar. You help facility managers with:

- Real-time equipment monitoring and alarms
- Energy optimization and cost analysis
- Predictive maintenance scheduling  
- GSAS sustainability compliance

Always be helpful, concise, and provide specific data when available.
Use QAR for currency. Acknowledge the desert climate context.
```

**Arabic Prompt:**
```
أنت أرفيس مساعد العمليات، مستشار ذكي لأنظمة إدارة المباني...
```

---

## 8. REST API

### 8.1 API Structure (routes.py)

```python
# Location: agent_bms/api/routes.py

# FastAPI application
app = FastAPI(
    title="ARVIS Ops Copilot API",
    version="1.0.0",
    docs_url="/api/docs"
)
```

### 8.2 Endpoints

#### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/dashboard/overview` | Dashboard summary |

**Response:**
```json
{
    "timestamp": "2026-01-16T00:30:00",
    "equipment_total": 6,
    "equipment_running": 6,
    "equipment_fault": 0,
    "active_alarms_critical": 0,
    "active_alarms_high": 1,
    "active_alarms_total": 3,
    "energy_today_kwh": 1250.5,
    "energy_vs_baseline_percent": -5.2,
    "insights_pending": 2,
    "maintenance_due_7d": 3
}
```

#### Equipment
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/equipment` | List all equipment |
| GET | `/api/v1/equipment/{id}` | Get equipment details |
| GET | `/api/v1/equipment/{id}/points` | Get equipment points |

#### Alarms
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/alarms` | Get active alarms |
| POST | `/api/v1/alarms/{id}/acknowledge` | Acknowledge alarm |

#### Energy
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/energy/consumption` | Get consumption data |
| GET | `/api/v1/energy/anomalies` | Get detected anomalies |

#### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat` | Natural language query |

**Request:**
```json
{
    "message": "What's wrong with chiller 1?",
    "context": {"floor": "1"}
}
```

**Response:**
```json
{
    "response": "Chiller 1 (CH-01) is currently running normally...",
    "tool_calls": [{"tool": "get_equipment_status", "args": {...}}],
    "confidence": 0.92,
    "language": "en"
}
```

#### GSAS Compliance
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/gsas/status` | Get GSAS scores |
| GET | `/api/v1/gsas/gord-report` | Generate GORD PDF |
| GET | `/api/v1/gsas/improvement-priorities` | Get improvement list |

#### Maintenance
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/maintenance/predictions` | Get failure predictions |
| POST | `/api/v1/maintenance/work-orders` | Create work order |

---

## 9. Database Persistence

### 9.1 SQLite Database (database.py)

```python
# Location: agent_bms/database.py

class BMSDatabase:
    """SQLite persistence layer for BMS data"""
    
    db_path = "agent_bms/data/arvis_bms.db"
```

### 9.2 Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `equipment` | Equipment registry | id, name, type, status |
| `data_points` | Point history | point_id, value, timestamp |
| `alarms` | Alarm history | id, equipment_id, severity, state |
| `energy_readings` | Energy data | meter_id, value, timestamp |
| `zones` | Zone configurations | zone_id, sensors, schedule |
| `work_orders` | Maintenance WOs | id, equipment_id, snapshots |
| `gsas_scores` | GSAS assessments | building_id, scores, timestamp |

### 9.3 Key Methods

```python
# Equipment
db.save_equipment(equipment_dict)
db.get_all_equipment()
db.get_equipment_requiring_maintenance(days=7)

# Energy
db.save_energy_reading(meter_id, value, unit, timestamp)
db.get_energy_today()
db.get_energy_baseline_comparison()

# Alarms
db.save_alarm(alarm_dict)
db.get_active_alarms()
db.get_pending_insights_count()

# Zones
db.save_zone(zone_config)
db.get_all_zones()
db.get_zone_with_current_values(zone_id)

# Work Orders
db.create_work_order(equipment_id, task_type, pre_snapshot)
db.close_work_order(work_order_id, post_snapshot, verification_result)
```

---

## 10. Titans Learning Loop

### 10.1 Overview

The Titans Learning Loop enables ARVIS to **learn from operator behavior** and improve over time, without model fine-tuning.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TITANS LEARNING LOOP                         │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │   OBSERVE   │───►│   STORE     │───►│   LEARN     │        │
│  │ (Operator   │    │ (ChromaDB   │    │ (30-min     │        │
│  │  Actions)   │    │  Patterns)  │    │  Cycle)     │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│         ▲                                     │                 │
│         │                                     ▼                 │
│  ┌─────────────┐                      ┌─────────────┐          │
│  │   APPLY     │◄─────────────────────│   SUGGEST   │          │
│  │ (Few-Shot   │                      │ (Automation │          │
│  │  Examples)  │                      │  Rules)     │          │
│  └─────────────┘                      └─────────────┘          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Operator Pattern Store (operator_patterns.py)

```python
# Location: agent_bms/learning/operator_patterns.py

class OperatorPatternStore:
    """ChromaDB store for operator interaction patterns"""
    
    # Query patterns (chat → tool mappings)
    query_collection: chromadb.Collection
    
    # Alarm response patterns
    alarm_collection: chromadb.Collection
```

**Pattern Types:**

| Type | Example | Learning Outcome |
|------|---------|-----------------|
| Query → Tool | "chiller status" → get_equipment_status | Few-shot injection |
| Alarm Response | Always silence comfort alarms | Suggest priority change |
| Equipment Focus | Frequently query CH-01 | Add to dashboard |

**Methods:**
```python
# Log successful query
store.log_query_success(
    query="What's wrong with AHU-01?",
    tool_calls=[{"tool": "get_equipment_status", "args": {...}}]
)

# Get similar patterns for few-shot
patterns = store.get_similar_queries("Check AHU status")

# Format as few-shot examples
fewshot = store.format_query_fewshot(patterns)
```

### 10.3 Learning Engine (learning_engine.py)

```python
# Location: agent_bms/learning/learning_engine.py

class BMSLearningEngine:
    """Periodic learning cycle for pattern detection"""
    
    interval_seconds = 1800  # 30 minutes
```

**Learning Cycle:**
```python
async def run_learning_cycle(self):
    # 1. Gather context
    context = await self._gather_learning_context()
    
    # 2. Local pattern analysis
    patterns = self._analyze_patterns_local(context)
    
    # 3. LLM-based suggestions (if available)
    suggestions = await self._generate_suggestions(context, patterns)
    
    # 4. Store lessons
    for pattern in patterns:
        self._store_lesson(pattern)
```

**Patterns Detected:**
1. **Recurring Alarms**: Same alarm 3+ times → Suggest investigation
2. **Frequent Tools**: Most-used tools → Add shortcuts
3. **Equipment Focus**: Frequently queried equipment → Dashboard priority

### 10.4 Integration Points

**BMSLLMAgent logs successful queries:**
```python
# In bms_llm_agent.py chat() method
if tool_calls:
    learning = get_learning_engine()
    learning.log_query_success(query, tool_calls)
```

**OpsCopilot starts learning engine:**
```python
# In main.py start() method
await self.learning_engine.start()
```

---

## 11. GSAS Compliance

### 11.1 GSAS Reporter (gsas_reporter.py)

```python
# Location: agent_bms/gsas_reporter.py

class GSASReporter:
    """GSAS v2.1 compliance reporting for Qatar buildings"""
```

**GSAS Categories:**
| Category | Weight | Key Metrics |
|----------|--------|-------------|
| Energy (E) | 24% | EUI, efficiency, renewable |
| Water (W) | 16% | WUI, recycling, fixtures |
| Indoor Environment (IE) | 16% | Comfort, IAQ, lighting |
| Cultural & Economic (CE) | 8% | Local materials, heritage |
| Site (S) | 9% | Landscaping, heat island |
| Urban Connectivity (UC) | 7% | Transport, walkability |
| Management (MO) | 14% | O&M, documentation |
| Materials (M) | 6% | Recycled, regional |

### 11.2 GORD Report Generation

```python
# Generate GORD compliance PDF
report = gsas_reporter.generate_gord_report(
    building_id="main",
    assessment_period="2026-Q1"
)

# Returns PDF bytes + metadata
{
    "pdf_content": bytes,
    "certification_level": "3-Star",
    "overall_score": 2.8,
    "improvement_priorities": [...]
}
```

### 11.3 Certification Levels

| Level | Score Range | Description |
|-------|-------------|-------------|
| Certified | 0.5 - 1.0 | Minimum compliance |
| 1-Star | 1.0 - 1.5 | Basic sustainability |
| 2-Star | 1.5 - 2.0 | Good performance |
| 3-Star | 2.0 - 2.5 | High performance |
| 4-Star | 2.5 - 3.0 | Outstanding |
| 5-Star | 3.0+ | World class |

---

## 12. Running the System

### 12.1 Installation

```bash
# Clone repository
git clone <repo>
cd Automation

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements-bms.txt
```

### 12.2 Environment Variables

```bash
# .env file
GROQ_API_KEY=gsk_xxx           # Primary LLM provider
OPENROUTER_API_KEY=sk-xxx      # Backup LLM provider
ARVIS_MODE=commercial          # residential | commercial
```

### 12.3 Running

```bash
# Simulator mode (development)
python -m agent_bms.main --mode simulator --port 8000

# BACnet mode (production)
python -m agent_bms.main --mode bacnet --port 8000 \
    --bacnet-address 192.168.1.100 --bacnet-port 47808
```

### 12.4 Accessing the System

| Interface | URL | Description |
|-----------|-----|-------------|
| API Docs | http://localhost:8000/api/docs | Swagger UI |
| Dashboard API | http://localhost:8000/api/v1/dashboard/overview | JSON |
| Chat API | POST http://localhost:8000/api/v1/chat | NL Interface |

---

## 13. File Structure

```
agent_bms/
├── __init__.py
├── main.py                  # Entry point, OpsCopilot orchestrator
├── bms_data_model.py        # Equipment, Alarm, DataPoint models
├── bms_state_engine.py      # Real-time state management
├── bms_llm_agent.py         # LLM integration
├── alarm_engine.py          # Alarm processing & clustering
├── energy_analyzer.py       # Energy analysis & anomaly detection
├── predictive_maintenance.py # ML failure prediction
├── bacnet_adapter.py        # BACnet/IP + simulator
├── tools_schema.py          # 18 LLM tools + handler
├── gsas_reporter.py         # GSAS compliance reports
├── cost_engine.py           # QAR burn rate calculations
├── virtual_sensors.py       # Ghost detector, occupancy
├── verification_engine.py   # Maintenance verification
├── database.py              # SQLite persistence
│
├── api/
│   ├── __init__.py
│   └── routes.py            # FastAPI REST endpoints
│
├── learning/
│   ├── __init__.py
│   ├── operator_patterns.py # ChromaDB pattern store
│   └── learning_engine.py   # Titans learning cycle
│
└── data/
    ├── arvis_bms.db         # SQLite database
    └── patterns/            # ChromaDB pattern storage
        └── patterns_db/
```

---

## Summary

ARVIS Ops Copilot is a production-ready AI-powered BMS advisor that combines:

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Protocol** | BACnet/IP, BAC0 | Building communication |
| **Data** | SQLite, ChromaDB | Persistence & patterns |
| **ML** | XGBoost, IsolationForest, Weibull | Predictions & anomalies |
| **AI** | Groq/OpenRouter/Gemini LLMs | Natural language |
| **Learning** | Titans Architecture | Continuous improvement |
| **Compliance** | GSAS v2.1 | Qatar sustainability |

**Ready for pilot deployment in Qatar commercial buildings!** 🏗️
