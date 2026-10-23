"""
ARVIS role agents — the seven-stage investigation pipeline
==========================================================

    Anomaly → Diagnostic → Knowledge → Verification → Recommendation
                      ↓ (dossier: evidence ledger + every specialist's context)
             Investigation (the domain specialists: Alarm, Comfort, Energy, …)
                      ↓
                   Briefing

The specialists (agent_commercial/swarm_nodes.py) are LLM agents that call
tools. Before they start, the role agents assemble what ARVIS already *knows*
from its deterministic engines and report it to them:

  Anomaly_Agent         confirmed rule-FDD faults, active alarms, bad/stale points
  Diagnostic_Agent      open diagnosis cases: ranked causes (Bayesian) + the next
                        question with the highest information gain
  Knowledge_Agent       learned skills for this equipment, how past cases on it
                        were resolved, and which repairs worked
  Verification_Agent    repairs awaiting re-check / verified / failed (closed loop)
  Recommendation_Agent  ranked next checks built from the reports above

After the specialists finish:

  Investigation_Agent   which specialists investigated and what evidence each added
  Briefing_Agent        a plain operator summary of the whole dossier

These roles make no LLM calls and never invent: each item comes from a stored
finding, case, skill or verification, is written to the plan's evidence ledger
(so answers can cite it), and an engine that has nothing says so. A role whose
engine fails reports "unavailable" with the reason — it never fills the gap.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger("arvis.roles")

ROLE_ORDER = ("Anomaly_Agent", "Diagnostic_Agent", "Investigation_Agent", "Recommendation_Agent",
              "Verification_Agent", "Knowledge_Agent", "Briefing_Agent")

_EQ_RE = re.compile(r"\b([A-Za-z]{2,8})[-_\s]?(\d{1,4})\b")   # 8: "chiller 1"
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _eq_key(prefix: str, number: str) -> str:
    """'ahu', '07' → 'AHU7' — so 'AHU 7', 'ahu-07' and 'AHU-07' are the same unit."""
    p = prefix.upper()
    return f"{'CH' if p == 'CHILLER' else p}{int(number)}"


@dataclass
class RoleReport:
    role: str
    status: str = "ok"                    # ok | empty | unavailable
    summary: str = ""
    items: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "status": self.status, "summary": self.summary,
                "items": self.items, "evidence_ids": self.evidence_ids}


class _Role:
    name = ""

    def __init__(self, orchestrator: "RoleOrchestrator"):
        self.o = orchestrator

    def _cite(self, report: RoleReport, plan: Any, kind: str, payload: Dict[str, Any], summary: str,
              equipment_id: Optional[str] = None) -> str:
        """Write one item to the evidence ledger and return its id (empty without a plan)."""
        if plan is None:
            return ""
        from arvis_core.evidence import Evidence, FreshnessStatus
        ev = Evidence(source_tool=f"role:{kind}", raw_payload=payload, node_name=self.name,
                      freshness=FreshnessStatus.RECENT, summary=summary, equipment_id=equipment_id)
        plan.evidence.add(ev)
        report.evidence_ids.append(ev.id)
        return ev.id


# ─────────────────────────────────────────────────────────────────────────────
class AnomalyAgent(_Role):
    name = "Anomaly_Agent"

    async def run(self, scope: Set[str], plan: Any) -> RoleReport:
        r = RoleReport(self.name)
        limit = self.o.max_items
        items: List[Dict[str, Any]] = []

        from agent_commercial.fdd.store import latest_findings
        faults = [f for f in await latest_findings(self.o.database, outcome="fail")
                  if not scope or f.get("equipment_id") in scope]
        faults.sort(key=lambda f: (-float((f.get("impact") or {}).get("cost") or 0),
                                   -float(f.get("fault_hours") or 0)))
        for f in faults[:limit]:
            impact = f.get("impact") or {}
            item = {"kind": "fault", "equipment_id": f.get("equipment_id"), "rule_id": f.get("rule_id"),
                    "title": f.get("title"), "fault_hours": f.get("fault_hours"), "fault_pct": f.get("fault_pct"),
                    "last_fault": f.get("last_fault"),
                    "cost": impact.get("cost"), "currency": impact.get("currency")}
            item["evidence_id"] = self._cite(r, plan, "anomaly:fdd", item, f.get("headline") or f.get("title", ""),
                                             f.get("equipment_id"))
            items.append(item)

        alarms = [a for a in await self.o.state_engine.get_active_alarms()
                  if not scope or a.equipment_id in scope]
        alarms.sort(key=lambda a: _SEVERITY_RANK.get(getattr(a.severity, "value", str(a.severity)), 9))
        for a in alarms[:limit]:
            sev = getattr(a.severity, "value", str(a.severity))
            item = {"kind": "alarm", "equipment_id": a.equipment_id, "severity": sev, "message": a.message,
                    "point_id": a.source_point_id}
            item["evidence_id"] = self._cite(r, plan, "anomaly:alarm", item,
                                             f"{a.equipment_id}: {sev} alarm — {a.message}", a.equipment_id)
            items.append(item)

        # Sensor data quality only within scope: building-wide it would be every point.
        for eq in sorted(scope):
            bad = [p for p in await self.o.state_engine.get_points_by_equipment(eq)
                   if getattr(getattr(p, "quality", None), "value", "") in ("stale", "bad")]
            for p in bad[:limit]:
                q = p.quality.value
                item = {"kind": "data_quality", "equipment_id": eq, "point_id": p.point_id, "quality": q}
                item["evidence_id"] = self._cite(r, plan, "anomaly:data_quality", item,
                                                 f"{p.point_id} reading is {q} — do not trust its value", eq)
                items.append(item)

        r.items = items
        n_f, n_a, n_d = (sum(1 for i in items if i["kind"] == k) for k in ("fault", "alarm", "data_quality"))
        if not items:
            r.status, r.summary = "empty", (f"No confirmed faults, active alarms or bad sensor readings "
                                            f"{'on ' + ', '.join(sorted(scope)) if scope else 'in the building'}.")
        else:
            r.summary = f"{n_f} confirmed fault(s), {n_a} active alarm(s), {n_d} unreliable reading(s)."
        return r


# ─────────────────────────────────────────────────────────────────────────────
class DiagnosticAgent(_Role):
    name = "Diagnostic_Agent"

    async def run(self, scope: Set[str], plan: Any) -> RoleReport:
        r = RoleReport(self.name)
        from agent_commercial.fdd.diagnosis import list_cases
        cases = [c for c in await list_cases(self.o.database, status="open")
                 if not scope or c.equipment_id in scope]
        for c in cases[: self.o.max_items]:
            d = c.diagnosis or {}
            ranked = [h for h in (d.get("posterior") or []) if (h.get("p") or 0) > 0][:3]
            item = {"case_id": c.id, "equipment_id": c.equipment_id, "rule_id": c.rule_id,
                    "causes": ranked, "eliminated": d.get("eliminated") or [],
                    "model_exhausted": bool(d.get("kb_bust")),
                    "next_question": d.get("next_question"), "occurrences": c.occurrences}
            if d.get("kb_bust"):
                text = (f"{c.equipment_id} {c.rule_id}: no modelled cause fits the evidence — "
                        "the true cause is outside the diagnosis model; investigate manually.")
            elif ranked:
                text = f"{c.equipment_id} {c.rule_id}: most likely " + "; ".join(
                    f"{h['label']} (p={h['p']:.2f})" for h in ranked)
            else:
                text = f"{c.equipment_id} {c.rule_id}: open case, no ranked causes yet."
            item["evidence_id"] = self._cite(r, plan, "diagnosis:case", item, text, c.equipment_id)
            r.items.append(item)
        if not r.items:
            r.status, r.summary = "empty", "No open diagnosis cases" + (
                f" for {', '.join(sorted(scope))}." if scope else ".")
        else:
            r.summary = f"{len(r.items)} open diagnosis case(s) with ranked causes."
        return r


# ─────────────────────────────────────────────────────────────────────────────
class KnowledgeAgent(_Role):
    name = "Knowledge_Agent"

    async def run(self, query: str, scope: Set[str], plan: Any) -> RoleReport:
        r = RoleReport(self.name)
        limit = self.o.max_items

        # Learned skills, scoped to each unit (and once building-wide when no unit is named).
        from agent_commercial.skillbook import get_skillbook
        sb = get_skillbook(self.o.building_id)
        await sb.ensure_initialized()
        seen: Set[str] = set()
        empty_diag = None
        for eq in (sorted(scope) or [None]):
            ctx: Dict[str, Any] = {"situation_query": query, "query": query, "similarity_threshold": 0.2}
            if eq:
                ctx["equipment_id"] = eq
            skills = await sb.get_relevant_skills(ctx, limit=limit)
            if not skills and empty_diag is None:
                empty_diag = await sb.explain_empty(ctx)
            for s in skills:
                # Semantic recall is not equipment-scoped: a lesson learned on another
                # unit must not be reported as this unit's experience.
                if s.skill_id in seen or (scope and s.equipment_id and s.equipment_id not in scope):
                    continue
                seen.add(s.skill_id)
                item = {"kind": "skill", "skill_id": s.skill_id, "title": s.title,
                        "equipment_id": s.equipment_id, "confidence": round(float(s.confidence), 2),
                        "status": getattr(s.status, "value", str(s.status))}
                item["evidence_id"] = self._cite(r, plan, "knowledge:skill", item,
                                                 f"Learned: {s.title} (confidence {item['confidence']})",
                                                 s.equipment_id)
                r.items.append(item)

        # Facts the team confirmed in conversation ("AHU-07 serves level 3 west").
        try:
            from agent_commercial.ops_engineer.learning import Learning
            for f in await Learning(self.o.database).facts(sorted(scope) or None, limit=limit):
                if scope and f.subject and f.subject not in scope:
                    continue
                item = {"kind": "fact", "equipment_id": f.subject, "title": f.statement,
                        "said_by": f.said_by_name, "said_at": f.said_at}
                item["evidence_id"] = self._cite(r, plan, "knowledge:fact", item,
                                                 f"Told by {f.said_by_name} ({f.said_at[:10]}): {f.statement}",
                                                 f.subject)
                r.items.append(item)
        except Exception as e:
            logger.debug(f"[Roles] building facts unavailable: {e}")

        # How earlier cases on these units ended.
        from agent_commercial.fdd.diagnosis import list_cases
        past = [c for c in await list_cases(self.o.database)
                if c.status in ("closed", "cleared") and c.resolution and (not scope or c.equipment_id in scope)]
        for c in past[-limit:]:
            item = {"kind": "past_case", "case_id": c.id, "equipment_id": c.equipment_id,
                    "rule_id": c.rule_id, "resolution": c.resolution}
            item["evidence_id"] = self._cite(r, plan, "knowledge:past_case", item,
                                             f"{c.equipment_id} {c.rule_id} previously resolved: "
                                             f"{str(c.resolution)[:160]}", c.equipment_id)
            r.items.append(item)

        if not r.items:
            r.status = "empty"
            why = (empty_diag or {}).get("empty_reason")
            r.summary = "No relevant past experience" + (f" ({why})." if why else ".")
            if empty_diag:
                r.items.append({"kind": "retrieval", "retrieval": empty_diag})
        else:
            n = {k: sum(1 for i in r.items if i["kind"] == k) for k in ("skill", "fact", "past_case")}
            r.summary = (f"{n['skill']} learned skill(s), {n['fact']} fact(s) from the team, "
                         f"{n['past_case']} resolved past case(s).")
        return r


# ─────────────────────────────────────────────────────────────────────────────
class VerificationAgent(_Role):
    name = "Verification_Agent"

    async def run(self, scope: Set[str], plan: Any) -> RoleReport:
        r = RoleReport(self.name)
        from agent_commercial.fdd.closed_loop import list_verifications
        rows = [v for v in await list_verifications(self.o.database)
                if not scope or v.equipment_id in scope]
        order = {"failed": 0, "pending": 1, "verified": 2}
        rows.sort(key=lambda v: (order.get(v.status, 3), v.id or 0))
        for v in rows[: self.o.max_items]:
            item = {"verification_id": v.id, "equipment_id": v.equipment_id, "rule_id": v.rule_id,
                    "status": v.status, "reason": v.reason, "repaired_at": v.repaired_at,
                    "running_hours": v.running_hours, "work_order_id": v.work_order_id,
                    "hypothesis": v.hypothesis}
            text = {"verified": f"Repair on {v.equipment_id} ({v.rule_id}) verified: fault no longer present.",
                    "failed": f"Repair on {v.equipment_id} ({v.rule_id}) did NOT clear the fault: {v.reason}",
                    }.get(v.status, f"Repair on {v.equipment_id} ({v.rule_id}) awaiting re-check: {v.reason}")
            item["evidence_id"] = self._cite(r, plan, "verification:repair", item, text, v.equipment_id)
            r.items.append(item)
        if not r.items:
            r.status, r.summary = "empty", "No recorded repairs to verify" + (
                f" on {', '.join(sorted(scope))}." if scope else ".")
        else:
            by = {s: sum(1 for i in r.items if i["status"] == s) for s in ("pending", "verified", "failed")}
            r.summary = f"{by['verified']} verified, {by['failed']} failed, {by['pending']} awaiting re-check."
        return r


# ─────────────────────────────────────────────────────────────────────────────
class RecommendationAgent(_Role):
    name = "Recommendation_Agent"

    def run(self, anomaly: RoleReport, diagnostic: RoleReport, verification: RoleReport) -> RoleReport:
        """Ranked next checks. Order: critical/high alarms, failed repairs, the
        diagnosis question that best separates the likely causes (costliest fault
        first), repairs awaiting re-check. Every check cites its source item."""
        r = RoleReport(self.name)
        checks: List[Dict[str, Any]] = []
        for a in anomaly.items:
            if a["kind"] == "alarm" and a.get("severity") in ("critical", "high"):
                checks.append({"priority": 0 if a["severity"] == "critical" else 1,
                               "check": f"Respond to the {a['severity']} alarm on {a['equipment_id']}: {a['message']}",
                               "why": "active alarm", "equipment_id": a["equipment_id"],
                               "source": a.get("evidence_id")})
        for v in verification.items:
            if v["status"] == "failed":
                checks.append({"priority": 2, "check": f"Re-open the repair on {v['equipment_id']} ({v['rule_id']}): "
                                                       f"the fault persisted after the work.",
                               "why": v.get("reason") or "repair not effective", "equipment_id": v["equipment_id"],
                               "source": v.get("evidence_id")})
        cost = {(a["equipment_id"], a.get("rule_id")): a.get("cost") or 0 for a in anomaly.items if a["kind"] == "fault"}
        diag = sorted(diagnostic.items, key=lambda c: -(cost.get((c["equipment_id"], c["rule_id"])) or 0))
        for c in diag:
            q = c.get("next_question")
            if q and q.get("question"):
                top = c["causes"][0]["label"] if c.get("causes") else "the open causes"
                checks.append({"priority": 3, "check": f"{c['equipment_id']}: {q['question']}",
                               "why": f"best separates the likely causes (currently: {top})",
                               "equipment_id": c["equipment_id"], "case_id": c["case_id"],
                               "evidence_question_id": q.get("evidence_id"), "source": c.get("evidence_id")})
            elif c.get("model_exhausted"):
                checks.append({"priority": 3, "check": f"{c['equipment_id']} {c['rule_id']}: inspect on site — "
                                                       "none of the modelled causes fits.",
                               "why": "diagnosis model exhausted", "equipment_id": c["equipment_id"],
                               "source": c.get("evidence_id")})
        for v in verification.items:
            if v["status"] == "pending":
                checks.append({"priority": 4, "check": f"Let {v['equipment_id']} run so the repair for "
                                                       f"{v['rule_id']} can be re-checked ({v['reason']}).",
                               "why": "closed-loop verification pending", "equipment_id": v["equipment_id"],
                               "source": v.get("evidence_id")})
        checks.sort(key=lambda c: c["priority"])
        r.items = checks[: self.o.max_items]
        if not r.items:
            r.status, r.summary = "empty", "No checks pending from alarms, diagnosis or repair verification."
        else:
            r.summary = f"{len(r.items)} next check(s), most urgent first."
        return r


# ─────────────────────────────────────────────────────────────────────────────
class BriefingRole(_Role):
    name = "Briefing_Agent"

    def run(self, reports: Dict[str, RoleReport]) -> RoleReport:
        """Plain operator summary of the dossier: one line per role, then the first checks."""
        lines = []
        for role in ("Anomaly_Agent", "Diagnostic_Agent", "Knowledge_Agent", "Verification_Agent"):
            rep = reports.get(role)
            if rep:
                lines.append(f"{role.replace('_Agent', '')}: {rep.summary}")
        rec = reports.get("Recommendation_Agent")
        if rec and rec.items:
            lines.append("Next checks: " + " | ".join(c["check"] for c in rec.items[:3]))
        return RoleReport(self.name, summary="\n".join(lines),
                          items=[{"line": ln} for ln in lines])


# ─────────────────────────────────────────────────────────────────────────────
class RoleOrchestrator:
    """Runs the role agents around a swarm investigation (wired to the Queen as
    ``queen.role_orchestrator``)."""

    def __init__(self, state_engine: Any, database: Any, building_id: Optional[str] = None,
                 max_items: Optional[int] = None):
        self.state_engine = state_engine
        self.database = database
        self.building_id = building_id or os.getenv("ARVIS_BUILDING_ID", "default")
        self.max_items = max_items or _env_int("ARVIS_ROLE_MAX_ITEMS", 8)
        self.anomaly = AnomalyAgent(self)
        self.diagnostic = DiagnosticAgent(self)
        self.knowledge = KnowledgeAgent(self)
        self.verification = VerificationAgent(self)
        self.recommendation = RecommendationAgent(self)
        self.briefing = BriefingRole(self)

    async def scope(self, query: str, context: Optional[Dict[str, Any]] = None) -> Set[str]:
        """Registered equipment the query (or context) names. Unknown ids are ignored —
        a typo must not silently scope the investigation to nothing."""
        known = {}
        for eq in await self.state_engine.get_all_equipment():
            m = _EQ_RE.fullmatch(eq.equipment_id.strip())
            if m:
                known[_eq_key(m.group(1), m.group(2))] = eq.equipment_id
            known.setdefault(eq.equipment_id.upper(), eq.equipment_id)
        text = " ".join([query or "", str((context or {}).get("equipment_id") or "")])
        out = set()
        for m in _EQ_RE.finditer(text):
            hit = known.get(_eq_key(m.group(1), m.group(2)))
            if hit:
                out.add(hit)
        return out

    async def _safe(self, role: _Role, coro) -> RoleReport:
        try:
            return await coro
        except Exception as e:
            logger.warning(f"[Roles] {role.name} unavailable: {type(e).__name__}: {e}")
            return RoleReport(role.name, status="unavailable", summary=f"{role.name} unavailable: {type(e).__name__}")

    async def before_investigation(self, query: str, context: Optional[Dict[str, Any]], plan: Any) -> Dict[str, Any]:
        """Build the dossier the specialists start from. Returns {"scope", "reports", "prompt"}."""
        scope = await self.scope(query, context)
        anomaly = await self._safe(self.anomaly, self.anomaly.run(scope, plan))
        # Without a named unit, diagnose and recall for the units that are actually faulting.
        focus = scope or {i["equipment_id"] for i in anomaly.items if i.get("equipment_id")}
        diagnostic = await self._safe(self.diagnostic, self.diagnostic.run(focus, plan))
        knowledge = await self._safe(self.knowledge, self.knowledge.run(query, focus, plan))
        verification = await self._safe(self.verification, self.verification.run(focus, plan))
        try:
            recommendation = self.recommendation.run(anomaly, diagnostic, verification)
        except Exception as e:
            logger.warning(f"[Roles] Recommendation_Agent unavailable: {e}")
            recommendation = RoleReport("Recommendation_Agent", status="unavailable", summary="unavailable")
        reports = {r.role: r for r in (anomaly, diagnostic, knowledge, verification, recommendation)}
        reports["Briefing_Agent"] = self.briefing.run(reports)
        if plan is not None:
            plan.role_reports = {"scope": sorted(scope), "focus": sorted(focus),
                                 **{k: v.to_dict() for k, v in reports.items()}}
        return {"scope": sorted(scope), "focus": sorted(focus), "reports": reports,
                "prompt": self.to_prompt(reports, focus)}

    def after_investigation(self, plan: Any, specialists: Iterable[str]) -> Dict[str, Any]:
        """Record what the Investigation stage (the specialists) contributed."""
        roles = set(ROLE_ORDER)
        counts: Dict[str, int] = {}
        for ev in plan.evidence.get_all():
            node = getattr(ev, "node_name", "") or ""
            if node and node not in roles:
                counts[node] = counts.get(node, 0) + 1
        names = sorted(set(specialists))
        inv = RoleReport("Investigation_Agent",
                         status="ok" if names else "empty",
                         summary=(f"{len(names)} specialist(s) investigated: {', '.join(names)}"
                                  if names else "No specialists ran."),
                         items=[{"specialist": n, "evidence_added": counts.get(n, 0)} for n in names])
        reports = dict(getattr(plan, "role_reports", {}) or {})
        reports["Investigation_Agent"] = inv.to_dict()
        plan.role_reports = reports
        return reports

    @staticmethod
    def to_prompt(reports: Dict[str, RoleReport], focus: Set[str]) -> str:
        """Compact block for the specialists' context. Cite items by evidence id."""
        out = ["ROLE AGENT REPORTS (deterministic, from ARVIS engines — cite by evidence id; "
               "these are facts already established, do not re-derive or contradict them without new evidence)"]
        if focus:
            out.append(f"Focus equipment: {', '.join(sorted(focus))}")
        for role in ("Anomaly_Agent", "Diagnostic_Agent", "Knowledge_Agent", "Verification_Agent",
                     "Recommendation_Agent"):
            rep = reports.get(role)
            if not rep:
                continue
            out.append(f"[{role}] {rep.summary}")
            for it in rep.items[:6]:
                eid = it.get("evidence_id") or it.get("source") or ""
                if role == "Anomaly_Agent":
                    desc = (f"{it['equipment_id']} {it.get('rule_id') or ''} {it.get('title') or it.get('message') or ''}"
                            f"{' — ' + str(it.get('quality')) if it['kind'] == 'data_quality' else ''}")
                    if it["kind"] == "fault":
                        # The figures travel with the fault, so whoever reads this can cite them.
                        if it.get("fault_hours") is not None:
                            desc += f" — confirmed {it['fault_hours']:g} h"
                            if it.get("fault_pct") is not None:
                                desc += f" ({it['fault_pct']:g}% of running time)"
                        if it.get("cost") is not None:
                            desc += f"; avoidable cost {it['cost']:g} {it.get('currency') or ''}".rstrip()
                    elif it["kind"] == "alarm":
                        desc += f" ({it.get('severity')})"
                elif role == "Diagnostic_Agent":
                    causes = "; ".join(f"{h['label']} p={h['p']:.2f}" for h in it.get("causes") or [])
                    desc = f"{it['equipment_id']} {it['rule_id']}: {causes or 'no ranked cause'}"
                elif role == "Knowledge_Agent":
                    desc = it.get("title") or f"{it.get('equipment_id')} {it.get('rule_id')}: {it.get('resolution')}"
                    if it.get("kind") == "retrieval":
                        continue
                    if it.get("kind") == "fact":
                        desc = f"(told by {it.get('said_by')}) {desc}"
                elif role == "Verification_Agent":
                    desc = f"{it['equipment_id']} {it['rule_id']}: {it['status']} — {it['reason']}"
                else:
                    desc = f"{it['check']} ({it['why']})"
                out.append(f"  - {str(desc).strip()}" + (f" [{eid}]" if eid else ""))
        return "\n".join(out)
