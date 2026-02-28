# P1 High Priority Fixes Plan

## Overview

This document outlines the implementation plan for P1 high-priority fixes for ARVIS.

## Items to Fix

### 1. Implement Firmware Update Endpoints

**Current State:** Placeholder implementation in [`api/routers/firmware.py`](api/routers/firmware.py)

**Required Implementation:**

1. **OTA Update Manager** - Create a dedicated module for OTA updates
2. **Firmware Version Management** - Track firmware versions per device
3. **Update Status Tracking** - Monitor update progress
4. **Rollback Support** - Ability to rollback failed updates

**New Files to Create:**
- `agent_home/firmware/ota_manager.py` - OTA update orchestration
- `agent_home/firmware/version_tracker.py` - Firmware version management

**Endpoints to Implement:**
- `POST /firmware/ota/update` - Initiate OTA update
- `GET /firmware/ota/status/{device_id}` - Check update status
- `POST /firmware/ota/rollback/{device_id}` - Rollback update
- `GET /firmware/versions` - List available firmware versions

---

### 2. Add Proper Restart/Shutdown Orchestration

**Current State:** Basic implementation in [`api/routers/admin.py`](api/routers/admin.py)

**Required Implementation:**

1. **Graceful Shutdown Sequence** - Ordered component shutdown
2. **Health Check Before Restart** - Verify components are ready
3. **State Persistence** - Save state before shutdown
4. **Startup Sequence** - Ordered component initialization
5. **Process Manager Integration** - Supervisor/systemd support

**Files to Modify:**
- `api/main.py` - Add lifespan shutdown sequence
- `api/routers/admin.py` - Enhance restart endpoint
- `arvis_core/orchestration/` - New module for orchestration

**New Endpoints:**
- `POST /admin/shutdown` - Graceful shutdown
- `POST /admin/restart` - Full restart with health checks
- `GET /admin/startup-status` - Check initialization progress

---

### 3. Complete Voice VAD Sensitivity Controls

**Current State:** Partial implementation in [`api/routers/voice.py`](api/routers/voice.py)

**Required Implementation:**

1. **VAD Configuration Storage** - Persist VAD settings
2. **Real-time VAD Adjustment** - Adjust without restart
3. **VAD Calibration Mode** - Auto-calibrate sensitivity
4. **VAD Metrics Endpoint** - Expose VAD performance metrics

**Files to Modify:**
- `agent_home/voice/realtime_voice.py` - Add VAD control methods
- `agent_home/voice/semantic_vad.py` - Add sensitivity controls
- `api/routers/voice.py` - Complete VAD endpoints

**New Endpoints:**
- `POST /voice/config/vad` - Set VAD sensitivity (already added)
- `GET /voice/config/vad` - Get current VAD config
- `POST /voice/vad/calibrate` - Auto-calibrate VAD
- `GET /voice/vad/metrics` - VAD performance metrics

---

### 4. Add Comprehensive API Integration Tests

**Current State:** Scattered test files, no unified API test suite

**Required Implementation:**

1. **Test Framework Setup** - pytest with fixtures
2. **API Test Suite** - Test all endpoints
3. **Authentication Tests** - Test API key security
4. **Error Handling Tests** - Test error responses
5. **Integration Tests** - End-to-end flows

**New Files to Create:**
- `tests/api/__init__.py`
- `tests/api/conftest.py` - Shared fixtures
- `tests/api/test_admin.py` - Admin endpoint tests
- `tests/api/test_learning.py` - Learning endpoint tests
- `tests/api/test_firmware.py` - Firmware endpoint tests
- `tests/api/test_voice.py` - Voice endpoint tests
- `tests/api/test_integration.py` - End-to-end tests

---

## Implementation Order

1. **First:** Restart/Shutdown Orchestration (foundation for other changes)
2. **Second:** Voice VAD Controls (completes existing partial implementation)
3. **Third:** Firmware Update Endpoints (new functionality)
4. **Fourth:** API Integration Tests (validates all changes)

---

## Files Summary

| Category | Files to Create | Files to Modify |
|----------|-----------------|-----------------|
| Firmware | 2 | 1 |
| Orchestration | 1 | 2 |
| Voice | 0 | 3 |
| Tests | 7 | 0 |
| **Total** | **10** | **6** |

---

## Switch to Code Mode

To implement these fixes, switch to **Code mode** and reference this plan document.
