"""Phase C — manual→skills (C1) + historical building memory (C2)."""
from __future__ import annotations

import asyncio
import os
import tempfile

from arvisx.persistence import ArvisxDb
from arvisx import checklist_intel as ci
from arvisx import manual_skills as ms
from arvisx.checklist_agent import CHECKLIST_REGISTRY, build_ctx


# ── C1: extraction helpers ──────────────────────────────────────────────────
def test_interval_days_parsing():
    assert ms._interval_days("every 3 months") == 90
    assert ms._interval_days("quarterly service") == 90
    assert ms._interval_days("annually") == 365
    assert ms._interval_days("every 2 weeks") == 14
    assert ms._interval_days("after 500 hours") is None        # run-hours, not time-based


def test_extract_text_txt():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.txt")
    open(p, "w").write("Rated power 25 kVA. Service every 3 months.")
    from pathlib import Path
    assert "25 kVA" in ms.extract_text(Path(p))


class _FakeLLM:
    def __init__(self, payload): self.payload = payload
    async def ask_json(self, **_): return self.payload


def test_extract_skills_filters_and_derives_intervals():
    payload = {
        "specs": [{"name": "Rated power", "value": "25 kVA"}, {"value": "no name → dropped"}],
        "ppm": [{"task": "Change oil", "interval_text": "every 3 months"},
                {"task": "no interval given", "interval_text": ""},
                {"interval_text": "monthly"}],            # no task → dropped
        "troubleshooting": [{"symptom": "Won't start", "action": "Check fuel"}],
    }
    k = asyncio.run(ms.extract_skills(_FakeLLM(payload), "DG-1", "DG", "manual text here"))
    assert [s["name"] for s in k["specs"]] == ["Rated power"]   # nameless dropped
    tasks = {p["task"]: p for p in k["ppm"]}
    assert tasks["Change oil"]["interval_days"] == 90          # derived from text
    assert tasks["no interval given"]["interval_days"] is None
    assert len(k["ppm"]) == 2                                  # taskless dropped
    assert k["troubleshooting"][0]["symptom"] == "Won't start"


def test_extract_skills_no_llm_returns_empty():
    assert asyncio.run(ms.extract_skills(None, "DG-1", "DG", "text")) == {}


def test_asset_knowledge_persist_and_recall_tool():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "k.db"))
    aid = db.add_asset("one-anthem", "DG-1", kind="DG")
    db.save_asset_knowledge(aid, "one-anthem", "DG-1", "dg.pdf", {
        "specs": [{"name": "Rated power", "value": "25 kVA"}],
        "ppm": [{"task": "Oil change", "interval_text": "quarterly", "interval_days": 90}],
        "troubleshooting": [{"symptom": "Overheat", "action": "Check coolant"}]})
    k = db.get_asset_knowledge_by_name("one-anthem", "DG-1")
    assert k["specs"][0]["value"] == "25 kVA" and k["ppm"][0]["interval_days"] == 90
    # the agent's asset_manual tool surfaces it (grounded recall)
    out = CHECKLIST_REGISTRY.call("asset_manual", build_ctx(db, "one-anthem"), {"asset": "DG-1"})
    assert out["specs"][0]["name"] == "Rated power"
    assert out["troubleshooting"][0]["action"] == "Check coolant"
    # unknown asset → honest 'no knowledge', not invented
    miss = CHECKLIST_REGISTRY.call("asset_manual", build_ctx(db, "one-anthem"), {"asset": "POOL-PUMP"})
    assert "no manual knowledge" in miss["manual"]


def test_knowledge_brief():
    brief = ms.knowledge_brief({"specs": [{"name": "P", "value": "25kVA"}],
                                "ppm": [{"task": "Oil", "interval_days": 90}],
                                "troubleshooting": [{"symptom": "Hot", "action": "Coolant"}]})
    assert "specs:" in brief and "PPM:" in brief and "Hot→Coolant" in brief
    assert ms.knowledge_brief({}) == ""


# ── C2: recurring-issue memory ──────────────────────────────────────────────
def test_recurring_issues_groups_and_counts():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "rec.db"))
    for _ in range(3):
        db.create_issue("one-anthem", "Oil leak at base", asset="DG-1")
    db.create_issue("one-anthem", "Chlorination low", asset="POOL")     # only once
    rec = ci.recurring_issues(db, "one-anthem", min_count=2)
    assert len(rec) == 1
    g = rec[0]
    assert g["asset"] == "DG-1" and g["count"] == 3 and g["open"] == 3


def test_recurring_issues_api_and_tool():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "rec2.db"))
    for _ in range(2):
        db.create_issue("one-anthem", "Pump tripping", asset="BP-1")
    out = CHECKLIST_REGISTRY.call("recurring_issues", build_ctx(db, "one-anthem"), {})
    assert out["recurring"] and out["recurring"][0]["asset"] == "BP-1"


def test_building_memory_endpoint():
    os.environ["ARVISX_DB"] = os.path.join(tempfile.mkdtemp(), "c.db")
    os.environ["ARVIS_X_LLM"] = "0"
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    c = TestClient(create_app())
    for _ in range(2):
        c.post("/api/v1/issues", json={"building": "one-anthem", "title": "Lift stuck", "asset": "LIFT-1"})
    mem = c.get("/api/v1/building/memory", params={"building": "one-anthem"}).json()
    assert mem["recurring"] and mem["recurring"][0]["asset"] == "LIFT-1" and mem["recurring"][0]["count"] == 2
