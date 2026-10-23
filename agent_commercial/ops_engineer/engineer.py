"""
One conversational turn of ARVIS-the-engineer.

    person + message
      → context: who they are, the thread so far, live building facts (role agents),
                 open field checks, what ARVIS already told them, the local time
      → reasoning with tools (equipment status, trends, open cases, building overview,
                 a deep investigation in the background, asking a technician, recording a repair)
      → guards: every number must come from the data; no repeating itself
      → reply, in WhatsApp style, in the person's language

If the language model is unavailable ARVIS says so plainly and still gives the
facts its engines have — it never goes silent and never improvises.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set

from agent_commercial.ops_engineer.memory import ConversationStore
from agent_commercial.ops_engineer.people import People, Person

logger = logging.getLogger("arvis.ops.engineer")

MAX_TOOL_CHARS = 4000

_ROLE_GUIDE = {
    "owner": "the building owner/asset manager: talk outcomes, cost and risk in plain words; spare them alarm detail",
    "fm": "the facilities manager / chief engineer who runs operations: technical, concise, decision-oriented",
    "technician": "an on-site technician: precise and practical — what to look at, where, what to report back",
}

_TOOLS = [
    {"name": "building_overview",
     "description": "What ARVIS's engines currently know: confirmed faults (with cost), active alarms, "
                    "unreliable sensors, open diagnoses with likely causes, repairs awaiting re-check, "
                    "learned history, and the most useful next checks. Optionally focused on one unit.",
     "parameters": {"type": "object", "properties": {"equipment_id": {"type": "string"}}}},
    {"name": "equipment_status",
     "description": "Live status and current point readings of one piece of equipment (e.g. AHU-07).",
     "parameters": {"type": "object", "properties": {"equipment_id": {"type": "string"}},
                    "required": ["equipment_id"]}},
    {"name": "point_history",
     "description": "Recent trend of one point (e.g. AHU-07/SAT): first/last/min/max over the window.",
     "parameters": {"type": "object", "properties": {"point_id": {"type": "string"},
                                                     "minutes": {"type": "integer"}},
                    "required": ["point_id"]}},
    {"name": "change_since",
     "description": "Did an action help? How one point (e.g. AHU-07/SAT or L3-ZONE-W/TEMP) changed since a "
                    "moment — a reset, a repair, a setpoint change. Give when it happened (minutes_ago, or "
                    "at='HH:MM' local) and, if known, the target/normal value (e.g. the setpoint from "
                    "equipment_status). Returns value before vs now, direction, and when it reached the target "
                    "and how many minutes that took.",
     "parameters": {"type": "object", "properties": {"point_id": {"type": "string"},
                                                     "minutes_ago": {"type": "integer"},
                                                     "at": {"type": "string", "description": "HH:MM local"},
                                                     "target": {"type": "number"},
                                                     "band": {"type": "number", "description": "tolerance around target"}},
                    "required": ["point_id"]}},
    {"name": "alarm_changes",
     "description": "Alarms on one equipment since a moment: which cleared (and how long after), which are still "
                    "active, which are new. Use with change_since to answer 'did the reset help?'.",
     "parameters": {"type": "object", "properties": {"equipment_id": {"type": "string"},
                                                     "minutes_ago": {"type": "integer"},
                                                     "at": {"type": "string", "description": "HH:MM local"}},
                    "required": ["equipment_id"]}},
    {"name": "acknowledge",
     "description": "The person says they (or someone) are on an alert you sent — record it so you stop "
                    "chasing and escalating. Optionally name the equipment it was about.",
     "parameters": {"type": "object", "properties": {"subject": {"type": "string"}}}},
    {"name": "explain",
     "description": "Why you did or did not message about something (e.g. 'why didn't you tell me about "
                    "AHU-07?'): your recorded decisions and their reasons.",
     "parameters": {"type": "object", "properties": {"subject": {"type": "string"}}, "required": ["subject"]}},
    {"name": "open_cases",
     "description": "Open diagnosis cases: ranked likely causes and the question that would settle them.",
     "parameters": {"type": "object", "properties": {"equipment_id": {"type": "string"}}}},
    {"name": "deep_investigation",
     "description": "Start a full multi-agent root-cause investigation in the background (takes minutes). "
                    "Use for 'why' questions that need cross-system reasoning. The result is sent to "
                    "the person automatically when it is ready.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "ask_technician",
     "description": "Send a technician the single most useful check for an equipment's open diagnosis. "
                    "Only the facilities manager or owner can ask this.",
     "parameters": {"type": "object", "properties": {"technician": {"type": "string", "description": "name"},
                                                     "equipment_id": {"type": "string"}},
                    "required": ["technician", "equipment_id"]}},
    {"name": "record_repair",
     "description": "Record that a repair was done on an equipment's open fault, so ARVIS re-checks it "
                    "after enough running time and confirms whether it worked.",
     "parameters": {"type": "object", "properties": {"equipment_id": {"type": "string"},
                                                     "rule_id": {"type": "string"},
                                                     "what_was_done": {"type": "string"}},
                    "required": ["equipment_id"]}},
]

_NUM = re.compile(r"(?<![A-Za-z0-9_\-/.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![A-Za-z0-9_\-])")


def _numbers(text: str) -> List[float]:
    out = []
    for m in _NUM.finditer(text or ""):
        whole = m.group(1).replace(",", "")
        out.append(float(f"{whole}.{m.group(2)}" if m.group(2) else whole))
    return out


def ungrounded_numbers(reply: str, sources: Iterable[str], free_below: float = 10.0) -> List[float]:
    """Numbers in the reply that appear nowhere in the data it was given.
    Allows rounding (2 %), probabilities written as percentages, and small counts."""
    src: Set[float] = set()
    for s in sources:
        for x in _numbers(s):
            src.add(x)
            if 0 < x <= 1:
                src.add(round(x * 100))
                src.add(round(x * 100, 1))
    bad = []
    for r in _numbers(reply):
        if r <= free_below:
            continue
        if not any(abs(r - s) <= max(0.5, 0.02 * abs(s)) for s in src):
            bad.append(r)
    return bad


def _aware(ts: Any) -> Optional[datetime]:
    """Any timestamp → timezone-aware. Naive values come from this process's own
    clock (datetime.now()), so they are local to the server, whatever that is."""
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(ts, datetime):
        return None
    return ts if ts.tzinfo is not None else ts.astimezone()


def _hhmm(dt: datetime, tz: Any) -> str:
    return dt.astimezone(tz).strftime("%H:%M") if tz else dt.strftime("%H:%M")


def analyze_change(samples: List[tuple], since: datetime, *, target: Optional[float] = None,
                   band: Optional[float] = None, before_minutes: float = 30.0, tz: Any = None) -> Dict[str, Any]:
    """What happened to a signal after a moment, from its samples [(aware datetime, value)].

    before    mean over the `before_minutes` before the moment (else the last value before it)
    now       the latest value
    target    when given: did it move toward it, when did it first get within `band`,
              how many minutes after the moment, and is it still within band now
    Nothing is extrapolated: with no readings after the moment, it says so.
    """
    pts = sorted((t, float(v)) for t, v in samples if t is not None and isinstance(v, (int, float)))
    pre = [(t, v) for t, v in pts if t < since]
    post = [(t, v) for t, v in pts if t >= since]
    out: Dict[str, Any] = {"action_at": _hhmm(since, tz), "readings_before": len(pre), "readings_after": len(post)}
    if not post:
        out["note"] = "no readings since that moment — cannot tell yet"
        return out
    window = [v for t, v in pre if (since - t).total_seconds() <= before_minutes * 60]
    before = (sum(window) / len(window)) if window else (pre[-1][1] if pre else None)
    now_t, now_v = post[-1]
    lo = min(post, key=lambda p: p[1])
    hi = max(post, key=lambda p: p[1])
    out.update({
        "before": None if before is None else round(before, 2),
        "now": round(now_v, 2), "now_at": _hhmm(now_t, tz),
        "minutes_observed_after": round((now_t - since).total_seconds() / 60),
        "after_min": round(lo[1], 2), "after_min_at": _hhmm(lo[0], tz),
        "after_max": round(hi[1], 2), "after_max_at": _hhmm(hi[0], tz),
    })
    if before is not None:
        change = now_v - before
        out["change"] = round(change, 2)
        out["direction"] = "flat" if abs(change) < 1e-6 or (abs(change) <= 0.01 * max(abs(before), 1.0)) \
            else ("up" if change > 0 else "down")
    if target is not None:
        tol = float(band) if band is not None else max(0.5, 0.02 * abs(float(target)))
        out.update({"target": target, "band": round(tol, 2)})
        if before is not None:
            out["moved_toward_target"] = abs(now_v - target) < abs(before - target)
        tol += 1e-9                                  # 24.3 − 24.0 is 0.3000000000000007 in floating point
        reached = next(((t, v) for t, v in post if abs(v - target) <= tol), None)
        if reached:
            out["reached_target_at"] = _hhmm(reached[0], tz)
            out["minutes_to_target"] = round((reached[0] - since).total_seconds() / 60)
        else:
            out["reached_target"] = False
        out["within_target_now"] = abs(now_v - target) <= tol
    return out


def _too_similar(a: str, b: str) -> bool:
    return bool(a and b) and difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.9


class OpsEngineer:
    def __init__(self, *, llm: Any, people: People, store: ConversationStore, database: Any,
                 roles: Any = None, tool_handler: Any = None, field_checks: Any = None,
                 investigate: Optional[Callable[[str, Person], Awaitable[str]]] = None,
                 notify: Optional[Callable[[Person, str, str], Awaitable[None]]] = None,
                 building_name: Optional[str] = None, max_rounds: int = 4):
        self.llm = llm
        self.people = people
        self.store = store
        self.database = database
        self.roles = roles
        self.tool_handler = tool_handler
        self.field_checks = field_checks
        self.investigate = investigate
        self.notify = notify
        self.building_name = building_name or os.getenv("ARVIS_BUILDING_NAME", "the building")
        self.max_rounds = max_rounds
        self._tasks: Set[asyncio.Task] = set()
        self.gate = None          # AttentionGate (alerts, held items, decision log), when proactive messaging is on
        self.calendar = None      # BuildingCalendar

    # ── context ───────────────────────────────────────────────────────────
    @staticmethod
    def _local_now() -> datetime:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(os.getenv("ARVIS_TZ", "Asia/Qatar")))
        except Exception:
            return datetime.now().astimezone()          # always timezone-aware

    async def _facts(self, person: Person, focus_text: str) -> str:
        lines = [f"Local time: {self.calendar.describe() if self.calendar else f'{self._local_now():%A %d %B %Y, %H:%M}'}"]
        if self.gate is not None:
            try:
                alerts = await self.gate.ledger.open_alerts(person.number)
                if alerts:
                    lines.append("Alerts you sent them that nobody has acknowledged yet: " +
                                 "; ".join(a["title"] for a in alerts[:5]))
                held = await self.gate.ledger.pending_for(person.number)
                if held:
                    lines.append(f"Held for them (next brief / later today): " +
                                 "; ".join(f"{i.title} [{i.level}]" for i in held[:6]))
            except Exception as e:
                logger.warning(f"[Ops] attention context unavailable: {e}")
        if self.roles is not None:
            try:
                dossier = await self.roles.before_investigation(focus_text, {}, None)
                lines.append(dossier["prompt"])
            except Exception as e:
                logger.warning(f"[Ops] building facts unavailable: {e}")
                lines.append("Building facts: unavailable right now (engine error).")
        if self.field_checks is not None:
            try:
                pending = [c for c in await self.field_checks.list_checks("sent")]
                if pending:
                    lines.append("Checks waiting on technicians: " + "; ".join(
                        f"{c.ref} {c.equipment_id} → {c.technician_name}: {c.question}" for c in pending[:6]))
            except Exception as e:
                logger.warning(f"[Ops] field checks unavailable: {e}")
        told = await self.store.notices_since(person.number, 24)
        if told:
            lines.append("Already told this person in the last 24 h: " + "; ".join(t["summary"] for t in told[-6:]))
        return "\n".join(lines)

    def _system(self, person: Person, facts: str) -> str:
        return (
            f"You are ARVIS, the operations engineer for {self.building_name}, talking on WhatsApp with "
            f"{person.name} — {_ROLE_GUIDE.get(person.role, _ROLE_GUIDE['fm'])}.\n"
            "You are a colleague, not a bot: talk naturally, like a senior engineer messaging a teammate. "
            "Short WhatsApp messages (usually 2-6 lines). No menus, no numbered option lists, no headings, "
            "no markdown tables. Reply in the language they write in (Arabic if they write Arabic).\n"
            "GROUND RULES:\n"
            "- Every reading, number, cost, percentage or time you state must come from BUILDING FACTS or a tool "
            "result in this conversation. If you don't have it, say so or look it up with a tool. Never guess.\n"
            "- Never invent equipment, causes or events. Likely causes come from the diagnosis, with their probability.\n"
            "- ARVIS is read-only: you cannot change setpoints or operate equipment. If asked, say who should and what to check.\n"
            "- For a 'why' that needs cross-system reasoning, call deep_investigation and tell them you're on it.\n"
            "- To settle a diagnosis from site, use ask_technician. When someone reports a repair done, use record_repair.\n"
            "- If they say they're on an alert you sent ('on it', 'handling it'), call acknowledge. If they ask why "
            "you did or didn't tell them about something, call explain and give the real reasons.\n"
            "- 'Did the reset/fix/change help?': find out when it happened (ask if they didn't say), then use "
            "change_since on the affected points (with the setpoint as target when you know it) and alarm_changes "
            "on the equipment. Report what actually happened, with the times and minutes the tools give you.\n"
            "- Do not repeat what you already said in this conversation; answer the new message.\n"
            "- If you're unsure, say what you'd check next — that's what a good engineer does.\n\n"
            f"BUILDING FACTS (from ARVIS's engines, just now):\n{facts}"
        )

    # ── a turn ────────────────────────────────────────────────────────────
    async def respond(self, person: Person, text: str) -> str:
        history = await self.store.recent(person.number, limit=12)
        focus = " ".join([t.text for t in history[-4:]] + [text])
        facts = await self._facts(person, focus)
        system = self._system(person, facts)
        messages: List[Dict[str, Any]] = [
            {"role": "user" if t.speaker == "person" else "assistant", "content": t.text} for t in history]
        if not messages or messages[-1]["content"] != text or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": text})
        sources = [facts, text] + [t.text for t in history]
        last_own = next((t.text for t in reversed(history) if t.speaker == "arvis"), "")

        try:
            reply, tool_outputs = await self._reason(person, system, messages)
            sources += tool_outputs
            problem = self._problem(reply, sources, last_own)
            if problem:
                messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": problem}]
                reply, more = await self._reason(person, system, messages)
                sources += more
                if self._problem(reply, sources, last_own):
                    reply = self._drop_ungrounded(reply, sources) or self._facts_only(facts)
        except Exception as e:
            logger.error(f"[Ops] reasoning failed for {person.name}: {type(e).__name__}: {e}")
            return ("I can't reach my reasoning engine right now, so I'll stick to what monitoring shows:\n"
                    + self._facts_only(facts))
        return reply.strip()

    def _problem(self, reply: str, sources: List[str], last_own: str) -> Optional[str]:
        if not reply.strip():
            return "You returned nothing. Answer the message."
        bad = ungrounded_numbers(reply, sources)
        if bad:
            return ("CHECK: these numbers are not in your data: " + ", ".join(f"{b:g}" for b in bad)
                    + ". Rewrite using only figures from the facts or tool results, or look them up.")
        if _too_similar(reply, last_own):
            return "CHECK: that repeats your previous message. Answer the new message instead."
        return None

    @staticmethod
    def _drop_ungrounded(reply: str, sources: List[str]) -> str:
        keep = [s for s in re.split(r"(?<=[.!?\n])\s+", reply) if not ungrounded_numbers(s, sources)]
        return " ".join(keep).strip()

    @staticmethod
    def _facts_only(facts: str) -> str:
        lines = [ln for ln in facts.splitlines() if ln.startswith(("[Anomaly", "[Recommendation", "  - "))]
        return "\n".join(lines[:8]) or "No confirmed faults or open issues on record right now."

    async def _reason(self, person: Person, system: str, messages: List[Dict[str, Any]]):
        tools = [{"type": "function", "function": t} for t in _TOOLS]
        outputs: List[str] = []
        msgs = list(messages)
        for _ in range(self.max_rounds):
            resp = await self.llm.ask_tool(messages=msgs, system_msgs=[{"role": "system", "content": system}],
                                           tools=tools, tool_choice="auto", channel="chat")
            calls = [tc for tc in (getattr(resp, "tool_calls", None) or [])
                     if getattr(tc.function, "name", "") and getattr(tc, "id", "")]
            if not calls:
                return (getattr(resp, "content", "") or ""), outputs
            raw = resp.model_dump().get("tool_calls") or []
            msgs.append({"role": "assistant", "content": resp.content,
                         "tool_calls": [c for c in raw if c.get("id") in {tc.id for tc in calls}]})
            for tc in calls:
                try:
                    args = json.loads(tc.function.arguments or "{}") if isinstance(tc.function.arguments, str) \
                        else (tc.function.arguments or {})
                except ValueError:
                    args = {}
                out = await self._run_tool(person, tc.function.name, args)
                outputs.append(out)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": out})
        # Out of rounds: one last answer without tools.
        resp = await self.llm.ask(messages=msgs, system_msgs=[{"role": "system", "content": system}],
                                  tools=tools, channel="chat")
        return (getattr(resp, "content", "") or ""), outputs

    # ── tools ─────────────────────────────────────────────────────────────
    async def _run_tool(self, person: Person, name: str, args: Dict[str, Any]) -> str:
        try:
            result = await getattr(self, f"_tool_{name}")(person, **args)
        except AttributeError:
            result = {"error": f"unknown tool {name}"}
        except TypeError as e:
            result = {"error": f"bad arguments for {name}: {e}"}
        except Exception as e:
            logger.warning(f"[Ops] tool {name} failed: {e}")
            result = {"error": f"{name} failed: {type(e).__name__}"}
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        return text[:MAX_TOOL_CHARS]

    async def _tool_building_overview(self, person: Person, equipment_id: str = "") -> str:
        if self.roles is None:
            return "building overview unavailable"
        return (await self.roles.before_investigation(equipment_id or "", {}, None))["prompt"]

    async def _tool_equipment_status(self, person: Person, equipment_id: str) -> Any:
        if self.tool_handler is None:
            return {"error": "live equipment data unavailable"}
        return await self.tool_handler.execute("get_equipment_status", {"equipment_id": equipment_id})

    def _tz(self):
        return self._local_now().tzinfo

    async def _samples(self, point_id: str, minutes: int) -> tuple:
        """[(aware datetime, value)] for a point, oldest first, plus any note."""
        res = await self.tool_handler.execute("get_point_history", {"point_id": point_id, "minutes": int(minutes)})
        pts = []
        for d in (res.get("data") or []):
            t, v = _aware(d.get("timestamp")), d.get("value")
            if t is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
                pts.append((t, float(v)))
        pts.sort()
        return pts, (res.get("note") or res.get("error"))

    def _resolve_since(self, minutes_ago: Optional[int], at: Optional[str], ref_now: datetime) -> Optional[datetime]:
        from datetime import timedelta
        if minutes_ago is not None:
            return ref_now - timedelta(minutes=int(minutes_ago))
        if at:
            m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(at))
            if not m:
                return None
            local = ref_now.astimezone(self._tz())
            t = local.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            return t - timedelta(days=1) if t > local else t
        return None

    async def _tool_point_history(self, person: Person, point_id: str, minutes: int = 120) -> Any:
        if self.tool_handler is None:
            return {"error": "trend data unavailable"}
        pts, note = await self._samples(point_id, minutes)
        if not pts:
            return {"point_id": point_id, "minutes": minutes, "samples": 0, "note": note}
        tz = self._tz()
        lo, hi = min(pts, key=lambda p: p[1]), max(pts, key=lambda p: p[1])
        step = max(1, len(pts) // 8)
        timeline = [[_hhmm(t, tz), round(v, 2)] for t, v in pts[::step]][:8]
        if timeline[-1][0] != _hhmm(pts[-1][0], tz):
            timeline.append([_hhmm(pts[-1][0], tz), round(pts[-1][1], 2)])
        return {"point_id": point_id, "minutes": minutes, "samples": len(pts),
                "first": round(pts[0][1], 2), "first_at": _hhmm(pts[0][0], tz),
                "last": round(pts[-1][1], 2), "last_at": _hhmm(pts[-1][0], tz),
                "min": round(lo[1], 2), "min_at": _hhmm(lo[0], tz),
                "max": round(hi[1], 2), "max_at": _hhmm(hi[0], tz), "timeline": timeline}

    async def _tool_change_since(self, person: Person, point_id: str, minutes_ago: Optional[int] = None,
                                 at: Optional[str] = None, target: Optional[float] = None,
                                 band: Optional[float] = None) -> Any:
        if self.tool_handler is None:
            return {"error": "trend data unavailable"}
        now = self._local_now()
        since = self._resolve_since(minutes_ago, at, now)
        if since is None:
            return {"error": "say when the action happened: minutes_ago, or at='HH:MM'"}
        before_minutes = 30
        # Fetch with a margin (the history buffer's own window is approximate) and filter exactly here.
        span = int((now - since).total_seconds() / 60) + before_minutes + 240
        pts, note = await self._samples(point_id, min(span, 7 * 24 * 60))
        if pts and abs((now - pts[-1][0]).total_seconds()) > 6 * 3600:
            # The data runs on another clock (simulator/replay): measure "ago" from its latest reading.
            offset = pts[-1][0] - now
            since = since + offset
        out = analyze_change(pts, since, target=target, band=band, before_minutes=before_minutes, tz=self._tz())
        out["point_id"] = point_id
        if not pts and note:
            out["note"] = note
        return out

    async def _tool_alarm_changes(self, person: Person, equipment_id: str, minutes_ago: Optional[int] = None,
                                  at: Optional[str] = None) -> Any:
        state = getattr(self.tool_handler, "bms_state", None)
        if state is None or not hasattr(state, "get_alarms_by_equipment"):
            return {"error": "alarm data unavailable"}
        now = self._local_now()
        since = self._resolve_since(minutes_ago, at, now)
        if since is None:
            return {"error": "say when the action happened: minutes_ago, or at='HH:MM'"}
        tz = self._tz()
        active, cleared, new = [], [], []
        for a in await state.get_alarms_by_equipment(equipment_id):
            state_name = getattr(a.state, "value", str(a.state)).lower()
            trig, res = _aware(a.triggered_at), _aware(getattr(a, "resolved_at", None))
            item = {"message": a.message, "severity": getattr(a.severity, "value", str(a.severity))}
            if res is not None and res >= since:
                cleared.append({**item, "cleared_at": _hhmm(res, tz),
                                "minutes_after_action": round((res - since).total_seconds() / 60)})
            elif state_name in ("active", "acknowledged"):
                active.append({**item, "since": _hhmm(trig, tz) if trig else None})
            if trig is not None and trig >= since:
                new.append({**item, "raised_at": _hhmm(trig, tz)})
        return {"equipment_id": equipment_id, "action_at": _hhmm(since, tz), "cleared_since": cleared,
                "still_active": active, "raised_since": new}

    async def _tool_acknowledge(self, person: Person, subject: str = "") -> Any:
        if self.gate is None:
            return {"error": "no alerts are tracked on this site"}
        alerts = await self.gate.ledger.open_alerts(person.number)
        if subject:
            alerts = [a for a in alerts if subject.lower().replace(" ", "") in
                      (a["title"] + a["topic"]).lower().replace(" ", "")] or alerts
        if not alerts:
            return {"acknowledged": [], "note": "no open alerts awaiting their acknowledgement"}
        done = []
        for a in alerts[:1] if subject else alerts:
            await self.gate.acknowledge(a["topic"], person)
            done.append(a["title"])
        return {"acknowledged": done}

    async def _tool_explain(self, person: Person, subject: str) -> Any:
        if self.gate is None:
            return {"error": "no decision log on this site"}
        rows = await self.gate.ledger.decisions_about(subject.strip(), person.number)
        if not rows:
            return {"subject": subject, "decisions": [], "note": "nothing about it reached me for you"}
        return {"subject": subject, "decisions": [
            {"when": r["decided_at"], "what": r["topic"], "decision": r["level"],
             "why": [f"{x['code']}: {x['detail']}" for x in r["reasons"]]} for r in rows]}

    async def _tool_open_cases(self, person: Person, equipment_id: str = "") -> Any:
        from agent_commercial.fdd.diagnosis import list_cases
        out = []
        for c in await list_cases(self.database, status="open", equipment_id=equipment_id or None):
            d = c.diagnosis or {}
            out.append({"case_id": c.id, "equipment_id": c.equipment_id, "rule_id": c.rule_id,
                        "likely_causes": [{"cause": h["label"], "p": h["p"]} for h in (d.get("posterior") or [])[:3]],
                        "settling_question": (d.get("next_question") or {}).get("question"),
                        "model_exhausted": bool(d.get("kb_bust"))})
        return out or {"open_cases": 0}

    async def _tool_deep_investigation(self, person: Person, question: str) -> str:
        if self.investigate is None or self.notify is None:
            return "deep investigation unavailable on this site"

        async def run():
            try:
                result = await self.investigate(question, person)
                text = await self.compose(person, result, purpose="report the result of the investigation you ran "
                                                                  f"for their question: {question!r}")
            except Exception as e:
                logger.error(f"[Ops] investigation for {person.name} failed: {e}")
                text = f"The investigation into \"{question[:80]}\" didn't complete ({type(e).__name__}). I'll keep watching."
            await self.notify(person, text, "investigation")

        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return "investigation started; the result will be sent to them when ready"

    async def _tool_ask_technician(self, person: Person, technician: str, equipment_id: str) -> Any:
        if person.role not in ("fm", "owner"):
            return {"error": "only the facilities manager or owner can send technicians checks"}
        if self.field_checks is None:
            return {"error": "field checks are not set up"}
        tech = self.people.by_name(technician)
        if tech is None or tech.role != "technician":
            names = ", ".join(p.name for p in self.people.by_role("technician")) or "none on the roster"
            return {"error": f"no technician named {technician!r} (technicians: {names})"}
        from agent_commercial.fdd.diagnosis import list_cases
        cases = [c for c in await list_cases(self.database, status="open", equipment_id=equipment_id)
                 if (c.diagnosis or {}).get("next_question")]
        if not cases:
            return {"error": f"no open diagnosis with a pending question for {equipment_id}"}
        check = await self.field_checks.request(cases[0].id, tech.number, requested_by=person.number)
        return {"sent_to": tech.name, "ref": check.ref, "question": check.question, "status": check.status}

    async def _tool_record_repair(self, person: Person, equipment_id: str, rule_id: str = "",
                                  what_was_done: str = "") -> Any:
        if person.role not in ("fm", "technician"):
            return {"error": "repairs are recorded by the facilities manager or a technician"}
        from agent_commercial.fdd.closed_loop import register_repair
        from agent_commercial.fdd.diagnosis import list_cases
        if not rule_id:
            open_ = await list_cases(self.database, status="open", equipment_id=equipment_id)
            if len(open_) != 1:
                return {"error": f"{len(open_)} open faults on {equipment_id}; ask which one was repaired",
                        "open": [c.rule_id for c in open_]}
            rule_id = open_[0].rule_id
        v = await register_repair(self.database, equipment_id, rule_id,
                                  note=f"reported on WhatsApp by {person.name}: {what_was_done}"[:500])
        return {"recorded": True, "verification_id": v.id, "equipment_id": equipment_id, "rule_id": rule_id,
                "next": "ARVIS re-checks the fault after enough running time and reports whether the repair worked"}

    # ── proactive phrasing ────────────────────────────────────────────────
    async def compose(self, person: Person, facts: str, purpose: str) -> str:
        """Say something unprompted, in ARVIS's voice, from given facts only.
        Falls back to the facts themselves if the language model is unavailable
        or will not stay within them."""
        system = (f"You are ARVIS, the operations engineer for {self.building_name}, messaging {person.name} — "
                  f"{_ROLE_GUIDE.get(person.role, _ROLE_GUIDE['fm'])}. Write ONE short WhatsApp message "
                  f"(2-5 lines, natural, no headings, no lists of options) to {purpose}. Use ONLY these facts; "
                  f"do not add numbers or causes that are not in them.\n\nFACTS:\n{facts}")
        try:
            resp = await self.llm.ask(messages=[{"role": "user", "content": "Write the message."}],
                                      system_msgs=[{"role": "system", "content": system}], channel="narrative")
            text = (getattr(resp, "content", "") or "").strip()
            if text and not ungrounded_numbers(text, [facts]):
                return text
            logger.warning(f"[Ops] composed message rejected (empty or ungrounded numbers); sending facts")
        except Exception as e:
            logger.error(f"[Ops] compose failed: {type(e).__name__}: {e}")
        return facts.strip()[:1500]
