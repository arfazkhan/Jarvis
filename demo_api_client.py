import asyncio
import httpx
import json
import logging
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("arvis.api.demo")

API_BASE = "http://localhost:8000/api/v1"

async def monitor_stream():
    """Stream 'Glass Box' thoughts from the API and log to file."""
    logger.info(f"Connecting to Glass Box Stream at {API_BASE}/stream/thoughts...")
    
    log_file = "glass_box_simulation.jsonl"
    print(f"[CLIENT] Logging all events to {log_file}...")
    
    async with httpx.AsyncClient(timeout=None) as client:
        with open(log_file, "a", encoding="utf-8") as f:
            async with client.stream("GET", f"{API_BASE}/stream/thoughts") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:]
                        try:
                            # Log raw JSONL
                            f.write(data_str + "\n")
                            f.flush()
                            
                            # Print pretty output to console
                            data = json.loads(data_str)
                            if "content" in data:
                                print(f"\n[STREAM] 🧠 THOUGHT: {data['content'][:100]}...")
                            elif "tool" in data:
                                print(f"\n[STREAM] 🛠️ TOOL: {data.get('tool')} ({data.get('status', 'done')})")
                        except:
                            pass
                    elif line.startswith("event:"):
                        event_type = line[6:].strip()
                        if event_type != "thought":
                            # print(f"\n[STREAM] 📡 EVENT: {event_type}")
                            pass

async def poll_advisories():
    """Periodically check for active advisories."""
    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(f"{API_BASE}/advisories/active")
                if resp.status_code == 200:
                    data = resp.json()
                    terminal = data.get("terminal", [])
                    integrity = data.get("integrity", [])
                    
                    if terminal:
                        print(f"\n[ADVISORY] 🚨 TERMINAL ALERT: {len(terminal)} active")
                        for a in terminal:
                            print(f"   - {a.get('type')}: {a.get('severity')}")
                            
                    if integrity:
                        print(f"\n[ADVISORY] ⚖️ INTEGRITY ALERT: {len(integrity)} active")
                        for a in integrity:
                            print(f"   - {a.get('type')}: {a.get('severity')}")
            except Exception as e:
                logger.error(f"Polling error: {e}")
                
            await asyncio.sleep(5)

async def control_sim():
    """Send control commands to demonstrate API control."""
    async with httpx.AsyncClient() as client:
        await asyncio.sleep(10)
        print("\n[CONTROL] ⏸️ PAUSING SIMULATION via API...")
        await client.post(f"{API_BASE}/sim/control", json={"action": "PAUSE"})
        
        await asyncio.sleep(5)
        print("\n[CONTROL] ▶️ RESUMING SIMULATION via API...")
        await client.post(f"{API_BASE}/sim/control", json={"action": "RESUME"})

async def main():
    # Verify server is up
    logger.info("Waiting for API server...")
    async with httpx.AsyncClient() as client:
        for _ in range(10):
            try:
                await client.get(f"{API_BASE}/governance/status")
                logger.info("API Server Online!")
                break
            except:
                await asyncio.sleep(2)
        else:
            logger.error("API Server failed to start.")
            return

    # Run tasks concurrently
    await asyncio.gather(
        monitor_stream(),
        poll_advisories(),
        control_sim()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Demo stopped.")
