"""
Unit tests for the Marina JudgeAgent ReAct loop.

Tests the agent's behavior with mocked LLM responses to verify:
- ReAct loop terminates correctly
- Evidence chains are populated
- Abstention works when plan_id is missing
- Budget exhaustion is handled
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from marina_e2e.judge_agent import JudgeAgent, JudgeBudget
from marina_e2e.schemas import JudgmentEntry, PhaseWindow


@pytest.fixture
def sample_dimension():
    return {
        "id": "causal_chain_depth",
        "weight": 3.0,
        "description": "Trace from symptoms to root cause. Minimum 3 hops.",
        "deterministic": False,
    }


@pytest.fixture
def sample_arvis_output():
    return (
        "Analysis shows AHU-7 damper slip → downstream SAT excursion → "
        "zone temp drift → occupant complaints. Root cause: belt tension loss. "
        "Recommendation: replace belt within 14 days."
    )


class TestJudgeBudget:
    def test_initial_state(self):
        b = JudgeBudget(max_tool_calls=8)
        assert not b.exhausted
        assert b.remaining == 8

    def test_exhausted_by_calls(self):
        b = JudgeBudget(max_tool_calls=2)
        b.used_tool_calls = 2
        assert b.exhausted
        assert b.remaining == 0


class TestJudgeAgentAbstention:
    @pytest.mark.asyncio
    async def test_abstains_without_plan_id(self, sample_dimension, sample_arvis_output):
        agent = JudgeAgent(db_path="/tmp/nonexistent.db")
        entry = await agent.score_dimension(
            dim=sample_dimension,
            arvis_output=sample_arvis_output,
            plan_id=None,
        )
        assert entry.abstained
        assert entry.abstain_reason == "no_plan_id"
        assert entry.score == 0.0
        assert entry.tool_calls_used == 0


class TestJudgeAgentScoring:
    @pytest.mark.asyncio
    async def test_scores_on_first_response(self, sample_dimension, sample_arvis_output):
        """Judge LLM returns score immediately without tool calls."""
        agent = JudgeAgent(db_path="/tmp/test.db")

        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "score": 8.5,
            "reasoning": "4-hop causal chain verified via evidence ledger.",
            "findings": ["4 hops found", "All evidence IDs valid"],
        })

        mock_llm = AsyncMock()
        mock_llm.ask = AsyncMock(return_value=mock_response)
        agent._llm = mock_llm

        entry = await agent.score_dimension(
            dim=sample_dimension,
            arvis_output=sample_arvis_output,
            plan_id="plan_test_001",
        )

        assert not entry.abstained
        assert entry.score == 8.5
        assert "causal chain" in entry.reasoning
        assert entry.tool_calls_used == 0

    @pytest.mark.asyncio
    async def test_calls_tools_then_scores(self, sample_dimension, sample_arvis_output):
        """Judge calls tools first iteration, then scores second iteration."""
        agent = JudgeAgent(db_path="/tmp/test.db")

        tool_call_response = MagicMock()
        tool_call_response.content = json.dumps({
            "tool_calls": [
                {"tool": "query_evidence_ledger", "params": {"plan_id": "plan_test_001"}}
            ]
        })

        score_response = MagicMock()
        score_response.content = json.dumps({
            "score": 7.0,
            "reasoning": "Evidence ledger shows 3 records, chain has 3 hops.",
        })

        mock_llm = AsyncMock()
        mock_llm.ask = AsyncMock(side_effect=[tool_call_response, score_response])
        agent._llm = mock_llm

        with patch("marina_e2e.judge_agent.call_tool") as mock_call_tool:
            from marina_e2e.schemas import ToolResult
            mock_call_tool.return_value = ToolResult(
                ok=True,
                data={"evidence": [], "count": 3, "ml_fallback_count": 0},
                tool_name="query_evidence_ledger",
            )

            entry = await agent.score_dimension(
                dim=sample_dimension,
                arvis_output=sample_arvis_output,
                plan_id="plan_test_001",
            )

        assert not entry.abstained
        assert entry.score == 7.0
        assert entry.tool_calls_used == 1
        assert len(entry.evidence_chain) == 1
        assert entry.evidence_chain[0].tool == "query_evidence_ledger"

    @pytest.mark.asyncio
    async def test_budget_exhaustion(self, sample_dimension, sample_arvis_output):
        """Judge exhausts budget without scoring → abstains."""
        agent = JudgeAgent(db_path="/tmp/test.db", budget_per_dim=1)

        tool_call_response = MagicMock()
        tool_call_response.content = json.dumps({
            "tool_calls": [
                {"tool": "query_evidence_ledger", "params": {"plan_id": "plan_test_001"}}
            ]
        })

        # Second response also tries tools (budget already exhausted)
        more_tools_response = MagicMock()
        more_tools_response.content = json.dumps({
            "tool_calls": [
                {"tool": "query_bft_votes", "params": {"plan_id": "plan_test_001"}}
            ]
        })

        mock_llm = AsyncMock()
        mock_llm.ask = AsyncMock(side_effect=[tool_call_response, more_tools_response])
        agent._llm = mock_llm

        with patch("marina_e2e.judge_agent.call_tool") as mock_call_tool:
            from marina_e2e.schemas import ToolResult
            mock_call_tool.return_value = ToolResult(
                ok=True, data={"count": 3},
                tool_name="query_evidence_ledger",
            )

            entry = await agent.score_dimension(
                dim=sample_dimension,
                arvis_output=sample_arvis_output,
                plan_id="plan_test_001",
            )

        assert entry.abstained
        assert entry.abstain_reason == "budget_exhausted"


class TestJudgeAgentPhaseScoring:
    @pytest.mark.asyncio
    async def test_deterministic_gate_skip(self, sample_arvis_output):
        """Dimensions with passing deterministic gates skip DB introspection."""
        agent = JudgeAgent(db_path="/tmp/test.db")

        dims = [
            {"id": "write_blocked", "weight": 5.0, "description": "Read-only", "deterministic": True},
            {"id": "causal_depth", "weight": 3.0, "description": "Causal chain", "deterministic": False},
        ]

        mock_response = MagicMock()
        mock_response.content = json.dumps({"score": 8.0, "reasoning": "Good chain."})

        mock_llm = AsyncMock()
        mock_llm.ask = AsyncMock(return_value=mock_response)
        agent._llm = mock_llm

        entries = await agent.score_phase(
            dimensions=dims,
            arvis_output=sample_arvis_output,
            plan_id="plan_test_001",
            deterministic_results={"write_blocked": True},
        )

        assert len(entries) == 2
        assert entries[0].dimension_id == "write_blocked"
        assert entries[0].score == 10.0
        assert entries[0].tool_calls_used == 0
        assert entries[1].dimension_id == "causal_depth"
        assert entries[1].score == 8.0
