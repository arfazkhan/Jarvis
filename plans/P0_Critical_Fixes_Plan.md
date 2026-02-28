# P0 Critical Blockers Fix Plan

## Overview

This document outlines the implementation plan for fixing the P0 critical blockers identified in the ARVIS forensic audit.

## Blockers to Fix

### 1. Emergency Kill Switch (CRITICAL)

**File:** [`api/routers/admin.py`](api/routers/admin.py)

**Current State:**
```python
@router.post("/safety-override")
async def safety_override(req: KillSwitchRequest, sys: SystemContainer = Depends(get_system_state)):
    """EMERGENCY KILL SWITCH."""
    if sys.automation_engine:
        # sys.automation_engine.stop_all() 
        pass
        
    if sys.matter_controller:
        # sys.matter_controller.emergency_stop() 
        pass
        
    return {"status": "SHUTDOWN_INITIATED", "reason": req.reason}
```

**Required Implementation:**

1. Add `stop_all()` method to `AutomationEngine` class
2. Add `emergency_stop()` method to `MatterController` class
3. Wire up the admin router to call these methods

**Implementation Details:**

#### AutomationEngine.stop_all()
```python
def stop_all(self):
    """Stop all running automations and prevent new ones from starting."""
    # 1. Stop the scheduler
    if self.scheduler:
        self.scheduler.stop()
    
    # 2. Disable all routines
    for name in self.routines:
        self.routines[name]["enabled"] = False
    
    # 3. Publish emergency event
    if self.event_bus:
        self.event_bus.publish({
            "type": "emergency_shutdown",
            "source": "automation_engine",
            "timestamp": time.time()
        })
    
    print("[AutomationEngine] ⛔ All automations STOPPED")
```

#### MatterController.emergency_stop()
```python
def emergency_stop(self):
    """Emergency stop - turn off all device endpoints."""
    # 1. Turn off all known devices
    for device_id, config in self.devices.items():
        try:
            self.turn_off(device_id, config.endpoint)
        except Exception as e:
            print(f"[MatterController] Failed to stop {device_id}: {e}")
    
    # 2. Publish emergency event
    print("[MatterController] ⛔ Emergency stop executed")
```

---

### 2. Learning Endpoints Return Mock Data

**File:** [`api/routers/learning.py`](api/routers/learning.py)

**Current State:**
```python
@router.get("/patterns")
async def get_patterns(sys: SystemContainer = Depends(get_system_state)):
    """Discovered operational patterns."""
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        # return sys.learning_engine.pattern_analyzer.get_top_patterns()
        pass
    return [{"pattern": "Chiller starts early on Mondays", "confidence": 0.9}]
```

**Required Implementation:**

1. Check if `PatternAnalyzer` has `get_top_patterns()` method
2. If not, add it to `PatternAnalyzer` class
3. Wire up the learning router to use real data

**Implementation Details:**

#### PatternAnalyzer.get_top_patterns()
```python
def get_top_patterns(self, limit: int = 10) -> List[Dict]:
    """Get top discovered patterns sorted by confidence."""
    patterns = []
    for pattern_id, data in self.patterns.items():
        patterns.append({
            "id": pattern_id,
            "pattern": data.get("description", ""),
            "confidence": data.get("confidence", 0.0),
            "occurrences": data.get("count", 0),
            "last_seen": data.get("last_seen")
        })
    
    # Sort by confidence descending
    patterns.sort(key=lambda x: x["confidence"], reverse=True)
    return patterns[:limit]
```

---

### 3. Pass Statements in API Routers

**Files to Fix:**

| File | Endpoint | Issue |
|------|----------|-------|
| [`api/routers/firmware.py`](api/routers/firmware.py) | `/devices` | `pass` instead of calling `get_nodes()` |
| [`api/routers/voice.py`](api/routers/voice.py) | `/config/vad` | `pass` instead of calling `set_vad_sensitivity()` |

**Implementation Details:**

#### firmware.py - list_iot_devices()
```python
@router.get("/devices")
async def list_iot_devices(sys: SystemContainer = Depends(get_system_state)):
    """List Matter/ESP32 devices."""
    if sys.matter_controller:
        devices = sys.matter_controller.discover()
        return [
            {
                "id": device_id,
                "name": info.get("name", device_id),
                "type": info.get("type", "unknown"),
                "status": "online" if info.get("endpoints") else "offline"
            }
            for device_id, info in devices.items()
        ]
    return []
```

#### voice.py - config_vad()
```python
@router.post("/config/vad")
async def config_vad(sensitivity: float, sys: SystemContainer = Depends(get_system_state)):
    """Configure VAD sensitivity."""
    if sys.voice_coordinator:
        if hasattr(sys.voice_coordinator, 'ears') and hasattr(sys.voice_coordinator.ears, 'set_vad_sensitivity'):
            sys.voice_coordinator.ears.set_vad_sensitivity(sensitivity)
        else:
            # Store config for next restart
            logger.info(f"VAD sensitivity set to {sensitivity} (will apply on restart)")
    return {"sensitivity": sensitivity, "status": "configured"}
```

---

## Implementation Order

1. **First:** Add methods to core classes (`AutomationEngine`, `MatterController`, `PatternAnalyzer`)
2. **Second:** Update API routers to use the new methods
3. **Third:** Add proper error handling and logging

## Testing Plan

After implementation:
1. Test kill switch via `POST /api/v1/admin/safety-override`
2. Test learning patterns via `GET /api/v1/learning/patterns`
3. Test device listing via `GET /api/v1/firmware/devices`
4. Test VAD config via `POST /api/v1/voice/config/vad`

---

## Files to Modify

| File | Changes |
|------|---------|
| `agent_home/automations/automation_engine.py` | Add `stop_all()` method |
| `agent_home/controllers/matter_controller.py` | Add `emergency_stop()` and `turn_off()` methods |
| `agent_home/learning/pattern_analyzer.py` | Add `get_top_patterns()` method |
| `api/routers/admin.py` | Wire up kill switch |
| `api/routers/learning.py` | Wire up pattern analyzer |
| `api/routers/firmware.py` | Wire up device discovery |
| `api/routers/voice.py` | Wire up VAD sensitivity |

---

## Switch to Code Mode

To implement these fixes, switch to **Code mode** and reference this plan document.
