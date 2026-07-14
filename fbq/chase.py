"""
The chase — commitment aging, reminders, and the morning/evening briefs.

This is AllGud's lapse-streak escalation ladder ported from "a shift nobody did" to "a promise
nobody kept". The insight that made AllGud feel alive: a message that repeats itself identically
every day reads like a robot and gets ignored. So the tone ESCALATES with the age of the promise,
and it names the person.

  day 0 (due today)   — a gentle heads-up, no blame
  1 day over          — "still on?"
  2-3 days over       — firmer, names them, asks for a new date
  4+ days over        — 🔴 chronic, escalated to the owner/manager

Deterministic and pure — no LLM, no DB. The caller feeds rows in and enqueues what comes out.
Nothing is fabricated: every number here is a real day-count off a real promise.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

MAX_NUDGES_PER_DAY = 1          # never chase the same promise twice in a day


def _d(iso: str) -> Optional[date]:
    try:
        return date.fromisoformat((iso or "")[:10])
    except Exception:
        return None


def days_overdue(commitment: Dict[str, Any], today: str) -> int:
    due, now = _d(commitment.get("due_date", "")), _d(today)
    if not due or not now:
        return 0
    return (now - due).days


def commitment_nudge(c: Dict[str, Any], over: int) -> Optional[Dict[str, str]]:
    """The escalation ladder. Returns {text, to} — to='group' or 'manager' — or None if it's
    not time to say anything yet."""
    who = c.get("owner_name") or "someone"
    what = (c.get("text") or "the task").strip()
    promised = c.get("promised_on") or ""
    if over < 0:
        return None                                    # not due yet — say nothing
    if over == 0:
        return {"to": "group",
                "text": f"⏰ {who} — *{what}* is due today. All good?"}
    if over == 1:
        return {"to": "group",
                "text": f"⏰ {who} — *{what}* was due yesterday. Still on?"}
    if over <= 3:
        return {"to": "group",
                "text": (f"⚠️ {who} — *{what}* is *{over} days* past due "
                         f"(promised on {promised}). What's the new date?")}
    return {"to": "manager",
            "text": (f"🔴 Chronic delay — *{what}* is *{over} days* overdue.\n"
                     f"{who} promised it on {promised} and it's still open"
                     + (f" after {c['nudges']} reminders" if c.get("nudges") else "") + ".")}


def due_nudges(commitments: List[Dict[str, Any]], today: str) -> List[Dict[str, Any]]:
    """Which open promises deserve a word today (≤1 per promise per day)."""
    out = []
    for c in commitments:
        if c.get("status") != "open" or c.get("last_nudge") == today:
            continue
        over = days_overdue(c, today)
        msg = commitment_nudge(c, over)
        if msg:
            out.append({"commitment": c, "over": over, **msg})
    return out


# ── briefs ────────────────────────────────────────────────────────────────
def morning_brief(project_name: str, today: str, due_today, overdue, commitments,
                  next_up) -> str:
    """What matters TODAY. Short — it's read on a site, one-handed."""
    L = [f"☀️ *{project_name} — {today}*"]
    if overdue:
        L.append("🔴 *Overdue:* " + ", ".join(
            f"{t.name}" + (f" ({t.owner_role})" if t.owner_role else "") for t in overdue[:5]))
    if due_today:
        L.append("*Today:* " + ", ".join(
            f"{t.name}" + (f" — {t.owner_role}" if t.owner_role else "") for t in due_today[:6]))
    promises = [c for c in commitments if (c.get("due_date") or "") <= today]
    if promises:
        L.append("*Promised by today:* " + ", ".join(
            f"{c['owner_name']}: {c['text'][:40]}" for c in promises[:4]))
    if next_up and not due_today:
        L.append("*Coming up:* " + ", ".join(f"{t.start} {t.name}" for t in next_up[:3]))
    if len(L) == 1:
        L.append("Nothing due today — plan is clear. ✅")
    return "\n".join(L)


def evening_brief(project_name: str, today: str, summary: str, open_promises,
                  unanswered_photos: int = 0) -> str:
    """What actually happened. `summary` is the day-memory (LLM or deterministic)."""
    L = [f"🌙 *{project_name} — end of day {today}*", summary]
    late = [c for c in open_promises if (c.get("due_date") or "9999") < today]
    if late:
        L.append("⚠️ *Still open:* " + ", ".join(
            f"{c['owner_name']} — {c['text'][:40]}" for c in late[:4]))
    if unanswered_photos:
        L.append(f"📷 {unanswered_photos} photo(s) still without context.")
    return "\n".join(L)
