
import sqlite3
import os
from pathlib import Path

def init_bms_database():
    db_path = Path("e:/Automation/agent_commercial/data/arvis_bms.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"🛠️ Initializing BMS Database at {db_path}...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Equipment table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS equipment (
        equipment_id TEXT PRIMARY KEY,
        name TEXT,
        equipment_type TEXT,
        status TEXT DEFAULT 'unknown',
        location TEXT,
        runtime_hours REAL DEFAULT 0,
        efficiency REAL,
        last_maintenance TEXT,
        parent_equipment_id TEXT,
        metadata TEXT,
        updated_at TEXT
    )
    """)
    
    # 2. Data Points table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS data_points (
        point_id TEXT,
        equipment_id TEXT,
        value REAL,
        unit TEXT,
        quality TEXT DEFAULT 'good',
        timestamp TEXT,
        PRIMARY KEY (point_id, timestamp)
    )
    """)
    
    # 3. Alarms table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alarms (
        alarm_id TEXT PRIMARY KEY,
        equipment_id TEXT,
        source_point_id TEXT,
        message TEXT,
        severity TEXT,
        state TEXT DEFAULT 'active',
        triggered_at TEXT,
        acknowledged_at TEXT,
        acknowledged_by TEXT,
        resolved_at TEXT,
        cluster_id TEXT,
        metadata TEXT
    )
    """)
    
    # 4. Energy Readings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS energy_readings (
        meter_id TEXT,
        value REAL,
        unit TEXT DEFAULT 'kW',
        outdoor_temp REAL,
        occupancy REAL,
        timestamp TEXT,
        PRIMARY KEY (meter_id, timestamp)
    )
    """)
    
    # 5. Zones table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS zones (
        zone_id TEXT PRIMARY KEY,
        name TEXT,
        floor TEXT,
        building TEXT,
        co2_point_id TEXT,
        vav_point_id TEXT,
        lighting_point_id TEXT,
        return_air_point_id TEXT,
        schedule_id TEXT,
        load_kw REAL DEFAULT 2.0,
        metadata TEXT
    )
    """)
    
    # 6. Work Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        work_order_id TEXT PRIMARY KEY,
        equipment_id TEXT,
        task_type TEXT,
        status TEXT DEFAULT 'open',
        pre_snapshot TEXT,
        post_snapshot TEXT,
        opened_at TEXT,
        closed_at TEXT,
        verification_result TEXT
    )
    """)
    
    # 7. GSAS Scores table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gsas_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id TEXT,
        overall_score REAL,
        certification_level TEXT,
        category_scores TEXT,
        timestamp TEXT
    )
    """)
    
    # 8. Audit Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        timestamp REAL,
        method TEXT,
        path TEXT,
        status INTEGER,
        user TEXT,
        ip TEXT,
        latency_ms REAL
    )
    """)

    # 9. Fleet Metrics (from fleet_intelligence.py)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fleet_metrics (
        building_id TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL,
        timestamp TEXT,
        PRIMARY KEY (building_id, metric_name)
    )
    """)

    # 10. Fleet Insights (from fleet_intelligence.py)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fleet_insights (
        insight_id TEXT PRIMARY KEY,
        source_building TEXT NOT NULL,
        insight_type TEXT,
        title TEXT,
        description TEXT,
        conditions TEXT,
        impact TEXT,
        confidence REAL,
        applicable_buildings TEXT,
        created_at TEXT
    )
    """)
    
    conn.commit()
    conn.close()
    print("✅ BMS Database Schema applied successfully.")

if __name__ == "__main__":
    init_bms_database()
