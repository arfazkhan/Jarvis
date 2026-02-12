import sys
import os
import time
from pathlib import Path
from datetime import datetime

# Set Env Var BEFORE importing app
os.environ["ARVIS_API_KEYS"] = "test-admin-key,test-user-key"
# Ensure K2 env vars are present if not already (though they should be in .env)
# os.environ["LLM_PROVIDER"] = "k2think" # Let .env handle this or system default

# Add root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from api.main import app

HEADERS = {"X-ARVIS-KEY": "test-admin-key"}

def main():
    print("🚀 Initializing ARVIS API (REAL SYSTEM)...")
    
    # Defaults for POST bodies and Query Params
    DEFAULT_PAYLOADS = {
        "/api/v1/knowledge/skills/search": {"query": "test", "limit": 1},
        "/api/v1/maintenance/verification": None, 
        "/api/v1/voice/config/vad": None,
        "/api/v1/agent/chat": {"message": "ping", "voice_mode": False},
        "/api/v1/agent/instruct": {"command": "ping"},
        "/api/v1/mission/inference": None, 
        "/api/v1/automations/jobs/trigger": None, 
        "/api/v1/automations/scenes/activate": None,
        "/api/v1/firmware/ota/update": None,
        "/api/v1/llm/config/switch": None,
        "/api/v1/personality/persona": None,
        "/api/v1/voice/config/synthesizer": None,
        "/api/v1/learning/patterns/promote": None,
        "/api/v1/admin/safety-override": {"reason": "test_verification", "force": False},
        "/api/v1/conversation/intent/check": None, 
        "/api/v1/planning/create": None, 
        "/api/v1/sensors/ingest": {"temp": 22.5}, 
    }
    
    # Use context manager to trigger lifespan events (startup/shutdown)
    with TestClient(app) as client:
        print("✅ System Started. Running Tests...")
        
        unique_routes = set()
        endpoints_to_test = []
        
        # Extract all routes
        for route in app.routes:
            if hasattr(route, "path"):
                path = route.path
                methods = []
                if hasattr(route, "methods"):
                    methods = [m for m in route.methods if m in ["GET", "POST", "PUT", "DELETE"]]
                
                for method in methods:
                    unique_routes.add(f"{method} {path}")
                    
                    # Defaults for parameterized paths
                    DEFAULT_PARAMS = {
                        "device_id": "node_12",
                        "ticket_id": "T-101",
                        "job_id": "job_001",
                        "scene_id": "night_mode",
                        "persona_id": "jarvis_default",
                        "provider_name": "k2think",
                        "wo_id": "T-101"
                    }

                    # Prepare URL with parameters for path variables {id}
                    test_url = path
                    for param, value in DEFAULT_PARAMS.items():
                        if f"{{{param}}}" in test_url:
                            test_url = test_url.replace(f"{{{param}}}", value)
                    
                    if "{" in test_url:
                        print(f"⚠️  Skipping complex path: {method} {path}")
                        continue
                        
                    endpoints_to_test.append((method, test_url, path))

        print(f"✅ Found {len(unique_routes)} unique endpoints.")
        print("="*60)
        
        success_count = 0
        failed_routes = []
        
        for method, url, original_path in endpoints_to_test:
            try:
                resp = None
                if method == "GET":
                    # Special case for knowledge search which needs query param
                    if "knowledge/skills/search" in url and "?" not in url:
                        url += "?query=test"
                    resp = client.get(url, headers=HEADERS)
                    
                elif method == "POST":
                    # If we have a defined body payload, use it
                    payload = DEFAULT_PAYLOADS.get(original_path, {})
                    
                    # Appending query params
                    if "?" not in url:
                        params = []
                        if "jobs/trigger" in url: params.append("job_id=job_001")
                        if "scenes/activate" in url: params.append("scene_id=night_mode")
                        if "switch" in url: params.append("provider_name=k2think")
                        if "persona" in url: params.append("persona_id=jarvis_default")
                        if "ota/update" in url: params.append("device_id=node_12&version=1.0")
                        if "vad" in url: params.append("sensitivity=0.5")
                        if "synthesizer" in url: params.append("engine=vibevoice")
                        if "patterns/promote" in url: params.append("pattern_id=pat_001")
                        if "inference" in url: params.append("cmd=test_command")
                        if "intent/check" in url: params.append("text=hello")
                        if "planning/create" in url: params.append("request=test_plan")
                        if "verification" in url: params.append("wo_id=T-101")
                        
                        if params:
                            url += "?" + "&".join(params)
                    
                    # Knowledge search Get/Post fix
                    if "knowledge/skills/search" in url and method=="GET":
                        if "?" not in url: url += "?query=test"

                    resp = client.post(url, json=payload, headers=HEADERS)

                if resp and resp.status_code in [200, 201, 202]:
                    print(f"✅ [{resp.status_code}] {method} {url}")
                    success_count += 1
                elif resp:
                    print(f"❌ [{resp.status_code}] {method} {url} - {resp.text[:100]}")
                    failed_routes.append((f"{method} {url}", resp.status_code))
                else:
                    pass
                    
            except Exception as e:
                print(f"❌ [ERR] {method} {url} - {e}")
                failed_routes.append((f"{method} {url}", "Exception"))

        print("="*60)
        print(f"📊 TRUE COVERAGE: {success_count}/{len(endpoints_to_test)} Checked Endpoints Passed")
        
        if failed_routes:
            print("\n❌ FAILURES:")
            for url, code in failed_routes:
                print(f"  - {url}: {code}")

if __name__ == "__main__":
    main()
