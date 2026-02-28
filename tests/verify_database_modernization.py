import sqlite3
import os
import sys

def check_wal(db_path):
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        
        if mode.lower() == "wal":
            print(f"✅ WAL Mode ACTIVE: {db_path}")
            return True
        else:
            print(f"❌ WAL Mode INACTIVE ({mode}): {db_path}")
            return False
    except Exception as e:
        print(f"❌ Error checking {db_path}: {e}")
        return False

if __name__ == "__main__":
    dbs = [
        "agent_commercial/data/arvis_bms.db",
        "agent_bms/data/advisory.db",
        "data/memories/observations.db"
    ]
    
    # Also check preferences.db in current dir as per PreferenceStore
    if os.path.exists("preferences.db"):
        dbs.append("preferences.db")
        
    print("\n" + "="*60)
    print("VERIFYING DATABASE CONCURRENCY (WAL MODE)")
    print("="*60)
    
    # Trigger database initializers to ensure PRAGMAs are run
    sys.path.append(".")
    try:
        from agent_commercial.database import get_database
        from agent_advisory.database import AdvisoryDatabase
        from arvis_core.memory.observation_store import ObservationStore
        
        get_database()
        AdvisoryDatabase()
        ObservationStore()
    except Exception as e:
        print(f"Note: Error during pre-init (might be ok if verify script runs separately): {e}")

    results = [check_wal(db) for db in dbs]
    
    if all(results):
        print("\n" + "="*60)
        print("PHASE 1 VERIFICATION SUCCESSFUL")
        print("="*60)
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("PHASE 1 VERIFICATION FAILED")
        print("="*60)
        sys.exit(1)
