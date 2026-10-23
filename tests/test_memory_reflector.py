"""Context-aware memory reflector.

Covers: the skillbook no longer returns unrelated skills when nothing matches;
explain_empty says WHY a search is empty; the reflector gate retries only when
relevant past experience may exist; Kev is asked only for the ambiguous case and
its failure falls back to the rule.
"""

import pytest
import pytest_asyncio

from agent_commercial.skillbook import BuildingSkillbook
from arvis_core.decision import kev
from arvis_core.decision import reflector
from arvis_core.decision.reflector import decide_reflection, gate, rule_judge


# ── Skillbook with a deterministic matcher (no model download) ────────────────

class WordMatcher:
    """Scores by word overlap — stands in for the embedding model."""
    is_available = True

    def __init__(self):
        self.texts = {}

    def add_skill(self, skill_id, text):
        self.texts[skill_id] = set(text.lower().split())

    def _score(self, q, sid):
        qw = set(q.lower().split())
        return len(qw & self.texts[sid]) / max(1, len(qw | self.texts[sid]))

    def nearest(self, query, top_k=3):
        return sorted(((s, self._score(query, s)) for s in self.texts), key=lambda x: -x[1])[:top_k]

    def find_similar(self, query, top_k=5, threshold=0.3):
        return [(s, sc) for s, sc in self.nearest(query, top_k) if sc >= threshold]


@pytest_asyncio.fixture
async def skillbook(tmp_path):
    sb = BuildingSkillbook("t", db_path=str(tmp_path / "sb.db"))
    sb.matcher = WordMatcher()
    await sb.ensure_initialized()
    yield sb
    await sb.close()


async def _add(sb, title, equipment_id, skill_type="fault_pattern"):
    await sb.add_skill(skill_type=skill_type, title=title, description=title, equipment_id=equipment_id)


@pytest.mark.asyncio
async def test_no_semantic_match_returns_nothing_not_top_skills(skillbook):
    await _add(skillbook, "chiller condenser fouling high approach", "CH-01")
    got = await skillbook.get_relevant_skills({"query": "lift door stuck on floor 3", "similarity_threshold": 0.3})
    assert got == []


@pytest.mark.asyncio
async def test_explain_empty_store_empty(skillbook):
    d = await skillbook.explain_empty({"query": "AHU-07 hot supply air"})
    assert d["empty_reason"] == "store_empty" and d["store_size"] == 0


@pytest.mark.asyncio
async def test_explain_empty_off_scope(skillbook):
    await _add(skillbook, "AHU-07 hot supply air coil capacity", "AHU-07")
    d = await skillbook.explain_empty({"query": "AHU-03 hot supply air coil capacity", "similarity_threshold": 0.3})
    assert d["empty_reason"] == "off_scope"
    assert d["near_misses"][0]["equipment_id"] == "AHU-07"


@pytest.mark.asyncio
async def test_explain_empty_dropped_by_tool_is_off_scope(skillbook):
    await _add(skillbook, "something", "AHU-07")
    d = await skillbook.explain_empty({"query": "x"}, dropped_off_scope=2)
    assert d["empty_reason"] == "off_scope" and d["dropped_off_scope"] == 2


@pytest.mark.asyncio
async def test_explain_empty_filtered_out(skillbook):
    await _add(skillbook, "hot supply air coil capacity", None, skill_type="pattern")
    d = await skillbook.explain_empty({"query": "hot supply air coil capacity", "skill_type": "fault_pattern",
                                       "similarity_threshold": 0.3})
    assert d["empty_reason"] == "filtered_out"


@pytest.mark.asyncio
async def test_explain_empty_below_threshold(skillbook):
    await _add(skillbook, "hot supply air coil capacity exhausted", None)
    d = await skillbook.explain_empty({"query": "supply air warm complaint", "similarity_threshold": 0.5})
    assert d["empty_reason"] == "below_threshold"
    assert 0 < d["best_score"] < 0.5


@pytest.mark.asyncio
async def test_explain_empty_without_model_says_so(skillbook):
    await _add(skillbook, "anything", None)
    skillbook.matcher.is_available = False
    d = await skillbook.explain_empty({"query": "x"})
    assert d["semantic_available"] is False
    dec = await decide_reflection(d, query="x")
    assert dec.retry is False and dec.source == "gate"


# ── Reflector gate / rule / Kev ───────────────────────────────────────────────

def _diag(reason, best=None, thr=0.2, **kw):
    nm = [{"title": "coil capacity exhausted", "equipment_id": "AHU-07", "skill_type": "fault_pattern", "score": best}] \
        if best is not None else []
    return {"empty_reason": reason, "store_size": 5, "threshold": thr, "best_score": best,
            "near_misses": nm, "filters": kw.get("filters", {}), "semantic_available": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,retry", [
    ("store_empty", False), ("off_scope", False), ("filtered_out", True), ("missed", True),
])
async def test_gate_decides_from_facts(reason, retry):
    d = await decide_reflection(_diag(reason, best=0.4, filters={"skill_type": "pattern"}), query="q")
    assert d.retry is retry and d.source == "gate"
    assert "REFLECTION" in d.note


@pytest.mark.asyncio
async def test_no_diagnostics_means_no_decision():
    assert await decide_reflection(None) is None
    assert await decide_reflection({"store_size": 3}) is None


@pytest.mark.asyncio
async def test_one_reflection_per_tool_and_budget():
    d = _diag("missed", best=0.4)
    assert (await decide_reflection(d, already_reflected=True)).retry is False
    assert (await decide_reflection(d, budget_ok=False)).retry is False


def test_ambiguous_cases_reach_the_judge():
    assert gate(_diag("below_threshold", best=0.15)) is None
    assert gate(_diag("no_candidates")) is None


def test_rule_judge_margin(monkeypatch):
    monkeypatch.setenv("ARVIS_REFLECTOR_MARGIN", "0.1")
    assert rule_judge(_diag("below_threshold", best=0.15, thr=0.2)) is True    # near miss
    assert rule_judge(_diag("below_threshold", best=0.05, thr=0.2)) is False   # far
    assert rule_judge(_diag("no_candidates")) is False


@pytest.mark.asyncio
async def test_kev_decides_ambiguous_case(monkeypatch):
    seen = {}

    async def fake(state, instructions, qid="q"):
        seen["state"] = state
        return 0.9
    monkeypatch.setattr(kev, "ask_noul", fake)
    d = await decide_reflection(_diag("below_threshold", best=0.01), query="AHU-07 hot", judge="kev")
    assert d.retry is True and d.source == "kev" and d.p_retry == 0.9
    assert "coil capacity exhausted" in seen["state"]       # near misses are the state


@pytest.mark.asyncio
async def test_kev_not_asked_when_facts_decide(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("Kev must not be called")
    monkeypatch.setattr(kev, "ask_noul", boom)
    d = await decide_reflection(_diag("store_empty"), judge="kev")
    assert d.retry is False


@pytest.mark.asyncio
async def test_kev_failure_falls_back_to_rule(monkeypatch):
    async def down(*a, **k):
        return None
    monkeypatch.setattr(kev, "ask_noul", down)
    d = await decide_reflection(_diag("below_threshold", best=0.18, thr=0.2), judge="kev")
    assert d.source == "rule" and d.retry is True


# ── Kev client ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload,p", [
    ({"reflect": {"noul": 0.7}}, 0.7),
    ({"answers": {"reflect": {"noul": 0.2}}}, 0.2),
    ({"results": {"reflect": 0.4}}, 0.4),
    ({"reflect": {"noul": 1.7}}, None),        # not a probability
    ({"reflect": {"noul": True}}, None),
    ({"other": {"noul": 0.5}}, None),
    ([], None),
])
def test_kev_response_parsing(payload, p):
    assert kev._find_p(payload, "reflect") == p


@pytest.mark.asyncio
async def test_kev_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("ARVIS_DECISION_URL", raising=False)
    assert await kev.ask_noul("s", "i") is None


@pytest.mark.asyncio
async def test_kev_request_shape_and_unreachable(monkeypatch):
    import httpx
    captured = {}

    def handler(request):
        import json as _j
        captured["url"] = str(request.url)
        captured["body"] = _j.loads(request.content)
        return httpx.Response(200, json={"reflect": {"noul": 0.66}, "latency_ms": 12})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("ARVIS_DECISION_URL", "http://127.0.0.1:8090/")
    assert await kev.ask_noul("STATE", "INSTR", qid="reflect") == 0.66
    assert captured["url"] == "http://127.0.0.1:8090/v1/systemone"
    assert captured["body"]["questions"]["reflect"] == {"type": "noul", "instructions": "INSTR"}
    assert captured["body"]["state"] == "STATE"

    def down(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(down), **kw))
    assert await kev.ask_noul("s", "i") is None


@pytest.mark.asyncio
async def test_low_confidence_matches_are_not_retried():
    d = _diag("low_confidence", best=0.6)
    d["low_confidence_matches"] = [{"title": "coil fouling", "equipment_id": "AHU-07", "relevance": 0.3}]
    dec = await decide_reflection(d, query="AHU-07 hot")
    assert dec.retry is False and dec.source == "gate"
    assert "coil fouling" in dec.note and "Do not cite" in dec.note


# ── Swarm node: the gate drives the loop ──────────────────────────────────────

def _run_node(monkeypatch, retrieval_per_call, second_call_tool="query_skillbook"):
    """Memory agent issues query_skillbook each turn; the tool returns empty with the
    given diagnostics. Returns (tool messages, number of LLM tool turns)."""
    import asyncio
    import agent_commercial.database as db
    from agent_unified.schema import Function, Message, ToolCall
    from arvis_core.swarm.node import SwarmNode

    monkeypatch.setattr(db, "get_database", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    turns = []

    class LLM:
        async def ask_json(self, **kw):
            return {"turns": 6}

        async def ask_tool(self, messages, **kw):
            turns.append(1)
            n = len(turns)
            return Message.assistant_message(content="", tool_calls=[
                ToolCall(id=f"c{n}", function=Function(name="query_skillbook", arguments=f'{{"query": "AHU-07 hot v{n}"}}'))])

        async def ask(self, **kw):
            return Message.assistant_message(content="done")

    calls = []

    class Tools:
        async def execute(self, tool_name, args, plan=None, task_id="", node_name=""):
            diag = retrieval_per_call[min(len(calls), len(retrieval_per_call) - 1)]
            calls.append(args)
            return {"query": args["query"], "skills": [], "retrieval": diag}

    agent = SwarmNode(name="Memory_Agent", role="r", llm=LLM(), tool_handler=Tools(),
                      tools=[{"name": "query_skillbook", "description": "d", "parameters": {"type": "object", "properties": {}}}])
    out = asyncio.run(agent.process("q", context={"_risk_tier": 3}))
    tool_msgs = [m for m in out["history"] if m.get("role") == "tool"]
    return tool_msgs, len(calls)


def test_node_accepts_no_experience_and_stops_searching(monkeypatch):
    msgs, n = _run_node(monkeypatch, [_diag("store_empty")])
    assert "No relevant past experience" in msgs[0]["content"]
    assert n == 2                         # second empty → early exit, no further memory calls


def test_node_grants_one_retry_then_accepts(monkeypatch):
    msgs, n = _run_node(monkeypatch, [_diag("missed", best=0.5), _diag("missed", best=0.5)])
    assert "may exist" in msgs[0]["content"]                          # retry granted
    assert "already searched again once" in msgs[1]["content"]       # one per tool
    assert n == 3                         # the sanctioned retry did not count toward the early exit


def test_node_without_diagnostics_keeps_old_behaviour(monkeypatch):
    msgs, n = _run_node(monkeypatch, [None])
    assert "REFLECTION" not in msgs[0]["content"]
    assert n == 2


@pytest.mark.asyncio
async def test_failed_reranker_does_not_halve_confidence(skillbook):
    """A reranker that fails returns candidates unscored. That used to count as a score
    of 0 and halve every skill's confidence, pushing all memories under the cite gate."""
    class FailedReranker:
        is_available = True

        def rerank(self, query, candidates, top_n=5):
            return candidates[:top_n]          # what CrossEncoderReranker does on failure
    skillbook.reranker = FailedReranker()
    await skillbook.add_skill(skill_type="fault_pattern", title="AHU-07 coil capacity exhausted",
                              description="AHU-07 coil capacity exhausted", equipment_id="AHU-07", confidence=0.7)
    got = await skillbook.get_relevant_skills({"situation_query": "AHU-07 coil capacity exhausted",
                                               "similarity_threshold": 0.3})
    assert got and got[0].confidence >= 0.6


@pytest.mark.asyncio
async def test_skills_written_back_to_back_are_both_kept(skillbook):
    """Ids were timestamp-only; on Windows two quick writes collided and the second
    INSERT OR REPLACE overwrote the first."""
    for n in range(20):
        await skillbook.add_skill(skill_type="pattern", title=f"lesson {n}", description=f"lesson number {n}",
                                  equipment_id=f"AHU-{n:02d}")
    async with skillbook.get_db() as conn:
        async with conn.execute("SELECT COUNT(*) FROM skills") as cur:
            assert (await cur.fetchone())[0] == 20
