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

import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

from arvisx.health import assess_asset, build_report
from arvisx.simulator import community_zones, healthy_community, inject_prd_scenario

logger = logging.getLogger("arvisx.api")


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
        self._sent_alerts: set = set()      # WhatsApp alert dedup across polls
        try:
            self.baselines.load_from(self.db)
            self.wo_store.load_from(self.db)
        except Exception:
            pass
        # Bootstrap an initial owner account if configured and no users exist yet.
        admin_u = os.environ.get("ARVISX_ADMIN_USER", "").strip()
        admin_p = os.environ.get("ARVISX_ADMIN_PASSWORD", "").strip()
        if admin_u and admin_p and self.db.count_users() == 0:
            from arvisx.auth import hash_password
            self.db.create_user(admin_u, "owner", hash_password(admin_p))
        # User auth is enforced when any user exists OR an API key is set.
        self.auth_on = bool(self.db.count_users() > 0 or os.environ.get("ARVISX_API_KEY", "").strip())
        if os.environ.get("ARVISX_SOURCE", "sim").lower() == "mqtt":
            self._start_mqtt()
        else:
            self.assets = inject_prd_scenario()

    def _zones(self):
        """Zones for ghost-energy detection. SIM mode → the demo fixtures. LIVE/MQTT
        mode → only zones the building actually commissioned (none by default), so a
        freshly commissioned building has NO phantom ghost faults from sim fixtures."""
        if self.store is not None:
            return list(getattr(self.store, "zones", None) or [])
        return community_zones("healthy" if self.scenario == "healthy" else "prd")

    def sync_workorders(self):
        from arvisx.workorders import sync_workorders
        zones = self._zones()
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
        zones = self._zones()
        if self.store is not None:
            self.baselines.learn_from_assets(assets)
            try:
                self.baselines.save_to(self.db)        # persist learned normals
            except Exception:
                pass
            return build_report(assets, baselines=self.baselines, virtual=True, zones=zones,
                                fusion=True, water=True, signal_quality=True)
        # Sim: instantaneous virtual sensors (cycling/duty/turnover) still apply;
        # baseline-dependent ones (power-creep/dry-run) abstain without history.
        return build_report(assets, virtual=True, zones=zones, fusion=True, water=True, signal_quality=True)

    def _start_mqtt(self):
        from arvisx.store import AssetStore
        from arvisx.ingest.mqtt_adapter import MqttIngest
        from arvisx.models import Asset, AssetType
        # Seed the fleet definition (ids/types/thresholds/maintenance = commissioning);
        # live telemetry then arrives over MQTT and overrides the signals.
        fleet = healthy_community()
        # Per-apartment gas meters (billing-grade reads). Count via ARVISX_GAS_METERS.
        n_meters = int(os.environ.get("ARVISX_GAS_METERS", "12"))
        fleet += [Asset(f"APT-{100 + i}", f"Apartment {100 + i} Gas Meter", AssetType.GAS_METER)
                  for i in range(1, n_meters + 1)]
        self.store = AssetStore.from_fleet_definition(fleet)
        self.assets = self.store.snapshot()
        self.scenario = "mqtt-live"
        # Timestamped signal history (downsampled) — backs gas billing + the
        # checklist's reading-verification ("the logbook can't be lied to").
        _siglog_interval = float(os.environ.get("ARVISX_SIGLOG_INTERVAL_S", "600"))

        def _log_signal(asset_id, signal, value=None):
            try:
                self.db.log_signal(asset_id, signal, value, min_interval_s=_siglog_interval)
            except Exception:
                pass

        self.store.set_update_callback(_log_signal)
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
    import asyncio
    import hmac
    from contextlib import asynccontextmanager

    from fastapi import Body, FastAPI, Header, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    @asynccontextmanager
    async def lifespan(_app):
        # Startup: optionally run the autonomous heartbeat (ARVISX_HEARTBEAT=1).
        state._last_tick = getattr(state, "_last_tick", None)
        if os.environ.get("ARVISX_HEARTBEAT", "").strip() in ("1", "true", "True"):
            from arvisx.scheduler import Heartbeat, community_tick
            interval = float(os.environ.get("ARVISX_HEARTBEAT_INTERVAL", "300"))

            async def _tick(n):
                state._last_tick = await community_tick(state, llm=_llm_for_reasoning())

            state._hb = Heartbeat(_tick, interval_s=interval)
            state._hb_task = asyncio.create_task(state._hb.run())
            logger.info(f"[ArvisX] heartbeat started (every {interval}s)")
        try:
            yield
        finally:
            # Shutdown: stop the heartbeat and let its task unwind.
            hb = getattr(state, "_hb", None)
            if hb is not None:
                hb.stop()
            task = getattr(state, "_hb_task", None)
            if task is not None:
                task.cancel()

    app = FastAPI(title="ArvisX — Residential Operations Intelligence", version="0.2.0",
                  lifespan=lifespan)
    # CORS: lock to configured origins when ARVISX_CORS is set, else open (dev).
    _origins = [o.strip() for o in os.environ.get("ARVISX_CORS", "*").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])

    # ── API-key auth ────────────────────────────────────────────────────
    # When ARVISX_API_KEY is set, every /api/v1 call must present it as
    # `Authorization: Bearer <key>` or `X-API-Key: <key>`. Unset = open (dev) + warn.
    _api_key = os.environ.get("ARVISX_API_KEY", "").strip()
    if not _api_key:
        logger.warning("[ArvisX] ARVISX_API_KEY not set — API is OPEN (dev mode). Set it for any networked pilot.")

    state = _State()
    app.state.community = state

    # Auth: API key (server) OR user Bearer token (browser). Writes (non-GET) require
    # an owner/fm role; reads need any authenticated identity. Login is exempt.
    from arvisx import auth as _auth_mod
    _EXEMPT = {"/api/v1/auth/login"}

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/v1") or path in _EXEMPT:
            return await call_next(request)
        if not (_api_key or state.auth_on):
            request.state.role = "system"          # dev mode: wide open
            return await call_next(request)
        authz = request.headers.get("authorization", "")
        # EventSource (SSE) can't set headers → allow ?token= for the stream.
        if not authz and request.query_params.get("token"):
            authz = "Bearer " + request.query_params["token"]
        sub, role = _auth_mod.identify(authz, request.headers.get("x-api-key", ""), _api_key)
        if role is None:
            return JSONResponse({"detail": "unauthorized — log in or present an API key"}, status_code=401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _auth_mod.role_can_write(role):
            return JSONResponse({"detail": "forbidden — this action requires an owner/fm role"}, status_code=403)
        request.state.sub, request.state.role = sub, role
        return await call_next(request)

    # ── auth endpoints ───────────────────────────────────────────────────
    @app.post("/api/v1/auth/login")
    async def login(payload: Dict[str, Any] = Body(...)):
        u = str((payload or {}).get("username", "")).strip()
        pw = str((payload or {}).get("password", ""))
        rec = state.db.get_user(u) if u else None
        if not rec or not _auth_mod.verify_password(pw, rec["pw_hash"]):
            raise HTTPException(401, "invalid credentials")
        return {"token": _auth_mod.make_token(u, rec["role"]), "role": rec["role"], "username": u}

    @app.get("/api/v1/auth/me")
    async def whoami(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        sub, role = _auth_mod.identify(authorization, x_api_key, _api_key)
        return {"username": sub, "role": role}

    @app.post("/api/v1/auth/users")
    async def create_user_ep(payload: Dict[str, Any] = Body(...),
                             authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        _, role = _auth_mod.identify(authorization, x_api_key, _api_key)
        if role not in ("system", "owner"):
            raise HTTPException(403, "only owner/system can create users")
        p = payload or {}
        u, pw, role = str(p.get("username", "")).strip(), str(p.get("password", "")), str(p.get("role", "viewer"))
        if not u or not pw or role not in _auth_mod.ALL_ROLES:
            raise HTTPException(400, "need username, password, role in {owner,fm,viewer}")
        state.db.create_user(u, role, _auth_mod.hash_password(pw))
        return {"username": u, "role": role}

    @app.get("/api/v1/community/overview")
    async def overview():
        rep = state.report_now()
        return {"scenario": state.scenario, "generated_at": rep.generated_at.isoformat(),
                "community_readiness": rep.readiness, "readiness_band": rep.readiness_band,
                "services": _jsonable(rep.services)}

    @app.get("/api/v1/community/risks")
    async def risks(limit: int = 200, offset: int = 0):
        rep = state.report_now()
        page = rep.risks[offset:offset + limit]
        return {"count": len(rep.risks), "limit": limit, "offset": offset, "risks": _jsonable(page)}

    @app.get("/api/v1/community/assets")
    async def assets(limit: int = 200, offset: int = 0):
        rep = state.report_now()
        page = rep.assets[offset:offset + limit]
        return {"count": len(rep.assets), "limit": limit, "offset": offset, "assets": _jsonable(page)}

    @app.get("/api/v1/community/report")
    async def report():
        return _jsonable(state.report_now())

    @app.get("/api/v1/asset/{asset_id}")
    async def asset_state(asset_id: str):
        """Single asset: live state + its current risks (for the asset detail screen)."""
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        rep = state.report_now()
        return {"asset": _jsonable(a),
                "risks": _jsonable([r for r in rep.risks if r.asset_id == asset_id])}

    @app.get("/api/v1/asset/{asset_id}/advisory")
    async def advisory(asset_id: str):
        from arvisx.advisory import investigate_asset
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        _, rks = assess_asset(a, datetime.now())
        adv = await investigate_asset(a, rks, llm=_llm_for_reasoning())
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

    @app.get("/api/v1/signal-quality")
    async def signal_quality():
        """Sensor health: quarantined bad readings, stale signals, and per-signal quality findings."""
        rep = state.report_now()
        sensor_risks = [r for r in rep.risks if "sensor" in r.message.lower()]
        out = {"sensor_findings": _jsonable(sensor_risks)}
        if state.store is not None:
            out["quarantined"] = state.store.quarantined[-50:]
            out["stale_signals"] = state.store.stale_signals()
        return out

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
    async def wo_list(limit: int = 200, offset: int = 0):
        state.sync_workorders()   # keep tickets reconciled with current risks
        allwo = state.wo_store.all()
        return {"count": len(allwo), "limit": limit, "offset": offset,
                "work_orders": _jsonable(allwo[offset:offset + limit])}

    @app.post("/api/v1/workorders/from-risk")
    async def wo_from_risk(payload: Dict[str, Any] = Body(...)):
        """Create ONE work order for an asset's current risk (the per-risk button).
        Optional 'message' picks a specific risk; default = the asset's top risk."""
        from arvisx.workorders import open_work_order
        asset_id = str((payload or {}).get("asset_id", "")).strip()
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        rep = state.report_now()
        cand = [r for r in rep.risks if r.asset_id == asset_id]
        if not cand:
            raise HTTPException(409, f"no active risk on {asset_id} to ticket")
        want = str((payload or {}).get("message", "")).strip().lower()
        risk = next((r for r in cand if want and want in r.message.lower()), cand[0])
        wo = open_work_order(state.wo_store, a, risk, db=state.db, skillbook=state.skillbook)
        try:
            state.wo_store.save_to(state.db)
        except Exception:
            pass
        return _jsonable(wo)

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
        if os.environ.get("ARVIS_X_LLM", "").strip() not in ("1", "true", "True"):
            return None
        try:
            from arvisx.llm_env import load_arvis_env
            load_arvis_env()                       # provider creds from repo .env
            from arvisx.llm_client import make_llm
            return make_llm()                      # ARVISX_LLM_PROVIDER (default k2think)
        except Exception:
            return None

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
                                db=state.db, baselines=state.baselines, skillbook=state.skillbook,
                                store=state.store, wo_store=state.wo_store)
        try:
            from dataclasses import asdict
            state.db.save_investigation(inv.asset_id, inv.trigger, inv.root_cause,
                                        inv.recommended_action, inv.confidence_band, inv.source, asdict(inv))
        except Exception:
            pass
        return _jsonable(inv)

    @app.post("/api/v1/monitor")
    async def monitor_endpoint(payload: Dict[str, Any] = Body(default={})):
        """Proactive sweep: autonomously prioritize + investigate the top risks. Rules
        handle the routine; the agent is auto-invoked only where escalation policy fires."""
        from arvisx.agent import monitor
        rep = state.report_now()
        cap = int((payload or {}).get("max_investigations", 3))
        zones = state._zones()
        invs = await monitor(state.current_assets(), rep.risks, llm=_llm_for_reasoning(),
                             db=state.db, baselines=state.baselines, skillbook=state.skillbook,
                             max_investigations=cap, store=state.store, zones=zones,
                             wo_store=state.wo_store)
        return {"investigated": len(invs), "investigations": _jsonable(invs)}

    @app.post("/api/v1/incident/{asset_id}")
    async def incident_endpoint(asset_id: str):
        """One incident, the ArvisX way: deterministic advisory always; the agent is
        auto-invoked only when rules can't cleanly resolve it (escalation policy)."""
        from arvisx.escalation import handle_incident
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        rep = state.report_now()
        rk = next((r for r in rep.risks if r.asset_id == asset_id), None)
        if rk is None:
            return {"asset_id": asset_id, "status": "no active risk", "route": "none"}
        zones = state._zones()
        out = await handle_incident(a, rk, state.current_assets(), rep.risks,
                                    llm=_llm_for_reasoning(), db=state.db, baselines=state.baselines,
                                    skillbook=state.skillbook, store=state.store, zones=zones,
                                    wo_store=state.wo_store)
        return _jsonable(out)

    @app.post("/api/v1/commission/building/{bid}/evaluate-readiness")
    async def commission_readiness(bid: str):
        """Data-driven ops-readiness gate: approve LEARNING→OPERATIONAL when the baselines
        are statistically trustworthy, else extend the learning window dynamically."""
        try:
            verdict = state.commissioner.evaluate_ops_readiness(
                bid, state.current_assets(), state.baselines)
        except Exception as e:
            raise HTTPException(400, str(e))
        return _jsonable(verdict)

    @app.post("/api/v1/commission/building/{bid}/check-anomalies")
    async def commission_anomalies(bid: str, payload: Dict[str, Any] = Body(default={})):
        """Detect config/reality mismatches (unmapped device, untyped/unsignaled asset, bad
        sensor) and let the agent explain each — why it matters + the fix. Read-only."""
        from arvisx.commission_check import detect_commissioning_anomalies, narrate_anomalies
        cfg = state.commissioner.get(bid)
        if cfg is None:
            raise HTTPException(404, f"unknown building {bid}")
        topics = (payload or {}).get("observed_topics") or None
        anomalies = detect_commissioning_anomalies(cfg, observed_topics=topics, store=state.store)
        narrated = await narrate_anomalies(anomalies, cfg, llm=_llm_for_reasoning())
        return {"building_id": bid, "count": len(narrated), "anomalies": narrated}

    # ── Heartbeat: ArvisX runs its own checks on a cadence ───────────────
    @app.post("/api/v1/heartbeat/tick")
    async def heartbeat_tick():
        """Run one heartbeat now: refresh → monitor sweep (escalation-aware) → readiness
        re-check for learning buildings."""
        from arvisx.scheduler import community_tick
        state._last_tick = await community_tick(state, llm=_llm_for_reasoning())
        return _jsonable(state._last_tick)

    @app.get("/api/v1/investigations")
    async def investigations_history(asset_id: str = "", limit: int = 20):
        """Durable agent memory: past investigations (optionally for one asset)."""
        return {"investigations": state.db.recent_investigations(asset_id or None, limit)}

    @app.get("/api/v1/watches")
    async def open_watches():
        """Active watches that survived restart (the agent's pending observations)."""
        return {"watches": state.db.load_open_watches()}

    @app.get("/api/v1/heartbeat/history")
    async def heartbeat_history(limit: int = 50):
        """Recorded heartbeat ticks — the building's pulse over time."""
        return {"ticks": state.db.recent_ticks(limit)}

    @app.get("/api/v1/events/stream")
    async def events_stream(interval: float = 5.0):
        """Server-Sent Events for live tiles: readiness, risk count, open work orders.
        EventSource can't set headers — pass the token as ?token=… (handled in auth).
        The stream ends when the client disconnects (generator is cancelled)."""
        import asyncio
        import json as _json

        async def gen():
            while True:
                rep = state.report_now()
                open_wo = sum(1 for w in state.wo_store.all()
                              if w.status.value in ("open", "acknowledged", "in_progress"))
                payload = {"ts": rep.generated_at.isoformat(), "readiness": rep.readiness,
                           "band": rep.readiness_band, "risks": len(rep.risks), "open_work_orders": open_wo}
                yield f"data: {_json.dumps(payload)}\n\n"
                await asyncio.sleep(max(1.0, float(interval)))

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/v1/heartbeat/status")
    async def heartbeat_status():
        return {"running": getattr(state, "_hb", None) is not None,
                "interval_s": float(os.environ.get("ARVISX_HEARTBEAT_INTERVAL", "300")),
                "ticks": getattr(getattr(state, "_hb", None), "ticks", 0),
                "last_tick": _jsonable(getattr(state, "_last_tick", None))}

    # (heartbeat start/stop is handled by the lifespan context manager above)

    # ── WhatsApp operational layer (Phase 14) — deterministic, no LLM ────
    _ACTION_ROLES = {"owner", "fm", "facility_manager"}

    @app.get("/api/v1/whatsapp/digest")
    async def wa_digest():
        from arvisx.messaging import daily_digest
        return {"text": daily_digest(state.report_now())}

    @app.post("/api/v1/whatsapp/ask")
    async def wa_ask(payload: Dict[str, Any] = Body(...)):
        from arvisx.messaging import answer
        p = payload or {}
        q = str(p.get("question", "")).strip()
        role = str(p.get("role", "viewer")).lower()
        by = str(p.get("by", "")).strip()        # sender number (resident requests)
        if not q:
            raise HTTPException(400, "provide 'question'")
        # Building phase (learning vs operational) drives the situation-aware answers.
        try:
            blds = state.commissioner.list()
            phase = "operational" if any(b.get("state") == "operational" for b in blds) else "learning"
        except Exception:
            phase = "operational"
        res = answer(q, state.report_now(), state.current_assets(),
                     state.baselines if state.store is not None else None, role=role, phase=phase)
        if res.get("action") == "resident_request":
            # Record FIRST, confirm after — 'noted' is only said once it's true.
            rid = state.db.save_resident_request(by, res.get("request_text") or q)
            res["text"] = (f"✅ Noted — your request has been logged for the building team "
                           f"(ref RR-{rid}). For emergencies, contact the facility desk directly.")
        elif res.get("action") == "create_work_order":
            if role not in _ACTION_ROLES:
                res["text"] = "⛔ Creating work orders requires a facility-manager role. Ask your FM."
            else:
                state.sync_workorders()
                openwos = [w for w in state.wo_store.all() if w.status.value in ("open", "acknowledged", "in_progress")]
                ids = ", ".join(w.wo_id for w in openwos[:6])
                res["text"] = f"✅ {len(openwos)} open work order(s): {ids or '(none)'}"
        return {"intent": res["intent"], "text": res["text"]}

    @app.get("/api/v1/whatsapp/alerts")
    async def wa_alerts():
        """New alerts to push (severity>=WARNING + confidence Medium/High, deduped across
        polls). Open resident requests ride the same poll so the building team hears about
        them on the next tick. They stay 'open' until the bot ACKS the WhatsApp send
        (POST /whatsapp/resident-requests/ack) — a crash mid-push re-delivers next poll:
        at-least-once, never silently lost (worst case the team sees a duplicate)."""
        from arvisx.messaging import pending_alerts
        bl = state.baselines if state.store is not None else None
        alerts, sent = pending_alerts(state.report_now(), state._sent_alerts, state.current_assets(), bl)
        state._sent_alerts = sent
        for rr in state.db.resident_requests(status="open"):
            sender = f" from +{rr['by_user']}" if rr.get("by_user") else ""
            alerts.append({
                "signature": f"resident_request::{rr['id']}", "severity": "info",
                "service": "resident_request", "asset_id": "",
                "text": (f"📩 *Resident request* RR-{rr['id']}{sender}\n\n{rr['text']}\n\n"
                         f"Reply 'create work order' to raise a ticket."),
                "resident_text": "",            # ops-only — never echoed to resident groups
            })
        return {"count": len(alerts), "alerts": alerts}

    @app.post("/api/v1/whatsapp/resident-requests/ack")
    async def resident_requests_ack(payload: Dict[str, Any] = Body(...)):
        """Bot confirms it DELIVERED resident-request pings to the team — only then do
        they stop riding the alerts poll."""
        ids = (payload or {}).get("ids") or []
        acked = []
        for i in ids:
            try:
                state.db.set_resident_request_status(int(i), "notified")
                acked.append(int(i))
            except (TypeError, ValueError):
                continue
        return {"acked": acked}

    @app.get("/api/v1/resident-requests")
    async def resident_requests(status: str = ""):
        """Resident maintenance requests (open / notified / closed) — frontend list."""
        return {"requests": state.db.resident_requests(status or None)}

    @app.get("/api/v1/costs")
    async def costs():
        """Economic layer — 'what is this costing us?' (waste/month + failure exposure)."""
        from arvisx.economics import community_cost
        bl = state.baselines if state.store is not None else None
        return community_cost(state.report_now(), state.current_assets(), bl)

    # ── Gas metering: the month-end statement writes itself (Phase 17) ───
    @app.get("/api/v1/gas/billing")
    async def gas_billing(month: str = "", format: str = "json"):
        """Per-apartment gas consumption from continuous meter telemetry — replaces
        the manual month-end meter round. format=csv for the billing person."""
        from arvisx.gas_billing import monthly_statement, statement_csv
        stmt = monthly_statement(state.db, month or None)
        if format.lower() == "csv":
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(statement_csv(stmt), media_type="text/csv")
        return stmt

    # ── Daily checklist: auto-filled, verified, prompted (Phase 17b) ─────
    @app.get("/api/v1/checklist/today")
    async def checklist_today(date: str = ""):
        """The self-writing daily log: telemetry items auto-filled, physical items
        from technician replies, submitted readings with verification verdicts."""
        from arvisx.checklist import daily_log
        return daily_log(state.current_assets(), state.db, date or None)

    @app.post("/api/v1/checklist/submit-reading")
    async def checklist_submit_reading(payload: Dict[str, Any] = Body(...)):
        """A human-submitted meter/gauge reading — verified against recorded telemetry
        at the claimed time. Mismatch = flagged (pencil-whip detection)."""
        from arvisx.checklist import verify_reading
        p = payload or {}
        asset_id = str(p.get("asset_id", "")).strip()
        signal = str(p.get("signal", "")).strip()
        try:
            value = float(p.get("value"))
        except (TypeError, ValueError):
            raise HTTPException(400, "provide numeric 'value'")
        if not asset_id or not signal:
            raise HTTPException(400, "provide 'asset_id' and 'signal'")
        claimed = p.get("claimed_ts")
        claimed_dt = datetime.fromisoformat(claimed) if claimed else None
        v = verify_reading(state.db, asset_id, signal, value, claimed_dt, str(p.get("unit", "")))
        state.db.save_checklist_response(
            item_id=f"reading:{asset_id}:{signal}",
            date=(claimed_dt or datetime.now()).strftime("%Y-%m-%d"),
            status="submitted", note=v.note, by_user=str(p.get("by", "")),
            verdict=v.verdict)
        return _jsonable(v)

    @app.post("/api/v1/checklist/physical")
    async def checklist_physical(payload: Dict[str, Any] = Body(...)):
        """Record a technician's physical-check response (ok / issue + note)."""
        from arvisx.checklist import PHYSICAL_ITEMS
        p = payload or {}
        item_id = str(p.get("item_id", "")).strip()
        if item_id not in {i for i, _, _ in PHYSICAL_ITEMS}:
            raise HTTPException(400, f"unknown checklist item '{item_id}'")
        status = str(p.get("status", "ok")).lower()
        if status not in ("ok", "issue"):
            raise HTTPException(400, "status must be 'ok' or 'issue'")
        state.db.save_checklist_response(
            item_id=item_id, date=datetime.now().strftime("%Y-%m-%d"),
            status=status, note=str(p.get("note", "")), by_user=str(p.get("by", "")))
        return {"recorded": True, "item_id": item_id, "status": status}

    @app.get("/api/v1/whatsapp/checklist-prompts")
    async def wa_checklist_prompts():
        """Physical-check prompts still pending today — the bot sends these to the
        technician ('pump room visual check? reply OK / photo')."""
        from arvisx.checklist import pending_prompts
        return {"prompts": pending_prompts(state.db)}

    @app.post("/api/v1/whatsapp/checklist-reply")
    async def wa_checklist_reply(payload: Dict[str, Any] = Body(...)):
        """A technician's WhatsApp reply ('ok pump_room_visual' / 'issue ... <note>')
        — parsed and timestamped into the same daily log."""
        from arvisx.checklist import parse_checklist_reply
        p = payload or {}
        parsed = parse_checklist_reply(str(p.get("text", "")))
        if parsed is None:
            return {"recorded": False,
                    "hint": "reply like: ok pump_room_visual — or: issue gen_room_visual oil leak"}
        state.db.save_checklist_response(
            item_id=parsed["item_id"], date=datetime.now().strftime("%Y-%m-%d"),
            status=parsed["status"], note=parsed["note"], by_user=str(p.get("by", "")))
        return {"recorded": True, **parsed}

    # ── Phase-0 digitized checklists (NO sensors) — the paper-sheet replacement ──
    def _today_str() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    _FORM_URL = (os.environ.get("ARVISX_PUBLIC_URL", "").rstrip("/") + "/forms") \
        if os.environ.get("ARVISX_PUBLIC_URL") else ""

    def _notify_assignment(rid: int) -> None:
        """DM the assigned technician their round (needs a roster phone; else skip —
        the assignment still shows in the app/manager view)."""
        from arvisx.checklist_forms import get_template, run_summary
        run = state.db.get_checklist_run(rid)
        if not run or not run.get("assignee"):
            return
        tech = state.db.get_technician(run["building_id"], run["assignee"])
        phone = (tech or {}).get("phone", "")
        if not phone:
            return
        tmpl = get_template(run["template_id"], run["building_id"])
        if tmpl is None:
            return
        summ = run_summary(tmpl, state.db.checklist_entries(rid))
        openn = summ["total"] - summ["done"]
        link = f"\nOpen: {_FORM_URL}" if _FORM_URL else ""
        txt = (f"📋 You've been assigned *{tmpl.name}* for {run['shift_date']}.\n"
               f"{openn} item(s) to complete.{link}")
        state.db.enqueue_notification(run["building_id"], txt, to_number=phone, kind="assignment")

    def _notify_issue(building: str, label: str, value: Any) -> None:
        txt = (f"⚠️ Checklist flagged an issue:\n*{label}*: {value}\n"
               "Open the app to assign + resolve.")
        state.db.enqueue_notification(building, txt, to_number="", kind="issue")   # ops broadcast

    def _run_view(rid: int) -> Dict[str, Any]:
        from arvisx.checklist_forms import get_template, run_summary
        run = state.db.get_checklist_run(rid)
        if not run:
            raise HTTPException(404, f"unknown run {rid}")
        tmpl = get_template(run["template_id"], run["building_id"])
        if tmpl is None:
            raise HTTPException(404, f"unknown template {run['template_id']}")
        entries = state.db.checklist_entries(rid)
        return {"run": run, "template": tmpl.to_dict(), "entries": entries,
                "summary": run_summary(tmpl, entries),
                "signoffs": state.db.checklist_signoffs(rid)}

    @app.get("/api/v1/forms/templates")
    async def forms_templates(building: str = "one-anthem"):
        from arvisx.checklist_forms import templates_for
        return {"building": building,
                "templates": [{"template_id": t.template_id, "name": t.name,
                               "cadence": t.cadence, "timing": t.timing,
                               "items": len(t.all_items()), "per_asset": t.per_asset}
                              for t in templates_for(building)]}

    @app.get("/api/v1/forms/template/{tid}")
    async def forms_template(tid: str, building: str = "one-anthem"):
        from arvisx.checklist_forms import get_template
        t = get_template(tid, building)
        if t is None:
            raise HTTPException(404, f"unknown template {tid}")
        return t.to_dict()

    @app.post("/api/v1/forms/run")
    async def forms_start_run(payload: Dict[str, Any] = Body(...)):
        """Start (or resume) a checklist run for a template+date(+asset). Resuming an
        OPEN run is intentional — one sheet per shift/day, entries accumulate."""
        from arvisx.checklist_forms import get_template
        p = payload or {}
        tid = str(p.get("template_id", "")).strip()
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        if get_template(tid, building) is None:
            raise HTTPException(400, f"unknown template '{tid}'")
        date = str(p.get("date", "")).strip() or _today_str()
        asset = str(p.get("asset", "")).strip()
        assignee = str(p.get("assignee", "")).strip()
        rid = state.db.find_open_run(building, tid, date, asset)
        if rid is None:
            rid = state.db.create_checklist_run(building, tid, date,
                                                technician=str(p.get("technician", "")).strip(),
                                                asset=asset, assignee=assignee)
            if assignee:
                _notify_assignment(rid)
        elif assignee:
            state.db.assign_checklist_run(rid, assignee)
            _notify_assignment(rid)
        return _run_view(rid)

    @app.get("/api/v1/forms/run/{rid}")
    async def forms_get_run(rid: int):
        return _run_view(rid)

    @app.post("/api/v1/forms/run/{rid}/entry")
    async def forms_save_entry(rid: int, payload: Dict[str, Any] = Body(...)):
        from arvisx.checklist_forms import get_template, entry_is_issue
        run = state.db.get_checklist_run(rid)
        if not run:
            raise HTTPException(404, f"unknown run {rid}")
        if run["status"] != "open":
            raise HTTPException(409, "run already submitted — cannot edit")
        tmpl = get_template(run["template_id"], run["building_id"])
        p = payload or {}
        item_id = str(p.get("item_id", "")).strip()
        item = next((i for i in tmpl.all_items() if i.item_id == item_id), None)
        if item is None:
            raise HTTPException(400, f"unknown item '{item_id}'")
        value = p.get("value", "")
        status = str(p.get("status", "")).strip().lower()
        note = str(p.get("note", ""))
        flagged = entry_is_issue(item, value, status)
        state.db.save_checklist_entry(rid, item_id, value=str(value), status=status,
                                      note=note, is_issue=flagged)
        # Auto issue lifecycle: a flagged entry opens a tracked issue (once); correcting
        # it back to OK auto-resolves the auto-opened issue. Manual issues are untouched.
        if flagged:
            if state.db.find_auto_issue(rid, item_id) is None:
                state.db.create_issue(
                    run["building_id"], title=f"{item.label}: {value}", detail=note,
                    run_id=rid, item_id=item_id, asset=run.get("asset", ""),
                    severity="issue", source="auto", raised_by=run.get("technician", ""))
                _notify_issue(run["building_id"], item.label, value)   # alert the manager
        else:
            aid = state.db.find_auto_issue(rid, item_id)
            if aid is not None:
                state.db.update_issue(aid, status="resolved", by="system", note="entry corrected to OK")
        return {"saved": True, "item_id": item_id, "is_issue": flagged,
                "summary": _run_view(rid)["summary"]}

    @app.post("/api/v1/forms/run/{rid}/submit")
    async def forms_submit_run(rid: int):
        if not state.db.get_checklist_run(rid):
            raise HTTPException(404, f"unknown run {rid}")
        state.db.submit_checklist_run(rid)
        return _run_view(rid)

    @app.post("/api/v1/forms/run/{rid}/signoff")
    async def forms_signoff(rid: int, payload: Dict[str, Any] = Body(...)):
        if not state.db.get_checklist_run(rid):
            raise HTTPException(404, f"unknown run {rid}")
        p = payload or {}
        role = str(p.get("role", "")).strip().lower()
        if not role:
            raise HTTPException(400, "provide 'role'")
        state.db.add_checklist_signoff(rid, role, by_user=str(p.get("by", "")).strip())
        return _run_view(rid)

    @app.get("/api/v1/forms/today")
    async def forms_today(building: str = "one-anthem", date: str = ""):
        """Manager view: every run for the day with completion % + open issues + assignee."""
        from arvisx.checklist_forms import get_template, run_summary
        date = date or _today_str()
        out = []
        for run in state.db.checklist_runs_for(building, date):
            tmpl = get_template(run["template_id"], building)
            if tmpl is None:
                continue
            summ = run_summary(tmpl, state.db.checklist_entries(run["id"]))
            out.append({"run_id": run["id"], "template_id": run["template_id"],
                        "name": tmpl.name, "status": run["status"],
                        "assignee": run.get("assignee") or "", "technician": run["technician"],
                        "asset": run["asset"], "completion_pct": summ["completion_pct"],
                        "issues": summ["issues"],
                        "signoffs": [s["role"] for s in state.db.checklist_signoffs(run["id"])]})
        return {"building": building, "date": date, "runs": out}

    # ── Technician roster + assignment (manager assigns; the task has an owner) ──
    @app.get("/api/v1/technicians")
    async def technicians_list(building: str = "one-anthem", all: bool = False):
        return {"building": building,
                "technicians": state.db.list_technicians(building, active_only=not all)}

    @app.post("/api/v1/technicians")
    async def technician_add(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        name = str(p.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "provide 'name'")
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        tid = state.db.add_technician(building, name, str(p.get("phone", "")).strip())
        return {"id": tid, "name": name}

    @app.post("/api/v1/technicians/{tech_id}/deactivate")
    async def technician_deactivate(tech_id: int):
        state.db.set_technician_active(tech_id, False)
        return {"id": tech_id, "active": False}

    @app.get("/api/v1/whatsapp/notifications")
    async def wa_notifications():
        """Pending outbound notifications for the bot to deliver. to_number set = DM that
        number (assigned technician); blank = broadcast to ops (manager). Stay pending
        until the bot ACKs — at-least-once."""
        return {"notifications": state.db.pending_notifications()}

    @app.post("/api/v1/whatsapp/notifications/ack")
    async def wa_notifications_ack(payload: Dict[str, Any] = Body(...)):
        ids = (payload or {}).get("ids") or []
        state.db.mark_notifications_sent([int(i) for i in ids if str(i).isdigit()])
        return {"acked": ids}

    @app.post("/api/v1/forms/run/{rid}/assign")
    async def forms_assign_run(rid: int, payload: Dict[str, Any] = Body(...)):
        """Manager assigns (or reassigns) a shift-round to a technician from the roster."""
        if not state.db.get_checklist_run(rid):
            raise HTTPException(404, f"unknown run {rid}")
        assignee = str((payload or {}).get("assignee", "")).strip()
        state.db.assign_checklist_run(rid, assignee)
        return _run_view(rid)

    @app.get("/api/v1/forms/assigned")
    async def forms_assigned(technician: str, building: str = "one-anthem", date: str = ""):
        """A technician's task list for the day — the rounds the manager assigned to them."""
        from arvisx.checklist_forms import get_template, run_summary
        date = date or _today_str()
        out = []
        for run in state.db.runs_assigned_to(building, technician, date):
            tmpl = get_template(run["template_id"], building)
            if tmpl is None:
                continue
            summ = run_summary(tmpl, state.db.checklist_entries(run["id"]))
            out.append({"run_id": run["id"], "name": tmpl.name, "status": run["status"],
                        "asset": run["asset"], "completion_pct": summ["completion_pct"],
                        "open_items": summ["total"] - summ["done"], "issues": len(summ["issues"])})
        return {"technician": technician, "date": date, "assigned": out}

    # ── Issue logging (lifecycle) + photo evidence ──────────────────────
    @app.get("/api/v1/issues")
    async def issues_list(building: str = "one-anthem", status: str = "", asset: str = ""):
        return {"building": building, "issues": _jsonable(state.db.list_issues(building, status, asset))}

    @app.get("/api/v1/issues/{issue_id}")
    async def issue_get(issue_id: int):
        iss = state.db.get_issue(issue_id)
        if not iss:
            raise HTTPException(404, f"unknown issue {issue_id}")
        return _jsonable(iss)

    @app.post("/api/v1/issues")
    async def issue_create(payload: Dict[str, Any] = Body(...)):
        """Log an issue directly (not from a checklist entry)."""
        p = payload or {}
        title = str(p.get("title", "")).strip()
        if not title:
            raise HTTPException(400, "provide 'title'")
        iid = state.db.create_issue(
            str(p.get("building", "one-anthem")).strip() or "one-anthem", title,
            detail=str(p.get("detail", "")), asset=str(p.get("asset", "")),
            severity=str(p.get("severity", "issue")), source="manual",
            raised_by=str(p.get("by", "")))
        return _jsonable(state.db.get_issue(iid))

    @app.post("/api/v1/issues/{issue_id}/transition")
    async def issue_transition(issue_id: int, payload: Dict[str, Any] = Body(...)):
        from arvisx.checklist_forms import valid_issue_transition, ISSUE_STATUSES
        iss = state.db.get_issue(issue_id)
        if not iss:
            raise HTTPException(404, f"unknown issue {issue_id}")
        p = payload or {}
        status = str(p.get("status", "")).strip().lower()
        assignee = p.get("assignee")
        if status:
            if status not in ISSUE_STATUSES:
                raise HTTPException(400, f"status must be one of {ISSUE_STATUSES}")
            if not valid_issue_transition(iss["status"], status):
                raise HTTPException(409, f"cannot go {iss['status']} → {status}")
        state.db.update_issue(issue_id, status=status,
                              assignee=(str(assignee) if assignee is not None else None),
                              by=str(p.get("by", "")), note=str(p.get("note", "")))
        return _jsonable(state.db.get_issue(issue_id))

    async def _save_photo_body(request, filename: str):
        from arvisx.uploads import save_photo
        data = await request.body()
        try:
            return save_photo(data, filename=filename,
                              content_type=request.headers.get("content-type", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/v1/forms/run/{rid}/photo")
    async def forms_entry_photo(rid: int, request: Request, item_id: str, filename: str = ""):
        """Attach a photo to a checklist entry. Raw image bytes in the body (Content-Type
        image/jpeg|png|webp) — no multipart dependency."""
        if not state.db.get_checklist_run(rid):
            raise HTTPException(404, f"unknown run {rid}")
        name, _mt = await _save_photo_body(request, filename)
        state.db.set_checklist_entry_photo(rid, item_id, name)
        return {"saved": True, "item_id": item_id, "photo": name}

    @app.post("/api/v1/issues/{issue_id}/photo")
    async def issue_photo(issue_id: int, request: Request, filename: str = ""):
        if not state.db.get_issue(issue_id):
            raise HTTPException(404, f"unknown issue {issue_id}")
        name, _mt = await _save_photo_body(request, filename)
        state.db.set_issue_photo(issue_id, name)
        return {"saved": True, "issue_id": issue_id, "photo": name}

    @app.get("/api/v1/photos/{name}")
    async def photo_get(name: str):
        from fastapi.responses import Response
        from arvisx.uploads import photo_path, media_type_of
        p = photo_path(name)
        if p is None:
            raise HTTPException(404, "photo not found")
        return Response(content=p.read_bytes(), media_type=media_type_of(name))

    @app.get("/api/v1/forms/digest")
    async def forms_digest(building: str = "one-anthem", date: str = ""):
        """WhatsApp-ready manager digest of today's checklists (completion, issues,
        sign-off). The bot can push this once a day / on shift close."""
        from arvisx.checklist_forms import manager_digest
        date = date or _today_str()
        runs = (await forms_today(building, date))["runs"]
        return {"date": date, "text": manager_digest(runs, date)}

    @app.get("/forms")
    async def forms_page():
        from fastapi.responses import HTMLResponse
        from arvisx.checklist_form_page import FORM_HTML
        return HTMLResponse(FORM_HTML)

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
