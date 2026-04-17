import asyncio
import httpx
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8000/api/v1"

class ColoredLogger:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"

    @staticmethod
    def monitor(msg):
        print(f"{ColoredLogger.BLUE}[MONITOR]{ColoredLogger.END} {msg}")

    @staticmethod
    def chat(msg):
        print(f"{ColoredLogger.GREEN}[CHAT]{ColoredLogger.END} {msg}")

    @staticmethod
    def system(msg):
        print(f"{ColoredLogger.YELLOW}[*]{ColoredLogger.END} {msg}")

async def listen_to_channel(channel_name: str, duration: int, results: list):
    url = f"{BASE_URL}/stream/{channel_name}"
    ColoredLogger.system(f"Connecting to {url}...")
    
    try:
        # No timeout for reading the stream
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    ColoredLogger.system(f"Error connecting to {channel_name}: HTTP {response.status_code}")
                    return

                start_time = time.time()
                async for line in response.aiter_lines():
                    if time.time() - start_time > duration:
                        break
                    
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        if payload:
                            try:
                                data = json.loads(payload)
                                results.append(data)
                                if channel_name == "monitor":
                                    ColoredLogger.monitor(f"Received: {data}")
                                else:
                                    ColoredLogger.chat(f"Received: {data}")
                            except:
                                pass
    except Exception as e:
        ColoredLogger.system(f"Stream {channel_name} Exception: {type(e).__name__}")

async def run_scenario():
    monitor_results = []
    chat_results = []
    
    ColoredLogger.system("Starting Dual Stream Test Scenario (60s)")
    
    # 1. Ensure Demo is running
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{BASE_URL}/demo/control", json={"action": "start"}, timeout=5.0)
            ColoredLogger.system("Demo loop active.")
        except:
            ColoredLogger.system("Demo loop already active or failed to respond (ignoring).")

    # 2. Start listeners
    duration = 50
    m_task = asyncio.create_task(listen_to_channel("monitor", duration, monitor_results))
    c_task = asyncio.create_task(listen_to_channel("chat", duration, chat_results))
    
    # 3. Wait for ambient events to start rolling in
    await asyncio.sleep(5)
    
    # 4. Trigger Interactive Chat
    ColoredLogger.system("Sending user message...")
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{BASE_URL}/chat", 
                json={"query": "Summary of current building efficiency?", "session_id": "isolation_test"},
                timeout=30.0
            )
            ColoredLogger.system("Chat request completed.")
        except Exception as e:
            ColoredLogger.system(f"Chat request failed: {e}")

    # 5. Wait for finish
    await asyncio.gather(m_task, c_task)
    
    # 6. Verification
    print("\n" + "="*50)
    print("ANALYSIS")
    print("="*50)
    
    chat_keywords = ["task_list", "Swarm", "initializing"]
    monitor_keywords = ["telemetry", "ambient", "day", "simulation"]
    
    failed = False
    for e in monitor_results:
        s = str(e)
        if any(kw in s for kw in chat_keywords):
            print(f"[!] BLEED DETECTED: Chat event data found in MONITOR stream.")
            failed = True
            
    for e in chat_results:
        s = str(e)
        if any(kw in s for kw in monitor_keywords):
            if "Connected" not in s:
                print(f"[!] BLEED DETECTED: Monitor event data found in CHAT stream.")
                failed = True

    if not failed and len(chat_results) > 1 and len(monitor_results) > 1:
        print(f"\n[✅] SUCCESS: ISO-9001 Grade Stream Separation Confirmed.")
        print(f"    - Monitor Channel: {len(monitor_results)} events")
        print(f"    - Chat Channel:    {len(chat_results)} events")
    else:
        print(f"\n[❌] TEST INCONCLUSIVE OR FAILED.")
        print(f"    - Monitor events: {len(monitor_results)}")
        print(f"    - Chat events:    {len(chat_results)}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_scenario())
