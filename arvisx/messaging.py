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

import random
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
    ServiceType.ENERGY:       ("💡 Common areas normal",
                               "🚨 Common-area systems need attention — building team notified"),
}

# Resident intent → the service it asks about (for single-service resident answers).
_RESIDENT_INTENT_SVC: Dict[str, ServiceType] = {
    "water": ServiceType.WATER, "power": ServiceType.POWER_BACKUP, "pool": ServiceType.POOL,
    "stp": ServiceType.STP, "fire": ServiceType.FIRE, "gas": ServiceType.GAS,
}

# Full technician/FM voice (raw asset IDs, σ, signal detail). The OWNER is the
# community secretary, NOT a technician — they get the understandable manager voice
# (and keep work-order rights via the API's action gate, which is separate from voice).
_TECH_ROLES = {"technician", "fm"}
# roles that receive the manager/committee voice
_MGR_ROLES = {"manager", "committee", "owner"}


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
    if re.search(r"about (the|my|this) (building|community|place)"
                 r"|what (do|did|have|'?ve) (you|u) (know|knew|learn|learned|monitor)"
                 r"|what (are|r) (you|u) (monitoring|watching|tracking)|what devices|connected devices"
                 r"|tell me about (the|my|this)|what can (you|u) see", t):
        return "building"
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


def _service_line(report: CommunityReport, st: ServiceType, soften: bool = True) -> str:
    """One service's status. soften=True → manager phrasing; technician passes False
    for the raw precise message."""
    s = _svc(report, st)
    if s is None:
        return f"{OUTCOME_LABEL.get(st, st.value)}: not monitored"
    rk = [r for r in report.risks if r.service == st]
    head = f"{_BAND_EMOJI.get(s.band.value, '•')} {OUTCOME_LABEL.get(st, st.value)} — {s.band.value} ({s.score:.0f}%)"
    if rk:
        head += "\n" + "\n".join(
            f"   • {_manager_phrasing(r) if soften else r.message}  [{r.confidence}]" for r in rk[:3])
    return head


# ── the canned answers (deterministic) ───────────────────────────────────
def answer(text: str, report: CommunityReport, assets: Optional[list] = None,
           baselines=None, role: str = "viewer", phase: str = "operational") -> Dict[str, Any]:
    intent = route_intent(text)
    r = role.lower() if role else "viewer"
    if r == "resident":
        return _answer_resident(intent, text, report, assets, baselines, phase)
    if r in _TECH_ROLES:
        return _answer_tech(intent, text, report, assets, baselines, phase)
    # manager / committee / viewer / owner fallthrough → standard voice (softened phrasing)
    if intent == "building":
        return {"intent": intent, "text": _building_summary(report, assets, baselines, phase, "manager")}
    if intent == "status":
        return {"intent": intent, "text": daily_digest(report)}
    if intent == "cost":
        from arvisx.economics import community_cost_message
        return {"intent": intent, "text": community_cost_message(report, assets or [], baselines)}
    if intent == "issues":
        return {"intent": intent, "text": _issues_text(report, tech=False)}
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
                     assets, baselines, phase: str = "operational") -> Dict[str, Any]:
    """Outcome-only voice. Residents never see asset names, %, kW, or confidence."""
    if intent == "building":
        return {"intent": intent, "text": _building_summary(report, assets, baselines, phase, "resident")}
    if intent == "create_work_order":
        # Resident maintenance request: hand the caller (API) the action to RECORD it.
        # The caller fills in the confirmation text only after the save succeeds —
        # never claim 'noted' for something that wasn't.
        return {"intent": intent, "text": "", "action": "resident_request",
                "request_text": (text or "").strip()}
    if intent == "help":
        return {"intent": intent, "text": (
            "Ask me:\n• Is water supply ok?\n• Is the pool open?\n• Is gas supply normal?\n"
            "• Is backup power ready?\n• Any issues?")}
    # Single-service question ("is the pool open?") → just that service's line.
    if intent in _RESIDENT_INTENT_SVC:
        return {"intent": intent,
                "text": _resident_service_line(report, _RESIDENT_INTENT_SVC[intent])}
    # Anything else → the whole-building outcome summary.
    return {"intent": intent, "text": _resident_summary(report)}


def _resident_service_line(report: CommunityReport, st: ServiceType) -> str:
    """One service, resident voice. CRITICAL → disruption phrase; otherwise normal."""
    pair = _RESIDENT_SERVICE.get(st)
    if pair is None:
        return "That service isn't monitored here."
    ok_phrase, bad_phrase = pair
    if any(r.service == st and r.severity == Severity.CRITICAL for r in report.risks):
        return bad_phrase
    return ok_phrase


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
                 assets, baselines, phase: str = "operational") -> Dict[str, Any]:
    """Full operational detail: asset names, signal deviations, actions, confidence."""
    if intent == "building":
        return {"intent": intent, "text": _building_summary(report, assets, baselines, phase, "tech")}
    if intent == "status":
        return {"intent": intent, "text": _tech_digest(report)}
    if intent == "issues":
        return {"intent": intent, "text": _issues_text(report, tech=True)}
    if intent == "fix":
        return {"intent": intent, "text": _how_to_fix(report, soften=False)}
    if intent in _RESIDENT_INTENT_SVC:   # same intent→service map; raw voice here
        return {"intent": intent,
                "text": _service_line(report, _RESIDENT_INTENT_SVC[intent], soften=False)}
    # for the remaining intents (cost / why / help / wo / unknown) use the standard path
    return answer(text, report, assets, baselines, role="manager", phase=phase)


def _tech_digest(report: CommunityReport) -> str:
    """Ops digest — clean overview, NOT a wall of risks. Service tiles + a one-line
    worst-issue teaser; detail lives in 'issues' / 'fix' so the digest stays scannable."""
    L = [_vary(_TECH_HEADERS), "", _readiness_headline(report), ""]
    L += _service_tiles(report)
    n = len(report.risks)
    L.append("")
    if n:
        worst = sorted(report.risks, key=_risk_rank)[0]
        L.append(f"📋 {n} active issue(s). Top: {worst.message}")
        L.append("Reply *issues* for the list · *fix* for what to do.")
    else:
        L.append("✅ No active issues.")
    return "\n".join(L)


# ── Manager phrasing (plain-language reword of technician risk text) ───────
# DETERMINISTIC reword, NOT paraphrase: each rule maps a known detector phrase to a
# plain-operational sentence (asset name preserved). It never invents — unmatched
# messages fall through with only the math noise (Nσ, % duty, kW, key=value) stripped,
# so a manager sees "working harder than usual" instead of "power creep (3.2σ above its
# own normal)", while the technician tier keeps the raw text. Source of truth for the
# phrasing seam if it later moves onto Risk itself.
_MGR_RULES: List[Tuple[str, str]] = [
    (r"short-?cycling",                 "{name} is switching on and off too often — extra wear, worth a check"),
    (r"power creep|drawing more power", "{name} is working harder than usual — worth an inspection"),
    (r"running near-continuously|duty", "{name} is running almost non-stop — may be undersized or a leak"),
    (r"drifting from its learned normal","{name} readings are drifting from their usual pattern"),
    (r"filtration runtime below normal","{name} is filtering less than usual — pool water quality at risk"),
    (r"offline — no operational signal","{name} has stopped reporting — we've lost its signal"),
    (r"runtime above threshold",        "{name} is past its service hours — schedule maintenance"),
]
# Math/jargon parentheticals to strip from any unmatched message.
_MGR_NOISE = re.compile(r"\s*\([^)]*(?:σ|sigma|% duty|starts/h|kW|=)[^)]*\)")


def _manager_phrasing(r) -> str:
    """Plain-language version of a risk message for the manager/committee tier."""
    msg = r.message or ""
    for pat, template in _MGR_RULES:
        if re.search(pat, msg, re.IGNORECASE):
            return template.format(name=r.asset_name)
    return _MGR_NOISE.sub("", msg).strip()


_SEV_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.MAINTENANCE: 2, Severity.INFO: 3}
_CONF_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _risk_rank(r):
    """Worst first: severity, then higher confidence, so the list a human reads first
    is the one that matters most."""
    return (_SEV_ORDER.get(r.severity, 9), _CONF_ORDER.get(r.confidence, 9))


def _how_to_fix(report: CommunityReport, soften: bool = True) -> str:
    """The top risks with their recommended actions (from the deterministic advisory
    detail) — 'what do I actually do?'. soften=True → manager phrasing; the technician
    tier passes soften=False to keep the raw precise message."""
    if not report.risks:
        return "✅ Nothing to fix — all services nominal."
    ranked = sorted(report.risks, key=_risk_rank)[:5]
    cards = []
    for r in ranked:
        action = (r.detail or "Inspect on site.").strip()
        msg = _manager_phrasing(r) if soften else r.message
        cards.append(f"{_SEV_EMOJI.get(r.severity, '•')} *{msg}*  [{r.confidence}]\n   → {action}")
    return "*What to do — top priorities:*\n\n" + "\n\n".join(cards) + \
           "\n\nReply *create work order* to log one."


def _why_readiness(report: CommunityReport) -> str:
    attention = [s for s in report.services if s.band.value != "Healthy"]
    if not attention:
        return f"✅ Community Readiness {report.readiness:.0f}% — everything is nominal."
    worst = min(attention, key=lambda s: s.score)
    rk = [r for r in report.risks if r.service == worst.service]
    cause = _manager_phrasing(rk[0]) if rk else f"{worst.outcome} below normal"
    conf = rk[0].confidence if rk else "Medium"
    return (f"Community Readiness {report.readiness:.0f}% ({report.readiness_band}).\n\n"
            f"Primary contributor: *{worst.outcome}*\nReason: {cause}\nConfidence: {conf}")


# ── outbound phrasing variants (anti-spam-pattern) ───────────────────────
# WhatsApp's automation detection flags REPEATED IDENTICAL outbound text. Every
# PUSHED surface (digest, alerts, checklist prompts, resident pings) varies its
# wrapper phrasing per send. DETERMINISTIC-safe: variants are hand-written, the
# facts (numbers, names, refs) are interpolated unchanged, and machine-parsed
# reply keywords ('create work order', 'ok <item_id>') stay verbatim in every
# variant. Q&A replies (responses to a user message) are NOT varied — replies
# don't pattern-match as broadcast spam, and tests pin their exact text.
_DIGEST_HEADERS = ("*ARVIS Daily Summary*", "*ARVIS Morning Brief*",
                   "*Daily Building Report*", "*ARVIS Daily Status*")
_TECH_HEADERS = ("*ARVIS Ops Brief*", "*ARVIS Status*", "*Building Status — ops*",
                 "*ARVIS Tech Summary*")
_DIGEST_FOOT_OK = ("No active issues.", "All clear — no active issues.",
                   "Nothing needs attention today.", "No issues on the board.")
_DIGEST_FOOT_N = ("{n} active issue(s).", "{n} issue(s) on the board.",
                  "{n} item(s) need attention.", "Tracking {n} active issue(s).")
_ALERT_HEAD = ("*{label} Risk*", "*{label} Alert*", "*{label} — attention needed*")
_ALERT_CTA = ("Create work order? Reply: create work order",
              "Raise a ticket? Reply: create work order",
              "Reply 'create work order' to log this.",
              "To raise a ticket, reply: create work order")
_RESIDENT_PUSH_SUFFIX = ("", " Updates to follow.", " We'll keep you posted.",
                         " More information as we have it.")


def _vary(options) -> str:
    return random.choice(options)


# ── "what do you know about my building?" — situation-aware ───────────────
def _assets_by_service(assets) -> "Dict[ServiceType, list]":
    by: Dict[ServiceType, list] = {}
    for a in (assets or []):
        try:
            by.setdefault(a.service, []).append(a)
        except Exception:
            continue
    return by


def _building_summary(report: CommunityReport, assets, baselines,
                      phase: str, tier: str) -> str:
    """What ArvisX knows about this building — different in LEARNING vs OPERATIONAL,
    and in each voice tier. Learning → what's connected + that it's still learning.
    Operational → that it has learned each device's normal and is watching live."""
    learning = (phase or "operational").lower() != "operational"
    by = _assets_by_service(assets)
    n_dev = sum(len(v) for v in by.values())
    n_svc = len(by)
    svc_names = [OUTCOME_LABEL.get(s, s.value) for s in by]

    # ---- Resident: outcome language, no counts-as-jargon, no asset IDs ----
    if tier == "resident":
        services_phrase = _friendly_list([_short_service(s) for s in by]) or "the building's core services"
        if learning:
            return ("*Getting to know your building*\n\n"
                    f"I'm still learning what's normal here — I'm connected to {services_phrase}.\n\n"
                    "Once I've learned the usual pattern (a few more days), I'll start letting you "
                    "know if anything needs attention. For now, ask me 'is water ok?' or 'is the pool open?'")
        return ("*About your building*\n\n"
                f"I've learned what's normal across {services_phrase}, and I'm watching them around the "
                "clock. If something looks off, I'll tell you — otherwise no news is good news.\n\n"
                "Ask me 'any issues?' anytime.")

    # ---- Manager / owner: friendly but with useful counts ----
    if tier == "manager":
        lines = ["*About your building*", ""]
        if learning:
            lines.append(f"I'm still learning — connected to *{n_dev} devices* across *{n_svc} services*:")
            for s in by:
                lines.append(f"   • {OUTCOME_LABEL.get(s, s.value)}: {len(by[s])} device(s)")
            lines += ["", "I'm watching them build up a picture of what's normal. Alerts switch on "
                          "once the baseline is ready — until then I won't cry wolf."]
            return "\n".join(lines)
        tracked, learned = _baseline_counts(baselines)
        lines.append(_readiness_headline(report))
        lines.append("")
        lines.append(f"I'm watching *{n_dev} devices* across *{n_svc} services* "
                     f"({', '.join(svc_names)}).")
        if learned:
            lines.append(f"I've learned the normal pattern for *{learned} readings* and I compare every "
                         "live reading against each device's own baseline.")
        lines.append("")
        lines.append("Ask 'any issues?' for the current picture, or 'what is this costing us?'.")
        return "\n".join(lines)

    # ---- Technician / FM: asset inventory + baseline coverage ----
    lines = ["*Building — monitoring inventory*", ""]
    lines.append(_readiness_headline(report))
    lines.append("")
    for s in by:
        ids = ", ".join(a.asset_id for a in by[s])
        lines.append(f"{_BAND_EMOJI.get('Healthy','•')} {OUTCOME_LABEL.get(s, s.value)}: {ids}")
    tracked, learned = _baseline_counts(baselines)
    lines.append("")
    if learning:
        lines.append(f"State: *LEARNING* — {tracked} signals tracked, {learned} with a usable baseline. "
                     "Drift alerts arm at operational.")
    else:
        lines.append(f"State: *OPERATIONAL* — {learned}/{tracked} signals have a learned baseline; "
                     "drift is judged per-asset against it.")
    return "\n".join(lines)


def _short_service(st: ServiceType) -> str:
    return {ServiceType.WATER: "water", ServiceType.POWER_BACKUP: "backup power",
            ServiceType.POOL: "the pool", ServiceType.STP: "the sewage plant",
            ServiceType.FIRE: "fire systems", ServiceType.GAS: "cooking gas",
            ServiceType.ENERGY: "common-area energy"}.get(st, st.value)


def _friendly_list(items) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _baseline_counts(baselines) -> "Tuple[int, int]":
    """(signals tracked, signals with a usable learned baseline)."""
    if baselines is None:
        return 0, 0
    try:
        return baselines.learned_summary()
    except Exception:
        return 0, 0


# ── shared rendering helpers (clean visual hierarchy) ────────────────────
def _readiness_headline(report: CommunityReport) -> str:
    tag = {"Healthy": "all good", "Attention Required": "needs attention",
           "Critical": "action needed"}.get(report.readiness_band, "")
    e = _BAND_EMOJI.get(report.readiness_band, "•")
    dash = f" — {tag}" if tag else ""
    return f"{e} Community Readiness: *{report.readiness:.0f}%*{dash}"


def _service_tiles(report: CommunityReport) -> List[str]:
    """One clean line per service — the reassuring at-a-glance grid."""
    return [f"{_BAND_EMOJI.get(s.band.value, '•')} {OUTCOME_LABEL.get(s.service, s.service.value)}"
            for s in report.services]


def _issues_text(report: CommunityReport, tech: bool) -> str:
    """Worst-first issues as clean cards: a title line, the action below, asset tag
    last (tech only). tech=raw message, else softened plain language."""
    if not report.risks:
        return "✅ No active issues. All services nominal."
    ranked = sorted(report.risks, key=_risk_rank)
    shown = ranked[:10]
    cards = []
    for r in shown:
        title = r.message if tech else _manager_phrasing(r)
        seg = [f"{_SEV_EMOJI.get(r.severity, '•')} {title}  [{r.confidence}]"]
        if r.detail:
            seg.append(f"   → {r.detail.strip()}")
        if tech and r.asset_id:
            seg.append(f"   ({r.asset_id})")
        cards.append("\n".join(seg))
    # header, then the worst card immediately (keeps it on line 2), blank between cards
    text = f"*{len(report.risks)} active issue(s)* (worst first):\n" + "\n\n".join(cards)
    extra = len(report.risks) - len(shown)
    if extra > 0:
        text += f"\n\n…and {extra} more."
    text += "\n\nReply *fix* for what to do · *create work order* to log one."
    return text


# ── daily digest ─────────────────────────────────────────────────────────
def daily_digest(report: CommunityReport) -> str:
    L = [_vary(_DIGEST_HEADERS), "", _readiness_headline(report), ""]
    L += _service_tiles(report)
    n = len(report.risks)
    L.append("")
    if n:
        L.append(f"📋 {_vary(_DIGEST_FOOT_N).format(n=n)} Reply *issues* for detail.")
    else:
        L.append(f"✅ {_vary(_DIGEST_FOOT_OK)}")
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
    """Clean ops alert card: title, what's wrong, the action, the money, a small
    confidence tag, then the CTA — one item per line, no duplicated 'impact' block."""
    head = _vary(_ALERT_HEAD).format(label=OUTCOME_LABEL.get(r.service, r.service.value))
    lines = [f"{_SEV_EMOJI.get(r.severity, '🚨')} {head}", "", r.message]
    if r.detail:
        lines.append(f"→ {r.detail.strip()}")
    try:
        from arvisx.economics import estimate, money_line
        ml = money_line(estimate(r, asset, baselines))
        if ml:
            lines.append(ml)
    except Exception:
        pass
    lines.append(f"Confidence: {r.confidence}")
    lines.append("")
    lines.append(_vary(_ALERT_CTA))
    return "\n".join(lines)


def format_alert_resident(r) -> str:
    """Resident-voiced push. ONLY a CRITICAL service disruption is worth a resident's
    attention — returns the plain disruption phrase, or '' for anything lower (residents
    don't get maintenance/warning noise pushed at them)."""
    if r.severity != Severity.CRITICAL:
        return ""
    pair = _RESIDENT_SERVICE.get(r.service)
    return (pair[1] + _vary(_RESIDENT_PUSH_SUFFIX)) if pair else ""


def pending_alerts(report: CommunityReport, already_sent: Set[str],
                   assets: Optional[list] = None, baselines=None) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """New alerts to push: severity>=WARNING, not previously sent. Each enriched with a
    money line (technician/manager voice) AND a resident-voiced variant (CRITICAL only,
    else ''). The bot picks per recipient tier. Returns (alerts, updated_sent_set).

    Resident dedup is per SERVICE, not per risk: the resident phrase is the same fixed
    disruption line, so three critical water risks must not ping a resident group three
    times. Tracked as 'resident::<service>' in the same persisted sent-set."""
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
        resident_text = format_alert_resident(r)
        if resident_text:
            rsig = f"resident::{r.service.value}"
            if rsig in sent:
                resident_text = ""          # this service's disruption already pushed
            else:
                sent.add(rsig)
        out.append({"signature": sig, "severity": r.severity.value, "service": r.service.value,
                    "asset_id": r.asset_id, "text": format_alert(r, by_id.get(r.asset_id), baselines),
                    "resident_text": resident_text})
    return out, sent
