"""
C5 NLU extraction + C6 task matching — the ArvisX discipline: the LLM classifies/extracts
(typed, confidence-scored), a deterministic keyword floor works with no LLM at all, and
NOTHING here writes — the router (api) decides the lane and asks for confirmation.

V1 taxonomy (subset of the PRD's ten types — the ones the pilot loop needs):
  commitment    — someone promised work by a time ("will finish plumbing tomorrow")
  status_update — work reported done/started ("false ceiling done")
  blocker       — progress blocked ("electrician didn't come", "material not delivered")
  approval      — client approved/rejected something
  chatter       — none of the above (ignored)
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fbq.models import ProjectPlan

EXTRACT_TYPES = ("commitment", "status_update", "blocker", "approval", "chatter")

_EXTRACT_SYS = (
    "You read ONE message from an interior-project WhatsApp group and classify it. Use ONLY "
    "what the message says — never invent. Types: 'commitment' (someone promises work will be "
    "done by some time), 'status_update' (work reported done/completed/started), 'blocker' "
    "(progress is stuck: no-show, material missing, site not ready), 'approval' (the client "
    "approves/rejects a material, design or extra work), 'chatter' (anything else — greetings, "
    "logistics small talk). Output JSON only: {\"type\": \"...\", \"task_hint\": \"which work "
    "it's about, from the message\", \"due_hint\": \"tomorrow|monday|a date, if said\", "
    "\"owner_hint\": \"who will do it, if said\", \"status\": \"done|in_progress, for "
    "status_update\", \"confidence\": 0.0-1.0}."
)


async def extract(llm, text: str) -> Dict[str, Any]:
    """One message → typed extraction. LLM first; deterministic keyword floor without it."""
    text = (text or "").strip()
    if not text:
        return {"type": "chatter", "confidence": 1.0}
    if llm is not None:
        try:
            out = await llm.ask_json(messages=[{"role": "user", "content": text}],
                                     system_msgs=[{"role": "system", "content": _EXTRACT_SYS}],
                                     channel="extract")
            if isinstance(out, dict) and out.get("type") in EXTRACT_TYPES:
                out["confidence"] = float(out.get("confidence", 0.5) or 0.5)
                return out
        except Exception:
            pass
    return _extract_deterministic(text)


def _extract_deterministic(text: str) -> Dict[str, Any]:
    """Keyword floor — coarse but honest (lower confidence, so it routes to Lane B, never A)."""
    low = text.lower()
    if re.search(r"\b(approved?|go ahead|okay to proceed|confirmed the (design|material)|reject(ed)?)\b", low):
        return {"type": "approval", "task_hint": text[:80], "confidence": 0.55}
    if re.search(r"\b(done|completed|finished|over|fitted|installed)\b", low) and not re.search(r"\bwill\b|\btomorrow\b", low):
        return {"type": "status_update", "status": "done", "task_hint": text[:80], "confidence": 0.55}
    if re.search(r"\b(didn'?t come|not come|no.?show|not delivered|material (not|nahi)|stuck|blocked|"
                 r"can'?t start|site not ready|delay(ed)?)\b", low):
        return {"type": "blocker", "task_hint": text[:80], "confidence": 0.55}
    if re.search(r"\b(will|we'?ll|shall|by (tomorrow|monday|tuesday|wednesday|thursday|friday|"
                 r"saturday|sunday|eod|evening|next week)|tomorrow|kal)\b", low):
        return {"type": "commitment", "task_hint": text[:80],
                "due_hint": _due_hint(low), "confidence": 0.5}
    return {"type": "chatter", "confidence": 0.9}


_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def _due_hint(low: str) -> str:
    for w in _WEEKDAYS:
        if w in low:
            return w
    if "tomorrow" in low or "kal" in low:
        return "tomorrow"
    if "next week" in low:
        return "next week"
    return ""


def resolve_due(hint: str, today: Optional[date] = None) -> str:
    """'tomorrow' / weekday / ISO → a concrete ISO date ('' if unresolvable)."""
    today = today or date.today()
    h = (hint or "").strip().lower()
    if not h:
        return ""
    if re.match(r"\d{4}-\d{2}-\d{2}$", h):
        return h
    if h in ("tomorrow", "kal", "eod tomorrow"):
        return (today + timedelta(days=1)).isoformat()
    if h in ("today", "eod", "evening", "tonight"):
        return today.isoformat()
    if h == "next week":
        return (today + timedelta(days=7)).isoformat()
    for w, wd in _WEEKDAYS.items():
        if w in h:
            delta = (wd - today.weekday()) % 7 or 7      # next occurrence, not today
            return (today + timedelta(days=delta)).isoformat()
    return ""


# ── C6: chat mention → plan task ──────────────────────────────────────────
_STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "for", "to", "and", "in", "on",
         "at", "we", "will", "by", "done", "completed", "finished", "work", "today", "tomorrow"}


def _tokens(s: str) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


def match_task(plan: ProjectPlan, hint: str) -> Optional[Dict[str, Any]]:
    """Fuzzy chat-mention → plan task. Score = token overlap of the hint vs task name
    (+milestone). Returns {task_id, name, score} for the best match ≥0.34, else None —
    the caller treats ≥0.8 as named-task confidence (FR-6), lower as ad-hoc fallback."""
    ht = _tokens(hint)
    if not ht:
        return None
    best, best_score = None, 0.0
    for t in plan.tasks:
        tt = _tokens(t.name) | _tokens(t.milestone)
        if not tt:
            continue
        overlap = len(ht & tt)
        score = overlap / max(1, min(len(ht), len(tt)))
        if overlap and score > best_score:
            best, best_score = t, score
    if best is None or best_score < 0.34:
        return None
    return {"task_id": best.task_id, "name": best.name, "score": round(best_score, 2)}
