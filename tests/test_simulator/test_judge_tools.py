"""
Unit tests for Marina agentic judge verification toolkit.

Tests each tool against a fixture SQLite database with known data.
"""

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure project root on path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from marina_e2e.judge_tools import (
    TOOL_REGISTRY,
    call_tool,
    get_all_tools,
    query_bft_abstentions,
    query_bft_votes,
    query_conversation_turns,
    query_distilled_rules,
    query_evidence_ledger,
    query_investigation_plan,
    query_llm_usage,
    query_skillbook_growth,
    query_violation_ledger,
)


@pytest.fixture
def fixture_db(tmp_path):
    """Create a fixture database with known test data."""
    db_path = str(tmp_path / "test_arvis.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create all required tables
    cur.executescript("""
        CREATE TABLE investigation_plans (
            plan_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            building_id TEXT DEFAULT '',
            status TEXT DEFAULT 'complete',
            progress REAL DEFAULT 1.0,
            evidence_count INTEGER DEFAULT 0,
            query_embedding BLOB,
            plan_json TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            total_llm_cost_usd REAL DEFAULT 0.0,
            total_llm_tokens INTEGER DEFAULT 0,
            total_tool_cost_usd REAL DEFAULT 0.0
        );

        CREATE TABLE plan_tasks (
            task_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            goal TEXT,
            tool_hint TEXT,
            status TEXT DEFAULT 'complete',
            expected_outcome TEXT,
            evidence_ids TEXT DEFAULT '[]',
            attempts INTEGER DEFAULT 1,
            assigned_node TEXT
        );

        CREATE TABLE audit_spans (
            span_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            task_id TEXT DEFAULT '',
            node_name TEXT DEFAULT '',
            action TEXT,
            tool_name TEXT,
            tool_args TEXT,
            evidence_id TEXT,
            verdict TEXT,
            duration_ms REAL DEFAULT 100.0,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE plan_evidence (
            evidence_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            source_tool TEXT,
            node_name TEXT DEFAULT '',
            summary TEXT,
            is_ml_fallback INTEGER DEFAULT 0,
            model_id TEXT,
            drift_score REAL,
            call_sig TEXT,
            evidence_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE bft_votes (
            vote_id TEXT PRIMARY KEY,
            round_id TEXT NOT NULL,
            plan_id TEXT DEFAULT '',
            agent_name TEXT NOT NULL,
            vote TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            conditions TEXT DEFAULT '[]',
            reasoning TEXT,
            proposal TEXT,
            proposer_name TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE bft_abstentions (
            abstention_id TEXT PRIMARY KEY,
            round_id TEXT NOT NULL,
            plan_id TEXT DEFAULT '',
            agent_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE violation_ledger (
            violation_id TEXT PRIMARY KEY,
            plan_id TEXT DEFAULT '',
            advisory_text TEXT,
            code TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT,
            expected_value REAL,
            cited_value REAL,
            component TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        );

        CREATE TABLE distilled_rules (
            rule_id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL,
            rule_text TEXT NOT NULL,
            confidence REAL DEFAULT 0.8,
            veto_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            source_evidence_id TEXT,
            expires_at TEXT,
            hit_count INTEGER DEFAULT 0
        );

        CREATE TABLE skills (
            skill_id TEXT PRIMARY KEY,
            building_id TEXT NOT NULL,
            skill_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            verified_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'unverified',
            equipment_id TEXT,
            zone_id TEXT,
            contractor_id TEXT,
            evidence TEXT,
            context_signature TEXT,
            confidence_history TEXT,
            tags TEXT,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT DEFAULT 'system'
        );

        CREATE TABLE conversation_turns (
            turn_id TEXT PRIMARY KEY,
            operator_id TEXT NOT NULL,
            building_id TEXT DEFAULT '',
            role TEXT NOT NULL,
            content TEXT,
            is_summary INTEGER DEFAULT 0,
            summary_range TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id TEXT DEFAULT '',
            node_name TEXT DEFAULT '',
            channel TEXT DEFAULT '',
            model_id TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            timestamp TEXT NOT NULL
        );
    """)

    now = datetime.now(timezone.utc).isoformat()
    plan_id = "plan_test_001"

    # Insert test plan
    cur.execute(
        "INSERT INTO investigation_plans VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, 0.05, 1200, 0.01)",
        (plan_id, "Investigate AHU-7 damper slip", "marina-heights", "complete", 1.0, 3, now),
    )

    # Insert tasks
    for i in range(3):
        cur.execute(
            "INSERT INTO plan_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"task_{i}", plan_id, f"Task goal {i}", "read_bms_data",
             "complete", f"Expected {i}", "[]", 1, "Energy_Agent"),
        )

    # Insert audit spans
    for i in range(4):
        cur.execute(
            "INSERT INTO audit_spans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"span_{i}", plan_id, f"task_{i % 3}", "Energy_Agent",
             "tool_call", "read_bms_data", '{"point": "AHU-7/SAT"}',
             f"ev_{i}", "pass", 50.0 + i * 10, now),
        )

    # Insert evidence
    for i in range(3):
        cur.execute(
            "INSERT INTO plan_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"ev_{i}", plan_id, "read_bms_data", "Energy_Agent",
             f"AHU-7 damper reading {i}", 0 if i < 2 else 1,
             "us.anthropic.claude-sonnet-4-6" if i == 2 else None,
             0.1 if i == 2 else None, None, None, now),
        )

    # Insert BFT votes
    cur.execute(
        "INSERT INTO bft_votes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("v1", "round_1", plan_id, "Comfort_Agent", "APPROVE", 0.9,
         "[]", "Within comfort bounds", "Replace belt", "Energy_Agent", now),
    )
    cur.execute(
        "INSERT INTO bft_votes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("v2", "round_1", plan_id, "Safety_Agent", "APPROVE_WITH_CONDITION", 0.7,
         '["Schedule during low occupancy"]', "Safe if scheduled properly",
         "Replace belt", "Energy_Agent", now),
    )

    # Insert abstention
    cur.execute(
        "INSERT INTO bft_abstentions VALUES (?, ?, ?, ?, ?, ?)",
        ("a1", "round_1", plan_id, "Maintenance_Agent", "parse_error: timeout", now),
    )

    # Insert violations
    cur.execute(
        "INSERT INTO violation_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("viol_1", plan_id, "Set SAT to 14C with 85% OA",
         "COP_EXCEEDS_PHYSICS", "hard", "COP 6.8 exceeds cubic model max",
         5.2, 6.8, "CH-01", now),
    )

    # Insert distilled rule
    cur.execute(
        "INSERT INTO distilled_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rule_1", "Energy_Agent", "AHU-7 belt slip causes cascading SAT drift",
         0.85, 0, 1, now, now, "ev_2", None, 3),
    )

    # Insert skill
    cur.execute(
        "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sk_1", "marina-heights", "equipment_quirk", "AHU-7 damper slip resolution",
         "When AHU-7 SAT drifts above setpoint, check belt tension first",
         0.8, 2, 0, "verified", "AHU-07", None, None,
         '{"source": "investigation"}', None, None, '["ahu", "belt"]', now, now, "system"),
    )

    # Insert conversation turns
    cur.execute(
        "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("t1", "noor", "marina-heights", "user",
         "What is wrong with AHU-7?", 0, "", now),
    )
    cur.execute(
        "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("t2", "noor", "marina-heights", "assistant",
         "AHU-7 shows SAT drift indicating belt slip.", 0, "", now),
    )

    # Insert LLM usage
    cur.execute(
        "INSERT INTO llm_usage (plan_id, node_name, channel, model_id, input_tokens, output_tokens, cost_usd, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (plan_id, "Energy_Agent", "chat", "us.anthropic.claude-sonnet-4-6",
         800, 400, 0.012, now),
    )

    conn.commit()
    conn.close()
    return db_path


class TestToolRegistry:
    def test_registry_has_all_tools(self):
        tools = get_all_tools()
        assert len(tools) >= 9
        assert "query_investigation_plan" in tools
        assert "query_evidence_ledger" in tools
        assert "query_bft_votes" in tools
        assert "query_violation_ledger" in tools
        assert "query_skillbook_growth" in tools

    def test_call_tool_unknown(self):
        result = call_tool("nonexistent_tool")
        assert not result.ok
        assert "Unknown tool" in result.error


class TestQueryInvestigationPlan:
    def test_existing_plan(self, fixture_db):
        result = query_investigation_plan("plan_test_001", db_path=fixture_db)
        assert result.ok
        assert result.data["plan"]["plan_id"] == "plan_test_001"
        assert result.data["task_count"] == 3
        assert result.data["span_count"] == 4

    def test_missing_plan(self, fixture_db):
        result = query_investigation_plan("nonexistent", db_path=fixture_db)
        assert not result.ok
        assert "No plan found" in result.error


class TestQueryEvidenceLedger:
    def test_evidence_for_plan(self, fixture_db):
        result = query_evidence_ledger("plan_test_001", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 3
        assert result.data["ml_fallback_count"] == 1

    def test_empty_evidence(self, fixture_db):
        result = query_evidence_ledger("no_such_plan", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 0


class TestQueryBFTVotes:
    def test_votes_for_plan(self, fixture_db):
        result = query_bft_votes("plan_test_001", db_path=fixture_db)
        assert result.ok
        assert result.data["total"] == 2
        assert result.data["approvals"] == 1
        assert result.data["conditional"] == 1
        assert result.data["vetoes"] == 0


class TestQueryBFTAbstentions:
    def test_abstentions(self, fixture_db):
        result = query_bft_abstentions("plan_test_001", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 1
        assert "Maintenance_Agent" in result.data["abstentions"][0]["agent_name"]


class TestQueryViolationLedger:
    def test_violations_for_plan(self, fixture_db):
        result = query_violation_ledger(plan_id="plan_test_001", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["hard_count"] == 1
        assert result.data["violations"][0]["code"] == "COP_EXCEEDS_PHYSICS"

    def test_violations_severity_filter(self, fixture_db):
        result = query_violation_ledger(severity="soft", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 0


class TestQueryDistilledRules:
    def test_rules_for_agent(self, fixture_db):
        result = query_distilled_rules(agent_name="Energy_Agent", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 1
        assert "belt slip" in result.data["rules"][0]["rule_text"]

    def test_rules_no_match(self, fixture_db):
        result = query_distilled_rules(agent_name="Nonexistent_Agent", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 0


class TestQuerySkillbookGrowth:
    def test_skills_for_building(self, fixture_db):
        result = query_skillbook_growth("marina-heights", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 1
        assert "equipment_quirk" in result.data["skill_types"]

    def test_skills_wrong_building(self, fixture_db):
        result = query_skillbook_growth("other-building", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 0


class TestQueryConversationTurns:
    def test_conversation_history(self, fixture_db):
        result = query_conversation_turns("noor", "marina-heights", db_path=fixture_db)
        assert result.ok
        assert result.data["count"] == 2
        roles = {t["role"] for t in result.data["turns"]}
        assert "user" in roles
        assert "assistant" in roles


class TestQueryLLMUsage:
    def test_usage_for_plan(self, fixture_db):
        result = query_llm_usage(plan_id="plan_test_001", db_path=fixture_db)
        assert result.ok
        assert result.data["call_count"] == 1
        assert result.data["total_cost_usd"] == 0.012
        assert "us.anthropic.claude-sonnet-4-6" in result.data["models_used"]
