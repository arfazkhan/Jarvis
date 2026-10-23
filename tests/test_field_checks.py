"""
Field checks — technicians as sensors, over WhatsApp via Evolution API.

The loop runs against the real diagnosis engine (temp BMSDatabase, real case
from process_findings, real answer_question re-ranking). Only the network edge
is replaced: RecordingTransport stands in for Evolution and records what would
have been sent. The Evolution client itself is tested against httpx's
MockTransport with the request/response shapes from Evolution's source.
"""
import json

import httpx
import pytest
import pytest_asyncio

from agent_commercial.fdd import Outcome
from agent_commercial.fdd.diagnosis import list_cases, process_findings
from agent_commercial.fdd.finding import FaultFinding
from agent_commercial.field_checks import FieldCheckService, load_roster, parse_answer
from agent_commercial.messaging import evolution
from agent_commercial.messaging.evolution import EvolutionTransport, parse_webhook, webhook_authorized

ALI, RAVI, STRANGER = "97455501234", "97455505678", "97499999999"


class RecordingTransport:
    def __init__(self):
        self.sent = []          # (kind, to, body)
        self.fail = False

    async def send_check(self, to, body, ref):
        if self.fail:
            raise RuntimeError("Evolution unreachable")
        self.sent.append(("check", to, body))
        return f"wamid.{len(self.sent)}"

    async def send_text(self, to, body):
        self.sent.append(("text", to, body))
        return f"wamid.{len(self.sent)}"


def _f(eq, rule):
    return FaultFinding(rule_id=rule, title=rule, family="ahu", equipment_id=eq, equipment_kind="ahu",
                        outcome=Outcome.FAIL, fault_pct=80.0, fault_hours=5.0)


@pytest_asyncio.fixture
async def svc(tmp_path):
    from agent_commercial.database import BMSDatabase
    db = BMSDatabase(db_path=str(tmp_path / "fc.db"))
    (case,) = await process_findings(db, [_f("FAHU-1", "FC14")])
    t = RecordingTransport()
    s = FieldCheckService(db, t, roster=load_roster("Ali:+974 5550-1234, Ravi:97455505678"), max_chain=2)
    s.case = case
    yield s
    await db.close()


# ── answer parsing ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,ans", [
    ("yes", "yes"), ("YES it is cold", "yes"), ("y", "yes"), ("C12 yes", "yes"), ("نعم", "yes"),
    ("no", "no"), ("No, valve is shut", "no"), ("لا", "no"), ("c3 NO", "no"),
    ("not sure", "unsure"), ("I don't know", "unsure"), ("لا أعرف", "unsure"), ("مش متأكد", "unsure"),
    ("the pump is noisy", None), ("", None), ("not working", None),
])
def test_parse_answer(text, ans):
    assert parse_answer(text) == ans


def test_roster_normalizes_numbers():
    assert load_roster("Ali:+974 5550-1234, bad, :") == {ALI: "Ali"}


# ── the loop ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_check_is_sent_with_the_most_informative_question(svc):
    q = svc.case.diagnosis["next_question"]
    check = await svc.request(svc.case.id, "+974 5550 1234")
    kind, to, body = svc.transport.sent[0]
    assert (kind, to) == ("check", ALI)
    assert q["question"] in body and f"ref {check.ref}" in body and "YES, NO or NOT SURE" in body
    assert check.status == "sent" and check.message_id == "wamid.1" and check.evidence_id == q["evidence_id"]
    # Asking again while it is open does not spam the technician.
    assert (await svc.request(svc.case.id, ALI)).id == check.id and len(svc.transport.sent) == 1


@pytest.mark.asyncio
async def test_only_roster_technicians(svc):
    with pytest.raises(ValueError, match="roster"):
        await svc.request(svc.case.id, STRANGER)
    await svc.request(svc.case.id, ALI)
    assert await svc.on_message(STRANGER, "yes") is None                 # strangers are ignored
    assert len(svc.transport.sent) == 1


@pytest.mark.asyncio
async def test_answer_updates_the_diagnosis_and_asks_the_next_question(svc):
    first = await svc.request(svc.case.id, ALI)
    before = svc.case.diagnosis["posterior"]
    reply = await svc.on_message(ALI, "yes", reply_to=first.message_id, message_id="in.1")

    case = next(c for c in await list_cases(svc.database) if c.id == svc.case.id)
    assert case.answers[first.evidence_id] == "yes"
    assert case.answer_sources[first.evidence_id] == "operator:whatsapp:Ali"   # audit: who, via what
    assert case.diagnosis["posterior"] != before                                # the ranking moved
    top = case.diagnosis["posterior"][0]
    assert reply.startswith("Thanks Ali — recorded.") and top["label"] in reply

    checks = await svc.list_checks()
    assert checks[0].status == "answered" and checks[0].answer == "yes"
    if case.diagnosis.get("next_question"):
        assert checks[1].status == "sent" and checks[1].chain == 2            # the follow-up question
        assert checks[1].evidence_id != first.evidence_id


@pytest.mark.asyncio
async def test_webhook_retry_is_applied_once(svc):
    await svc.request(svc.case.id, ALI)
    await svc.on_message(ALI, "yes", message_id="in.7")
    n_sent, n_checks = len(svc.transport.sent), len(await svc.list_checks())
    assert await svc.on_message(ALI, "yes", message_id="in.7") is None
    assert len(svc.transport.sent) == n_sent and len(await svc.list_checks()) == n_checks


@pytest.mark.asyncio
async def test_not_sure_is_never_turned_into_an_answer(svc):
    check = await svc.request(svc.case.id, ALI)
    reply = await svc.on_message(ALI, "not sure")
    case = next(c for c in await list_cases(svc.database) if c.id == svc.case.id)
    assert check.evidence_id not in case.answers or case.answer_sources.get(check.evidence_id, "").startswith("auto")
    assert (await svc.list_checks())[0].status == "unsure"
    assert "engineer" in reply


@pytest.mark.asyncio
async def test_unclear_reply_asks_again_without_guessing(svc):
    check = await svc.request(svc.case.id, ALI)
    reply = await svc.on_message(ALI, "the pump is noisy")
    assert "please reply YES, NO or NOT SURE" in reply and check.question in reply
    assert (await svc.list_checks())[0].status == "sent"


@pytest.mark.asyncio
async def test_two_open_checks_need_a_reference(svc):
    (case2,) = await process_findings(svc.database, [_f("AHU-07", "FC13")])
    c1 = await svc.request(svc.case.id, ALI)
    c2 = await svc.request(case2.id, ALI)
    reply = await svc.on_message(ALI, "yes")
    assert c1.ref in reply and c2.ref in reply                            # which one?
    await svc.on_message(ALI, f"{c2.ref} no")
    statuses = {c.id: c.status for c in await svc.list_checks()}
    assert statuses[c1.id] == "sent" and statuses[c2.id] == "answered"


@pytest.mark.asyncio
async def test_someone_cannot_answer_another_technicians_check(svc):
    await svc.request(svc.case.id, ALI)
    reply = await svc.on_message(RAVI, "yes")
    assert reply == "No ARVIS check is waiting for you right now."
    assert (await svc.list_checks())[0].status == "sent"


@pytest.mark.asyncio
async def test_undelivered_check_is_marked_failed(svc):
    check = await svc.request(svc.case.id, ALI)
    assert await svc.on_delivery_failure(check.message_id, "WhatsApp reported delivery ERROR") == 1
    assert (await svc.list_checks())[0].status == "failed"
    svc.transport.fail = True
    (case2,) = await process_findings(svc.database, [_f("AHU-07", "FC13")])
    c2 = await svc.request(case2.id, ALI)
    assert c2.status == "failed"                                          # send error recorded, not hidden


@pytest.mark.asyncio
async def test_old_checks_expire(svc):
    check = await svc.request(svc.case.id, ALI)
    conn = await svc._conn()
    await conn.execute("UPDATE field_checks SET created_at = '2000-01-01T00:00:00' WHERE id = ?", (check.id,))
    await conn.commit()
    assert (await svc.list_checks())[0].status == "expired"
    assert await svc.on_message(ALI, "yes") == "No ARVIS check is waiting for you right now."


@pytest.mark.asyncio
async def test_chain_stops_at_the_limit(svc):
    await svc.request(svc.case.id, ALI)
    await svc.on_message(ALI, "yes", message_id="a")
    await svc.on_message(ALI, "no", message_id="b")                      # answers check #2 (max_chain=2)
    checks = await svc.list_checks()
    assert len(checks) <= 2 and all(c.chain <= 2 for c in checks)


# ── Evolution client ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_evolution_send_and_webhook_setup(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers.get("apikey"), json.loads(request.content)))
        if request.url.path.startswith("/message/sendText/"):
            return httpx.Response(201, json={"key": {"remoteJid": "97455501234@s.whatsapp.net", "fromMe": True,
                                                     "id": "3EB0ABC"}, "status": "PENDING",
                                             "message": {"conversation": "hi"}, "messageType": "conversation"})
        return httpx.Response(201, json={"webhook": {"enabled": True}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    t = EvolutionTransport("http://127.0.0.1:8080/", "arvis-site", "inst-key")
    assert await t.send_text(ALI, "hello") == "3EB0ABC"
    assert seen[0][:3] == ("POST", "http://127.0.0.1:8080/message/sendText/arvis-site", "inst-key")
    assert seen[0][3] == {"number": ALI, "text": "hello"}

    await t.configure_webhook("http://127.0.0.1:8000/api/v1/evolution/webhook", "s3cret")
    body = seen[1][3]
    assert seen[1][1].endswith("/webhook/set/arvis-site")
    assert body["webhook"]["headers"] == {"x-arvis-webhook-token": "s3cret"}
    assert body["webhook"]["enabled"] is True and body["webhook"]["events"] == ["MESSAGES_UPSERT", "MESSAGES_UPDATE"]


@pytest.mark.asyncio
async def test_evolution_errors_are_raised(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"status": 400, "error": "Bad Request",
                                            "response": {"message": ["number not on WhatsApp"]}})), **kw))
    with pytest.raises(evolution.EvolutionError, match="400"):
        await EvolutionTransport("http://x", "i", "k").send_text(ALI, "hi")


def _upsert(key, message, context=None):
    data = {"key": key, "pushName": "Ali", "message": message, "messageType": "conversation",
            "messageTimestamp": 1761200000, "instanceId": "x", "source": "android"}
    if context is not None:
        data["contextInfo"] = context
    return {"event": "messages.upsert", "instance": "arvis-site", "data": data,
            "destination": "http://127.0.0.1:8000/api/v1/evolution/webhook",
            "date_time": "2026-10-23T10:00:00.000Z", "sender": "97400000000@s.whatsapp.net",
            "server_url": "http://127.0.0.1:8080", "apikey": None}


def test_parse_text_reply_lid_group_and_own_messages():
    reply = _upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": False, "id": "IN1"},
                    {"conversation": "yes"}, {"stanzaId": "3EB0ABC", "participant": "x"})
    (m,), _ = parse_webhook(reply)
    assert (m.sender, m.text, m.message_id, m.reply_to) == (ALI, "yes", "IN1", "3EB0ABC")

    lid = _upsert({"remoteJid": "123456789@lid", "remoteJidAlt": f"{ALI}@s.whatsapp.net", "fromMe": False,
                   "id": "IN2", "addressingMode": "lid"}, {"conversation": "no"})
    assert parse_webhook(lid)[0][0].sender == ALI
    unresolved = _upsert({"remoteJid": "123456789@lid", "fromMe": False, "id": "IN3"}, {"conversation": "no"})
    group = _upsert({"remoteJid": "1203630@g.us", "fromMe": False, "id": "IN4", "participant": f"{ALI}@s.whatsapp.net"},
                    {"conversation": "yes"})
    own = _upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": True, "id": "IN5"}, {"conversation": "yes"})
    for p in (unresolved, group, own):
        assert parse_webhook(p) == ([], [])


def test_parse_voice_transcript_and_delivery_error():
    voice = _upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": False, "id": "IN6"},
                    {"audioMessage": {"seconds": 3}, "speechToText": "yes the valve is open"})
    assert parse_webhook(voice)[0][0].text == "yes the valve is open"
    update = {"event": "messages.update", "instance": "arvis-site",
              "data": {"keyId": "3EB0ABC", "remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": True, "status": "ERROR"}}
    assert parse_webhook(update)[1][0].message_id == "3EB0ABC"
    ok = dict(update, data=dict(update["data"], status="DELIVERY_ACK"))
    assert parse_webhook(ok) == ([], [])


def test_webhook_token():
    assert webhook_authorized({"x-arvis-webhook-token": "s3cret"}, token="s3cret")
    assert not webhook_authorized({"x-arvis-webhook-token": "nope"}, token="s3cret")
    assert not webhook_authorized({}, token="s3cret")
    assert not webhook_authorized({"x-arvis-webhook-token": ""}, token="")    # unset token never authorizes


# ── API: send a check, receive the answer through the Evolution webhook ──────
def test_api_round_trip(tmp_path, monkeypatch):
    import os
    from datetime import timedelta
    os.environ["ARVIS_AUTH_SECRET"] = "regression-secret"
    from fastapi.testclient import TestClient
    import agent_commercial.database as dbmod
    import agent_commercial.field_checks as fc
    from agent_commercial.api.auth import create_access_token
    from agent_commercial.api.routes import create_api
    from agent_commercial.database import BMSDatabase

    db = BMSDatabase(db_path=str(tmp_path / "api.db"))
    monkeypatch.setattr(dbmod, "get_database", lambda *a, **k: db)
    transport = RecordingTransport()
    monkeypatch.setattr(fc, "_service", FieldCheckService(db, transport, roster=load_roster(f"Ali:{ALI}")))
    monkeypatch.setenv("ARVIS_EVOLUTION_WEBHOOK_TOKEN", "hook-secret")
    monkeypatch.setenv("ARVIS_FIELD_TECHNICIANS", f"Ali:{ALI}")
    tok = create_access_token({"sub": "eng.sara", "role": "operator"}, expires_delta=timedelta(minutes=5))
    auth = {"Authorization": f"Bearer {tok}"}

    with TestClient(create_api()) as client:
        (case,) = client.portal.call(process_findings, db, [_f("FAHU-1", "FC14")])

        assert client.post(f"/api/v1/fdd/cases/{case.id}/field-check", json={"technician": ALI}).status_code == 401
        r = client.post(f"/api/v1/fdd/cases/{case.id}/field-check", json={"technician": ALI}, headers=auth)
        assert r.status_code == 200 and r.json()["ref"] == "C1"
        sent_id = r.json()["message_id"]

        payload = _upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": False, "id": "IN9"},
                          {"conversation": "yes"}, {"stanzaId": sent_id})
        assert client.post("/api/v1/evolution/webhook", json=payload).status_code == 401          # no token
        assert client.post("/api/v1/evolution/webhook", json=payload,
                           headers={"x-arvis-webhook-token": "wrong"}).status_code == 401
        r = client.post("/api/v1/evolution/webhook", json=payload, headers={"x-arvis-webhook-token": "hook-secret"})
        assert r.status_code == 200 and r.json()["received"] == 1

        checks = client.get("/api/v1/field-checks", headers=auth).json()
        assert checks[0]["status"] == "answered" and checks[0]["answer"] == "yes"
        cases = client.get("/api/v1/fdd/cases").json()
        assert cases[0]["answer_sources"][checks[0]["evidence_id"]] == "operator:whatsapp:Ali"

        channel = client.get("/api/v1/field-checks/channel", headers=auth).json()
        assert channel["configured"] and "Evolution API" in channel["notice"]
