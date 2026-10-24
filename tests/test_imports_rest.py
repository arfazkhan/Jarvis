"""
Phase 6 — history and vendors: trend exports, utility bills (and the bill
document path, which used to invent bills), REST vendor APIs.

Real: BMSDatabase, the importers, document_ingestion, coverage, RestSource over
httpx with a MockTransport standing in for the vendor's server, the egress
policy. Scripted: the vendor server's answers, and the LLM in the one test of
the LLM extraction path.
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio

from agent_commercial.importers.trend_csv import import_trends
from agent_commercial.importers.utility_bills import import_bills_csv, period_end


@pytest_asyncio.fixture
async def db(tmp_path):
    from agent_commercial.database import BMSDatabase
    d = BMSDatabase(db_path=str(tmp_path / "h.db"))
    yield d
    await d.close()


async def _rows(db, where="1=1"):
    conn = await db._get_async_connection()
    async with conn.execute(f"SELECT point_id, value, source, timestamp FROM data_points WHERE {where} "
                            "ORDER BY point_id, timestamp") as cur:
        return [tuple(r) for r in await cur.fetchall()]


# ── trend exports ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_wide_trend_export_becomes_history(db):
    csv_text = ("Timestamp,AHU-01 SAT,AHU-01/RAT\n"
                "2026-09-01 10:00:00,13.1,24.0\n"
                "2026-09-01 10:15:00,13.4,#N/A\n"
                "not a time,1,2\n")
    out = await import_trends(db, csv_text, tz="Asia/Qatar", columns={"AHU-01 SAT": "AHU-01/SAT"})
    assert (out["rows"], out["points"], out["non_numeric"], out["bad_timestamps"]) == (3, 2, 1, 1)
    rows = await _rows(db)
    assert {r[0] for r in rows} == {"AHU-01/SAT", "AHU-01/RAT"} and {r[2] for r in rows} == {"import"}
    expected = datetime(2026, 9, 1, 10, 0).replace(tzinfo=ZoneInfo("Asia/Qatar"))
    assert rows[1][3] == expected.astimezone().replace(tzinfo=None).isoformat()   # Qatar 10:00, stored on this host's clock


@pytest.mark.asyncio
async def test_a_long_export_and_the_timezone_is_never_guessed(db):
    long_csv = "time,point_id,value,unit\n2026-09-01T10:00:00,TANK-1/LVL,61,%\n2026-09-01T11:00:00,TANK-1/LVL,ON,%\n"
    out = await import_trends(db, long_csv, tz="local")
    assert out["rows"] == 2 and [r[1] for r in await _rows(db)] == [61.0, 1.0]
    with pytest.raises(ValueError, match="say which timezone"):
        await import_trends(db, long_csv, tz="")
    with pytest.raises(ValueError, match="no timestamp column"):
        await import_trends(db, "a,b\n1,2\n", tz="local")


@pytest.mark.asyncio
async def test_imported_history_never_reaches_the_live_building(db):
    from agent_commercial.alarms.rule_alarms import RuleAlarms
    from agent_commercial.bms_state_engine import BMSStateEngine
    se = BMSStateEngine()
    ra = RuleAlarms(se)
    ra.load([{"point_id": "TX-1/TEMP", "alarm_when": {"op": ">", "value": 100}}])
    ra.attach()
    await import_trends(db, "timestamp,TX-1/TEMP\n2026-08-01 14:00:00,130\n", tz="local")
    assert se._points == {} and se._alarms == {}                  # history only: no alarm, no current value


@pytest.mark.asyncio
async def test_coverage_counts_imported_history(db):
    from agent_commercial.bms_data_model import Equipment, EquipmentType
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.coverage import assess
    se = BMSStateEngine()
    await se.register_equipment(Equipment(equipment_id="TANK-1", name="t", equipment_type=EquipmentType.WATER_TANK))
    rep = assess(se, imported=[("TANK-1/LVL", "TANK-1")])
    assert rep["equipment"][0]["required"] == [{"need": "tank-level", "state": "imported"}]


# ── utility bills ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bills_become_monthly_meter_points(db):
    out = await import_bills_csv(db, "meter,period,kwh,cost\nMAIN,2026-04,\"45,000\",15000\nMAIN,April,1,1\n")
    assert out["bills"] == 1 and "YYYY-MM" in out["errors"][0]["error"]
    rows = await _rows(db)
    assert [(r[0], r[1]) for r in rows] == [("MAIN/BILL_COST", 15000.0), ("MAIN/BILL_KWH", 45000.0)]
    assert rows[0][3] == period_end("2026-04").isoformat() == "2026-04-30T23:59:59"


# ── the bill document path no longer invents bills ──────────────────────────
@pytest.mark.asyncio
async def test_an_unreadable_document_is_never_filled_in(db, tmp_path):
    from agent_commercial.document_ingestion import IngestionManager
    m = IngestionManager(database=db)
    out = await m.ingest_document(str(tmp_path / "april_utility_elec_bill.png"), "utility_bill")   # doesn't exist
    assert out["status"] == "pending_review" and out["extracted_data"] == {}
    assert await _rows(db) == []                                   # the old fallback "found" 45,000 kWh here


@pytest.mark.asyncio
async def test_bill_text_is_read_but_a_pattern_match_waits_for_review(db, tmp_path):
    from agent_commercial.document_ingestion import IngestionManager, _regex_extract
    text = "Kahramaa — Account 1234. Billing period: Sep 2026. Consumption 38,250 kWh. Amount due QAR 12,817.50"
    assert _regex_extract(text, "utility_bill") == {"utility": "electricity", "consumption_kwh": 38250.0,
                                                    "cost_qar": 12817.5, "period": "2026-09"}
    f = tmp_path / "bill.txt"; f.write_text(text, encoding="utf-8")
    out = await IngestionManager(database=db).ingest_document(str(f), "utility_bill")
    assert out["status"] == "pending_review" and out["confidence"] == .7 and await _rows(db) == []


@pytest.mark.asyncio
async def test_a_bill_the_model_reads_is_recorded(db, tmp_path):
    from agent_commercial.document_ingestion import IngestionManager

    class Model:
        async def generate(self, prompt):
            assert "38,250 kWh" in prompt
            return 'Here: {"utility": "electricity", "consumption_kwh": 38250, "cost_qar": 12817.5, "period": "2026-09"}'
    f = tmp_path / "bill.txt"; f.write_text("Billing period Sep 2026. 38,250 kWh. QAR 12,817.50", encoding="utf-8")
    m = IngestionManager(database=db)
    m.extractor.llm_agent = Model()
    out = await m.ingest_document(str(f), "utility_bill")
    assert out["status"] == "success"
    assert [(r[0], r[1]) for r in await _rows(db)] == [("MAIN/BILL_COST", 12817.5), ("MAIN/BILL_KWH", 38250.0)]


# ── REST vendor APIs ─────────────────────────────────────────────────────────
def _vendor(seen):
    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("authorization")))
        if req.url.path == "/v1/units/2/status":
            return httpx.Response(200, json={"inService": False, "fault": 1, "ts": "2026-10-25T09:00:00Z"})
        if req.url.path == "/v2/plants/77/now":
            return httpx.Response(200, json={"power_kw": "412.5"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_a_vendor_api_is_read_with_one_get_per_path(monkeypatch):
    from agent_commercial.sources.rest_source import RestSource
    monkeypatch.setenv("LIFT_AUTH", "Bearer abc")
    src = RestSource({"id": "lifts", "base_url": "https://api.vendor.example", "headers_env": {"Authorization": "LIFT_AUTH"}})
    src.load_points_from_config({"points": [
        {"point_id": "LIFT-2/INSVC", "path": "/v1/units/2/status", "value": "$.inService", "ts": "$.ts"},
        {"point_id": "LIFT-2/FAULT", "path": "/v1/units/2/status", "value": "$.fault"},
        {"point_id": "PV-1/KW", "path": "/v2/plants/77/now", "value": "$.power_kw", "unit": "kW"}]})
    seen, got = [], []
    src.transport = _vendor(seen)
    src.on_point_update(got.append)
    assert asyncio.run(src.read_all()) == 3
    assert sorted(seen) == [("GET", "/v1/units/2/status", "Bearer abc"), ("GET", "/v2/plants/77/now", "Bearer abc")]
    by = {p.point_id: p for p in got}
    assert (by["LIFT-2/INSVC"].value, by["LIFT-2/FAULT"].value, by["PV-1/KW"].value) == (0.0, 1.0, 412.5)
    assert by["LIFT-2/INSVC"].timestamp.isoformat() == "2026-10-25T09:00:00+00:00" and by["PV-1/KW"].source == "rest:lifts"


def test_a_cloud_host_the_site_has_not_approved_is_refused(monkeypatch):
    from agent_commercial import egress_policy
    from agent_commercial.sources.rest_source import RestSource
    monkeypatch.setattr(egress_policy, "_installed", egress_policy.EgressPolicy.from_allow_list("api.approved.example"))
    with pytest.raises(ValueError, match="not approved for outbound traffic"):
        RestSource({"id": "x", "base_url": "https://api.vendor.example"})
    RestSource({"id": "y", "base_url": "https://api.approved.example"})          # approved: fine
    RestSource({"id": "z", "base_url": "http://10.10.0.40"})                    # on the site LAN: fine


def test_secrets_and_pushes(monkeypatch):
    from agent_commercial.sources.rest_source import RestSource
    with pytest.raises(ValueError, match="headers_env"):
        RestSource({"id": "x", "base_url": "https://a.example", "headers": {"Authorization": "Bearer abc"}})
    monkeypatch.setenv("PUSH_T", "p0sh")
    src = RestSource({"id": "acs", "base_url": "https://a.example", "push_token_env": "PUSH_T"})
    src.load_points_from_config({"points": [{"point_id": "GATE-1/OPEN", "push": True, "value": "$.gate.open"}]})
    got = []
    src.on_point_update(got.append)
    with pytest.raises(PermissionError):
        asyncio.run(src.push({"gate": {"open": True}}, "wrong"))
    assert asyncio.run(src.push({"gate": {"open": True}}, "p0sh")) == 1 and got[0].value == 1.0
    no_token = RestSource({"id": "acs2", "base_url": "https://a.example"})
    with pytest.raises(PermissionError):                                       # no token configured: refuses all
        asyncio.run(no_token.push({}, ""))
