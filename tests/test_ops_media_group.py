"""
Phase 5 — voice notes, photos, the ops group, and the Kev judge.

Real: temp BMSDatabase, conversation memory, field checks, diagnosis cases, the
attention gate + ledger, the media store (files on disk), the Evolution transport
(over httpx.MockTransport, shapes from Evolution's source), the webhook parser.
Scripted: the language model, the WhatsApp phone, the speech model, the vision
model and the Kev decision service — each at its own interface.
"""
import base64
import json
from datetime import timedelta

import pytest

from agent_commercial.bms_data_model import Alarm, AlarmSeverity, AlarmState
from agent_commercial.fdd.diagnosis import process_findings
from agent_commercial.messaging.evolution import InboundMessage, parse_webhook
from agent_commercial.ops_engineer.media import LocalTranscriber, MediaStore, PhotoReader
from agent_commercial.ops_engineer.proactive import ProactiveEngineer
from tests.test_attention_gate import (HUDA, MON_03, SUN_10, LoudLLM, NoLLM, decisions, fault_event,  # noqa: F401
                                       gate, process, tick)
from tests.test_field_checks import _f, _upsert
from tests.test_ops_engineer import ALI, SARA, Phone, ScriptedLLM, call, say, site  # noqa: F401

GROUP = "120363025555@g.us"
ARVIS_JID = "97400000000@s.whatsapp.net"            # the instance's own number (webhook "sender")
ARVIS_LID = "88112233445566@lid"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
OGG = b"OggS-fake-voice"


class MediaPhone(Phone):
    """A phone that also hands back received media and records images sent."""
    def __init__(self, media=None):
        super().__init__()
        self.inbox = media or {}
        self.images = []

    async def fetch_media(self, media):
        mid = media["key"]["id"]
        if mid not in self.inbox:
            raise RuntimeError("media expired")
        return self.inbox[mid]

    async def send_media(self, to, data, *, caption="", filename="", mimetype="", delay_ms=None):
        self.images.append((to, caption))
        return f"wamid.img{len(self.images)}"


class Ears:
    def __init__(self, text=None):
        self.text, self.heard, self.error = text, [], None

    async def transcribe(self, audio):
        self.heard.append(audio)
        if self.text is None:
            self.error = "speech model 'small' unavailable: LocalEntryNotFoundError"
            return None
        return self.text, "en"


class Eyes:
    available = True

    def __init__(self, seen):
        self.seen, self.prompts = seen, []

    def describe(self, image, prompt, max_tokens=1024):
        self.prompts.append(prompt)
        return self.seen


class Blind:
    available = False


def voice(sender, mid, group=None, **kw):
    return InboundMessage(sender=sender, text="", message_id=mid, reply_to=None, kind="voice", group=group,
                          media={"key": {"id": mid}, "message": {"audioMessage": {"ptt": True}}}, **kw)


def photo(sender, mid, caption="", group=None, **kw):
    return InboundMessage(sender=sender, text="", message_id=mid, reply_to=None, kind="image", caption=caption,
                          group=group, media={"key": {"id": mid}, "message": {"imageMessage": {"caption": caption}}},
                          **kw)


def in_group(sender, text, mid, mentions=(), reply_to=None, quoted_author=None):
    return InboundMessage(sender=sender, text=text, message_id=mid, reply_to=reply_to, group=GROUP,
                          mentions=list(mentions), quoted_author=quoted_author, own_jid=ARVIS_JID)


def media_site(site, llm, tmp_path, phone=None, ears=None, eyes=None, group=None):
    eng, gw = site.build(llm)
    gw.transport = phone or MediaPhone()
    site.checks.transport = gw.transport
    gw.group = group
    gw.media_store = eng.media = MediaStore(site.db, directory=str(tmp_path / "media"))
    gw.transcriber = ears
    gw.photos = PhotoReader(eyes) if eyes is not None else None
    eng.send_image = gw.send_image
    return eng, gw


# ── Evolution: media and group shapes ────────────────────────────────────────
def test_parse_media_and_ops_group_messages():
    img = _upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": False, "id": "P1"},
                  {"imageMessage": {"mimetype": "image/jpeg", "caption": "FAHU-1 actuator"}})
    (m,), _ = parse_webhook(img)
    assert (m.kind, m.caption, m.group) == ("image", "FAHU-1 actuator", None)
    assert m.media == {"key": img["data"]["key"], "message": img["data"]["message"]}   # what fetch_media posts back
    (v,), _ = parse_webhook(_upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": False, "id": "V1"},
                                    {"audioMessage": {"seconds": 4, "ptt": True}}))
    assert (v.kind, v.text) == ("voice", "")                                      # ARVIS transcribes it itself

    grp = _upsert({"remoteJid": GROUP, "fromMe": False, "id": "G1", "participant": "5550001@lid",
                   "participantAlt": f"{ALI}@s.whatsapp.net"},
                  {"conversation": "@88112233445566 is AHU-07 ok?"},
                  {"mentionedJid": [ARVIS_LID], "stanzaId": "wamid.9", "participant": ARVIS_LID})
    (g,), _ = parse_webhook(grp, group=GROUP)
    assert (g.sender, g.group, g.mentions, g.reply_to, g.quoted_author, g.own_jid) == \
        (ALI, GROUP, [ARVIS_LID], "wamid.9", ARVIS_LID, "97400000000@s.whatsapp.net")
    assert parse_webhook(grp, group="999@g.us") == ([], [])                       # not the ops group
    assert parse_webhook(grp, group="") == ([], [])                               # group mode off


@pytest.mark.asyncio
async def test_fetch_media_posts_the_received_message_back_to_evolution(monkeypatch):
    import httpx
    from agent_commercial.messaging.evolution import EvolutionError, EvolutionTransport
    seen = []

    def handler(req):
        seen.append((str(req.url), json.loads(req.content)))
        if len(seen) == 2:
            return httpx.Response(400, json={"status": 400, "response": {"message": ["Message not found"]}})
        return httpx.Response(201, json={"mediaType": "imageMessage", "fileName": "P1.jpeg", "caption": "x",
                                         "size": {"fileLength": 12}, "mimetype": "image/jpeg",
                                         "base64": base64.b64encode(JPEG).decode()})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    t = EvolutionTransport("http://127.0.0.1:8080", "tower1", "secret")
    media = {"key": {"id": "P1", "remoteJid": f"{ALI}@s.whatsapp.net"}, "message": {"imageMessage": {}}}
    assert await t.fetch_media(media) == (JPEG, "image/jpeg")
    assert seen[0] == ("http://127.0.0.1:8080/chat/getBase64FromMediaMessage/tower1",
                       {"message": media, "convertToMp4": False})
    with pytest.raises(EvolutionError, match="HTTP 400"):
        await t.fetch_media(media)


# ── voice notes ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_spoken_yes_answers_the_technicians_check(site, tmp_path):
    (case,) = await process_findings(site.db, [_f("FAHU-1", "FC14")])
    llm = ScriptedLLM(call("ask_technician", technician="ali", equipment_id="FAHU-1"),
                      say("Sent Ali the check."))
    phone = MediaPhone({"V1": (OGG, "audio/ogg; codecs=opus")})
    ears = Ears("Yes, it is.")
    eng, gw = media_site(site, llm, tmp_path, phone=phone, ears=ears)
    await gw.on_inbound(SARA, "get Ali to check FAHU-1 please")

    reply = await gw.on_message(voice(ALI, "V1"))
    assert ears.heard == [OGG]
    assert reply.startswith("Thanks Ali — recorded.")                             # the deterministic check path
    assert (await site.checks.list_checks())[0].status == "answered"
    assert len(llm.script) == 0                                                   # no LLM spent on it
    texts = [t.text for t in await site.store.recent(ALI, limit=5)]
    assert "[voice note] Yes, it is." in texts
    conn = await site.db._get_async_connection()
    async with conn.execute("SELECT kind, transcript FROM ops_media") as cur:
        assert [tuple(r) for r in await cur.fetchall()] == [("voice", "Yes, it is.")]   # kept, with what was heard


@pytest.mark.asyncio
async def test_voice_note_it_cannot_hear_gets_an_honest_answer_not_a_guess(site, tmp_path):
    llm = ScriptedLLM()                                                           # must not be called
    eng, gw = media_site(site, llm, tmp_path, phone=MediaPhone({"V2": (OGG, "audio/ogg")}), ears=Ears(None))
    reply = await gw.on_message(voice(SARA, "V2"))
    assert reply.startswith("I couldn't make out that voice note (speech model 'small' unavailable")
    assert site.phone.to(SARA) == [] and gw.transport.to(SARA) == [reply]
    eng2, gw2 = media_site(site, ScriptedLLM(), tmp_path)                         # no speech model on this site
    assert "isn't set up on this site" in await gw2.on_message(voice(SARA, "V3"))


@pytest.mark.asyncio
async def test_local_transcriber_never_downloads_at_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVIS_STT_MODEL_DIR", str(tmp_path / "empty"))
    t = LocalTranscriber(model="small")
    assert await t.transcribe(OGG) is None
    assert t.error and ("unavailable" in t.error or "not installed" in t.error)
    assert not any((tmp_path / "empty").rglob("*.bin"))


@pytest.mark.asyncio
async def test_videos_and_files_are_declined_plainly(site, tmp_path):
    eng, gw = media_site(site, ScriptedLLM(), tmp_path)
    m = InboundMessage(sender=SARA, text="", message_id="D1", reply_to=None, kind="video")
    assert (await gw.on_message(m)).startswith("I can't use videos yet")


# ── photos ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_photo_is_kept_read_and_linked_to_the_equipment_being_checked(site, tmp_path):
    (case,) = await process_findings(site.db, [_f("FAHU-1", "FC14")])
    eyes = Eyes("Valve actuator on a chilled-water pipe. Display reads: POS 0 %. Label: CHW-V-01.")
    llm = ScriptedLLM(call("ask_technician", technician="ali", equipment_id="FAHU-1"), say("Sent."),
                      say("Thanks Ali — the actuator shows 0 %, so the valve is commanded shut. Is the stem moving?"))
    phone = MediaPhone({"P1": (JPEG, "image/jpeg")})
    eng, gw = media_site(site, llm, tmp_path, phone=phone, eyes=eyes)
    await gw.on_inbound(SARA, "get Ali to check FAHU-1 please")

    reply = await gw.on_message(photo(ALI, "P1"))                                 # no caption
    assert "0 %" in reply
    sent_to_llm = llm.calls[-1]["messages"][-1]["content"]
    assert sent_to_llm.startswith("[photo #1 of FAHU-1]")                         # linked via Ali's open check
    assert "read by a vision model" in sent_to_llm and "POS 0 %" in sent_to_llm
    (shot,) = await eng.media.photos_on("FAHU-1")
    assert shot["description"].startswith("Valve actuator") and shot["number"] == ALI
    assert (tmp_path / "media").exists() and any((tmp_path / "media").iterdir())  # the file itself is kept

    # …and the work order carries it as evidence.
    from agent_commercial.ops_engineer.work_orders import WorkOrderLog
    eng.work_orders = WorkOrderLog(site.db)
    out = json.loads(await eng._run_tool(site.people.get(SARA), "raise_work_order", {"equipment_id": "FAHU-1"}))
    assert "Site photos in ARVIS: #1 (" in out["description"]


@pytest.mark.asyncio
async def test_photo_without_a_vision_model_is_kept_and_says_so(site, tmp_path):
    llm = ScriptedLLM(say("I can't see photos on this site — what does the display on AHU-07 say?"))
    eng, gw = media_site(site, llm, tmp_path, phone=MediaPhone({"P2": (JPEG, "image/jpeg")}))
    gw.photos = PhotoReader(Blind())
    await gw.on_message(photo(SARA, "P2", caption="AHU-07 panel"))
    msg = llm.calls[-1]["messages"][-1]["content"]
    assert msg.startswith("[photo #1 of AHU-07] AHU-07 panel")
    assert "could not look at the photo itself: no vision model configured. It is kept as evidence." in msg


@pytest.mark.asyncio
async def test_photo_that_did_not_arrive_costs_no_llm_call(site, tmp_path):
    eng, gw = media_site(site, ScriptedLLM(), tmp_path, eyes=Eyes("x"))
    reply = await gw.on_message(photo(SARA, "GONE"))
    assert reply == "That photo didn't come through to me — could you send it again?"


# ── the ops group ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_group_arvis_reads_along_and_answers_only_when_addressed(site, tmp_path):
    llm = ScriptedLLM(say("Sara mentioned chiller 2 tripping — AHU-07 itself has no open fault right now."),
                      say("Because chiller 2 feeds it; I'd check the CH-2 trip log first."))
    eng, gw = media_site(site, llm, tmp_path, group=GROUP)
    phone = gw.transport

    assert await gw.on_message(in_group(SARA, "chiller 2 tripped again this morning", "g1")) is None
    assert phone.sent == [] and llm.calls == []                                   # not addressed: silent

    reply = await gw.on_message(in_group(ALI, f"@97400000000 what's going on with AHU-07?", "g2",
                                         mentions=[ARVIS_JID]))
    assert phone.sent == [(GROUP, reply)]                                         # answered in the group
    call1 = llm.calls[0]
    assert "team's WhatsApp group" in call1["system"] and "Ali just addressed you" in call1["system"]
    lines = [m["content"] for m in call1["messages"]]
    assert lines[-2:] == ["Sara: chiller 2 tripped again this morning", "Ali: what's going on with AHU-07?"]

    # Replying to ARVIS's message is addressing it — and teaches ARVIS its group identity (@lid).
    await gw.on_message(in_group(SARA, "why?", "g3", reply_to="wamid.1", quoted_author=ARVIS_LID))
    assert len(phone.sent) == 2
    assert ARVIS_LID in await site.store.own_ids()
    llm.script.append(say("Yes."))
    await gw.on_message(in_group(SARA, "@88112233445566 still there?", "g4", mentions=[ARVIS_LID]))
    assert len(phone.sent) == 3
    assert await gw.on_message(in_group(SARA, "@97455509999 can you approve?", "g5",
                                        mentions=["97455509999@s.whatsapp.net"])) is None   # someone else


@pytest.mark.asyncio
async def test_group_messages_are_ignored_when_group_mode_is_off(site, tmp_path):
    eng, gw = media_site(site, ScriptedLLM(), tmp_path, group=None)
    assert await gw.on_message(in_group(SARA, "arvis status?", "g1", mentions=[ARVIS_JID])) is None
    assert gw.transport.sent == []


@pytest.mark.asyncio
async def test_a_chart_asked_for_in_the_group_goes_to_the_group(site, tmp_path):
    from datetime import datetime
    from agent_commercial.bms_data_model import BMSDataPoint
    from agent_commercial.tools.handlers.base import BMSToolHandler
    now = datetime.now()
    for m, v in [(-30, 15.0), (-20, 14.0), (-10, 13.2), (0, 13.0)]:
        await site.state.update_point(BMSDataPoint(point_id="AHU-07/SAT", name="SAT", value=v, unit="°C",
                                                   equipment_id="AHU-07", timestamp=now + timedelta(minutes=m)))
    llm = ScriptedLLM(call("send_chart", point_ids=["AHU-07/SAT"], minutes=60), say("There you go."))
    eng, gw = media_site(site, llm, tmp_path, group=GROUP)
    eng.tool_handler = BMSToolHandler(bms_state=site.state)
    await gw.on_message(in_group(SARA, "arvis show me AHU-07 supply air", "g1"))
    assert [to for to, _ in gw.transport.images] == [GROUP]


@pytest.mark.asyncio
async def test_critical_alarm_is_posted_to_the_group_once_and_on_it_there_acknowledges(gate):
    g = gate(NoLLM())
    g.gateway.group = GROUP
    alarm = Alarm(equipment_id="L3", message="Smoke detected level 3 corridor", severity=AlarmSeverity.CRITICAL)
    await g.state.add_alarm(alarm)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": alarm.to_dict()}}, MON_03)
    posts = g.phone.to(GROUP)
    assert len(posts) == 1 and posts[0].startswith("⚠️") and "Reply 'on it'" in posts[0]   # fixed template
    group_msg_id = f"wamid.{[b for _, b in g.phone.sent].index(posts[0]) + 1}"

    reply = await g.gateway.on_message(in_group(HUDA, "on it", "h1", reply_to=group_msg_id,
                                                quoted_author=ARVIS_LID))
    assert reply == "Thanks Huda — it's yours, I'll stop chasing."
    assert alarm.state == AlarmState.ACKNOWLEDGED and alarm.acknowledged_by == "whatsapp:Huda"
    n = len(g.phone.sent)
    await tick(g, MON_03 + timedelta(minutes=40))
    assert len(g.phone.sent) == n                                                 # ladder stopped for everyone


@pytest.mark.asyncio
async def test_costly_but_not_critical_fault_stays_out_of_the_group(gate):
    g = gate(LoudLLM())
    g.gateway.group = GROUP
    await process(g, fault_event(cost=1200.0), SUN_10)
    assert g.phone.to(GROUP) == []                                                # personal: 1:1 only


@pytest.mark.asyncio
async def test_team_gets_one_morning_summary_in_the_group(gate):
    g = gate(LoudLLM())
    g.gateway.group = GROUP
    pro = ProactiveEngineer(people=g.people, store=g.store, gateway=g.gateway, engineer=g.engineer,
                            gate=g, calendar=g.calendar)
    morning = SUN_10.replace(hour=7)
    g.clock.t = morning
    await pro.morning_brief(morning)
    await pro.morning_brief(morning + timedelta(minutes=5))
    assert len(g.phone.to(GROUP)) == 1


# ── Kev, for the borderline calls ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_kev_can_hold_a_borderline_item_for_the_brief_but_never_louder(gate, monkeypatch):
    from arvis_core.decision import kev
    asked = []

    async def fake_kev(state, instructions, qid="q"):
        asked.append(json.loads(state))
        return 0.2
    monkeypatch.setattr(kev, "ask_noul", fake_kev)
    monkeypatch.setenv("ARVIS_OPS_JUDGE", "kev")
    g = gate(LoudLLM())
    await process(g, fault_event(cost=50.0), SUN_10)                              # medium: borderline SOON
    assert (await decisions(g, SARA))[-1][1:] == ("DIGEST", ["medium", "judge_kev"])
    assert asked[0]["recipient_role"] == "fm" and asked[0]["severity"] == "medium"
    await tick(g, SUN_10 + timedelta(minutes=1))
    assert g.phone.to(SARA) == []                                                 # held for the brief

    n = len(asked)
    alarm = Alarm(equipment_id="L3", message="Smoke detected level 3 corridor", severity=AlarmSeverity.CRITICAL)
    await g.state.add_alarm(alarm)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": alarm.to_dict()}}, SUN_10)
    assert len(asked) == n and g.phone.to(SARA)                                  # safety never goes to Kev


@pytest.mark.asyncio
async def test_without_kev_the_rules_stand(gate, monkeypatch):
    from arvis_core.decision import kev

    async def down(state, instructions, qid="q"):
        return None
    monkeypatch.setattr(kev, "ask_noul", down)
    monkeypatch.setenv("ARVIS_OPS_JUDGE", "kev")
    g = gate(LoudLLM())
    await process(g, fault_event(cost=50.0), SUN_10)
    assert (await decisions(g, SARA))[-1][1:] == ("SOON", ["medium"])
