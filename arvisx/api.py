"""
ArvisX Phase-1b API — serves the residential dashboard.

Self-contained FastAPI app (separate from the commercial ARVIS API). Holds an
in-memory community (the simulator output for the prototype) and exposes the three
PRD dashboard views + per-asset grounded advisory.

Run:  python -m arvisx.api          # uvicorn on :8090
Endpoints (prefix /api/v1):
  GET  /community/overview          → service-health tiles
  GET  /community/risks             → active risks
  GET  /community/assets            → asset explorer
  GET  /community/report            → all three in one payload
  GET  /asset/{asset_id}/advisory   → grounded RCA advisory for one asset
  POST /scenario/{name}             → reset community state: "healthy" | "prd"
"""
from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

from arvisx.health import assess_asset, build_report
from arvisx.simulator import community_zones, healthy_community, inject_prd_scenario


def _jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/enums/datetimes to JSON-safe values."""
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class _State:
    """Community state. Default = in-memory simulator. With ARVISX_SOURCE=mqtt it is
    a live AssetStore fed by the MQTT ingest adapter (broker on ARVISX_MQTT_BROKER)."""
    def __init__(self):
        from arvisx.workorders import WorkOrderStore
        from arvisx.learning import BaselineStore
        from arvisx.persistence import ArvisxDb
        from arvisx.skillbook import Skillbook
        self.scenario = "prd"
        self.store = None        # set when MQTT source is active
        self._ingest = None
        self.wo_store = WorkOrderStore()
        self.baselines = BaselineStore()
        # Phase 7: institutional memory — warm-start from the SQLite store.
        self.db = ArvisxDb(os.environ.get("ARVISX_DB") or None)
        self.skillbook = Skillbook(self.db)
        from arvisx.commissioning import CommissioningManager
        self.commissioner = CommissioningManager(self.db)
        try:
            self.baselines.load_from(self.db)
            self.wo_store.load_from(self.db)
        except Exception:
            pass
        if os.environ.get("ARVISX_SOURCE", "sim").lower() == "mqtt":
            self._start_mqtt()
        else:
            self.assets = inject_prd_scenario()

    def sync_workorders(self):
        from arvisx.workorders import sync_workorders
        zones = community_zones("healthy" if self.scenario == "healthy" else "prd")
        out = sync_workorders(self.current_assets(), self.wo_store, zones=zones,
                              baselines=(self.baselines if self.store is not None else None),
                              virtual=True, fusion=True, db=self.db, skillbook=self.skillbook)
        try:
            self.wo_store.save_to(self.db)
        except Exception:
            pass
        return out

    def report_now(self):
        # Drift learning only on a LIVE stream (MQTT) — a static sim snapshot has no
        # real variation to learn from. Fixed thresholds carry the sim path.
        assets = self.current_assets()
        zones = community_zones("healthy" if self.scenario == "healthy" else "prd")
        if self.store is not None:
            self.baselines.learn_from_assets(assets)
            try:
                self.baselines.save_to(self.db)        # persist learned normals
            except Exception:
                pass
            return build_report(assets, baselines=self.baselines, virtual=True, zones=zones,
                                fusion=True, water=True)
        # Sim: instantaneous virtual sensors (cycling/duty/turnover) still apply;
        # baseline-dependent ones (power-creep/dry-run) abstain without history.
        return build_report(assets, virtual=True, zones=zones, fusion=True, water=True)

    def _start_mqtt(self):
        from arvisx.store import AssetStore
        from arvisx.ingest.mqtt_adapter import MqttIngest
        # Seed the fleet definition (ids/types/thresholds/maintenance = commissioning);
        # live telemetry then arrives over MQTT and overrides the signals.
        self.store = AssetStore.from_fleet_definition(healthy_community())
        self.assets = self.store.snapshot()
        self.scenario = "mqtt-live"
        broker = os.environ.get("ARVISX_MQTT_BROKER", "localhost")
        port = int(os.environ.get("ARVISX_MQTT_PORT", "1883"))
        self._ingest = MqttIngest(self.store, broker=broker, port=port)
        self._ingest.start(loop=False)   # background network loop

    def current_assets(self):
        return self.store.snapshot() if self.store is not None else self.assets

    def set_scenario(self, name: str):
        if self.store is not None:
            return  # live MQTT source — scenarios don't apply
        if name == "healthy":
            self.assets = healthy_community()
        else:
            self.assets = inject_prd_scenario()
            name = "prd"
        self.scenario = name

    def asset(self, asset_id: str):
        return next((a for a in self.current_assets() if a.asset_id == asset_id), None)


def create_app():
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ArvisX — Residential Operations Intelligence", version="0.1.0-phase1b")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    state = _State()
    app.state.community = state

    @app.get("/api/v1/community/overview")
    async def overview():
        rep = state.report_now()
        return {"scenario": state.scenario, "generated_at": rep.generated_at.isoformat(),
                "community_readiness": rep.readiness, "readiness_band": rep.readiness_band,
                "services": _jsonable(rep.services)}

    @app.get("/api/v1/community/risks")
    async def risks():
        rep = state.report_now()
        return {"count": len(rep.risks), "risks": _jsonable(rep.risks)}

    @app.get("/api/v1/community/assets")
    async def assets():
        rep = state.report_now()
        return {"count": len(rep.assets), "assets": _jsonable(rep.assets)}

    @app.get("/api/v1/community/report")
    async def report():
        return _jsonable(state.report_now())

    @app.get("/api/v1/asset/{asset_id}/advisory")
    async def advisory(asset_id: str):
        from arvisx.advisory import investigate_asset
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        _, rks = assess_asset(a, datetime.now())
        llm = None
        if os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True"):
            try:
                from arvisx.llm_env import load_arvis_env
                load_arvis_env()
                from agent_unified.llm import UnifiedLLM
                llm = UnifiedLLM()
            except Exception:
                llm = None
        adv = await investigate_asset(a, rks, llm=llm)
        out = _jsonable(adv)
        # Institutional memory: surface a prior learned skill for the leading risk.
        if rks:
            note = state.skillbook.recall_note(a, rks[0])
            if note:
                out["institutional_memory"] = note
        return out

    @app.get("/api/v1/asset/{asset_id}/history")
    async def asset_history(asset_id: str):
        return {"asset_id": asset_id, "events": state.db.history(asset_id)}

    @app.post("/api/v1/workorders/{wo_id}/close")
    async def wo_close(wo_id: str, payload: Dict[str, Any] = Body(...)):
        cause = (payload or {}).get("actual_cause", "").strip()
        if not cause:
            raise HTTPException(400, "provide 'actual_cause'")
        wo = state.wo_store.close_with_cause(wo_id, cause, (payload or {}).get("action", ""),
                                             skillbook=state.skillbook, by=(payload or {}).get("by", "vendor"))
        if wo is None:
            raise HTTPException(404, f"unknown work order {wo_id}")
        try:
            state.wo_store.save_to(state.db)
        except Exception:
            pass
        return _jsonable(wo)

    @app.get("/api/v1/skillbook")
    async def skillbook_list():
        return {"skills": state.skillbook.all()}

    # ── Commissioning wizard (Phase 11a) ────────────────────────────────
    def _commission_call(fn):
        from arvisx.commissioning import CommissioningError
        try:
            return _jsonable(fn().to_dict())
        except CommissioningError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/v1/commission/building")
    async def commission_create(payload: Dict[str, Any] = Body(...)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, "provide 'name'")
        return _jsonable(state.commissioner.create_building(name).to_dict())

    @app.get("/api/v1/commission/buildings")
    async def commission_list():
        return {"buildings": state.commissioner.list()}

    @app.get("/api/v1/commission/building/{bid}")
    async def commission_get(bid: str):
        b = state.commissioner.get(bid)
        if b is None:
            raise HTTPException(404, f"unknown building {bid}")
        return _jsonable(b.to_dict())

    @app.post("/api/v1/commission/building/{bid}/services")
    async def commission_services(bid: str, payload: Dict[str, Any] = Body(...)):
        return _commission_call(lambda: state.commissioner.set_services(bid, (payload or {}).get("services", [])))

    @app.post("/api/v1/commission/building/{bid}/assets")
    async def commission_asset(bid: str, payload: Dict[str, Any] = Body(...)):
        return _commission_call(lambda: state.commissioner.add_asset(bid, (payload or {}).get("asset", {})))

    @app.post("/api/v1/commission/building/{bid}/signals")
    async def commission_signal(bid: str, payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        return _commission_call(lambda: state.commissioner.add_signal_map(
            bid, p.get("source", ""), p.get("asset_id", ""), p.get("signal", "")))

    @app.post("/api/v1/commission/building/{bid}/dependencies")
    async def commission_deps(bid: str, payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        return _commission_call(lambda: state.commissioner.set_dependencies(
            bid, p.get("service", ""), p.get("nodes", [])))

    @app.post("/api/v1/commission/building/{bid}/transition")
    async def commission_transition(bid: str, payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        return _commission_call(lambda: state.commissioner.transition(bid, p.get("state", ""), bool(p.get("force"))))

    @app.post("/api/v1/commission/building/{bid}/apply-template")
    async def commission_template(bid: str, payload: Dict[str, Any] = Body(...)):
        return _commission_call(lambda: state.commissioner.apply_template(bid, (payload or {}).get("service", "")))

    @app.post("/api/v1/commission/discover")
    async def commission_discover(payload: Dict[str, Any] = Body(...)):
        """Auto-suggest assets + signal maps from observed MQTT topics (technician confirms)."""
        from arvisx.discovery_assist import suggest_from_topics
        return suggest_from_topics((payload or {}).get("topics", []))

    @app.get("/api/v1/commission/building/{bid}/learning")
    async def commission_learning(bid: str):
        from arvisx.commissioning import CommissioningError
        try:
            return state.commissioner.learning_progress(bid)
        except CommissioningError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/v1/commission/building/{bid}/validations/{val_id}/answer")
    async def commission_validate(bid: str, val_id: str, payload: Dict[str, Any] = Body(...)):
        return _commission_call(lambda: state.commissioner.answer_validation(
            bid, val_id, bool((payload or {}).get("is_normal"))))

    @app.get("/api/v1/water")
    async def water():
        """Water Availability Engine — the hero screen: how much water, for how long, refill."""
        from arvisx.water import assess_water
        bl = state.baselines if state.store is not None else None
        return _jsonable(assess_water(state.current_assets(), bl))

    @app.get("/api/v1/topology")
    async def topology():
        """The asset dependency graph (service → assets in roles)."""
        from arvisx.topology import service_graph
        return {"graph": service_graph()}

    @app.get("/api/v1/impact")
    async def impact():
        """Cascade: current asset risks → service impact → Community Readiness impact."""
        from arvisx.topology import impact_analysis
        rep = state.report_now()
        return {"impacts": _jsonable(impact_analysis(state.current_assets(), rep.risks))}

    @app.post("/api/v1/workorders/sync")
    async def wo_sync():
        return {"status": "ok", **state.sync_workorders()}

    @app.get("/api/v1/workorders")
    async def wo_list():
        state.sync_workorders()   # keep tickets reconciled with current risks
        return {"count": len(state.wo_store.all()), "work_orders": _jsonable(state.wo_store.all())}

    @app.get("/api/v1/workorders/{wo_id}")
    async def wo_get(wo_id: str):
        wo = state.wo_store.get(wo_id)
        if wo is None:
            raise HTTPException(404, f"unknown work order {wo_id}")
        return _jsonable(wo)

    @app.post("/api/v1/workorders/{wo_id}/status/{status}")
    async def wo_status(wo_id: str, status: str):
        from arvisx.models import WorkOrderStatus
        try:
            st = WorkOrderStatus(status)
        except ValueError:
            raise HTTPException(400, f"invalid status '{status}'")
        wo = state.wo_store.set_status(wo_id, st)
        if wo is None:
            raise HTTPException(404, f"unknown work order {wo_id}")
        return _jsonable(wo)

    def _llm_for_reasoning():
        llm = None
        if os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True"):
            try:
                from arvisx.llm_env import load_arvis_env
                load_arvis_env()
                from agent_unified.llm import UnifiedLLM
                llm = UnifiedLLM()
            except Exception:
                llm = None
        return llm

    @app.post("/api/v1/reason/correlate")
    async def reason_correlate():
        """Cross-asset 'thinking': find a common root cause across the active risks."""
        from arvisx.reasoning import correlate
        rep = state.report_now()
        out = await correlate(state.current_assets(), rep.risks, llm=_llm_for_reasoning())
        return _jsonable(out)

    @app.post("/api/v1/ask")
    async def ask_endpoint(payload: Dict[str, Any] = Body(...)):
        """Natural-language Q&A over the live community state."""
        from arvisx.reasoning import ask
        q = (payload or {}).get("question", "").strip()
        if not q:
            raise HTTPException(400, "provide 'question'")
        rep = state.report_now()
        out = await ask(q, state.current_assets(), rep.risks, llm=_llm_for_reasoning())
        return _jsonable(out)

    @app.post("/api/v1/investigate/{asset_id}")
    async def investigate_endpoint(asset_id: str):
        """Agentic multi-step investigation of an asset's active risk (tool-using loop)."""
        from arvisx.agent import investigate
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        rep = state.report_now()
        rk = next((r for r in rep.risks if r.asset_id == asset_id), None)
        if rk is None:
            return {"asset_id": asset_id, "status": "no active risk to investigate"}
        inv = await investigate(a, rk, state.current_assets(), rep.risks, llm=_llm_for_reasoning(),
                                db=state.db, baselines=state.baselines, skillbook=state.skillbook)
        return _jsonable(inv)

    @app.post("/api/v1/monitor")
    async def monitor_endpoint(payload: Dict[str, Any] = Body(default={})):
        """Proactive sweep: autonomously prioritize + investigate the top risks by tier."""
        from arvisx.agent import monitor
        rep = state.report_now()
        cap = int((payload or {}).get("max_investigations", 3))
        invs = await monitor(state.current_assets(), rep.risks, llm=_llm_for_reasoning(),
                             db=state.db, baselines=state.baselines, skillbook=state.skillbook,
                             max_investigations=cap)
        return {"investigated": len(invs), "investigations": _jsonable(invs)}

    @app.post("/api/v1/scenario/{name}")
    async def scenario(name: str):
        state.set_scenario(name)
        return {"status": "ok", "scenario": state.scenario, "assets": len(state.current_assets())}

    @app.get("/")
    async def root():
        return {"service": "ArvisX", "phase": "1b",
                "endpoints": ["/api/v1/community/overview", "/api/v1/community/risks",
                              "/api/v1/community/assets", "/api/v1/community/report",
                              "/api/v1/asset/{asset_id}/advisory", "/api/v1/scenario/{name}"]}
    return app


def main() -> int:
    import uvicorn
    port = int(os.environ.get("ARVISX_API_PORT", "8090"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
