"""
Database Layer for ARVIS Ops Copilot
=====================================

SQLite persistence for BMS state, alarms, and energy readings.
Uses SQLAlchemy with async support for non-blocking I/O.

This ensures data survives restarts and enables historical analysis.
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# Use aiosqlite for non-blocking I/O
import sqlite3
import aiosqlite
import json
import asyncio

logger = logging.getLogger("arvis.bms.database")

# Default database path.
# Honors ARVIS_DB_PATH env var so test harnesses (e.g. marina_prove_it.py
# with --isolated-db) can redirect every BMSDatabase consumer to a per-run
# file without code changes. skillbook.py and other modules that compute
# their own path against this directory also benefit.
import os as _os
_env_db = _os.getenv("ARVIS_DB_PATH", "").strip()
if _env_db:
    DEFAULT_DB_PATH = Path(_env_db)
else:
    DEFAULT_DB_PATH = Path(__file__).parent / "data" / "arvis_bms.db"

def get_sync_db(db_path: Any) -> sqlite3.Connection:
    """Central factory for synchronous SQLite connections with WAL mode and busy timeout."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception as e:
        logger.warning(f"Failed to configure sync SQLite connection for {db_path}: {e}")
    return conn


async def get_async_db(db_path: Any) -> aiosqlite.Connection:
    """Central factory for asynchronous SQLite connections with WAL mode and busy timeout."""
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute("PRAGMA busy_timeout=30000")
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
    except Exception as e:
        logger.warning(f"Failed to configure async SQLite connection for {db_path}: {e}")
    return conn


class BMSDatabase:
    """
    SQLite persistence layer for BMS data.
    
    Stores:
    - Equipment registry
    - Data point history
    - Alarms (active and historical)
    - Energy readings
    - GSAS scores
    
    Usage:
        >>> db = BMSDatabase()
        >>> db.save_data_point("CH-01/CHWST", 7.2, "°C")
        >>> history = db.get_point_history("CH-01/CHWST", hours=24)
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._async_conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        
        logger.info(f"BMSDatabase initialized: {self.db_path}")

    async def close(self) -> None:
        """Close the database connection and cleanup resources"""
        async with self._lock:
            if self._async_conn:
                logger.info(f"Closing async database connection to: {self.db_path}")
                try:
                    await self._async_conn.close()
                except Exception as e:
                    logger.error(f"Error closing database: {e}")
                finally:
                    self._async_conn = None

    async def _get_async_connection(self) -> aiosqlite.Connection:
        """Get or create asynchronous database connection with WAL mode enabled"""
        async with self._lock:
            if self._async_conn is None:
                logger.info(f"Establishing NEW async connection to: {self.db_path}")
                self._async_conn = await aiosqlite.connect(str(self.db_path))
                self._async_conn.row_factory = aiosqlite.Row
                
                # Enable WAL mode for high concurrency
                try:
                    # 10s timeout — Marina harness fires ~62k background point-persist
                    # tasks per phase via state-engine callback. Reduced to 10000ms per instructions.
                    await self._async_conn.execute("PRAGMA busy_timeout=60000")
                    await self._async_conn.execute("PRAGMA journal_mode=WAL")
                    await self._async_conn.execute("PRAGMA synchronous=NORMAL")
                    await self._async_conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
                    await self._async_conn.execute("PRAGMA wal_autocheckpoint=1000")
                    
                    # Ensure schema exists (Automatic Initialization)
                    await self._init_schema(self._async_conn)
                    
                except Exception as e:
                    logger.error(f"❌ Failed to initialize database in async: {e}")
                    # If init fails, reset connection so next call tries again
                    try:
                        await self._async_conn.close()
                    except:
                        pass
                    self._async_conn = None
                    raise e # Propagate error
                    
            return self._async_conn

    @__import__('contextlib').asynccontextmanager
    async def _execute(self, query: str, params: tuple = ()):
        """Execute a query and yield the cursor (async context manager)"""
        query_upper = query.strip().upper()
        is_write = any(query_upper.startswith(w) for w in ["INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "PRAGMA"])
        
        if is_write:
            async with self._write_lock:
                conn = await self._get_async_connection()
                async with conn.execute(query, params) as cursor:
                    yield cursor
        else:
            conn = await self._get_async_connection()
            async with conn.execute(query, params) as cursor:
                yield cursor

    async def _init_schema(self, conn: aiosqlite.Connection) -> None:
        """Initialize database tables if they don't exist"""
        logger.info("🛠️ Verifying database schema...")
        # Get list of existing tables
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            rows = await cursor.fetchall()
            existing_tables = [row[0] for row in rows]
            logger.info(f"Existing tables: {existing_tables}")

        # 1. Equipment table
        if 'equipment' not in existing_tables:
            logger.info("Creating table: equipment")
            await conn.execute("""
            CREATE TABLE equipment (
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
        if 'data_points' not in existing_tables:
            logger.info("Creating table: data_points")
            await conn.execute("""
            CREATE TABLE data_points (
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
        if 'alarms' not in existing_tables:
            logger.info("Creating table: alarms")
            await conn.execute("""
            CREATE TABLE alarms (
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
        if 'energy_readings' not in existing_tables:
            logger.info("Creating table: energy_readings")
            await conn.execute("""
            CREATE TABLE energy_readings (
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
        if 'zones' not in existing_tables:
            logger.info("Creating table: zones")
            await conn.execute("""
            CREATE TABLE zones (
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
        if 'work_orders' not in existing_tables:
            logger.info("Creating table: work_orders")
            await conn.execute("""
            CREATE TABLE work_orders (
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
        if 'gsas_scores' not in existing_tables:
            logger.info("Creating table: gsas_scores")
            await conn.execute("""
            CREATE TABLE gsas_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id TEXT,
                overall_score REAL,
                certification_level TEXT,
                category_scores TEXT,
                timestamp TEXT
            )
            """)
        
        # 8. Audit Logs table
        if 'audit_logs' not in existing_tables:
            logger.info("Creating table: audit_logs")
            await conn.execute("""
            CREATE TABLE audit_logs (
                timestamp REAL,
                method TEXT,
                path TEXT,
                status INTEGER,
                user TEXT,
                ip TEXT,
                latency_ms REAL
            )
            """)

        # 9. Fleet Metrics
        if 'fleet_metrics' not in existing_tables:
            logger.info("Creating table: fleet_metrics")
            await conn.execute("""
            CREATE TABLE fleet_metrics (
                building_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                timestamp TEXT,
                PRIMARY KEY (building_id, metric_name)
            )
            """)

        # 10. Fleet Insights
        if 'fleet_insights' not in existing_tables:
            logger.info("Creating table: fleet_insights")
            await conn.execute("""
            CREATE TABLE fleet_insights (
                insight_id TEXT PRIMARY KEY,
                building_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL,
                status TEXT DEFAULT 'active',
                timestamp TEXT
            )
            """)

        # 11. Chat Sessions
        if 'chat_sessions' not in existing_tables:
            logger.info("Creating table: chat_sessions")
            await conn.execute("""
            CREATE TABLE chat_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)

        # 12. Chat Messages
        if 'chat_messages' not in existing_tables:
            logger.info("Creating table: chat_messages")
            await conn.execute("""
            CREATE TABLE chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT,
                FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id)
            )
            """)
            
            # Create indexes for fast message lookup by session
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages(session_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_sess_updated ON chat_sessions(updated_at DESC)")

        # 13. Operator Feedback (Learning Signal)
        if 'operator_feedback' not in existing_tables:
            logger.info("Creating table: operator_feedback")
            await conn.execute("""
            CREATE TABLE operator_feedback (
                feedback_id TEXT PRIMARY KEY,
                session_id TEXT,
                equipment_id TEXT,
                recommendation_id TEXT,
                feedback_type TEXT,
                rating INTEGER,
                comment TEXT,
                timestamp TEXT,
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_equipment ON operator_feedback(equipment_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON operator_feedback(timestamp DESC)")

        # 14. Trust Metrics
        if 'trust_metrics' not in existing_tables:
            logger.info("Creating table: trust_metrics")
            await conn.execute("""
            CREATE TABLE trust_metrics (
                metric_id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                building_id TEXT,
                follow_through_rate REAL DEFAULT 0.0,
                avg_response_time_seconds REAL,
                total_recommendations INTEGER DEFAULT 0,
                accepted_recommendations INTEGER DEFAULT 0,
                rejected_recommendations INTEGER DEFAULT 0,
                silence_rate REAL DEFAULT 0.0,
                last_updated TEXT,
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trust_operator ON trust_metrics(operator_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trust_building ON trust_metrics(building_id)")

        # 15. Recommendations
        if 'recommendations' not in existing_tables:
            logger.info("Creating table: recommendations")
            await conn.execute("""
            CREATE TABLE recommendations (
                recommendation_id TEXT PRIMARY KEY,
                equipment_id TEXT,
                domain TEXT,
                recommendation_type TEXT,
                priority TEXT,
                title TEXT,
                description TEXT,
                confidence REAL,
                evidence TEXT,
                action TEXT,
                created_at TEXT,
                accepted_at TEXT,
                rejected_at TEXT,
                operator_id TEXT,
                status TEXT DEFAULT 'pending',
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_equipment ON recommendations(equipment_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_created ON recommendations(created_at DESC)")

        # 16. Briefings
        if 'briefings' not in existing_tables:
            logger.info("Creating table: briefings")
            await conn.execute("""
            CREATE TABLE briefings (
                briefing_id TEXT PRIMARY KEY,
                period TEXT,
                building_id TEXT,
                title TEXT,
                critical_items TEXT,
                attention_items TEXT,
                info_items TEXT,
                wins_items TEXT,
                generated_at TEXT,
                operator_id TEXT,
                operator_response TEXT,
                responded_at TEXT,
                status TEXT DEFAULT 'pending',
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_brief_building ON briefings(building_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_brief_period ON briefings(period)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_brief_generated ON briefings(generated_at DESC)")

        
        # 17. System Config (key-value store for pilot day, feature flags, etc.)
        if 'system_config' not in existing_tables:
            logger.info("Creating table: system_config")
            await conn.execute("""
            CREATE TABLE system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            )
            """)

        # 18. Suggested Actions (Learning Engine feedback loop)
        if 'suggested_actions' not in existing_tables:
            logger.info("Creating table: suggested_actions")
            await conn.execute("""
            CREATE TABLE suggested_actions (
                suggestion_id TEXT PRIMARY KEY,
                type TEXT,
                target TEXT,
                action TEXT,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                applied_at TEXT,
                outcome TEXT,
                outcome_metrics TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_suggested_status ON suggested_actions(status)")

        # 19. State Snapshots (warm-start persistence)
        if 'state_snapshots' not in existing_tables:
            logger.info("Creating table: state_snapshots")
            await conn.execute("""
            CREATE TABLE state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)

        # 20. Prediction Baselines (cognitive engine warm-start)
        if 'prediction_baselines' not in existing_tables:
            logger.info("Creating table: prediction_baselines")
            await conn.execute("""
            CREATE TABLE prediction_baselines (
                metric TEXT NOT NULL,
                hour INTEGER NOT NULL,
                value REAL NOT NULL,
                samples INTEGER DEFAULT 1,
                updated_at TEXT,
                PRIMARY KEY (metric, hour)
            )
            """)

        # 21. Recommendation Outcomes (feedback loop — Track 2)
        if 'recommendation_outcomes' not in existing_tables:
            logger.info("Creating table: recommendation_outcomes")
            await conn.execute("""
            CREATE TABLE recommendation_outcomes (
                outcome_id          TEXT PRIMARY KEY,
                recommendation_id   TEXT NOT NULL,
                session_id          TEXT,
                action_type         TEXT,
                baseline_kwh        REAL,
                predicted_kwh_delta REAL,
                actual_kwh_delta    REAL,
                predicted_score     REAL,
                actual_score        REAL,
                confidence          REAL DEFAULT 0.7,
                outcome_status      TEXT DEFAULT 'pending',
                accuracy            REAL,
                measured_at         TEXT,
                created_at          TEXT,
                notes               TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_status ON recommendation_outcomes(outcome_status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_rec ON recommendation_outcomes(recommendation_id)")

        # 22. Distilled Rules (replaces swarm_nodes.py source rewriting — Track 2)
        if 'distilled_rules' not in existing_tables:
            logger.info("Creating table: distilled_rules")
            await conn.execute("""
            CREATE TABLE distilled_rules (
                rule_id     TEXT PRIMARY KEY,
                agent_name  TEXT NOT NULL,
                rule_text   TEXT NOT NULL,
                confidence  REAL DEFAULT 0.0,
                veto_count  INTEGER DEFAULT 0,
                active      INTEGER DEFAULT 1,
                created_at  TEXT,
                updated_at  TEXT,
                source_evidence_id TEXT,
                expires_at  TEXT,
                hit_count   INTEGER DEFAULT 0
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rules_agent ON distilled_rules(agent_name, active)")
        else:
            # Migration: add columns if table exists but lacks new fields
            try:
                await conn.execute("ALTER TABLE distilled_rules ADD COLUMN source_evidence_id TEXT")
            except Exception:
                pass
            try:
                await conn.execute("ALTER TABLE distilled_rules ADD COLUMN expires_at TEXT")
            except Exception:
                pass
            try:
                await conn.execute("ALTER TABLE distilled_rules ADD COLUMN hit_count INTEGER DEFAULT 0")
            except Exception:
                pass

        # 23. Investigation Plans — T2 Episodic memory archive
        if 'investigation_plans' not in existing_tables:
            logger.info("Creating table: investigation_plans")
            await conn.execute("""
            CREATE TABLE investigation_plans (
                plan_id         TEXT PRIMARY KEY,
                query           TEXT NOT NULL,
                building_id     TEXT DEFAULT '',
                status          TEXT DEFAULT 'active',
                progress        REAL DEFAULT 0.0,
                evidence_count  INTEGER DEFAULT 0,
                query_embedding BLOB,
                plan_json       TEXT,
                created_at      TEXT NOT NULL,
                completed_at    TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_building ON investigation_plans(building_id, created_at)")

        if 'plan_tasks' not in existing_tables:
            logger.info("Creating table: plan_tasks")
            await conn.execute("""
            CREATE TABLE plan_tasks (
                task_id         TEXT PRIMARY KEY,
                plan_id         TEXT NOT NULL,
                goal            TEXT,
                tool_hint       TEXT,
                status          TEXT DEFAULT 'pending',
                expected_outcome TEXT,
                evidence_ids    TEXT DEFAULT '[]',
                attempts        INTEGER DEFAULT 0,
                assigned_node   TEXT,
                FOREIGN KEY (plan_id) REFERENCES investigation_plans(plan_id)
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_plan ON plan_tasks(plan_id)")

        if 'audit_spans' not in existing_tables:
            logger.info("Creating table: audit_spans")
            await conn.execute("""
            CREATE TABLE audit_spans (
                span_id         TEXT PRIMARY KEY,
                plan_id         TEXT NOT NULL,
                task_id         TEXT DEFAULT '',
                node_name       TEXT DEFAULT '',
                action          TEXT,
                tool_name       TEXT,
                tool_args       TEXT,
                evidence_id     TEXT,
                verdict         TEXT,
                duration_ms     REAL DEFAULT 0.0,
                timestamp       TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES investigation_plans(plan_id)
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_plan ON audit_spans(plan_id)")

        if 'plan_evidence' not in existing_tables:
            logger.info("Creating table: plan_evidence")
            await conn.execute("""
            CREATE TABLE plan_evidence (
                evidence_id     TEXT PRIMARY KEY,
                plan_id         TEXT NOT NULL,
                source_tool     TEXT,
                node_name       TEXT DEFAULT '',
                summary         TEXT,
                is_ml_fallback  INTEGER DEFAULT 0,
                model_id        TEXT,
                drift_score     REAL,
                call_sig        TEXT,
                evidence_json   TEXT,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES investigation_plans(plan_id)
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_plan ON plan_evidence(plan_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_tool ON plan_evidence(source_tool)")

        if 'conversation_turns' not in existing_tables:
            logger.info("Creating table: conversation_turns")
            await conn.execute("""
            CREATE TABLE conversation_turns (
                turn_id         TEXT PRIMARY KEY,
                operator_id     TEXT NOT NULL,
                building_id     TEXT DEFAULT '',
                role            TEXT NOT NULL,
                content         TEXT,
                is_summary      INTEGER DEFAULT 0,
                summary_range   TEXT,
                created_at      TEXT NOT NULL
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_operator ON conversation_turns(operator_id, building_id, created_at)")

        # 25. LLM Usage Metering — per-call Bedrock cost tracking
        if 'llm_usage' not in existing_tables:
            logger.info("Creating table: llm_usage")
            await conn.execute("""
            CREATE TABLE llm_usage (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id         TEXT DEFAULT '',
                node_name       TEXT DEFAULT '',
                channel         TEXT DEFAULT '',
                model_id        TEXT NOT NULL,
                input_tokens    INTEGER NOT NULL,
                output_tokens   INTEGER NOT NULL,
                cost_usd        REAL NOT NULL,
                timestamp       TEXT NOT NULL
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_plan ON llm_usage(plan_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON llm_usage(timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage(model_id)")

        # Add cost columns to investigation_plans (safe for existing DBs)
        try:
            await conn.execute("ALTER TABLE investigation_plans ADD COLUMN total_llm_cost_usd REAL DEFAULT 0.0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE investigation_plans ADD COLUMN total_llm_tokens INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE investigation_plans ADD COLUMN total_tool_cost_usd REAL DEFAULT 0.0")
        except Exception:
            pass

        # 27. BFT Vote Archive — persists consensus outcomes for judge introspection
        if 'bft_votes' not in existing_tables:
            logger.info("Creating table: bft_votes")
            await conn.execute("""
            CREATE TABLE bft_votes (
                vote_id         TEXT PRIMARY KEY,
                round_id        TEXT NOT NULL,
                plan_id         TEXT DEFAULT '',
                agent_name      TEXT NOT NULL,
                vote            TEXT NOT NULL,
                confidence      REAL DEFAULT 0.5,
                conditions      TEXT DEFAULT '[]',
                reasoning       TEXT,
                proposal        TEXT,
                proposer_name   TEXT,
                timestamp       TEXT NOT NULL
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bft_votes_round ON bft_votes(round_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bft_votes_plan ON bft_votes(plan_id)")

        # 28. BFT Abstention Log — nodes that failed to vote
        if 'bft_abstentions' not in existing_tables:
            logger.info("Creating table: bft_abstentions")
            await conn.execute("""
            CREATE TABLE bft_abstentions (
                abstention_id   TEXT PRIMARY KEY,
                round_id        TEXT NOT NULL,
                plan_id         TEXT DEFAULT '',
                agent_name      TEXT NOT NULL,
                reason          TEXT NOT NULL,
                timestamp       TEXT NOT NULL
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bft_abstentions_round ON bft_abstentions(round_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bft_abstentions_plan ON bft_abstentions(plan_id)")

        # 29. Violation Ledger — physics violations persisted from simulator
        if 'violation_ledger' not in existing_tables:
            logger.info("Creating table: violation_ledger")
            await conn.execute("""
            CREATE TABLE violation_ledger (
                violation_id    TEXT PRIMARY KEY,
                plan_id         TEXT DEFAULT '',
                advisory_text   TEXT,
                code            TEXT NOT NULL,
                severity        TEXT NOT NULL,
                description     TEXT,
                expected_value  REAL,
                cited_value     REAL,
                component       TEXT DEFAULT '',
                timestamp       TEXT NOT NULL
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_plan ON violation_ledger(plan_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_code ON violation_ledger(code)")

        # 30. Judgment Ledger — agentic judge audit trail
        if 'judgment_ledger' not in existing_tables:
            logger.info("Creating table: judgment_ledger")
            await conn.execute("""
            CREATE TABLE judgment_ledger (
                judgment_id     TEXT PRIMARY KEY,
                run_id          TEXT NOT NULL,
                phase           TEXT NOT NULL,
                scenario        TEXT NOT NULL,
                dimension_id    TEXT NOT NULL,
                score           REAL NOT NULL,
                reasoning       TEXT,
                evidence_chain  TEXT DEFAULT '[]',
                tool_calls_used INTEGER DEFAULT 0,
                judge_model_id  TEXT,
                wall_time_ms    REAL DEFAULT 0.0,
                timestamp       TEXT NOT NULL
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_judgment_run ON judgment_ledger(run_id, phase)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_judgment_dimension ON judgment_ledger(dimension_id)")

        # 31. Calibration Schema tables
        if 'point_baselines' not in existing_tables:
            logger.info("Creating table: point_baselines")
            await conn.execute("""
            CREATE TABLE point_baselines (
                building_id      TEXT DEFAULT 'default' NOT NULL,
                point_id         TEXT NOT NULL,
                equipment_id     TEXT NOT NULL,
                equipment_type   TEXT NOT NULL,
                point_type       TEXT NOT NULL,
                location         TEXT,
                date             TEXT NOT NULL,
                sample_count     INTEGER NOT NULL,
                mean_val         REAL NOT NULL,
                std_val          REAL NOT NULL,
                median_val       REAL NOT NULL,
                mad_val          REAL NOT NULL,
                p05_val          REAL NOT NULL,
                p95_val          REAL NOT NULL,
                min_val          REAL NOT NULL,
                max_val          REAL NOT NULL,
                alarm_duration_s INTEGER DEFAULT 0,
                is_healthy       INTEGER DEFAULT 1,
                PRIMARY KEY (building_id, point_id, date)
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pb_eqtype_date ON point_baselines(building_id, equipment_type, point_type, date)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pb_eqid_date ON point_baselines(building_id, equipment_id, date)")

        if 'point_calibrations' not in existing_tables:
            logger.info("Creating table: point_calibrations")
            await conn.execute("""
            CREATE TABLE point_calibrations (
                building_id          TEXT DEFAULT 'default' NOT NULL,
                scope_key            TEXT NOT NULL,
                scope_level          TEXT NOT NULL,
                point_type           TEXT NOT NULL,
                equipment_type       TEXT,
                calibrated_floor     REAL NOT NULL,
                calibrated_z_thresh  REAL NOT NULL,
                prev_floor           REAL,
                prev_z_thresh        REAL,
                sample_size_days     INTEGER NOT NULL,
                rejection_rate_7d    REAL,
                fp_target            REAL DEFAULT 0.001,
                promoted             INTEGER DEFAULT 0,
                change_reason        TEXT,
                last_calibrated_at   TEXT NOT NULL,
                last_promoted_at     TEXT,
                next_due_at          TEXT,
                PRIMARY KEY (building_id, scope_key)
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_eqtype ON point_calibrations(building_id, equipment_type, point_type)")

        if 'calibration_runs' not in existing_tables:
            logger.info("Creating table: calibration_runs")
            await conn.execute("""
            CREATE TABLE calibration_runs (
                run_id               TEXT PRIMARY KEY,
                building_id          TEXT DEFAULT 'default' NOT NULL,
                started_at           TEXT NOT NULL,
                finished_at          TEXT,
                trigger_source       TEXT NOT NULL,
                window_days          INTEGER NOT NULL,
                rows_scanned         INTEGER,
                rows_rejected_alarm  INTEGER,
                rows_rejected_hampel INTEGER,
                scopes_updated       INTEGER,
                scopes_rolled_back   INTEGER,
                notes                TEXT
            )
            """)

        await conn.commit()
        logger.info("✅ Database schema verification complete.")


    # ═══════════════════════════════════════════════════════════════════════════
    # EQUIPMENT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_equipment(self, equipment: Dict[str, Any]) -> None:
        """Save or update equipment (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()

            await conn.execute("""
                INSERT OR REPLACE INTO equipment
                (equipment_id, name, equipment_type, status, location, runtime_hours,
                 efficiency, last_maintenance, parent_equipment_id, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                equipment.get("equipment_id"),
                equipment.get("name"),
                equipment.get("equipment_type"),
                equipment.get("status", "unknown"),
                equipment.get("location"),
                equipment.get("runtime_hours", 0),
                equipment.get("efficiency"),
                equipment.get("last_maintenance"),
                equipment.get("parent_equipment_id"),
                json.dumps(equipment.get("metadata", {})),
                datetime.now().isoformat(),
            ))

            await conn.commit()
    
    async def update_equipment_runtime(self, equipment_id: str, hours_delta: float) -> None:
        """Increment runtime_hours for equipment by hours_delta."""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute(
                "UPDATE equipment SET runtime_hours = runtime_hours + ?, updated_at = ? WHERE equipment_id = ?",
                (hours_delta, datetime.now().isoformat(), equipment_id),
            )
            await conn.commit()

    async def get_equipment(self, equipment_id: str) -> Optional[Dict]:
        """Get equipment by ID (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM equipment WHERE equipment_id = ?", (equipment_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                # Convert aiosqlite.Row to dict
                return dict(row)
        return None
    
    async def get_all_equipment(self) -> List[Dict]:
        """Get all equipment (Async)"""
        conn = await self._get_async_connection()

        async with conn.execute("SELECT * FROM equipment ORDER BY equipment_id") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_equipment_runtime(
        self,
        equipment_id: str,
        hours_delta: float = 0.0,
        cycles_delta: int = 0,
    ) -> bool:
        """Increment runtime_hours / start_stop_cycles on equipment (B10)."""
        if not equipment_id:
            return False
        if hours_delta == 0 and cycles_delta == 0:
            return False
        try:
            async with self._write_lock:
                conn = await self._get_async_connection()
                cursor = await conn.execute(
                    """
                    UPDATE equipment
                    SET runtime_hours = COALESCE(runtime_hours, 0) + ?,
                        start_stop_cycles = COALESCE(start_stop_cycles, 0) + ?
                    WHERE equipment_id = ?
                    """,
                    (float(hours_delta), int(cycles_delta), equipment_id),
                )
                await conn.commit()
                return (cursor.rowcount or 0) > 0
        except Exception as e:
            logger.debug(f"[DB] update_equipment_runtime failed for {equipment_id}: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════════
    # DATA POINT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_data_point(
        self,
        point_id: str,
        value: float,
        unit: str = "",
        equipment_id: str = None,
        quality: str = "good",
        timestamp: datetime = None
    ) -> None:
        """Save a data point reading (Async).

        Uses INSERT OR REPLACE on the (point_id, timestamp) PK so duplicate
        writes within the same microsecond (common with high-frequency
        emulator ticks or fast phase injection bursts) coalesce silently.

        Also swallows sqlite3.IntegrityError as a belt-and-suspenders guard:
        callers fire-and-forget this as a background asyncio.Task and any
        unhandled exception surfaces as "Task exception was never retrieved"
        in stderr, which is noise — not a correctness problem.
        """
        try:
            async with self._write_lock:
                conn = await self._get_async_connection()

                ts = timestamp if isinstance(timestamp, str) else (timestamp or datetime.now()).isoformat()
                quality_str = quality.value if hasattr(quality, "value") else str(quality)

                await conn.execute("""
                    INSERT OR REPLACE INTO data_points (point_id, equipment_id, value, unit, quality, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (point_id, equipment_id, value, unit, quality_str, ts))

                await conn.commit()
        except sqlite3.IntegrityError as _ie:
            # Duplicate (point_id, timestamp) under WAL contention — discard.
            logger.debug(f"[DB] save_data_point dedupe: {point_id} @ {ts}: {_ie}")
        except Exception as _e:
            logger.debug(f"[DB] save_data_point failed for {point_id}: {_e}")
    
    async def save_data_points_batch(self, points: List[Dict]) -> None:
        """Save multiple data points efficiently (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            
            data = []
            for p in points:
                _q = p.get("quality", "good")
                _q_str = _q.value if hasattr(_q, "value") else str(_q)
                _ts = p.get("timestamp")
                _ts_str = _ts.isoformat() if isinstance(_ts, datetime) else (_ts or datetime.now().isoformat())
                data.append((
                    p.get("point_id"),
                    p.get("equipment_id"),
                    p.get("value"),
                    p.get("unit", ""),
                    _q_str,
                    _ts_str,
                ))
            
            await conn.executemany("""
                INSERT OR REPLACE INTO data_points (point_id, equipment_id, value, unit, quality, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, data)
            
            await conn.commit()
    
    async def get_point_history(
        self, 
        point_id: str, 
        hours: int = 24,
        limit: int = 1000
    ) -> List[Dict]:
        """Get historical values for a point (Async)"""
        conn = await self._get_async_connection()
        
        # Get simulated reference time
        sim_now = datetime.now()
        try:
            async with conn.execute("SELECT MAX(timestamp) FROM data_points") as c:
                row = await c.fetchone()
                if row and row[0]:
                    # Handle possible string formats
                    val_str = str(row[0])
                    if "T" in val_str:
                        sim_now = datetime.fromisoformat(val_str.split(".")[0].split("+")[0])
                    else:
                        sim_now = datetime.fromisoformat(val_str)
        except Exception:
            pass
            
        cutoff = (sim_now - timedelta(hours=hours)).isoformat()
        
        async with conn.execute("""
            SELECT value, unit, quality, timestamp 
            FROM data_points 
            WHERE point_id = ? AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (point_id, cutoff, limit)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
    
    async def get_latest_value(self, point_id: str) -> Optional[Dict]:
        """Get the most recent value for a point (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT value, unit, quality, timestamp 
            FROM data_points 
            WHERE point_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (point_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
            
    async def get_latest_values_batch(self, point_ids: List[str]) -> Dict[str, float]:
        """Get latest values for multiple points (Async)"""
        result = {}
        for point_id in point_ids:
            latest = await self.get_latest_value(point_id)
            if latest:
                result[point_id] = latest["value"]
        return result

    async def get_fleet_insights(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get the latest insights generated across the fleet"""
        query = "SELECT * FROM fleet_insights ORDER BY timestamp DESC LIMIT ?"
        conn = await self._get_async_connection()
        async with conn.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            if rows:
                return [dict(row) for row in rows]
            return []
        
    # ═══════════════════════════════════════════════════════════════════════════
    # CHAT HISTORY COMMANDS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def create_chat_session(self, session_id: str, title: str = "New Conversation") -> Optional[str]:
        """Create a new chat session."""
        now = datetime.now().isoformat()
        query = "INSERT INTO chat_sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)"
        try:
            async with self._write_lock:
                conn = await self._get_async_connection()
                await conn.execute(query, (session_id, title, now, now))
                await conn.commit()
            return session_id
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            return None
            
    async def update_chat_session_timestamp(self, session_id: str) -> None:
        """Update the last activity timestamp for a chat session."""
        now = datetime.now().isoformat()
        try:
            async with self._write_lock:
                conn = await self._get_async_connection()
                await conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
                await conn.commit()
        except Exception as e:
            logger.error(f"Failed to update chat session timestamp: {e}")

    async def add_chat_message(self, session_id: str, message_id: str, role: str, content: str) -> bool:
        """Add a message to a specific chat session."""
        now = datetime.now().isoformat()
        query = "INSERT INTO chat_messages (message_id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)"
        try:
            async with self._write_lock:
                conn = await self._get_async_connection()
                await conn.execute(query, (message_id, session_id, role, content, now))
                await conn.commit()
            await self.update_chat_session_timestamp(session_id)
            return True
        except Exception as e:
            logger.error(f"Failed to add chat message: {e}")
            return False

    async def get_chat_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve a list of recent chat sessions."""
        conn = await self._get_async_connection()
        query = "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?"
        async with conn.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_chat_history(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve messages for a specific session ordered by timestamp."""
        conn = await self._get_async_connection()
        query = "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?"
        async with conn.execute(query, (session_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALARM OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_alarm(self, alarm: Dict[str, Any]) -> None:
        """Save or update an alarm (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()

            await conn.execute("""
                INSERT OR REPLACE INTO alarms
                (alarm_id, equipment_id, source_point_id, message, severity, state,
                 triggered_at, acknowledged_at, acknowledged_by, resolved_at, cluster_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alarm.get("alarm_id"),
                alarm.get("equipment_id"),
                alarm.get("source_point_id"),
                alarm.get("message"),
                alarm.get("severity"),
                alarm.get("state", "active"),
                alarm.get("triggered_at", datetime.now().isoformat()),
                alarm.get("acknowledged_at"),
                alarm.get("acknowledged_by"),
                alarm.get("resolved_at"),
                alarm.get("cluster_id"),
                json.dumps(alarm.get("metadata", {})),
            ))

            await conn.commit()
    
    async def get_active_alarms(self) -> List[Dict]:
        """Get all active alarms (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT * FROM alarms 
            WHERE state IN ('active', 'acknowledged')
            ORDER BY 
                CASE severity 
                    WHEN 'critical' THEN 1 
                    WHEN 'high' THEN 2 
                    WHEN 'medium' THEN 3 
                    WHEN 'low' THEN 4 
                    ELSE 5 
                END,
                triggered_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_alarm_count_by_severity(self) -> Dict[str, int]:
        """Get count of active alarms by severity (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT severity, COUNT(*) as count 
            FROM alarms 
            WHERE state IN ('active', 'acknowledged')
            GROUP BY severity
        """) as cursor:
            rows = await cursor.fetchall()
            return {row["severity"]: row["count"] for row in rows}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ENERGY OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_energy_reading(
        self,
        meter_id: str,
        value: float,
        unit: str = "kW",
        outdoor_temp: float = None,
        occupancy: float = None,
        timestamp: datetime = None
    ) -> None:
        """Save energy meter reading (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            ts = timestamp if isinstance(timestamp, str) else (timestamp or datetime.now()).isoformat()
            await conn.execute("""
                INSERT INTO energy_readings (meter_id, value, unit, outdoor_temp, occupancy, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (meter_id, value, unit, outdoor_temp, occupancy, ts))
            await conn.commit()
    
    async def get_energy_today(self, meter_id: str = None) -> float:
        """Get total energy consumption for today (kWh) (Async)"""
        conn = await self._get_async_connection()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        
        if meter_id:
            query = """
                SELECT AVG(value) as avg_kw, COUNT(*) as readings
                FROM energy_readings 
                WHERE meter_id = ? AND timestamp > ?
            """
            params = (meter_id, today_start)
        else:
            query = """
                SELECT AVG(value) as avg_kw, COUNT(*) as readings
                FROM energy_readings 
                WHERE timestamp > ?
            """
            params = (today_start,)
            
        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row and row["avg_kw"]:
                # Estimate kWh: avg_kw * hours since midnight
                hours = (datetime.now() - datetime.now().replace(hour=0, minute=0, second=0)).seconds / 3600
                return row["avg_kw"] * hours
        return 0.0
    
    async def get_energy_baseline_comparison(self, meter_id: str = None) -> float:
        """Compare today's energy to 7-day baseline (Async)"""
        conn = await self._get_async_connection()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        
        # Get today's average
        if meter_id:
            today_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE meter_id = ? AND timestamp > ?"
            today_params = (meter_id, today_start)
        else:
            today_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE timestamp > ?"
            today_params = (today_start,)
            
        async with conn.execute(today_query, today_params) as cursor:
            today_row = await cursor.fetchone()
            today_avg = today_row["avg_kw"] if today_row and today_row["avg_kw"] else 0
        
        # Get baseline average
        if meter_id:
            base_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE meter_id = ? AND timestamp > ? AND timestamp < ?"
            base_params = (meter_id, week_ago, today_start)
        else:
            base_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE timestamp > ? AND timestamp < ?"
            base_params = (week_ago, today_start)
            
        async with conn.execute(base_query, base_params) as cursor:
            baseline_row = await cursor.fetchone()
            baseline_avg = baseline_row["avg_kw"] if baseline_row and baseline_row["avg_kw"] else 0
        
        if baseline_avg > 0:
            return ((today_avg - baseline_avg) / baseline_avg) * 100
        return 0.0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ZONE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_zone(self, zone: Dict[str, Any]) -> None:
        """Save or update zone configuration (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR REPLACE INTO zones
                (zone_id, name, floor, building, co2_point_id, vav_point_id,
                 lighting_point_id, return_air_point_id, schedule_id, load_kw, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                zone.get("zone_id"),
                zone.get("name"),
                zone.get("floor"),
                zone.get("building"),
                zone.get("co2_point_id"),
                zone.get("vav_point_id"),
                zone.get("lighting_point_id"),
                zone.get("return_air_point_id"),
                zone.get("schedule_id"),
                zone.get("load_kw", 2.0),
                json.dumps(zone.get("metadata", {})),
            ))
            await conn.commit()
    
    async def get_all_zones(self) -> List[Dict]:
        """Get all zone configurations (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM zones ORDER BY building, floor, name") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_zone_with_current_values(self, zone_id: str) -> Optional[Dict]:
        """Get zone config with current sensor values (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM zones WHERE zone_id = ?", (zone_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            
            zone = dict(row)
            
            # Get current sensor values
            if zone.get("co2_point_id"):
                latest = await self.get_latest_value(zone["co2_point_id"])
                zone["co2_ppm"] = latest["value"] if latest else None
            
            if zone.get("vav_point_id"):
                latest = await self.get_latest_value(zone["vav_point_id"])
                zone["vav_damper_pct"] = latest["value"] if latest else None
            
            if zone.get("lighting_point_id"):
                latest = await self.get_latest_value(zone["lighting_point_id"])
                zone["light_status"] = latest["value"] > 0 if latest else None
            
            return zone
    
    # ═══════════════════════════════════════════════════════════════════════════
    # WORK ORDER OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def create_work_order(
        self,
        work_order_id: str,
        equipment_id: str,
        task_type: str,
        pre_snapshot: Dict[str, float]
    ) -> None:
        """Create a work order with pre-maintenance snapshot (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT INTO work_orders (work_order_id, equipment_id, task_type, status, pre_snapshot, opened_at)
            VALUES (?, ?, ?, 'open', ?, ?)
        """, (
            work_order_id,
            equipment_id,
            task_type,
            json.dumps(pre_snapshot),
            datetime.now().isoformat(),
        ))
        
        await conn.commit()
    
    async def close_work_order(
        self,
        work_order_id: str,
        post_snapshot: Dict[str, float],
        verification_result: Dict[str, Any]
    ) -> None:
        """Close work order with post-maintenance data (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            UPDATE work_orders 
            SET status = 'closed', 
                post_snapshot = ?, 
                closed_at = ?,
                verification_result = ?
            WHERE work_order_id = ?
        """, (
            json.dumps(post_snapshot),
            datetime.now().isoformat(),
            json.dumps(verification_result),
            work_order_id,
        ))
        
        await conn.commit()
    
    async def get_work_order(self, work_order_id: str) -> Optional[Dict]:
        """Get work order details (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (work_order_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                wo = dict(row)
                wo["pre_snapshot"] = json.loads(wo.get("pre_snapshot") or "{}")
                wo["post_snapshot"] = json.loads(wo.get("post_snapshot") or "{}")
                wo["verification_result"] = json.loads(wo.get("verification_result") or "{}")
                return wo
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # GSAS OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_gsas_score(
        self,
        building_id: str,
        overall_score: float,
        certification_level: str,
        category_scores: Dict[str, float]
    ) -> None:
        """Save GSAS assessment score (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT INTO gsas_scores (building_id, overall_score, certification_level, category_scores, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (
                building_id,
                overall_score,
                certification_level,
                json.dumps(category_scores),
                datetime.now().isoformat(),
            ))
            await conn.commit()
    
    async def get_latest_gsas_score(self, building_id: str = None) -> Optional[Dict]:
        """Get the most recent GSAS score (Async)"""
        conn = await self._get_async_connection()
        
        if building_id:
            query = """
                SELECT * FROM gsas_scores 
                WHERE building_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """
            params = (building_id,)
        else:
            query = """
                SELECT * FROM gsas_scores 
                ORDER BY timestamp DESC LIMIT 1
            """
            params = ()
        
        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                result["category_scores"] = json.loads(result.get("category_scores") or "{}")
                return result
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAINTENANCE ANALYTICS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def get_equipment_requiring_maintenance(self, days: int = 7) -> List[Dict]:
        """Get equipment with high failure probability or overdue maintenance (Async)"""
        conn = await self._get_async_connection()
        
        overdue_cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        
        async with conn.execute("""
            SELECT * FROM equipment 
            WHERE last_maintenance < ? OR last_maintenance IS NULL
            ORDER BY last_maintenance ASC
        """, (overdue_cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_pending_insights_count(self) -> int:
        """Get count of unacknowledged high-priority alarms (as insights) (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT COUNT(*) as count FROM alarms 
            WHERE state = 'active' AND severity IN ('critical', 'high')
        """) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def cleanup_old_data(self, days: int = 30) -> int:
        """Remove data older than specified days (Async)"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("DELETE FROM data_points WHERE timestamp < ?", (cutoff,))
            await conn.execute("DELETE FROM energy_readings WHERE timestamp < ?", (cutoff,))
            await conn.execute("DELETE FROM alarms WHERE resolved_at < ? AND state = 'resolved'", (cutoff,))
            await conn.commit()
        # Note: rowcount might not be readily available on the connection after commit in aiosqlite,
        # but we usually don't depend on it for logic.
        return 0
    
    async def save_audit_log(
        self,
        user: str,
        method: str,
        path: str,
        status: int,
        ip: str = "unknown",
        latency_ms: float = 0.0
    ) -> None:
        """Save a security audit record (Async)"""
        ts = time.time()
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT INTO audit_logs (timestamp, method, path, status, user, ip, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ts, method, path, status, user, ip, latency_ms))
            await conn.commit()
    
    async def close(self):
        """Close database connections (Async)"""
        async with self._lock:
            if self._async_conn:
                await self._async_conn.close()
                self._async_conn = None

    # ═══════════════════════════════════════════════════════════════════════════
    # ALARM STATE OPERATIONS (for bms_state_engine)
    # ═══════════════════════════════════════════════════════════════════════════

    async def update_alarm_state(
        self,
        alarm_id: str,
        state: str = None,
        acknowledged_by: str = None,
        acknowledged_at: datetime = None,
        resolved_at: datetime = None
    ) -> None:
        """Update alarm state fields (Async)"""
        conn = await self._get_async_connection()
        
        fields = []
        params = []
        if state is not None:
            fields.append("state = ?")
            params.append(state.value if hasattr(state, 'value') else state)
        if acknowledged_by is not None:
            fields.append("acknowledged_by = ?")
            params.append(acknowledged_by)
        if acknowledged_at is not None:
            fields.append("acknowledged_at = ?")
            params.append(acknowledged_at.isoformat() if hasattr(acknowledged_at, 'isoformat') else acknowledged_at)
        if resolved_at is not None:
            fields.append("resolved_at = ?")
            params.append(resolved_at.isoformat() if hasattr(resolved_at, 'isoformat') else resolved_at)
        
        if not fields:
            return
        
        params.append(alarm_id)
        query = f"UPDATE alarms SET {', '.join(fields)} WHERE alarm_id = ?"
        await conn.execute(query, params)
        await conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # OPERATOR FEEDBACK (for trust calibration + learning)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_operator_feedback(self, feedback: Dict[str, Any]) -> None:
        """Save operator feedback on a recommendation (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR REPLACE INTO operator_feedback
                (feedback_id, session_id, equipment_id, recommendation_id, feedback_type,
                 rating, comment, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                feedback.get("feedback_id"),
                feedback.get("session_id"),
                feedback.get("equipment_id"),
                feedback.get("recommendation_id"),
                feedback.get("feedback_type"),
                feedback.get("rating"),
                feedback.get("comment"),
                datetime.now().isoformat(),
                json.dumps(feedback.get("metadata", {})),
            ))
            await conn.commit()

    async def get_operator_feedback(
        self,
        equipment_id: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get operator feedback history (Async)"""
        conn = await self._get_async_connection()
        
        if equipment_id:
            query = """
                SELECT * FROM operator_feedback 
                WHERE equipment_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """
            params = (equipment_id, limit)
        else:
            query = "SELECT * FROM operator_feedback ORDER BY timestamp DESC LIMIT ?"
            params = (limit,)
        
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ═══════════════════════════════════════════════════════════════════════════
    # TRUST METRICS (for trust calibrator)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_trust_metrics(self, metrics: Dict[str, Any]) -> None:
        """Save or update trust metrics for an operator (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR REPLACE INTO trust_metrics
                (metric_id, operator_id, building_id, follow_through_rate, avg_response_time_seconds,
                 total_recommendations, accepted_recommendations, rejected_recommendations,
                 silence_rate, last_updated, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.get("metric_id"),
                metrics.get("operator_id"),
                metrics.get("building_id"),
                metrics.get("follow_through_rate", 0.0),
                metrics.get("avg_response_time_seconds"),
                metrics.get("total_recommendations", 0),
                metrics.get("accepted_recommendations", 0),
                metrics.get("rejected_recommendations", 0),
                metrics.get("silence_rate", 0.0),
                datetime.now().isoformat(),
                json.dumps(metrics.get("metadata", {})),
            ))
            await conn.commit()

    async def get_trust_metrics(
        self,
        operator_id: str,
        building_id: str = None
    ) -> Optional[Dict]:
        """Get trust metrics for an operator (Async)"""
        conn = await self._get_async_connection()
        
        if building_id:
            query = """
                SELECT * FROM trust_metrics 
                WHERE operator_id = ? AND building_id = ?
                LIMIT 1
            """
            params = (operator_id, building_id)
        else:
            query = """
                SELECT * FROM trust_metrics 
                WHERE operator_id = ?
                ORDER BY last_updated DESC LIMIT 1
            """
            params = (operator_id,)
        
        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_trust_after_feedback(
        self,
        operator_id: str,
        recommendation_id: str,
        accepted: bool,
        response_time_seconds: float = None
    ) -> None:
        """Increment trust counters after feedback (Async)"""
        conn = await self._get_async_connection()
        
        # Get existing
        existing = await self.get_trust_metrics(operator_id)
        
        total = (existing.get("total_recommendations", 0) or 0) + 1
        accepted_count = (existing.get("accepted_recommendations", 0) or 0) + (1 if accepted else 0)
        rejected_count = (existing.get("rejected_recommendations", 0) or 0) + (0 if accepted else 1)
        follow_rate = accepted_count / total if total > 0 else 0.0
        
        # Update avg response time
        avg_rt = existing.get("avg_response_time_seconds") or 0
        if response_time_seconds is not None:
            prev_count = total - 1
            if prev_count > 0:
                avg_rt = (avg_rt * prev_count + response_time_seconds) / total
            else:
                avg_rt = response_time_seconds
        
        await conn.execute("""
            UPDATE trust_metrics SET
                total_recommendations = ?,
                accepted_recommendations = ?,
                rejected_recommendations = ?,
                follow_through_rate = ?,
                avg_response_time_seconds = ?,
                last_updated = ?
            WHERE operator_id = ?
        """, (
            total, accepted_count, rejected_count, follow_rate, avg_rt,
            datetime.now().isoformat(), operator_id
        ))
        await conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # RECOMMENDATIONS (for advisory engine)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_recommendation(self, rec: Dict[str, Any]) -> None:
        """Save an AI recommendation (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()

            await conn.execute("""
                INSERT OR REPLACE INTO recommendations
                (recommendation_id, equipment_id, domain, recommendation_type, priority,
                 title, description, confidence, evidence, action, created_at,
                 accepted_at, rejected_at, operator_id, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec.get("recommendation_id"),
                rec.get("equipment_id"),
                rec.get("domain"),
                rec.get("recommendation_type"),
                rec.get("priority", "medium"),
                rec.get("title"),
                rec.get("description"),
                rec.get("confidence", 0.5),
                json.dumps(rec.get("evidence", [])),
                rec.get("action"),
                datetime.now().isoformat(),
                rec.get("accepted_at"),
                rec.get("rejected_at"),
                rec.get("operator_id"),
                rec.get("status", "pending"),
                json.dumps(rec.get("metadata", {})),
            ))
            await conn.commit()

    async def get_recommendation(self, recommendation_id: str) -> Optional[Dict]:
        """Get a recommendation by ID (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute(
            "SELECT * FROM recommendations WHERE recommendation_id = ?",
            (recommendation_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                result["evidence"] = json.loads(result.get("evidence") or "[]")
                return result
        return None

    async def get_recommendations_by_equipment(
        self,
        equipment_id: str,
        status: str = None,
        limit: int = 20
    ) -> List[Dict]:
        """Get recommendations for an equipment (Async)"""
        conn = await self._get_async_connection()
        
        if status:
            query = """
                SELECT * FROM recommendations 
                WHERE equipment_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
            """
            params = (equipment_id, status, limit)
        else:
            query = """
                SELECT * FROM recommendations 
                WHERE equipment_id = ?
                ORDER BY created_at DESC LIMIT ?
            """
            params = (equipment_id, limit)
        
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                r = dict(row)
                r["evidence"] = json.loads(r.get("evidence") or "[]")
                result.append(r)
            return result

    async def update_recommendation_status(
        self,
        recommendation_id: str,
        status: str,
        operator_id: str = None,
        accepted_at: datetime = None,
        rejected_at: datetime = None
    ) -> None:
        """Update recommendation status (accepted/rejected/pending) (Async)"""
        conn = await self._get_async_connection()
        
        now = datetime.now().isoformat()
        
        if status == "accepted":
            await conn.execute("""
                UPDATE recommendations SET 
                    status = 'accepted', 
                    operator_id = ?,
                    accepted_at = ?
                WHERE recommendation_id = ?
            """, (operator_id, now, recommendation_id))
        elif status == "rejected":
            await conn.execute("""
                UPDATE recommendations SET 
                    status = 'rejected', 
                    operator_id = ?,
                    rejected_at = ?
                WHERE recommendation_id = ?
            """, (operator_id, now, recommendation_id))
        else:
            await conn.execute("""
                UPDATE recommendations SET status = ? WHERE recommendation_id = ?
            """, (status, recommendation_id))
        
        await conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # BRIEFINGS (for briefing engine)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_briefing(self, briefing: Dict[str, Any]) -> None:
        """Save a generated briefing (Async)"""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR REPLACE INTO briefings
                (briefing_id, period, building_id, title, critical_items, attention_items,
                 info_items, wins_items, generated_at, operator_id, operator_response,
                 responded_at, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                briefing.get("briefing_id"),
                briefing.get("period"),
                briefing.get("building_id"),
                briefing.get("title"),
                json.dumps(briefing.get("critical_items", [])),
                json.dumps(briefing.get("attention_items", [])),
                json.dumps(briefing.get("info_items", [])),
                json.dumps(briefing.get("wins_items", [])),
                datetime.now().isoformat(),
                briefing.get("operator_id"),
                briefing.get("operator_response"),
                briefing.get("responded_at"),
                briefing.get("status", "pending"),
                json.dumps(briefing.get("metadata", {})),
            ))
            await conn.commit()

    async def get_briefing(self, briefing_id: str) -> Optional[Dict]:
        """Get a briefing by ID (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute(
            "SELECT * FROM briefings WHERE briefing_id = ?",
            (briefing_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                for key in ["critical_items", "attention_items", "info_items", "wins_items"]:
                    result[key] = json.loads(result.get(key) or "[]")
                return result
        return None

    async def get_briefings_by_period(
        self,
        period: str,
        building_id: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """Get briefings by period (Async)"""
        conn = await self._get_async_connection()
        
        if building_id:
            query = """
                SELECT * FROM briefings 
                WHERE period = ? AND building_id = ?
                ORDER BY generated_at DESC LIMIT ?
            """
            params = (period, building_id, limit)
        else:
            query = """
                SELECT * FROM briefings 
                WHERE period = ?
                ORDER BY generated_at DESC LIMIT ?
            """
            params = (period, limit)
        
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                r = dict(row)
                for key in ["critical_items", "attention_items", "info_items", "wins_items"]:
                    r[key] = json.loads(r.get(key) or "[]")
                result.append(r)
            return result

    async def update_briefing_response(
        self,
        briefing_id: str,
        operator_response: str,
        status: str = "responded"
    ) -> None:
        """Record operator response to a briefing (Async)"""
        conn = await self._get_async_connection()

        await conn.execute("""
            UPDATE briefings SET
                operator_response = ?,
                responded_at = ?,
                status = ?
            WHERE briefing_id = ?
        """, (
            operator_response,
            datetime.now().isoformat(),
            status,
            briefing_id,
        ))
        await conn.commit()

    async def save_recommendation_outcome(self, outcome: Dict[str, Any]) -> None:
        """Persist a recommendation outcome record."""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR REPLACE INTO recommendation_outcomes
                (outcome_id, recommendation_id, session_id, action_type,
                 baseline_kwh, predicted_kwh_delta, actual_kwh_delta,
                 predicted_score, actual_score, confidence,
                 outcome_status, accuracy, measured_at, created_at, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                outcome.get("outcome_id"),
                outcome.get("recommendation_id"),
                outcome.get("session_id"),
                outcome.get("action_type"),
                outcome.get("baseline_kwh"),
                outcome.get("predicted_kwh_delta"),
                outcome.get("actual_kwh_delta"),
                outcome.get("predicted_score"),
                outcome.get("actual_score"),
                outcome.get("confidence", 0.7),
                outcome.get("outcome_status", "pending"),
                outcome.get("accuracy"),
                outcome.get("measured_at"),
                outcome.get("created_at"),
                outcome.get("notes"),
            ))
            await conn.commit()

    async def get_pending_outcomes(self) -> List[Dict[str, Any]]:
        """Fetch outcomes that are pending measurement (older than 20h)."""
        conn = await self._get_async_connection()
        cutoff = (datetime.now() - timedelta(hours=20)).isoformat()
        async with conn.execute("""
            SELECT * FROM recommendation_outcomes
            WHERE outcome_status = 'pending' AND created_at <= ?
            ORDER BY created_at ASC LIMIT 20
        """, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(zip([c[0] for c in cursor.description], r)) for r in rows]

    async def update_outcome(self, outcome_id: str, **kwargs) -> None:
        """Update fields on an existing outcome record."""
        conn = await self._get_async_connection()
        allowed = {"actual_kwh_delta", "actual_score", "outcome_status", "accuracy", "measured_at", "notes"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        await conn.execute(
            f"UPDATE recommendation_outcomes SET {set_clause} WHERE outcome_id = ?",
            (*fields.values(), outcome_id)
        )
        await conn.commit()

    async def save_distilled_rule(self, rule: Dict[str, Any]) -> None:
        """Persist a distilled rule with TTL and source tracking."""
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR REPLACE INTO distilled_rules
                (rule_id, agent_name, rule_text, confidence, veto_count, active,
                 created_at, updated_at, source_evidence_id, expires_at, hit_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                rule.get("rule_id"),
                rule.get("agent_name"),
                rule.get("rule_text"),
                rule.get("confidence", 0.0),
                rule.get("veto_count", 0),
                rule.get("active", 1),
                rule.get("created_at"),
                rule.get("updated_at"),
                rule.get("source_evidence_id"),
                rule.get("expires_at"),
                rule.get("hit_count", 0),
            ))
            await conn.commit()

    async def get_distilled_rules(self, agent_name: str) -> List[Dict[str, Any]]:
        """Fetch active, non-expired distilled rules for a specific agent."""
        from datetime import datetime, timezone
        _now = datetime.now(timezone.utc).isoformat()
        conn = await self._get_async_connection()
        async with conn.execute("""
            SELECT rule_id, rule_text, confidence FROM distilled_rules
            WHERE agent_name = ? AND active = 1
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY confidence DESC LIMIT 5
        """, (agent_name, _now)) as cursor:
            rows = await cursor.fetchall()
            rules = [dict(zip([c[0] for c in cursor.description], r)) for r in rows]

        # Increment hit_count for retrieved rules
        if rules:
            rule_ids = [r["rule_id"] for r in rules if r.get("rule_id")]
            if rule_ids:
                placeholders = ",".join("?" * len(rule_ids))
                await conn.execute(
                    f"UPDATE distilled_rules SET hit_count = hit_count + 1 WHERE rule_id IN ({placeholders})",
                    rule_ids,
                )
                await conn.commit()

        return rules

    # ── T2 Episodic Memory: Investigation archive ────────────────────────────

    async def archive_investigation_plan(self, plan) -> str:
        """Persist a completed InvestigationPlan to the episodic archive."""
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        conn = await self._get_async_connection()
        now = _dt.now(_tz.utc).isoformat()

        plan_id = getattr(plan, "id", str(__import__("uuid").uuid4())[:12])
        query = getattr(plan, "query", "")
        status = getattr(plan, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status)
        progress = getattr(plan, "progress", 0.0)
        evidence_count = len(getattr(plan, "evidence", []))
        created_at = getattr(plan, "created_at", None)
        created_at_str = created_at.isoformat() if created_at else now

        try:
            plan_json = plan.to_persist_dict() if hasattr(plan, "to_persist_dict") else {}
        except Exception:
            plan_json = {}

        await conn.execute("""
            INSERT OR REPLACE INTO investigation_plans
            (plan_id, query, building_id, status, progress, evidence_count, plan_json, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (plan_id, query, "", status_val, progress, evidence_count,
              _json.dumps(plan_json, default=str), created_at_str, now))

        # Archive tasks
        for task in getattr(plan, "tasks", []):
            await conn.execute("""
                INSERT OR REPLACE INTO plan_tasks
                (task_id, plan_id, goal, tool_hint, status, expected_outcome, evidence_ids, attempts, assigned_node)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (task.id, plan_id, task.goal, task.tool_hint,
                  task.status.value if hasattr(task.status, "value") else str(task.status),
                  task.expected_outcome, _json.dumps(task.evidence_ids),
                  task.attempts, task.assigned_node))

        # Archive audit spans
        for span in getattr(plan, "audit_trail", []):
            await conn.execute("""
                INSERT OR REPLACE INTO audit_spans
                (span_id, plan_id, task_id, node_name, action, tool_name, tool_args,
                 evidence_id, verdict, duration_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (span.id, plan_id, span.task_id, span.node_name, span.action,
                  span.tool_name, _json.dumps(span.tool_args or {}, default=str),
                  span.evidence_id, span.verdict, span.duration_ms,
                  span.timestamp.isoformat() if hasattr(span.timestamp, "isoformat") else str(span.timestamp)))

        # Archive evidence
        for ev in getattr(plan, "evidence", type("", (), {"get_all": lambda self: []})()).get_all() if hasattr(getattr(plan, "evidence", None), "get_all") else []:
            await conn.execute("""
                INSERT OR REPLACE INTO plan_evidence
                (evidence_id, plan_id, source_tool, node_name, summary, is_ml_fallback,
                 model_id, drift_score, call_sig, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ev.id, plan_id, ev.source_tool, ev.node_name, ev.summary,
                  1 if ev.is_ml_fallback else 0, ev.model_id, ev.drift_score,
                  ev.call_sig, _json.dumps(ev.raw_payload, default=str), now))

        await conn.commit()
        return plan_id

    async def get_investigation_plans(
        self,
        building_id: str = "",
        limit: int = 20,
        query_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve archived investigation plans, newest first."""
        conn = await self._get_async_connection()
        if query_filter:
            rows = await conn.execute_fetchall(
                "SELECT plan_id, query, status, progress, evidence_count, created_at, completed_at "
                "FROM investigation_plans WHERE query LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query_filter}%", limit),
            )
        else:
            rows = await conn.execute_fetchall(
                "SELECT plan_id, query, status, progress, evidence_count, created_at, completed_at "
                "FROM investigation_plans ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    async def load_investigation_plan_json(self, plan_id: str) -> Optional[str]:
        """Load full plan JSON for replay."""
        conn = await self._get_async_connection()
        rows = await conn.execute_fetchall(
            "SELECT plan_json FROM investigation_plans WHERE plan_id = ?", (plan_id,)
        )
        if rows:
            return rows[0]["plan_json"]
        return None

    async def flush_llm_usage(self, plan_id: str, budget=None) -> int:
        """Drain _LLM_USAGE_LOG into llm_usage table and update investigation_plans totals."""
        from agent_unified.llm import drain_usage_log
        entries = drain_usage_log()
        if not entries:
            return 0

        conn = await self._get_async_connection()
        total_cost = 0.0
        total_tokens = 0
        for entry in entries:
            await conn.execute("""
                INSERT INTO llm_usage (plan_id, node_name, channel, model_id, input_tokens, output_tokens, cost_usd, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan_id,
                entry.get("node_name", ""),
                entry.get("channel", ""),
                entry["model_id"],
                entry["input_tokens"],
                entry["output_tokens"],
                entry["cost_usd"],
                entry["timestamp"],
            ))
            total_cost += entry["cost_usd"]
            total_tokens += entry["input_tokens"] + entry["output_tokens"]

        # Update investigation_plans aggregate columns
        if plan_id:
            tool_cost = budget.used_cost_usd - total_cost if budget else 0.0
            await conn.execute("""
                UPDATE investigation_plans
                SET total_llm_cost_usd = ?, total_llm_tokens = ?, total_tool_cost_usd = ?
                WHERE plan_id = ?
            """, (total_cost, total_tokens, max(0.0, tool_cost), plan_id))

        await conn.commit()
        logger.info(f"[DB] Flushed {len(entries)} LLM usage entries for plan={plan_id} (${total_cost:.4f}, {total_tokens} tokens)")
        return len(entries)

    # ── BFT Vote & Violation Persistence (for Agentic Judge) ─────────────────

    async def save_bft_vote(
        self,
        round_id: str,
        plan_id: str,
        agent_name: str,
        vote: str,
        confidence: float,
        conditions: List[str],
        reasoning: str,
        proposal: str,
        proposer_name: str,
    ) -> None:
        """Persist a single BFT vote result."""
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR IGNORE INTO bft_votes
                (vote_id, round_id, plan_id, agent_name, vote, confidence,
                 conditions, reasoning, proposal, proposer_name, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(_uuid.uuid4())[:12], round_id, plan_id or "",
                agent_name, vote, confidence,
                json.dumps(conditions), reasoning,
                proposal, proposer_name,
                _dt.now(_tz.utc).isoformat(),
            ))
            await conn.commit()

    async def save_bft_abstention(
        self,
        round_id: str,
        plan_id: str,
        agent_name: str,
        reason: str,
    ) -> None:
        """Persist a BFT abstention (node failed to vote)."""
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR IGNORE INTO bft_abstentions
                (abstention_id, round_id, plan_id, agent_name, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                str(_uuid.uuid4())[:12], round_id, plan_id or "",
                agent_name, reason,
                _dt.now(_tz.utc).isoformat(),
            ))
            await conn.commit()

    async def save_violation(
        self,
        plan_id: str,
        advisory_text: str,
        code: str,
        severity: str,
        description: str,
        expected_value: Optional[float] = None,
        cited_value: Optional[float] = None,
        component: str = "",
    ) -> None:
        """Persist a physics violation from the simulator."""
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR IGNORE INTO violation_ledger
                (violation_id, plan_id, advisory_text, code, severity,
                 description, expected_value, cited_value, component, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(_uuid.uuid4())[:12], plan_id or "",
                advisory_text, code, severity, description,
                expected_value, cited_value, component,
                _dt.now(_tz.utc).isoformat(),
            ))
            await conn.commit()

    async def save_judgment(
        self,
        run_id: str,
        phase: str,
        scenario: str,
        dimension_id: str,
        score: float,
        reasoning: str,
        evidence_chain: List[Dict[str, Any]],
        tool_calls_used: int = 0,
        judge_model_id: str = "",
        wall_time_ms: float = 0.0,
    ) -> None:
        """Persist a single judge dimension score with evidence chain."""
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT OR IGNORE INTO judgment_ledger
                (judgment_id, run_id, phase, scenario, dimension_id, score,
                 reasoning, evidence_chain, tool_calls_used, judge_model_id,
                 wall_time_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(_uuid.uuid4())[:12], run_id, phase, scenario,
                dimension_id, score, reasoning,
                json.dumps(evidence_chain), tool_calls_used,
                judge_model_id, wall_time_ms,
                _dt.now(_tz.utc).isoformat(),
            ))
            await conn.commit()

    # ── T1 Working Memory: Conversation turns ────────────────────────────────

    async def save_conversation_turn(
        self,
        operator_id: str,
        building_id: str,
        role: str,
        content: str,
        is_summary: bool = False,
        summary_range: str = "",
    ) -> None:
        """Persist one conversation turn."""
        from datetime import datetime as _dt, timezone as _tz
        async with self._write_lock:
            conn = await self._get_async_connection()
            await conn.execute("""
                INSERT INTO conversation_turns
                (turn_id, operator_id, building_id, role, content, is_summary, summary_range, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(__import__("uuid").uuid4())[:12], operator_id, building_id,
                  role, content, 1 if is_summary else 0, summary_range,
                  _dt.now(_tz.utc).isoformat()))
            await conn.commit()

    async def load_conversation_turns(
        self,
        operator_id: str,
        building_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Load recent conversation turns for an operator."""
        conn = await self._get_async_connection()
        rows = await conn.execute_fetchall(
            "SELECT role, content, is_summary, created_at FROM conversation_turns "
            "WHERE operator_id = ? AND building_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (operator_id, building_id, limit),
        )
        return [dict(r) for r in reversed(rows)]

    async def save_suggested_action(self, action_text: str, source: str = "system", confidence: float = 1.0) -> None:
        """Persist a suggested action for injection into LLM context."""
        async with self._write_lock:
            async with await self._get_async_connection() as conn:
                await conn.execute(
                    """INSERT OR IGNORE INTO suggested_actions
                       (action_id, action_text, source, confidence, created_at, status)
                       VALUES (?, ?, ?, ?, ?, 'pending')""",
                    (str(__import__('uuid').uuid4()), action_text, source, confidence,
                     __import__('datetime').datetime.now().isoformat())
                )
                await conn.commit()

    async def get_pending_suggestions(self, limit: int = 10) -> list:
        """Fetch pending suggested actions for LLM context injection."""
        async with await self._get_async_connection() as conn:
            async with conn.execute(
                "SELECT action_text, source, confidence FROM suggested_actions WHERE status='pending' ORDER BY confidence DESC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows] if rows else []


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

_db_instance: Optional[BMSDatabase] = None


def get_database(db_path: str = None) -> BMSDatabase:
    """Get or create the singleton database instance.

    If db_path differs from the cached instance's path, rebuild the singleton
    so isolated-run paths (e.g. runs/<id>/arvis_bms.db) are honored instead of
    silently falling back to the first-call path.
    """
    global _db_instance

    if _db_instance is None:
        _db_instance = BMSDatabase(db_path)
    elif db_path is not None and str(_db_instance.db_path) != str(db_path):
        # Path changed (isolated test run, etc.) — rebuild singleton
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Best-effort close; caller responsible for awaiting in async ctx
                asyncio.ensure_future(_db_instance.close())
            else:
                loop.run_until_complete(_db_instance.close())
        except Exception:
            pass
        _db_instance = BMSDatabase(db_path)

    return _db_instance
