"""Golden eval set for the conversational layer — the CI regression gate.

Asserts INVARIANTS, not exact strings (LLM output is nondeterministic): the right
deterministic branch fires, greetings/meta never dump the stats overview, role-scoping
keeps a technician in their lane, the LLM-busy acknowledgement fires only when the model
is down AND nothing is grounded, and the phrasing-sandbox invariance check holds.

Offline cases (llm=None / a raising fake) run in CI. Live-provider cases are marked
`online` and skipped there — run them by hand with a key configured.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from arvisx.checklist_skills import (
    building_qa_deterministic, run_building_qa, _persona,
    _invariants_preserved, render_message, _LLM_BUSY_MSG, _REDIRECT_MSG,
)
from arvisx.persistence import ArvisxDb

T = "2026-06-14"
_FIX = pathlib.Path(__file__).parent / "fixtures" / "golden_messages.json"


def _seed(tmp_path):
    """A fixed building state every golden case is asserted against."""
    db = ArvisxDb(str(tmp_path / "golden.db"))
    db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical", source="auto")
    db.create_issue("one-anthem", "WTP leakage: DETECTED", asset="WTP", source="auto")
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", T, assignee="Ajith")
    db.save_checklist_entry(rid, "wtp_backwash", value="done", status="ok")  # leaves items pending
    return db


# ── the golden set: offline routing + no stats-dump on social/meta ──────────
_CASES = json.loads(_FIX.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _CASES, ids=[c["q"] for c in _CASES])
def test_golden_offline(tmp_path, case):
    db = _seed(tmp_path)
    res = asyncio.run(run_building_qa(None, db, "one-anthem", case["q"], T))
    txt = (res["text"] or "").lower()
    assert txt, f"empty answer for {case['q']!r}"
    for sub in case.get("contains", []):
        assert sub.lower() in txt, f"{case['q']!r} → expected {sub!r} in: {res['text']}"
    for sub in case.get("absent", []):
        assert sub.lower() not in txt, f"{case['q']!r} → {sub!r} should be absent in: {res['text']}"


# ── role-scoping carries no authority but shapes the persona line ───────────
def test_persona_scopes_technician():
    p = _persona({"name": "Rohit", "kind": "technician"})
    assert "Rohit" in p and "TECHNICIAN" in p and "lane" in p.lower()


def test_persona_manager_not_lane_restricted():
    p = _persona({"name": "Sara", "kind": "manager"})
    assert "Sara" in p and "TECHNICIAN" not in p and "lane" not in p.lower()


# ── LLM-busy acknowledgement: only when the model is down AND nothing grounded ──
class _RaisingLLM:
    async def ask_tools(self, *a, **k):
        raise RuntimeError("429 tokens per day limit reached")


def test_busy_message_on_llm_failure_meta(tmp_path):
    db = _seed(tmp_path)
    res = asyncio.run(run_building_qa(_RaisingLLM(), db, "one-anthem", "who created you?", T))
    assert res["source"] == "llm_busy" and res["text"] == _LLM_BUSY_MSG


def test_no_busy_message_when_grounded_answer_exists(tmp_path):
    # Model down, but a status question the deterministic floor can answer → real data, not "busy".
    db = _seed(tmp_path)
    res = asyncio.run(run_building_qa(_RaisingLLM(), db, "one-anthem", "riskiest system?", T))
    assert res["source"] == "deterministic" and "DG-2" in res["text"]
    assert res["text"] != _LLM_BUSY_MSG


def test_no_llm_configured_is_not_busy(tmp_path):
    # No model at all is a setup state, not high-demand — meta falls to the plain redirect.
    db = _seed(tmp_path)
    res = asyncio.run(run_building_qa(None, db, "one-anthem", "who created you?", T))
    assert res["text"] != _LLM_BUSY_MSG and res["text"] == _REDIRECT_MSG


# ── phrasing sandbox: the widened invariance check (#1) ─────────────────────
_TMPL = "⚠️ *Shift I* (2026-06-14) closed INCOMPLETE at 40% — assigned: Rohit."


def test_invariants_clean_rephrase_passes():
    out = "⚠️ Heads up — *Shift I* on 2026-06-14 wrapped at just 40%, assigned to Rohit."
    assert _invariants_preserved(out, _TMPL, locks=["Rohit"])


def test_invariants_swapped_name_fails():
    out = "⚠️ Heads up — *Shift I* on 2026-06-14 wrapped at 40%, assigned to Ajith."
    assert not _invariants_preserved(out, _TMPL, locks=["Rohit"])


def test_invariants_dropped_bold_fails():
    out = "⚠️ Heads up — Shift I on 2026-06-14 wrapped at 40%, assigned to Rohit."
    assert not _invariants_preserved(out, _TMPL, locks=["Rohit"])


def test_invariants_changed_emoji_fails():
    out = "✅ *Shift I* on 2026-06-14 wrapped at 40%, assigned to Rohit."
    assert not _invariants_preserved(out, _TMPL, locks=["Rohit"])


def test_invariants_invented_number_fails():
    out = "⚠️ *Shift I* on 2026-06-14 wrapped at 55%, assigned to Rohit."
    assert not _invariants_preserved(out, _TMPL, locks=["Rohit"])


def test_render_message_no_llm_returns_template():
    assert asyncio.run(render_message(None, _TMPL, facts="")) == _TMPL


# ── #3: shift day-parts come from real template windows, not a hardcoded rule ──
def test_shift_synonyms_from_templates():
    from arvisx.checklist_intel import shift_synonyms
    s = shift_synonyms("one-anthem")
    assert "Shift I" in s and "Shift II" in s and "Shift III" in s
    assert "08:00 AM" in s and "morning" in s          # real hours + mapping instruction
    # the PPM template ('Every 3 months') has no clock window → excluded
    assert "3 months" not in s


def test_shift_synonyms_empty_for_unknown_building():
    from arvisx.checklist_intel import shift_synonyms
    assert shift_synonyms("no-such-building") == ""


# ── live-provider smoke (skipped in CI) ─────────────────────────────────────
@pytest.mark.online
def test_online_qa_grounded(tmp_path):
    from arvisx.llm_client import make_llm
    llm = make_llm()
    if llm is None:
        pytest.skip("no LLM configured")
    db = _seed(tmp_path)
    res = asyncio.run(run_building_qa(llm, db, "one-anthem", "what's the riskiest system?", T))
    assert res["text"]
    # never a fabricated figure — a live answer must still be grounded or fall back cleanly
    assert res["source"] in ("agent", "deterministic", "social")


if __name__ == "__main__":
    import tempfile
    passed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or getattr(fn, "pytestmark", None):
            continue
        argc = fn.__code__.co_argcount
        vars = fn.__code__.co_varnames[:argc]
        if "case" in vars:
            for c in _CASES:
                fn(pathlib.Path(tempfile.mkdtemp()), c)
                passed += 1
        elif "tmp_path" in vars:
            fn(pathlib.Path(tempfile.mkdtemp())); passed += 1
        else:
            fn(); passed += 1
        print(f"  ok {name}")
    print(f"PASS — {passed} golden checks")
