"""SLA + escalation + vendor accountability: clock/levels, escalation sweep (dedup),
vendor performance, persistence. Pure + DB; no network."""
from __future__ import annotations

from datetime import datetime, timedelta

from arvisx.sla import (sla_status, escalation_level, priority_of, vendor_performance,
                        run_escalations, DEFAULT_SLA)
from arvisx.persistence import ArvisxDb

NOW = datetime(2026, 6, 14, 12, 0, 0)


def _iss(created_hours_ago, status="open", priority="high", **extra):
    d = {"created_at": (NOW - timedelta(hours=created_hours_ago)).isoformat(timespec="seconds"),
         "status": status, "priority": priority, "severity": "issue"}
    d.update(extra)
    return d


# ── clock + levels ───────────────────────────────────────────────────────
def test_priority_falls_back_to_severity():
    assert priority_of({"severity": "critical"}) == "critical"
    assert priority_of({"severity": "issue"}) == "medium"
    assert priority_of({"priority": "low"}) == "low"


def test_escalation_levels_high_priority():
    # high = (response 4, resolution 24)
    r, res = DEFAULT_SLA["high"]
    assert escalation_level(2, r, res) == 0       # fresh
    assert escalation_level(5, r, res) == 1       # past response → reminder
    assert escalation_level(25, r, res) == 2      # past resolution → supervisor
    assert escalation_level(49, r, res) == 3      # 2x → FM
    assert escalation_level(73, r, res) == 4      # 3x → committee


def test_sla_status_breach_and_resolved():
    st = sla_status(_iss(30, priority="high"), now=NOW)
    assert st["breached_resolution"] is True and st["escalation_level"] == 2 and st["target"] == "supervisor"
    done = sla_status(_iss(99, status="resolved", priority="high"), now=NOW)
    assert done["escalation_level"] == 0 and done["breached_resolution"] is False


def test_sla_config_override():
    cfg = {"high": (1, 2)}
    st = sla_status(_iss(5, priority="high"), cfg=cfg, now=NOW)
    assert st["escalation_level"] >= 2            # 5h with 2h resolution → escalated


# ── vendor performance ───────────────────────────────────────────────────
def test_vendor_performance_ranks_slowest_first():
    issues = [
        {"vendor": "FastFix", "created_at": "2026-06-01T08:00:00", "status": "resolved",
         "escalated_level": 0,
         "history": [{"ts": "2026-06-01T08:00:00", "action": "opened"},
                     {"ts": "2026-06-01T10:00:00", "action": "vendor visited"},
                     {"ts": "2026-06-01T12:00:00", "action": "→ resolved"}]},
        {"vendor": "SlowCo", "created_at": "2026-06-01T08:00:00", "status": "resolved",
         "escalated_level": 2,
         "history": [{"ts": "2026-06-01T08:00:00", "action": "opened"},
                     {"ts": "2026-06-03T08:00:00", "action": "vendor visited"},
                     {"ts": "2026-06-05T08:00:00", "action": "→ resolved"}]},
    ]
    perf = vendor_performance(issues)
    assert perf[0]["vendor"] == "SlowCo"          # slowest resolution first
    assert perf[0]["escalations"] == 1
    ff = next(p for p in perf if p["vendor"] == "FastFix")
    assert ff["avg_response_hours"] == 2.0 and ff["avg_resolution_hours"] == 4.0


# ── escalation sweep (DB) — fires once per level, never on resolved ───────
def test_run_escalations_fires_once_per_level(tmp_path):
    db = ArvisxDb(str(tmp_path / "esc.db"))
    iid = db.create_issue("one-anthem", "DG-2 panel FAULT", asset="DG-2", priority="high",
                          severity="critical", source="auto")
    # backdate created_at to 30h ago (past 24h resolution → level 2)
    old = (datetime.now() - timedelta(hours=30)).isoformat(timespec="seconds")
    with db._conn() as c:
        c.execute("UPDATE checklist_issues SET created_at=? WHERE id=?", (old, iid))

    fired = run_escalations(db, "one-anthem")
    assert any(f["issue_id"] == iid and f["level"] == 2 for f in fired)
    # second sweep — same level, must NOT re-fire
    assert run_escalations(db, "one-anthem") == []
    # a notification was queued for the escalation
    assert any(n["kind"] == "escalation" for n in db.pending_notifications())
    # resolved issues never escalate
    db.update_issue(iid, status="resolved", by="x")
    assert run_escalations(db, "one-anthem") == []


# ── persistence: vendors + sla config ────────────────────────────────────
def test_vendor_registry_and_sla_config(tmp_path):
    db = ArvisxDb(str(tmp_path / "v.db"))
    v = db.add_vendor("one-anthem", "ABC Power", "DG", "98xx")
    assert db.list_vendors("one-anthem")[0]["name"] == "ABC Power"
    assert db.add_vendor("one-anthem", "ABC Power") == v        # re-add reactivates, no dup
    db.set_vendor_active(v, False)
    assert db.list_vendors("one-anthem") == []
    db.set_sla_config("one-anthem", "critical", 0.5, 4)
    assert db.get_sla_config("one-anthem")["critical"] == (0.5, 4)


if __name__ == "__main__":
    import tempfile, pathlib
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, f in fns:
        if "tmp_path" in f.__code__.co_varnames:
            f(pathlib.Path(tempfile.mkdtemp()))
        else:
            f()
        print(f"  ok {name}")
    print(f"PASS — {len(fns)} sla tests")
