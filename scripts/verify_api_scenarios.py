import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Set Env Var BEFORE importing app/security to ensure keys are loaded
os.environ["ARVIS_API_KEYS"] = "test-admin-key,test-user-key"

# Add root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from api.main import app
from agent_home.llm_agent.llm_agent import LLMAgent

# Initialize Test Client
# This triggers the lifespan event (startup)
print("🚀 Initializing ARVIS API for Scenario Testing...")
client = TestClient(app)

# Test Data
HEADERS = {"X-ARVIS-KEY": "test-admin-key"}

def log(message, category="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{category}] {message}")

def run_scenario(name, steps):
    print(f"\n🎬 SCENARIO: {name}")
    print("="*60)
    success_count = 0
    
    for step_name, method, url, payload in steps:
        try:
            log(f"Executing: {step_name} ({method} {url})", "STEP")
            
            # Simple query param handling for GET if payload is provided
            if method == "GET" and payload:
                # Append payload as query params if not already in URL
                if "?" not in url:
                    from urllib.parse import urlencode
                    url += "?" + urlencode(payload)

            if method == "GET":
                resp = client.get(url, headers=HEADERS)
            elif method == "POST":
                resp = client.post(url, json=payload, headers=HEADERS)
            
            if resp.status_code in [200, 201, 202]:
                log(f"✅ Success ({resp.status_code})", "PASS")
                # Optional: print snippet of response
                try:
                    data = resp.json()
                    snippet = str(data)[:100] + "..." if len(str(data)) > 100 else str(data)
                    log(f"   Response: {snippet}", "DATA")
                except:
                    pass
                success_count += 1
            else:
                log(f"❌ Failed ({resp.status_code}): {resp.text}", "FAIL")
                
        except Exception as e:
            log(f"❌ Exception: {e}", "ERROR")
            
    print(f"\n✨ Scenario Complete. Success: {success_count}/{len(steps)}")
    return success_count == len(steps)

def main():
    # 1. System Health & Infrastructure
    # ----------------------------------------------------------------
    infra_steps = [
        ("Root Check", "GET", "/", None),
        ("Docs Check", "GET", "/docs", None),
        ("Admin Health", "GET", "/api/v1/admin/health", None),
        ("Infrastructure Status", "GET", "/api/v1/infrastructure/status", None),
        ("Config View", "GET", "/api/v1/admin/config", None),
    ]
    run_scenario("System Infrastructure & Health", infra_steps)

    # 2. Morning Routine (Agent, Mission, Briefing)
    # ----------------------------------------------------------------
    morning_steps = [
        ("Get Daily Briefing", "GET", "/api/v1/agent/briefing", None),
        ("Check Active Goals", "GET", "/api/v1/mission/goals", None),
        ("Check Active Plan", "GET", "/api/v1/mission/plan/active", None),
        ("Get Persona State", "GET", "/api/v1/personality/state", None),
        ("List Automations", "GET", "/api/v1/automations/jobs", None),
    ]
    run_scenario("Morning Routine", morning_steps)

    # 3. BMS & Operations (Real-time Data)
    # ----------------------------------------------------------------
    bms_steps = [
        ("BMS Dashboard", "GET", "/api/v1/bms/dashboard", None),
        ("List Equipment", "GET", "/api/v1/bms/equipment", None),
        ("Active Alarms", "GET", "/api/v1/bms/alarms", None),
        ("Energy Analysis", "GET", "/api/v1/bms/energy/analysis", None),
        ("Sensor Health", "GET", "/api/v1/sensors/health", None),
        ("Firmware Nodes", "GET", "/api/v1/firmware/devices", None),
    ]
    run_scenario("BMS Operations", bms_steps)

    # 4. Cognitive & Research (LLM, RAG, Chat)
    # ----------------------------------------------------------------
    cognitive_steps = [
        ("LLM Providers", "GET", "/api/v1/llm/providers", None),
        ("Skill Search", "GET", "/api/v1/knowledge/skills/search", {"query": "chiller maintenance"}),
        ("Refection Pattern", "GET", "/api/v1/learning/patterns", None),
        # ("Agent Chat", "POST", "/api/v1/agent/chat", {"message": "Status", "voice_mode": False}), 
    ]
    run_scenario("Cognitive Layer", cognitive_steps)

    # 5. Maintenance & Action
    # ----------------------------------------------------------------
    maint_steps = [
        ("Maintenance Predictions", "GET", "/api/v1/maintenance/predictions", None),
        ("Verify Work", "POST", "/api/v1/maintenance/verification?wo_id=T-101", None),
        ("Advisory Audit", "GET", "/api/v1/advisory/audit-log", None),
        ("Voice Config VAD", "POST", "/api/v1/voice/config/vad?sensitivity=0.5", None),
    ]
    run_scenario("Maintenance & Action", maint_steps)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Test Aborted.")
