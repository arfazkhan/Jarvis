
import os
import shutil
from pathlib import Path

def deep_reset():
    paths_to_delete = [
        "agent_commercial/data/arvis_bms.db",
        "agent_commercial/data/arvis_bms.db-wal",
        "agent_commercial/data/arvis_bms.db-shm",
        "agent_bms/data/advisory.db",
        "agent_bms/data/advisory.db-wal",
        "agent_bms/data/advisory.db-shm",
        "agent_commercial/data/patterns/patterns_db",
        "data/state.json",
        "data/memories/observations.db",
        "data/memories/conversations.db"
    ]
    
    base_dir = Path("e:/Automation")
    
    print("🚀 Starting Deep Reset...")
    
    for relative_path in paths_to_delete:
        full_path = base_dir / relative_path
        if full_path.exists():
            try:
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                    print(f"✅ Deleted directory: {relative_path}")
                else:
                    os.remove(full_path)
                    print(f"✅ Deleted file: {relative_path}")
            except Exception as e:
                print(f"❌ Failed to delete {relative_path}: {e}")
        else:
            print(f"ℹ️ Skipping {relative_path} (not found)")

    print("\n✨ System is now in a 'Clean Slate' state.")

if __name__ == "__main__":
    deep_reset()
