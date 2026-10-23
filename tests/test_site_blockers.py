"""
Phase 0 — things that silently broke WhatsApp and alarm handling on a real site.

Run with ARVIS_ENV=production, because that is where the auth middleware applies:
the Evolution webhook must get through it (it authenticates with its own header
token), nothing else may, and alarm acknowledgement must reach the state engine.
"""
import asyncio
from datetime import timedelta

import pytest

from tests.test_field_checks import RecordingTransport, _upsert, ALI


@pytest.fixture
def prod_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVIS_ENV", "production")
    monkeypatch.setenv("ARVIS_AUTH_SECRET", "site-secret")
    monkeypatch.setenv("ARVIS_EVOLUTION_WEBHOOK_TOKEN", "hook-secret")
    from fastapi.testclient import TestClient
    import agent_commercial.database as dbmod
    import agent_commercial.field_checks as fc
    from agent_commercial.api import auth
    from agent_commercial.api.routes import create_api
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import BMSDatabase
    from agent_commercial.field_checks import FieldCheckService, load_roster

    monkeypatch.setattr(auth, "SECRET_KEY", "site-secret")
    db = BMSDatabase(db_path=str(tmp_path / "site.db"))
    monkeypatch.setattr(dbmod, "get_database", lambda *a, **k: db)
    monkeypatch.setattr(fc, "_service", FieldCheckService(db, RecordingTransport(), roster=load_roster(f"Ali:{ALI}")))
    state = BMSStateEngine()
    with TestClient(create_api(bms_state=state)) as client:
        client.state = state
        client.token = auth.create_access_token({"sub": "eng.sara", "role": "operator"},
                                                expires_delta=timedelta(minutes=5))
        yield client


def test_webhook_passes_production_auth_with_its_own_token(prod_api):
    payload = _upsert({"remoteJid": f"{ALI}@s.whatsapp.net", "fromMe": False, "id": "IN1"}, {"conversation": "hi"})
    ok = prod_api.post("/api/v1/evolution/webhook", json=payload, headers={"x-arvis-webhook-token": "hook-secret"})
    assert ok.status_code == 200 and ok.json()["received"] == 1
    assert prod_api.post("/api/v1/evolution/webhook", json=payload).status_code == 401           # no token
    assert prod_api.post("/api/v1/evolution/webhook", json=payload,
                         headers={"x-arvis-webhook-token": "nope"}).status_code == 401


def test_exemption_is_exact(prod_api):
    hdr = {"x-arvis-webhook-token": "hook-secret"}
    assert prod_api.get("/api/v1/evolution/webhook", headers=hdr).status_code == 401           # other method
    assert prod_api.get("/api/v1/field-checks", headers=hdr).status_code == 401                # other path
    assert prod_api.get("/api/v1/fdd/cases").status_code == 401
    assert prod_api.get("/api/v1/fdd/cases", headers={"Authorization": f"Bearer {prod_api.token}"}).status_code == 200


def test_alarm_acknowledge_reaches_the_state_engine(prod_api):
    from agent_commercial.bms_data_model import Alarm, AlarmSeverity, AlarmState
    alarm = Alarm(equipment_id="AHU-07", message="High supply air temperature", severity=AlarmSeverity.HIGH)
    prod_api.portal.call(prod_api.state.add_alarm, alarm)
    auth = {"Authorization": f"Bearer {prod_api.token}"}
    r = prod_api.post(f"/api/v1/alarms/{alarm.alarm_id}/acknowledge?note=on%20it", headers=auth)
    assert r.status_code == 200 and r.json()["by"] == "eng.sara"
    assert alarm.state == AlarmState.ACKNOWLEDGED and alarm.acknowledged_by == "eng.sara"
    assert prod_api.post("/api/v1/alarms/nope/acknowledge", headers=auth).status_code == 404


@pytest.mark.asyncio
async def test_a_failed_turn_is_answered_not_swallowed(tmp_path):
    """The webhook hands messages to the background; if handling crashes, the person
    is told, instead of talking to silence."""
    from agent_commercial.database import BMSDatabase
    from agent_commercial.ops_engineer.gateway import OpsGateway
    from agent_commercial.ops_engineer.memory import ConversationStore
    from agent_commercial.ops_engineer.people import People
    from tests.test_ops_engineer import Phone, SARA

    class Broken:
        async def respond(self, person, text):
            raise RuntimeError("database is locked")

    db = BMSDatabase(db_path=str(tmp_path / "gw.db"))
    phone = Phone()
    gw = OpsGateway(transport=phone, people=People.parse(f"Sara:{SARA}:fm"), store=ConversationStore(db),
                    engineer=Broken())
    task = gw.spawn_inbound(SARA, "status?", message_id="x1")
    await asyncio.wait_for(task, 5)
    assert phone.to(SARA) == ["Something went wrong on my side handling that — it's logged. "
                              "Could you send it again in a minute?"]
    await db.close()


def test_event_bus_exists_in_every_mode():
    import inspect
    from agent_commercial import main
    src = inspect.getsource(main.OpsCopilot.__init__)
    i = src.index("self._event_bus = EventBus()")
    assert i < src.index("if not self.lite_mode:\n            try:\n                from agent_commercial.anomaly_watchdog")
