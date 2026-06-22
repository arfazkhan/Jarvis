"""Usage + cost metrics — WhatsApp (in/out) + LLM (tokens/cost)."""
from __future__ import annotations

import os
import tempfile

from arvisx.persistence import ArvisxDb
from arvisx import metrics


def test_log_usage_and_summary():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "u.db"))
    db.log_usage("b", "whatsapp_in", n=3)
    db.log_usage("b", "whatsapp_out", n=5, cost=0.0)
    db.log_usage("b", "llm", channel="ask", model="K2", prompt_tokens=1000,
                 completion_tokens=200, cost=0.0012)
    db.log_usage("b", "llm", channel="extract", model="K2", prompt_tokens=500,
                 completion_tokens=100, cost=0.0006)
    s = db.usage_summary("0000-01-01T00:00:00")
    assert s["whatsapp"]["in"] == 3 and s["whatsapp"]["out"] == 5 and s["whatsapp"]["total"] == 8
    assert s["llm"]["calls"] == 2
    assert s["llm"]["prompt_tokens"] == 1500 and s["llm"]["completion_tokens"] == 300
    assert s["llm"]["avg_context"] == 750
    assert abs(s["llm"]["cost"] - 0.0018) < 1e-9
    assert set(s["llm"]["by_channel"]) == {"ask", "extract"}
    assert abs(s["total_cost"] - 0.0018) < 1e-9


def test_usage_daily():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "ud.db"))
    db.log_usage("b", "whatsapp_in", n=2)
    db.log_usage("b", "llm", channel="ask", prompt_tokens=10, completion_tokens=5, cost=0.001)
    daily = db.usage_daily("0000-01-01T00:00:00")
    assert len(daily) == 1
    d = daily[0]
    assert d["wa_in"] == 2 and d["llm_calls"] == 1 and d["llm_tokens"] == 15


def test_cost_env_rates(monkeypatch):
    monkeypatch.setenv("ARVISX_LLM_PRICE_IN", "1.0")      # $1 / 1M input tokens
    monkeypatch.setenv("ARVISX_LLM_PRICE_OUT", "2.0")     # $2 / 1M output tokens
    monkeypatch.setenv("ARVISX_WA_MSG_COST", "0.005")
    assert metrics.llm_cost(1_000_000, 0) == 1.0
    assert metrics.llm_cost(0, 1_000_000) == 2.0
    assert metrics.wa_cost(4) == 0.02


def test_recorder_writes_rows():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "r.db"))
    metrics.set_db(db)
    try:
        metrics.record_llm("ask", "K2", 100, 20, building="b")
        metrics.record_whatsapp("in", kind="manager", building="b")
        metrics.record_whatsapp("out", kind="notification", building="b", count=2)
        s = db.usage_summary("0000-01-01T00:00:00")
        assert s["llm"]["calls"] == 1 and s["llm"]["prompt_tokens"] == 100
        assert s["whatsapp"]["in"] == 1 and s["whatsapp"]["out"] == 2
    finally:
        metrics.set_db(None)


def test_wa_ask_records_in_and_out():
    os.environ["ARVISX_DB"] = os.path.join(tempfile.mkdtemp(), "c.db")
    os.environ["ARVIS_X_LLM"] = "0"
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    c = TestClient(create_app())
    c.post("/api/v1/whatsapp/ask", json={"question": "any issues?", "by": "910000000001"})
    db = c.app.state.community.db
    s = db.usage_summary("0000-01-01T00:00:00")
    assert s["whatsapp"]["in"] >= 1 and s["whatsapp"]["out"] >= 1
