import asyncio
import os
import sys
from datetime import datetime

# Add root to sys.path
sys.path.append(".")

from agent_commercial.database import get_database

async def test_async_operations():
    db = get_database()
    print("Testing async save_data_point...")
    await db.save_data_point("TEST/POINT", 42.0, "units")
    
    print("Testing async get_point_history...")
    history = await db.get_point_history("TEST/POINT", hours=1)
    if history and history[0]["value"] == 42.0:
        print("✅ Async history retrieval successful")
    else:
        print("❌ Async history retrieval failed")
        
    print("Testing batch operation...")
    points = [
        {"point_id": f"TEST/BATCH_{i}", "value": float(i)} for i in range(10)
    ]
    await db.save_data_points_batch(points)
    print("✅ Async batch save successful")
    
    # Verify WAL mode again
    print("Verifying WAL mode persistence...")
    import sqlite3
    conn = sqlite3.connect("agent_commercial/data/arvis_bms.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    conn.close()
    if mode.lower() == "wal":
        print(f"✅ WAL mode confirmed: {mode}")
    else:
        print(f"❌ WAL mode detection failed: {mode}")

if __name__ == "__main__":
    asyncio.run(test_async_operations())
