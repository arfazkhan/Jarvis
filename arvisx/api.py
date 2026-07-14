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
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

# Module-level so FastAPI can resolve `request: Request` annotations under
# `from __future__ import annotations` (it reads hints from module globals). Guarded so
# the module still imports where fastapi isn't installed (create_app imports it for real).
try:
    from fastapi import Request
except Exception:                       # pragma: no cover
    Request = None

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


def _checklist_bot_mode() -> bool:
    """True = CHECKLIST deployment (default): the WhatsApp bot answers from checklist data,
    suppresses the residential-sensor telemetry alerts/prompts, and sends the checklist digest.
    False = residential-sensor bot — when ARVISX_SOURCE=mqtt OR ARVISX_BOT_MODE=residential.
    Note this is the BOT-CONTENT mode, decoupled from the ingest source (mqtt boots the broker;
    bot mode does not), so residential bot behavior can be exercised on sim data without MQTT."""
    if os.environ.get("ARVISX_SOURCE", "sim").lower() == "mqtt":
        return False
    return os.environ.get("ARVISX_BOT_MODE", "checklist").lower() != "residential"


# When a fix is recorded with NO cause note, AllGud asks the resolver — curious, not naggy.
# Initial ask + 2 gently-varied nudges (one per heartbeat gap), then it lets go.
_KNOWLEDGE_ASK = [
    "Nice — {subject} sorted 👏 For the record, what was actually wrong / what did you do to fix "
    "it? I'll remember it so it's quicker next time. One line is plenty (or reply 'skip').",
    "Still curious about that {subject} fix 🙂 — what was the cause? A quick line whenever you get a sec.",
    "Last little nudge on {subject} — what fixed it? It helps the whole team next round. (or reply 'skip')",
]
_KNOWLEDGE_ABANDON = "No worries about {subject} — I'll pick it up from the pattern if it comes back 👍"


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
        # WhatsApp bridge pairing state, pushed by the bot for the ADMIN panel (status:
        # unknown|waiting_scan|connected|disconnected). Transient.
        self._bridge: Dict[str, Any] = {"status": "unknown", "qr": "", "ts": ""}
        self._bot_reset_id: int = 0   # admin "Re-pair" one-shot signal (bot polls + acks)
        # Per-sender rate limit for the LLM WhatsApp Q&A (anti-abuse / cost-burn).
        self._ask_rate: Dict[str, List[float]] = {}
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
        # Bootstrap the AllGud OPERATOR (admin panel) account — separate from the building
        # owner. Idempotent: only created if that username doesn't already exist.
        panel_u = os.environ.get("ARVISX_PANEL_USER", "").strip()
        panel_p = os.environ.get("ARVISX_PANEL_PASSWORD", "").strip()
        if panel_u and panel_p and not self.db.get_user(panel_u):
            from arvisx.auth import hash_password
            self.db.create_user(panel_u, "admin", hash_password(panel_p))
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

            # Deterministic on the cadence — the heartbeat exists to advance the checklist
            # sweeps (reminders/lapse/escalation), not to burn LLM tokens auto-investigating
            # every tick. Ask/RCA/handover still use the LLM on demand.
            async def _tick(n):
                # Auto-open today's recurring rounds (carry-forward tech) each morning,
                # then DM the assignee — so the daily checklists always appear without a
                # manual assign. Gated to >= 6am local by ensure_daily_runs.
                try:
                    from arvisx import checklist_intel as ci
                    from datetime import datetime as _dt
                    nowt = _dt.now()
                    owner = os.environ.get("OWNER_NUMBER", "").strip()
                    for b in (state.db.checklist_buildings() or ["one-anthem"]):
                        for c in ci.ensure_daily_runs(state.db, b, _today_str()):
                            if c["assignee"]:
                                _notify_assignment(c["run_id"])
                        # B2: fire any scheduled checklists now due; DM a pre-assigned tech.
                        for s in ci.due_scheduled_checklists(state.db, b, nowt):
                            if s["assignee"]:
                                _notify_assignment(s["run_id"])
                        # Learned-lesson candidates: propose recurring patterns for approval +
                        # notify the manager (they approve/reject from dashboard or WhatsApp).
                        for cand in ci.propose_memory_candidates(state.db, b):
                            state.db.enqueue_notification(
                                b, f"📚 AllGud learned something — review to add to building memory:\n"
                                   f"*{cand['title']}*\n{cand['detail']}\n"
                                   f"Reply *approve {cand['id']}* or *reject {cand['id']}* "
                                   f"(or use the Knowledge page).", to_number="", kind="memory_candidate")
                        # Curiosity nudges: gently follow up unanswered "what was the fix?" asks
                        # (≤2 more, varied wording), then let it go. Spaced by env gap (default 6h).
                        gap_h = float(os.environ.get("ARVISX_KNOWLEDGE_NUDGE_HOURS", "6"))
                        for kreq in state.db.list_open_knowledge_requests(b):
                            try:
                                last = _dt.fromisoformat(str(kreq["last_nudge_at"])[:19])
                            except Exception:
                                continue
                            if (nowt - last).total_seconds() < gap_h * 3600:
                                continue
                            subj = kreq.get("subject", "that")
                            if kreq["nudges"] < 2:
                                state.db.enqueue_notification(b, _KNOWLEDGE_ASK[kreq["nudges"] + 1].format(subject=subj),
                                                              to_number=kreq["ask_number"], kind="knowledge_request")
                                state.db.bump_knowledge_request_nudge(kreq["id"])
                            else:
                                state.db.enqueue_notification(b, _KNOWLEDGE_ABANDON.format(subject=subj),
                                                              to_number=kreq["ask_number"], kind="knowledge_request")
                                state.db.close_knowledge_request(kreq["id"], "abandoned")
                        # weekly (Mon ≥8am, once/wk) + monthly (1st ≥8am, once/mo) summary to owner
                        if owner and nowt.hour >= 8:
                            if nowt.weekday() == 0 and state.db.notifications_since(
                                    b, "weekly_summary", nowt.strftime("%Y-%m-%dT00:00:00")) == 0:
                                state.db.enqueue_notification(b, ci.period_summary_text(state.db, b, "week"),
                                                              to_number=owner, kind="weekly_summary")
                            if nowt.day == 1 and state.db.notifications_since(
                                    b, "monthly_summary", nowt.strftime("%Y-%m-01T00:00:00")) == 0:
                                state.db.enqueue_notification(b, ci.period_summary_text(state.db, b, "month"),
                                                              to_number=owner, kind="monthly_summary")
                except Exception as e:
                    logger.warning(f"[heartbeat] auto-open/summary failed: {e}")
                state._last_tick = await community_tick(state, llm=None)

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

    # Usage/cost metrics recorder (WhatsApp + LLM) writes to this building's DB.
    from arvisx import metrics as _metrics
    _metrics.set_db(state.db)
    # LLM provider/model/key are configurable from the admin panel (stored in the DB) — make_llm
    # reads that before falling back to env, so the operator isn't locked to K2Think.
    try:
        from arvisx import llm_client as _llmc
        _llmc.set_config_db(state.db)
        if _llmc._db_llm_config():          # a saved provider → enable the LLM layer (survives restart)
            os.environ["ARVIS_X_LLM"] = "1"
    except Exception:
        pass
    try:                                    # embeddings provider/model/key also admin-configurable
        from arvisx import embeddings as _emb
        _emb.set_config_db(state.db)
    except Exception:
        pass

    # Background-task keeper: asyncio GCs tasks with no strong reference mid-run, so hold
    # them until done (used for fire-and-forget LLM work like manual-distil + learn-from-fix).
    state._bg_tasks = set()
    def _spawn(coro):
        import asyncio as _aio
        t = _aio.create_task(coro)
        state._bg_tasks.add(t)
        t.add_done_callback(state._bg_tasks.discard)
        return t

    # Checklist builder: make DB custom templates visible everywhere templates_for is used.
    from arvisx.checklist_forms import set_custom_loader, Template as _Tmpl
    def _load_custom(building: str):
        return [_Tmpl.from_dict(d) for d in state.db.list_templates(building)]
    set_custom_loader(_load_custom)

    # Auth: API key (server) OR user Bearer token (browser). Writes (non-GET) require
    # an owner/fm role; reads need any authenticated identity. Login is exempt.
    from arvisx import auth as _auth_mod
    _EXEMPT = {"/api/v1/auth/login", "/api/v1/auth/field-login", "/api/v1/healthz/bot"}

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

    # ── field access (technicians) ───────────────────────────────────────────
    # A technician must reach the round runner without the manager login wall.
    # Two doors, ONE primitive — both mint a `technician`-role token the SPA
    # already understands (Bearer): a short PIN they type, OR a pre-minted
    # deep-link token embedded in the WhatsApp assignment link (?t=...).
    @app.post("/api/v1/auth/field-login")
    async def field_login(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        building = str(p.get("building", "")).strip()
        pin = str(p.get("pin", "")).strip()
        if not building or not pin:
            raise HTTPException(400, "need building and pin")
        for t in state.db.list_technicians(building):
            ph = t.get("pin_hash")
            if ph and _auth_mod.verify_password(pin, ph):
                tok = _auth_mod.make_token(t["name"], "technician")
                return {"token": tok, "role": "technician",
                        "technician": t["name"], "building": building}
        raise HTTPException(401, "invalid PIN")

    def _writer_role(authorization: str, x_api_key: str) -> Optional[str]:
        """Resolve a write role, honoring dev-open mode the same way the middleware does
        (no key + no users → 'system'). Endpoints that re-identify must use this, else
        they 403 in open mode even though the middleware let the request through."""
        if not (_api_key or state.auth_on):
            return "system"
        return _auth_mod.identify(authorization, x_api_key, _api_key)[1]

    @app.post("/api/v1/technicians/{tech_id}/pin")
    async def set_field_pin(tech_id: int, payload: Dict[str, Any] = Body(...),
                            authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        role = _writer_role(authorization, x_api_key)
        if role not in ("system", "owner", "fm"):
            raise HTTPException(403, "only owner/fm/system can set a technician PIN")
        pin = str((payload or {}).get("pin", "")).strip()
        if len(pin) < 4:
            raise HTTPException(400, "pin must be at least 4 digits")
        state.db.set_technician_pin(tech_id, _auth_mod.hash_password(pin))
        return {"ok": True, "tech_id": tech_id}

    @app.post("/api/v1/auth/field-token")
    async def field_token(payload: Dict[str, Any] = Body(...),
                          authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        # Mint a deep-link token for a technician (owner/fm/system). The
        # assignment link can carry this as ?t=<token> so a tap auto-authenticates.
        role = _writer_role(authorization, x_api_key)
        if role not in ("system", "owner", "fm"):
            raise HTTPException(403, "only owner/fm/system can mint a field token")
        p = payload or {}
        tech = str(p.get("technician", "")).strip()
        if not tech:
            raise HTTPException(400, "need technician")
        ttl = int(p.get("ttl", _auth_mod.TOKEN_TTL))
        return {"token": _auth_mod.make_token(tech, "technician", ttl=ttl), "technician": tech}

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

    def _phrasing_llm():
        """LLM used ONLY to reword grounded alerts into natural language. On by default when an
        LLM is configured; flip ARVISX_LLM_PHRASING=0 to keep alerts deterministic (zero tokens).
        Cheap (a few short calls a day) and always falls back to the deterministic baseline."""
        if os.environ.get("ARVISX_LLM_PHRASING", "1").strip().lower() not in ("1", "true", "yes", "on"):
            return None
        return _llm_for_reasoning()

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
    async def wa_digest(building: str = "one-anthem"):
        # Checklist deployment (no live sensors): the daily digest is the CHECKLIST summary,
        # not the residential simulator brief (pool/fire/energy readiness).
        if _checklist_bot_mode():
            from arvisx.checklist_forms import manager_digest
            from arvisx import checklist_intel as ci
            runs = (await forms_today(building, _today_str()))["runs"]
            text = manager_digest(runs, _today_str())
            aged = ci.aged_open_issues(state.db, building)
            if aged:
                text += "\n\n⏳ Aged open issues (>2d):\n" + "\n".join(
                    f"• {a['title']} — {a['age_days']:.0f}d" for a in aged[:6])
            return {"text": text}
        from arvisx.messaging import daily_digest
        return {"text": daily_digest(state.report_now())}

    @app.post("/api/v1/whatsapp/ask")
    async def wa_ask(payload: Dict[str, Any] = Body(...)):
        from arvisx.messaging import answer
        p = payload or {}
        q = str(p.get("question", "")).strip()
        by = str(p.get("by", "")).strip()        # sender WhatsApp number (phone or @lid)
        by_lid = str(p.get("by_lid", "")).strip()   # the @lid (LID era; groups often lid-only)
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        claimed = str(p.get("role", "viewer")).lower()
        # A0: backend resolves WHO is texting. When the number is KNOWN (roster), that is
        # authoritative; an UNKNOWN number falls back to the bot-claimed role for Q&A voice
        # only — it can never trigger manager actions / resident tickets (gated on kind below).
        sender = _resolve_sender(by, building, by_lid=by_lid) if (by or by_lid) else {
            "role": claimed, "kind": "claimed", "name": "", "number": ""}
        role = sender["role"] if sender.get("kind") in ("manager", "technician", "resident") else claimed
        if not q:
            raise HTTPException(400, "provide 'question'")
        # Usage metrics: one inbound message + one reply (every path below returns a reply).
        from arvisx import metrics as _metrics
        _metrics.record_whatsapp("in", kind=sender.get("kind", "claimed"), building=building)
        _metrics.record_whatsapp("out", kind="reply", building=building)
        # ── Guardrails: length cap + per-sender rate limit (anti-abuse / LLM cost-burn) ──
        if len(q) > 400:
            return {"intent": "guard", "text": "Please keep it short — ask about the building "
                    "(rounds, issues, PPM, assets)."}
        if by:
            import time as _time
            now_t, window, cap = _time.time(), 3600.0, int(os.environ.get("ARVISX_ASK_CAP_HOURLY", "30"))
            hist = [t for t in state._ask_rate.get(by, []) if now_t - t < window]
            if len(hist) >= cap:
                state._ask_rate[by] = hist
                return {"intent": "guard", "text": "You've sent a lot of questions this hour — "
                        "please try again later."}
            hist.append(now_t)
            state._ask_rate[by] = hist
        # Curiosity loop: if this sender has an open "what was the fix?" request, their free-text
        # reply IS the answer — record it (unless it's a manager command / a pending-action reply).
        if by and not _CMD_VERBS.match(q) and not (hasattr(state, "_wa_pending") and state._wa_pending.get(by)):
            kreq = state.db.open_knowledge_request_for(building, by)
            if kreq:
                r = _capture_knowledge_answer(kreq, q, building)
                if r:
                    return r
        # A2: managers can RUN actions from WhatsApp (assign / open / start / close / sign-off).
        # Deterministic command parser; only a BACKEND-resolved manager number (not a claimed
        # role) may act. Short-circuits before Q&A.
        if sender.get("kind") == "manager" and by:
            try:
                cmd = _handle_manager_command(q, sender, building)
            except Exception as e:
                logger.warning(f"[wa_ask] manager command failed: {e}")
                cmd = "Couldn't run that — try 'help' for commands."
            if cmd is not None:
                _record_turn(building, sender.get("name") or "manager", role, q, cmd)
                return {"intent": "action", "text": cmd, "source": "command"}
            # A manager/owner reporting a problem in plain words → log it (don't send them to
            # the read-only Q&A, which can only OFFER to create an issue but not actually do it).
            if _is_problem_report(q):
                r = _log_reported_issue(q, sender.get("name") or "Manager", building)
                _record_turn(building, sender.get("name") or "manager", role, q, r["text"])
                return r
            if _report_preamble(q):
                return {"intent": "action", "source": "report", "text":
                        "Sure — what's the problem? Describe it (e.g. 'lift not working in B block') "
                        "and I'll log it right away."}
            # Natural-language action ("reassign shift 2 to Ajith", "mark the lift in progress")
            # → LLM maps it, asks YES, then the deterministic executor runs it.
            try:
                la = await _try_llm_action(q, sender, building)
            except Exception as e:
                logger.warning(f"[wa_ask] llm action failed: {e}")
                la = None
            if la is not None:
                _record_turn(building, sender.get("name") or "manager", role, q, la)
                return {"intent": "action", "text": la, "source": "llm_action"}
        # A3: a pre-registered (backend-resolved) resident's message → common-area ticket.
        if sender.get("kind") == "resident":
            return await _handle_resident_message(q, sender, building)
        # Semantic recall: "what did we discuss about the pump", "when did we decide on X" →
        # search the FULL history by meaning (embeddings; keyword fallback), answer with dates.
        from arvisx.checklist_skills import recall_request, answer_recall, summary_request, summarize_chat
        rreq = recall_request(q)
        if rreq is not None:
            from arvisx import embeddings as emb
            topic = rreq["topic"]
            turns = []
            try:
                qv = await asyncio.to_thread(emb.embed_one, topic)
                if qv:
                    items = [(e["chat_id"], e["vec"]) for e in state.db.chat_embeddings(building)]
                    hits = emb.top_k(qv, items, k=6)
                    turns = state.db.chat_by_ids([cid for cid, _ in hits])
            except Exception:
                turns = []
            if not turns:                       # no embedder / no vectors / no hit → keyword
                _stop = {"the", "a", "an", "our", "we", "did", "was", "were", "is", "are", "about",
                         "on", "for", "of", "to", "and", "that", "this", "with", "in", "conversation",
                         "discussion", "chat", "talk", "discuss"}
                terms = [w for w in re.split(r"\W+", topic.lower()) if len(w) > 2 and w not in _stop][:5]
                turns = state.db.chat_keyword_search(building, terms)
            ans = await answer_recall(_llm_for_reasoning(), turns, topic)
            state.db.log_chat(building, sender.get("name") or role, role, q, "(recall)")
            return {"intent": "qa", "text": ans, "source": "recall"}
        # Recap: "what did we discuss?" → summarize the conversation log (rolling 24h, a named
        # day, or a specific date; ask when the date is ambiguous). Non-residents only.
        sreq = summary_request(q)
        if sreq is not None:
            if sreq["need_date"]:
                rtext = ("Which day should I recap? Tell me a day (e.g. 'Sunday') or a date "
                         "like 2026-06-29.")
            else:
                from datetime import datetime as _dtr, timedelta as _tdr
                if sreq["date"]:
                    turns = state.db.chat_on_date(building, sreq["date"])
                else:
                    days = 1 if "24 hours" in sreq["label"] else 7
                    turns = state.db.chat_since(building, (_dtr.now() - _tdr(days=days)).isoformat(timespec="seconds"))
                rtext = await summarize_chat(_llm_for_reasoning(), turns, sreq["label"])
            state.db.log_chat(building, sender.get("name") or role, role, q, "(recap)")
            return {"intent": "qa", "text": rtext, "source": "recap"}
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
        elif _checklist_bot_mode():
            # CHECKLIST deployment: a general question is answered from the CHECKLIST data
            # (rounds, issues, PPM, assets), grounded + crisp, deterministic fallback if no
            # LLM. An mqtt (residential-sensor) deployment keeps the residential answers above.
            try:
                from arvisx.checklist_skills import run_building_qa
                from arvisx.llm_client import make_llm
                try:
                    llm = make_llm()
                except Exception:
                    llm = None
                # Conversation continuity: recent turns (this building, ~last 40 min) so follow-ups
                # feel like a real chat — the model resolves "it"/"that"/"him" from context.
                from datetime import datetime as _dth, timedelta as _tdh
                recent = state.db.chat_since(building, (_dth.now() - _tdh(minutes=40)).isoformat(timespec="seconds"))
                history = []
                for t in recent[-6:]:
                    if (t.get("reply") or "") == "(recap)":
                        continue
                    history.append({"role": "user", "content": t.get("text", "")})
                    if t.get("reply"):
                        history.append({"role": "assistant", "content": t.get("reply", "")})
                qa = await run_building_qa(llm, state.db, building, q, _today_str(),
                                           asker=sender, history=history)
                if qa.get("text"):
                    res["text"] = qa["text"]
                    res["source"] = qa.get("source", "")
                # LLM off + a meta/identity question → an honest answer, not the generic redirect.
                if qa.get("source") == "deterministic":
                    m = _meta_reply(q, sender, role)
                    if m:
                        res["text"] = m
                        res["source"] = "meta"
            except Exception:
                pass
        _record_turn(building, sender.get("name") or role, role, q, res.get("text", ""))
        return {"intent": res.get("intent", "qa"), "text": res["text"], "source": res.get("source", "")}

    @app.get("/api/v1/whatsapp/alerts")
    async def wa_alerts():
        """New alerts to push (severity>=WARNING + confidence Medium/High, deduped across
        polls). Open resident requests ride the same poll so the building team hears about
        them on the next tick. They stay 'open' until the bot ACKS the WhatsApp send
        (POST /whatsapp/resident-requests/ack) — a crash mid-push re-delivers next poll:
        at-least-once, never silently lost (worst case the team sees a duplicate)."""
        # Checklist-only deployments (no live sensors) must NOT broadcast the simulator's
        # telemetry alerts (pool/fire/energy/ghost). Only checklist flows push there —
        # assignment DMs, reminders, issue alerts, digest, handover (separate endpoints).
        if _checklist_bot_mode():
            return {"count": 0, "alerts": []}
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
        technician ('pump room visual check? reply OK / photo'). Legacy residential
        (sensor) feature; off for checklist-only deployments (templates drive the field app)."""
        if _checklist_bot_mode():
            return {"prompts": []}
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

    _PUBLIC_URL = os.environ.get("ARVISX_PUBLIC_URL", "").rstrip("/")
    _FORM_URL = (_PUBLIC_URL + "/forms") if _PUBLIC_URL else ""

    def _field_deeplink(rid: int, building: str, assignee: str) -> str:
        """Deep-link a technician straight into the field round runner.
        Carries a pre-minted technician token (?t=) so the tap auto-authenticates —
        same primitive as the PIN login, no manager wall. Falls back to the legacy
        /forms page if the SPA URL isn't configured."""
        if not _PUBLIC_URL:
            return f"\nOpen: {_FORM_URL}" if _FORM_URL else ""
        tok = _auth_mod.make_token(assignee, "technician") if assignee else ""
        url = f"{_PUBLIC_URL}/field/run/{rid}?building={building}"
        if tok:
            url += f"&t={tok}"
        return f"\nOpen: {url}"

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
        link = _field_deeplink(rid, run["building_id"], run["assignee"])
        txt = (f"📋 You've been assigned *{tmpl.name}* for {run['shift_date']}.\n"
               f"{openn} item(s) to complete.{link}")
        state.db.enqueue_notification(run["building_id"], txt, to_number=phone, kind="assignment")

    def _notify_issue(building: str, label: str, value: Any) -> None:
        txt = (f"⚠️ Checklist flagged an issue:\n*{label}*: {value}\n"
               "Open the app to assign + resolve.")
        state.db.enqueue_notification(building, txt, to_number="", kind="issue")   # ops broadcast

    # ── Autonomous reading-anomaly loop (learned band → auto-issue + alert + lesson) ──
    def _anomaly_already_open(building: str, item) -> bool:
        """Don't re-fire: an anomaly issue for this item is already open."""
        return any(i.get("source") == "anomaly" and i.get("item_id") == item.item_id
                   and i.get("status") != "resolved" for i in state.db.list_issues(building))

    async def _learn_from_anomaly(building: str, item, finding: Dict[str, Any]) -> None:
        """Turn an anomaly into a durable building-memory candidate (pending manager approval)."""
        unit = item.unit or ""
        if finding.get("detector") == "band":
            title = (f"{item.label} on {item.asset or 'asset'} normally sits "
                     f"{finding.get('low')}–{finding.get('high')}{unit}; flag when it deviates.")
        else:
            title = (f"{item.label} on {item.asset or 'asset'} trended {finding.get('direction', '')} "
                     f"({finding.get('from')}→{finding.get('to')}{unit}); watch for continued drift.")
        state.db.add_memory_candidate(building, "anomaly_lesson", title[:140],
                                      source="anomaly", dedup_key=f"anomaly:{item.item_id}")

    def _open_anomaly_issue(rid: int, run: Dict[str, Any], item, value, finding: Dict[str, Any]) -> None:
        """A reading outside its learned band / in a strong trend → auto-issue + manager alert +
        (background) a proposed lesson. Grounded in the item's own history — no threshold, no sensor."""
        building = run["building_id"]
        unit = item.unit or ""
        if finding.get("detector") == "band":
            detail = (f"{item.label} read {value}{unit} — outside its normal band "
                      f"{finding.get('low')}–{finding.get('high')}{unit} "
                      f"(learned from {finding.get('n')} readings, {finding.get('direction', '')}).")
            sev = "critical" if abs(finding.get("z", 0) or 0) >= 5 else "issue"
        else:
            detail = (f"{item.label} is {finding.get('direction', '')}: "
                      f"{finding.get('from')}→{finding.get('to')}{unit} "
                      f"({finding.get('change_pct')}% over recent readings).")
            sev = "issue"
        iid = state.db.create_issue(building, f"{item.label} anomaly: {value}{unit}", detail=detail,
                                    run_id=rid, item_id=item.item_id, asset=(item.asset or run.get("asset", "")),
                                    severity=sev, source="anomaly", raised_by="AllGud (auto)")
        _notify_issue_event(state.db.get_issue(iid), f"⚠️ Auto-detected reading anomaly — {detail}", by="AllGud")
        _spawn(_learn_from_anomaly(building, item, finding))

    def _remind_technician(building: str, name: str) -> str:
        """Manager-triggered nudge: DM `name` their still-open assigned round(s) for today with
        the pending count + a deep-link. Returns a manager-facing summary string."""
        from arvisx.checklist_forms import get_template, run_summary
        tech = state.db.get_technician(building, name)
        phone = _norm_phone((tech or {}).get("phone", ""))
        pend = []
        for run in state.db.checklist_runs_for(building, _today_str()):
            if (run.get("assignee") or "").lower() != name.lower() or run["status"] != "open":
                continue
            tmpl = get_template(run["template_id"], building)
            if not tmpl:
                continue
            summ = run_summary(tmpl, state.db.checklist_entries(run["id"]))
            openn = summ["total"] - summ["done"]
            if openn > 0:
                pend.append((run, tmpl, summ, openn))
        if not pend:
            return f"{name} has nothing pending on today's assigned rounds — nothing to remind."
        total = sum(o for *_, o in pend)
        if not phone:
            return (f"{name} has {total} pending item(s), but no WhatsApp number on file — "
                    f"add their number in Setup to remind them here.")
        for run, tmpl, summ, openn in pend:
            link = _field_deeplink(run["id"], building, name)
            state.db.enqueue_notification(
                building, f"⏰ Reminder: *{tmpl.name}* — {openn} item(s) still pending "
                f"({summ['completion_pct']:.0f}% done). Please finish before shift end.{link}",
                to_number=phone, kind="round_reminder")
        return f"✅ Reminded {name} — {total} pending item(s) across {len(pend)} round(s)."

    # ── A0: WhatsApp sender identity & role map ──────────────────────────
    def _norm_phone(num: str) -> str:
        """Digits only — strips +, spaces, and any '@s.whatsapp.net' suffix."""
        if not num:
            return ""
        return "".join(ch for ch in str(num).split("@")[0] if ch.isdigit())

    def _manager_numbers() -> List[str]:
        """Manager/owner WhatsApp numbers that receive alerts + may run actions: env
        (OWNER_NUMBER + ARVISX_MANAGER_NUMBERS) PLUS active owner/fm users added in the admin
        panel (DB) — so a manager can be added without editing env / SSH."""
        raw = [os.environ.get("OWNER_NUMBER", "")] + os.environ.get("ARVISX_MANAGER_NUMBERS", "").split(",")
        try:
            raw += state.db.manager_phones()
        except Exception:
            pass
        out, seen = [], set()
        for n in (_norm_phone(x) for x in raw):
            if n and n not in seen:
                seen.add(n); out.append(n)
        return out

    def _resolve_sender(by: str, building: str = "one-anthem", by_lid: str = "") -> Dict[str, Any]:
        """Resolve an incoming WhatsApp number → AUTHORITATIVE identity+role (backend
        roster, independent of what the bot claims). Roles: owner (manager — full ops +
        actions) · technician (field; own round/issue DMs) · resident (common-area tickets
        only, A3) · viewer (unknown number, read-only Q&A).

        LID era: `by` is the phone when WhatsApp gives it, else the @lid; `by_lid` is always the
        @lid. When both are present and differ, `by` is the real phone → learn the lid→phone map
        (DMs always carry the phone). When only a lid arrives (common in groups), resolve it to
        the learned phone so a manager can still run commands from the group."""
        num = _norm_phone(by)
        lid = _norm_phone(by_lid)
        if num and lid and num != lid:
            try:
                state.db.remember_lid(lid, num)
            except Exception:
                pass
        elif lid and (not num or num == lid):
            try:
                mapped = _norm_phone(state.db.phone_for_lid(lid))
                if mapped:
                    num = mapped
            except Exception:
                pass
        if not num:
            return {"role": "viewer", "kind": "unknown", "name": "", "number": ""}
        if num in _manager_numbers():
            return {"role": "owner", "kind": "manager", "name": "Manager", "number": num}
        for t in state.db.list_technicians(building, active_only=True):
            if _norm_phone(t.get("phone", "")) == num:
                return {"role": "technician", "kind": "technician", "name": t["name"],
                        "number": num, "technician": t}
        rb = getattr(state.db, "resident_by_phone", None)   # present once A3 lands
        if rb:
            res = rb(building, num)
            if res:
                return {"role": "resident", "kind": "resident", "name": res.get("name", ""),
                        "number": num, "unit": res.get("unit", ""), "resident": res}
        return {"role": "viewer", "kind": "unknown", "name": "", "number": num}

    # ── A1: issue-lifecycle WhatsApp alerts (manager + assigned technician) ─
    def _notify_issue_event(iss: Dict[str, Any], event: str, by: str = "", note: str = "") -> None:
        """DM the manager(s) AND the assigned technician on issue open + each status change.
        Grounded: only real roster phones; console link for the manager."""
        if not iss:
            return
        building = iss.get("building_id", "one-anthem")
        bits = [b for b in (iss.get("asset") or "", iss.get("severity") or "") if b]
        meta = (" — " + " · ".join(bits)) if bits else ""
        assignee = iss.get("assignee") or ""
        line = f"🔧 Issue #{iss['id']}: {iss.get('title', 'issue')}{meta}\n{event}"
        if assignee and "assign" not in event.lower():
            line += f" · assigned: {assignee}"
        if note:
            line += f"\nNote: {note}"
        clink = f"\nOpen: {_PUBLIC_URL}/issues" if _PUBLIC_URL else ""
        seen = set()
        for m in _manager_numbers():
            state.db.enqueue_notification(building, line + clink, to_number=m, kind="issue_lifecycle")
            seen.add(m)
        if assignee:
            tech = state.db.get_technician(building, assignee)
            ph = _norm_phone((tech or {}).get("phone", ""))
            if ph and ph not in seen:
                state.db.enqueue_notification(building, line, to_number=ph, kind="issue_lifecycle")

    def _building_name(building: str) -> str:
        return (building or "").replace("-", " ").replace("_", " ").title() or "the building"

    def _welcome_member(building: str, name: str, phone: str, role: str) -> None:
        """One-time, role-aware welcome DM when someone is added to the roster. Skipped
        silently if there's no phone. Roles: resident, technician, manager (owner/fm), viewer."""
        ph = _norm_phone(phone)
        if not ph:
            return
        first = (name or "").strip().split(" ")[0] or "there"
        bname = _building_name(building)
        clink = f"\nConsole: {_PUBLIC_URL}" if _PUBLIC_URL else ""
        role = (role or "").strip().lower()
        if role == "technician":
            lines = [
                f"Hi {first} 👋 You're added as a technician for {bname} on AllGud.",
                "You'll get your daily checklist rounds and any issues assigned to you right "
                "here on WhatsApp — each with a tap-to-open link, no login needed.",
                "When you finish a task, just submit it from the link. We'll nudge you if "
                "something's still pending before your shift ends.",
            ]
            kind = "technician_welcome"
        elif role in ("owner", "fm", "manager"):
            label = "the owner" if role == "owner" else "a manager"
            lines = [
                f"Hi {first} 👋 You're added as {label} for {bname} on AllGud.",
                "You'll get issue alerts and the daily summary here. You can manage issues by "
                "replying — e.g. *assign 12 to Rohit*, *close 12*, *approve 3*." + clink,
            ]
            kind = "manager_welcome"
        elif role == "viewer":
            lines = [
                f"Hi {first} 👋 You're added as a viewer for {bname} on AllGud.",
                "You'll get the daily summary and key alerts here (read-only)." + clink,
            ]
            kind = "viewer_welcome"
        else:  # resident
            lines = [
                f"Hi {first} 👋 You're now registered with AllGud for {bname}.",
                "To report any common-area issue — lift, water, lights, cleaning — just message "
                "here and the building team gets it right away.",
            ]
            link = state.db.get_setting(building, "resident_group_link", "").strip()
            if link:
                lines.append(f"\nJoin the residents' group here 👉 {link}")
            lines.append("\nFor emergencies, contact the facility desk directly.")
            kind = "resident_welcome"
        state.db.enqueue_notification(building, "\n".join(lines), to_number=ph, kind=kind)

    async def _recognize_submission(rid: int) -> None:
        """A round was actually completed → if it's a RECOVERY (broke a missed-day run) or a
        MILESTONE good streak, DM the manager a short positive note (phrased if enabled).
        Routine good days stay silent — the positive mirror of the lapse escalation."""
        from arvisx.checklist_forms import get_template
        from arvisx import checklist_intel as ci
        run = state.db.get_checklist_run(rid)
        if not run:
            return
        tmpl = get_template(run["template_id"], run["building_id"])
        name = tmpl.name if tmpl else run["template_id"]
        who = run.get("technician") or run.get("assignee") or ""
        msg, facts = ci.recognition_message(state.db, run["building_id"], run, name, who)
        if not msg:
            return
        llm = _phrasing_llm()
        if llm is not None:
            from arvisx.checklist_skills import phrase_line
            msg = await phrase_line(llm, msg, facts)
        state.db.enqueue_notification(run["building_id"], msg, to_number="", kind="round_done")

    async def _learn_from_resolved_issue(issue_id: int) -> None:
        """An LLM distils a reusable lesson from a resolved issue → pending memory candidate +
        notify the manager to approve. Falls back to the resolution note if no LLM."""
        import json as _json
        iss = state.db.get_issue(issue_id)
        if not iss:
            return
        h = iss.get("history")
        if isinstance(h, str):          # get_issue may return it already-parsed; don't clobber
            try:
                iss["history"] = _json.loads(h or "[]")
            except Exception:
                iss["history"] = []
        elif not isinstance(h, list):
            iss["history"] = []
        try:
            from arvisx.llm_client import make_llm
            llm = make_llm()
        except Exception:
            llm = None
        from arvisx.checklist_skills import lesson_from_issue
        lesson = await lesson_from_issue(llm, iss)
        if not lesson:                       # deterministic fallback from the last resolution note
            notes = [h.get("note") for h in iss["history"] if h.get("note")]
            if notes:
                lesson = {"title": f"{iss.get('asset') or iss.get('title', 'issue')}: {str(notes[-1])[:100]}",
                          "detail": iss.get("title", "")}
        if not lesson:
            return
        cid = state.db.add_memory_candidate(iss["building_id"], "rca_lesson", lesson["title"],
                                            lesson.get("detail", ""), source="resolved_issue",
                                            dedup_key=f"issue:{issue_id}")
        if cid:
            state.db.enqueue_notification(
                iss["building_id"], f"📚 AllGud learned from a fix:\n*{lesson['title']}*\n"
                f"Reply *approve {cid}* or *reject {cid}* (or use the Knowledge page).",
                to_number="", kind="memory_candidate")

    def _issue_subject(iss: Dict[str, Any]) -> str:
        s = iss.get("title", "the issue")
        return f"{s} on {iss['asset']}" if iss.get("asset") else s

    def _ask_for_knowledge(issue_id: int, by: str = "") -> None:
        """Fix recorded with no cause → curiously ask the resolver (the tech, else a manager)."""
        iss = state.db.get_issue(issue_id)
        if not iss:
            return
        phone = ""
        if by:
            t = state.db.get_technician(iss["building_id"], by)
            phone = _norm_phone((t or {}).get("phone", "")) if t else ""
        if not phone:
            mn = _manager_numbers()
            phone = mn[0] if mn else ""
        if not phone:
            return                      # nobody reachable — skip quietly
        subject = _issue_subject(iss)
        state.db.add_knowledge_request(iss["building_id"], issue_id, phone, subject)
        state.db.enqueue_notification(iss["building_id"], _KNOWLEDGE_ASK[0].format(subject=subject),
                                      to_number=phone, kind="knowledge_request")

    _CMD_VERBS = re.compile(r"^(assign|re-?assign|open|start|mark|move|set|in[-\s]?progress|close|"
                            r"resolve|reopen|re-?open|sign|signoff|remind|approve|reject|add\s+memory|"
                            r"help|commands|menu|yes|y|confirm|ok|okay|cancel|stop)\b",
                            re.I)

    def _capture_knowledge_answer(kreq: Dict[str, Any], text: str, building: str) -> Optional[Dict[str, Any]]:
        """The resolver replied to a 'what was the fix?' ask — record it (or accept a skip)."""
        low = text.strip().lower()
        subject = kreq.get("subject", "that")
        if low in ("skip", "no", "nope", "dunno", "don't know", "dont know", "na", "n/a", "later", "nvm"):
            state.db.close_knowledge_request(kreq["id"], "abandoned")
            return {"intent": "knowledge", "source": "knowledge", "text": "All good — thanks anyway 👍"}
        iid = kreq["issue_id"]
        state.db.append_issue_history(iid, "cause noted", by="(via WhatsApp)", note=text.strip())
        state.db.close_knowledge_request(kreq["id"], "answered", answer=text.strip())
        _spawn(_learn_from_resolved_issue(iid))      # now there's a cause → learn a lesson
        return {"intent": "knowledge", "source": "knowledge",
                "text": f"Thanks! 🧠 Noted — I'll remember that for {subject}."}

    # ── A2: manager actions over WhatsApp (deterministic, owner/fm only) ──
    def _shift_num(tok: str):
        return {"i": 1, "ii": 2, "iii": 3, "1": 1, "2": 2, "3": 3,
                "one": 1, "two": 2, "three": 3}.get(tok.strip().lower())

    def _find_today_run(building: str, tok: str):
        n = _shift_num(tok)
        if not n:
            return None
        for r in state.db.checklist_runs_for(building, _today_str()):
            if str(r["template_id"]).rstrip().endswith(f"-{n}"):
                return r
        return None

    def _run_name(run: Dict[str, Any]) -> str:
        from arvisx.checklist_forms import get_template
        t = get_template(run["template_id"], run["building_id"])
        return t.name if t else run["template_id"]

    def _match_technician(building: str, q: str):
        q = q.strip().lower()
        techs = state.db.list_technicians(building, active_only=True)
        for t in techs:                                   # exact name
            if t["name"].lower() == q:
                return t["name"]
        for t in techs:                                   # prefix / contains
            if t["name"].lower().startswith(q) or q in t["name"].lower():
                return t["name"]
        return None

    def _issue_action(iid: int, status: str, actor: str, building: str) -> str:
        iss = state.db.get_issue(iid)
        if not iss or iss.get("building_id") != building:
            return f"No issue #{iid} found for this building."
        state.db.update_issue(iid, status=status, by=actor, note="")
        fresh = state.db.get_issue(iid)
        label = {"in_progress": "Work started", "resolved": "Resolved ✅"}.get(status, status)
        _notify_issue_event(fresh, label, by=actor)
        if status == "resolved":          # no cause given → curiously ask the resolver
            _ask_for_knowledge(iid, actor)
        return f"✅ Issue #{iid} → {label}."

    def _do_signoff(rid: int, actor: str) -> str:
        state.db.add_checklist_signoff(rid, "manager", by_user=actor)
        return f"✅ Signed off {_run_name(state.db.get_checklist_run(rid))} as manager."

    def _resolve_open_issue(building: str, ref: str):
        """Find the open issue a manager means by a phrase like 'the lift issue' — token-match
        (drop stopwords) so 'lift issue' still hits 'the lift in B block is not working'."""
        toks = [t for t in re.split(r"\W+", (ref or "").lower())
                if len(t) > 2 and t not in ("the", "issue", "ticket", "problem", "fault", "open", "one")]
        if not toks:
            return None
        for i in state.db.list_issues(building):
            if i["status"] == "resolved":
                continue
            hay = f"{i.get('title', '')} {i.get('asset') or ''}".lower()
            if any(t in hay for t in toks):
                return i
        return None

    _ACTIONY = re.compile(
        r"\b(re-?assign|assign|mark|set|move|change|close|resolve|reopen|re-?open|start|"
        r"sign\s*off|signoff|remind|nudge|send|share|forward|give|link)\b", re.I)

    async def _try_llm_action(q: str, sender: Dict[str, Any], building: str):
        """Natural-language write, LLM-mapped → CONFIRM → deterministic execute. Handles the
        phrasings the exact-command parser misses ('reassign shift 2 to Ajith', 'mark the lift in
        progress'). Only fires on action-y wording; always asks YES before mutating."""
        if not _ACTIONY.search(q or ""):
            return None
        llm = _llm_for_reasoning()
        if llm is None:
            return None
        import time as _t
        techs = [t["name"] for t in state.db.list_technicians(building, active_only=True)]
        openi = [i for i in state.db.list_issues(building) if i["status"] != "resolved"]
        ctx = ("Technicians: " + (", ".join(techs) or "none") + "\nShifts: 1, 2, 3\nOpen issues: "
               + ("; ".join(f"#{i['id']} {i.get('title', '')} [{i.get('asset') or ''}]" for i in openi[:10]) or "none"))
        # Recent conversation → the extractor can resolve referents ("send HIM the link").
        from datetime import datetime as _dta, timedelta as _tda
        recent = state.db.chat_since(building, (_dta.now() - _tda(minutes=40)).isoformat(timespec="seconds"))
        history = []
        for t in recent[-6:]:
            if (t.get("reply") or "") in ("(recap)", "(recall)"):
                continue
            history.append({"role": "user", "content": t.get("text", "")})
            if t.get("reply"):
                history.append({"role": "assistant", "content": t.get("reply", "")})
        from arvisx.checklist_skills import extract_action
        a = await extract_action(llm, q, ctx, history=history)
        if not a:
            return None
        num = sender.get("number", "")
        actor = sender.get("name") or "manager"
        if not hasattr(state, "_wa_pending"):
            state._wa_pending = {}

        def _arm(run_fn, confirm):
            state._wa_pending[num] = {"ts": _t.time(), "run": run_fn}
            return f"⚠️ {confirm} Reply YES to confirm."

        act = a["action"]
        if act == "assign":
            run = _find_today_run(building, a["shift"])
            if not run:
                return None
            name = _match_technician(building, a["technician"])
            if not name:
                return None
            def _do(rid=run["id"], nm=name):
                state.db.assign_checklist_run(rid, nm); state.db.set_run_reminded(rid, 0)
                _notify_assignment(rid)
                return f"✅ Assigned {_run_name(state.db.get_checklist_run(rid))} to {nm} — they've been notified."
            return _arm(_do, f"Assign {_run_name(run)} to {name}?")
        if act == "issue_status":
            iss = _resolve_open_issue(building, a["issue_ref"])
            if iss is None:
                return None
            st = a["status"] if a["status"] in ("in_progress", "resolved", "open") else "in_progress"
            def _do(iid=iss["id"], s=st, ac=actor):
                return _issue_action(iid, s, ac, building)
            return _arm(_do, f"Set issue #{iss['id']} ({iss.get('title', '')}) to {st.replace('_', ' ')}?")
        if act == "signoff":
            run = _find_today_run(building, a["shift"])
            if not run or run["status"] != "submitted":
                return None
            def _do(rid=run["id"], ac=actor):
                return _do_signoff(rid, ac)
            return _arm(_do, f"Sign off {_run_name(run)}?")
        if act == "remind":
            name = _match_technician(building, a["technician"])
            if not name:
                return None
            return _remind_technician(building, name)      # non-destructive → do it directly
        if act == "open_today":
            from arvisx import checklist_intel as ci
            opened = ci.ensure_daily_runs(state.db, building, _today_str(), min_hour=0)
            return f"✅ Today's rounds are open ({len(opened)} created)."
        return None

    def _handle_manager_command(text: str, sender: Dict[str, Any], building: str):
        """Map a manager's WhatsApp message → a real action. Returns a reply string when
        `text` is a recognised command, else None (falls through to Q&A). Destructive
        actions (close issue, sign-off) require a 'YES' confirm (5-min window)."""
        import re as _re, time as _t
        low = text.strip().lower()
        if not hasattr(state, "_wa_pending"):
            state._wa_pending = {}
        num = sender.get("number", "")
        actor = sender.get("name") or "manager"

        # resolve / cancel a pending destructive action
        pend = state._wa_pending.get(num)
        if pend and low in ("yes", "y", "confirm", "ok", "okay"):
            state._wa_pending.pop(num, None)
            if _t.time() - pend["ts"] > 300:
                return "That confirmation expired — please re-send the command."
            return pend["run"]()
        if pend and low in ("no", "cancel", "stop"):
            state._wa_pending.pop(num, None)
            return "Cancelled."

        m = _re.match(r"assign\s+(?:shift\s+)?(\w+)\s+to\s+(.+)$", low)
        if m:
            run = _find_today_run(building, m.group(1))
            if not run:
                return f"No shift '{m.group(1)}' found for today."
            name = _match_technician(building, m.group(2))
            if not name:
                return f"No active technician matches '{m.group(2).strip()}'."
            state.db.assign_checklist_run(run["id"], name)
            state.db.set_run_reminded(run["id"], 0)
            _notify_assignment(run["id"])
            return f"✅ Assigned {_run_name(run)} to {name} — they've been notified."

        if _re.match(r"open\s+(today|rounds|today'?s\s+rounds)", low):
            from arvisx import checklist_intel as ci
            opened = ci.ensure_daily_runs(state.db, building, _today_str())
            return f"✅ Today's rounds are open ({len(opened)} created). Assign in the app or here."

        m = _re.match(r"remind\s+(.+)$", low)
        if m:
            name = _match_technician(building, m.group(1))
            if not name:
                return f"No active technician matches '{m.group(1).strip()}'."
            return _remind_technician(building, name)

        # Weekly / monthly report → summary text + a tappable PDF link.
        m = _re.match(r"(weekly|monthly|month|week)\s*(report|summary)?\s*$", low)
        if m or low in ("report", "reports", "summary"):
            from arvisx import checklist_intel as ci
            monthly = bool(m and m.group(1).startswith("month"))
            txt = ci.period_summary_text(state.db, building, "month" if monthly else "week")
            link = _report_link("monthly" if monthly else "weekly", building, sender)
            return txt + (f"\n\n📄 Full PDF report: {link}" if link else
                          "\n\n(Set ARVISX_PUBLIC_URL to enable the PDF download link.)")

        m = _re.match(r"(?:start|in[-\s]?progress)\s+issue\s+#?(\d+)", low)
        if m:
            return _issue_action(int(m.group(1)), "in_progress", actor, building)

        m = _re.match(r"(?:close|resolve)\s+issue\s+#?(\d+)", low)
        if m:
            iid = int(m.group(1)); iss = state.db.get_issue(iid)
            if not iss or iss.get("building_id") != building:
                return f"No issue #{iid} found for this building."
            state._wa_pending[num] = {"ts": _t.time(),
                                      "run": (lambda i=iid, a=actor: _issue_action(i, "resolved", a, building))}
            return f"⚠️ Reply YES to confirm closing issue #{iid}: {iss.get('title', '')}."

        m = _re.match(r"sign[-\s]?off\s+(?:shift\s+)?(\w+)", low)
        if m:
            run = _find_today_run(building, m.group(1))
            if not run:
                return f"No shift '{m.group(1)}' found for today."
            if run["status"] != "submitted":
                return f"{_run_name(run)} isn't submitted yet — only a submitted round can be signed off."
            state._wa_pending[num] = {"ts": _t.time(),
                                      "run": (lambda rid=run["id"], a=actor: _do_signoff(rid, a))}
            return f"⚠️ Reply YES to confirm signing off {_run_name(run)}."

        # Building-memory curation: approve/reject a learned-lesson candidate, or add one.
        m = _re.match(r"(approve|reject)\s+#?(\d+)", low)
        if m:
            cid = int(m.group(2)); cand = state.db.get_memory_candidate(cid)
            if not cand or cand.get("building_id") != building:
                return f"No learning #{cid} found."
            status = "approved" if m.group(1) == "approve" else "rejected"
            state.db.decide_memory_candidate(cid, status, by=actor)
            return (f"✅ Learning #{cid} added to building memory." if status == "approved"
                    else f"🗑️ Learning #{cid} rejected — won't be remembered.")
        m = _re.match(r"add\s+memory[:\s]+(.+)$", text.strip(), _re.I)
        if m:
            cid = state.db.add_memory_candidate(building, "manual", m.group(1).strip()[:120],
                                                source="manual", status="approved", decided_by=actor)
            return f"✅ Noted in building memory (#{cid})."

        if low in ("help", "commands", "?", "menu"):
            return ("Manager commands:\n• assign shift II to <name>\n• remind <name>\n• open today\n"
                    "• weekly report / monthly report\n• start issue <n>\n• close issue <n>\n"
                    "• sign off shift I\n• approve <n> / reject <n>  (learned lessons)\n"
                    "• add memory: <note>")
        return None

    # ── A3: resident common-area tickets over WhatsApp ───────────────────
    def _resident_category(text: str) -> str:
        import re as _re
        t = text.lower()
        for label, pat in (("Lift/Elevator", r"lift|elevator"),
                           ("Water", r"water|tap|plumb|leak|drain"),
                           ("Electricity", r"power|electric|light|outage"),
                           ("Cleaning", r"clean|garbage|trash|waste|dirty|smell"),
                           ("Security", r"security|guard|gate|intrud|theft"),
                           ("Parking", r"parking|car ?park|vehicle"),
                           ("Pool", r"pool|swim"),
                           ("Fire/Safety", r"fire|smoke|alarm")):
            if _re.search(pat, t):
                return label
        return "Common area"

    def _is_problem_report(text: str) -> bool:
        """A plain-language problem statement (not a question) → should become a logged issue."""
        import re as _re
        low = text.strip().lower()
        if "?" in low:
            return False
        first = low.split(" ")[0] if low else ""
        if first in ("is", "are", "was", "were", "do", "does", "did", "can", "could", "how",
                     "what", "why", "when", "who", "should", "will", "would", "has", "have",
                     "any", "show", "list", "status", "report", "weekly", "monthly"):
            return False
        return bool(_re.search(
            r"not working|isn'?t working|won'?t (work|start|turn|open|close)|stopped working|"
            r"broken|leak|no water|no power|power (cut|gone|out|failure|off)|stuck|jammed|"
            r"fault|faulty|damaged|tripped|overflow|not turning on|\bdown\b|\bdead\b|sparking|"
            r"flicker|burst|blocked|clogged|smell|smoke|noisy|not cooling|not heating",
            low))

    def _report_preamble(text: str) -> bool:
        """A bare 'I want to report / I have a complaint' with no concrete problem yet → we
        should ask them to describe it, not log a blank issue or dump the compliance report."""
        import re as _re
        low = text.strip().lower()
        if _is_problem_report(text):
            return False
        return bool(_re.search(
            r"\b(complain|complaint|report (a|an|the)? ?(problem|issue|fault)|"
            r"raise (a|an|the)? ?(issue|ticket|complaint)|log (a|an|the)? ?(issue|complaint|problem))\b",
            low))

    async def _embed_turn(chat_id: int, building: str, text: str) -> None:
        """Embed a chat turn for semantic recall (best-effort, off the reply path)."""
        from arvisx import embeddings as emb
        try:
            v = await asyncio.to_thread(emb.embed_one, text)
            if v:
                state.db.save_chat_embedding(chat_id, building, emb.to_blob(v))
        except Exception:
            pass

    _DECISION_HINT = re.compile(
        r"\b(we'?ll|we will|we should|we need to|let'?s|plan to|going to|decided?|approved?|"
        r"agree(?:d)? to|replace|purchase|buy|schedule|budget|next (?:week|month|quarter|year)|"
        r"by (?:next|end of))\b", re.I)

    async def _maybe_capture_decision(building: str, sender: str, q: str, reply: str) -> None:
        """If a turn looks like a decision/plan, an LLM extracts it → pending building-memory
        candidate for the manager to approve (human-in-the-loop; nothing auto-saved)."""
        if not _DECISION_HINT.search(q or ""):
            return
        llm = _llm_for_reasoning()
        if llm is None:
            return
        from arvisx.checklist_skills import extract_decision
        dec = await extract_decision(llm, sender, q, reply)
        if not dec:
            return
        cid = state.db.add_memory_candidate(building, "decision", dec[:140],
                                            source="chat_decision", dedup_key=f"decision:{dec[:60].lower()}")
        if cid:
            state.db.enqueue_notification(
                building, f"📌 Sounds like a decision worth remembering:\n\"{dec}\"\n"
                f"Reply *approve {cid}* to save it to building memory, or *reject {cid}*.",
                to_number="", kind="decision_candidate")

    def _record_turn(building: str, sender_name: str, role: str, q: str, reply: str) -> None:
        """Log a substantive turn + (background) embed it for recall + scan it for a decision."""
        try:
            cid = state.db.log_chat(building, sender_name, role, q, reply)
        except Exception:
            return
        _spawn(_embed_turn(cid, building, f"{sender_name}: {q}\n{reply}"))
        _spawn(_maybe_capture_decision(building, sender_name, q, reply))

    def _meta_reply(text: str, sender: Dict[str, Any], role: str):
        """Identity / capability / 'what's my role' → an honest, specific answer instead of the
        read-only agent flailing and falling back to a stats dump."""
        import re as _re
        low = text.strip().lower()
        name = sender.get("name") or ""
        if _re.search(r"\b(who are you|what are you|are you (real|human|a bot|an ai|there)|your name)\b", low):
            return ("I'm AllGud — an AI assistant for this building's day-to-day operations. Ask me "
                    "about rounds, issues, assets, PPM, or say 'weekly report'.")
        if _re.search(r"(what can you do|your capabilities|what do you do|what access|what data do you|"
                      r"how can you help|what are your (tools|features)|what all can you)", low):
            return ("Here's what I can do for this building:\n"
                    "• Rounds & shifts — who's on, what's pending, who's behind\n"
                    "• Issues — open list & history; I'll log a problem you report\n"
                    "• Assets, health & equipment manuals\n"
                    "• PPM / compliance — what's overdue\n"
                    "• Weekly & monthly PDF reports\n"
                    "• Recap what we've discussed (say 'summarise today')\n"
                    "Managers can run commands too: assign, remind, close issue, sign off. I can't "
                    "change settings or add users — that's the console.")
        if _re.search(r"(what.?s my role|who am i|my access level|am i (the |an )?(owner|manager|admin))", low):
            rl = {"owner": "the owner", "fm": "a manager", "manager": "a manager",
                  "viewer": "a viewer", "technician": "a technician"}.get(role, role or "a user")
            return (f"You're {rl} here{(', ' + name) if name else ''} — you can ask about operations "
                    "and run manager commands (assign, remind, close issue, reports).")
        return None

    def _log_reported_issue(text: str, who: str, building: str) -> Dict[str, Any]:
        """Log a manager/owner-reported problem as a tracked issue + notify the team."""
        cat = _resident_category(text)
        title = text.strip()
        title = (title[:80] + "…") if len(title) > 80 else title
        iid = state.db.create_issue(building, title, detail=f"Reported by {who} via WhatsApp",
                                    asset=cat, severity="issue", source="manual", raised_by=who)
        _notify_issue_event(state.db.get_issue(iid), f"Opened — reported by {who} ({cat})", by=who)
        return {"intent": "action", "source": "report", "text":
                f"✅ Logged as issue #{iid} ({cat}) — the team has been notified. "
                f"Assign or close it from the console or here (e.g. 'close issue {iid}')."}

    def _resident_who(sender: Dict[str, Any]) -> str:
        name = sender.get("name") or "Resident"
        unit = sender.get("unit") or ""
        return name + (f" (Unit {unit})" if unit else "")

    def _my_resident_tickets(building: str, sender: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The resident's OWN reports (match on the name we stamp into raised_by). Resident-scoped
        — never exposes other residents' or staff data."""
        name = (sender.get("name") or "").strip().lower()
        if not name:
            return []
        out = []
        for i in state.db.list_issues(building):
            if i.get("source") == "resident" and name in (i.get("raised_by") or "").lower():
                out.append({"id": i["id"], "title": i.get("title", ""), "status": i["status"]})
        return out[:10]

    def _log_resident_ticket(text: str, sender: Dict[str, Any], building: str, title: str = "") -> Dict[str, Any]:
        """Create a common-area ticket from a resident report + notify the team. The grounded
        confirmation always carries the REAL ticket number."""
        who = _resident_who(sender)
        cat = _resident_category(text)
        t = (title or text).strip()
        t = (t[:80] + "…") if len(t) > 80 else t
        iid = state.db.create_issue(building, t, detail=f"Reported by {who} via WhatsApp",
                                    asset=cat, severity="issue", source="resident", raised_by=who)
        _notify_issue_event(state.db.get_issue(iid), f"Opened — resident report ({cat})", by=who)
        return {"intent": "resident", "source": "resident", "text":
                f"✅ Logged as ticket #{iid} ({cat}) — the building team has been notified. Thank you!\n"
                "For emergencies, please contact the facility desk directly."}

    def _resident_status_list(building: str, sender: Dict[str, Any]) -> str:
        """Deterministic 'your reports' list — the safe answer for a status question."""
        mine = _my_resident_tickets(building, sender)
        openish = [t for t in mine if t["status"] != "resolved"]
        if not mine:
            return ("You don't have any reports on file yet. Describe any common-area problem and "
                    "I'll log it for the team.")
        if not openish:
            return "Good news — all your reports are resolved. ✅"
        return "Here are your open reports:\n" + "\n".join(
            f"• #{t['id']} {t['title']} [{t['status']}]" for t in openish[:6])

    async def _handle_resident_message(text: str, sender: Dict[str, Any], building: str) -> Dict[str, Any]:
        """Resident conversational turn: warm small talk, status of THEIR OWN reports, or log a
        common-area ticket. Resident-scoped (never staff/equipment data). LLM-driven with a hard
        safety net — any failure defaults to ticket-intake so a real problem is never lost."""
        low = text.strip().lower()
        name = sender.get("name") or "Resident"
        from arvisx.checklist_skills import _social_reply, run_resident_chat, _numbers_grounded
        # Resident greeting → resident-appropriate instructions FIRST (before the generic social
        # reply, which is phrased for managers and would mislead a resident).
        if (low in ("hi", "hello", "hey", "help", "menu", "?", "start", "salam", "good morning",
                    "good afternoon", "good evening", "gm") or len(low) < 4
                or low.startswith(("hi ", "hello ", "hey ", "good morning", "good afternoon", "good evening"))):
            return {"intent": "resident", "source": "resident", "text":
                    f"Hi {name}! 👋 Describe any *common-area* problem (e.g. 'Lift not working in "
                    "B block', 'No water in lobby washroom') and I'll log it for the building team.\n"
                    "You can also ask me about the status of your reports anytime."}
        soc = _social_reply(text)            # thanks / acks → warm, no ticket
        if soc:
            return {"intent": "resident", "source": "resident", "text": soc}
        llm = _llm_for_reasoning()
        if llm is not None:
            try:
                tickets = _my_resident_tickets(building, sender)
                r = await run_resident_chat(llm, tickets, _building_name(building), name, text)
                if r and r["intent"] == "report":
                    return _log_resident_ticket(text, sender, building, title=r.get("issue_title"))
                if r and r["intent"] == "status":
                    allowed = " ".join(f"#{t['id']}" for t in tickets)
                    reply = r.get("reply") or ""
                    txt = reply if (reply and _numbers_grounded(reply, allowed)) else _resident_status_list(building, sender)
                    return {"intent": "resident", "source": "resident", "text": txt}
                if r and r["intent"] in ("smalltalk", "other") and r.get("reply"):
                    return {"intent": "resident", "source": "resident", "text": r["reply"]}
            except Exception:
                pass
        # Safety net: deterministic status (keyword) or ticket — never lose a real report.
        if any(w in low for w in ("status", "update", "my report", "my complaint", "my ticket",
                                  "any news", "fixed yet", "resolved yet", "done yet")):
            return {"intent": "resident", "source": "resident", "text": _resident_status_list(building, sender)}
        return _log_resident_ticket(text, sender, building)

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

    # ── Checklist builder: create / edit / delete custom templates ───────
    @app.post("/api/v1/forms/templates")
    async def forms_save_template(payload: Dict[str, Any] = Body(...)):
        """Create or update a building's checklist template (the builder). Validated, then
        layered over the code defaults; same template_id overrides the default."""
        from arvisx.checklist_forms import validate_template_dict, Template
        p = payload or {}
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        tmpl = p.get("template") or p
        try:
            validate_template_dict(tmpl)
            Template.from_dict(tmpl)              # parse-check
        except (ValueError, KeyError) as e:
            raise HTTPException(400, f"invalid template: {e}")
        state.db.save_template(building, str(tmpl["template_id"]), tmpl)
        return {"saved": True, "template_id": tmpl["template_id"], "building": building}

    @app.delete("/api/v1/forms/template/{tid}")
    async def forms_delete_template(tid: str, building: str = "one-anthem"):
        ok = state.db.delete_template(building, tid)
        if not ok:
            raise HTTPException(404, f"no custom template {tid} for {building}")
        return {"deleted": tid, "building": building}

    # ── Seed / onboard a new building from a starter pack ────────────────
    @app.get("/api/v1/forms/seeds")
    async def forms_seeds():
        """Starter packs available on disk (e.g. one-anthem). Use POST /forms/seed to clone
        one into a new building."""
        from arvisx.checklist_forms import seed_catalog
        return {"seeds": seed_catalog()}

    @app.post("/api/v1/forms/seed")
    async def forms_seed(payload: Dict[str, Any] = Body(...)):
        """Onboard a building's checklists in one call — clone a starter pack (`from`) into a
        new `building`, or bulk-import `templates`. Saved as that building's DB templates."""
        from arvisx.checklist_forms import seed_templates, validate_template_dict, Template
        p = payload or {}
        building = str(p.get("building", "")).strip()
        if not building:
            raise HTTPException(400, "provide 'building'")
        src = str(p.get("from", "")).strip()
        if src:
            tpls = seed_templates(src)
            if not tpls:
                raise HTTPException(400, f"unknown seed '{src}'")
            to_save = [t.to_dict() for t in tpls]
        elif isinstance(p.get("templates"), list) and p["templates"]:
            to_save = p["templates"]
        else:
            raise HTTPException(400, "provide 'from' (a seed id) or a non-empty 'templates' list")
        saved = []
        for t in to_save:
            try:
                validate_template_dict(t)
                Template.from_dict(t)
            except (ValueError, KeyError) as e:
                raise HTTPException(400, f"invalid template '{t.get('template_id','?')}': {e}")
            state.db.save_template(building, str(t["template_id"]), t)
            saved.append(t["template_id"])
        return {"building": building, "seeded": saved}

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

    @app.post("/api/v1/forms/open-today")
    async def forms_open_today(building: str = "one-anthem"):
        """Open today's recurring (daily) rounds now — carry-forward the usual technician +
        DM them. One click instead of assigning each shift by hand. Idempotent."""
        from arvisx import checklist_intel as ci
        created = ci.ensure_daily_runs(state.db, building, _today_str(), min_hour=0)
        for c in created:
            if c["assignee"]:
                _notify_assignment(c["run_id"])
        return {"building": building, "opened": created}

    @app.get("/api/v1/forms/run/{rid}")
    async def forms_get_run(rid: int):
        return _run_view(rid)

    @app.post("/api/v1/forms/run/{rid}/entry")
    async def forms_save_entry(rid: int, payload: Dict[str, Any] = Body(...),
                               authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        from arvisx.checklist_forms import get_template, entry_is_issue
        run = state.db.get_checklist_run(rid)
        if not run:
            raise HTTPException(404, f"unknown run {rid}")
        if run["status"] == "lapsed":
            raise HTTPException(409, "round has lapsed — cannot edit")
        # Lock a round to its assignee: a technician can only fill their OWN round
        # (an old/reassigned deep-link can't write). Managers/owner/system can edit any.
        sub, role = _auth_mod.identify(authorization, x_api_key, _api_key)
        if role == "technician" and run.get("assignee") and sub != run["assignee"]:
            raise HTTPException(403, "this round is assigned to another technician")
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
        # Accountability: stamp WHO recorded this. Prefer the authenticated subject (technician
        # PIN/login, manager/owner login); fall back to the round's assignee in open dev mode.
        actor = sub or run.get("technician") or run.get("assignee") or ""
        state.db.save_checklist_entry(rid, item_id, value=str(value), status=status,
                                      note=note, is_issue=flagged, actor=actor)
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
        # Autonomous anomaly detection: a numeric reading that deviates from its OWN learned band
        # (or is in a strong decline) auto-opens an issue + alerts the manager — no threshold to
        # configure, no sensor. Only when the entry didn't already flag, and no anomaly is open
        # for this item yet (don't re-fire every shift).
        if not flagged and getattr(item, "kind", "") == "reading":
            from arvisx import checklist_intel as ci
            finding = ci.reading_anomaly_check(state.db, run["building_id"], item)
            if finding and not _anomaly_already_open(run["building_id"], item):
                _open_anomaly_issue(rid, run, item, value, finding)
        return {"saved": True, "item_id": item_id, "is_issue": flagged,
                "summary": _run_view(rid)["summary"]}

    @app.post("/api/v1/forms/run/{rid}/submit")
    async def forms_submit_run(rid: int):
        from arvisx.checklist_forms import get_template
        run = state.db.get_checklist_run(rid)
        if not run:
            raise HTTPException(404, f"unknown run {rid}")
        state.db.submit_checklist_run(rid)
        # Submitting a PPM round (non-daily template) for an asset closes its PPM loop —
        # resets the schedule from today, recording who did it via the run's technician.
        tmpl = get_template(run["template_id"], run["building_id"])
        if tmpl and tmpl.cadence != "daily" and run.get("asset"):
            state.db.mark_ppm_done(run["building_id"], run["asset"], _today_str())
        # Sign-off request: DM the owner a link to review + sign off the submitted round.
        owner = os.environ.get("OWNER_NUMBER", "").strip()
        if _PUBLIC_URL and owner:
            who = run.get("technician") or run.get("assignee") or "—"
            name = tmpl.name if tmpl else run["template_id"]
            state.db.enqueue_notification(
                run["building_id"],
                f"📝 *{name}* ({run['shift_date']}) submitted by {who} — review & sign off:\n"
                f"{_PUBLIC_URL}/operations/round/{rid}",
                to_number=owner, kind="signoff_request")
        _spawn(_recognize_submission(rid))   # recovery / milestone praise, off the request path
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
        # Never ship the PIN hash to the client; expose only whether one is set so the
        # console can show "PIN set" and offer to (re)set it.
        out = []
        for t in state.db.list_technicians(building, active_only=not all):
            t = dict(t)
            t["has_pin"] = bool(t.pop("pin_hash", None))
            out.append(t)
        return {"building": building, "technicians": out}

    @app.post("/api/v1/technicians")
    async def technician_add(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        name = str(p.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "provide 'name'")
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        phone = str(p.get("phone", "")).strip()
        tid = state.db.add_technician(building, name, phone)
        _welcome_member(building, name, phone, "technician")
        return {"id": tid, "name": name}

    @app.post("/api/v1/technicians/{tech_id}/deactivate")
    async def technician_deactivate(tech_id: int):
        state.db.set_technician_active(tech_id, False)
        return {"id": tech_id, "active": False}

    # ── Residents roster (A3) ────────────────────────────────────────────
    @app.get("/api/v1/residents")
    async def residents_list(building: str = "one-anthem", all: bool = False):
        return {"building": building,
                "residents": state.db.list_residents(building, active_only=not all)}

    @app.post("/api/v1/residents")
    async def resident_add(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        name = str(p.get("name", "")).strip()
        phone = str(p.get("phone", "")).strip()
        if not name or not phone:
            raise HTTPException(400, "provide 'name' and 'phone'")
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        rid = state.db.add_resident(building, name, phone, unit=str(p.get("unit", "")).strip())
        _welcome_member(building, name, phone, "resident")
        return {"id": rid, "name": name}

    @app.post("/api/v1/residents/{resident_id}/deactivate")
    async def resident_deactivate(resident_id: int):
        state.db.set_resident_active(resident_id, False)
        return {"id": resident_id, "active": False}

    @app.get("/api/v1/settings")
    async def get_settings(building: str = "one-anthem"):
        return {"building": building,
                "resident_group_link": state.db.get_setting(building, "resident_group_link", "")}

    @app.post("/api/v1/settings")
    async def set_settings(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        if "resident_group_link" in p:
            state.db.set_setting(building, "resident_group_link", str(p.get("resident_group_link", "")).strip())
        return {"building": building,
                "resident_group_link": state.db.get_setting(building, "resident_group_link", "")}

    @app.get("/api/v1/whatsapp/roster")
    async def wa_roster(building: str = "one-anthem"):
        """Phone numbers the bot should accept 1:1 messages from — the live backend roster
        (managers/owner + technicians + residents). The bot polls this so adding someone in the
        admin panel AUTO-AUTHORIZES them; no separate bot allowlist to edit. Digits only."""
        mgrs = _manager_numbers()
        techs = [_norm_phone(t.get("phone", "")) for t in state.db.list_technicians(building, active_only=True)]
        res = [_norm_phone(r.get("phone", "")) for r in state.db.list_residents(building, active_only=True)]
        techs = [t for t in techs if t]
        res = [r for r in res if r]
        return {"managers": mgrs, "technicians": techs, "residents": res,
                "all": sorted(set(mgrs) | set(techs) | set(res))}

    @app.get("/api/v1/whatsapp/notifications")
    async def wa_notifications():
        """Pending outbound notifications for the bot to deliver. to_number set = DM that
        number (assigned technician); blank = broadcast to ops (manager). Stay pending
        until the bot ACKs — at-least-once."""
        return {"notifications": state.db.pending_notifications()}

    @app.post("/api/v1/whatsapp/notifications/ack")
    async def wa_notifications_ack(payload: Dict[str, Any] = Body(...)):
        ids = [int(i) for i in ((payload or {}).get("ids") or []) if str(i).isdigit()]
        state.db.mark_notifications_sent(ids)
        if ids:                                       # proactive outbound messages delivered
            from arvisx import metrics as _metrics
            _metrics.record_whatsapp("out", kind="notification", count=len(ids))
        return {"acked": ids}

    # ── Admin panel (AllGud operator) — bot pairing + building analytics ────────
    @app.post("/api/v1/whatsapp/bridge/state")
    async def wa_bridge_set(payload: Dict[str, Any] = Body(...)):
        """The bot pushes its pairing state (write-role/api-key gated by middleware).
        QR retained only while waiting to scan."""
        p = payload or {}
        status = str(p.get("status", "")).strip() or "unknown"
        state._bridge = {"status": status,
                         "qr": str(p.get("qr", "")) if status == "waiting_scan" else "",
                         "ts": datetime.now().isoformat(timespec="seconds")}
        return {"ok": True}

    @app.get("/api/v1/admin/bridge/state")
    async def admin_bridge_get(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Bridge pairing state for the admin panel. QR is a sensitive pairing secret → admin only."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        return state._bridge

    @app.post("/api/v1/admin/bot/reset")
    async def admin_bot_reset(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Operator clicks 'Re-pair' → signal the bot to clear its (broken) Baileys session
        and regenerate a QR. One-shot: the bot polls /whatsapp/bot/control, acts, then acks."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        import time as _t
        state._bot_reset_id = int(_t.time())
        state._bridge = {"status": "waiting_scan", "qr": "", "ts": datetime.now().isoformat(timespec="seconds")}
        return {"requested": True, "reset_id": state._bot_reset_id}

    @app.get("/api/v1/healthz/bot")
    async def healthz_bot():
        """PUBLIC bot-health probe for an external uptime monitor (UptimeRobot etc.).
        200 only if the bot reported 'connected' recently; 503 if disconnected / waiting to
        re-pair / stale (no heartbeat). The monitor alerts you out-of-band — the bot itself
        can't WhatsApp you that the bot is down."""
        from fastapi.responses import JSONResponse
        b = state._bridge or {}
        status = b.get("status", "unknown")
        age = None
        try:
            age = (datetime.now() - datetime.fromisoformat(b.get("ts", ""))).total_seconds()
        except Exception:
            pass
        fresh = age is not None and age < 180        # bot heartbeats every ~60s
        ok = status == "connected" and fresh
        body = {"ok": ok, "status": status, "stale": (not fresh), "age_seconds": (round(age) if age is not None else None)}
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/api/v1/whatsapp/bot/control")
    async def wa_bot_control():
        """The bot polls this; a non-zero reset_id it hasn't handled = re-pair requested."""
        return {"reset_id": state._bot_reset_id}

    @app.post("/api/v1/whatsapp/bot/control/ack")
    async def wa_bot_control_ack(payload: Dict[str, Any] = Body(...)):
        """Bot acks the reset it's handling → clear the one-shot flag (if it still matches)."""
        rid = int((payload or {}).get("reset_id", 0) or 0)
        if rid and rid == state._bot_reset_id:
            state._bot_reset_id = 0
        return {"acked": rid}

    @app.get("/api/v1/admin/analytics")
    async def admin_analytics(building: str = "one-anthem", days: int = 7,
                              authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Building performance rollup for the admin panel (admin only)."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        from arvisx import checklist_intel as ci
        ev = ci.building_evaluation(state.db, building, days=int(days))
        ev["trend"] = ci.building_trend(state.db, building, days=int(days))
        return ev

    @app.get("/api/v1/admin/usage")
    async def admin_usage(building: str = "one-anthem", days: int = 30,
                          authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """WhatsApp (sent/received) + LLM (tokens/context/cost) usage for the admin panel.
        Deployment-wide: each AllGud deployment serves one building, and LLM token usage is
        recorded at the (building-agnostic) client layer — so we aggregate across the DB."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        from datetime import datetime as _dt, timedelta as _td
        since = (_dt.now() - _td(days=int(days))).isoformat(timespec="seconds")
        return {"building": building, "days": int(days), "currency": os.environ.get("ARVISX_CURRENCY", "USD"),
                "summary": state.db.usage_summary(since), "daily": state.db.usage_daily(since)}

    # ── Admin: manage building team (owner / manager logins + WhatsApp numbers) ──
    @app.get("/api/v1/admin/users")
    async def admin_users_list(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        return {"users": state.db.list_users()}

    @app.post("/api/v1/admin/users")
    async def admin_users_add(payload: Dict[str, Any] = Body(...),
                              authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Add an owner / manager (fm) / viewer with a login + optional WhatsApp number.
        A phone on an owner/fm grants WhatsApp manager privileges (alerts + actions)."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        p = payload or {}
        u = str(p.get("username", "")).strip()
        pw = str(p.get("password", ""))
        role = str(p.get("role", "fm")).strip().lower()
        if not u or not pw:
            raise HTTPException(400, "provide username + password")
        if role not in ("owner", "fm", "viewer"):
            raise HTTPException(400, "role must be owner, fm (manager), or viewer")
        phone = str(p.get("phone", ""))
        state.db.create_user(u, role, _auth_mod.hash_password(pw), phone=phone)
        _welcome_member(str(p.get("building", "one-anthem")).strip() or "one-anthem",
                        str(p.get("name", "")).strip() or u, phone, role)
        return {"username": u, "role": role}

    @app.post("/api/v1/admin/users/{username}/deactivate")
    async def admin_users_deactivate(username: str,
                                     authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        state.db.set_user_active(username, False)
        return {"username": username, "active": False}

    @app.get("/api/v1/admin/llm/config")
    async def admin_llm_config_get(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Current LLM config (from the admin panel) + the provider/model catalog for the UI.
        The API key is never returned in full — only whether one is set + its last 4."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        from arvisx.llm_client import PROVIDER_CATALOG, _PROVIDERS
        key = state.db.get_setting("_llm", "api_key", "")
        return {
            "provider": state.db.get_setting("_llm", "provider", ""),
            "model": state.db.get_setting("_llm", "model", ""),
            "base_url": state.db.get_setting("_llm", "base_url", ""),
            "api_key_set": bool(key), "api_key_last4": key[-4:] if key else "",
            "providers": sorted(_PROVIDERS.keys()), "catalog": PROVIDER_CATALOG,
            "defaults": {p: {"base_url": v[1], "model": v[2]} for p, v in _PROVIDERS.items()},
        }

    @app.post("/api/v1/admin/llm/config")
    async def admin_llm_config_set(payload: Dict[str, Any] = Body(...),
                                   authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Save the LLM provider/model/API key from the admin panel (overrides env). Blank
        api_key keeps the existing one (so you can change model without re-entering the key)."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        p = payload or {}
        provider = str(p.get("provider", "")).strip().lower()
        from arvisx.llm_client import _PROVIDERS
        if provider not in _PROVIDERS:
            raise HTTPException(400, f"unknown provider — pick one of {sorted(_PROVIDERS)}")
        state.db.set_setting("_llm", "provider", provider)
        state.db.set_setting("_llm", "model", str(p.get("model", "")).strip())
        state.db.set_setting("_llm", "base_url", str(p.get("base_url", "")).strip())
        new_key = str(p.get("api_key", "")).strip()
        if new_key:                                     # blank = keep the existing key
            state.db.set_setting("_llm", "api_key", new_key)
        os.environ["ARVIS_X_LLM"] = "1"                 # enable the LLM layer once a provider is set
        return {"saved": True, "provider": provider, "model": str(p.get("model", "")).strip()}

    @app.get("/api/v1/admin/embed/config")
    async def admin_embed_config_get(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Current embeddings config (semantic chat recall) + catalog. Key never returned in full."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        from arvisx.embeddings import EMBED_PROVIDERS, EMBED_CATALOG
        key = state.db.get_setting("_embed", "api_key", "")
        return {
            "provider": state.db.get_setting("_embed", "provider", ""),
            "model": state.db.get_setting("_embed", "model", ""),
            "base_url": state.db.get_setting("_embed", "base_url", ""),
            "api_key_set": bool(key), "api_key_last4": key[-4:] if key else "",
            "providers": sorted(EMBED_PROVIDERS.keys()), "catalog": EMBED_CATALOG,
            "defaults": {p: {"base_url": v[0], "model": v[1]} for p, v in EMBED_PROVIDERS.items()},
        }

    @app.post("/api/v1/admin/embed/config")
    async def admin_embed_config_set(payload: Dict[str, Any] = Body(...),
                                     authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Save the embeddings provider/model/API key from the admin panel (overrides env). Blank
        api_key keeps the existing one. Enables semantic (vs keyword) chat recall."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        p = payload or {}
        provider = str(p.get("provider", "")).strip().lower()
        from arvisx.embeddings import EMBED_PROVIDERS
        if provider not in EMBED_PROVIDERS:
            raise HTTPException(400, f"unknown provider — pick one of {sorted(EMBED_PROVIDERS)}")
        state.db.set_setting("_embed", "provider", provider)
        state.db.set_setting("_embed", "model", str(p.get("model", "")).strip())
        state.db.set_setting("_embed", "base_url", str(p.get("base_url", "")).strip())
        new_key = str(p.get("api_key", "")).strip()
        if new_key:
            state.db.set_setting("_embed", "api_key", new_key)
        return {"saved": True, "provider": provider, "model": str(p.get("model", "")).strip()}

    @app.get("/api/v1/admin/llm/test")
    async def admin_llm_test(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Smoke-test the LLM: one minimal round-trip. Returns ok + provider/model/latency."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        import time as _t
        if os.environ.get("ARVIS_X_LLM", "").strip() not in ("1", "true", "True"):
            return {"ok": False, "reason": "LLM disabled (ARVIS_X_LLM is off)"}
        try:
            from arvisx.llm_client import make_llm
            llm = make_llm()
        except Exception as e:
            return {"ok": False, "reason": f"make_llm failed: {e}"}
        if llm is None:
            return {"ok": False, "reason": "no LLM client (missing API key / SDK)"}
        t0 = _t.time()
        try:
            out = await llm.ask_json(
                messages=[{"role": "user", "content": 'Reply with exactly this JSON: {"pong": true}'}],
                system_msgs=[{"role": "system", "content": "You are a connectivity test. Output ONLY JSON."}],
                channel="chat")
        except Exception as e:
            return {"ok": False, "provider": getattr(llm, "provider", "?"), "model": getattr(llm, "model", "?"),
                    "latency_ms": round((_t.time() - t0) * 1000), "reason": f"call failed: {e}"}
        ms = round((_t.time() - t0) * 1000)
        reached = isinstance(out, dict)
        return {"ok": reached, "provider": getattr(llm, "provider", "?"), "model": getattr(llm, "model", "?"),
                "latency_ms": ms, "pong": bool(out.get("pong")) if isinstance(out, dict) else False,
                "reply": out, "reason": "" if reached else "no JSON returned"}

    @app.post("/api/v1/forms/run/{rid}/assign")
    async def forms_assign_run(rid: int, payload: Dict[str, Any] = Body(...)):
        """Manager assigns (or reassigns) a shift-round to a technician from the roster."""
        if not state.db.get_checklist_run(rid):
            raise HTTPException(404, f"unknown run {rid}")
        assignee = str((payload or {}).get("assignee", "")).strip()
        state.db.assign_checklist_run(rid, assignee)
        state.db.set_run_reminded(rid, 0)        # new owner → fresh reminder ladder
        if assignee:
            _notify_assignment(rid)              # DM the (new) assignee their round link
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
            raised_by=str(p.get("by", "")), priority=str(p.get("priority", "")),
            vendor=str(p.get("vendor", "")))
        iss = state.db.get_issue(iid)
        _notify_issue_event(iss, "Opened", by=str(p.get("by", "")), note=str(p.get("detail", "")))
        return _jsonable(iss)

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
        old_status = iss["status"]
        old_assignee = iss.get("assignee") or ""
        state.db.update_issue(issue_id, status=status,
                              assignee=(str(assignee) if assignee is not None else None),
                              by=str(p.get("by", "")), note=str(p.get("note", "")))
        # priority / vendor ownership (SLA + vendor accountability)
        if p.get("priority") is not None or p.get("vendor") is not None:
            state.db.set_issue_fields(
                issue_id,
                priority=(str(p["priority"]) if p.get("priority") is not None else None),
                vendor=(str(p["vendor"]) if p.get("vendor") is not None else None))
        fresh = state.db.get_issue(issue_id)
        # A1: notify manager + assigned tech on assignment / status change.
        events = []
        new_assignee = str(assignee) if assignee is not None else old_assignee
        if assignee is not None and new_assignee != old_assignee:
            events.append(f"Assigned to {new_assignee or 'unassigned'}")
        if status and status != old_status:
            events.append({"assigned": "Assigned", "in_progress": "Work started",
                           "resolved": "Resolved ✅", "open": "Reopened"}.get(status, status))
        if events:
            _notify_issue_event(fresh, " · ".join(events),
                                by=str(p.get("by", "")), note=str(p.get("note", "")))
        # Learn from the fix: when an issue is RESOLVED, an LLM synthesizes a reusable lesson
        # → pending memory candidate for manager approval. Background (no blocking, best-effort).
        if status == "resolved" and old_status != "resolved":
            rnote = str(p.get("note", "")).strip()
            if len(rnote) >= 6:
                _spawn(_learn_from_resolved_issue(issue_id))   # has a cause → learn now
            else:
                _ask_for_knowledge(issue_id, str(p.get("by", "")))   # no cause → curiously ask
        return _jsonable(fresh)

    @app.post("/api/v1/issues/{issue_id}/visited")
    async def issue_vendor_visited(issue_id: int, payload: Dict[str, Any] = Body(default={})):
        """Record a vendor site visit milestone (feeds vendor response-time analytics)."""
        if not state.db.get_issue(issue_id):
            raise HTTPException(404, f"unknown issue {issue_id}")
        state.db.append_issue_history(issue_id, "vendor visited", by=str((payload or {}).get("by", "")))
        return _jsonable(state.db.get_issue(issue_id))

    @app.get("/api/v1/issues/{issue_id}/sla")
    async def issue_sla(issue_id: int):
        from arvisx.sla import sla_status
        iss = state.db.get_issue(issue_id)
        if not iss:
            raise HTTPException(404, f"unknown issue {issue_id}")
        return sla_status(iss, state.db.get_sla_config(iss["building_id"]))

    # ── Vendors + SLA config + escalation + vendor analytics ─────────────
    @app.get("/api/v1/vendors")
    async def vendors_list(building: str = "one-anthem", all: bool = False):
        return {"building": building, "vendors": state.db.list_vendors(building, active_only=not all)}

    @app.post("/api/v1/vendors")
    async def vendor_add(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        name = str(p.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "provide 'name'")
        vid = state.db.add_vendor(str(p.get("building", "one-anthem")).strip() or "one-anthem",
                                  name, str(p.get("category", "")), str(p.get("contact", "")))
        return {"id": vid, "name": name}

    @app.post("/api/v1/vendors/{vendor_id}/deactivate")
    async def vendor_deactivate(vendor_id: int):
        state.db.set_vendor_active(vendor_id, False)
        return {"id": vendor_id, "active": False}

    @app.get("/api/v1/sla/config")
    async def sla_config_get(building: str = "one-anthem"):
        from arvisx.sla import DEFAULT_SLA
        override = state.db.get_sla_config(building)
        merged = {}
        for pr, (resp, res) in DEFAULT_SLA.items():
            r = override.get(pr, (resp, res))
            merged[pr] = {"response_hours": r[0], "resolution_hours": r[1],
                          "default": pr not in override}
        return {"building": building, "sla": merged}

    @app.post("/api/v1/sla/config")
    async def sla_config_set(payload: Dict[str, Any] = Body(...)):
        from arvisx.sla import PRIORITIES
        p = payload or {}
        pr = str(p.get("priority", "")).strip().lower()
        if pr not in PRIORITIES:
            raise HTTPException(400, f"priority must be one of {PRIORITIES}")
        try:
            state.db.set_sla_config(str(p.get("building", "one-anthem")).strip() or "one-anthem",
                                    pr, float(p["response_hours"]), float(p["resolution_hours"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "provide numeric response_hours and resolution_hours")
        return {"saved": True, "priority": pr}

    @app.post("/api/v1/escalations/run")
    async def escalations_run(building: str = "one-anthem"):
        """Sweep open issues, escalate any past SLA (one notification per new level).
        The bot calls this each poll; safe to call often."""
        from arvisx.sla import run_escalations
        return {"building": building, "fired": run_escalations(state.db, building)}

    @app.post("/api/v1/forms/reminders/run")
    async def round_reminders_run(building: str = "one-anthem"):
        """Chase assigned-but-unfinished rounds: DM the technician partway through the shift,
        escalate to the manager near shift close, lapse at shift end (shift-end-aware via the
        template timing). Bot calls each poll. Fixed-hours fallback for templates without a
        clock window: ARVISX_ROUND_REMIND_H (6) / ARVISX_ROUND_ESCALATE_H (10)."""
        from arvisx import checklist_intel as ci
        remind_h = float(os.environ.get("ARVISX_ROUND_REMIND_H", "6"))
        esc_h = float(os.environ.get("ARVISX_ROUND_ESCALATE_H", "10"))
        llm = _phrasing_llm()
        # No phraser → lapse_stale_rounds sends its deterministic notice inline. With a phraser,
        # defer the send, reword each grounded notice, then enqueue (baseline on any failure).
        lapsed = ci.lapse_stale_rounds(state.db, building, enqueue=(llm is None))
        if llm is not None:
            from arvisx.checklist_skills import phrase_line
            for f in lapsed:
                line = await phrase_line(llm, f.get("msg", ""), f.get("facts", ""))
                if line:
                    state.db.enqueue_notification(building, line, to_number="", kind="round_lapsed")
        fired = ci.round_reminders(state.db, building, remind_after_h=remind_h, escalate_after_h=esc_h)
        return {"building": building, "lapsed": lapsed, "fired": fired}

    @app.get("/api/v1/analyzers/vendors")
    async def analyzers_vendors(building: str = "one-anthem"):
        """Vendor performance: jobs, avg response/resolution hours, escalations (slowest first)."""
        from arvisx.sla import vendor_performance
        return {"building": building, "vendors": vendor_performance(state.db.list_issues(building))}

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
        from arvisx import checklist_intel as ci
        date = date or _today_str()
        runs = (await forms_today(building, date))["runs"]
        text = manager_digest(runs, date)
        aged = ci.aged_open_issues(state.db, building)        # Fix #2 — aged issues can't fade
        if aged:
            text += "\n\n*⏳ Aged open issues (>2d):*\n" + "\n".join(
                f"• {a['title']} — {a['age_days']:.0f}d [{a['status']}]"
                + (f" → {a['assignee'] or a['vendor']}" if (a['assignee'] or a['vendor']) else "")
                for a in aged[:6])
        return {"date": date, "text": text, "aged_open_issues": aged}

    @app.get("/api/v1/forms/activity")
    async def forms_activity(building: str = "one-anthem", date: str = "", limit: int = 50):
        """A grounded 'what changed today' feed — real events only (rounds submitted,
        issues opened/resolved, sign-offs), newest first. No AI, no fabrication; each
        item is a row that actually happened."""
        from arvisx.checklist_forms import get_template
        date = date or _today_str()
        events: List[Dict[str, Any]] = []

        def _name(tid: str) -> str:
            t = get_template(tid, building)
            return t.name if t else tid

        # rounds submitted today
        for run in state.db.checklist_runs_for(building, date):
            sub = run.get("submitted_at") or ""
            if run.get("status") == "submitted" and sub.startswith(date):
                events.append({"ts": sub, "kind": "round_submitted",
                               "title": f"{_name(run['template_id'])} submitted",
                               "who": run.get("assignee") or run.get("technician") or "",
                               "asset": run.get("asset") or ""})
            # sign-offs on this run today
            for s in state.db.checklist_signoffs(run["id"]):
                if (s.get("ts") or "").startswith(date):
                    events.append({"ts": s["ts"], "kind": "signoff",
                                   "title": f"{_name(run['template_id'])} signed off ({s['role']})",
                                   "who": s.get("by_user") or "", "asset": run.get("asset") or ""})

        # issues opened / resolved today
        for iss in state.db.list_issues(building):
            created = iss.get("created_at") or ""
            updated = iss.get("updated_at") or ""
            if created.startswith(date):
                events.append({"ts": created, "kind": "issue_opened",
                               "title": iss.get("title") or "Issue opened",
                               "who": iss.get("raised_by") or "", "asset": iss.get("asset") or "",
                               "severity": iss.get("severity") or ""})
            if iss.get("status") == "resolved" and updated.startswith(date) and updated != created:
                events.append({"ts": updated, "kind": "issue_resolved",
                               "title": f"Resolved: {iss.get('title') or 'issue'}",
                               "who": iss.get("assignee") or "", "asset": iss.get("asset") or ""})

        events.sort(key=lambda e: e["ts"], reverse=True)
        return {"building": building, "date": date, "events": events[:limit]}

    @app.get("/api/v1/forms/trend")
    async def forms_trend(building: str = "one-anthem", days: int = 30):
        """Per-day completion/issue trend — so the console can show today in context
        (a low day inside a healthy week/month)."""
        from arvisx import checklist_intel as ci
        return {"building": building, "trend": ci.building_trend(state.db, building, days=int(days))}

    @app.get("/api/v1/whatsapp/period-digest")
    async def wa_period_digest(building: str = "one-anthem", period: str = "week"):
        """Weekly/monthly summary text for the bot to push (or the owner to pull)."""
        from arvisx import checklist_intel as ci
        return {"period": period, "text": ci.period_summary_text(state.db, building, period)}

    @app.get("/api/v1/reports/{period}.pdf")
    async def report_pdf(period: str, building: str = "one-anthem", token: str = "",
                         authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Download the weekly/monthly operations report as a PDF. Manager/owner only. Accepts
        a normal Authorization header (dashboard) OR a ?token=<jwt> in the URL (the WhatsApp link;
        the auth middleware also honours ?token= for non-header clients like a browser tap)."""
        auth_hdr = authorization or (f"Bearer {token}" if token else "")
        _sub, role = _auth_mod.identify(auth_hdr, x_api_key, _api_key)
        if role not in ("owner", "fm", "manager", "system", "admin"):
            raise HTTPException(403, "manager/owner only")
        from arvisx import reports
        from fastapi.responses import Response
        per = "monthly" if str(period).lower().startswith(("month", "mo")) else "weekly"
        data = reports.report_data(state.db, building, per)
        summary = await reports.narrative(_llm_for_reasoning(), data, _building_name(building))
        pdf = reports.render_pdf(data, _building_name(building), summary)
        fname = f"allgud-{per}-report-{data['end']}.pdf"
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    def _report_link(period: str, building: str, sender: Dict[str, Any]) -> str:
        """A tappable, self-authenticating PDF link for WhatsApp (carries a manager token)."""
        if not _PUBLIC_URL:
            return ""
        per = "monthly" if str(period).lower().startswith(("month", "mo")) else "weekly"
        tok = _auth_mod.make_token(sender.get("name") or "manager", "fm")
        return f"{_PUBLIC_URL}/api/v1/reports/{per}.pdf?building={building}&token={tok}"

    @app.post("/api/v1/admin/send-summary")
    async def admin_send_summary(building: str = "one-anthem", period: str = "week",
                                 authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        """Operator: push the weekly/monthly summary to the owner now, on demand."""
        if not _auth_mod.is_admin(_writer_role(authorization, x_api_key)):
            raise HTTPException(403, "admin only")
        from arvisx import checklist_intel as ci
        text = ci.period_summary_text(state.db, building, period)
        owner = os.environ.get("OWNER_NUMBER", "").strip()
        sent = False
        if owner:
            state.db.enqueue_notification(building, text, to_number=owner,
                                          kind=f"{'monthly' if period == 'month' else 'weekly'}_summary")
            sent = True
        return {"period": period, "text": text, "sent_to_owner": sent}

    # ── Phase-S substrate: asset registry, asset history, PPM scheduling ──
    def _latest_run_hours(building: str, asset: str):
        """Newest logged run-hours reading for an asset (condition-based PPM input)."""
        from arvisx.checklist_forms import items_for_asset
        ids = [it.item_id for _tid, it in items_for_asset(building, asset)
               if it.kind == "reading" and it.unit == "hrs"]
        for e in state.db.asset_entries(building, ids, limit=50):
            try:
                return float(e["value"])
            except (TypeError, ValueError):
                continue
        return None

    @app.get("/api/v1/assets")
    async def assets_registry(building: str = "one-anthem"):
        """Asset names for pickers (PPM / builder): the explicit registry (active) merged
        with assets derived from checklist item tags. Unique, sorted."""
        from arvisx.checklist_forms import assets_in
        names = {a["name"] for a in state.db.list_assets_registry(building)} | set(assets_in(building))
        return {"building": building, "assets": sorted(names)}

    @app.get("/api/v1/assets/registry")
    async def assets_registry_list(building: str = "one-anthem"):
        """The explicit asset registry (full records) for the Manage Assets screen, with a
        flag for which names also appear in checklists (derived)."""
        from arvisx.checklist_forms import assets_in
        derived = set(assets_in(building))
        reg = state.db.list_assets_registry(building)
        regnames = {a["name"] for a in reg}
        out = [{**a, "in_checklists": a["name"] in derived} for a in reg]
        # derived-only assets (tagged in checklists but not registered) shown read-only
        for n in sorted(derived - regnames):
            out.append({"id": None, "name": n, "kind": "", "location": "", "active": 1, "in_checklists": True})
        return {"building": building, "assets": out}

    @app.post("/api/v1/assets")
    async def asset_add(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        name = str(p.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "provide 'name'")
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        aid = state.db.add_asset(building, name, str(p.get("kind", "")).strip(), str(p.get("location", "")).strip())
        return {"id": aid, "name": name}

    @app.post("/api/v1/assets/{asset_id}/deactivate")
    async def asset_deactivate(asset_id: int):
        state.db.set_asset_active(asset_id, False)
        return {"id": asset_id, "active": False}

    # ── B1: equipment user-manual / datasheet ────────────────────────────
    @app.post("/api/v1/assets/{asset_id}/manual")
    async def asset_manual_upload(asset_id: int, request: Request, filename: str = ""):
        """Attach a manual/datasheet to an asset. Raw file bytes in the body
        (pdf/doc/docx/txt/image). Feeds the C1 skillbook extraction later."""
        from arvisx.uploads import save_document
        if not state.db.get_asset(asset_id):
            raise HTTPException(404, f"unknown asset {asset_id}")
        try:
            name, _mt = save_document(await request.body(), filename=filename,
                                      content_type=request.headers.get("content-type", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        state.db.set_asset_manual(asset_id, name, filename or name)
        # C1: distil the manual into structured skills in the background (no LLM token-burst on
        # the upload request; the manager can also trigger it explicitly via /extract-skills).
        try:
            _spawn(_extract_asset_skills(asset_id))
        except Exception:
            pass
        return {"saved": True, "asset_id": asset_id, "manual_path": name, "manual_name": filename or name}

    @app.post("/api/v1/assets/{asset_id}/manual/clear")
    async def asset_manual_clear(asset_id: int):
        if not state.db.get_asset(asset_id):
            raise HTTPException(404, f"unknown asset {asset_id}")
        state.db.set_asset_manual(asset_id, "", "")
        return {"cleared": True, "asset_id": asset_id}

    @app.get("/api/v1/assets/manual/{name}")
    async def asset_manual_get(name: str):
        from fastapi.responses import Response
        from arvisx.uploads import file_path, media_type_any
        p = file_path(name)
        if p is None:
            raise HTTPException(404, "manual not found")
        return Response(content=p.read_bytes(), media_type=media_type_any(name))

    # ── C1: manual → structured skills (specs / PPM intervals / troubleshooting) ──
    async def _extract_asset_skills(asset_id: int) -> Dict[str, Any]:
        """Returns {knowledge, text_len, llm} so the caller can explain failures accurately."""
        from arvisx.uploads import file_path
        from arvisx import manual_skills as ms
        a = state.db.get_asset(asset_id)
        if not a or not a.get("manual_path"):
            return {"knowledge": {}, "text_len": 0, "llm": False}
        p = file_path(a["manual_path"])
        text = ms.extract_text(p) if p else ""
        try:
            from arvisx.llm_client import make_llm
            llm = make_llm()
        except Exception:
            llm = None
        knowledge = await ms.extract_skills(llm, a["name"], a.get("kind", ""), text)
        if knowledge:
            state.db.save_asset_knowledge(asset_id, a["building_id"], a["name"],
                                          a.get("manual_name", ""), knowledge)
        return {"knowledge": knowledge, "text_len": len(text), "llm": llm is not None}

    @app.post("/api/v1/assets/{asset_id}/extract-skills")
    async def asset_extract_skills(asset_id: int):
        """Distil the asset's attached manual into structured skills now (specs / PPM /
        troubleshooting). Needs a manual attached + an LLM key; degrades to 'stored only'."""
        a = state.db.get_asset(asset_id)
        if not a:
            raise HTTPException(404, f"unknown asset {asset_id}")
        if not a.get("manual_path"):
            raise HTTPException(400, "attach a manual first")
        r = await _extract_asset_skills(asset_id)
        k = r["knowledge"]
        stored = state.db.get_asset_knowledge(asset_id) or {"specs": [], "ppm": [], "troubleshooting": []}
        if k:
            note = None
        elif not r["llm"]:
            note = "LLM is unavailable right now — try again shortly."
        elif r["text_len"] < 50:
            note = "Couldn't read text from this file — it looks scanned/image-only. Upload a digital (text) PDF; OCR for scans is coming."
        else:
            note = ("Read the manual but found no equipment specs, PPM intervals, or troubleshooting "
                    "in it — is this an equipment operation/maintenance manual? (This looks like a "
                    "policy/quality document.)")
        return {"extracted": bool(k), "knowledge": stored, "note": note}

    @app.get("/api/v1/assets/{asset_id}/knowledge")
    async def asset_knowledge_get(asset_id: int):
        return state.db.get_asset_knowledge(asset_id) or {
            "asset_id": asset_id, "specs": [], "ppm": [], "troubleshooting": []}

    @app.post("/api/v1/assets/{asset_id}/knowledge")
    async def asset_knowledge_save(asset_id: int, payload: Dict[str, Any] = Body(...)):
        """Manually add/remove/edit an asset's knowledge (the operator can curate what the
        AI distilled). Replaces the stored specs/ppm/troubleshooting with what's sent."""
        a = state.db.get_asset(asset_id)
        if not a:
            raise HTTPException(404, f"unknown asset {asset_id}")
        p = payload or {}
        knowledge = {
            "specs": [s for s in (p.get("specs") or []) if isinstance(s, dict) and s.get("name")],
            "ppm": [s for s in (p.get("ppm") or []) if isinstance(s, dict) and s.get("task")],
            "troubleshooting": [s for s in (p.get("troubleshooting") or []) if isinstance(s, dict) and s.get("symptom")],
        }
        state.db.save_asset_knowledge(asset_id, a["building_id"], a["name"],
                                      a.get("manual_name", ""), knowledge)
        return {"saved": True, "knowledge": knowledge}

    @app.post("/api/v1/assets/{asset_id}/apply-ppm")
    async def asset_apply_ppm(asset_id: int):
        """One-click: turn the manual's extracted PPM intervals into this asset's PPM schedule.
        Uses the SHORTEST stated interval (services at least that often); last_done = today."""
        a = state.db.get_asset(asset_id)
        if not a:
            raise HTTPException(404, f"unknown asset {asset_id}")
        k = state.db.get_asset_knowledge(asset_id) or {}
        dated = [p for p in (k.get("ppm") or [])
                 if isinstance(p.get("interval_days"), int) and p["interval_days"] > 0]
        if not dated:
            raise HTTPException(400, "no PPM intervals with a day-count in this asset's knowledge — "
                                     "distil a manual or add a PPM row with an interval first")
        best = min(dated, key=lambda p: p["interval_days"])
        state.db.set_ppm_schedule(a["building_id"], a["name"],
                                  interval_days=int(best["interval_days"]), last_done=_today_str())
        return {"applied": True, "asset": a["name"], "interval_days": int(best["interval_days"]),
                "task": best.get("task", ""), "from_count": len(dated)}

    # ── C2: building memory — recurring issues + approved/pending lessons ──
    @app.get("/api/v1/building/memory")
    async def building_memory(building: str = "one-anthem", days: int = 90):
        from arvisx import checklist_intel as ci
        return {"building": building, "days": days,
                "recurring": ci.recurring_issues(state.db, building, days=days),
                "lessons": state.db.list_memory_candidates(building, "approved"),
                "pending": state.db.list_memory_candidates(building, "pending")}

    @app.get("/api/v1/memory/candidates")
    async def memory_candidates_list(building: str = "one-anthem", status: str = ""):
        return {"candidates": state.db.list_memory_candidates(building, status or None)}

    @app.post("/api/v1/memory/candidates")
    async def memory_candidate_add(payload: Dict[str, Any] = Body(...)):
        """Manager adds a lesson by hand → goes straight in as APPROVED (they're the curator)."""
        p = payload or {}
        title = str(p.get("title", "")).strip()
        if not title:
            raise HTTPException(400, "provide 'title'")
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        cid = state.db.add_memory_candidate(building, "manual", title, str(p.get("detail", "")),
                                            source="manual", status="approved",
                                            decided_by=str(p.get("by", "manager")))
        return {"id": cid, "title": title, "status": "approved"}

    @app.post("/api/v1/memory/candidates/{cand_id}/decide")
    async def memory_candidate_decide(cand_id: int, payload: Dict[str, Any] = Body(...)):
        if not state.db.get_memory_candidate(cand_id):
            raise HTTPException(404, f"unknown candidate {cand_id}")
        status = str((payload or {}).get("status", "")).strip().lower()
        if status not in ("approved", "rejected"):
            raise HTTPException(400, "status must be approved or rejected")
        state.db.decide_memory_candidate(cand_id, status, by=str((payload or {}).get("by", "")))
        return {"id": cand_id, "status": status}

    # ── B2: scheduled checklists (date+time triggers) ────────────────────
    @app.get("/api/v1/schedules")
    async def schedules_list(building: str = "one-anthem", all: bool = False):
        from arvisx.checklist_forms import get_template
        out = []
        for s in state.db.list_schedules(building, active_only=not all):
            t = get_template(s["template_id"], building)
            out.append({**s, "template_name": t.name if t else s["template_id"]})
        return {"building": building, "schedules": out}

    @app.post("/api/v1/schedules")
    async def schedule_add(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        template_id = str(p.get("template_id", "")).strip()
        if not template_id:
            raise HTTPException(400, "provide 'template_id'")
        mode = str(p.get("mode", "once")).strip().lower()
        recur = str(p.get("recur", "")).strip().lower()
        if mode == "once" and not str(p.get("date", "")).strip():
            raise HTTPException(400, "a one-off schedule needs a 'date'")
        if mode == "recurring" and recur not in ("daily", "weekly", "monthly"):
            raise HTTPException(400, "recurring needs recur=daily|weekly|monthly")
        dow = p.get("dow"); dom = p.get("dom")
        sid = state.db.add_schedule(
            building, template_id, label=str(p.get("label", "")).strip(), mode=mode,
            run_date=str(p.get("date", "")).strip(), run_time=str(p.get("time", "09:00")).strip(),
            recur=recur, dow=(int(dow) if dow is not None and str(dow) != "" else None),
            dom=(int(dom) if dom is not None and str(dom) != "" else None),
            assignee=str(p.get("assignee", "")).strip())
        return {"id": sid, "template_id": template_id}

    @app.post("/api/v1/schedules/{schedule_id}/deactivate")
    async def schedule_deactivate(schedule_id: int):
        state.db.set_schedule_active(schedule_id, False)
        return {"id": schedule_id, "active": False}

    @app.post("/api/v1/schedules/{schedule_id}/run-now")
    async def schedule_run_now(schedule_id: int):
        """Fire a schedule immediately (manager triggers it now) — opens the run, assigns,
        DMs the tech, and marks it fired for today so the heartbeat won't duplicate it."""
        sch = state.db.get_schedule(schedule_id)
        if not sch:
            raise HTTPException(404, f"unknown schedule {schedule_id}")
        assignee = sch.get("assignee") or ""
        rid = state.db.create_checklist_run(sch["building_id"], sch["template_id"], _today_str(),
                                            assignee=assignee)
        state.db.set_schedule_fired(schedule_id, _today_str())
        if (sch.get("mode") or "once").lower() == "once":
            state.db.set_schedule_active(schedule_id, False)
        if assignee:
            _notify_assignment(rid)
        return {"run_id": rid, "schedule_id": schedule_id}

    @app.get("/api/v1/assets/{asset}/history")
    async def asset_history(asset: str, building: str = "one-anthem", limit: int = 100):
        """Per-asset timeline: checklist entries (newest first) + issues + PPM status."""
        from arvisx.checklist_forms import items_for_asset, ppm_status
        ids = [it.item_id for _tid, it in items_for_asset(building, asset)]
        entries = state.db.asset_entries(building, ids, limit=limit)
        issues = [i for i in state.db.list_issues(building, asset=asset)]
        sched = state.db.get_ppm_schedule(building, asset)
        ppm = ppm_status(sched, _today_str(), _latest_run_hours(building, asset)) if sched else None
        return {"building": building, "asset": asset, "entries": _jsonable(entries),
                "issues": _jsonable(issues), "ppm": ppm}

    @app.get("/api/v1/ppm/schedule")
    async def ppm_schedule_list(building: str = "one-anthem"):
        from arvisx.checklist_forms import ppm_status
        out = []
        for s in state.db.list_ppm_schedules(building):
            out.append(ppm_status(s, _today_str(), _latest_run_hours(building, s["asset"])))
        return {"building": building, "schedules": out}

    @app.post("/api/v1/ppm/schedule")
    async def ppm_schedule_set(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        asset = str(p.get("asset", "")).strip()
        if not asset:
            raise HTTPException(400, "provide 'asset'")
        state.db.set_ppm_schedule(
            str(p.get("building", "one-anthem")).strip() or "one-anthem", asset,
            interval_days=(int(p["interval_days"]) if p.get("interval_days") is not None else None),
            last_done=(str(p["last_done"]) if p.get("last_done") else None),
            run_hours_limit=(float(p["run_hours_limit"]) if p.get("run_hours_limit") is not None else None))
        return {"saved": True, "asset": asset}

    @app.post("/api/v1/ppm/{asset}/done")
    async def ppm_mark_done(asset: str, payload: Dict[str, Any] = Body(default={})):
        p = payload or {}
        building = str(p.get("building", "one-anthem")).strip() or "one-anthem"
        state.db.mark_ppm_done(building, asset, str(p.get("date", "")).strip() or _today_str())
        return {"asset": asset, "last_done": p.get("date") or _today_str()}

    # ── Phase-A deterministic analyzers (L1, L2, L7, L8) — no LLM ─────────
    # All compute lives in checklist_intel (shared with the agent tools); endpoints are thin.
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @app.get("/api/v1/analyzers/readings")
    async def analyzers_readings(building: str = "one-anthem"):
        from arvisx import checklist_intel as ci
        findings, _ = ci.reading_findings(state.db, building)
        return {"building": building, "anomalies": findings}

    @app.get("/api/v1/analyzers/health")
    async def analyzers_health(building: str = "one-anthem"):
        from arvisx import checklist_intel as ci
        return {"building": building, "assets": ci.asset_health_all(state.db, building, _today_str())}

    @app.get("/api/v1/analyzers/compliance")
    async def analyzers_compliance(building: str = "one-anthem"):
        from arvisx import checklist_intel as ci
        return {"building": building, **ci.compliance(state.db, building, _today_str())}

    @app.get("/api/v1/analyzers/readiness")
    async def analyzers_readiness(building: str = "one-anthem"):
        """One building score (Maintenance Readiness) from checklist data — weighted asset
        health + round completion − PPM penalty, with its components shown. NOT live
        equipment condition (sensors upgrade the same score in Phase 1)."""
        from arvisx import checklist_intel as ci
        return {"building": building, **ci.building_readiness(state.db, building, _today_str())}

    @app.get("/api/v1/analyzers/watchlist")
    async def analyzers_watchlist(building: str = "one-anthem"):
        """L6 failure watchlist — grounded rising-concern (evidence + level), NO fabricated %."""
        from arvisx import checklist_intel as ci
        return {"building": building, "watchlist": ci.failure_watchlist(state.db, building, _today_str())}

    @app.get("/api/v1/forms/run/{rid}/review")
    async def forms_run_review(rid: int):
        """L2 Supervisor: auto-review a run — missing items + reading anomalies + trends."""
        from arvisx.checklist_forms import get_template, run_summary
        from arvisx.analyzers import reading_anomaly, trend_alert
        run = state.db.get_checklist_run(rid)
        if not run:
            raise HTTPException(404, f"unknown run {rid}")
        tmpl = get_template(run["template_id"], run["building_id"])
        entries = state.db.checklist_entries(rid)
        summ = run_summary(tmpl, entries)
        by_id = {it.item_id: it for it in tmpl.all_items()}
        missing = [{"item_id": m, "label": by_id[m].label} for m in summ["missing"] if m in by_id]
        anomalies, trends = [], []
        for it in tmpl.all_items():
            if it.kind != "reading" or it.item_id not in entries:
                continue
            cur = _num(entries[it.item_id].get("value"))
            if cur is None:
                continue
            hist = [_num(e["value"]) for e in state.db.asset_entries(run["building_id"], [it.item_id], limit=60)]
            hist = [v for v in hist if v is not None]
            r = reading_anomaly(hist[1:] if hist else [], cur)
            if r.get("flagged"):
                anomalies.append({"item_id": it.item_id, "label": it.label, **r})
            t = trend_alert(list(reversed(hist)))     # oldest→newest
            if t.get("flagged"):
                trends.append({"item_id": it.item_id, "label": it.label, **t})
        return {"run_id": rid, "completion_pct": summ["completion_pct"],
                "missing": missing, "flagged_issues": summ["issues"],
                "anomalies": anomalies, "trends": trends}

    # ── Phase C-1: Shift Handover agent (LLM if configured, else deterministic) ──
    @app.get("/api/v1/agents/handover")
    async def agent_handover(building: str = "one-anthem", notify: bool = False, to: str = ""):
        """Grounded shift-handover for the incoming shift. notify=true enqueues it (DM `to`
        if set, else ops broadcast). Falls back to deterministic text without an LLM."""
        from arvisx.checklist_skills import run_handover
        llm = None
        try:
            from arvisx.llm_client import make_llm
            llm = make_llm()
        except Exception:
            llm = None
        res = await run_handover(llm, state.db, building, _today_str())
        if notify:
            state.db.enqueue_notification(building, res["text"], to_number=to, kind="handover")
        return res

    # ── Phase C-2: Root-Cause Investigator ──────────────────────────────
    @app.get("/api/v1/agents/rca")
    async def agent_rca(asset: str, building: str = "one-anthem", notify: bool = False, to: str = ""):
        """Grounded root-cause for an asset from its checklist/issue history. LLM if
        configured + grounded, else deterministic observations + inferred cause."""
        from arvisx.checklist_skills import run_rca
        llm = None
        try:
            from arvisx.llm_client import make_llm
            llm = make_llm()
        except Exception:
            llm = None
        res = await run_rca(llm, state.db, building, asset, _today_str())
        if notify:
            state.db.enqueue_notification(building, res["text"], to_number=to, kind="rca")
        return res

    # ── Phase C-3: Work-Order agent (deterministic classification) ──────
    @app.get("/api/v1/agents/work-order")
    async def agent_work_order(issue_id: int, building: str = "one-anthem"):
        """Suggest a work order for an issue: category / priority / required team / action
        (action from the grounded RCA). Pure rules — human confirms before raising."""
        from arvisx.checklist_skills import suggest_work_order, render_work_order
        s = suggest_work_order(state.db, building, issue_id, _today_str())
        if not s:
            raise HTTPException(404, f"unknown issue {issue_id}")
        return {**s, "text": render_work_order(s)}

    # ── Phase C-4: Digital-Twin Q&A ("ask the building") ────────────────
    @app.get("/api/v1/agents/ask")
    async def agent_ask(q: str, building: str = "one-anthem"):
        """Natural-language question about the building, answered over the health/issues/
        history tools (grounded + guarded), with a deterministic fallback."""
        from arvisx.checklist_skills import run_building_qa
        if not q.strip():
            raise HTTPException(400, "provide 'q'")
        llm = None
        try:
            from arvisx.llm_client import make_llm
            llm = make_llm()
        except Exception:
            llm = None
        return await run_building_qa(llm, state.db, building, q, _today_str())

    # ── Phase D: Vision — photo → extraction PROPOSAL → operator confirms ──
    @app.post("/api/v1/vision/extract")
    async def vision_extract(request: Request, kind: str = "auto", hint: str = "",
                             building: str = "one-anthem", run_id: int = 0, item_id: str = "",
                             filename: str = ""):
        """Raw image bytes in the body. Stores the photo, runs the vision provider, and
        records a PENDING suggestion. Never writes to a checklist entry — that needs confirm."""
        from arvisx.uploads import save_photo
        from arvisx.vision import extract_from_photo
        data = await request.body()
        try:
            name, _mt = save_photo(data, filename=filename,
                                   content_type=request.headers.get("content-type", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        result = extract_from_photo(data, kind=kind, hint=hint)
        sug_id = state.db.create_vision_suggestion(
            building, name, kind, result.get("extracted", {}),
            run_id=(run_id or None), item_id=item_id)
        return {"suggestion_id": sug_id, "photo": name, "available": result.get("available", False),
                "reason": result.get("reason", ""), "kind": kind,
                "extracted": result.get("extracted", {})}

    @app.get("/api/v1/vision/suggestions")
    async def vision_suggestions(building: str = "one-anthem", status: str = ""):
        return {"building": building, "suggestions": _jsonable(state.db.list_vision_suggestions(building, status))}

    @app.post("/api/v1/vision/suggestion/{sug_id}/confirm")
    async def vision_confirm(sug_id: int, payload: Dict[str, Any] = Body(default={})):
        """Operator confirms the extraction → NOW it's written to the checklist entry
        (if run_id+item_id are on the suggestion or in the body)."""
        from arvisx.vision import confirm_suggestion
        sug = state.db.get_vision_suggestion(sug_id)
        if not sug:
            raise HTTPException(404, f"unknown suggestion {sug_id}")
        p = payload or {}
        run_id = p.get("run_id") or sug.get("run_id")
        item_id = p.get("item_id") or sug.get("item_id") or ""
        out = confirm_suggestion(state.db, sug_id, value=p.get("value"),
                                 run_id=run_id, item_id=item_id, by=str(p.get("by", "")))
        return _jsonable(out)

    @app.post("/api/v1/vision/suggestion/{sug_id}/reject")
    async def vision_reject(sug_id: int):
        if not state.db.get_vision_suggestion(sug_id):
            raise HTTPException(404, f"unknown suggestion {sug_id}")
        state.db.set_vision_suggestion_status(sug_id, "rejected")
        return {"suggestion_id": sug_id, "status": "rejected"}

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
