"""
fbq API — the agent backend for the Baileys-pilot: group ingest → typed extraction →
risk-routed writes (Lane A auto+undo · Lane B confirm-in-chat) → plan sync → digest → Q&A,
plus the web app's endpoints (plan editor F11, Lane-B inbox, activity F12).

ArvisX discipline throughout: the LLM proposes, only deterministic executors write; every
write is provenance-stamped + logged to activity; money-ish types (cost/approval amounts)
never auto-commit; everything degrades to a deterministic floor without an LLM.
"""
from __future__ import annotations

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

from fbq import extraction as ex
from fbq import plan_engine as pe
from fbq.models import PlanTemplate, ProjectPlan
from fbq.persistence import FbqDb

logger = logging.getLogger("fbq.api")
_SEED_DIR = Path(__file__).parent / "seeds"


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
    app = FastAPI(title="fbq agent API")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    db = FbqDb()
    templates = _load_templates()
    _api_key = os.environ.get("FBQ_API_KEY", "").strip()

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
        if e["type"] == "status_update" and pay.get("task_id"):
            shifts, nxt = pe.mark_done(plan, pay["task_id"], date.today().isoformat())
            _save(pid, plan)
            db.log_activity(pid, "task_done", f"{pay['task_id']} via chat", by, lane="B",
                            source_msg=e.get("message_id") or 0)
            if gj:
                _notify_shifts(pid, gj, shifts)
                _notify_next(pid, gj, nxt)
            t = plan.task(pay["task_id"])
            return f"✅ Marked *{t.name if t else pay['task_id']}* done."
        if e["type"] == "commitment":
            # ad-hoc task appended (F5); matched commitments become due-date updates (F17)
            if pay.get("task_id"):
                t = plan.task(pay["task_id"])
                nd = pay.get("due") or ""
                if t and nd:
                    t.end = nd
                    t.notes = (t.notes + f" | committed {nd} by {pay.get('owner', by)}").strip(" |")
                    shifts = pe.recompute(plan)
                    _save(pid, plan)
                    db.log_activity(pid, "commitment", f"{t.task_id} due {nd}", by, lane="B",
                                    source_msg=e.get("message_id") or 0)
                    if gj:
                        _notify_shifts(pid, gj, shifts)
                    return f"📌 Noted — *{t.name}* committed for {nd}."
            from fbq.models import PlanTask
            tid = f"adhoc_{e['id']}"
            nd = pay.get("due") or ""
            nt = PlanTask(tid, pay.get("task_hint", "ad-hoc task")[:60],
                          owner_role=pay.get("owner", ""), milestone="(ad-hoc)")
            nt.status = "pending"
            nt.start = date.today().isoformat()
            nt.end = nd or nt.start
            plan.tasks.append(nt)
            _save(pid, plan)
            db.log_activity(pid, "task_created", f"{tid}: {nt.name} due {nt.end}", by, lane="B",
                            source_msg=e.get("message_id") or 0)
            return f"📌 Task added: *{nt.name}* — due {nt.end}" + (f" ({nt.owner_role})" if nt.owner_role else "")
        if e["type"] == "blocker":
            db.log_activity(pid, "blocker", pay.get("task_hint", ""), by, lane="B",
                            source_msg=e.get("message_id") or 0)
            return "🚧 Blocker logged — the owner has been flagged."
        if e["type"] == "approval":
            db.log_activity(pid, "approval", pay.get("task_hint", ""), by, lane="B",
                            source_msg=e.get("message_id") or 0)
            return "📝 Approval recorded (evidence kept with the source message)."
        return "Noted."

    @app.post("/api/v1/ingest")
    async def ingest(payload: Dict[str, Any] = Body(...)):
        """The bot relays every group message here. Returns {reply} when the agent should
        answer in the group ('' = stay silent — most chatter)."""
        p = payload or {}
        gj = str(p.get("group_jid", "")).strip()
        phone = re.sub(r"\D", "", str(p.get("phone", "")))
        name = str(p.get("name", "")).strip()
        text = str(p.get("text", "")).strip()
        kind = str(p.get("kind", "text"))
        pr = db.project_by_group(gj)
        if pr is None:
            return {"reply": ""}                       # unlinked group — ignore
        pid = pr["id"]
        db.upsert_person(pid, phone, name=name)
        mid = db.log_message(pid, phone, name, kind, text, media_ref=str(p.get("media_ref", "")))

        # 1) resolve a pending Lane-B confirm addressed to this sender
        pend = db.latest_pending_for(pid, phone)
        if pend and _YES.match(text):
            db.decide_extraction(pend["id"], "confirmed", by=name or phone)
            try:
                return {"reply": _execute_extraction(pend, name or phone)}
            except Exception as err:
                logger.warning(f"execute failed: {err}")
                return {"reply": "Couldn't apply that — the team has been notified."}
        if pend and _NO.match(text):
            db.decide_extraction(pend["id"], "declined", by=name or phone)   # training signal
            return {"reply": "👍 Ignored."}

        # 2) commands (deterministic, addressed to the agent)
        low = text.lower()
        if re.search(r"@?firstbriq\s+tasks|^tasks$|today'?s tasks", low):
            return {"reply": _task_list(pid)}
        if re.search(r"@?firstbriq\s+digest|^digest$", low):
            return {"reply": _digest(pid)}
        if low.startswith(("@firstbriq", "firstbriq")):
            q = re.sub(r"@?firstbriq[,:]?", "", text, flags=re.I).strip()
            if q:
                return {"reply": await _answer(pid, q)}

        # 3) typed extraction → lane routing
        if kind != "text" or not text:
            db.log_activity(pid, "media_filed", f"{kind} stored", name or phone, lane="A", source_msg=mid)
            return {"reply": ""}                       # Lane A: photos/docs filed silently
        llm = _llm()
        found = await ex.extract(llm, text)
        etype = found.get("type", "chatter")
        if etype == "chatter":
            return {"reply": ""}
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
        return {"reply": f"{ask} Reply YES / NO. (#{eid})"}

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

    async def _answer(pid: int, q: str) -> str:
        """F9 grounded Q&A: plan state + recent messages; deterministic fallback = task list."""
        llm = _llm()
        plan = _plan(pid)
        if llm is not None:
            try:
                from arvisx.checklist_skills import _crisp, _looks_like_reasoning, _numbers_grounded
                lines = [f"{t.task_id}|{t.name}|{t.status}|{t.start}->{t.end}|{t.owner_role}"
                         for t in plan.tasks]
                recent = db.recent_messages(pid, 15)
                ctx = ("PLAN TASKS (id|name|status|dates|owner):\n" + "\n".join(lines)
                       + "\n\nRECENT MESSAGES:\n"
                       + "\n".join(f"[{m['ts'][:16]}] {m['sender_name']}: {m['text'][:120]}" for m in recent))
                out = await llm.ask_json(
                    messages=[{"role": "user", "content": f"{ctx}\n\nQUESTION: {q}"}],
                    system_msgs=[{"role": "system", "content":
                                  "You answer questions about ONE interior project from the plan "
                                  "and messages given. Use ONLY this data; cite task names/dates; "
                                  "if it isn't there say you don't know. Output JSON only: "
                                  '{"answer": "..."}'}],
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
