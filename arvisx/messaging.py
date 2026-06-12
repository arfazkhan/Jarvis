"""
ArvisX Phase-14 — WhatsApp operational layer (deterministic, no LLM, no raw telemetry).

Residential users live in WhatsApp, not dashboards. This turns the engine's output into
operational-language messages: a daily digest, sparse trustworthy alerts, and answers to
the handful of questions people actually ask ("any issues? why? water status?"). Three
principles from the product review, enforced here:
  1. DETERMINISTIC first — the top questions are answered from the floor (build_report,
     impact graph, water engine), no LLM. Sovereign, instant, no hallucination.
  2. NO raw telemetry — never '12.4A'; always 'Transfer Pump A runtime +43%, inspect bearings'.
  3. ANTI-FATIGUE — alerts only for severity>=WARNING AND confidence in {Medium,High}, deduped
     by signature, so the bot stays sparse and trusted (the 'act on 8/10 alerts' metric).
Actions (create work order) are ROLE-gated; reads are open to any authorized user.

Three-tier voice:
  resident — outcome language only; no asset names, no %, no kW, no confidence noise.
             Only surfaces CRITICAL service disruptions; all else is "normal".
  manager/owner — current digest: bands, issues ranked, money lines.
  technician/fm — full: asset, signal deviation, recommended action, confidence tag.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from arvisx.models import CommunityReport, OUTCOME_LABEL, ServiceType, Severity

_BAND_EMOJI = {"Healthy": "✅", "Attention Required": "⚠️", "Critical": "🚨"}
_SEV_EMOJI = {Severity.CRITICAL: "🚨", Severity.WARNING: "⚠️", Severity.MAINTENANCE: "🔧", Severity.INFO: "ℹ️"}

# ── Resident-tier voice ───────────────────────────────────────────────────
# Maps ServiceType → (ok_phrase, disrupted_phrase).
# ok = what a resident sees when nothing is wrong.
# disrupted = what a resident sees when severity==CRITICAL (service down or imminent).
_RESIDENT_SERVICE: Dict[ServiceType, tuple] = {
    ServiceType.WATER:        ("💧 Water supply normal",
                               "🚨 Water supply disruption — building team is on it"),
    ServiceType.POWER_BACKUP: ("⚡ Backup power ready",
                               "🚨 Backup power issue — building team notified"),
    ServiceType.POOL:         ("🏊 Pool operational",
                               "🚨 Pool temporarily out of service"),
    ServiceType.STP:          ("🌿 Waste management normal",
                               "🚨 Waste system issue — building team is on it"),
    ServiceType.FIRE:         ("🔥 Fire systems normal",
                               "🚨 Fire system alert — evacuate if alarm sounds"),
    ServiceType.GAS:          ("🔥 Cooking gas supply normal",
                               "🚨 Gas supply issue — do not use gas appliances, building team notified"),
    ServiceType.ENERGY:       ("💡 Common areas normal", "⚠️ Energy system attention needed"),
}

# roles that receive the full technician/FM voice
_TECH_ROLES = {"technician", "fm", "owner"}
# roles that receive the manager/committee voice
_MGR_ROLES = {"manager", "committee"}


# ── intent routing (keyword → canned intent) ─────────────────────────────
def route_intent(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"\bcreate\b.*\b(work ?order|ticket|wo)\b|\braise\b.*\bticket\b", t):
        return "create_work_order"
    if re.search(r"cost|costing|money|spend|expensive|how much|save|budget", t):
        return "cost"
    if re.search(r"\bwhy\b|reason|dropped|going down|reduced", t):
        return "why"
    if re.search(r"\bwater\b", t):
        return "water"
    if re.search(r"\bpower\b|generator|backup|\bgen\b|diesel", t):
        return "power"
    if re.search(r"\bpool\b", t):
        return "pool"
    if re.search(r"\bstp\b|sewage|blower", t):
        return "stp"
    if re.search(r"\bfire\b", t):
        return "fire"
    if re.search(r"\bgas\b|\blpg\b|cooking", t):
        return "gas"
    if re.search(r"\bfix\b|repair|what (should|do) (i|we) do|recommend|next step|action", t):
        return "fix"
    if re.search(r"issue|problem|alert|wrong|attention|risk", t):
        return "issues"
    if re.search(r"how.*(doing|building|today)|status|readiness|overall|summary|digest", t):
        return "status"
    if re.search(r"^(hi|hello|hey|salam|salaam|namaste|good (morning|evening|afternoon))\b", t.strip()):
        return "status"                      # a greeting gets the digest, not a shrug
    if re.search(r"help|commands|what can you", t):
        return "help"
    return "unknown"


def _svc(report: CommunityReport, st: ServiceType):
    return next((s for s in report.services if s.service == st), None)


def _service_line(report: CommunityReport, st: ServiceType) -> str:
    s = _svc(report, st)
    if s is None:
        return f"{OUTCOME_LABEL.get(st, st.value)}: not monitored"
    rk = [r for r in report.risks if r.service == st]
    head = f"{_BAND_EMOJI.get(s.band.value, '•')} {OUTCOME_LABEL.get(st, st.value)} — {s.band.value} ({s.score:.0f}%)"
    if rk:
        head += "\n" + "\n".join(f"   • {r.message}  [{r.confidence}]" for r in rk[:3])
    return head


# ── the canned answers (deterministic) ───────────────────────────────────
def answer(text: str, report: CommunityReport, assets: Optional[list] = None,
           baselines=None, role: str = "viewer") -> Dict[str, Any]:
    intent = route_intent(text)
    r = role.lower() if role else "viewer"
    if r == "resident":
        return _answer_resident(intent, text, report, assets, baselines)
    if r in _TECH_ROLES:
        return _answer_tech(intent, text, report, assets, baselines)
    # manager / committee / viewer / owner fallthrough → standard voice
    if intent == "status":
        return {"intent": intent, "text": daily_digest(report)}
    if intent == "cost":
        from arvisx.economics import community_cost_message
        return {"intent": intent, "text": community_cost_message(report, assets or [], baselines)}
    if intent == "issues":
        if not report.risks:
            return {"intent": intent, "text": "✅ No active issues. All services nominal."}
        ranked = sorted(report.risks, key=_risk_rank)        # worst first
        shown = ranked[:10]
        lines = [f"{_SEV_EMOJI.get(r.severity, '•')} {r.message}  [{r.confidence}]" for r in shown]
        text = f"*{len(report.risks)} active issue(s)* (top {len(shown)}):\n" + "\n".join(lines)
        extra = len(report.risks) - len(shown)
        if extra > 0:
            text += f"\n\n…and {extra} more (ask e.g. 'show water status' to filter, or 'how to fix')."
        return {"intent": intent, "text": text}
    if intent == "fix":
        return {"intent": intent, "text": _how_to_fix(report)}
    if intent == "why":
        return {"intent": intent, "text": _why_readiness(report)}
    if intent in ("water", "power", "pool", "stp", "fire", "gas"):
        st = {"water": ServiceType.WATER, "power": ServiceType.POWER_BACKUP, "pool": ServiceType.POOL,
              "stp": ServiceType.STP, "fire": ServiceType.FIRE, "gas": ServiceType.GAS}[intent]
        return {"intent": intent, "text": _service_line(report, st)}
    if intent == "help":
        return {"intent": intent, "text": (
            "I answer:\n• How is the building doing?\n• Any issues?\n• How to fix?\n• Why is readiness down?\n"
            "• What is this costing us?\n• Show water / power / gas / pool / STP / fire status\n• Create work order")}
    if intent == "create_work_order":
        return {"intent": intent, "text": "", "action": "create_work_order"}
    return {"intent": "unknown", "text": (
        "I didn't get that. Try: 'any issues?', 'how is the building?', 'why is readiness down?', "
        "or 'show water status'.")}


# ── Resident renderer ────────────────────────────────────────────────────
def _answer_resident(intent: str, text: str, report: CommunityReport,
                     assets, baselines) -> Dict[str, Any]:
    """Outcome-only voice. Residents never see asset names, %, kW, or confidence."""
    if intent == "create_work_order":
        return {"intent": intent, "text": "", "action": "create_work_order"}
    if intent == "help":
        return {"intent": intent, "text": (
            "Ask me:\n• Is water supply ok?\n• Is the pool open?\n• Is gas supply normal?\n"
            "• Is backup power ready?\n• Any issues?")}
    # For any query, produce the resident-friendly outcome summary.
    return {"intent": intent, "text": _resident_summary(report)}


def _resident_summary(report: CommunityReport) -> str:
    """Resident view: one line per service, plain outcome language, CRITICAL disruptions only."""
    lines = ["*Building Status*", ""]
    critical_services = {r.service for r in report.risks if r.severity == Severity.CRITICAL}
    for st, (ok_phrase, bad_phrase) in _RESIDENT_SERVICE.items():
        svc = next((s for s in report.services if s.service == st), None)
        if svc is None:
            continue
        if st in critical_services:
            lines.append(bad_phrase)
        else:
            lines.append(ok_phrase)
    # Only surface critical count — no noise for healthy buildings
    crits = [r for r in report.risks if r.severity == Severity.CRITICAL]
    lines.append("")
    if crits:
        lines.append(f"⚠️ {len(crits)} issue(s) being addressed. Building team has been notified.")
    else:
        lines.append("✅ All services operating normally.")
    return "\n".join(lines)


# ── Technician / FM renderer ──────────────────────────────────────────────
def _answer_tech(intent: str, text: str, report: CommunityReport,
                 assets, baselines) -> Dict[str, Any]:
    """Full operational detail: asset names, signal deviations, actions, confidence."""
    if intent == "status":
        return {"intent": intent, "text": _tech_digest(report)}
    if intent == "issues":
        if not report.risks:
            return {"intent": intent, "text": "✅ No active issues."}
        ranked = sorted(report.risks, key=_risk_rank)
        shown = ranked[:10]
        lines = [f"{_SEV_EMOJI.get(r.severity,'•')} [{r.asset_id}] {r.message}  [{r.confidence}]  → {r.detail or 'inspect on site'}"
                 for r in shown]
        body = f"*{len(report.risks)} issue(s)* (top {len(shown)}):\n" + "\n".join(lines)
        extra = len(report.risks) - len(shown)
        if extra > 0:
            body += f"\n…and {extra} more."
        return {"intent": intent, "text": body}
    if intent == "fix":
        return {"intent": intent, "text": _how_to_fix(report)}
    # for service-specific and other intents fall back to standard answer path
    return answer(text, report, assets, baselines, role="manager")


def _tech_digest(report: CommunityReport) -> str:
    """Technician digest: all services + worst risk per service + action."""
    L = ["*ARVIS Tech Summary*", "",
         f"{_BAND_EMOJI.get(report.readiness_band,'•')} Community Readiness: *{report.readiness:.0f}%*", ""]
    for s in report.services:
        band_e = _BAND_EMOJI.get(s.band.value, "•")
        L.append(f"{band_e} {OUTCOME_LABEL.get(s.service, s.service.value)} ({s.score:.0f}%)")
        svc_risks = sorted([r for r in report.risks if r.service == s.service], key=_risk_rank)
        for r in svc_risks[:2]:
            L.append(f"   {_SEV_EMOJI.get(r.severity,'•')} [{r.asset_id}] {r.message}  [{r.confidence}]")
            if r.detail:
                L.append(f"      → {r.detail}")
    n = len(report.risks)
    L.append("")
    L.append(f"{n} active issue(s). Reply 'issues' for full list." if n else "No active issues.")
    return "\n".join(L)


_SEV_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.MAINTENANCE: 2, Severity.INFO: 3}
_CONF_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _risk_rank(r):
    """Worst first: severity, then higher confidence, so the list a human reads first
    is the one that matters most."""
    return (_SEV_ORDER.get(r.severity, 9), _CONF_ORDER.get(r.confidence, 9))


def _how_to_fix(report: CommunityReport) -> str:
    """The top risks with their recommended actions (from the deterministic advisory
    detail) — 'what do I actually do?'"""
    if not report.risks:
        return "✅ Nothing to fix — all services nominal."
    ranked = sorted(report.risks, key=_risk_rank)[:5]
    lines = ["*What to do — top priorities:*", ""]
    for r in ranked:
        action = (r.detail or "Inspect on site.").strip()
        lines.append(f"{_SEV_EMOJI.get(r.severity, '•')} *{r.message}*  [{r.confidence}]")
        lines.append(f"   → {action}")
    lines.append("")
    lines.append("Reply 'create work order' to raise a ticket.")
    return "\n".join(lines)


def _why_readiness(report: CommunityReport) -> str:
    attention = [s for s in report.services if s.band.value != "Healthy"]
    if not attention:
        return f"✅ Community Readiness {report.readiness:.0f}% — everything is nominal."
    worst = min(attention, key=lambda s: s.score)
    rk = [r for r in report.risks if r.service == worst.service]
    cause = rk[0].message if rk else f"{worst.outcome} below normal"
    conf = rk[0].confidence if rk else "Medium"
    return (f"Community Readiness {report.readiness:.0f}% ({report.readiness_band}).\n\n"
            f"Primary contributor: *{worst.outcome}*\nReason: {cause}\nConfidence: {conf}")


# ── daily digest ─────────────────────────────────────────────────────────
def daily_digest(report: CommunityReport) -> str:
    L = [f"*ARVIS Daily Summary*", f"", f"{_BAND_EMOJI.get(report.readiness_band, '•')} "
         f"Community Readiness: *{report.readiness:.0f}%*", ""]
    for s in report.services:
        L.append(f"{_BAND_EMOJI.get(s.band.value, '•')} {OUTCOME_LABEL.get(s.service, s.service.value)}")
    n = len(report.risks)
    L.append("")
    L.append(f"{n} active issue(s)." if n else "No active issues.")
    return "\n".join(L)


# ── alert dispatch (anti-fatigue) ────────────────────────────────────────
# Push only actionable severities (Critical/Warning) — Maintenance/Info go in the daily
# digest, not as alerts. Confidence is SHOWN in the message (the recipient weights it),
# not used to suppress a real warning. Fatigue is controlled by severity + dedup +
# the learning-mode gate + signal-quality (no false alarms).
_PUSH_SEV = {Severity.CRITICAL, Severity.WARNING}


def _alert_signature(r) -> str:
    stem = re.sub(r"\d+(\.\d+)?", "#", r.message.replace(r.asset_name, "").lower())
    return f"{r.asset_id}::{re.sub(r'[^a-z# ]', '', stem).strip()}"


def format_alert(r, asset=None, baselines=None) -> str:
    impact = f"\nPotential impact: {r.detail}" if r.detail else ""
    money = ""
    try:
        from arvisx.economics import estimate, money_line
        ml = money_line(estimate(r, asset, baselines))
        money = f"\n{ml}" if ml else ""
    except Exception:
        pass
    return (f"{_SEV_EMOJI.get(r.severity, '🚨')} *{OUTCOME_LABEL.get(r.service, r.service.value)} Risk*\n\n"
            f"{r.message}\nConfidence: {r.confidence}{money}{impact}\n\nCreate work order? Reply: create work order")


def pending_alerts(report: CommunityReport, already_sent: Set[str],
                   assets: Optional[list] = None, baselines=None) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """New alerts to push: severity>=WARNING, not previously sent. Each enriched with a
    money line. Returns (alerts, updated_sent_set) — caller persists the set."""
    by_id = {a.asset_id: a for a in (assets or [])}
    out: List[Dict[str, Any]] = []
    sent = set(already_sent)
    for r in report.risks:
        if r.severity not in _PUSH_SEV:
            continue
        sig = _alert_signature(r)
        if sig in sent:
            continue
        sent.add(sig)
        out.append({"signature": sig, "severity": r.severity.value, "service": r.service.value,
                    "asset_id": r.asset_id, "text": format_alert(r, by_id.get(r.asset_id), baselines)})
    return out, sent
