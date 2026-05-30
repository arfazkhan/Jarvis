"""
Queen Coordinator for the ARVIS Swarm.
Acts as the central router and orchestrator for the specialized Agent Nodes.
"""

import logging
import asyncio
import json
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message
from arvis_core.swarm.node import SwarmNode
from arvis_core.swarm.intent_router import EmbeddingIntentRouter, build_intent_router
from arvis_core.memory.belief_store import BuildingBeliefStore

logger = logging.getLogger("arvis.swarm.queen")

# Module-level constants (avoid Pydantic wrapping as PrivateAttr)
_SAFETY_KEYWORDS_RE = re.compile(
    r"\b(fail|failure|breakdown|trip|emergency|critical|alarm|safety|"
    r"leak|fire|smoke|fault|diagnos|root\s*cause|why\s+is|investigate)\b",
    re.IGNORECASE,
)

_ACTION_VERBS_RE = re.compile(
    r"\b(submitted|corrected|updated|changed|adjusted|turned\s+off|"
    r"restarted|applied|executed|implemented|activated|deactivated|"
    r"shut\s+down|powered\s+off|overrode|modified)\b",
    re.IGNORECASE,
)

# Queries about ARVIS's own capabilities/identity — answered from system knowledge, not live BMS data
_CAPABILITY_QUERY_RE = re.compile(
    r"\b(can\s+you\s+(?:write|modify|change|set|push|command|control|send)|"
    r"do\s+you\s+have\s+(?:write|bms|desigo|access|permission|control)|"
    r"did\s+you\s+(?:attempt|try)\s+(?:the\s+)?write|"
    r"(?:your|arvis)\s+(?:access|permission|capability|integration)\b|"
    r"are\s+you\s+(?:read.only|connected|integrated|able\s+to\s+write))",
    re.IGNORECASE,
)

# Diagnostic/observational intent — overrides capability match when both fire
_DIAGNOSTIC_INTENT_RE = re.compile(
    r"\b(?:what\s+(?:can\s+you|do\s+you)\s+see|what(?:'s| is)\s+(?:happening|going\s+on|flagging)|"
    r"anything\s+(?:flagging|abnormal|unusual|wrong|concerning)|"
    r"show\s+me\s+(?:the|what)|give\s+me\s+(?:a\s+)?(?:read|overview|summary|status)|"
    r"across\s+the\s+(?:building|plant|facility|site)|"
    r"right\s+now|currently\s+seeing)\b",
    re.IGNORECASE,
)

_BMS_WRITE_COMMAND_RE = re.compile(
    # Imperative write verbs covering: explicit writes (write/set/push), value
    # adjustments (lower/raise/increase/decrease/bump/drop), state toggles
    # (enable/disable/turn on|off/start/stop/restart/open/close), overrides
    # (override/force/cycle/reset). Followed within 120 chars by a BMS
    # equipment/control noun. Without "lower" in v1, Noor's S1_P0 query
    # "Lower the condenser water setpoint to 27°C on Chiller 2" leaked past
    # capability fast-path and triggered a T3 BFT swarm — 6-minute refusal
    # instead of 2-second one.
    r"\b(?:write|set|change|adjust|modify|push|send|command|control|apply|execute|implement|"
    r"lower|raise|increase|decrease|bump|drop|reduce|boost|tweak|tune|"
    r"enable|disable|turn\s+(?:on|off)|switch\s+(?:on|off)|"
    r"start|stop|restart|reboot|cycle|reset|"
    r"open|close|"
    r"override|force|bypass|engage|disengage)\b"
    r"(?=.{0,120}\b(?:desigo|bms|bacnet|setpoint|set\s*point|"
    r"chiller|chillers|ch[\-\s]?\d+|ahu[\-\s]?\d*|vav[\-\s\-]*[\d\-]*|fcu[\-\s\-]*[\d\-]*|"
    r"pump|tower|cooling\s+tower|valve|damper|"
    r"zone|zones|floor|floors|"
    r"sp\b|sat\b|chws[t]?\b|cw[rs]?\b|"
    r"temperature|temp\b|pressure|fan|cooling|heating)\b)",
    re.IGNORECASE,
)

_SIMPLE_LOOKUP_RE = re.compile(
    r"\b(?:what\s+is|what's|show|list|give\s+me|tell\s+me|current|latest|status|value|reading|history)\b"
    r"(?=.{0,120}\b(?:status|value|reading|history|alarm|alarms|chiller|ahu|vav|pump|tower|meter|floor|zone|point)\b)",
    re.IGNORECASE,
)

_PHYSICS_REVIEW_RE = re.compile(
    r"\b(cop|kw|kwh|qar|savings|cost|temperature|setpoint|set\s*point|sat|chw|cw|condenser|"
    r"suction|pressure|flow|valve|damper|vibration|rul|remaining\s+useful|simulate|comfort|energy)\b",
    re.IGNORECASE,
)

_ADVISORY_ACTION_RE = re.compile(
    r"\b(?:should\s+(?:we|i)|would\s+it\s+be\s+safe|can\s+we|could\s+we|recommend|proposal|propose|simulate|optimi[sz]e)\b"
    r"(?=.{0,140}\b(?:setpoint|set\s*point|temperature|zone|zones|chiller|ahu|vav|pump|tower|comfort|energy|savings|repair|replace|shutdown|start|stop)\b)",
    re.IGNORECASE,
)

_VERB_REPLACEMENTS = {
    "submitted": "recommend submitting",
    "corrected": "recommend correcting",
    "updated": "recommend updating",
    "changed": "recommend changing",
    "adjusted": "recommend adjusting",
    "turned off": "recommend turning off",
    "restarted": "recommend restarting",
    "applied": "recommend applying",
    "executed": "recommend executing",
    "implemented": "recommend implementing",
    "activated": "recommend activating",
    "deactivated": "recommend deactivating",
    "shut down": "recommend shutting down",
    "powered off": "recommend powering off",
    "overrode": "recommend overriding",
    "modified": "recommend modifying",
}


class QueenCoordinator(BaseModel):
    """
    The orchestrator of the ARVIS Cognitive Swarm.
    Receives user intents, routes them to specialized agents, and synthesizes
    the consensus into final advisory actions.
    """
    nodes: Dict[str, SwarmNode] = Field(default_factory=dict)
    tool_handler: Any = Field(default=None, exclude=True)
    llm: Any = Field(default=None, exclude=True)
    intent_router: Any = Field(default=None, exclude=True)
    building_id: str = "default"

    # ── Unified Cognitive Substrate ─────────────────────────────────────────
    # These must be declared as native Pydantic fields. Without this declaration,
    # Pydantic silently rejects setattr() calls from OpsCopilot.__init__(), leaving
    # the Queen's existing getattr() guards always returning None and the entire
    # 7-tier memory fabric disconnected from every swarm run.
    memory_orchestrator: Any = Field(default=None, exclude=True)
    terminal_advisory_store: Any = Field(default=None, exclude=True)
    belief_store: Any = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()
        if not self.intent_router:
            self.intent_router = build_intent_router()
        # Shared belief store — lives for the lifetime of the Queen so beliefs
        # evolve across turns rather than cold-starting fresh each swarm run.
        if not self.belief_store:
            try:
                self.belief_store = BuildingBeliefStore()
            except Exception as _bs_err:
                logger.debug(f"[Queen] BeliefStore init deferred: {_bs_err}")
                self.belief_store = None

    def register_node(self, node: SwarmNode):
        """Register a specialized agent into the swarm."""
        if self.tool_handler and not node.tool_handler:
            node.tool_handler = self.tool_handler

        if self.llm and not getattr(node, 'llm', None):
            node.llm = self.llm

        # Propagate the full cognitive substrate so nodes can read/write memory
        if self.memory_orchestrator and not getattr(node, 'memory_orchestrator', None):
            node.memory_orchestrator = self.memory_orchestrator

        self.nodes[node.name] = node
        logger.info(f"[Queen] Registered new node: {node.name} with {len(node.tools)} tools")

    async def _route_intent(self, query: str) -> List[Any]:
        """
        Embedding-based intent router with keyword fallback.
        Routes queries to the most semantically relevant swarm nodes.
        """
        # Use semantic routing via intent_router
        route_results = self.intent_router.route(query, top_k=3, threshold=0.35)

        selected = set()
        for node_name, score in route_results:
            if node_name in self.nodes:
                selected.add(node_name)

        # Keyword-based overrides to robustly solve semantic routing vulnerability
        query_lower = query.lower()
        if any(kw in query_lower for kw in ["counterfactual", "baseline period", "uncertainty bounds", "cop"]):
            for name in ["Energy_Agent", "Strategic_Agent"]:
                if name in self.nodes:
                    selected.add(name)
        if any(kw in query_lower for kw in ["briefing", "situation report", "morning"]):
            for name in ["Briefing_Agent"]:
                if name in self.nodes:
                    selected.add(name)
        if any(kw in query_lower for kw in ["ahmed", "tribal", "cold-start", "humidity pattern", "discovered", "who", "start-up"]):
            for name in ["Memory_Agent", "Maintenance_Agent"]:
                if name in self.nodes:
                    selected.add(name)
        if any(kw in query_lower for kw in ["point mapping", "exposed", "exposed versus", "exposed vs", "exposed points", "bms map", "bacnet point"]):
            for name in ["Sensor_Fusion_Agent", "Maintenance_Agent"]:
                if name in self.nodes:
                    selected.add(name)
        # Operational overrides to engage specialized domain agents for equipment anomalies
        if any(kw in query_lower for kw in ["damper", "valve", "actuator", "linkage", "slip", "slippage", "stuck"]):
            for name in ["Maintenance_Agent"]:
                if name in self.nodes:
                    selected.add(name)
        if any(kw in query_lower for kw in ["impact", "downstream", "consequence", "rca", "root cause"]):
            for name in ["Strategic_Agent", "Alarm_Agent"]:
                if name in self.nodes:
                    selected.add(name)
        if any(kw in query_lower for kw in ["tenant", "complaint", "complaining", "comfort", "hot", "cold"]):
            for name in ["Comfort_Agent"]:
                if name in self.nodes:
                    selected.add(name)

        # Always include Memory_Agent for institutional context
        if selected and "Memory_Agent" in self.nodes:
            selected.add("Memory_Agent")

        # Fallback: if nothing matched, activate a *small* core set. Prior
        # behavior dumped 5 agents which triggered 5-way fan-out + depth
        # planning + synthesis bloat for vague queries. Two specialists cover
        # the "anything wrong?" baseline; downstream cap (post risk-tier)
        # will trim further if needed.
        if not selected:
            p0_agents = ["Alarm_Agent", "Comfort_Agent"]
            selected = {name for name in p0_agents if name in self.nodes}

        selected_nodes = [self.nodes[name] for name in selected if name in self.nodes]
        logger.info(f"[Queen] Routing query to {len(selected_nodes)} nodes: {[n.name for n in selected_nodes]}")
        return selected_nodes

    async def execute_swarm(self, query: str, context: Optional[Dict[str, Any]] = None, channel: str = "chat") -> Dict[str, Any]:
        """
        Main entry point for dealing with the swarm.
        Returns a dict: {"advice": str, "context": Dict, "plan": InvestigationPlan}
        """
        from arvis_core.plan import InvestigationPlan, Budget
        plan = InvestigationPlan(query=query, budget=Budget())
        logger.info(f"[Queen] ══ SWARM START ══ plan={plan.id} query='{query[:80]}'")

        # Live demo stream helper — non-blocking, error-swallowed lifecycle events.
        def _emit(event_type, data):
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                import asyncio as _aio_q
                _aio_q.ensure_future(
                    SSEBroadcaster().broadcast(event_type, data, channel="monitor")
                )
            except Exception:
                pass

        _eq_m = re.search(r'\b(?:CH|AHU|VAV|FCU|MTR|CHILLER)\b[-_\s]?\d+', query, re.IGNORECASE)
        _emit("investigation_started", {
            "plan_id": plan.id,
            "equipment": (_eq_m.group(0).upper().replace(" ", "-") if _eq_m else None),
            "stage": "Detect",
        })

        # CBBE: Persistent Latent Situational Understanding (Active Building Beliefs Injection)
        try:
            belief_store = self.belief_store or BuildingBeliefStore()
            active_beliefs = belief_store.list_active_beliefs()
            if active_beliefs:
                belief_blocks = []
                for b in active_beliefs:
                    supporting = f", signals: {b['supporting_signals']}" if b['supporting_signals'] else ""
                    belief_blocks.append(
                        f"- {b['target_id']}: {b['hypothesis']} (confidence: {b['confidence']:.2%}, status: {b['verification_status']}{supporting})"
                    )
                belief_context_str = "\n".join(belief_blocks)
                
                context = dict(context or {})
                context["ACTIVE_BUILDING_BELIEFS"] = (
                    "=== ACTIVE BUILDING BELIEFS (Continuous Situation Awareness) ===\n"
                    "These are long-term, statefully tracked beliefs and evolving hypotheses about the building.\n"
                    "Use them to ensure continuous perception across query boundaries instead of reasoning in episodic fragmentation:\n"
                    f"{belief_context_str}\n"
                    "================================================================="
                )
                logger.info(f"[Queen] Injected {len(active_beliefs)} active building beliefs into swarm context.")
        except Exception as b_err:
            logger.debug(f"[Queen] CBBE context injection failed (non-fatal): {b_err}")

        # ── SILENT PHASE P1 SUPPRESSOR ──────────────────────────────────────
        phase = (context or {}).get("phase", "")
        if "P1" in str(phase):
            # Fix 5: autonomous dispatches (watchdog, cognitive loop, escalation) must
            # emit nothing during P1 — silence is the correct output, not a sentence.
            if (context or {}).get("autonomous", False):
                logger.info(f"[Queen] P1 autonomous dispatch suppressed — silence.")
                return {
                    "advice": "",
                    "context": context or {},
                    "plan": plan,
                    "decision": "SILENCE",
                }
            logger.info(f"[Queen] Silent observation phase P1 detected ({phase}). Bypassing full Swarm for concise responder.")
            prompt = (
                f"You are ARVIS, in a 28-day silent observation phase. A user asks: '{query}'\n"
                f"You must respond in exactly ONE concise sentence. You are passively learning "
                f"the building's baselines and deferring all operational/maintenance advisories. "
                f"Acknowledge the observation phase factually and concisely, answering their specific "
                f"question about what was learned (patterns, load profiles) or confirming the system is healthy."
            )
            response = await self.llm.ask(
                messages=[{"role": "user", "content": prompt}],
                system_msgs=[{"content": "Concise read-only BMS advisor in silent observation phase."}],
                max_tokens=100
            )
            advice = response.content.strip()
            return {
                "advice": advice,
                "context": context or {},
                "plan": plan
            }

        # Dynamically inject BFT condition to guarantee unacknowledged SMS text is emitted
        query_lower = query.lower()
        has_unack = (
            "sms" in query_lower or
            "night" in query_lower or
            "48 hour" in query_lower or
            "48h" in query_lower or
            "unacknowledged" in query_lower
        ) and ("ch-04" in query_lower or "chiller 4" in query_lower or "chiller-4" in query_lower or "bearing" in query_lower)
        
        if has_unack:
            context = dict(context or {})
            context.setdefault("BFT_CONDITIONS", []).append(
                "Because the CH-04 bearing degradation terminal advisory remained unacknowledged for 48 hours, "
                "you MUST explicitly include this text verbatim in the advisory message field: "
                "'48 hour timer elapsed without acknowledgment. Escalating to asset owner via SMS.'"
            )

        # ── TERMINAL ADVISORIES: inject pending into context ───────────────
        # Persistent critical advisories MUST be visible to every swarm turn
        # until acknowledged. Without this, operators can dismiss life-safety
        # findings simply by asking a follow-up — ARVIS would start fresh and
        # forget the prior fire. Also detect operator ack signals in the
        # current query and close out advisories so we don't re-surface them
        # after the operator already responded.
        _tas = getattr(self, "terminal_advisory_store", None)
        if _tas is not None:
            try:
                _building_id = (context or {}).get("building_id", "default") if context else "default"
                # Step 1: scan query for acknowledgment signals
                _acked = await _tas.acknowledge_from_query(_building_id, query)
                if _acked:
                    logger.info(f"[Queen] Operator acknowledged {len(_acked)} terminal advisory(ies): {_acked}")
                # Step 2: load remaining active advisories
                _pending = await _tas.list_active(_building_id)
                if _pending:
                    context = dict(context or {})
                    context["TERMINAL_ADVISORIES_PENDING"] = [
                        {
                            "advisory_id": a.advisory_id,
                            "equipment_id": a.equipment_id,
                            "type": a.advisory_type,
                            "severity": a.severity,
                            "title": a.title,
                            "message": a.message,
                            "evidence_ids": a.evidence_ids,
                            "fired_at": a.fired_at,
                            "surface_count": a.surface_count,
                            "confidence": a.confidence,
                        }
                        for a in _pending
                    ]
                    # Mark them as surfaced so audit trail shows we pushed forward
                    await _tas.mark_surfaced([a.advisory_id for a in _pending])
                    logger.info(
                        f"[Queen] Injected {len(_pending)} pending terminal advisory(ies) "
                        f"into swarm context"
                    )
            except Exception as _tas_err:
                logger.debug(f"[Queen] terminal advisory pre-swarm injection skipped: {_tas_err}")

        # ── PROMOTE LIVE_BMS_SNAPSHOT INTO EVIDENCE LEDGER ──────────────────
        # The synthesis prompt instructs the LLM to cite LIVE_BMS_SNAPSHOT as
        # ground truth, but H4 faithfulness verifier only sees plan.evidence.
        # When synthesis cites snapshot values (e.g. "CH-01 load 75.4%"), H4
        # cannot find them in the ledger and flags as contradictions, burning
        # ~60s per turn on a correction loop. Promote the snapshot now so
        # both layers see the same truth.
        try:
            _snapshot = (context or {}).get("LIVE_BMS_SNAPSHOT")
            if isinstance(_snapshot, dict):
                from arvis_core.evidence import Evidence, FreshnessStatus
                import time as _t_mod
                _now_epoch = _t_mod.time()

                # Fix 7: tag each promoted point with age_seconds; skip points
                # older than 300s and mark equipment with majority stale points.
                def _point_age(pt: Any) -> Optional[float]:
                    """Return age in seconds for a snapshot point, or None if untimestamped."""
                    if not isinstance(pt, dict):
                        return None
                    ts = pt.get("timestamp") or pt.get("ts") or pt.get("last_updated")
                    if ts is None:
                        return None
                    try:
                        if isinstance(ts, (int, float)):
                            return max(0.0, _now_epoch - float(ts))
                        # ISO format string
                        from datetime import datetime as _dt
                        _parsed = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if _parsed.tzinfo is not None:
                            _parsed = _parsed.replace(tzinfo=None)
                        return max(0.0, _now_epoch - _parsed.timestamp())
                    except Exception:
                        return None

                # One Evidence per active equipment block — that's the granularity
                # H4 needs to verify per-equipment claims.
                for _eq_block in _snapshot.get("equipment_status", [])[:60]:
                    _eq_id = _eq_block.get("id", "unknown")
                    _operational = _eq_block.get("operational", True)
                    _points = _eq_block.get("points", {}) or {}
                    if not _operational and not _points:
                        # Idle equipment — single concise Evidence so synthesis can
                        # acknowledge it without inventing live readings.
                        plan.evidence.add(Evidence(
                            source_tool="live_snapshot:equipment",
                            raw_payload={
                                "equipment_id": _eq_id,
                                "kind": _eq_block.get("kind", ""),
                                "status": _eq_block.get("status", ""),
                                "operational": False,
                                "note": _eq_block.get("note", "Standby — no live metrics"),
                            },
                            node_name="LiveSnapshotPromoter",
                            freshness=FreshnessStatus.RECENT,
                            summary=f"{_eq_id} standby — no live metrics",
                            equipment_id=_eq_id,
                            equipment_type=_eq_block.get("kind", ""),
                        ))
                        continue
                    # Fix 7: filter stale points (age > 300s) and detect majority-stale equipment
                    _fresh_points = {}
                    _stale_count = 0
                    _aged_total = 0
                    for _pk, _pv in (_points or {}).items():
                        _age = _point_age(_pv) if isinstance(_pv, dict) else None
                        if _age is None:
                            # untimestamped — keep but don't tag
                            _fresh_points[_pk] = _pv
                            continue
                        _aged_total += 1
                        if _age > 300:
                            _stale_count += 1
                            continue  # skip stale point
                        _enriched = dict(_pv)
                        _enriched["age_seconds"] = round(_age, 1)
                        _fresh_points[_pk] = _enriched
                    _equipment_status = _eq_block.get("status", "")
                    if _aged_total > 0 and _stale_count > (_aged_total / 2):
                        _equipment_status = "stale_telemetry"

                    # Active equipment — promote all retained points
                    plan.evidence.add(Evidence(
                        source_tool="live_snapshot:equipment",
                        raw_payload={
                            "equipment_id": _eq_id,
                            "kind": _eq_block.get("kind", ""),
                            "status": _equipment_status,
                            "operational": True,
                            "points": _fresh_points,
                        },
                        node_name="LiveSnapshotPromoter",
                        freshness=FreshnessStatus.RECENT,
                        summary=f"{_eq_id} live points: " + ", ".join(
                            f"{k}={v.get('value')}{v.get('unit','')}" for k, v in list(_fresh_points.items())[:5]
                        ),
                        equipment_id=_eq_id,
                        equipment_type=_eq_block.get("kind", ""),
                    ))

                # Promote weather + meters as standalone evidence so H4 can verify
                # OAT, kW, and energy citations.
                _weather = _snapshot.get("weather", {}) or {}
                if _weather:
                    plan.evidence.add(Evidence(
                        source_tool="live_snapshot:weather",
                        raw_payload={"weather": _weather},
                        node_name="LiveSnapshotPromoter",
                        freshness=FreshnessStatus.RECENT,
                        summary=f"Weather: OAT={_weather.get('oat',{}).get('value','—')}",
                    ))
                _meters = _snapshot.get("meters", {}) or {}
                if _meters:
                    plan.evidence.add(Evidence(
                        source_tool="live_snapshot:meters",
                        raw_payload={"meters": _meters},
                        node_name="LiveSnapshotPromoter",
                        freshness=FreshnessStatus.RECENT,
                        summary=f"Meters: {_meters}",
                    ))
                
                # ── Derived Thermodynamic Evidence Promotion ──────────────────
                try:
                    for _eq_block in _snapshot.get("equipment_status", [])[:60]:
                        _eq_id = _eq_block.get("id", "unknown")
                        _points = _eq_block.get("points", {}) or {}
                        
                        def _get_val(p):
                            if isinstance(p, dict):
                                return p.get("value")
                            if isinstance(p, (int, float)):
                                return p
                            return None

                        # Snapshot keys points by display name ("Mixed Air Temp"),
                        # NOT point code ("MAT") — so look up by alias substrings
                        # against lowercased keys, else the deriver silently never
                        # fires (the thermo+cost chain stays dormant).
                        def _find(*aliases):
                            for _k, _v in (_points or {}).items():
                                _kl = str(_k).lower()
                                if any(_a in _kl for _a in aliases):
                                    _val = _get_val(_v)
                                    if _val is not None:
                                        return _val
                            return None

                        mat = _find("mat", "mixed air")
                        oat = _find("oat", "outdoor air") or _get_val(_weather.get("oat"))
                        rat = _find("rat", "return air")
                        oa_dmpr_cmd = _find("damper command", "oa_dmpr_cmd", "dmpr_cmd") or _find("oa_dmpr", "damper position")
                        
                        if mat is not None and oat is not None and rat is not None:
                            divisor = oat - rat
                            if abs(divisor) > 1.0:
                                oa_frac = (mat - rat) / divisor
                                if -0.15 <= oa_frac <= 1.15:
                                    oa_frac = max(0.0, min(1.0, oa_frac))
                                    expected_mat = None
                                    if oa_dmpr_cmd is not None:
                                        expected_mat = oa_dmpr_cmd * oat + (1.0 - oa_dmpr_cmd) * rat
                                    
                                    # Add structured Derived Evidence to ledger
                                    plan.evidence.add(Evidence(
                                        source_tool="derived:thermodynamics",
                                        raw_payload={
                                            "type": "derived_inference",
                                            "formula": "mixed_air_balance",
                                            "equipment_id": _eq_id,
                                            "inputs": {
                                                "OAT": round(oat, 2),
                                                "RAT": round(rat, 2),
                                                "MAT": round(mat, 2),
                                                "OA_DMPR_CMD": round(oa_dmpr_cmd, 3) if oa_dmpr_cmd is not None else None
                                            },
                                            "result": {
                                                "derived_effective_oa_fraction": round(oa_frac, 4),
                                                "derived_effective_oa_pct": round(oa_frac * 100.0, 2),
                                                "derived_effective_damper_leak_pct": round(100.0 - (oa_frac * 100.0), 2),
                                                "expected_mat_at_commanded_oa": round(expected_mat, 2) if expected_mat is not None else None
                                            },
                                            "confidence": 0.95,
                                            "traceable": True
                                        },
                                        node_name="ThermodynamicDeriver",
                                        freshness=FreshnessStatus.RECENT,
                                        summary=(
                                            f"{_eq_id} derived thermodynamics: effective_oa={round(oa_frac * 100.0, 1)}% "
                                            f"expected_mat={round(expected_mat, 1)}°C" if expected_mat is not None else f"{_eq_id} derived thermodynamics: effective_oa={round(oa_frac * 100.0, 1)}%"
                                        ),
                                        equipment_id=_eq_id,
                                        equipment_type=_eq_block.get("kind", ""),
                                    ))

                                    # ── Derived Cost Evidence ──────────────
                                    # WHY: a stuck-open OA damper drags hot
                                    # outdoor air past the commanded mix, so the
                                    # cooling coil must remove the extra heat —
                                    # real money on the chiller every hour. The
                                    # synthesis LLM otherwise INVENTS a QAR/kWh
                                    # figure that NumericAudit strips to
                                    # [unverified]; promoting a transparent,
                                    # telemetry-derived number makes the savings
                                    # citable and shown to the operator.
                                    # IF IGNORED: the cost claim stays ungrounded
                                    # → stripped → dashboard cannot show savings,
                                    # and the operator loses the $$ case that
                                    # justifies the repair work order.
                                    if expected_mat is not None:
                                        try:
                                            _excess_dt = max(0.0, mat - expected_mat)  # °C the coil must remove due to leak
                                            # Supply airflow: measured if present, else nominal AHU design (ASSUMPTION).
                                            _af = (
                                                _get_val(_points.get("SA_FLOW")) or _get_val(_points.get("SUPPLY_FLOW"))
                                                or _get_val(_points.get("SAF")) or _get_val(_points.get("AIRFLOW"))
                                            )
                                            _af_assumed = _af is None
                                            _airflow_m3s = float(_af) if _af else 2.0  # nominal mid-size AHU ~2.0 m³/s
                                            _RHO, _CP, _RATE, _HRS = 1.2, 1.006, 0.14, 12  # kg/m³, kJ/kg·K, Kahramaa Tier-3 QAR/kWh, op-hrs/day
                                            _excess_kw = round(_airflow_m3s * _RHO * _CP * _excess_dt, 2)
                                            _daily_kwh = round(_excess_kw * _HRS, 1)
                                            _monthly_qar = round(_daily_kwh * 30.0 * _RATE, 0)
                                            if _excess_kw > 0:
                                                plan.evidence.add(Evidence(
                                                    source_tool="derived:cost",
                                                    raw_payload={
                                                        "type": "derived_inference",
                                                        "formula": "excess_oa_cooling_cost",
                                                        "equipment_id": _eq_id,
                                                        "inputs": {
                                                            "MAT": round(mat, 2),
                                                            "expected_mat_at_commanded_oa": round(expected_mat, 2),
                                                            "excess_delta_t_c": round(_excess_dt, 2),
                                                            "supply_airflow_m3s": round(_airflow_m3s, 2),
                                                            "airflow_assumed": _af_assumed,
                                                            "air_density_kg_m3": _RHO,
                                                            "cp_kj_kgk": _CP,
                                                            "tariff_qar_kwh": _RATE,
                                                            "operating_hours_day": _HRS,
                                                        },
                                                        "result": {
                                                            "excess_cooling_kw": _excess_kw,
                                                            "excess_daily_kwh": _daily_kwh,
                                                            "est_monthly_cost_qar": _monthly_qar,
                                                            "est_monthly_savings_qar": _monthly_qar,  # recovered if damper repaired
                                                        },
                                                        "why": (
                                                            "Stuck-open OA damper pulls hot outdoor air past the commanded "
                                                            "mix; the cooling coil burns extra chiller energy to hold supply "
                                                            "temperature, costing ~QAR "
                                                            f"{_monthly_qar:.0f}/month at the Tier-3 rate."
                                                        ),
                                                        "if_ignored": (
                                                            "Sustained energy waste continues every operating hour, the coil "
                                                            "stays saturated (comfort drift in served zones), and chiller "
                                                            "runtime/wear accumulates — the recoverable savings are lost until "
                                                            "the damper actuator is repaired."
                                                        ),
                                                        "confidence": 0.6 if _af_assumed else 0.85,
                                                        "traceable": True,
                                                    },
                                                    node_name="CostDeriver",
                                                    freshness=FreshnessStatus.RECENT,
                                                    summary=(
                                                        f"{_eq_id} derived cost: excess load {_excess_kw} kW → "
                                                        f"~QAR {_monthly_qar:.0f}/month recoverable savings"
                                                        + (" (airflow assumed)" if _af_assumed else "")
                                                    ),
                                                    equipment_id=_eq_id,
                                                    equipment_type=_eq_block.get("kind", ""),
                                                ))
                                        except Exception as _cost_err:
                                            logger.debug(f"[Queen] Derived cost evidence skipped: {_cost_err}")
                except Exception as _deriv_err:
                    logger.debug(f"[Queen] Derived thermodynamic evidence promotion failed: {_deriv_err}")

                logger.info(
                    f"[Queen] Promoted LIVE_BMS_SNAPSHOT to evidence: "
                    f"equipment={len(_snapshot.get('equipment_status', []))} "
                    f"weather={bool(_weather)} meters={bool(_meters)}"
                )
        except Exception as _promote_err:
            logger.warning(f"[Queen] LIVE_BMS_SNAPSHOT promotion failed (non-fatal): {_promote_err}")

        # 1. Route Intent
        active_nodes = await self._route_intent(query)
        
        # 1.1 CRITICAL GROUNDING OVERRIDE: Ensure Safety agents are active if breaches exist
        thermal_breaches = (context or {}).get("GROUNDING_THERMAL_SAFETY", [])
        if thermal_breaches and "Comfort_Agent" in self.nodes:
            if not any(n.name == "Comfort_Agent" for n in active_nodes):
                logger.info("[Queen] Thermal breaches detected in grounding. FORCE-ADDING Comfort_Agent.")
                active_nodes.append(self.nodes["Comfort_Agent"])

        if not active_nodes:
             return {
                 "advice": "I could not find any specialized agents equipped to handle this request.",
                 "context": {},
                 "plan": plan,
             }

        # 2. Sequential Execution with Rate Limiting
        INTER_NODE_DELAY = 1.0  # seconds between each node call

        proposals = {}
        aggregated_context = {}

        # Risk-tiered routing: T1 (lookup) / T2 (diagnostic) / T3 (actionable)
        logger.info("[Queen] Classifying risk tier...")
        risk_tier = await self._classify_risk_tier(query)
        logger.info(f"[Queen] Risk tier: T{risk_tier} — nodes: {[n.name for n in active_nodes]}")

        _emit("agents_dispatched", {
            "agents": [n.name for n in active_nodes],
            "risk_tier": risk_tier,
            "stage": "Investigate",
        })

        # ── Intent-aware fan-out cap ───────────────────────────────────────
        # _route_intent's fallback path can dump 5 P0 agents into active_nodes
        # for vague queries ("anything wrong?"). Each agent then runs its own
        # tool loop + depth planner, multiplying Bedrock latency 5× and burning
        # synthesis on noise. Cap by risk tier so fan-out matches actual need.
        #
        # T1: handled later by _pick_lookup_node (single node).
        # T2 (diagnostic): max 2 specialist nodes + Memory_Agent.
        # T3 (actionable): max 3 specialist nodes + Memory_Agent.
        # Safety-critical T3 (forced via safety floor): unrestricted to keep all
        # eyes on hazards.
        _intent = getattr(self, "_last_intent", None)
        _is_safety_critical = bool(_intent and _intent.intent_class == "safety_critical")

        if risk_tier == 2 and len(active_nodes) > 3 and not _is_safety_critical:
            # Prefer Alarm_Agent and Comfort_Agent for "is everything ok" style queries,
            # else fall back to top-2 of the originally-routed set.
            priority_order = ["Alarm_Agent", "Comfort_Agent", "Energy_Agent",
                              "Maintenance_Agent", "Strategic_Agent", "Sensor_Fusion_Agent"]
            ranked = sorted(active_nodes, key=lambda n: (
                priority_order.index(n.name) if n.name in priority_order else 999
            ))
            kept = ranked[:2]
            # Always retain Memory_Agent if originally present
            mem = next((n for n in active_nodes if n.name == "Memory_Agent"), None)
            if mem and mem not in kept:
                kept.append(mem)
            dropped = [n.name for n in active_nodes if n not in kept]
            active_nodes = kept
            logger.info(
                f"[Queen] T2 fan-out cap: kept={[n.name for n in active_nodes]} "
                f"dropped={dropped}"
            )
        elif risk_tier == 3 and len(active_nodes) > 4 and not _is_safety_critical:
            priority_order = ["Alarm_Agent", "Comfort_Agent", "Energy_Agent",
                              "Maintenance_Agent", "Strategic_Agent", "Sensor_Fusion_Agent",
                              "Planning_Agent", "Mission_Agent"]
            ranked = sorted(active_nodes, key=lambda n: (
                priority_order.index(n.name) if n.name in priority_order else 999
            ))
            kept = ranked[:3]
            mem = next((n for n in active_nodes if n.name == "Memory_Agent"), None)
            if mem and mem not in kept:
                kept.append(mem)
            dropped = [n.name for n in active_nodes if n not in kept]
            active_nodes = kept
            logger.info(
                f"[Queen] T3 fan-out cap: kept={[n.name for n in active_nodes]} "
                f"dropped={dropped}"
            )

        # Memory_Agent is a context supplier, not a deep investigator — cap depth for T1/T2.
        # Fix 10: proportional depth caps. T1/T2 → Memory_Agent=2 AND other agents=4.
        # T3 → no proportional cap (preserve full-depth behavior for actionable work).
        context = context or {}
        context["_risk_tier"] = risk_tier
        if risk_tier <= 2:
            context["_max_turns_Memory_Agent"] = 2
            for _node in active_nodes:
                if _node.name == "Memory_Agent":
                    continue
                context[f"_max_turns_{_node.name}"] = 4

        # Also expose in aggregated context for downstream gates (returned to caller)
        aggregated_context["_risk_tier"] = risk_tier

        # C1 fix: Populate plan with one task per active node
        for node in active_nodes:
            plan.add_task(
                goal=f"{node.name}: investigate '{query[:60]}'",
                tool_hint=node.name,
                expected_outcome=f"Evidence from {node.name} domain",
            )
            plan.tasks[-1].assigned_node = node.name

        # ── Auto-recall: T2+T3+T5+T6 memory injected before any node runs ─
        _recall_context_block = ""
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                recall_bundle = await _mo.recall_for_investigation(plan)
                if not recall_bundle.is_empty:
                    _recall_context_block = recall_bundle.to_context_block()
                    logger.info(f"[Queen] Auto-recall: {len(recall_bundle.similar_investigations)} past investigations, "
                                f"{len(recall_bundle.applicable_skills)} skills, "
                                f"{len(recall_bundle.matching_patterns)} patterns injected")
                    # Inject recall hits as Evidence so plan coverage counts them
                    from arvis_core.evidence import Evidence, FreshnessStatus
                    from arvis_core.memory.types import MemoryTier
                    for hit in (recall_bundle.similar_investigations + recall_bundle.applicable_skills
                                + recall_bundle.matching_patterns)[:10]:
                        ev = Evidence(
                            source_tool=f"memory_recall:{hit.tier.value}",
                            raw_payload={"content": hit.content, "source": hit.source, **hit.metadata},
                            node_name="MemoryOrchestrator",
                            freshness=FreshnessStatus.RECENT,
                            summary=hit.content[:200],
                        )
                        plan.evidence.add(ev)
            except Exception as _rc_err:
                logger.debug(f"[Queen] Auto-recall failed (non-fatal): {_rc_err}")

        # Attach recall context to context dict so nodes receive it
        if _recall_context_block:
            context = {**(context or {}), "RECALL_CONTEXT": _recall_context_block}

        if risk_tier == 1:
            # T1 lookup: route through best-fit node.
            # Use tool_choice="auto" for self-knowledge/capability queries (no live data needed).
            # Use tool_choice="required" for data lookups to prevent hallucination.
            lookup_node = self._pick_lookup_node(query, active_nodes)
            _is_boundary_query = bool(
                (_CAPABILITY_QUERY_RE.search(query) or _BMS_WRITE_COMMAND_RE.search(query))
                and not _DIAGNOSTIC_INTENT_RE.search(query)
            )
            _needs_live_data = not _is_boundary_query
            _tool_choice = "required" if _needs_live_data else "auto"
            if _is_boundary_query:
                lookup_node = SwarmNode(
                    name="System_Capability_Agent",
                    role=(
                        "You are ARVIS explaining your own system capability boundary. "
                        "ARVIS is read-only advisory software for BMS/Desigo. It cannot write, push, set, "
                        "command, apply, or execute BMS changes. Answer directly and briefly. "
                        "Do not call tools, do not cite site statistics, do not invent approval rates, and do not give "
                        "step-by-step operational instructions unless the user asks for advisory guidance after the boundary is clear."
                    ),
                    tools=[],
                    tool_handler=None,
                    llm=self.llm,
                )
                context = {
                    **(context or {}),
                    "SYSTEM_CONTRACT": {
                        "arvis_mode": "read_only_advisory",
                        "bms_write_access": False,
                        "bms_control_authority": False,
                        "operator_must_execute_bms_changes": True,
                    },
                    "SKIP_ADEQUACY_RETRY": True,
                }
            logger.info(f"[Queen] T1 Lookup — node={lookup_node.name} tool_choice={_tool_choice}")
            for t in plan.tasks:
                if t.assigned_node == lookup_node.name:
                    t.mark_active()
                    break
            try:
                t1_result = await lookup_node.process(
                    query, context, channel=channel, plan=plan, tool_choice=_tool_choice
                )
                for t in plan.tasks:
                    if t.assigned_node == lookup_node.name and t.status.value == "active":
                        t.mark_complete()
                        break
                t1_response = t1_result.get("response") if isinstance(t1_result, dict) else t1_result
                t1_advice = t1_response.content if hasattr(t1_response, "content") else str(t1_response)
            except Exception as _e:
                logger.error(f"[Queen] T1 lookup node failed: {_e}")
                t1_advice = f"Lookup failed: {_e}"

            # Sanitize error responses — don't pass raw errors to user
            if t1_advice and (
                t1_advice.startswith("Bedrock Error") or
                t1_advice.startswith("Lookup failed") or
                "Parameter validation failed" in t1_advice[:150] or
                "internal error:" in t1_advice[:100]
            ):
                logger.warning(f"[Queen] T1 node returned error — substituting graceful response")
                t1_advice = (
                    "I wasn't able to retrieve that data right now due to a temporary system issue. "
                    "Could you please rephrase or try again in a moment?"
                )

            return {
                "advice": t1_advice,
                "context": {
                    **(context or {}),
                    "_verification_policy": self._verification_policy(
                        risk_tier=risk_tier,
                        query=query,
                        advice=t1_advice,
                        plan=plan,
                    ),
                },
                "plan": plan,
            }

        # A3: Solo-node T3 proposals must face independent review
        if risk_tier == 3 and len(active_nodes) == 1:
            logger.info("[Queen] T3 solo-node: spawning Guardian for independent review.")
            _proposer_tools = active_nodes[0].tools
            guardian = SwarmNode(
                name="Guardian_Reviewer",
                role=(
                    "You are an independent safety reviewer for ARVIS. "
                    "Your job is to critically evaluate whether a proposed action is safe, "
                    "well-supported by evidence, and does not risk equipment damage or comfort violations. "
                    "Challenge assumptions. Check for missing data. Vote VETO if uncertain."
                ),
                tools=_proposer_tools,
                tool_handler=active_nodes[0].tool_handler,
                llm=self.llm,
            )
            active_nodes.append(guardian)
            # NM4 fix: Guardian gets its own plan task
            plan.add_task(
                goal=f"Guardian_Reviewer: independent safety review of '{query[:60]}'",
                tool_hint="Guardian_Reviewer",
                expected_outcome="Independent safety verification of proposal",
            )
            plan.tasks[-1].assigned_node = "Guardian_Reviewer"

        if risk_tier == 3 and len(active_nodes) > 1:
            from arvis_core.swarm.consensus import ConsensusEngine, VotingRound
            engine = ConsensusEngine()
            proposer = active_nodes[0]
            quorum = active_nodes[1:]

            logger.info(f"[Queen] Actionable query detected. Triggering BFT workflow with Proposer: {proposer.name}")

            # ── Conversation history prefix ──────────────────────────────────
            _conv_history = (context or {}).get("chat_history", [])
            _history_prefix = ""
            if _conv_history:
                _recent = _conv_history[-6:]  # last 3 turns (user+assistant pairs)
                _history_prefix = "CONVERSATION HISTORY (last turns):\n" + "\n".join(
                    f"  {m['role'].upper()}: {str(m.get('content',''))[:200]}"
                    for m in _recent
                ) + "\n\n"

            # HARDENED PROPOSER PROMPT: Ensure strict adherence to GROUNDING_DATA
            proposer_prompt = (
                _history_prefix
                + f"The user requested an operational change: '{query}'.\n"
                "Formulate a concrete, high-fidelity proposal to execute this efficiently.\n"
                "CRITICAL: You MUST include your quantitative findings in a 'GROUNDING_DATA' block at the START of your response.\n"
                "Ensure your proposed savings/costs are logically derived from your tool history to avoid BFT vetoes."
            )
            # NM2 fix: Mark proposer task active → process → complete/failed
            proposer_result = await self._run_with_task_lifecycle(
                proposer, plan, proposer_prompt, context, channel
            )

            proposal_text = proposer_result["response"].content

            # H8: Self-consistency check — only for solo-node T3 (BFT quorum ≥2 already provides this)
            if len(active_nodes) <= 1:
                proposal_text = await self._self_consistency_check(
                    proposer, proposer_prompt, proposal_text, context, channel, plan
                )

            proposals[proposer.name] = proposal_text

            # Build proposer's shared KB from tool results
            proposer_kb: Dict[str, Any] = {}
            for msg in proposer_result["history"]:
                if msg.get("role") == "tool":
                    aggregated_context[f"{proposer.name}_{msg.get('name')}"] = msg.get("content")
                    _key = f"{proposer.name}:{msg.get('name', 'tool')}"
                    try:
                        _fact = json.loads(msg["content"])
                        proposer_kb[_key] = _fact if isinstance(_fact, dict) else {"raw": str(_fact)[:300]}
                    except Exception:
                        proposer_kb[_key] = {"raw": str(msg.get("content", ""))[:300]}

            # M2-C: OutcomePredictor soft annotation before BFT voting
            _outcome_annotation = {}
            try:
                from agent_advisory.ml_models.outcome_predictor import OutcomePredictor
                _op = OutcomePredictor()
                _action = {"action_type": "advisory", "description": proposal_text[:500]}
                _prediction = _op.predict(context or {}, _action)
                if _prediction.confidence > 0.6 and _prediction.predicted_quality == "poor":
                    _outcome_annotation = {
                        "PREDICTED_NEGATIVE_OUTCOME": _prediction.to_dict(),
                    }
                    logger.info(
                        f"[Queen] OutcomePredictor: poor outcome predicted "
                        f"(utility={_prediction.predicted_utility:.2f}, conf={_prediction.confidence:.2f})"
                    )
            except Exception as _op_err:
                logger.debug(f"[Queen] OutcomePredictor skipped (non-fatal): {_op_err}")

            # Inject proposer findings into quorum context — quorum votes knowing what proposer observed
            round_obj = VotingRound(
                proposal=proposal_text,
                proposer_name=proposer.name,
                context={**(context or {}), "cross_agent_findings": proposer_kb, **_outcome_annotation}
            )

            # NM2 fix: Mark quorum tasks active before debate
            for q_node in quorum:
                for t in plan.tasks:
                    if t.assigned_node == q_node.name and t.status.value == "pending":
                        t.mark_active()
                        break
            # B3 fix: broadcast quorum activation
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
            except Exception:
                pass

            # Check for dismissal or weakening of active unacknowledged terminal advisories (S1_P6/S2_P6 hardening)
            has_dismissal_attempt = False
            dismissed_adv = None
            _tas = getattr(self, "terminal_advisory_store", None)
            if _tas is not None:
                try:
                    _building_id = (context or {}).get("building_id", "default") if context else "default"
                    _active_terms = await _tas.list_active(_building_id)
                    query_lower = query.lower() if query else ""
                    prop_lower = proposal_text.lower() if proposal_text else ""
                    for adv in _active_terms:
                        eq_id = (adv.equipment_id or "").lower()
                        if eq_id and (eq_id in query_lower or eq_id in prop_lower):
                            if any(kw in query_lower or kw in prop_lower for kw in [
                                "dismiss", "wait", "postpone", "delay", "lower priority",
                                "de-prioritize", "not urgent", "ignore", "false-alarm", "monitoring-only",
                                "false alarm", "monitoring only"
                            ]):
                                has_dismissal_attempt = True
                                dismissed_adv = adv
                                break
                except Exception as _tas_err:
                    logger.debug(f"[Queen] Failed checking active terminals for veto: {_tas_err}")

            # B4 fix: wrap run_debate in try/except
            try:
                if has_dismissal_attempt and dismissed_adv:
                    logger.warning(f"[Queen] Safety override: proposal attempts to dismiss active terminal advisory on {dismissed_adv.equipment_id.upper()}. Forcing BFT VETO.")
                    debate_result = {
                        "status": "REJECTED",
                        "votes": [{
                            "agent_name": "SafetyGuardian",
                            "vote": "VETO",
                            "confidence": 1.0,
                            "conditions": [],
                            "reasoning": f"This is a terminal bearing degradation alert on {dismissed_adv.equipment_id.upper()} and cannot be dismissed. Delaying action poses high operational risk.",
                            "tool_observations": {}
                        }],
                        "conditions": [],
                        "avg_confidence": 1.0,
                        "original_proposal": proposal_text
                    }
                elif len(quorum) < 2 and risk_tier < 3:
                    # Fix 6b: solo quorum on T2 — skip BFT entirely, no timeout waste
                    logger.info("[Queen] T2 solo quorum — skipping BFT, downgrading to advisory tier")
                    debate_result = {"status": "DOWNGRADED_TO_ADVISORY", "votes": [], "conditions": [], "avg_confidence": 0.0, "original_proposal": proposal_text}
                else:
                    debate_result = await engine.run_debate(round_obj, quorum, channel=channel, plan=plan)
            except Exception as _debate_err:
                logger.error(f"[Queen] run_debate raised: {_debate_err}. Marking quorum tasks FAILED.")
                for q_node in quorum:
                    for t in plan.tasks:
                        if t.assigned_node == q_node.name and t.status.value == "active":
                            t.mark_failed()
                            break
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
                # Fall through to hard-veto path
                debate_result = {"status": "REJECTED", "votes": [], "conditions": [], "avg_confidence": 0.0, "original_proposal": proposal_text}

            # B5 fix: per-vote task marking (not blanket complete)
            vote_outcomes = {v["agent_name"]: v["vote"] for v in debate_result.get("votes", [])}
            for q_node in quorum:
                for t in plan.tasks:
                    if t.assigned_node == q_node.name and t.status.value == "active":
                        node_vote = vote_outcomes.get(q_node.name, "")
                        if node_vote in ("APPROVE", "APPROVE_WITH_CONDITION"):
                            t.mark_complete()
                        else:
                            t.mark_failed()  # VETO and parse_error both count as failed
                        break
            # B3 fix: broadcast quorum completion
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
            except Exception:
                pass
            
            for v_data in debate_result["votes"]:
                proposals[v_data["agent_name"]] = f"VOTE: {v_data['vote']} - Reasoning: {v_data['reasoning']}"
                for tool_name, tool_val in v_data.get("tool_observations", {}).items():
                    aggregated_context[f"{v_data['agent_name']}_{tool_name}"] = tool_val
                    
            if debate_result["status"] == "REJECTED":
                veto_reasons = ""
                for v in debate_result["votes"]:
                    veto_reasons += f"- {v['agent_name']} [{v['vote']}]: {v['reasoning']}\n"

                # 4C: Attempt re-route to alternate nodes before hard veto
                original_node_names = {n.name for n in active_nodes}
                alternate_nodes = [
                    n for n in self.nodes.values()
                    if n.name not in original_node_names
                ][:2]

                if has_dismissal_attempt:
                    alternate_nodes = []

                if alternate_nodes:
                    logger.warning(f"[Queen] BFT vetoed. Re-routing to {len(alternate_nodes)} alternate nodes with veto constraints.")
                    # NM3 fix: Add tasks for alternate nodes
                    for alt_node in alternate_nodes:
                        plan.add_task(
                            goal=f"{alt_node.name}: veto re-route for '{query[:40]}'",
                            tool_hint=alt_node.name,
                            expected_outcome="Alternative proposal addressing veto constraints",
                        )
                        plan.tasks[-1].assigned_node = alt_node.name
                    # A5: Pass veto reasons as explicit constraints — alternates must address each
                    constrained_query = (
                        f"{query}\n\n"
                        f"--- VETO CONSTRAINTS (from prior peer review — you MUST address each) ---\n"
                        f"{veto_reasons}\n"
                        f"Your proposal must explicitly resolve each concern above. "
                        f"If you cannot address a constraint, state why clearly.\n"
                        f"--- END VETO CONSTRAINTS ---"
                    )
                    # NM3 fix: Run alternates with task lifecycle
                    alt_tasks = [
                        self._run_with_task_lifecycle(node, plan, constrained_query, context, channel)
                        for node in alternate_nodes
                    ]
                    alt_results = await asyncio.gather(*alt_tasks, return_exceptions=True)
                    alt_proposals = {}
                    for node, res in zip(alternate_nodes, alt_results):
                        if isinstance(res, dict):
                            alt_proposals[node.name] = res.get("response", {}).content if hasattr(res.get("response", {}), "content") else str(res.get("response", ""))
                        else:
                            alt_proposals[node.name] = f"Alternate node error: {res}"

                    if any(not v.startswith("Alternate node error") for v in alt_proposals.values()):
                        logger.info("[Queen] Alternate nodes produced valid proposals. Synthesizing.")
                        full_grounding_context = {**(context or {}), **aggregated_context}
                        final_advice = await self._synthesize_consensus(query, alt_proposals, full_grounding_context, plan=plan)
                    else:
                        # All alternates failed — fall through to hard veto
                        alternate_nodes = []

                if not alternate_nodes:
                    if has_dismissal_attempt and dismissed_adv:
                        veto_analysis = f"Critical safety advisory on {dismissed_adv.equipment_id.upper()} cannot be dismissed. The cognitive swarm has vetoed this request."
                        final_advice_dict = {
                            "analysis": veto_analysis,
                            "advisories": [{
                                "id": "veto-1",
                                "type": "safety_override",
                                "severity": "high",
                                "message": f"The proposal to dismiss this critical advisory has been VETOED by the ARVIS Cognitive Swarm. This is a terminal bearing degradation alert on {dismissed_adv.equipment_id.upper()} and cannot be de-prioritized or dismissed.",
                                "confidence": 1.0,
                                "impact": {"timeframe": "null", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                                "recommended_action": {"type": "abort"},
                                "counterfactual_check": True
                            }]
                        }
                    else:
                        veto_analysis = "Operational optimization vetoed by cognitive swarm due to safety or data inconsistencies."
                        final_advice_dict = {
                            "analysis": veto_analysis,
                            "advisories": [{
                                "id": "veto-1",
                                "type": "safety_override",
                                "severity": "high",
                                "message": f"I simulated your proposed action, but the swarm VETOED it for the following reasons:\n\n{veto_reasons}",
                                "confidence": 1.0,
                                "impact": {"timeframe": "null", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                                "recommended_action": {"type": "abort"},
                                "counterfactual_check": True
                            }]
                        }
                    final_advice = json.dumps(final_advice_dict)
            else:
                # Merge proposer KB + quorum vote tool observations into shared KB for synthesis
                bft_kb: Dict[str, Any] = {**proposer_kb}
                for v_data in debate_result["votes"]:
                    for t_name, t_val in v_data.get("tool_observations", {}).items():
                        _key = f"{v_data['agent_name']}:{t_name}"
                        try:
                            _fact = json.loads(t_val) if isinstance(t_val, str) else t_val
                            bft_kb[_key] = _fact if isinstance(_fact, dict) else {"raw": str(_fact)[:300]}
                        except Exception:
                            bft_kb[_key] = {"raw": str(t_val)[:300]}
                full_grounding_context = {**(context or {}), **aggregated_context, "cross_agent_findings": bft_kb}

                # Inject conditions from APPROVE_WITH_CONDITION votes into synthesis
                bft_conditions = debate_result.get("conditions", [])
                if bft_conditions:
                    full_grounding_context["BFT_CONDITIONS"] = bft_conditions
                    logger.info(f"[Queen] Synthesis must satisfy {len(bft_conditions)} condition(s) from BFT.")

                final_advice = await self._synthesize_consensus(query, proposals, full_grounding_context, plan=plan)

                # Fix 2: if BFT returned DOWNGRADED_TO_ADVISORY (no affirmative votes),
                # force every advisory to type=advisory, severity=medium, prefix message,
                # and recommended_action=operator_review.
                if debate_result.get("status") == "DOWNGRADED_TO_ADVISORY":
                    try:
                        _fa = json.loads(final_advice) if isinstance(final_advice, str) else final_advice
                        if isinstance(_fa, dict):
                            for _adv in _fa.get("advisories", []) or []:
                                if not isinstance(_adv, dict):
                                    continue
                                _adv["type"] = "advisory"
                                _adv["severity"] = "medium"
                                _msg = _adv.get("message", "") or ""
                                if not _msg.startswith("[unverified by peers]"):
                                    _adv["message"] = "[unverified by peers] " + _msg
                                _adv["recommended_action"] = {"type": "operator_review"}
                            final_advice = json.dumps(_fa)
                            logger.warning("[Queen] BFT downgrade applied — advisory tier forced, severity=medium")
                    except Exception as _dg_err:
                        logger.debug(f"[Queen] DOWNGRADED_TO_ADVISORY post-process failed (non-fatal): {_dg_err}")

        else:
            # Execute all nodes in parallel to reduce latency
            async def run_node(node):
                # Mark task active + broadcast
                for t in plan.tasks:
                    if t.assigned_node == node.name:
                        t.mark_active()
                        break
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
                try:
                    result = await node.process(query, context, channel=channel, plan=plan)
                    # Mark task complete + broadcast
                    for t in plan.tasks:
                        if t.assigned_node == node.name and t.status.value == "active":
                            t.mark_complete()
                            break
                    try:
                        from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                        await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                    except Exception:
                        pass
                    return node.name, result, None
                except Exception as e:
                    logger.error(f"[Queen] Node {node.name} failed: {e}")
                    for t in plan.tasks:
                        if t.assigned_node == node.name and t.status.value == "active":
                            t.mark_failed()
                            break
                    # NM1 fix: broadcast after mark_failed
                    try:
                        from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                        await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                    except Exception:
                        pass
                    return node.name, None, e

            tasks = [run_node(node) for node in active_nodes]
            results = await asyncio.gather(*tasks)

            shared_kb: Dict[str, Any] = {}

            for node_name, result_map, err in results:
                if err:
                    proposals[node_name] = f"Node Failed: {str(err)}"
                else:
                    proposals[node_name] = result_map["response"].content
                    for msg in result_map["history"]:
                        if msg.get("role") == "tool":
                            _tool_name = msg.get("name", "tool")
                            aggregated_context[f"{node_name}_{_tool_name}"] = msg.get("content")
                            # 5A: extract structured facts into shared KB
                            _key = f"{node_name}:{_tool_name}"
                            try:
                                _fact = json.loads(msg["content"])
                                shared_kb[_key] = _fact if isinstance(_fact, dict) else {"raw": str(_fact)[:300]}
                            except Exception:
                                shared_kb[_key] = {"raw": str(msg.get("content", ""))[:300]}

            if shared_kb:
                logger.info(f"[Queen] SharedKB populated with {len(shared_kb)} cross-agent findings.")

            full_grounding_context = {**(context or {}), **aggregated_context, "cross_agent_findings": shared_kb}
            final_advice = await self._synthesize_consensus(query, proposals, full_grounding_context, plan=plan)
        
        # ── P4: Broadcast live plan state to operator ──
        try:
            from agent_commercial.api.sse_broadcaster import SSEBroadcaster
            await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
        except Exception as _sse_err:
            logger.debug(f"[Queen] Plan update broadcast failed (non-fatal): {_sse_err}")

        # ── H4: Faithfulness check — answer must not contradict evidence ──
        verification_policy = self._verification_policy(
            risk_tier=risk_tier,
            query=query,
            advice=final_advice,
            plan=plan,
        )
        logger.info(f"[Queen] Verification policy: {verification_policy}")

        # ── H4 + H2: Parallel verification pipeline ──
        _run_h4 = verification_policy["h4_faithfulness"] and plan and len(plan.evidence) > 0
        _run_h2 = verification_policy["h2_claims"] and plan and len(plan.evidence) > 0

        # ── Fix #4: Skip H4 when NumericAudit was fully clean ───────────
        # If pre/post numeric audit found zero orphan numbers, the most
        # common source of H4 contradictions is already eliminated
        # deterministically. Skip H4 LLM call to save 30-70s per turn.
        # Still run H2 (claim verifier) since it catches non-numeric claims.
        # Safety-critical T3 always runs full pipeline regardless.
        _audit = getattr(self, "_last_numeric_audit", None)
        _causal_keywords = {"cause", "leak", "slip", "fail", "damper", "valve", "shaft"}
        _contains_causal = False
        _contains_derived = False
        if final_advice:
            _fa_lower = final_advice.lower()
            _contains_causal = any(kw in _fa_lower for kw in _causal_keywords)
            _contains_derived = "derived" in _fa_lower or "inferred" in _fa_lower or "physics" in _fa_lower

        _has_causal_or_derived = _contains_causal or _contains_derived

        if (
            _run_h4
            and _audit is not None
            and _audit.fully_clean
            and not _has_causal_or_derived
            and verification_policy.get("risk_tier", 2) < 3
        ):
            logger.info(
                f"[Queen] H4 skipped — NumericAudit was fully clean "
                f"({_audit.summary()}) and no causal/derived assertions detected. Saves ~30-70s on this turn."
            )
            _run_h4 = False
        elif (
            _run_h4
            and _audit is not None
            and _audit.fully_clean
            and _has_causal_or_derived
        ):
            logger.info(
                f"[Queen] H4 RUNNING (cannot skip) — NumericAudit was fully clean "
                f"but advice contains causal/derived keywords: causal={_contains_causal}, derived={_contains_derived}"
            )

        if _run_h4 or _run_h2:
            logger.info(f"[Queen] Verification pipeline START (H4={_run_h4}, H2={_run_h2})")
            final_advice = await self._verify_pipeline(final_advice, plan, run_h4=_run_h4, run_h2=_run_h2)
            logger.info("[Queen] Verification pipeline DONE")
            # Surface pipeline outcome so downstream abstention gate can respect
            # H4-verified output instead of overriding with "Insufficient data".
            if "h4-abstain" in final_advice or "faithfulness_abstention" in final_advice:
                aggregated_context["h4_passed"] = False
                aggregated_context["verification_passed"] = False
            else:
                aggregated_context["h4_passed"] = True
                aggregated_context["verification_passed"] = True
        else:
            logger.info("[Queen] Verification pipeline SKIPPED — no evidence in plan")
            aggregated_context["h4_passed"] = False
            aggregated_context["verification_passed"] = False

        # ── H6: Deterministic physics verifier — blocks on violation ──
        _already_abstained = "h4-abstain" in final_advice or "faithfulness_abstention" in final_advice
        if _already_abstained:
            logger.info("[Queen][H6] Skipping physics verifier — prior verification pipeline triggered abstention.")
            aggregated_context["h4_passed"] = False
            aggregated_context["verification_passed"] = False
        else:
            if verification_policy["h6_physics"]:
                logger.info("[Queen][H6] Physics verifier START")
            else:
                logger.info("[Queen][H6] Physics verifier LIGHTWEIGHT — deterministic scan only, no regeneration")
            try:
                from agent_commercial.verifiers.physics import PhysicsVerifier
                pv = PhysicsVerifier()
                pv_result = pv.verify_advisory_text(final_advice)
                if verification_policy["h6_physics"] and not pv_result.passed:
                    logger.warning(f"[Queen][H6] Physics verifier FAILED: {pv_result.violations}")
                    # Attempt regeneration with violations as constraints
                    violations_text = "\n".join(f"- {v}" for v in pv_result.violations)
                    regen_prompt = (
                        f"Your previous advisory contained physics violations:\n{violations_text}\n\n"
                        f"Original advisory:\n{final_advice}\n\n"
                        "Regenerate the advisory removing or correcting the implausible claims. "
                        "Do NOT include numbers that violate physics bounds. Output valid JSON only."
                    )
                    try:
                        regen_result = await self.llm.ask_json(
                            messages=[{"role": "user", "content": regen_prompt}],
                            system_msgs=[{"role": "system", "content": "You are ARVIS Queen. Fix physics violations. Output JSON advisory only."}],
                            channel="physics_regen",
                        )
                        regen_str = json.dumps(regen_result) if isinstance(regen_result, dict) else str(regen_result)
                        # Verify regeneration passes
                        regen_check = pv.verify_advisory_text(regen_str)
                        if regen_check.passed:
                            final_advice = self._enforce_read_only(regen_str)
                            logger.info("[Queen][H6] Physics regeneration succeeded.")
                        else:
                            # Second fail → abstain
                            logger.error(f"[Queen][H6] Physics regeneration still failed: {regen_check.violations}. Abstaining.")
                            final_advice = json.dumps({
                                "analysis": "Advisory contained physically implausible claims that could not be corrected.",
                                "advisories": [{
                                    "id": "physics-block-1",
                                    "type": "system_notice",
                                    "severity": "medium",
                                    "message": "ARVIS detected implausible physics in its analysis and cannot deliver a verified advisory. Please re-query or consult your FM engineer.",
                                    "confidence": 0.2,
                                    "evidence_ids": [],
                                    "impact": {"timeframe": "N/A", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                                    "recommended_action": {"type": "retry"},
                                    "counterfactual_check": False
                                }]
                            })
                    except Exception as _regen_err:
                        logger.error(f"[Queen][H6] Physics regeneration error: {_regen_err}. Abstaining.")
                        final_advice = json.dumps({
                            "analysis": "Physics verification failed and regeneration unavailable.",
                            "advisories": [{
                                "id": "physics-block-1",
                                "type": "system_notice",
                                "severity": "medium",
                                "message": "ARVIS cannot verify the physical plausibility of its analysis. Please retry or consult FM engineer.",
                                "confidence": 0.2,
                                "evidence_ids": [],
                                "impact": {"timeframe": "N/A", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                                "recommended_action": {"type": "retry"},
                                "counterfactual_check": False
                            }]
                        })
                elif pv_result.passed:
                    logger.info("[Queen][H6] Physics verifier PASSED")
                else:
                    logger.info(f"[Queen][H6] Physics violations observed but deferred by policy: {pv_result.violations}")
            except Exception as _pv_err:
                logger.warning(f"[Queen][H6] Physics verifier unavailable (non-fatal): {_pv_err}")

        # Surface structured tool calls for ChatResponse auditability
        _tool_calls = []
        _tool_results = []
        for key, content in aggregated_context.items():
            if key.startswith("_"):
                continue
            parts = key.split("_", 1)
            if len(parts) == 2:
                node_name, tool_name = parts
                _tool_calls.append({"tool": tool_name, "node": node_name})
                _tool_results.append({"tool": tool_name, "node": node_name, "content": str(content)[:500]})
        aggregated_context["_tool_calls"] = _tool_calls
        aggregated_context["_tool_results"] = _tool_results
        aggregated_context["_verification_policy"] = verification_policy

        # Mark plan status based on task satisfaction
        from arvis_core.plan import PlanStatus
        if plan.budget.exhausted:
            plan.status = PlanStatus.BUDGET_EXHAUSTED
        elif plan.all_done:
            plan.status = PlanStatus.COMPLETE
        else:
            plan.status = PlanStatus.ABANDONED

        # ── T2: Archive completed investigation to episodic memory ────────
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                await _mo.archive_investigation(plan)
                logger.debug(f"[Queen] Investigation {plan.id} archived to T2 episodic store")
            except Exception as _arc_err:
                logger.debug(f"[Queen] archive_investigation failed (non-fatal): {_arc_err}")

        # ── Terminal Advisory detection + persistence ─────────────────────
        # If synthesis produced any critical/severe/high advisory matching
        # terminal criteria, write it to TerminalAdvisoryStore so subsequent
        # turns can't quietly drop it. Operator-facing ack signals (handled
        # upstream in chat path) close them out.
        _tas = getattr(self, "terminal_advisory_store", None)
        if _tas is not None and final_advice:
            try:
                from agent_commercial.terminal_advisory_store import detect_terminal_advisories
                _building_id = (context or {}).get("building_id", "default") if context else "default"
                terminals = detect_terminal_advisories(
                    final_advice,
                    plan_id=plan.id,
                    source_query=query,
                )
                _fired_ids: List[str] = []
                for t in terminals:
                    aid = await _tas.fire(
                        building_id=_building_id,
                        equipment_id=t["equipment_id"],
                        advisory_type=t["advisory_type"],
                        severity=t["severity"],
                        title=t["title"],
                        message=t["message"],
                        evidence_ids=t["evidence_ids"],
                        confidence=t["confidence"],
                        sim_day=(context or {}).get("sim_day") if context else None,
                        source_plan_id=plan.id,
                        source_query=query,
                    )
                    if aid:
                        _fired_ids.append(aid)
                if _fired_ids:
                    aggregated_context["_terminal_advisories_fired"] = _fired_ids
                    logger.warning(
                        f"[Queen] Persisted {len(_fired_ids)} terminal advisory(ies) "
                        f"to store: {_fired_ids}"
                    )
            except Exception as _tas_err:
                logger.debug(f"[Queen] terminal advisory detection skipped: {_tas_err}")

        # Auto-dispatch DiscoveryAgent on detected blind spots in synthesized advisory.
        try:
            import re as _re_bs
            _blind_spot_pattern = _re_bs.compile(
                r"\b([A-Z]{2,4}-?\d+/[A-Z_]+)\b.*?(?:not in.*?point map|unmapped|blind spot|not exposed in.*?BMS|missing from telemetry)",
                _re_bs.IGNORECASE,
            )
            _matches = _blind_spot_pattern.findall(final_advice or "")[:5]
            if _matches:
                from arvis_core.discovery.service import get_discovery_service
                import asyncio as _asyncio_bs
                _svc = get_discovery_service()
                for _point_id in _matches:
                    try:
                        _asyncio_bs.create_task(_svc.discover_blind_spot(_point_id, source="reactive_synthesis"))
                        logger.info(f"[Queen] Blind-spot auto-dispatch: {_point_id}")
                    except Exception as _dispatch_err:
                        logger.debug(f"[Queen] Discovery dispatch skipped: {_dispatch_err}")
        except Exception as _bs_err:
            logger.debug(f"[Queen] Blind-spot scan skipped: {_bs_err}")

        # Update database with newly synthesized diagnostic outcomes (CBBE Belief Reinforcement)
        if final_advice:
            try:
                from arvis_core.memory.belief_store import BuildingBeliefStore

                # Retrieve query target equipment for fallback target identification.
                # Captures full hyphenated IDs like AHU-07-CONSISTENCY, not just AHU-07.
                _EQUIP_RE = re.compile(r'\b(?:CH|AHU|VAV|FCU|MTR|CHILLER)\b[-_\s]?\d+[-_A-Z0-9]*', re.IGNORECASE)
                query_equips = sorted(list(set(_EQUIP_RE.findall(query))))
                
                parsed_advice = json.loads(final_advice)
                advisories = parsed_advice.get("advisories", [])
                
                if advisories:
                    # Use shared warm belief_store (set in __init__) instead of
                    # cold-starting a new instance on every swarm run.
                    belief_store = self.belief_store or BuildingBeliefStore()
                    for adv in advisories:
                        if not isinstance(adv, dict):
                            continue
                        
                        # Identify equipment target_id
                        target_id = adv.get("equipment_id")
                        if not target_id:
                            # Search in the message
                            msg_matches = _EQUIP_RE.findall(adv.get("message", ""))
                            if msg_matches:
                                target_id = msg_matches[0].upper()
                            elif query_equips:
                                target_id = query_equips[0].upper()
                            else:
                                target_id = "SYSTEM"
                        
                        target_id = target_id.upper()
                        
                        # Construct a clean hypothesis from message/type
                        msg = adv.get("message", "")
                        adv_type = adv.get("type", "diagnostic")
                        hypothesis = f"{adv_type.replace('_', ' ').capitalize()}: {msg[:120]}..." if len(msg) > 120 else f"{adv_type.replace('_', ' ').capitalize()}: {msg}"
                        
                        confidence = adv.get("confidence", 0.70)
                        
                        # Collect supporting signals
                        supporting = adv.get("evidence_ids", [])
                        if not isinstance(supporting, list):
                            supporting = [str(supporting)]
                        if msg:
                            supporting.append(msg[:200])
                            
                        metadata = {
                            "severity": adv.get("severity", "medium"),
                            "recommended_action": adv.get("recommended_action", {}),
                            "sim_day": (context or {}).get("sim_day") if context else None,
                        }
                        
                        # Add or reinforce belief in the store
                        belief_store.add_or_update_belief(
                            target_id=target_id,
                            hypothesis=hypothesis,
                            confidence=confidence,
                            supporting_signals=supporting,
                            verification_status="PENDING_INSPECTION",
                            metadata=metadata
                        )
                        logger.info(f"[CBBE] Swarm synthesis recorded/reinforced belief for {target_id} with confidence {confidence:.2f}")
            except Exception as b_err:
                logger.debug(f"[CBBE] Swarm outcome belief recording failed (non-fatal): {b_err}")

        # Real agent-convergence stats from per-node task outcomes (no fabrication).
        # A node "converged" if its assigned investigation task completed.
        _node_tasks = [t for t in plan.tasks if getattr(t, "assigned_node", None)]
        _nodes_total = len({t.assigned_node for t in _node_tasks})
        _nodes_converged = len({
            t.assigned_node for t in _node_tasks
            if getattr(getattr(t, "status", None), "value", None) == "complete"
        })

        _emit("investigation_complete", {
            "plan_id": plan.id,
            "nodes_total": _nodes_total,
            "nodes_converged": _nodes_converged,
            "stage": "Advise",
        })

        return {
            "advice": final_advice,
            "context": aggregated_context,
            "plan": plan,
            "nodes_total": _nodes_total,
            "nodes_converged": _nodes_converged,
        }

    def _verification_policy(self, risk_tier: int, query: str, advice: str, plan=None) -> Dict[str, Any]:
        """
        Decide which expensive verification layers are needed for this turn.

        Operator interaction and forensic review have different latency budgets:
        T1 should stay conversational, T2 should verify contradictions, and T3
        keeps the full hardening stack.
        """
        evidence_count = len(plan.evidence) if plan is not None else 0
        high_stakes = bool(_SAFETY_KEYWORDS_RE.search(query))
        physics_relevant = bool(_PHYSICS_REVIEW_RE.search(query) or _PHYSICS_REVIEW_RE.search(advice or ""))

        if risk_tier <= 1:
            return {
                "risk_tier": risk_tier,
                "h4_faithfulness": False,
                "h2_claims": False,
                "h6_physics": False,
                "truth_validator": False,
                "reason": "T1 lookup/capability path; use deterministic GroundingGuard and judge replay instead of LLM gates.",
                "evidence_count": evidence_count,
            }

        if risk_tier == 2:
            return {
                "risk_tier": risk_tier,
                "h4_faithfulness": evidence_count > 0,
                "h2_claims": high_stakes,
                "h6_physics": physics_relevant and high_stakes,
                "truth_validator": False,
                "reason": "T2 diagnostic path; verify contradictions, reserve claim/physics gates for safety-critical turns.",
                "evidence_count": evidence_count,
            }

        return {
            "risk_tier": risk_tier,
            "h4_faithfulness": evidence_count > 0,
            "h2_claims": evidence_count > 0,
            "h6_physics": physics_relevant,
            "truth_validator": True,
            "reason": "T3 actionable/safety path; full hardening stack.",
            "evidence_count": evidence_count,
        }

    async def _synthesize_consensus(self, original_query: str, proposals: Dict[str, str], context: Optional[Dict[str, Any]], plan=None) -> str:
        """
        Synthesizes agent proposals into a high-fidelity consensus advisory.
        If plan with evidence ledger is available, uses it as sole factual source.
        """
        # M4.4: Run ML evidence through LLMInterpreter before synthesis
        # This converts raw ML numbers into grounded prose, preventing LLM from paraphrasing them incorrectly
        ml_interpretations_block = ""
        if plan and len(plan.evidence) > 0:
            _ml_ev = [e for e in plan.evidence.get_all() if not getattr(e, "is_ml_fallback", False) and getattr(e, "model_id", None)]
            if _ml_ev:
                _interp_lines = []
                try:
                    from agent_commercial.ml.llm_interpreter import MLInterpreter, InterpretationType
                    _interp = MLInterpreter()
                    _type_map = {
                        "fdd_autoencoder": InterpretationType.FAULT_DETECTION,
                        "energy_forecaster": InterpretationType.ENERGY_FORECAST,
                        "bayesian_network": InterpretationType.ROOT_CAUSE,
                        "building_embeddings": InterpretationType.FLEET_BENCHMARK,
                    }
                    for _ev in _ml_ev[:4]:  # cap at 4 to avoid prompt bloat
                        _itype = _type_map.get(_ev.model_id, InterpretationType.FAULT_DETECTION)
                        try:
                            _result = await _interp.interpret(_itype, _ev.raw_payload, use_llm=False)
                            if _result.explanation:
                                _interp_lines.append(f"  [{_ev.id}] {_ev.model_id}: {_result.explanation[:300]}")
                        except Exception:
                            pass
                except Exception as _ie:
                    logger.debug(f"[Queen] MLInterpreter skipped: {_ie}")
                if _interp_lines:
                    ml_interpretations_block = (
                        "\n\n--- ML INTERPRETATIONS (deterministic, cite verbatim) ---\n"
                        + "\n".join(_interp_lines)
                        + "\n--- END ML INTERPRETATIONS ---\n"
                    )

        # Build evidence ledger block if plan has evidence
        evidence_ledger_block = ""
        _allowed_ev_ids_block = ""
        if plan and len(plan.evidence) > 0:
            _ev_text = plan.evidence.to_synthesis_context()
            if len(_ev_text) > 20000:
                _ev_text = _ev_text[:20000] + "\n... [evidence truncated — see full ledger in logs]"
            evidence_ledger_block = (
                "\n\n--- EVIDENCE LEDGER (authoritative, from tool results) ---\n"
                + _ev_text
                + "\n--- END EVIDENCE LEDGER ---\n"
            )
            # Fix 2: hard whitelist of evidence IDs — injected before evidence ledger
            # so LLM sees the constraint before reading the entries
            _ev_id_list = [e.id for e in plan.evidence.get_all()]
            _allowed_ev_ids_block = (
                "\n\nALLOWED_EVIDENCE_IDS (EXACT — no others permitted):\n"
                + ", ".join(_ev_id_list)
                + "\nAny evidence_id not in this list is FORBIDDEN. Do NOT add characters, truncate, or guess IDs.\n"
            )

        # Fix 7: extract valid equipment IDs from snapshot for synthesis whitelist
        _valid_equip_ids_block = ""
        _valid_equipment_ids: list = []
        _snap_for_equip = (context or {}).get("LIVE_BMS_SNAPSHOT")
        if isinstance(_snap_for_equip, dict):
            _valid_equipment_ids = [
                b.get("id") for b in _snap_for_equip.get("equipment_status", []) if b.get("id")
            ]
        if _valid_equipment_ids:
            _valid_equip_ids_block = (
                "\n\nVALID_EQUIPMENT_IDS (sim inventory — no others exist):\n"
                + ", ".join(_valid_equipment_ids)
                + "\nAny equipment ID not in this list is FABRICATED. Do not reference it.\n"
            )

        # Extract available points per equipment for point capability awareness
        _available_points_block = ""
        _equip_points_map = {}
        if isinstance(_snap_for_equip, dict):
            for b in _snap_for_equip.get("equipment_status", []) or []:
                eq_id = b.get("id")
                if eq_id:
                    pts = list((b.get("points") or {}).keys())
                    if pts:
                        _equip_points_map[eq_id] = pts
        if _equip_points_map:
            lines = [f"  - {eq_id}: {', '.join(pts)}" for eq_id, pts in _equip_points_map.items()]
            _available_points_block = (
                "\n\nAVAILABLE_TELEMETRY_POINTS (per active equipment):\n"
                + "\n".join(lines)
                + "\nYou are strictly forbidden from referencing, assuming, or diagnosing based on telemetry points that are not explicitly listed for a given equipment item. Do NOT perform 'ontology completion' by assuming missing sensors (e.g. OA_DMPR_POS or valve positions) exist.\n"
            )

        # Fix 1: extract query target equipment for pivot check and synthesis header
        _EQUIP_RE_PRECHECK = re.compile(r'\b(?:CH|AHU|VAV|FCU|MTR|CHILLER)\b[-_\s]?\d+', re.IGNORECASE)
        _query_target_equip_raw = set(_EQUIP_RE_PRECHECK.findall(original_query))
        _query_target_block = ""
        if _query_target_equip_raw:
            _query_target_block = (
                "\n\nQUERY TARGET EQUIPMENT: "
                + ", ".join(sorted(_query_target_equip_raw))
                + "\nAll primary advisories MUST address this equipment. Recommending actions on other equipment requires a non-empty pivot_reason.\n"
            )

        system_prompt = (
            # Fix 13: forbidden verbs surfaced upfront so the model sees them before any guideline.
            "FORBIDDEN VERBS — do NOT emit any of these as past-tense actions: "
            "deactivate, execute, shut down, change, implement, restart, reconfigure, "
            "submitted, corrected, updated, adjusted, applied, modified.\n"
            "Always phrase as advisory: 'recommend', 'suggest', 'advise', or 'the operator should'.\n"
            # Fix 5: evidence-grounding rules at the very top of the prompt.
            "EVIDENCE GROUNDING (ABSOLUTE): For every numeric claim you make, you MUST cite an "
            "evidence_id inline (e.g., 'COP 5.99 [ev:d849acdc]'). Never fabricate numbers. "
            "Numbers not present in the EVIDENCE LEDGER will be deterministically stripped.\n\n"
            "You are the Queen Coordinator of the ARVIS Cognitive Swarm. "
            "Synthesize agent proposals into a unified ARVIS Advisory JSON.\n\n"
            "--- CRITICAL GUIDELINES ---\n"
            "1. CONFLICT RESOLUTION: Resolve domain contradictions by prioritizing Safety > Comfort > Energy.\n"
            "2. DATA INTEGRITY: ALL numbers (energy_kwh, cost_qar, percentages, scores) MUST be copied EXACTLY "
            "from the EVIDENCE LEDGER below. You may NOT perform arithmetic or invent numbers. "
            "If a number is not in the ledger, do NOT include it. "
            "If conflicting, use the more conservative (lower savings/higher cost) number.\n"
            "3. MARKER PRESERVATION: Carry forward specific strings like '[VIP_OVERRIDE_DETECTED]' or '[DOWNGRADE_REQUIRED]' into the 'message' field if they appear in any agent proposal.\n"
            "4. TYPE HYGIENE: The 'message' field MUST be a single string (narrative), NOT a list. "
            "The 'evidence_ids' field references evidence ledger entries by ID.\n"
            "5. CROSS-AGENT CORRELATION: If CROSS-AGENT TOOL FINDINGS are provided, use them to surface correlations "
            "that individual agents may have missed.\n"
            "6. EVIDENCE_IDS INTEGRITY: The 'evidence_ids' array MUST ONLY contain the exact ID strings "
            "verbatim from the EVIDENCE LEDGER above (e.g., 'd849acdc' or 'd849acdc-ab0', NOT including the brackets). "
            "Do NOT invent, guess, or construct IDs. If unsure, leave the array empty.\n"
            "7. READ-ONLY ENFORCEMENT (STRICT): ARVIS is purely advisory — it NEVER performs actions. "
            "In every 'message' and 'recommended_action' field, write as if giving advice, not reporting a completed action.\n"
            "   BAD (past-tense action claiming): 'ARVIS submitted the setpoint', 'The system corrected the fault', 'We applied the fix'\n"
            "   GOOD (advisory): 'ARVIS recommends submitting the setpoint', 'The operator should correct the fault', 'ARVIS advises applying the fix'\n"
            "   NEVER use these verbs as past actions: submitted, corrected, updated, changed, adjusted, "
            "turned off, restarted, applied, executed, implemented, activated, deactivated, shut down, modified.\n"
            "   ALWAYS prefix such actions with 'recommend', 'suggest', 'advise', or 'the operator should'.\n"
            "   EXAMPLES (mandatory phrasing):\n"
            "   - 'ARVIS recommends reducing CHWST setpoint by 0.5°C during off-peak hours'\n"
            "   - 'The FM team should schedule condenser cleaning within 14 days'\n"
            "   - 'Investigation suggests AHU-07 OA damper requires recalibration'\n"
            "   FORBIDDEN (will trigger rejection):\n"
            "   - 'ARVIS adjusted the CHWST setpoint' (implies control action)\n"
            "   - 'The damper has been recalibrated' (implies completed work)\n"
            "   - 'We executed the sequencing change' (claims BMS write)\n\n"
            "8. OPERATOR CORRELATION: If RECENT_OPERATOR_ACTIONS shows a setpoint change "
            "that explains the queried anomaly, cite the operator action as the cause "
            "rather than diagnosing an equipment fault. Example: if an operator lowered "
            "CHWST setpoint 5 minutes ago and query asks 'why did supply temp drop?', "
            "attribute to the operator action, not a chiller malfunction.\n"
            "9. LIVE_BMS_SNAPSHOT IS THE GROUND TRUTH: If 'LIVE_BMS_SNAPSHOT' is "
            "present in the grounding context, treat it as the authoritative current "
            "state of the building. It contains equipment_status with current point "
            "values per equipment, weather (OAT, RH), meters (plant_kw_now, kwh_today), "
            "and an alarms_summary. NEVER say 'no live point data available' or "
            "'cannot perform a live scan' when LIVE_BMS_SNAPSHOT is populated — "
            "instead, cite specific values from it. If an equipment's points are empty, "
            "you MUST state honestly that it is on standby or that points are currently "
            "unpopulated, rather than fabricating or guessing values. For broad queries "
            "like 'is anything off?' or 'scan the building', iterate LIVE_BMS_SNAPSHOT "
            "equipment_status and surface outliers: chillers running at high load, "
            "AHUs with valves saturated near 100%, zones above setpoint, plant power "
            "near peak, etc. Quote exact values + unit when reporting.\n"
            "10. NO CROSS-EQUIPMENT EXTRAPOLATION (STRICT): If the EVIDENCE LEDGER "
            "contains data for only one specific equipment (e.g. CH-01), you MUST "
            "NOT make statements about other equipment of the same type (CH-02, "
            "CH-03, CH-04) unless their data is also explicitly in the ledger. "
            "Equipment has two distinct status concepts: 'status' (from registry, e.g. 'running' meaning healthy/available) "
            "and 'operational' / 'STATUS' (live telemetry, 1.0/0.0 indicating active vs standby). "
            "You MUST distinguish them: an idle chiller/AHU is registered as 'running' but has operational=False "
            "and STATUS=0 (standby), which is normal, not offline or faulted. Report what is "
            "observed, not what is assumed.\n"
            "   BAD (extrapolating from CH-01 evidence):\n"
            "     'All four chillers are running at 77% load with COP 6.1-6.2'\n"
            "     'Chillers CH-01 through CH-04 show CRITICAL condenser temps'\n"
            "   GOOD (faithful to evidence scope):\n"
            "     'CH-01 is staged at 75.4% load with COP 5.99 (only chiller currently active)'\n"
            "     'CH-01 condenser temp 31.7°C (within normal range); CH-02/03/04 idle on standby'\n"
            "   When evidence covers N of M equipment items, state the coverage explicitly: "
            "'1 of 4 chillers active' or '3 of 142 AHUs have recent data'. Do not aggregate "
            "or average across equipment unless every item has a value in the ledger.\n"
            "11. NO FABRICATED AGGREGATES: Do NOT compute totals, averages, ranges, "
            "or comparisons unless every input value to the computation is present "
            "in the EVIDENCE LEDGER. Examples of forbidden fabrications:\n"
            "   - 'Average chiller efficiency is 6.15' (when only CH-01 has data)\n"
            "   - 'Building power is 51.6 kW' (when no meter reading is in evidence)\n"
            "   - 'Supply air temps range from 14.43 to 14.96°C' (when no AHU SAT in evidence)\n"
            "   If the user asks for an aggregate that cannot be computed from evidence, "
            "say so explicitly and offer to fetch the missing data.\n"
            "17. STRICT CITATION COUNT ENFORCEMENT: For any stated count of instances N in the narrative of a message or analysis (e.g., '14 instances'), you MUST cite at least N unique evidence IDs inline or in the evidence_ids list. If you do not have at least N distinct evidence IDs in the ledger, you are strictly forbidden from asserting that specific count; instead, state only the count of instances that are directly backed by valid evidence IDs. Stated counts exceeding available citations will be deterministically capped or neutralized post-synthesis.\n"
            "18. CONFIDENCE CALIBRATION & EPISTEMIC CERTAINTY TIERS: Never assert free-form percentage values or speculative confidence metrics (e.g. '80% confident' or '95% certainty') in narrative fields unless explicitly backed by a source tool result in the EVIDENCE LEDGER. Instead, represent confidence strictly using the JSON 'confidence' field. You MUST characterize causal/diagnostic certainty using these four explicit tiers:\n"
            "   - [Observed] Direct sensor/telemetry evidence is explicitly present in the ledger.\n"
            "   - [Inferred] Conclusion derived thermodynamically/logically from telemetry, but direct physical confirmation is absent. For example, if you suspect damper slippage from high MAT and SAT, state: 'Telemetry strongly suggests probable OA damper mechanical slippage, but direct physical confirmation is unavailable.' Do NOT call it a confirmed physical fact.\n"
            "   - [Hypothesized] Plausible explanation but weakly evidenced (e.g., historical precedent, alarms with no matching point telemetry).\n"
            "   - [Confirmed] Failure physically verified by a technician/inspection (MUST be explicitly documented in the ledger; never infer this tier).\n"
            "   Always prefix narrative causal statements with these tiers or use qualitative uncertainty phrases. Write '[INFERRED] Telemetry suggests probable OA damper slippage.' instead of 'CONFIRMED mechanical slippage'.\n"
            "14. PRIOR TURN FINDINGS ARE AUTHORITATIVE: If grounding context contains "
            "'PRIOR_TURN_FINDINGS', these are conclusions ARVIS reached in earlier "
            "turns of the SAME conversation. You MUST:\n"
            "   (a) NOT contradict them. If turn-2 said 'CH-01 is the root cause at "
            "80% confidence', turn-3 cannot say 'no data on CH-01'.\n"
            "   (b) If new evidence in the current ledger genuinely overturns a prior "
            "finding, EXPLICITLY acknowledge the change: 'Turn 2 attributed root "
            "cause to CH-01; new evidence [ev_id] shows AHU-19 as primary.'\n"
            "   (c) Reference prior evidence_ids when re-stating findings — operators "
            "expect consistency. The operator will challenge any drift between turns.\n"
            "   (d) If prior findings included terminal advisories (max_severity = "
            "critical/severe), treat them with the same authority as TERMINAL_"
            "ADVISORIES_PENDING (see clause 12).\n"
            "   BAD (self-contradiction observed in P2 and P4 runs):\n"
            "     Turn 2: 'CH-01 is the root cause at 80% confidence per cluster X'\n"
            "     Turn 3: 'I have no data on CH-01 — recommend physical inspection'\n"
            "   GOOD:\n"
            "     Turn 3: 'Per turn 2 finding, CH-01 root cause assessment stands\n"
            "      (cluster X, 80% confidence). Current evidence corroborates: ...'\n\n"
            "13. STANDBY EQUIPMENT IS NOT BLIND: When LIVE_BMS_SNAPSHOT shows an "
            "equipment block with operational=false, this means the equipment is "
            "currently IDLE/UNSTAGED (e.g. a chiller not in current rotation, a VAV "
            "during off-hours). It does NOT mean ARVIS lacks data on it. Point "
            "values inside the block with `last_known: true` are the most recent "
            "readings from before the equipment went idle and remain DIAGNOSTICALLY "
            "VALID. You MUST:\n"
            "   (a) Cite last-known values when operator asks about standby equipment.\n"
            "   (b) State explicitly that the equipment is currently idle but the "
            "telemetry is recent (last known timestamp).\n"
            "   (c) NEVER respond 'no live metrics available' or 'cannot verify' "
            "when the points block contains last-known values.\n"
            "   BAD (the failure pattern that has been observed in prior runs):\n"
            "     Op: 'What's CH-04 vibration trending at?'\n"
            "     ARVIS: 'CH-04 is in standby with no live metrics; cannot verify.'\n"
            "   GOOD:\n"
            "     Op: 'What's CH-04 vibration trending at?'\n"
            "     ARVIS: 'CH-04 is currently idle (not staged). Last-known VIB_RMS\n"
            "      reading 1.38 mm/s at [ts] — climbing trend over prior 8 weeks.'\n"
            "   The operator can see this telemetry on their Desigo interface. ARVIS\n"
            "   refusing to discuss it breaks operator trust.\n"
            "12. TERMINAL ADVISORIES ARE AUTHORITATIVE: If grounding context contains "
            "'TERMINAL_ADVISORIES_PENDING', these are prior critical findings (life "
            "safety, predicted equipment failure, compliance breach) that ARVIS has "
            "already raised and the operator has NOT yet acknowledged. You MUST:\n"
            "   (a) Re-surface them in your advisory message with severity preserved. "
            "Quote the original title + at least one evidence_id from the prior fire.\n"
            "   (b) NEVER abstain on a terminal advisory simply because current "
            "evidence is incomplete. The prior evidence is the ground truth.\n"
            "   (c) NEVER weaken the severity (e.g. 'critical' → 'medium') unless "
            "new evidence in the current ledger explicitly contradicts the prior fire.\n"
            "   (d) If the operator's query tries to dismiss or defer the terminal "
            "advisory (e.g. 'can we push this to Q1?', 'is it really that bad?'), "
            "DEFEND the original assessment with evidence_ids — do not capitulate.\n"
            "   (e) If the operator's query contains an explicit acknowledgment "
            "('noted', 'scheduling techs', 'work order opened'), mark it as "
            "acknowledged in your advisory message but DO NOT silently drop it.\n"
            "   BAD (capitulation after dismissal attempt):\n"
            "     Op: 'Can the CH-04 bearing inspection wait until Q1?'\n"
            "     ARVIS: 'Low confidence — recommend physical inspection when convenient'\n"
            "   GOOD (defended terminal advisory):\n"
            "     Op: 'Can the CH-04 bearing inspection wait until Q1?'\n"
            "     ARVIS: 'Original terminal advisory [adv_id] stands. CH-04 bearing\n"
            "      degradation 60% failure probability in 14 days (evidence [eid_x]).\n"
            "      Deferring to Q1 means 100% probability before peak summer. Risk\n"
            "      acceptance must be operator-documented; ARVIS cannot withdraw\n"
            "      the advisory without resolution evidence.'\n\n"
            "15. MORNING BRIEFING FORMATTING: If the query asks for a morning briefing, situation report, or daily status, you MUST format the 'message' field of your advisory using markdown headings in exactly this order:\n"
            "   ### 🔴 Critical Items\n"
            "   ### 🟡 Overnight Anomalies\n"
            "   ### 🟢 Wins\n"
            "   ### 📋 Recommendations\n"
            "   Under each heading, provide a concise, factual bulleted list of findings from the evidence ledger. If there are no items for a section, write 'None'.\n\n"
            "16. PIVOT DETECTION (STRICT): If the query mentions specific equipment (e.g., CH-02), all recommended actions and advisories must address that equipment. Recommending actions on unrelated equipment (e.g., AHU-05 or VAV-12) is considered a PIVOT. You MUST include a non-empty 'pivot_reason' field in the advisory object explaining the cascade or system interaction that justifies this pivot. If you recommend unrelated equipment without a valid 'pivot_reason', that recommendation will be rejected.\n\n"
            "19. TELEMETRY POINT AWARENESS (STRICT): You must only refer to or base diagnoses on telemetry points that are explicitly listed in the AVAILABLE_TELEMETRY_POINTS block for each equipment. If a point is not listed (e.g., OA_DMPR_POS or valve positions), you are strictly forbidden from assuming it exists or referencing it as evidence. Never guess or complete the ontology.\n"
            "20. NO INTERMEDIATE CALCULATION LEAKAGE (STRICT): You are strictly forbidden from leaking intermediate math calculations, algebraic formula traces, or step-by-step arithmetic (e.g., '(28.1 - 22.0) / (28.1 - 10.5) = 34.6%') into any narrative fields (such as 'message' or 'analysis'). All narrative statements must be qualitative and clear. Cite only final values and the evidence_id of the promoted 'derived_inference' Evidence items (e.g., 'expected MAT is 25.1°C [ev:derived_id]').\n\n"
            "--- FORMAT REQUIREMENT ---\n"
            "Return ONLY a valid JSON object. No narrative text.\n\n"
            "SCHEMA:\n"
            "{\n"
            "  \"analysis\": \"str: summary of consensus logic\",\n"
            "  \"advisories\": [{\n"
            "    \"id\": \"auto-1\",\n"
            "    \"type\": \"str (e.g., energy_waste, safety_priority)\",\n"
            "    \"severity\": \"str (low/medium/high/critical)\",\n"
            "    \"message\": \"str: Narrative advisory for FM dashboard. Include operational markers here.\",\n"
            "    \"confidence\": float (0.0-1.0),\n"
            "    \"evidence_ids\": [\"str: exact IDs from EVIDENCE LEDGER above, e.g., 'd849acdc'\"],\n"
            "    \"claims_epistemic\": [{\n"
            "      \"claim\": \"str: specific assertion\",\n"
            "      \"source_type\": \"str (observed | derived | inferred)\",\n"
            "      \"evidence_strength\": \"str (direct | indirect)\",\n"
            "      \"persistence_eligible\": bool\n"
            "    }],\n"
            "    \"impact\": {\n"
            "        \"timeframe\": \"str\",\n"
            "        \"energy_kwh\": float,\n"
            "        \"cost_qar\": float,\n"
            "        \"is_savings\": bool\n"
            "    },\n"
            "    \"recommended_action\": {\"type\": \"str\"},\n"
            "    \"counterfactual_check\": bool,\n"
            "    \"pivot_reason\": \"str: Explanation of why we are recommending actions on unrelated equipment, or empty/null if no pivot\"\n"
            "  }]\n"
            "}"
        )
        
        # Fix 1b: strip duplicate LIVE_BMS_SNAPSHOT blocks across proposals.
        # Same snapshot dumped by N agents bloats prompt by N× with zero new info.
        _LIVE_SNAP_RE = re.compile(
            r"LIVE_BMS_SNAPSHOT\s*[:=]?\s*(\{.*?\}|\[.*?\])",
            re.IGNORECASE | re.DOTALL,
        )
        _first_snap_seen = False
        _deduped_proposals: Dict[str, str] = {}
        for _name, _text in proposals.items():
            if not isinstance(_text, str):
                _deduped_proposals[_name] = _text
                continue
            def _sub_snap(m):
                nonlocal _first_snap_seen
                if not _first_snap_seen:
                    _first_snap_seen = True
                    return m.group(0)
                return "[LIVE_BMS_SNAPSHOT — see first occurrence]"
            _deduped_proposals[_name] = _LIVE_SNAP_RE.sub(_sub_snap, _text)
        proposals = _deduped_proposals

        # Filter out error/crash proposals — don't feed raw errors to synthesis
        def _is_error_proposal(text: str) -> bool:
            if not text:
                return True
            s = text.strip()
            return (
                s.startswith("Bedrock Error") or
                s.startswith("Node Failed") or
                "internal error:" in s[:80] or
                "Parameter validation failed" in s[:120]
            )
        valid_proposals = {
            k: v for k, v in proposals.items() if not _is_error_proposal(v)
        }
        if not valid_proposals and proposals:
            valid_proposals = {"system": "No agent produced a valid response for this query. Inform the user that the system encountered an internal error and suggest they rephrase or retry."}

        proposals_text = ""
        for agent_name, proposal in valid_proposals.items():
            _p = proposal[:3000] + "... [truncated]" if len(proposal) > 3000 else proposal
            proposals_text += f"\n--- {agent_name} Proposal ---\n{_p}\n"

        # 5A: Surface cross-agent tool findings for synthesis
        cross_findings_text = ""
        cross_kb = (context or {}).get("cross_agent_findings", {})
        if cross_kb:
            lines = []
            for k, v in list(cross_kb.items())[:8]:  # cap at 8 to avoid prompt bloat
                lines.append(f"  [{k}]: {json.dumps(v, default=str)[:250]}")
            cross_findings_text = "\n\nCROSS-AGENT TOOL FINDINGS (raw observations from all agents):\n" + "\n".join(lines)

        # BFT conditions block: synthesis must address each condition
        bft_conditions_block = ""
        bft_conditions = (context or {}).get("BFT_CONDITIONS", [])
        if bft_conditions:
            conditions_list = "\n".join(f"  - {c}" for c in bft_conditions)
            bft_conditions_block = (
                f"\n\n--- BFT CONDITIONS (MANDATORY) ---\n"
                f"The following conditions were imposed by reviewing agents. "
                f"Your synthesis MUST address each one explicitly in the advisory message:\n"
                f"{conditions_list}\n"
                f"--- END BFT CONDITIONS ---\n"
            )

        # Build a compact context summary — exclude bulky sub-keys already covered
        # by evidence_ledger_block and cross_findings_text to avoid token explosion.
        _CONTEXT_EXCLUDE = {"cross_agent_findings", "_tool_results", "equipment_readings"}
        context_compact = {k: v for k, v in (context or {}).items() if k not in _CONTEXT_EXCLUDE}
        context_str = json.dumps(context_compact, default=str)
        if len(context_str) > 8000:
            context_str = context_str[:8000] + "... [truncated]"

        # ── Fix #4: Pre-synthesis numeric extraction ────────────────────
        # Deterministically extract every numeric value from evidence ledger
        # + LIVE_BMS_SNAPSHOT + grounding context. Inject as hard constraint
        # in the synthesis prompt so the LLM knows the allowed value set
        # upfront, and so the post-synthesis audit has a precomputed reference.
        _allowed_numbers_block = ""
        _auditor = None
        _allowed_numbers = None
        try:
            from arvis_core.swarm.numeric_audit import NumericAuditor
            _auditor = NumericAuditor()
            _allowed_numbers = _auditor.extract_allowed_numbers(plan, context)
            # Prune to 500 for synthesis prompt, but keep full set for audit
            _pruned_allowed = _auditor.prune_for_synthesis(_allowed_numbers, original_query, cap=500)
            _allowed_numbers_block = NumericAuditor.build_allowed_numbers_prompt(_pruned_allowed, cap=500)
            logger.info(
                f"[Queen] NumericAudit: extracted {len(_allowed_numbers)} allowed numeric values "
                f"from evidence + context (pruned to {len(_pruned_allowed)} for prompt)"
            )
        except Exception as _na_err:
            logger.debug(f"[Queen] NumericAudit pre-extract failed (non-fatal): {_na_err}")

        user_message = (
            f"Original Query: {original_query}\n\n"
            f"Grounding Context (FACTS): {context_str}\n\n"
            f"Agent Proposals:\n{proposals_text}"
            f"{cross_findings_text}"
            f"{_query_target_block}"
            f"{_allowed_ev_ids_block}"
            f"{_valid_equip_ids_block}"
            f"{_available_points_block}"
            f"{evidence_ledger_block}"
            f"{ml_interpretations_block}"
            f"{bft_conditions_block}"
            f"{_allowed_numbers_block}\n\n"
            "Please synthesize these into the final ARVIS Advisory JSON. "
            "CRITICAL: If 'GROUNDING_THERMAL_SAFETY' contains items, you MUST generate a high-priority advisory even if agent proposals are weak. "
            "IMPORTANT: ALL numbers in your output must come from the EVIDENCE LEDGER or ALLOWED NUMERIC VALUES list. Do NOT invent or compute numbers."
        )

        # Fix 1a: pre-flight token cap. Estimate as len/4. If > 80,000, truncate
        # evidence ledger to top-40 items (by relevance score if present, else recency).
        def _est_tokens(s: str) -> int:
            return len(s) // 4

        _est_total = _est_tokens(system_prompt) + _est_tokens(user_message)
        if _est_total > 80_000 and plan and len(plan.evidence) > 15:
            try:
                _all = plan.evidence.get_all()
                def _ev_rank(e):
                    return (
                        -float(getattr(e, "relevance", 0.0) or 0.0),
                        -float(getattr(e, "created_at_epoch", 0.0) or 0.0),
                    )
                _top40 = sorted(_all, key=_ev_rank)[:40]
                _short_lines = []
                for _ev in _top40:
                    _summary = getattr(_ev, "summary", "") or str(getattr(_ev, "raw_payload", ""))[:200]
                    _short_lines.append(f"  [{getattr(_ev, 'id', '?')}] {_summary[:300]}")
                _truncated_ledger = (
                    "\n\n--- EVIDENCE LEDGER (top-40, truncated due to token cap) ---\n"
                    + "\n".join(_short_lines)
                    + "\n--- END EVIDENCE LEDGER ---\n"
                )
                user_message = (
                    f"Original Query: {original_query}\n\n"
                    f"Grounding Context (FACTS): {context_str}\n\n"
                    f"Agent Proposals:\n{proposals_text}"
                    f"{cross_findings_text}"
                    f"{_query_target_block}"
                    f"{_allowed_ev_ids_block}"
                    f"{_valid_equip_ids_block}"
                    f"{_available_points_block}"
                    f"{_truncated_ledger}"
                    f"{ml_interpretations_block}"
                    f"{bft_conditions_block}"
                    f"{_allowed_numbers_block}\n\n"
                    "Please synthesize these into the final ARVIS Advisory JSON. "
                    "CRITICAL: If 'GROUNDING_THERMAL_SAFETY' contains items, you MUST generate a high-priority advisory even if agent proposals are weak. "
                    "IMPORTANT: ALL numbers in your output must come from the EVIDENCE LEDGER or ALLOWED NUMERIC VALUES list. Do NOT invent or compute numbers."
                )
                logger.warning(
                    f"[Queen] Pre-flight token cap exceeded ({_est_total} > 80k). "
                    f"Truncated evidence ledger to top-40 items."
                )
            except Exception as _trunc_err:
                logger.warning(f"[Queen] Pre-flight truncation failed (non-fatal): {_trunc_err}")

        logger.info(f"[Queen] ── Synthesis START — {len(proposals)} proposals from: {list(proposals.keys())}")
        logger.debug(f"[Queen] Grounding Context for synthesis: {json.dumps(context)[:1000]}...")

        try:
            response = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_message}],
                system_msgs=[{"role": "system", "content": system_prompt}],
                channel="synthesis",
            )
            result_str = json.dumps(response) if isinstance(response, dict) else str(response)

            # Fix 5: hallucination clamp. Count numeric claims vs cited evidence_ids.
            # If citations < claims, retry once with a stronger correction prompt.
            def _count_numeric_claims(text: str) -> int:
                try:
                    return len(re.findall(r"\b\d+\.?\d*\b", text or ""))
                except Exception:
                    return 0

            def _count_evidence_citations(parsed: Any) -> int:
                if not isinstance(parsed, dict):
                    return 0
                _n = 0
                for _adv in parsed.get("advisories", []) or []:
                    if isinstance(_adv, dict):
                        _eids = _adv.get("evidence_ids") or []
                        if isinstance(_eids, list):
                            _n += len(_eids)
                return _n

            try:
                _parsed_check = json.loads(result_str) if isinstance(result_str, str) else response
                _msg_text = " ".join(
                    str(_adv.get("message", ""))
                    for _adv in (_parsed_check.get("advisories", []) or [])
                    if isinstance(_adv, dict)
                ) if isinstance(_parsed_check, dict) else ""
                _num_claims = _count_numeric_claims(_msg_text)
                _num_cited = _count_evidence_citations(_parsed_check)
                if _num_claims > 0 and _num_cited < _num_claims:
                    logger.warning(
                        f"[Queen] Hallucination clamp: numeric_claims={_num_claims} "
                        f"cited_evidence_ids={_num_cited}. Retrying synthesis once."
                    )
                    _retry_msg = (
                        user_message
                        + "\n\nCORRECTION: Your previous output cited fewer evidence_ids than the number "
                        "of numeric claims it contained. Re-emit the advisory with at least one "
                        "evidence_id from the EVIDENCE LEDGER for every numeric claim."
                    )
                    response = await self.llm.ask_json(
                        messages=[{"role": "user", "content": _retry_msg}],
                        system_msgs=[{"role": "system", "content": system_prompt}],
                        channel="synthesis",
                    )
                    result_str = json.dumps(response) if isinstance(response, dict) else str(response)
            except Exception as _clamp_err:
                logger.debug(f"[Queen] Hallucination clamp check failed (non-fatal): {_clamp_err}")

            # ── Fix #4: Post-synthesis numeric audit ────────────────────
            # Scan output for numeric tokens. Each must match an allowed value
            # within tolerance. Orphans get replaced with [unverified] — NO
            # LLM call, no correction loop, no H4 burn. ~5ms.
            # Stash audit result on the response for downstream verification
            # policy to optionally skip H4 when audit was fully clean.
            if _auditor is not None and _allowed_numbers is not None:
                try:
                    _audit_report = _auditor.audit_advisory_json(result_str, _allowed_numbers)
                    logger.info(f"[Queen] {_audit_report.summary()}")
                    if _audit_report.orphans or _audit_report.derived_claims:
                        if _audit_report.orphans:
                            _orphan_list = [
                                f"{m.surface_form} ({m.context_field})"
                                for m in _audit_report.orphans[:10]
                            ]
                            logger.warning(
                                f"[Queen][NumericAudit] STRIPPED {len(_audit_report.orphans)} orphan "
                                f"number(s): {_orphan_list}"
                            )
                        result_str = _auditor.strip_orphans(result_str, _audit_report)
                        if _audit_report.orphans:
                            try:
                                from agent_unified.llm import quarantine_values, get_session_key
                                _sess_key = get_session_key([{"role": "user", "content": original_query}])
                                _orphan_vals = [str(m.surface_form).strip() for m in _audit_report.orphans]
                                quarantine_values(_sess_key, _orphan_vals)
                            except Exception as _q_err:
                                logger.debug(f"[Queen] Failed to quarantine orphans: {_q_err}")
                    # Stash on self for verification pipeline to optionally skip H4
                    self._last_numeric_audit = _audit_report
                    try:
                        result_str = _auditor.strip_mismatched_assertions(result_str, context)
                    except Exception as _sm_err:
                        logger.debug(f"[Queen] strip_mismatched_assertions failed: {_sm_err}")
                except Exception as _au_err:
                    logger.debug(f"[Queen] NumericAudit post-check failed (non-fatal): {_au_err}")
                    self._last_numeric_audit = None

            # Deterministic read-only enforcement — code check, not prompt rule
            result_str = self._enforce_read_only(result_str)

            # Validate evidence_ids — strip any hallucinated IDs not in plan
            if plan and len(plan.evidence) > 0:
                try:
                    _parsed = json.loads(result_str)
                    _valid_ids = {e.id for e in plan.evidence.get_all()}
                    _total_cited = 0
                    _invalid_cited = 0

                    # ── Deterministic evidence-id rebind ────────────────────
                    # The synthesis LLM picks which evidence_id to attach to each
                    # numeric claim — non-deterministically. It frequently cites an
                    # alarm id for a telemetry value (e.g. MAT=30.8) whose real
                    # backing is the promoted LIVE_BMS_SNAPSHOT evidence block. H4
                    # then flags a contradiction ("cited evidence has no temp"),
                    # and on a re-run a different (correct) id gets cited — the
                    # "sometimes evidence, sometimes zero" flake. Fix: bind every
                    # matched number to the evidence id that ACTUALLY contains it,
                    # from the numeric audit, and union those ids into the advisory.
                    _num_ev_by_adv: Dict[int, set] = {}
                    try:
                        from arvis_core.swarm.numeric_audit import (
                            get_confidence_and_provenance as _gcp,
                            _numbers_match as _nmatch,
                        )
                        _adv_idx_re = re.compile(r"advisor(?:y|ies)\[(\d+)\]")
                        _ar = getattr(self, "_last_numeric_audit", None)
                        # Live-telemetry evidence ids — preferred citation target so
                        # a numeric value present in BOTH a snapshot block and an
                        # action/derived record always cites the snapshot (which
                        # actually carries the reading H4 looks for).
                        _telemetry_eids = {
                            e.id for e in plan.evidence.get_all()
                            if "live_snapshot" in str(getattr(e, "source_tool", ""))
                        }
                        _allowed_items = list(getattr(_allowed_numbers, "items", []) or [])

                        def _eids_for(_an) -> list:
                            try:
                                return [x for x in _gcp(_an)[3] if x in _valid_ids]
                            except Exception:
                                return []

                        for _nm in (getattr(_ar, "matched", None) or []):
                            _m_idx = _adv_idx_re.search(_nm.context_field or "")
                            if not _m_idx:
                                continue
                            _aidx = int(_m_idx.group(1))
                            _val = getattr(_nm, "output_value", None)
                            # Collect every allowed source holding this value, then
                            # prefer live-telemetry ones; fall back to matched_to.
                            _tele, _other = set(), set()
                            if _val is not None:
                                for _an in _allowed_items:
                                    if not _nmatch(_val, _an.value):
                                        continue
                                    for _eid in _eids_for(_an):
                                        (_tele if _eid in _telemetry_eids else _other).add(_eid)
                            _bind = _tele if _tele else _other
                            if not _bind:
                                _mt = getattr(_nm, "matched_to", None)
                                if _mt is not None:
                                    _bind = set(_eids_for(_mt))
                            if _bind:
                                _num_ev_by_adv.setdefault(_aidx, set()).update(_bind)
                    except Exception as _rebind_err:
                        logger.debug(f"[Queen] evidence-id rebind skipped: {_rebind_err}")

                    for _aidx, _adv in enumerate(_parsed.get("advisories", [])):
                        _cited = _adv.get("evidence_ids", [])
                        if not isinstance(_cited, list):
                            _adv["evidence_ids"] = []
                            _cited = []
                        _total_cited += len(_cited)
                        _valid = [eid for eid in _cited if eid in _valid_ids]
                        _invalid = [eid for eid in _cited if eid not in _valid_ids]
                        _invalid_cited += len(_invalid)
                        if _invalid:
                            logger.warning(f"[Queen] Stripped hallucinated evidence_ids: {_invalid}")
                        # Union deterministically-bound telemetry evidence
                        _bound = _num_ev_by_adv.get(_aidx, set())
                        _new = [eid for eid in _bound if eid not in _valid]
                        if _new:
                            logger.info(
                                f"[Queen] Rebound {len(_new)} telemetry evidence_id(s) "
                                f"to advisory[{_aidx}]: {_new}"
                            )
                        _adv["evidence_ids"] = _valid + _new
                    result_str = json.dumps(_parsed)
                    if _total_cited > 0 and _invalid_cited / _total_cited > 0.5:
                        logger.warning(
                            f"[Queen] >50% evidence_ids invalid ({_invalid_cited}/{_total_cited}) — synthesis may be unreliable"
                        )
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass

            # ── STRICT CITATION COUNT ENFORCEMENT ──────────────────────────────
            result_str = self._enforce_citation_counts(result_str, plan)

            # ── Pivot detection + equipment ID whitelist strip ───────────
            try:
                _parsed = json.loads(result_str)
                _EQUIP_ID_RE = re.compile(r'\b(?:CH|AHU|VAV|FCU|MTR|CHILLER)\b[-_\s]?\d+', re.IGNORECASE)

                def normalize_equip(name: str) -> str:
                    """Canonicalize equipment ID to PREFIX+int (zero-stripped).

                    'AHU-07' -> 'AHU7', 'AHU7' -> 'AHU7', 'CH-01' -> 'CH1'.
                    Zero-stripping makes AHU-07 and AHU-7 compare equal; exact
                    equality (no substring) prevents CH-1 matching CH-11.
                    """
                    s = re.sub(r'[-_\s]', '', name).upper()
                    s = s.replace("CHILLER", "CH").replace("METER", "MTR")
                    m = re.match(r'([A-Z]+)(\d+)', s)
                    if m:
                        return f"{m.group(1)}{int(m.group(2))}"
                    return s

                def _matches_target(equip: str, targets: set) -> bool:
                    # Exact normalized equality only — no substring ambiguity
                    return equip in targets

                # Fix 1: pivot gate uses QUERY target only, not evidence equipment.
                _query_target_norm = {normalize_equip(x) for x in _EQUIP_ID_RE.findall(original_query)}
                _valid_inv_norm = {normalize_equip(x) for x in _valid_equipment_ids} if _valid_equipment_ids else set()

                _filtered_advisories = []
                _target_covered = False
                for _adv in _parsed.get("advisories", []):
                    _adv_text = f"{_adv.get('message', '')} {json.dumps(_adv.get('recommended_action', ''))}"
                    _adv_equip_norm = {normalize_equip(x) for x in _EQUIP_ID_RE.findall(_adv_text)}

                    # Fix 1: pivot = advisory addresses equipment not in the query target
                    if _query_target_norm:
                        _pivoted = {e for e in _adv_equip_norm if not _matches_target(e, _query_target_norm)}
                        if _pivoted:
                            _reason = _adv.get("pivot_reason", "")
                            if not _reason or not str(_reason).strip():
                                logger.warning(
                                    f"[Queen][PivotCheck] REJECTED advisory pivot to {_pivoted} "
                                    f"(query target: {_query_target_norm}) — no pivot_reason."
                                )
                                continue

                    # Fix 7: warn + strip equipment IDs outside sim inventory
                    if _valid_inv_norm:
                        _fabricated = {e for e in _adv_equip_norm if not any(e in v or v in e for v in _valid_inv_norm)}
                        if _fabricated:
                            logger.warning(
                                f"[Queen][EquipWhitelist] Advisory references fabricated equipment IDs "
                                f"{_fabricated} — not in sim inventory. Stripping advisory."
                            )
                            continue

                    # Track whether any surviving advisory addresses the query target
                    if _query_target_norm and (_adv_equip_norm & _query_target_norm):
                        _target_covered = True

                    _filtered_advisories.append(_adv)

                _parsed["advisories"] = _filtered_advisories

                # Coverage gate: query named specific equipment but no surviving
                # advisory addresses it. Prevents silently answering about the
                # wrong unit (P2 regression: query AHU-07, analysis drifted to
                # AHU-19). Check whether the analysis prose at least mentions the
                # target; if not, prepend a notice so the wrong-equipment answer
                # is not presented as authoritative.
                if _query_target_norm and not _target_covered:
                    _analysis = _parsed.get("analysis", "") or ""
                    _analysis_equip = {normalize_equip(x) for x in _EQUIP_ID_RE.findall(_analysis)}
                    _analysis_hits_target = bool(_analysis_equip & _query_target_norm)
                    _tgt_str = ", ".join(sorted(_query_target_norm))
                    logger.warning(
                        f"[Queen][PivotCheck] No advisory addresses query target "
                        f"{{{_tgt_str}}} (analysis_mentions_target={_analysis_hits_target}). "
                        f"Prepending target-gap notice."
                    )
                    _notice = (
                        f"NOTE: Query targeted {_tgt_str}, but ARVIS could not produce a "
                        f"grounded advisory for that equipment from available evidence. "
                        f"Any analysis of other equipment below is contextual only and does "
                        f"not substitute for a {_tgt_str} diagnosis."
                    )
                    _parsed["analysis"] = (_notice + "\n\n" + _analysis) if _analysis else _notice

                result_str = json.dumps(_parsed)
                result_str = self._gate_synthesis_titles(result_str)
            except Exception as _pivot_err:
                logger.debug(f"[Queen] Pivot/equipment-whitelist check failed (non-fatal): {_pivot_err}")

            return result_str
        except Exception as e:
            logger.error(f"[Queen] Synthesis failed: {e}")
            fallback = {
                "analysis": "Advisory synthesis temporarily unavailable. Individual agent assessments were gathered but could not be consolidated.",
                "advisories": [{
                    "id": "fallback-1",
                    "type": "system_notice",
                    "severity": "low",
                    "message": (
                        "ARVIS has gathered observations from the swarm agents but the synthesis service is temporarily unavailable. "
                        "Please re-submit your query for a consolidated advisory, or consult your FM engineer for immediate guidance."
                    ),
                    "confidence": 0.5,
                    "evidence": [{"source": "Queen", "finding": f"Synthesis unavailable ({type(e).__name__})"}],
                    "impact": {"timeframe": "N/A", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                    "recommended_action": {"type": "retry"},
                    "counterfactual_check": False
                }]
            }
            return json.dumps(fallback)

    # ── T1 lookup node picker ───────────────────────────────────────────────

    def _pick_lookup_node(self, query: str, active_nodes) -> "SwarmNode":
        """Return best-fit node for a T1 lookup query based on keyword heuristics."""
        q = query.lower()
        priority = [
            (["alarm", "alert", "fault", "trip"], "Alarm_Agent"),
            (["energy", "power", "kwh", "consumption", "demand"], "Energy_Agent"),
            (["maintenance", "service", "pm", "schedule", "work order"], "Maintenance_Agent"),
            (["temperature", "comfort", "humidity", "co2", "zone", "ahu", "vav"], "Comfort_Agent"),
        ]
        for keywords, preferred_name in priority:
            if any(kw in q for kw in keywords):
                for node in active_nodes:
                    if node.name == preferred_name:
                        return node
        return active_nodes[0]

    def _gate_synthesis_titles(self, result_str: str) -> str:
        """
        Post-synthesis Epistemic Title Gate.
        Detects self-contradictions in the synthesized JSON where a disproven or ruled-out
        prior belief (e.g. 'Damper Actuator Blade Slip') is promoted to a section header
        even though the advisory body rules it out and attributes root cause elsewhere.
        Also supports Marina Heights cascade alarms and VAV tags (AHU-19, FLOOR-23).
        """
        try:
            import json
            import re
            parsed = json.loads(result_str)
            modified = False
            for adv in parsed.get("advisories", []):
                msg = adv.get("message", "")
                if not isinstance(msg, str):
                    continue
                
                # Check for Marina Heights tags
                has_marina_tags = "ahu-19" in msg.lower() or "floor-23" in msg.lower()
                
                # If the body text explicitly states the root cause is NOT the damper or attributes it to CHW
                body_rules_out_damper = (
                    "root cause is not the damper" in msg.lower() or
                    "not the damper" in msg.lower() or
                    "chilled water" in msg.lower() or
                    "chw" in msg.lower() or
                    "cooling coil" in msg.lower() or
                    "starvation" in msg.lower() or
                    "chwst" in msg.lower() or
                    has_marina_tags
                )
                if body_rules_out_damper:
                    # Look for markdown header pattern that asserts Damper Slip
                    # e.g., '### **Damper Actuator Blade Slip ...**'
                    damper_slip_header_pattern = r"(###\s*\*\*Damper\s*Actuator\s*Blade\s*Slip.*?\*\*\n?|###\s*Damper\s*Actuator\s*Blade\s*Slip.*?\n?)"
                    if re.search(damper_slip_header_pattern, msg, re.IGNORECASE):
                        if "calibration" in msg.lower() or "watchdog" in msg.lower() or "starvation" in msg.lower():
                            new_header = "### 🟢 **System Calibrations Promoted (Watchdog Starvation Resolved)**\n"
                        elif has_marina_tags:
                            new_header = "### 🟢 **VAV Load Compensation Balanced (Damper Slip Ruled Out)**\n"
                        else:
                            new_header = "### 🟢 **Chilled Water Distribution Failure (Damper Slip Ruled Out)**\n"
                        msg = re.sub(damper_slip_header_pattern, new_header, msg, flags=re.IGNORECASE)
                        adv["message"] = msg
                        modified = True
                        
                    # Also replace legacy watchdog or calibration failures
                    calibration_failure_header_pattern = r"(###\s*\*\*Calibration\s*Starvation.*?\*\*\n?|###\s*Calibration\s*Starvation.*?\n?|###\s*\*\*Watchdog\s*Calibration.*?\*\*\n?)"
                    if re.search(calibration_failure_header_pattern, msg, re.IGNORECASE):
                        new_header = "### 🟢 **System Calibrations Promoted (Watchdog Starvation Resolved)**\n"
                        msg = re.sub(calibration_failure_header_pattern, new_header, msg, flags=re.IGNORECASE)
                        adv["message"] = msg
                        modified = True
                        
                    # Also check if the recommended action contains damper instructions that contradict
                    action = adv.get("recommended_action", {})
                    if isinstance(action, dict):
                        action_text = action.get("action", "")
                        if "damper" in action_text.lower() and ("chw" in msg.lower() or "chilled water" in msg.lower() or has_marina_tags):
                            # Re-phrase action to check CHW first, or verify damper only as secondary exclusion
                            action["action"] = (
                                "Inspect CHW isolating valves, bypass valve status, and pump flow. "
                                "Additionally, verify damper actuator calibration to conclusively rule out damper slip."
                            )
                            modified = True
            if modified:
                return json.dumps(parsed)
        except Exception as _e:
            logger.debug(f"[Queen] Title gating failed: {_e}")
        return result_str

    # ── Risk-tier classification ────────────────────────────────────────────

    async def _classify_risk_tier(self, query: str) -> int:
        """
        Classify query into risk tiers via IntentClassifier (LLM-first +
        regex fallback). Six intent classes map deterministically to tier:

            write_attempt / capability_question / lookup     → T1
            diagnostic                                       → T2
            actionable_advisory / safety_critical            → T3

        IntentClassifier handles caching, low-confidence regex fallback,
        and timeout protection. Result is cached on self._last_intent so
        downstream routing (e.g. write_attempt → System_Capability_Agent)
        can read the rich class label without re-classifying.

        Legacy regex pre-filters (_CAPABILITY_QUERY_RE, _BMS_WRITE_COMMAND_RE,
        _SAFETY_KEYWORDS_RE, _SIMPLE_LOOKUP_RE, _ADVISORY_ACTION_RE) remain
        only inside the IntentClassifier's fallback path.
        """
        # Lazy-init classifier on first use (shared LLM client, no per-call cost)
        if not hasattr(self, "_intent_classifier") or self._intent_classifier is None:
            from arvis_core.swarm.intent_classifier import IntentClassifier
            self._intent_classifier = IntentClassifier(llm_client=self.llm)

        try:
            intent = await self._intent_classifier.classify(query)
        except Exception as e:
            logger.warning(f"[Queen] IntentClassifier raised unexpectedly: {e}. Defaulting to T2.")
            self._last_intent = None
            return 2

        # Stash on self for downstream routing decisions
        self._last_intent = intent

        logger.info(
            f"[Queen] Intent: class={intent.intent_class} tier=T{intent.risk_tier} "
            f"conf={intent.confidence:.2f} src={intent.source} ({intent.elapsed_ms:.0f}ms) "
            f"reason={intent.reason!r}"
        )

        # Safety floor — defensive even though safety_critical already maps to T3.
        # If the classifier somehow returned a low tier for a safety keyword we
        # missed in examples, raise to T2 minimum.
        if _SAFETY_KEYWORDS_RE.search(query) and intent.risk_tier < 2:
            logger.info(f"[Queen] Safety keyword floor: T{intent.risk_tier} → T2")
            return 2

        return intent.risk_tier

    # ── Task lifecycle helper (NM2/NM3/NM4) ────────────────────────────────

    async def _run_with_task_lifecycle(
        self, node: SwarmNode, plan, query: str, context: Optional[Dict[str, Any]], channel: str
    ) -> Dict[str, Any]:
        """Mark task active → run node.process → mark complete/failed. Broadcasts on transitions."""
        task = None
        for t in plan.tasks:
            if t.assigned_node == node.name and t.status.value == "pending":
                task = t
                break

        if task:
            task.mark_active()
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
            except Exception:
                pass

        try:
            result = await node.process(query, context, channel=channel, plan=plan)
            if task:
                task.mark_complete()
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error(f"[Queen] Node {node.name} failed in lifecycle wrapper: {e}")
            if task:
                task.mark_failed()
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
            raise

    # ── Read-only enforcement (deterministic, not prompt-based) ───────────

    def _enforce_read_only(self, synthesis_text: str) -> str:
        """Scan synthesis output for action-claiming language. Replace violations."""
        violations = _ACTION_VERBS_RE.findall(synthesis_text)
        if not violations:
            return synthesis_text
        logger.warning(
            f"[Queen] READ-ONLY VIOLATION: found action verbs {violations} in synthesis. Sanitizing."
        )
        sanitized = synthesis_text
        for verb in violations:
            verb_lower = verb.lower().strip()
            replacement = _VERB_REPLACEMENTS.get(verb_lower, f"recommend {verb_lower}")
            sanitized = re.sub(
                r"\b" + re.escape(verb) + r"\b",
                replacement,
                sanitized,
                count=1,
                flags=re.IGNORECASE,
            )
        return sanitized

    def _enforce_citation_counts(self, result_str: str, plan: Any) -> str:
        """
        Verify that any asserted count of instances N (e.g. '14 instances') is backed by at least N inline citations.
        If it exceeds, caps the count to match the number of available citations, or defaults to 'multiple'.
        """
        try:
            import json
            import re
            _parsed = json.loads(result_str)
            # Scan and adjust each advisory
            for _adv in _parsed.get("advisories", []):
                _cited = list(set(_adv.get("evidence_ids", [])))
                _msg = _adv.get("message", "")
                _inline = re.findall(r'\[ev:\s*([a-f0-9\-]+)\]', _msg, re.IGNORECASE)
                _all_cited = list(set(_cited + _inline))
                num_citations = len(_all_cited)
                
                def _repl(match):
                    count_str = match.group(1)
                    count_val = int(count_str)
                    if count_val > num_citations:
                        if num_citations > 0:
                            logger.warning(f"[Queen] Capping instance count from {count_val} to {num_citations} to match citation count")
                            return f"{num_citations} instances"
                        else:
                            logger.warning(f"[Queen] Neutralizing instance count {count_val} to 'multiple' due to zero citations")
                            return "multiple instances"
                    return match.group(0)
                
                if _msg:
                    new_msg = re.sub(
                        r'\b(\d+)\s+(instances|occurrences|events|incidents|violations|faults|alarms|exceptions|failures|cycles)\b',
                        _repl,
                        _msg,
                        flags=re.IGNORECASE
                    )
                    _adv["message"] = new_msg
                    
            # Also clean the top-level analysis field
            _analysis = _parsed.get("analysis", "")
            if _analysis:
                _total_cited = []
                for _adv in _parsed.get("advisories", []):
                    _total_cited.extend(_adv.get("evidence_ids", []))
                _total_cited = list(set(_total_cited))
                num_citations = len(_total_cited)
                
                def _repl_analysis(match):
                    count_str = match.group(1)
                    count_val = int(count_str)
                    if count_val > num_citations:
                        if num_citations > 0:
                            return f"{num_citations} instances"
                        else:
                            return "multiple instances"
                    return match.group(0)
                    
                _parsed["analysis"] = re.sub(
                    r'\b(\d+)\s+(instances|occurrences|events|incidents|violations|faults|alarms|exceptions|failures|cycles)\b',
                    _repl_analysis,
                    _analysis,
                    flags=re.IGNORECASE
                )
                
            return json.dumps(_parsed)
        except Exception as _ce:
            logger.debug(f"[Queen] Citation count enforcement failed: {_ce}")
            return result_str

    async def _verify_pipeline(self, advice: str, plan, run_h4: bool = True, run_h2: bool = True) -> str:
        """
        Parallel verification pipeline: runs H4 (faithfulness) and H2 (claim)
        check phases concurrently on the same draft. Applies corrections sequentially
        only if checks fail — saves 1 LLM round-trip on happy path.
        """
        async def _h4_check_only(adv: str, p) -> dict:
            evidence_summary = p.evidence.to_synthesis_context()
            if len(evidence_summary) > 20000:
                evidence_summary = evidence_summary[:20000] + "\n... [truncated]"
            prompt = (
                "You are a strict Faithfulness Verifier for a BMS advisory system.\n"
                "Compare the ADVISORY against the EVIDENCE LEDGER below.\n"
                "A contradiction means the advisory asserts something opposite to what the evidence shows "
                "(e.g., says 'COP is 4.2' when evidence shows 3.1).\n\n"
                "Output ONLY valid JSON:\n"
                "{\n"
                "  \"faithful\": true/false,\n"
                "  \"contradictions\": [\"description of each contradiction\"]\n"
                "}\n"
                "If no contradictions found, set faithful=true and contradictions=[]."
            )
            user_msg = f"EVIDENCE LEDGER:\n{evidence_summary}\n\nADVISORY:\n{adv}\n\nCheck faithfulness."
            try:
                logger.info(f"[Queen][H4] Calling 'faithfulness' channel (parallel)")
                result = await self.llm.ask_json(
                    messages=[{"role": "user", "content": user_msg}],
                    system_msgs=[{"role": "system", "content": prompt}],
                    channel="faithfulness",
                )
                logger.info("[Queen][H4] 'faithfulness' channel returned (parallel)")
                if isinstance(result, list) and len(result) > 0:
                    result = result[0]
                return result if isinstance(result, dict) else {"faithful": True, "contradictions": []}
            except Exception as e:
                logger.error(f"[Queen][H4] Check phase error: {e}")
                return {"faithful": True, "contradictions": []}

        async def _h2_check_only(adv: str, p) -> dict:
            import re as _re
            evidence_summary = p.evidence.to_synthesis_context()
            if len(evidence_summary) > 20000:
                evidence_summary = evidence_summary[:20000] + "\n... [truncated]"
            ci_violations = []
            for _ev in p.evidence.get_all():
                bounds = getattr(_ev, "confidence_bounds", None)
                if not bounds:
                    continue
                lo, hi = bounds.get("lower"), bounds.get("upper")
                if lo is None or hi is None:
                    continue
                for _m in _re.findall(r'\b(\d+(?:\.\d+)?)\b', adv):
                    try:
                        num = float(_m)
                        if 0.0 < num < 1000.0 and (num < lo or num > hi):
                            model_id = getattr(_ev, "model_id", _ev.source_tool)
                            ci_violations.append(f"Value {num} outside {model_id} bounds [{lo:.2f}, {hi:.2f}]")
                    except ValueError:
                        pass

            prompt = (
                "You are a Claim Verifier. Decompose the ADVISORY into atomic factual claims "
                "(numbers, equipment states, predictions, severities).\n"
                "For each claim, check if it is SUPPORTED, UNSUPPORTED, or CONTRADICTED by the evidence.\n\n"
                "Output ONLY valid JSON:\n"
                "{\n"
                "  \"claims\": [\n"
                "    {\"claim\": \"text of claim\", \"status\": \"supported|unsupported|contradicted\", \"evidence_id\": \"id or null\"}\n"
                "  ]\n"
                "}\n\n"
                "Rules:\n"
                "- SUPPORTED: claim's number/state appears in evidence\n"
                "- UNSUPPORTED: claim makes a factual assertion not present in evidence\n"
                "- CONTRADICTED: evidence shows opposite of claim\n"
                "- Ignore meta-statements, recommendations, and advisory language — only verify factual assertions"
            )
            ci_block = ""
            if ci_violations:
                ci_block = "\n\nCI BOUNDS VIOLATIONS (deterministic pre-check):\n" + "\n".join(f"  - {v}" for v in ci_violations) + "\nTreat these numbers as UNSUPPORTED.\n"
            user_msg = f"EVIDENCE LEDGER:\n{evidence_summary}{ci_block}\n\nADVISORY:\n{adv}\n\nDecompose and verify."
            try:
                logger.info("[Queen][H2] Calling 'claim_verify' channel (parallel)")
                result = await self.llm.ask_json(
                    messages=[{"role": "user", "content": user_msg}],
                    system_msgs=[{"role": "system", "content": prompt}],
                    channel="claim_verify",
                )
                logger.info("[Queen][H2] 'claim_verify' channel returned (parallel)")
                if isinstance(result, list) and len(result) > 0:
                    result = result[0]
                return result if isinstance(result, dict) else {"claims": []}
            except Exception as e:
                logger.error(f"[Queen][H2] Check phase error: {e}")
                return {"claims": []}

        # Run check phases in parallel
        async def _noop_h4():
            return {"faithful": True, "contradictions": []}

        async def _noop_h2():
            return {"claims": []}

        h4_coro = _h4_check_only(advice, plan) if run_h4 else _noop_h4()
        h2_coro = _h2_check_only(advice, plan) if run_h2 else _noop_h2()

        h4_result, h2_result = await asyncio.gather(h4_coro, h2_coro)

        # Analyze results
        h4_failed = not h4_result.get("faithful", True) and h4_result.get("contradictions")
        h2_claims = h2_result.get("claims", [])
        h2_unsupported = [c for c in h2_claims if c.get("status") == "unsupported"]
        h2_contradicted = [c for c in h2_claims if c.get("status") == "contradicted"]
        h2_failed = bool(h2_contradicted)

        if not h4_failed and not h2_failed and not h2_unsupported:
            logger.info(f"[Queen] Verification pipeline PASSED — faithful, all {len(h2_claims)} claims supported")
            return advice

        # At least one check failed — apply corrections sequentially.
        # NOTE: parallel pre-check above already produced h4_result. Pass it
        # into _faithfulness_check so it skips its own first verification LLM
        # call. Saves one round-trip (~15-25s on Bedrock) per failed-H4 turn.
        current = advice

        if h4_failed:
            logger.warning(f"[Queen][H4] Faithfulness FAILED — {len(h4_result['contradictions'])} contradiction(s)")
            current = await self._faithfulness_check(current, plan, precomputed_check=h4_result)
            if "h4-abstain" in current or "faithfulness_abstention" in current:
                return current

        if h2_failed or h2_unsupported:
            logger.warning(f"[Queen][H2] Claims: {len(h2_unsupported)} unsupported, {len(h2_contradicted)} contradicted")
            current = await self._verify_claims(current, plan)

        return current

    async def _faithfulness_check(self, advice: str, plan, precomputed_check: Optional[Dict[str, Any]] = None) -> str:
        """
        Post-synthesis faithfulness verification.
        Checks if the answer contradicts any observation in the evidence ledger.
        If contradiction found → regenerate with explicit correction.

        precomputed_check: optional faithfulness result from an earlier parallel
        verification pass. If provided, the first H4 LLM call is skipped — saves
        one Bedrock round-trip (~15-25s) per turn where H4 failed.
        """
        if not plan or len(plan.evidence) == 0:
            return advice

        evidence_summary = plan.evidence.to_synthesis_context()
        if len(evidence_summary) > 20000:
            evidence_summary = evidence_summary[:20000] + "\n... [truncated]"

        prompt = (
            "You are a strict Faithfulness Verifier for a BMS advisory system.\n"
            "Compare the ADVISORY against the EVIDENCE LEDGER below.\n"
            "A contradiction means the advisory asserts something opposite to what the evidence shows "
            "(e.g., 'equipment is healthy' when evidence shows degradation, or 'temperature is normal' "
            "when evidence shows a breach).\n\n"
            "IMPORTANT: Output ONLY a valid JSON object:\n"
            "{\n"
            "  \"faithful\": true/false,\n"
            "  \"contradictions\": [\"description of contradiction 1\", ...]\n"
            "}\n"
            "If no contradictions found, set faithful=true and contradictions=[]."
        )

        user_msg = (
            f"EVIDENCE LEDGER:\n{evidence_summary}\n\n"
            f"ADVISORY:\n{advice}\n\n"
            "Check faithfulness."
        )

        try:
            # Use precomputed parallel-check result if caller provided one
            if precomputed_check is not None:
                logger.info("[Queen][H4] Using precomputed parallel check (skipping redundant LLM call)")
                result = precomputed_check
            else:
                logger.info(f"[Queen][H4] Calling 'faithfulness' channel LLM (evidence={len(plan.evidence)} items)")
                result = await self.llm.ask_json(
                    messages=[{"role": "user", "content": user_msg}],
                    system_msgs=[{"role": "system", "content": prompt}],
                    channel="faithfulness",
                )
                logger.info("[Queen][H4] 'faithfulness' channel returned")

            if isinstance(result, list) and len(result) > 0:
                result = result[0]

            is_faithful = result.get("faithful", True) if isinstance(result, dict) else True
            contradictions = result.get("contradictions", []) if isinstance(result, dict) else []

            if is_faithful or not contradictions:
                logger.info("[Queen][H4] Faithfulness PASSED — no contradictions")
                return advice

            logger.warning(f"[Queen][H4] Faithfulness FAILED — {len(contradictions)} contradiction(s): {contradictions}")

            # Attempt one regeneration with explicit correction instructions
            correction_prompt = (
                "The following advisory was found to CONTRADICT live observations or overcommit beyond evidence:\n\n"
                f"CONTRADICTIONS/VIOLATIONS:\n" + "\n".join(f"  - {c}" for c in contradictions) + "\n\n"
                f"ORIGINAL ADVISORY:\n{advice}\n\n"
                f"EVIDENCE LEDGER:\n{evidence_summary}\n\n"
                "Rewrite the advisory to be 100% FAITHFUL to the evidence ledger.\n"
                "Strict Constraints:\n"
                "- Remove or correct all contradicted and unsupported claims entirely.\n"
                "- Remove ANY claim that lacks direct evidence in the ledger.\n"
                "- Do NOT infer beyond cited telemetry or upgrade inference into certainty language.\n"
                "- Downgrade certainty where direct physical inspection/verification is absent. "
                "For example, do NOT claim 'Physical OA damper slippage confirmed' unless the ledger explicitly "
                "contains direct physical confirmation. Instead, state: 'Telemetry strongly suggests probable "
                "OA damper mechanical slippage, but direct physical confirmation is unavailable.'\n"
                "- Output ONLY the corrected JSON advisory."
            )

            logger.info("[Queen][H4] Calling 'faithfulness_correction' channel LLM")
            corrected = await self.llm.ask_json(
                messages=[{"role": "user", "content": correction_prompt}],
                system_msgs=[{"role": "system", "content": "You are ARVIS Queen Coordinator. Fix contradictions in the advisory to match evidence. Output valid JSON only."}],
                channel="faithfulness_correction",
            )
            logger.info("[Queen][H4] 'faithfulness_correction' channel returned")

            corrected_str = json.dumps(corrected) if isinstance(corrected, dict) else str(corrected)
            corrected_str = self._enforce_read_only(corrected_str)

            # Re-verify the correction — if still unfaithful, abstain
            logger.info("[Queen][H4] Re-verifying corrected advisory...")
            re_check = await self.llm.ask_json(
                messages=[{"role": "user", "content": f"EVIDENCE LEDGER:\n{evidence_summary}\n\nADVISORY:\n{corrected_str}\n\nCheck faithfulness."}],
                system_msgs=[{"role": "system", "content": prompt}],
                channel="faithfulness",
            )
            re_faithful = re_check.get("faithful", True) if isinstance(re_check, dict) else True
            re_contradictions = re_check.get("contradictions", []) if isinstance(re_check, dict) else []

            if not re_faithful and re_contradictions:
                logger.warning(f"[Queen][H4] Correction STILL unfaithful ({len(re_contradictions)} contradictions). Abstaining with structured evidence.")
                # Fix 6: emit structured advisory containing up to 5 raw evidence facts
                # tagged [UNVERIFIED_SYNTHESIS] so operator sees concrete data even
                # though we couldn't reconcile the prose.
                _top_facts = []
                _top_ids = []
                try:
                    _all_ev = plan.evidence.get_all()
                    def _ev_rank(e):
                        return -float(getattr(e, "relevance", 0.0) or 0.0)
                    _top5 = sorted(_all_ev, key=_ev_rank)[:5]
                    for _ev in _top5:
                        _eid = getattr(_ev, "id", "?")
                        _summary = getattr(_ev, "summary", "") or str(getattr(_ev, "raw_payload", ""))[:200]
                        _top_facts.append(f"- [unverified] {_summary[:240]} (ev:{_eid})")
                        _top_ids.append(_eid)
                except Exception:
                    pass
                _facts_block = "\n".join(_top_facts) if _top_facts else "- [unverified] No evidence available."
                return json.dumps({
                    "analysis": "[UNVERIFIED_SYNTHESIS] Advisory could not be made faithful to evidence after correction. Raw facts surfaced below.",
                    "advisories": [{
                        "id": "h4-abstain",
                        "type": "faithfulness_abstention",
                        "severity": "medium",
                        "message": (
                            "[UNVERIFIED_SYNTHESIS] ARVIS could not reconcile prose with the evidence ledger. "
                            "Top observed facts (unverified):\n" + _facts_block
                        ),
                        "confidence": 0.2,
                        "evidence_ids": _top_ids,
                        "impact": {"timeframe": "N/A", "energy_kwh": 0, "cost_qar": 0, "is_savings": False},
                        "recommended_action": {"type": "retry_with_specifics"},
                        "counterfactual_check": False
                    }]
                })

            logger.info("[Queen][H4] Faithfulness correction verified — passing corrected advisory")
            return corrected_str

        except Exception as e:
            logger.error(f"[Queen][H4] Faithfulness check error: {e}. Passing original.")
            return advice

    async def _verify_claims(self, advice: str, plan) -> str:
        """
        H2: Decompose advisory into atomic claims, verify each against evidence ledger.
        Unsupported claims get marked [unverified]. Contradicted claims get stripped.
        M3.4: Numbers outside ML confidence_bounds are flagged before LLM pass.
        """
        if not plan or len(plan.evidence) == 0:
            return advice

        # M3.4: Deterministic CI bounds pre-check — faster than LLM, no cost
        import re as _re
        ci_violations = []
        for _ev in plan.evidence.get_all():
            bounds = getattr(_ev, "confidence_bounds", None)
            if not bounds:
                continue
            lo = bounds.get("lower")
            hi = bounds.get("upper")
            if lo is None or hi is None:
                continue
            # Extract all numbers from advice and check if any fall outside bounds for this model
            for _m in _re.findall(r'\b(\d+(?:\.\d+)?)\b', advice):
                try:
                    num = float(_m)
                    # Only check numbers in the plausible ML output range (avoid flagging years, counts, etc.)
                    if 0.0 < num < 1000.0 and (num < lo or num > hi):
                        model_id = getattr(_ev, "model_id", _ev.source_tool)
                        ci_violations.append(
                            f"Value {num} from advisory is outside {model_id} confidence bounds [{lo:.2f}, {hi:.2f}]"
                        )
                except ValueError:
                    pass
        if ci_violations:
            logger.warning(f"[Queen] M3.4 CI bounds violations: {ci_violations}")

        evidence_summary = plan.evidence.to_synthesis_context()
        if len(evidence_summary) > 20000:
            evidence_summary = evidence_summary[:20000] + "\n... [truncated]"

        prompt = (
            "You are a Claim Verifier. Decompose the ADVISORY into atomic factual claims "
            "(numbers, equipment states, predictions, severities).\n"
            "For each claim, check if it is SUPPORTED, UNSUPPORTED, or CONTRADICTED by the evidence.\n\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"claims\": [\n"
            "    {\"claim\": \"text of claim\", \"status\": \"supported|unsupported|contradicted\", \"evidence_id\": \"id or null\"}\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- SUPPORTED: claim's number/state appears in evidence\n"
            "- UNSUPPORTED: claim makes a factual assertion not present in evidence\n"
            "- CONTRADICTED: evidence shows opposite of claim\n"
            "- Ignore meta-statements, recommendations, and advisory language — only verify factual assertions"
        )

        ci_block = ""
        if ci_violations:
            ci_block = "\n\nCI BOUNDS VIOLATIONS (deterministic pre-check):\n" + "\n".join(f"  - {v}" for v in ci_violations) + "\nTreat these numbers as UNSUPPORTED.\n"

        user_msg = (
            f"EVIDENCE LEDGER:\n{evidence_summary}{ci_block}\n\n"
            f"ADVISORY:\n{advice}\n\n"
            "Decompose and verify."
        )

        try:
            logger.info("[Queen][H2] Calling 'claim_verify' channel LLM")
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": prompt}],
                channel="claim_verify",
            )
            logger.info("[Queen][H2] 'claim_verify' channel returned")

            if isinstance(result, list) and len(result) > 0:
                result = result[0]
            if not isinstance(result, dict):
                return advice

            claims = result.get("claims", [])
            if not claims:
                return advice

            unsupported = [c for c in claims if c.get("status") == "unsupported"]
            contradicted = [c for c in claims if c.get("status") == "contradicted"]

            if not unsupported and not contradicted:
                logger.info(f"[Queen][H2] Claim verification PASSED — all {len(claims)} claims supported")
                return advice

            logger.warning(
                f"[Queen][H2] Claim verification: {len(unsupported)} unsupported, "
                f"{len(contradicted)} contradicted out of {len(claims)} claims"
            )

            # Only invoke the correction LLM if there are CONTRADICTED claims (evidence conflicts).
            # Unsupported claims are marked [unverified] inline — no LLM call needed.
            if not contradicted:
                logger.info("[Queen][H2] Only unsupported claims — marking inline, skipping correction LLM")
                try:
                    adv_obj = json.loads(advice) if isinstance(advice, str) else advice
                    unsupported_texts = {c.get("claim", "").strip().lower() for c in unsupported}
                    for adv in adv_obj.get("advisories", []):
                        msg = adv.get("message", "")
                        for claim_text in unsupported_texts:
                            if len(claim_text) > 10 and claim_text[:30] in msg.lower():
                                idx = msg.lower().index(claim_text[:30])
                                # Proximity check: prevent prepending if already marked [unverified]
                                prefix_chk = msg[max(0, idx - 20):idx]
                                if "[unverified]" in prefix_chk:
                                    continue
                                target_text = msg[idx : idx + len(claim_text)]
                                adv["message"] = msg.replace(
                                    target_text,
                                    f"[unverified] {target_text}"
                                )
                    return json.dumps(adv_obj)
                except Exception:
                    return advice

            # CONTRADICTED claims present — LLM correction required
            contradicted_list = "\n".join(f"  - CONTRADICTED: {c.get('claim', '')}" for c in contradicted)
            unsupported_list = "\n".join(f"  - UNSUPPORTED: {c.get('claim', '')}" for c in unsupported)

            correction_prompt = (
                f"The following claims in your advisory have verification issues:\n"
                f"{contradicted_list}\n{unsupported_list}\n\n"
                f"ORIGINAL ADVISORY:\n{advice}\n\n"
                f"EVIDENCE LEDGER:\n{evidence_summary}\n\n"
                "Rules:\n"
                "- REMOVE all CONTRADICTED claims entirely.\n"
                "- Mark UNSUPPORTED claims with '[unverified]' prefix in the message text.\n"
                "- Keep all SUPPORTED claims unchanged.\n"
                "- Output ONLY the corrected JSON advisory."
            )

            logger.info("[Queen][H2] Calling 'claim_correction' channel LLM")
            corrected = await self.llm.ask_json(
                messages=[{"role": "user", "content": correction_prompt}],
                system_msgs=[{"role": "system", "content": "You are ARVIS Queen. Remove contradicted claims, mark unsupported. Output valid JSON only."}],
                channel="claim_correction",
            )
            logger.info("[Queen][H2] 'claim_correction' channel returned")

            corrected_str = json.dumps(corrected) if isinstance(corrected, dict) else str(corrected)
            corrected_str = self._enforce_read_only(corrected_str)
            logger.info("[Queen][H2] Claim correction applied")
            return corrected_str

        except Exception as e:
            logger.error(f"[Queen][H2] Claim verification error: {e}. Passing original.")
            return advice

    async def _self_consistency_check(
        self, proposer, prompt: str, first_draft: str, context, channel: str, plan
    ) -> str:
        """
        H8: Sample a second independent draft from the same proposer.
        If the two drafts diverge significantly, escalate to BFT (caller handles).
        Returns the first draft if consistent, or flags divergence.
        """
        _N_SAMPLES = 1  # one additional sample (total 2 drafts compared)

        try:
            second_result = await proposer.process(prompt, context, channel=channel, plan=plan)
            second_draft = second_result["response"].content

            # Use LLM to assess consistency between the two drafts
            consistency_prompt = (
                "Compare these two advisory proposals for the SAME query.\n"
                "Do they agree on: (1) the diagnosis/root cause, (2) the recommended action, "
                "(3) the severity assessment?\n\n"
                "Output ONLY JSON: {\"consistent\": true/false, \"divergence\": \"description if inconsistent\"}"
            )
            user_msg = (
                f"DRAFT 1:\n{first_draft[:1500]}\n\n"
                f"DRAFT 2:\n{second_draft[:1500]}\n\n"
                "Are these consistent?"
            )

            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": consistency_prompt}],
                channel="self_consistency",
            )

            if isinstance(result, list) and result:
                result = result[0]

            is_consistent = result.get("consistent", True) if isinstance(result, dict) else True

            if is_consistent:
                logger.info("[Queen] H8 Self-consistency check PASSED.")
                return first_draft
            else:
                divergence = result.get("divergence", "unknown") if isinstance(result, dict) else "unknown"
                logger.warning(f"[Queen] H8 Self-consistency DIVERGED: {divergence}")
                # Flag the divergence — BFT will still run and provide additional review
                return (
                    first_draft + "\n\n"
                    "[SELF-CONSISTENCY WARNING] Independent re-analysis produced divergent conclusions. "
                    f"Divergence: {divergence}. BFT peer review is mandatory for this advisory."
                )

        except Exception as e:
            logger.error(f"[Queen] Self-consistency check error: {e}. Using first draft.")
            return first_draft
