"""
ArvisX agent tool registry — the extensible way to give the agent new capabilities.

Adding a tool used to mean editing a dict AND a parallel schema list in agent.py. Here a
tool is ONE `@tool(...)` decorator: name, description, JSON-schema params, and a function
`fn(ctx, **args) -> dict`. The registry auto-produces the OpenAI tool schemas (native
function-calling) and the text tool-doc (JSON-ReAct fallback), and dispatches calls with
uniform error handling. Every tool returns REAL data from the deterministic floor / DB /
live store, so the agent stays grounded by construction; tools are READ-ONLY (no actuation).

`ctx` is a dict the agent fills with whatever it has: by_id, assets, risks, baselines, db,
skillbook, store, zones, wo_store. Tools degrade gracefully when a piece is absent.

To add a tool:
    @tool("get_xyz", "what it does", {"type":"object","properties":{...}})
    def _xyz(ctx, **args): return {...}
That's it — it's immediately offered to the agent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# ── schema shorthands ────────────────────────────────────────────────────
_NONE = {"type": "object", "properties": {}}
_AID = {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}
_AID_OPT = {"type": "object", "properties": {"asset_id": {"type": "string"}}}
_AID_SIG = {"type": "object", "properties": {"asset_id": {"type": "string"}, "signal": {"type": "string"}},
            "required": ["asset_id", "signal"]}


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    fn: Callable[..., Dict[str, Any]]


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: Optional[Dict[str, Any]] = None):
        def deco(fn):
            self._tools[name] = Tool(name, description, parameters or _NONE, fn)
            return fn
        return deco

    def names(self) -> List[str]:
        return list(self._tools)

    def schemas(self, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        ts = self._tools.values()
        if only is not None:
            ts = [t for t in ts if t.name in only]
        return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                  "parameters": t.parameters}} for t in ts]

    def doc(self) -> str:
        return " · ".join(f"{t.name}({','.join(t.parameters.get('properties', {}).keys())})"
                          for t in self._tools.values())

    def call(self, name: str, ctx: dict, args: Optional[dict] = None) -> Dict[str, Any]:
        t = self._tools.get(name)
        if t is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return t.fn(ctx, **(args or {}))
        except TypeError as e:
            return {"error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # tools must never crash the agent loop
            return {"error": f"{name} failed: {e}"}


REGISTRY = ToolRegistry()
tool = REGISTRY.register


# ── helpers ──────────────────────────────────────────────────────────────
def _asset(ctx, asset_id):
    return (ctx.get("by_id") or {}).get(asset_id)


def _risks_for(ctx, asset_id):
    return [r for r in (ctx.get("risks") or []) if r.asset_id == asset_id]


# ══════════════════════════════════════════════════════════════════════════
# Core investigation tools (the original 6)
# ══════════════════════════════════════════════════════════════════════════
@tool("get_asset_state", "Live signals, runtime and online state for an asset", _AID)
def _get_asset_state(ctx, asset_id: str = "", **_):
    a = _asset(ctx, asset_id)
    if not a:
        return {"error": f"unknown asset {asset_id}"}
    return {"asset_id": asset_id, "type": a.asset_type.value, "online": getattr(a, "online", None),
            "runtime_hours": getattr(a, "runtime_hours", None), "signals": dict(a.signals or {})}


@tool("get_fault_history", "Recent fault/event history for an asset (from the DB)", _AID)
def _get_fault_history(ctx, asset_id: str = "", **_):
    db = ctx.get("db")
    return {"asset_id": asset_id, "history": (db.history(asset_id, 5) if db else [])}


@tool("get_baseline", "Learned median/MAD baseline + drift sigma for one signal", _AID_SIG)
def _get_baseline(ctx, asset_id: str = "", signal: str = "", **_):
    bl = ctx.get("baselines")
    if not bl:
        return {"baseline": None, "note": "no learned baseline available"}
    base = bl.baseline(asset_id, signal)
    z = bl.drift_z(asset_id, signal)
    if base is None:
        return {"baseline": None, "note": "insufficient history"}
    med, mad, n = base
    return {"asset_id": asset_id, "signal": signal, "median": round(med, 2), "mad": round(mad, 3),
            "samples": n, "drift_sigma": (round(z, 2) if z is not None else None)}


@tool("check_dependency_impact", "Downstream service impact + lost redundancy if this asset degrades", _AID)
def _check_dependency_impact(ctx, asset_id: str = "", **_):
    from arvisx.topology import impact_analysis
    a = _asset(ctx, asset_id)
    rel = _risks_for(ctx, asset_id)
    if not a or not rel:
        return {"impact": None}
    imp = impact_analysis(ctx.get("assets") or [], rel)
    return {"impacts": [{"service": c.service.value, "impact": c.impact, "redundancy": c.redundancy,
                         "readiness_delta": c.readiness_delta, "note": c.note} for c in imp]}


@tool("recall_known_pattern", "Prior confirmed fault pattern for this equipment class (institutional memory)", _AID)
def _recall_known_pattern(ctx, asset_id: str = "", **_):
    sb = ctx.get("skillbook")
    a = _asset(ctx, asset_id)
    rel = _risks_for(ctx, asset_id)
    if not sb or not a or not rel:
        return {"known_pattern": None}
    return {"known_pattern": sb.recall(a, rel[0])}


@tool("get_active_risks", "All currently active risks across the community", _NONE)
def _get_active_risks(ctx, **_):
    return {"risks": [{"asset_id": r.asset_id, "service": r.service.value, "severity": r.severity.value,
                       "confidence": r.confidence, "message": r.message} for r in (ctx.get("risks") or [])]}


# ══════════════════════════════════════════════════════════════════════════
# Domain tools — the rest of the ArvisX engine, exposed to the agent
# ══════════════════════════════════════════════════════════════════════════
@tool("get_water_status", "Water availability: stored litres, hours remaining, refill feasibility, forecast", _NONE)
def _get_water_status(ctx, **_):
    from arvisx.water import assess_water
    w = assess_water(ctx.get("assets") or [], ctx.get("baselines"))
    return {"band": w.band, "stored_l": round(w.stored_l), "fill_pct": round(w.fill_pct, 1),
            "draw_lph": round(w.draw_lph, 1), "hours_remaining": w.hours_remaining,
            "can_refill": w.can_refill, "forecast": w.forecast}


@tool("get_cost_estimate", "Money impact of an asset's active risk: energy waste/month or failure exposure range", _AID)
def _get_cost_estimate(ctx, asset_id: str = "", **_):
    from arvisx.economics import estimate, money_line
    rel = _risks_for(ctx, asset_id)
    if not rel:
        return {"cost": None, "note": "no active risk for this asset"}
    est = estimate(rel[0], _asset(ctx, asset_id), ctx.get("baselines"))
    return {"asset_id": asset_id, "kind": est.kind, "monthly_waste": est.monthly_waste,
            "exposure_low": est.exposure_low, "exposure_high": est.exposure_high,
            "currency": est.currency, "summary": money_line(est), "basis": est.basis}


@tool("get_community_cost", "Total recurring waste + failure exposure across all active risks", _NONE)
def _get_community_cost(ctx, **_):
    from arvisx.economics import community_cost
    from arvisx.health import build_report
    assets = ctx.get("assets") or []
    rep = build_report(assets, baselines=ctx.get("baselines"), virtual=True, water=True)
    c = community_cost(rep, assets, ctx.get("baselines"))
    return {"currency": c["currency"], "monthly_waste": c["monthly_waste"],
            "exposure_low": c["exposure_low"], "exposure_high": c["exposure_high"],
            "top": c["items"][:4]}


@tool("get_community_readiness", "Overall Community Readiness % + per-service health bands", _NONE)
def _get_community_readiness(ctx, **_):
    from arvisx.health import build_report
    rep = build_report(ctx.get("assets") or [], baselines=ctx.get("baselines"), virtual=True, water=True)
    return {"readiness": round(rep.readiness, 1), "band": rep.readiness_band,
            "services": [{"service": s.service.value, "band": s.band.value, "score": round(s.score)}
                         for s in rep.services]}


@tool("get_virtual_sensors", "Derived PM indicators for an asset (power-creep, cycling, dry-run, duty, turnover)", _AID)
def _get_virtual_sensors(ctx, asset_id: str = "", **_):
    from arvisx.virtual_sensors import derive_all
    a = _asset(ctx, asset_id)
    if not a:
        return {"error": f"unknown asset {asset_id}"}
    readings, _risks = derive_all(a, ctx.get("baselines"))
    return {"asset_id": asset_id, "virtual": [{"key": r.key, "value": r.value, "unit": r.unit,
                                               "note": r.note} for r in readings]}


@tool("get_fusion_findings", "Cross-signal sensor-fusion findings (multi-modality corroborated conclusions)", _NONE)
def _get_fusion_findings(ctx, **_):
    from arvisx.fusion import assess_fusion
    fs = assess_fusion(ctx.get("assets") or [], ctx.get("baselines"))
    return {"findings": [{"asset_id": f.asset_id, "conclusion": f.conclusion, "action": f.action,
                          "confidence": f.confidence_band, "modalities": f.modalities} for f in fs]}


@tool("get_signal_quality", "Sensor-health for an asset: out-of-range/spike/stuck risks + quarantined readings", _AID)
def _get_signal_quality(ctx, asset_id: str = "", **_):
    from arvisx.signal_quality import assess_quality_risks
    a = _asset(ctx, asset_id)
    if not a:
        return {"error": f"unknown asset {asset_id}"}
    risks = assess_quality_risks(a, ctx.get("baselines"))
    store = ctx.get("store")
    quarantined = [q for q in (getattr(store, "quarantined", []) or [])
                   if q.get("asset_id") == asset_id] if store else []
    return {"asset_id": asset_id, "sensor_risks": [r.message for r in risks], "quarantined": quarantined}


@tool("get_stale_signals", "Signals not updated recently (frozen sensors) across the live store", _NONE)
def _get_stale_signals(ctx, **_):
    store = ctx.get("store")
    if not store or not hasattr(store, "stale_signals"):
        return {"stale": [], "note": "no live store in context"}
    return {"stale": [{"asset_id": a, "signal": s, "age_s": age} for a, s, age in store.stale_signals()]}


@tool("get_zone_occupancy", "Conditioned-zone occupancy + ghost-load (empty but running) findings", _NONE)
def _get_zone_occupancy(ctx, **_):
    zones = ctx.get("zones")
    if not zones:
        return {"zones": [], "note": "no zones in context"}
    from arvisx.occupancy import assess_zones
    _load, _risks, ghosts = assess_zones(zones)
    return {"ghost_alerts": [{"zone": g.zone_name, "note": g.note} for g in ghosts],
            "zone_risks": [r.message for r in _risks]}


@tool("get_work_orders", "Open/active work orders, optionally for one asset", _AID_OPT)
def _get_work_orders(ctx, asset_id: str = "", **_):
    wo = ctx.get("wo_store")
    if not wo:
        return {"work_orders": [], "note": "no work-order store in context"}
    items = wo.all()
    if asset_id:
        items = [w for w in items if w.asset_id == asset_id]
    return {"work_orders": [{"wo_id": w.wo_id, "asset_id": w.asset_id, "title": w.title,
                             "status": w.status.value, "priority": w.priority.value} for w in items]}


@tool("get_baseline_readiness", "Whether the learned baselines are trustworthy enough for operations "
      "(coverage + stability) — the data-driven learning gate", _NONE)
def _get_baseline_readiness(ctx, **_):
    from arvisx.readiness import assess_baseline_readiness
    rd = assess_baseline_readiness(ctx.get("assets") or [], ctx.get("baselines"))
    return {"ready": rd.ready, "coverage": rd.coverage, "ready_count": rd.ready_count,
            "total": rd.total, "reasons": rd.reasons,
            "suggested_extra_days": rd.suggested_extra_days, "summary": rd.summary()}


@tool("get_maintenance_schedule", "Upcoming maintenance/test due dates + runtime-vs-threshold, optionally one asset",
      _AID_OPT)
def _get_maintenance_schedule(ctx, asset_id: str = "", **_):
    from datetime import datetime
    now = datetime.now()
    assets = [_asset(ctx, asset_id)] if asset_id else (ctx.get("assets") or [])
    out = []
    for a in assets:
        if a is None:
            continue
        due = getattr(a, "next_maintenance_due", None)
        days = round((due - now).total_seconds() / 86400.0, 1) if due else None
        rt, rtt = getattr(a, "runtime_hours", None), getattr(a, "runtime_threshold_hours", None)
        out.append({"asset_id": a.asset_id, "maintenance_due_in_days": days,
                    "runtime_hours": rt, "runtime_threshold_hours": rtt,
                    "runtime_pct": (round(100 * rt / rtt, 1) if rt and rtt else None)})
    return {"schedule": out}


@tool("compare_to_peer_asset", "Compare an asset's signals to same-type peers to spot an outlier sibling", _AID)
def _compare_to_peer_asset(ctx, asset_id: str = "", **_):
    a = _asset(ctx, asset_id)
    if not a:
        return {"error": f"unknown asset {asset_id}"}
    peers = [p for p in (ctx.get("assets") or [])
             if p.asset_type == a.asset_type and p.asset_id != a.asset_id]
    if not peers:
        return {"asset_id": asset_id, "peers": 0, "note": "no same-type peer to compare"}
    cmp = {}
    for k, v in (a.signals or {}).items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        pv = [p.signals[k] for p in peers if isinstance(p.signals.get(k), (int, float))
              and not isinstance(p.signals.get(k), bool)]
        if not pv:
            continue
        peer_mean = sum(pv) / len(pv)
        dev = (v - peer_mean) / peer_mean * 100 if peer_mean else None
        cmp[k] = {"value": v, "peer_mean": round(peer_mean, 2),
                  "deviation_pct": (round(dev, 1) if dev is not None else None)}
    return {"asset_id": asset_id, "peers": len(peers), "comparison": cmp}


@tool("get_skill_history", "Learned fault patterns (institutional memory) for this building", _NONE)
def _get_skill_history(ctx, **_):
    sb = ctx.get("skillbook")
    if not sb:
        return {"skills": [], "note": "no skillbook in context"}
    return {"skills": [{"scope": s["scope"], "symptom": s["symptom"], "cause": s["cause"],
                        "confirmed": bool(s["confirmed"]), "times_seen": s["times_seen"]}
                       for s in sb.all()[:10]]}
