"""
Phase 4 — the dashboard's jobs, done from WhatsApp.

Real: temp BMSDatabase, BMSStateEngine + BMSToolHandler (trends), diagnosis cases,
field checks, attention gate, ledger, conversation memory, work-order log, chart
rendering (matplotlib), the Evolution transport (over httpx.MockTransport with the
request/response shapes from Evolution's source). Scripted: the language model, the
WhatsApp phone, and the CAFM system on the far side of its adapter interface.
"""
import asyncio
import base64
import json
import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent_commercial.bms_data_model import BMSDataPoint
from agent_commercial.fdd.diagnosis import list_cases, process_findings
from agent_commercial.ops_engineer.proactive import ProactiveEngineer
from agent_commercial.ops_engineer.work_orders import WorkOrderLog
from tests.test_attention_gate import (HUDA, SARA as G_SARA, SUN_10, SUN_23, LoudLLM, fault_event, gate,  # noqa: F401
                                       process, tick)
from tests.test_field_checks import _f
from tests.test_ops_engineer import ALI, OMAR, SARA, Phone, ScriptedLLM, call, say, site  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n"


class MediaPhone(Phone):
    def __init__(self):
        super().__init__()
        self.media = []

    async def send_media(self, to, data, *, caption="", filename="", mimetype="", delay_ms=None):
        self.media.append({"to": to, "data": data, "caption": caption, "mimetype": mimetype})
        return f"wamid.m{len(self.media)}"


async def run(eng, site, who, tool, **args):
    return json.loads(await eng._run_tool(site.people.get(who), tool, args))


# ── Evolution: sendMedia ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_send_media_posts_bare_base64_in_evolutions_shape(monkeypatch):
    import httpx
    from agent_commercial.messaging.evolution import EvolutionError, EvolutionTransport
    seen = []

    def handler(req):
        seen.append({"url": str(req.url), "apikey": req.headers.get("apikey"), "body": json.loads(req.content)})
        if len(seen) == 2:
            return httpx.Response(400, json={"status": 400, "error": "Bad Request",
                                             "response": {"message": ["Owned media must be a url or base64"]}})
        return httpx.Response(201, json={"key": {"remoteJid": "97455501111@s.whatsapp.net", "fromMe": True,
                                                 "id": "3EB0MEDIA1"}, "status": "PENDING"})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    t = EvolutionTransport("http://127.0.0.1:8080", "tower1", "secret")
    assert await t.send_media("97455501111", PNG + b"data", caption="Last 2 h — …", filename="arvis-trend.png",
                              delay_ms=900) == "3EB0MEDIA1"
    req = seen[0]
    assert req["url"] == "http://127.0.0.1:8080/message/sendMedia/tower1" and req["apikey"] == "secret"
    assert req["body"] == {"number": "97455501111", "mediatype": "image", "mimetype": "image/png",
                           "media": base64.b64encode(PNG + b"data").decode(), "fileName": "arvis-trend.png",
                           "caption": "Last 2 h — …", "delay": 900}
    assert not req["body"]["media"].startswith("data:")              # bare base64, as Evolution checks it
    with pytest.raises(EvolutionError, match="HTTP 400"):
        await t.send_media("97455501111", PNG)


# ── charts ───────────────────────────────────────────────────────────────────
def test_chart_breaks_the_line_over_missing_data_and_renders_a_png():
    from datetime import timezone
    from agent_commercial.ops_engineer.charts import _with_gaps, caption_for, render_trend
    t0 = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    pts = [(t0 + timedelta(minutes=m), v) for m, v in [(0, 14.0), (5, 14.5), (10, 15.0), (40, 13.0), (45, 12.8)]]
    xs, ys = _with_gaps([t for t, _ in pts], [v for _, v in pts])
    assert sum(math.isnan(y) for y in ys) == 1                       # 30 min silence: not drawn through
    assert caption_for({"AHU-07/SAT": pts}, timezone.utc, 1) == \
        "Last 1 h — AHU-07/SAT: 14 → 12.8 (min 12.8 at 09:45, max 15 at 09:10)"
    png = render_trend({"AHU-07/SAT": pts, "AHU-07/SAT_SP": [(t, 13.0) for t, _ in pts]}, tz=timezone.utc,
                       title="AHU-07", mark_at=t0 + timedelta(minutes=20), target=13.0, band=0.5)
    assert png.startswith(PNG) and len(png) > 5000


@pytest.mark.asyncio
async def test_charts_render_concurrently_in_threads():
    from datetime import timezone
    from agent_commercial.ops_engineer.charts import render_trend
    t0 = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    series = {"P": [(t0 + timedelta(minutes=m), float(m % 7)) for m in range(0, 120, 2)]}
    pngs = await asyncio.gather(*[asyncio.to_thread(render_trend, series, tz=timezone.utc, title=f"#{i}")
                                  for i in range(4)])
    assert all(p.startswith(PNG) for p in pngs)


@pytest.mark.asyncio
async def test_show_me_sends_a_chart_with_a_caption_from_the_data(site):
    from agent_commercial.tools.handlers.base import BMSToolHandler
    now = datetime.now().astimezone()
    for m, v in [(-50, 17.9), (-40, 18.2), (-30, 18.0), (-20, 15.1), (-10, 13.4), (0, 13.1)]:
        await site.state.update_point(BMSDataPoint(point_id="AHU-07/SAT", name="Supply air temp", value=v, unit="°C",
                                                   equipment_id="AHU-07",
                                                   timestamp=(now + timedelta(minutes=m)).replace(tzinfo=None)))
    llm = ScriptedLLM(call("send_chart", point_ids=["AHU-07/SAT"], minutes=60, minutes_ago=30, target=13.0),
                      say("That's the last hour — supply air came down after the reset and is holding."))
    eng, gw = site.build(llm)
    eng.tool_handler = BMSToolHandler(bms_state=site.state)
    gw.transport = phone = MediaPhone()
    eng.send_image = gw.send_image
    reply = await gw.on_inbound(SARA, "show me AHU-07 supply air since the reset")

    (img,) = phone.media
    assert img["to"] == SARA and img["data"].startswith(PNG) and img["mimetype"] == "image/png"
    assert img["caption"].startswith("Last 1 h — AHU-07/SAT: 17.9 → 13.1 (min 13.1 at ")
    tool_out = json.loads(next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")["content"])
    assert tool_out["sent"] is True and tool_out["caption"] == img["caption"]
    assert phone.to(SARA) == [reply]                                  # then one text, after the image
    texts = [t.text for t in await site.store.recent(SARA, limit=5)]
    assert any(t.startswith("[chart] Last 1 h") for t in texts)       # ARVIS remembers what it showed


@pytest.mark.asyncio
async def test_chart_says_so_when_there_is_nothing_to_draw_or_no_way_to_send(site):
    from agent_commercial.tools.handlers.base import BMSToolHandler
    eng, gw = site.build(ScriptedLLM())
    eng.tool_handler = BMSToolHandler(bms_state=site.state)
    assert "cannot send images" in (await run(eng, site, SARA, "send_chart", point_ids=["AHU-07/SAT"]))["error"]
    eng.send_image = gw.send_image
    out = await run(eng, site, SARA, "send_chart", point_ids=["NOPE/X"])
    assert out["error"] == "no readings for those points in that window"


# ── answering a diagnosis question directly ──────────────────────────────────
@pytest.mark.asyncio
async def test_fm_answers_the_diagnosis_question_and_the_technician_is_stood_down(site):
    (case,) = await process_findings(site.db, [_f("FAHU-1", "FC14")])
    q = case.diagnosis["next_question"]
    eng, gw = site.build(ScriptedLLM())
    check = await site.checks.request(case.id, ALI, requested_by=SARA)              # Ali was asked the same thing

    assert "facilities manager or a technician" in (await run(eng, site, OMAR, "answer_diagnosis",
                                                              equipment_id="FAHU-1", answer="yes"))["error"]
    unsure = await run(eng, site, SARA, "answer_diagnosis", equipment_id="FAHU-1", answer="not sure")
    assert unsure["recorded"] is False and (await list_cases(site.db, status="open"))[0].answers == case.answers

    out = await run(eng, site, SARA, "answer_diagnosis", equipment_id="FAHU-1", answer="yes")
    assert out["recorded"] and out["question"] == q["question"] and out["technician_checks_closed"] == ["Ali"]
    (now_case,) = await list_cases(site.db, status="open")
    assert now_case.answers[q["evidence_id"]] == "yes"
    assert now_case.answer_sources[q["evidence_id"]] == "operator:whatsapp:Sara"
    assert out["likely_causes"][0]["cause"] == now_case.diagnosis["posterior"][0]["label"]
    (closed,) = await site.checks.list_checks("superseded")
    assert closed.id == check.id and closed.answer == "yes"
    assert site.phone.to(ALI)[-1] == f"No need for check {check.ref} on FAHU-1 — Sara has already answered it. Thanks."
    await site.checks.on_message(ALI, "no")                           # a late reply can't overwrite it
    assert (await list_cases(site.db, status="open"))[0].answers[q["evidence_id"]] == "yes"


@pytest.mark.asyncio
async def test_answer_names_the_question_when_it_is_ambiguous(site):
    await process_findings(site.db, [_f("FAHU-1", "FC14"), _f("FAHU-1", "FC13")])
    eng, _ = site.build(ScriptedLLM())
    out = await run(eng, site, SARA, "answer_diagnosis", equipment_id="FAHU-1", answer="no")
    assert "which one" in out["error"] and {q["rule_id"] for q in out["questions"]} == {"FC13", "FC14"}
    qid = next(q["question_id"] for q in out["questions"] if q["rule_id"] == "FC14")
    out = await run(eng, site, SARA, "answer_diagnosis", equipment_id="FAHU-1", answer="no", question_id=qid)
    assert out["recorded"] and out["rule_id"] == "FC14"


# ── work orders ──────────────────────────────────────────────────────────────
class FlakyCAFM:
    """The site's CAFM, on the far side of the adapter interface: down first, then up."""
    def __init__(self):
        self.up = False
        self.received = []

    async def push_work_order(self, wo):
        self.received.append(wo)
        if not self.up:
            raise ConnectionError("Maximo unreachable")
        return "WO-1001"


@pytest.mark.asyncio
async def test_work_order_from_the_diagnosis_queued_while_cafm_is_down_then_raised(site):
    from agent_commercial.adapters.cafm_adapter import CAFMIntegration
    from agent_commercial.ops_engineer.situation import Situation
    (case,) = await process_findings(site.db, [_f("FAHU-1", "FC14")])
    cafm = FlakyCAFM()
    log = WorkOrderLog(site.db, cafm=CAFMIntegration(cafm))
    eng, gw = site.build(ScriptedLLM())
    eng.work_orders = log

    assert "facilities manager or the owner" in (await run(eng, site, ALI, "raise_work_order",
                                                           equipment_id="FAHU-1"))["error"]
    out = await run(eng, site, SARA, "raise_work_order", equipment_id="FAHU-1", note="before the weekend please")
    assert out["status"] == "queued" and "ConnectionError" in out["error"]
    (wo,) = cafm.received
    top = case.diagnosis["posterior"][0]
    assert wo.equipment_id == "FAHU-1" and wo.work_type == "corrective" and wo.priority == "medium"
    assert "(FC14), confirmed by ARVIS fault detection." in wo.description
    assert f"{top['label']} ({top['p']:.0%})" in wo.description                 # the diagnosis's own numbers
    assert wo.description.endswith("Requested by Sara: before the weekend please")
    assert wo.metadata["case_id"] == case.id

    again = await run(eng, site, SARA, "raise_work_order", equipment_id="FAHU-1")
    assert again["already_open"]["id"] == out["id"] and len(cafm.received) == 1  # no duplicate job
    assert any(r.startswith(f"work order #{out['id']}") for r in await Situation(site.db, work_orders=log)
               .handling("FAHU-1"))                                              # the gate sees it is handled

    pro = ProactiveEngineer(people=site.people, store=site.store, gateway=gw, engineer=eng, gate=None,
                            calendar=None)
    pro.work_orders = log
    assert await pro.retry_work_orders() == 0                                    # still down: kept, not lost
    cafm.up = True
    assert await pro.retry_work_orders() == 1
    assert site.phone.to(SARA)[-1] == "The work order for FAHU-1 is in the maintenance system now: WO-1001."
    assert (await log.open_on("FAHU-1"))[0]["cafm_id"] == "WO-1001"


@pytest.mark.asyncio
async def test_work_order_without_cafm_is_logged_and_a_described_job_needs_no_fault(site):
    eng, _ = site.build(ScriptedLLM())
    eng.work_orders = WorkOrderLog(site.db, cafm=None)
    out = await run(eng, site, OMAR, "raise_work_order", equipment_id="AHU-07")
    assert "ask what the job is" in out["error"]
    out = await run(eng, site, OMAR, "raise_work_order", equipment_id="AHU-07", note="replace the filters",
                    priority="low")
    assert out["status"] == "logged" and "no CAFM" in out["note"] and out["priority"] == "low"
    assert out["description"] == "AHU-07 Requested by Omar: replace the filters"


# ── brief on request ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_brief_me_sends_what_was_held_and_counts_as_todays_brief(gate):
    g = gate(LoudLLM(call("brief_now"), say("That's everything I was holding.")))
    await process(g, fault_event(cost=1200.0), SUN_23)                       # quiet hours → held for the brief
    assert g.phone.sent == []
    pro = ProactiveEngineer(people=g.people, store=g.store, gateway=g.gateway, engineer=g.engineer, gate=g,
                            calendar=g.calendar)
    pro.clock = lambda: g.clock.t
    g.engineer.brief = pro.brief_now

    after_midnight = SUN_23 + timedelta(minutes=90)                          # Monday 00:30
    g.clock.t = after_midnight
    reply = await g.gateway.on_inbound(G_SARA, "can't sleep — brief me")
    brief, last = g.phone.to(G_SARA)
    assert "Supply air above setpoint" in brief and last == reply == "That's everything I was holding."
    assert await g.ledger.pending_for(G_SARA) == []

    await pro.morning_brief(after_midnight + timedelta(hours=6, minutes=30))  # Monday 07:00
    assert len(g.phone.to(G_SARA)) == 2                                      # already had today's
    assert "Supply air above setpoint" in g.phone.to(HUDA)[-1]               # Huda still gets hers


# ── sweep on request ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sweep_on_request_and_what_it_found_is_not_announced_twice(gate):
    g = gate(LoudLLM(call("run_sweep"), say("One new one: AHU-07 supply air is running above setpoint.")))
    runs = []

    async def sweep():
        runs.append(g.clock.t)
        await process(g, fault_event(cost=50.0), g.clock.t)               # the sweep publishes, as main does
        return {"at": datetime.now().isoformat(timespec="seconds"), "window_hours": 24.0, "counts": {"fail": 1},
                "new_faults": ["AHU-07 FC13: Supply air above setpoint"], "fixes_decided": [],
                "new_fault_keys": [{"equipment_id": "AHU-07", "rule_id": "FC13",
                                    "headline": "AHU-07 FC13: Supply air above setpoint"}]}
    g.engineer.run_sweep = sweep
    g.engineer.last_sweep = lambda: {}
    assert "facilities manager or the owner" in json.loads(
        await g.engineer._run_tool(g.people.get("97455501234"), "run_sweep", {}))["error"]

    g.clock.t = SUN_10
    await g.gateway.on_inbound(G_SARA, "check everything again please")
    assert len(runs) == 1 and len(g.phone.to(G_SARA)) == 1
    await tick(g, SUN_10 + timedelta(minutes=10))
    assert len(g.phone.to(G_SARA)) == 1                                      # she heard it in the conversation
    assert len(g.phone.to(HUDA)) == 1 and "AHU-07" in g.phone.to(HUDA)[0]   # Huda didn't: she gets it

    g.engineer.last_sweep = lambda: {"at": (datetime.now() - timedelta(minutes=3)).isoformat(timespec="seconds"),
                                     "counts": {"pass": 40}, "new_faults": []}
    out = json.loads(await g.engineer._run_tool(g.people.get(G_SARA), "run_sweep", {}))
    assert out["note"] == "a sweep ran 3 min ago — this is its result" and len(runs) == 1


@pytest.mark.asyncio
async def test_sweeps_never_overlap():
    from agent_commercial.main import OpsCopilot
    live, peak = [0], [0]

    async def body(hours=None):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.02)
        live[0] -= 1
        return {"at": "x"}
    ops = SimpleNamespace(_run_fdd_sweep=body)
    await asyncio.gather(*[OpsCopilot.run_fdd_sweep(ops) for _ in range(3)])
    assert peak[0] == 1
