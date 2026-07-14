"""
fbq API — the agent backend for the Baileys-pilot: group ingest → typed extraction →
risk-routed writes (Lane A auto+undo · Lane B confirm-in-chat) → plan sync → digest → Q&A,
plus the web app's endpoints (plan editor F11, Lane-B inbox, activity F12).

ArvisX discipline throughout: the LLM proposes, only deterministic executors write; every
write is provenance-stamped + logged to activity; money-ish types (cost/approval amounts)
never auto-commit; everything degrades to a deterministic floor without an LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fbq import brain
from fbq import chase
from fbq import extraction as ex
from fbq import plan_engine as pe
from fbq.models import PlanTemplate, ProjectPlan
from fbq.persistence import FbqDb

logger = logging.getLogger("fbq.api")
_SEED_DIR = Path(__file__).parent / "seeds"
_MEDIA_DIR = Path(os.environ.get("FBQ_MEDIA_DIR", "fbq/data/media"))


def _load_templates() -> Dict[str, PlanTemplate]:
    out = {}
    for f in sorted(_SEED_DIR.glob("*.json")):
        try:
            t = PlanTemplate.from_dict(json.loads(f.read_text(encoding="utf-8")))
            out[t.template_id] = t
        except Exception:
            continue
    return out


def _llm():
    if os.environ.get("FBQ_LLM", os.environ.get("ARVIS_X_LLM", "")).strip() not in ("1", "true", "True"):
        return None
    try:
        from arvisx.llm_env import load_arvis_env
        load_arvis_env()
        from arvisx.llm_client import make_llm
        return make_llm()
    except Exception:
        return None


def create_app() -> FastAPI:
    app = FastAPI(title="firstbriq AI Manager")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    db = FbqDb()
    templates = _load_templates()
    _api_key = os.environ.get("FBQ_API_KEY", "").strip()
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # Background-task keeper — a bare create_task can be GC'd mid-run (ArvisX scar tissue).
    _bg: set = set()

    def _spawn(coro) -> None:
        t = asyncio.create_task(coro)
        _bg.add(t)
        t.add_done_callback(_bg.discard)

    async def _index(project_id: int, ref_kind: str, ref_id: int, text: str) -> None:
        await asyncio.to_thread(brain.index_text, db, project_id, ref_kind, ref_id, text)

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        if _api_key and request.url.path.startswith("/api/"):
            if request.headers.get("x-api-key", "") != _api_key:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    def _plan(project_id: int) -> ProjectPlan:
        d = db.load_plan(project_id)
        if d is None:
            raise HTTPException(404, f"no plan for project {project_id}")
        return ProjectPlan.from_dict(d)

    def _save(project_id: int, plan: ProjectPlan) -> None:
        db.save_plan(project_id, plan.to_dict())

    def _notify_shifts(project_id: int, group_jid: str, shifts: List[Dict]) -> None:
        """F14 — grouped dependency-impact message."""
        if not shifts:
            return
        lines = [f"• {s['name']} → now {s['new_start']} to {s['new_end']}"
                 f" ({'+' if s['delta_days'] >= 0 else ''}{s['delta_days']}d)"
                 + (f" [{s['owner_role']}]" if s.get("owner_role") else "")
                 for s in shifts[:8]]
        db.enqueue(project_id, group_jid,
                   "📅 Schedule updated — these tasks moved:\n" + "\n".join(lines), kind="shift_alert")

    def _notify_next(project_id: int, group_jid: str, next_tasks) -> None:
        """F15 — next-task trigger."""
        for t in next_tasks:
            who = f" ({t.owner_role})" if t.owner_role else ""
            db.enqueue(project_id, group_jid,
                       f"▶️ Up next{who}: *{t.name}* — planned {t.start} to {t.end}.",
                       kind="next_task")

    # ── projects & plan (web app + agent) ─────────────────────────────────
    @app.get("/api/v1/templates")
    async def list_templates():
        return {"templates": [{"template_id": t.template_id, "name": t.name, "phase": t.phase,
                               "tasks": len(t.tasks)} for t in templates.values()]}

    @app.post("/api/v1/projects")
    async def create_project(payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        name = str(p.get("name", "")).strip()
        tid = str(p.get("template_id", "P3-MANUF-EXEC"))
        start = str(p.get("start_date", date.today().isoformat()))
        if not name:
            raise HTTPException(400, "provide 'name'")
        tmpl = templates.get(tid)
        if tmpl is None:
            raise HTTPException(404, f"unknown template {tid}")
        pid = db.create_project(name, tmpl.phase, start, group_jid=str(p.get("group_jid", "")),
                                working_days_only=bool(p.get("working_days_only", False)))
        plan = pe.instantiate(tmpl, str(pid), name, start,
                              working_days_only=bool(p.get("working_days_only", False)),
                              customize=p.get("customize"))
        _save(pid, plan)
        db.log_activity(pid, "project_created", f"from template {tid}", "web", lane="")
        return {"id": pid, "name": name, "tasks": len(plan.tasks)}

    @app.get("/api/v1/projects")
    async def list_projects():
        out = []
        for pr in db.list_projects():
            try:
                plan = _plan(pr["id"])
                done = sum(1 for t in plan.tasks if t.status == "done")
                pr = {**pr, "tasks_total": len(plan.tasks), "tasks_done": done,
                      "pct": round(100 * done / len(plan.tasks), 0) if plan.tasks else 0}
            except HTTPException:
                pr = {**pr, "tasks_total": 0, "tasks_done": 0, "pct": 0}
            out.append(pr)
        return {"projects": out}

    @app.get("/api/v1/projects/{pid}/plan")
    async def get_plan(pid: int):
        return _plan(pid).to_dict()

    @app.post("/api/v1/projects/{pid}/tasks/{tid}")
    async def edit_task(pid: int, tid: str, payload: Dict[str, Any] = Body(...),
                        x_actor: str = Header(default="web")):
        """F11 plan edit / F7 write-back from the web: status, duration, owner. Recomputes and
        pushes F14/F15 notices to the group."""
        p = payload or {}
        plan = _plan(pid)
        t = plan.task(tid)
        if t is None:
            raise HTTPException(404, f"unknown task {tid}")
        pr = db.get_project(pid) or {}
        gj = pr.get("group_jid", "")
        shifts, nxt = [], []
        if "duration_days" in p:
            t.duration_days = max(1, int(p["duration_days"]))
            t.start = t.end = ""                       # let the scheduler restamp
            shifts = pe.recompute(plan)
        if "owner_role" in p:
            t.owner_role = str(p["owner_role"])
        if "status" in p:
            st = str(p["status"])
            if st == "done":
                shifts, nxt = pe.mark_done(plan, tid, str(p.get("on_date", date.today().isoformat())))
            elif st in ("pending", "in_progress", "blocked"):
                t.status = st
        _save(pid, plan)
        db.log_activity(pid, "task_edit", f"{tid}: {json.dumps(p)}", x_actor, lane="web")
        if gj:
            _notify_shifts(pid, gj, shifts)
            _notify_next(pid, gj, nxt)
        return {"saved": True, "shifts": shifts, "next": [t.task_id for t in nxt]}

    # ── the agent loop: ingest → extract → route → confirm ────────────────
    _YES = re.compile(r"^(yes|y|haan|ha|ok(ay)?|confirm|👍)\b", re.I)
    _NO = re.compile(r"^(no|n|nahi|nope|cancel|❌)\b", re.I)

    def _execute_extraction(e: Dict[str, Any], by: str) -> str:
        """Deterministic executor — the ONLY thing that writes plan state from chat."""
        pid = e["project_id"]
        pay = e["payload"]
        plan = _plan(pid)
        pr = db.get_project(pid) or {}
        gj = pr.get("group_jid", "")
        phone = pay.get("confirm_phone", "")
        if e["type"] == "status_update" and pay.get("task_id"):
            shifts, nxt = pe.mark_done(plan, pay["task_id"], date.today().isoformat())
            _save(pid, plan)
            kept = db.close_commitments_for_task(pid, pay["task_id"])   # promise kept
            db.log_activity(pid, "task_done", f"{pay['task_id']} via chat", by, lane="B",
                            source_msg=e.get("message_id") or 0)
            if gj:
                _notify_shifts(pid, gj, shifts)
                _notify_next(pid, gj, nxt)
            t = plan.task(pay["task_id"])
            tail = " (promise kept 👊)" if kept else ""
            return f"✅ Marked *{t.name if t else pay['task_id']}* done.{tail}"
        if e["type"] == "commitment":
            due = pay.get("due") or date.today().isoformat()
            what = pay.get("task_hint", "the work")[:120]
            # matched commitment → move the plan date (F17); unmatched → an ad-hoc task (F5).
            if pay.get("task_id"):
                t = plan.task(pay["task_id"])
                if t and pay.get("due"):
                    t.end = due
                    t.notes = (t.notes + f" | committed {due} by {by}").strip(" |")
                    shifts = pe.recompute(plan)
                    _save(pid, plan)
                    if gj:
                        _notify_shifts(pid, gj, shifts)
                    what = t.name
            else:
                from fbq.models import PlanTask
                tid = f"adhoc_{e['id']}"
                nt = PlanTask(tid, what[:60], owner_role=pay.get("owner", ""), milestone="(ad-hoc)")
                nt.status, nt.start, nt.end = "pending", date.today().isoformat(), due
                plan.tasks.append(nt)
                _save(pid, plan)
                pay["task_id"] = tid
                db.log_activity(pid, "task_created", f"{tid}: {nt.name} due {due}", by, lane="B",
                                source_msg=e.get("message_id") or 0)
            # The PROMISE itself is now a tracked thing — this is what gets aged.
            cid = db.add_commitment(pid, what, owner_name=by, owner_phone=phone, due_date=due,
                                    task_id=pay.get("task_id", ""),
                                    source_msg=e.get("message_id") or 0)
            db.log_activity(pid, "commitment", f"{by} → {what} by {due}", by, lane="B",
                            source_msg=e.get("message_id") or 0)
            memo = f"{by} committed: {what} by {due}"
            memid = db.add_memory(pid, memo, source="commitment", sender=by,
                                  ref_date=date.today().isoformat())
            _spawn(_index(pid, "memory", memid, memo))
            return f"📌 Noted — *{what}* by *{due}* ({by}). I'll follow up. (#c{cid})"
        if e["type"] == "blocker":
            db.log_activity(pid, "blocker", pay.get("task_hint", ""), by, lane="B",
                            source_msg=e.get("message_id") or 0)
            if gj:
                db.enqueue(pid, gj, f"🚧 Blocker logged: _{pay.get('task_hint', '')[:80]}_ "
                                    f"— flagged to the project owner.", kind="blocker")
            return "🚧 Blocker logged — the owner has been flagged."
        if e["type"] == "approval":
            what = pay.get("task_hint", "")[:200]
            aid = db.add_approval(pid, what, approver_name=by, approver_phone=phone,
                                  source_msg=e.get("message_id") or 0)
            db.log_activity(pid, "approval", what, by, lane="B",
                            source_msg=e.get("message_id") or 0)
            memo = f"{by} approved: {what}"
            memid = db.add_memory(pid, memo, source="approval", sender=by,
                                  ref_date=date.today().isoformat())
            _spawn(_index(pid, "memory", memid, memo))
            return (f"📝 Approval #{aid} recorded — *{by}*, {date.today().isoformat()}. "
                    f"Kept with the original message as evidence.")
        return "Noted."

    async def _process_text(pr: Dict[str, Any], phone: str, name: str, text: str,
                            mid: int, kind: str = "text") -> str:
        """The ONE brain. A typed message and a transcribed voice note both land here — voice
        adds an input channel, never a second pipeline (ArvisX rule)."""
        pid = pr["id"]
        who = name or phone

        # 1) resolve a pending Lane-B confirm addressed to this sender
        pend = db.latest_pending_for(pid, phone)
        if pend and _YES.match(text):
            db.decide_extraction(pend["id"], "confirmed", by=who)
            try:
                return _execute_extraction(pend, who)
            except Exception as err:
                logger.warning(f"execute failed: {err}")
                return "Couldn't apply that — the team has been notified."
        if pend and _NO.match(text):
            db.decide_extraction(pend["id"], "declined", by=who)   # training signal
            return "👍 Ignored."

        # 2) a photo we asked about → THIS is the answer. The human gives the context; the bot
        #    never guesses at an image. The caption becomes durable memory.
        pending_media = db.awaiting_caption(pid, phone)
        if pending_media and not text.lower().startswith(("@firstbriq", "firstbriq")):
            db.set_media_caption(pending_media["id"], text)
            db.log_activity(pid, "photo_captioned", f"{pending_media['filename']}: {text[:80]}",
                            who, lane="A", source_msg=mid)
            memo = f"Photo ({pending_media['filename']}): {text}"
            memid = db.add_memory(pid, memo, source="photo", sender=who,
                                  ref_date=date.today().isoformat())
            _spawn(_index(pid, "memory", memid, memo))
            return f"📷 Got it — filed as: _{text[:70]}_"

        # 3) "remember X" → straight into the brain, verbatim, forever
        what = brain.remember_request(text)
        if what:
            memid = db.add_memory(pid, what, source="remember", sender=who,
                                  ref_date=date.today().isoformat())
            _spawn(_index(pid, "memory", memid, what))
            db.log_activity(pid, "memory_saved", what[:120], who, lane="A", source_msg=mid)
            return f"🧠 Noted, I'll remember that: _{what[:90]}_"

        # 4) commands (deterministic, addressed to the agent)
        low = text.lower()
        if re.search(r"@?firstbriq\s+tasks|^tasks$|today'?s tasks", low):
            return _task_list(pid)
        if re.search(r"@?firstbriq\s+digest|^digest$", low):
            return _digest(pid)
        # manager: chase someone by name — "remind Ravi" / "@firstbriq remind Ravi"
        mm = re.match(r"^(?:@?firstbriq[,:\s]+)?(?:remind|chase|follow ?up (?:with|on))\s+(.+)$",
                      text.strip(), re.I)
        if mm:
            return _remind_person(pid, mm.group(1).strip().rstrip("?.!"), by=who)
        if re.search(r"@?firstbriq\s+(commitments|promises)|^promises$", low):
            return _promise_list(pid)
        if re.search(r"@?firstbriq\s+approvals|^approvals$", low):
            return _approval_list(pid)
        # recall — "what did we say about X" (works months later)
        topic = brain.recall_request(text)
        if topic and (low.startswith(("@firstbriq", "firstbriq")) or "?" in text):
            hits = await asyncio.to_thread(brain.search, db, pid, topic)
            return await brain.answer_recall(_llm(), hits, topic)
        if low.startswith(("@firstbriq", "firstbriq")):
            q = re.sub(r"@?firstbriq[,:]?", "", text, flags=re.I).strip()
            if q:
                return await _answer(pid, q)

        # 5) typed extraction → lane routing
        if not text:
            return ""
        llm = _llm()
        found = await ex.extract(llm, text)
        etype = found.get("type", "chatter")
        if etype == "chatter":
            return ""
        plan = _plan(pid)
        m = ex.match_task(plan, found.get("task_hint", ""))
        payload_out = {"task_hint": found.get("task_hint", ""), "owner": found.get("owner_hint", ""),
                       "due": ex.resolve_due(found.get("due_hint", "")),
                       "status": found.get("status", ""), "confirm_phone": phone}
        if m and m["score"] >= 0.34:
            payload_out["task_id"] = m["task_id"]
        conf = float(found.get("confidence", 0.5))
        eid = db.add_extraction(pid, mid, etype, payload_out, conf, lane="B")
        # Lane B confirm-in-chat (read-first trust rule: nothing above auto-commits)
        if etype == "status_update" and payload_out.get("task_id"):
            ask = f"Mark *{m['name']}* as done?"
        elif etype == "commitment":
            tgt = f"*{m['name']}*" if payload_out.get("task_id") else f"\"{payload_out['task_hint'][:50]}\""
            due = payload_out.get("due") or "no date"
            ask = f"Log this commitment — {tgt} by {due}?"
        elif etype == "blocker":
            ask = f"Log a blocker: \"{payload_out['task_hint'][:60]}\"?"
        else:
            ask = f"Record this as a client approval: \"{payload_out['task_hint'][:60]}\"?"
        return f"{ask} Reply YES / NO. (#{eid})"

    @app.post("/api/v1/ingest")
    async def ingest(payload: Dict[str, Any] = Body(...)):
        """The bot relays every group TEXT message here. Returns {reply} when the agent should
        speak ('' = stay silent). Understanding is never gated — only speaking is."""
        p = payload or {}
        pr = db.project_by_group(str(p.get("group_jid", "")).strip())
        if pr is None:
            return {"reply": ""}                       # unlinked group — ignore
        pid = pr["id"]
        phone = re.sub(r"\D", "", str(p.get("phone", "")))
        name = str(p.get("name", "")).strip()
        text = str(p.get("text", "")).strip()
        db.upsert_person(pid, phone, name=name)
        mid = db.log_message(pid, phone, name, "text", text)
        if text:
            _spawn(_index(pid, "message", mid, f"{name or phone}: {text}"))
        return {"reply": await _process_text(pr, phone, name, text, mid)}

    @app.post("/api/v1/media")
    async def media(request: Request, group_jid: str = "", phone: str = "", name: str = "",
                    kind: str = "photo", filename: str = "", seconds: float = 0.0):
        """Raw media bytes from the bot. VOICE is transcribed and then flows through the SAME
        text brain. A PHOTO is stored and the bot ASKS what it is — it never guesses at an image;
        the human's answer becomes the caption and durable memory. PDFs are text-extracted."""
        pr = db.project_by_group((group_jid or "").strip())
        if pr is None:
            return {"reply": ""}
        pid = pr["id"]
        ph = re.sub(r"\D", "", phone or "")
        nm = (name or "").strip()
        who = nm or ph
        data = await request.body()
        db.upsert_person(pid, ph, name=nm)

        if kind == "voice":
            from arvisx import stt
            r = await asyncio.to_thread(stt.transcribe, data, filename or "voice.ogg", True, seconds)
            text = (r or {}).get("text", "").strip()
            if not text:
                # No STT key / failed → say nothing rather than guess at the audio.
                db.log_message(pid, ph, nm, "voice", "", media_ref="(not transcribed)")
                return {"reply": ""}
            mid = db.log_message(pid, ph, nm, "voice", text)
            _spawn(_index(pid, "message", mid, f"{who}: {text}"))
            reply = await _process_text(pr, ph, nm, text, mid, kind="voice")
            # A voice note that triggers a state change must show what was heard (a misheard
            # command must never execute silently) — the confirm ask carries the transcript.
            if reply:
                reply = f'🎙 Heard: "{text[:120]}"\n\n{reply}'
            return {"reply": reply}

        # photo / pdf → store the file
        _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or f"{kind}.bin")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        fn = f"{pid}-{stamp}-{safe}"
        (_MEDIA_DIR / fn).write_bytes(data)
        mid = db.log_message(pid, ph, nm, kind, "", media_ref=fn)
        med = db.add_media(pid, mid, kind, str(_MEDIA_DIR / fn), safe, ph, nm)

        if kind == "pdf":
            text = ""
            try:
                from arvisx.manual_skills import extract_text
                text = (await asyncio.to_thread(extract_text, _MEDIA_DIR / fn) or "")[:4000]
            except Exception:
                pass
            if text:
                db.set_media_caption(med, f"PDF: {safe}")
                memid = db.add_memory(pid, f"Document {safe}: {text[:600]}", source="document",
                                      sender=who, ref_date=date.today().isoformat())
                _spawn(_index(pid, "memory", memid, f"Document {safe}: {text[:600]}"))
            db.log_activity(pid, "document_filed", safe, who, lane="A", source_msg=mid)
            return {"reply": f"📄 Filed *{safe}*."}

        # PHOTO — ask, don't analyse.
        db.mark_media_asked(med)
        db.log_activity(pid, "photo_filed", safe, who, lane="A", source_msg=mid)
        return {"reply": "📷 Got the photo — what's this about? (reply here, voice note is fine)"}

    # ── chase: remind / promises / approvals ──────────────────────────────
    def _remind_person(pid: int, name: str, by: str = "") -> str:
        """Manager chases someone by name: their open promises + tasks they own, in-group."""
        plan = _plan(pid)
        today = date.today().isoformat()
        promises = db.commitments_for(pid, name)
        # roles are the plan's owner field; match loosely against the person's name or role
        low = name.lower()
        tasks = [t for t in plan.tasks
                 if t.status != "done" and (low in (t.owner_role or "").lower()
                                            or (t.owner_role or "").lower() in low)]
        if not promises and not tasks:
            people = ", ".join(p["name"] for p in db.people(pid) if p["name"]) or "nobody yet"
            return f"I have nothing open against *{name}*. (Known here: {people})"
        L = [f"👋 *{name}* — a nudge from {by or 'the team'}:"]
        for c in promises[:5]:
            over = (date.fromisoformat(today) - date.fromisoformat(c["due_date"])).days \
                if c.get("due_date") else 0
            tag = f" — *{over}d overdue*" if over > 0 else (" — due today" if over == 0 else "")
            L.append(f"• {c['text'][:60]} (by {c['due_date']}){tag}")
        for t in tasks[:5]:
            L.append(f"• {t.name} — planned {t.start} → {t.end}")
        L.append("_Reply here with an update, or say when it'll be done._")
        db.log_activity(pid, "reminded", f"{name} ({len(promises)} promises, {len(tasks)} tasks)",
                        by or "agent", lane="B")
        return "\n".join(L)

    def _promise_list(pid: int) -> str:
        today = date.today().isoformat()
        cs = db.open_commitments(pid)
        if not cs:
            return "No open promises. 👌"
        L = ["🤝 *Open promises:*"]
        for c in cs[:12]:
            over = chase.days_overdue(c, today)
            tag = f" 🔴 *{over}d overdue*" if over > 0 else (" — due today" if over == 0 else "")
            L.append(f"• *{c['owner_name']}* — {c['text'][:50]} (by {c['due_date']}){tag}")
        return "\n".join(L)

    def _approval_list(pid: int) -> str:
        aps = db.approvals(pid)
        if not aps:
            return "No approvals on record yet."
        L = ["📝 *Approval log:*"]
        for a in aps[-10:]:
            L.append(f"• #{a['id']} {a['approved_on'][:10]} — *{a['approver_name']}*: "
                     f"{a['text'][:60]}")
        L.append("_Full evidence pack: ask the office for the PDF export._")
        return "\n".join(L)

    # ── the sweep: morning brief, evening brief, commitment aging ─────────
    async def _run_sweep(pid: int, now: Optional[datetime] = None) -> List[str]:
        """Called on a poll by the bot. Idempotent per day per kind. Returns what it queued."""
        now = now or datetime.now()
        today = now.date().isoformat()
        pr = db.get_project(pid) or {}
        gj = pr.get("group_jid", "")
        if not gj:
            return []
        pname = pr.get("name", "Project")
        did: List[str] = []
        morning_h = int(os.environ.get("FBQ_MORNING_HOUR", "8"))
        evening_h = int(os.environ.get("FBQ_EVENING_HOUR", "19"))

        # morning brief
        if now.hour >= morning_h and not db.sweep_done(pid, "morning", today):
            plan = _plan(pid)
            overdue = pe.overdue_tasks(plan, today)
            due_today = [t for t in plan.tasks if t.status != "done" and t.start <= today <= t.end]
            nxt = sorted([t for t in plan.tasks if t.status != "done" and t.start > today],
                         key=lambda t: t.start)
            txt = chase.morning_brief(pname, today, due_today, overdue,
                                      db.open_commitments(pid), nxt)
            db.enqueue(pid, gj, txt, kind="morning_brief")
            db.mark_sweep(pid, "morning", today)
            did.append("morning")

        # commitment aging — the ladder (≤1 nudge per promise per day)
        for n in chase.due_nudges(db.open_commitments(pid), today):
            c = n["commitment"]
            db.enqueue(pid, gj, n["text"], kind=f"chase_{n['to']}")
            db.bump_commitment_nudge(c["id"], today)
            db.log_activity(pid, "chased", f"{c['owner_name']}: {c['text'][:50]} ({n['over']}d)",
                            "agent", lane="A")
            did.append(f"chase:{c['id']}")

        # photo without context — ask once more, then let it go (AllGud curiosity rule)
        for m in db.uncaptioned_media(pid):
            if m["kind"] != "photo" or (m.get("created_at") or "")[:10] == today:
                continue
            if m["nudges"] >= 1:
                db.give_up_media(m["id"])              # filed without context; stop nagging
                continue
            db.enqueue(pid, gj, f"📷 {m['sender_name'] or 'Someone'} — the photo from "
                                f"{m['created_at'][:10]}, what was it about?", kind="photo_nudge")
            db.bump_media_nudge(m["id"])
            did.append(f"photo:{m['id']}")

        # evening brief — the day becomes a memory
        if now.hour >= evening_h and not db.sweep_done(pid, "evening", today):
            summary = await _close_day_text(pid, today)
            unanswered = len([m for m in db.uncaptioned_media(pid) if m["kind"] == "photo"])
            txt = chase.evening_brief(pname, today, summary, db.open_commitments(pid), unanswered)
            db.enqueue(pid, gj, txt, kind="evening_brief")
            db.mark_sweep(pid, "evening", today)
            did.append("evening")
        return did

    @app.post("/api/v1/sweep")
    async def sweep_ep(payload: Dict[str, Any] = Body(default={})):
        """The bot polls this. Runs briefs + aging for every active project."""
        out: Dict[str, Any] = {}
        for pr in db.list_projects():
            try:
                r = await _run_sweep(pr["id"])
                if r:
                    out[pr["name"]] = r
            except Exception as err:
                logger.warning(f"sweep failed for {pr['id']}: {err}")
        return {"ran": out}

    @app.get("/api/v1/projects/{pid}/commitments")
    async def commitments_ep(pid: int):
        return {"commitments": db.open_commitments(pid)}

    @app.get("/api/v1/projects/{pid}/approvals")
    async def approvals_ep(pid: int):
        return {"approvals": db.approvals(pid)}

    # ── digest / tasks / Q&A (read lane) ──────────────────────────────────
    def _task_list(pid: int) -> str:
        plan = _plan(pid)
        today = date.today().isoformat()
        week = (date.today()).isoformat(), (date.fromordinal(date.today().toordinal() + 7)).isoformat()
        due_today = [t for t in plan.tasks if t.status != "done" and t.start <= today <= t.end]
        upcoming = [t for t in plan.tasks if t.status != "done" and today < t.start <= week[1]]
        od = pe.overdue_tasks(plan, today)
        L = []
        if od:
            L.append("*Overdue:*")
            L += [f"• {t.name} (was due {t.end})" + (f" — {t.owner_role}" if t.owner_role else "") for t in od[:6]]
        if due_today:
            L.append("*Today:*")
            L += [f"• {t.name}" + (f" — {t.owner_role}" if t.owner_role else "") for t in due_today[:8]]
        if upcoming:
            L.append("*Next 7 days:*")
            L += [f"• {t.start} {t.name}" + (f" — {t.owner_role}" if t.owner_role else "") for t in upcoming[:8]]
        return "\n".join(L) or "Nothing due — plan is clear. ✅"

    def _digest(pid: int) -> str:
        plan = _plan(pid)
        pr = db.get_project(pid) or {}
        today = date.today().isoformat()
        msgs = db.messages_on(pid, today)
        done_today = [t for t in plan.tasks if t.status == "done" and t.actual_end == today]
        od = pe.overdue_tasks(plan, today)
        ms = [m for m in pe.milestone_progress(plan) if m["total"] and m["milestone"] != "(ad-hoc)"]
        L = [f"🏗 *{pr.get('name', 'Project')} — daily digest ({today})*"]
        L.append(f"Progress: " + " · ".join(f"{m['milestone']} {m['pct']:.0f}%" for m in ms[:4]))
        if done_today:
            L.append("Done today: " + ", ".join(t.name for t in done_today[:5]))
        if od:
            L.append(f"⚠️ Overdue ({len(od)}): " + ", ".join(t.name for t in od[:4]))
        blockers = [a for a in db.activities(pid, 50)
                    if a["action"] == "blocker" and a["ts"][:10] == today]
        if blockers:
            L.append("🚧 Blockers: " + "; ".join(b["detail"][:60] for b in blockers[:3]))
        L.append(f"({len(msgs)} messages today)")
        return "\n".join(L)

    def _situation(pid: int, q: str, hits: List[Dict[str, Any]]) -> str:
        """EVERYTHING the AI Manager knows, in one block — the same picture the web console shows.
        Plan, the promise ledger, the approval trail, what photos turned out to be, and the
        semantically-retrieved history. Whatever is changed in the console lands here on the next
        question, because both read the one database."""
        plan = _plan(pid)
        today_ = date.today().isoformat()
        L = ["PLAN TASKS (id|name|status|dates|owner):"]
        L += [f"{t.task_id}|{t.name}|{t.status}|{t.start}->{t.end}|{t.owner_role}" for t in plan.tasks]
        cs = db.open_commitments(pid)
        if cs:
            L.append("\nOPEN PROMISES (who|what|promised|due|days_overdue):")
            L += [f"{c['owner_name']}|{c['text']}|{c['promised_on']}|{c['due_date']}|"
                  f"{max(0, chase.days_overdue(c, today_))}" for c in cs]
        aps = db.approvals(pid)
        if aps:
            L.append("\nAPPROVALS (who approved what, and when):")
            L += [f"#{a['id']} {a['approved_on'][:10]} {a['approver_name']}: {a['text'][:100]}"
                  for a in aps[-8:]]
        med = [m for m in db.media_on(pid, today_) if m.get("caption")]
        if med:
            L.append("\nTODAY'S PHOTOS (as described by the person who sent them):")
            L += [f"{m['sender_name']}: {m['caption'][:80]}" for m in med[:6]]
        if hits:
            L.append("\nRELEVANT HISTORY & MEMORIES:")
            L += [f"[{(h.get('ts') or '')[:10]}] {h.get('who') or '?'}"
                  f"{' (memory)' if h.get('kind') == 'memory' else ''}: {h.get('text', '')[:140]}"
                  for h in hits]
        recent = db.recent_messages(pid, 12)
        if recent:
            L.append("\nRECENT MESSAGES:")
            L += [f"[{m['ts'][:16]}] {m['sender_name']}: {m['text'][:120]}"
                  for m in recent if (m.get("text") or "").strip()]
        return "\n".join(L)

    async def _answer(pid: int, q: str) -> str:
        """The AI Manager answering about its project. Sees the whole situation — plan, promises,
        approvals, photo context, and semantically-retrieved history — so anything done in the web
        console is already known here (one database, one brain). Deterministic fallback."""
        llm = _llm()
        if llm is not None:
            try:
                from arvisx.checklist_skills import _crisp, _looks_like_reasoning, _numbers_grounded
                hits = await asyncio.to_thread(brain.search, db, pid, q, 5)
                ctx = _situation(pid, q, hits)
                out = await llm.ask_json(
                    messages=[{"role": "user", "content": f"{ctx}\n\nQUESTION: {q}"}],
                    system_msgs=[{"role": "system", "content":
                                  "You are the AI Manager for ONE interior project. Answer from the "
                                  "situation given — plan, promises, approvals, photos, history. Use "
                                  "ONLY this data; name people and dates; if it isn't there, say you "
                                  'don\'t know. Output JSON only: {"answer": "..."}'}],
                    channel="chat")
                s = _crisp(str(out.get("answer", ""))).strip() if isinstance(out, dict) else ""
                if s and not _looks_like_reasoning(s) and _numbers_grounded(s, ctx):
                    return s
            except Exception:
                pass
        return _task_list(pid)

    @app.get("/api/v1/projects/{pid}/digest")
    async def digest_ep(pid: int):
        return {"text": _digest(pid)}

    @app.get("/api/v1/projects/{pid}/tasks-due")
    async def tasks_due(pid: int):
        return {"text": _task_list(pid)}

    @app.get("/api/v1/projects/{pid}/ask")
    async def ask_ep(pid: int, q: str):
        return {"text": await _answer(pid, q)}

    # ── Lane-B inbox + activity (web app) ─────────────────────────────────
    @app.get("/api/v1/projects/{pid}/pending")
    async def pending_ep(pid: int):
        return {"pending": db.pending_extractions(pid)}

    @app.post("/api/v1/pending/{eid}/decide")
    async def decide_ep(eid: int, payload: Dict[str, Any] = Body(...)):
        e = db.get_extraction(eid)
        if e is None or e["status"] != "pending":
            raise HTTPException(404, "no such pending item")
        status = str((payload or {}).get("status", ""))
        by = str((payload or {}).get("by", "web"))
        if status not in ("confirmed", "declined"):
            raise HTTPException(400, "status must be confirmed|declined")
        db.decide_extraction(eid, status, by=by)
        if status == "confirmed":
            reply = _execute_extraction(e, by)
            pr = db.get_project(e["project_id"]) or {}
            if pr.get("group_jid"):
                db.enqueue(e["project_id"], pr["group_jid"], reply, kind="confirm_result")
            return {"done": True, "result": reply}
        return {"done": True, "result": "declined"}

    @app.get("/api/v1/projects/{pid}/activity")
    async def activity_ep(pid: int):
        return {"activity": db.activities(pid)}

    # ── the brain (web) ───────────────────────────────────────────────────
    @app.get("/api/v1/projects/{pid}/memories")
    async def memories_ep(pid: int):
        return {"memories": db.memories(pid)}

    @app.post("/api/v1/projects/{pid}/memories")
    async def add_memory_ep(pid: int, payload: Dict[str, Any] = Body(...)):
        text = str((payload or {}).get("text", "")).strip()
        if not text:
            raise HTTPException(400, "provide 'text'")
        mid = db.add_memory(pid, text, source="manual", sender=str((payload or {}).get("by", "web")),
                            ref_date=date.today().isoformat())
        _spawn(_index(pid, "memory", mid, text))
        return {"id": mid}

    @app.get("/api/v1/projects/{pid}/recall")
    async def recall_ep(pid: int, q: str):
        hits = await asyncio.to_thread(brain.search, db, pid, q)
        return {"answer": await brain.answer_recall(_llm(), hits, q), "hits": hits}

    @app.get("/api/v1/projects/{pid}/media")
    async def media_list_ep(pid: int):
        return {"media": db.media_on(pid, date.today().isoformat())}

    async def _close_day_text(pid: int, day: str) -> str:
        """Distil the day and STORE it as a memory (idempotent). Returns the summary body."""
        summary = await brain.day_memory(_llm(), db.messages_on(pid, day),
                                         db.activities_on(pid, day), db.media_on(pid, day), day)
        if not db.memory_exists_for_date(pid, "daily", day):
            mid = db.add_memory(pid, summary, source="daily", sender="firstbriq", ref_date=day)
            _spawn(_index(pid, "memory", mid, f"Day {day}: {summary}"))
        return summary

    @app.post("/api/v1/projects/{pid}/close-day")
    async def close_day_ep(pid: int, payload: Dict[str, Any] = Body(default={})):
        day = str((payload or {}).get("date") or date.today().isoformat())
        summary = await _close_day_text(pid, day)
        pr = db.get_project(pid) or {}
        unanswered = len([m for m in db.uncaptioned_media(pid) if m["kind"] == "photo"])
        text = chase.evening_brief(pr.get("name", "Project"), day, summary,
                                   db.open_commitments(pid), unanswered)
        if pr.get("group_jid"):
            db.enqueue(pid, pr["group_jid"], text, kind="evening_brief")
        return {"text": text}

    @app.get("/api/v1/projects/{pid}/evidence.pdf")
    async def evidence_pack(pid: int):
        """The dispute-proof export: every approval, with who / when / the exact words, plus the
        promise ledger. This is the artefact a contractor shows an angry client."""
        from fastapi.responses import Response
        from fpdf import FPDF
        pr = db.get_project(pid) or {}
        plan = _plan(pid)

        def _safe(s: Any) -> str:
            return (str(s).replace("—", "-").replace("’", "'")
                    .encode("latin-1", "ignore").decode("latin-1"))

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 9, _safe(f"{pr.get('name', 'Project')} - Evidence Pack"), ln=1)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 6, _safe(f"Generated {datetime.now():%Y-%m-%d %H:%M} - every entry is a real "
                             f"message from the project group."), ln=1)
        pdf.set_text_color(0, 0, 0)

        pdf.ln(3); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 7, "Approvals", ln=1)
        aps = db.approvals(pid)
        pdf.set_font("Helvetica", "", 9)
        if not aps:
            pdf.cell(0, 6, "No approvals recorded.", ln=1)
        for a in aps:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, _safe(f"#{a['id']}  {a['approved_on'][:16]}  -  {a['approver_name']}"), ln=1)
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, _safe(f'   "{a["text"]}"'))
            pdf.ln(1)

        pdf.ln(2); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 7, "Commitments", ln=1)
        pdf.set_font("Helvetica", "", 9)
        cs = db.open_commitments(pid)
        today = date.today().isoformat()
        if not cs:
            pdf.cell(0, 6, "No open commitments.", ln=1)
        for c in cs:
            over = chase.days_overdue(c, today)
            tag = f"  [{over}d OVERDUE]" if over > 0 else ""
            pdf.multi_cell(0, 5, _safe(f"- {c['owner_name']}: {c['text']}  (promised "
                                       f"{c['promised_on']}, due {c['due_date']}){tag}"))

        pdf.ln(2); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 7, "Completed work", ln=1)
        pdf.set_font("Helvetica", "", 9)
        done = [t for t in plan.tasks if t.status == "done"]
        if not done:
            pdf.cell(0, 6, "Nothing completed yet.", ln=1)
        for t in done:
            pdf.multi_cell(0, 5, _safe(f"- {t.name} (completed {t.actual_end or t.end})"))

        out = pdf.output(dest="S")
        data = bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")
        fn = f"evidence-{pr.get('name', 'project').replace(' ', '_')}-{today}.pdf"
        return Response(content=data, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fn}"'})

    @app.get("/api/v1/projects/{pid}/people")
    async def people_ep(pid: int):
        return {"people": db.people(pid)}

    @app.post("/api/v1/projects/{pid}/people")
    async def person_ep(pid: int, payload: Dict[str, Any] = Body(...)):
        p = payload or {}
        db.upsert_person(pid, re.sub(r"\D", "", str(p.get("phone", ""))),
                         name=str(p.get("name", "")), role=str(p.get("role", "")))
        return {"saved": True}

    @app.post("/api/v1/projects/{pid}/link-group")
    async def link_group_ep(pid: int, payload: Dict[str, Any] = Body(...)):
        gj = str((payload or {}).get("group_jid", "")).strip()
        if not gj:
            raise HTTPException(400, "provide group_jid")
        db.link_group(pid, gj)
        db.log_activity(pid, "group_linked", gj, "web")
        return {"linked": gj}

    # ── bot delivery queue ────────────────────────────────────────────────
    @app.get("/api/v1/outbox")
    async def outbox_ep():
        return {"outbox": db.outbox_pending()}

    @app.post("/api/v1/outbox/ack")
    async def outbox_ack_ep(payload: Dict[str, Any] = Body(...)):
        ids = [int(i) for i in (payload or {}).get("ids", [])]
        db.outbox_ack(ids)
        return {"acked": len(ids)}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "ts": datetime.now().isoformat(timespec="seconds")}

    app.state.db = db
    return app
