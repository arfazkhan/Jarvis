"""
Every event ARVIS might tell someone about, in one shape.

The event bus carries many kinds of payload (FDD findings, BMS alarms, monitoring
health, investigation conclusions, advisories, watch outcomes, field checks).
Each is turned into one or more ``Signal``s here, and the attention gate decides
— with the same rules for all of them — who needs to know, and when.

  topic        novelty key across episodes ("fault:AHU-07:FC13"), the same key the
               conversation memory uses for "already told"
  clears       a signal that ends another (fault cleared, alarm cleared, monitoring back)
  safety       life-safety or loss of monitoring: may break quiet hours
  llm_origin   produced by a language model (investigation conclusions, terminal
               advisories): never wakes anyone unless deterministic evidence agrees
  facts        the ONLY material a message about it may use (numbers are checked)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

SEVERITIES = ("info", "low", "medium", "high", "critical")

_LIFE_SAFETY = re.compile(
    r"\b(fire|smoke|facp|sprinkler|gas\s*leak|gas\s*alarm|refrigerant\s*leak|co\s*alarm|carbon\s*monoxide|"
    r"flood|water\s*leak|leak\s*detect\w*|entrap\w*|trapped|evacuat\w*)\b", re.IGNORECASE)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Signal:
    kind: str
    topic: str
    title: str
    facts: str
    severity: str = "medium"
    subject: Optional[str] = None             # equipment / space id
    safety: bool = False
    llm_origin: bool = False
    cost: Optional[float] = None
    currency: Optional[str] = None
    clears: Optional[str] = None              # topic this signal ends
    audience: List[str] = field(default_factory=list)   # explicit recipients (numbers), if any
    ref: Dict[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def rank(self) -> int:
        return SEVERITIES.index(self.severity) if self.severity in SEVERITIES else 2


def life_safety_points() -> set:
    """Points declared life-safety in the site config (ARVIS_LIFE_SAFETY_POINTS=pid,pid)."""
    return {p.strip() for p in os.getenv("ARVIS_LIFE_SAFETY_POINTS", "").split(",") if p.strip()}


def is_life_safety(alarm: Dict[str, Any]) -> bool:
    if alarm.get("source_point_id") and alarm["source_point_id"] in life_safety_points():
        return True
    text = " ".join(str(alarm.get(k) or "") for k in ("message", "source_point_id", "alarm_type"))
    return bool(_LIFE_SAFETY.search(text))


# ── normalisers: event payload → [Signal] ─────────────────────────────────────

def from_fdd_faults(p: Dict[str, Any]) -> List[Signal]:
    owner_cost = _env_float("ARVIS_OPS_OWNER_COST", 1000.0)
    out = []
    for f in p.get("faults") or []:
        eq, rule = f.get("equipment_id"), f.get("rule_id")
        impact = f.get("impact") or {}
        cost = impact.get("cost")
        diag = (f.get("case") or {}).get("diagnosis") or {}
        causes = (diag.get("posterior") or [])[:2]
        question = (diag.get("next_question") or {}).get("question")
        headline = f.get("headline") or f"{eq} {f.get('title') or rule}"
        facts = "\n".join(filter(None, [
            f"Newly confirmed fault: {headline}",
            (f"Avoidable cost: {cost} {impact.get('currency', '')}" if cost is not None else "Cost impact: not quantified"),
            ("Likely causes: " + "; ".join(f"{c['label']} (p={c['p']})" for c in causes)) if causes else None,
            f"Question that would settle it on site: {question}" if question else None,
        ]))
        out.append(Signal(kind="fdd_fault", topic=f"fault:{eq}:{rule}", subject=eq,
                          title=f"{eq} {f.get('title') or rule}", facts=facts,
                          severity="high" if cost is not None and float(cost) >= owner_cost else "medium",
                          cost=float(cost) if cost is not None else None, currency=impact.get("currency"),
                          ref={"rule_id": rule, "case_id": (f.get("case") or {}).get("id")}))
    return out


def from_fdd_cleared(p: Dict[str, Any]) -> List[Signal]:
    return [Signal(kind="fdd_fault_cleared", topic=f"fault_cleared:{c.get('equipment_id')}:{c.get('rule_id')}",
                   subject=c.get("equipment_id"), title=f"{c.get('equipment_id')} {c.get('title')} cleared",
                   facts=f"Fault cleared on its own (no repair recorded): {c.get('headline')}", severity="info",
                   clears=f"fault:{c.get('equipment_id')}:{c.get('rule_id')}", ref={"rule_id": c.get("rule_id")})
            for c in p.get("cleared") or []]


def from_fdd_fixes(p: Dict[str, Any]) -> List[Signal]:
    out = []
    for v in p.get("verifications") or []:
        status = v.get("status")
        if status not in ("verified", "failed"):
            continue
        eq, rule = v.get("equipment_id"), v.get("rule_id")
        out.append(Signal(
            kind="fdd_fix", topic=f"fix:{v.get('id')}", subject=eq,
            title=f"{eq} repair {'worked' if status == 'verified' else 'did not fix it'}",
            facts=(f"Repair re-check on {eq} ({rule}): "
                   f"{'WORKED — fault no longer present' if status == 'verified' else 'did NOT fix it — fault still present'}.\n"
                   f"Detail: {v.get('reason', '')}\nRecorded: {v.get('note', '')}"),
            severity="low" if status == "verified" else "high",
            clears=f"fault:{eq}:{rule}" if status == "verified" else None,
            ref={"verification_id": v.get("id"), "rule_id": rule, "status": status, "note": v.get("note")}))
    return out


_ALARM_SEV = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "info": "info"}


def from_alarm_raised(p: Dict[str, Any]) -> List[Signal]:
    a = p.get("alarm") or {}
    if not a.get("alarm_id") or str(a.get("state", "active")).lower() == "resolved":
        return []
    safety = is_life_safety(a)
    sev = "critical" if safety else _ALARM_SEV.get(str(a.get("severity", "medium")).lower(), "medium")
    return [Signal(kind="alarm", topic=f"alarm:{a['alarm_id']}", subject=a.get("equipment_id"),
                   title=f"{a.get('equipment_id')}: {a.get('message')}",
                   facts=(f"BMS alarm ({sev}{', life-safety' if safety else ''}) on {a.get('equipment_id')}: "
                          f"{a.get('message')} — raised {a.get('triggered_at')}"),
                   severity=sev, safety=safety, ref={"alarm_id": a["alarm_id"], "point_id": a.get("source_point_id")})]


def from_alarm_cleared(p: Dict[str, Any]) -> List[Signal]:
    a = p.get("alarm") or {}
    if not a.get("alarm_id"):
        return []
    return [Signal(kind="alarm_cleared", topic=f"alarm_cleared:{a['alarm_id']}", subject=a.get("equipment_id"),
                   title=f"{a.get('equipment_id')} alarm cleared", severity="info",
                   facts=p.get("resolution_summary") or f"{a.get('equipment_id')} alarm cleared: {a.get('message')}",
                   clears=f"alarm:{a['alarm_id']}", ref={"alarm_id": a["alarm_id"]})]


def _health_facts(p: Dict[str, Any]) -> str:
    a = p.get("assessment") or {}
    adapters = "; ".join(f"{x['adapter']}: {'connected' if x['connected'] else 'DISCONNECTED'}"
                         f"{', ' + str(x['stale_points']) + ' stale points' if x.get('stale_points') else ''}"
                         f"{', missing devices ' + str(x['devices_missing']) if x.get('devices_missing') else ''}"
                         for x in a.get("adapters") or [])
    return (f"{a.get('fresh_points', '?')} of {a.get('total_points', '?')} points reporting in the last "
            f"{a.get('fresh_minutes', '?')} min. {adapters}").strip()


def from_monitoring(event_type: str, p: Dict[str, Any]) -> List[Signal]:
    if event_type == "monitoring_blind":
        return [Signal(kind="monitoring", topic="monitoring:blind", title="ARVIS has lost sight of the building",
                       facts=f"No live building data since {p.get('since')}. {_health_facts(p)}",
                       severity="critical", safety=True, ref={"since": p.get("since")})]
    if event_type == "monitoring_degraded":
        return [Signal(kind="monitoring", topic="monitoring:degraded", title="Part of the building is not reporting",
                       facts=f"Monitoring degraded since {p.get('since')}. {_health_facts(p)}", severity="medium",
                       ref={"since": p.get("since")})]
    if event_type == "monitoring_restored":
        was = p.get("was") or "blind"
        return [Signal(kind="monitoring_restored", topic=f"monitoring_restored:{p.get('at')}",
                       title="Building data is back",
                       facts=f"Monitoring restored after {p.get('minutes')} min ({was}). {_health_facts(p)}",
                       severity="info", clears=f"monitoring:{was}")]
    return []


def from_investigation(p: Dict[str, Any]) -> List[Signal]:
    if p.get("abstained") or not (p.get("advice") or "").strip():
        return []                                   # nothing it is willing to stand behind
    eq = p.get("equipment_id")
    return [Signal(kind="investigation", topic=f"investigation:{eq}:{p.get('plan_id') or p.get('timestamp')}",
                   subject=eq, title=f"Investigation of {eq} ({p.get('trigger')})",
                   facts=(f"Autonomous investigation ({p.get('trigger')}) on {eq}"
                          f"{', point ' + str(p['point_id']) if p.get('point_id') else ''}"
                          f"{', confidence ' + str(p['confidence']) if p.get('confidence') is not None else ''}.\n"
                          f"Conclusion: {str(p.get('advice'))[:1500]}"),
                   severity="medium", llm_origin=True,
                   ref={"plan_id": p.get("plan_id"), "trigger": p.get("trigger"), "point_id": p.get("point_id")})]


def from_advisory(p: Dict[str, Any]) -> List[Signal]:
    sev = str(p.get("severity", "high")).lower()
    sev = "critical" if sev in ("critical", "severe") else ("high" if sev == "high" else "medium")
    return [Signal(kind="advisory", topic=f"advisory:{p.get('advisory_id')}", subject=p.get("equipment_id"),
                   title=p.get("title") or "Advisory", facts=f"{p.get('title')}: {p.get('message')}",
                   severity=sev, llm_origin=True,
                   ref={"advisory_id": p.get("advisory_id"), "confidence": p.get("confidence")})]


def from_drift(p: Dict[str, Any]) -> List[Signal]:
    if p.get("status") != "confirmed":
        return []                                   # transient: it cleared by itself
    eq = p.get("equipment_id")
    return [Signal(kind="drift", topic=f"drift:{eq}:{p.get('point_id')}", subject=eq,
                   title=f"Sustained deviation on {p.get('point_id')}",
                   facts=(f"Sustained deviation on {p.get('point_id')} ({eq}): flagged {p.get('repeats')} times "
                          f"over the watch window — {p.get('reason')}. An investigation is running."),
                   severity="low", ref={"point_id": p.get("point_id")})]


def from_field_check(p: Dict[str, Any]) -> List[Signal]:
    status = p.get("status")
    if status not in ("expired", "failed") or not p.get("requested_by"):
        return []
    who = p.get("technician_name") or p.get("technician")
    what = "got no answer in time" if status == "expired" else "could not be delivered"
    return [Signal(kind="field_check", topic=f"check:{p.get('id')}:{status}", subject=p.get("equipment_id"),
                   title=f"Check {p.get('ref')} to {who} {what}",
                   facts=f"The check you asked for ({p.get('ref')}, {p.get('equipment_id')}: {p.get('question')}) "
                         f"sent to {who} {what}.", severity="medium", audience=[p["requested_by"]],
                   ref={"check_id": p.get("id"), "status": status})]


def from_empty_conditioned(p: Dict[str, Any]) -> List[Signal]:
    """A zone nobody is in (access control / people counter) that is still being cooled."""
    zone, name = p.get("zone"), p.get("name") or p.get("zone")
    return [Signal(kind="energy", topic=f"empty:{zone}", subject=zone,
                   title=f"{name} is empty but still being cooled",
                   facts=(f"{name} ({zone}) has had nobody in it since {str(p.get('empty_since', ''))[11:16]} "
                          f"({p.get('minutes')} min, by access control / people count), but its conditioning is "
                          f"still running: {'; '.join(p.get('running') or [])}. Worth switching it to unoccupied mode."),
                   severity="medium", ref={"zone": zone})]


def from_empty_conditioned_cleared(p: Dict[str, Any]) -> List[Signal]:
    zone, name = p.get("zone"), p.get("name") or p.get("zone")
    return [Signal(kind="energy_cleared", topic=f"empty:{zone}:cleared", subject=zone,
                   title=f"{name}: no longer cooling an empty space",
                   facts=f"{name} ({zone}): {p.get('why')}.", severity="info", clears=f"empty:{zone}")]


NORMALISERS: Dict[str, Callable[[Dict[str, Any]], List[Signal]]] = {
    "fdd_faults_confirmed": from_fdd_faults,
    "fdd_fault_cleared": from_fdd_cleared,
    "fdd_fix_verified": from_fdd_fixes,
    "bms_alarm_raised": from_alarm_raised,
    "bms_alarm_cleared": from_alarm_cleared,
    "monitoring_blind": lambda p: from_monitoring("monitoring_blind", p),
    "monitoring_degraded": lambda p: from_monitoring("monitoring_degraded", p),
    "monitoring_restored": lambda p: from_monitoring("monitoring_restored", p),
    "investigation_concluded": from_investigation,
    "terminal_advisory_fired": from_advisory,
    "drift_watch_outcome": from_drift,
    "field_check_changed": from_field_check,
    "zone_empty_but_conditioned": from_empty_conditioned,
    "zone_empty_but_conditioned_cleared": from_empty_conditioned_cleared,
}


def to_signals(event: Dict[str, Any]) -> List[Signal]:
    fn = NORMALISERS.get(event.get("type", ""))
    return fn(event.get("payload") or {}) if fn else []
