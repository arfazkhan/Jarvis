"""
ArvisX Phase-0 — digitized operations checklists (NO sensors).

The wedge before the edge: One Anthem (and buildings like it) run their daily ops on
paper checklists — three shifts a day plus a quarterly preventive-maintenance (PPM)
form. Paper can be filled from memory on Saturday, the fire-panel line can read "OFF"
for two days and nobody escalates, and the sign-off boxes stay blank. This module
digitizes those exact sheets and delivers the value that needs zero hardware:

  • SERVER-TIMESTAMPED entries — you cannot backfill a week; each tick is when it happened.
  • RULES ON THE OPERATOR'S OWN INPUT — an item can declare alert-states (fire panel
    "OFF/FAULT", leakage "DETECTED"); the human's own entry trips a flag, no sensor needed.
  • SIGN-OFF CHAIN — technician → supervisor → caretaker → engineer → president.
  • ISSUE → CORRECTIVE ACTION tracking, and a manager completion/issue digest.

When edge sensors arrive (Phase 1), the same run/entry model gains telemetry auto-fill and
reading-verification (grounding applied to humans) — this is the foundation, not a throwaway.

Templates are CODE-defined per building (faithful to the real sheets); runs/entries/sign-offs
are persisted. Item kinds:
  tick    → done | issue | na
  reading → a number (+ unit)         e.g. tank level %, battery V, run hours
  state   → one of `options`          e.g. ON/OFF, OK/NIL, RUNNING/STOPPED
  note    → free text
An item may carry `alert_states` (state values that mean trouble) — entering one flags
the entry as an issue automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── template model ────────────────────────────────────────────────────────
@dataclass
class Item:
    item_id: str
    label: str
    kind: str = "tick"                     # tick | reading | state | note
    unit: str = ""                         # reading unit (%, V, hrs, bar…)
    options: List[str] = field(default_factory=list)   # state choices
    alert_states: List[str] = field(default_factory=list)  # values that auto-flag an issue
    asset: str = ""                        # canonical asset this item is about (Phase-S tagging)

    def to_dict(self) -> Dict[str, Any]:
        return {"item_id": self.item_id, "label": self.label, "kind": self.kind,
                "unit": self.unit, "options": self.options, "alert_states": self.alert_states,
                "asset": self.asset}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Item":
        return cls(item_id=str(d["item_id"]), label=str(d.get("label", d["item_id"])),
                   kind=str(d.get("kind", "tick")), unit=str(d.get("unit", "")),
                   options=list(d.get("options", [])), alert_states=list(d.get("alert_states", [])),
                   asset=str(d.get("asset", "")))


@dataclass
class Section:
    name: str
    items: List[Item]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "items": [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Section":
        return cls(name=str(d.get("name", "")), items=[Item.from_dict(i) for i in d.get("items", [])])


@dataclass
class Template:
    template_id: str
    name: str
    cadence: str                           # daily | weekly | monthly | quarterly | custom
    sections: List[Section]
    timing: str = ""                       # shift window, informational
    signoff_roles: List[str] = field(default_factory=list)
    per_asset: List[str] = field(default_factory=list)  # PPM: one run-block per asset
    # Cadence-driven auto-open schedule (set by the builder). sched_time = open time HH:MM.
    # weekly→sched_dow (0=Mon..6=Sun); monthly→sched_dom (1..31); quarterly→sched_date anchor
    # (recurs every 3 months from it); custom→sched_date (one specific date). daily ignores all.
    sched_time: str = ""
    sched_dow: Optional[int] = None
    sched_dom: Optional[int] = None
    sched_date: str = ""

    def all_items(self) -> List[Item]:
        return [it for s in self.sections for it in s.items]

    def to_dict(self) -> Dict[str, Any]:
        return {"template_id": self.template_id, "name": self.name, "cadence": self.cadence,
                "timing": self.timing, "signoff_roles": self.signoff_roles,
                "per_asset": self.per_asset, "sched_time": self.sched_time,
                "sched_dow": self.sched_dow, "sched_dom": self.sched_dom,
                "sched_date": self.sched_date, "sections": [s.to_dict() for s in self.sections]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Template":
        def _int_or_none(v):
            try:
                return int(v) if v is not None and str(v).strip() != "" else None
            except (TypeError, ValueError):
                return None
        return cls(template_id=str(d["template_id"]), name=str(d.get("name", "")),
                   cadence=str(d.get("cadence", "daily")),
                   sections=[Section.from_dict(s) for s in d.get("sections", [])],
                   timing=str(d.get("timing", "")), signoff_roles=list(d.get("signoff_roles", [])),
                   per_asset=list(d.get("per_asset", [])),
                   sched_time=str(d.get("sched_time", "")),
                   sched_dow=_int_or_none(d.get("sched_dow")),
                   sched_dom=_int_or_none(d.get("sched_dom")),
                   sched_date=str(d.get("sched_date", "")))


def validate_template_dict(d: Dict[str, Any]) -> None:
    """Reject malformed builder input before it's saved."""
    if not isinstance(d, dict) or not str(d.get("template_id", "")).strip():
        raise ValueError("template_id required")
    if not str(d.get("name", "")).strip():
        raise ValueError("name required")
    secs = d.get("sections")
    if not isinstance(secs, list) or not secs:
        raise ValueError("at least one section required")
    seen = set()
    for s in secs:
        for it in s.get("items", []):
            iid = str(it.get("item_id", "")).strip()
            if not iid:
                raise ValueError("every item needs an item_id")
            if iid in seen:
                raise ValueError(f"duplicate item_id '{iid}'")
            seen.add(iid)
            if it.get("kind", "tick") not in ("tick", "reading", "state", "note"):
                raise ValueError(f"bad kind for '{iid}'")
    if not seen:
        raise ValueError("at least one item required")


# ── building templates load from SEED DATA — no building hardcoded in code ──
# Each arvisx/seeds/<name>.json = {"building_id":.., "name":.., "templates":[<Template dicts>]}.
# One Anthem is just the first seed file (asset tags baked into the items). A new building is a
# new seed file OR templates created via the API builder (DB, layered on via set_custom_loader).
# The engine code carries ZERO building-specific data.
import json as _json
from pathlib import Path as _Path

_SEED_DIR = _Path(__file__).parent / "seeds"
_SEED_NAMES: Dict[str, str] = {}      # building_id → display name (from the seed file)


def _load_seed_templates() -> Dict[str, List[Template]]:
    out: Dict[str, List[Template]] = {}
    if not _SEED_DIR.is_dir():
        return out
    for f in sorted(_SEED_DIR.glob("*.json")):
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        bid = data.get("building_id")
        if not bid:
            continue
        out.setdefault(bid, [])
        _SEED_NAMES[bid] = data.get("name", bid)
        for t in data.get("templates", []):
            try:
                out[bid].append(Template.from_dict(t))
            except Exception:
                continue
    return out


_BUILDING_TEMPLATES: Dict[str, List[Template]] = _load_seed_templates()


def seed_catalog() -> List[Dict[str, Any]]:
    """Available starter packs on disk — for onboarding a new building from a seed."""
    return [{"building_id": b, "name": _SEED_NAMES.get(b, b), "templates": len(_BUILDING_TEMPLATES[b])}
            for b in _BUILDING_TEMPLATES]


def seed_templates(building_id: str) -> List[Template]:
    """The SEED (starter-pack) templates for a building_id — used to clone into a new building."""
    return list(_BUILDING_TEMPLATES.get(building_id, []))


# Custom (builder-created) templates live in the DB. The API sets this loader at startup so
# DB templates are visible EVERYWHERE templates_for is used (forms, analyzers, agents) — a
# custom template with the same id overrides the code default. Loader unset → code only.
_CUSTOM_LOADER = None


def set_custom_loader(loader) -> None:
    """loader(building_id) -> List[Template] (from the DB). Pass None to disable."""
    global _CUSTOM_LOADER
    _CUSTOM_LOADER = loader


def templates_for(building_id: str = "one-anthem") -> List[Template]:
    code = list(_BUILDING_TEMPLATES.get(building_id, []))
    if _CUSTOM_LOADER is None:
        return code
    try:
        custom = _CUSTOM_LOADER(building_id) or []
    except Exception:
        custom = []
    by_id = {t.template_id: t for t in code}
    for t in custom:                       # custom overrides a same-id code template
        by_id[t.template_id] = t
    # keep code order first, then any new custom ones
    ordered = [by_id[t.template_id] for t in code]
    ordered += [t for t in custom if t.template_id not in {c.template_id for c in code}]
    return ordered


def assets_in(building_id: str = "one-anthem") -> List[str]:
    """Distinct assets the checklists touch — the building's asset registry (Phase S)."""
    seen: List[str] = []
    for t in templates_for(building_id):
        for it in t.all_items():
            if it.asset and it.asset not in seen:
                seen.append(it.asset)
    return sorted(seen)


def items_for_asset(building_id: str, asset: str) -> List[tuple]:
    """(template_id, Item) for every item about this asset — drives asset history."""
    out = []
    for t in templates_for(building_id):
        for it in t.all_items():
            if it.asset == asset:
                out.append((t.template_id, it))
    return out


def get_template(template_id: str, building_id: str = "one-anthem") -> Optional[Template]:
    return next((t for t in templates_for(building_id) if t.template_id == template_id), None)


# ── entry evaluation (rules on the operator's OWN input) ──────────────────
def entry_is_issue(item: Item, value: Any, status: str = "") -> bool:
    """An entry is an issue if the operator marked it 'issue', or the value they
    entered is one of the item's declared alert-states (fire panel OFF, leakage
    DETECTED…). No sensor required — the human's own input trips the flag."""
    if (status or "").lower() == "issue":
        return True
    if item.alert_states and value is not None:
        return str(value).strip().upper() in {s.upper() for s in item.alert_states}
    return False


def run_summary(template: Template, entries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Completion + issues for a run. `entries` = {item_id: {value, status, note, ts}}.
    Completion counts items that have an entry; issues are flagged entries."""
    def _filled(e) -> bool:
        # A photo-only stub (no value, no status) does NOT count as completed.
        return bool(e) and (str(e.get("value", "")).strip() != "" or bool(e.get("status")))

    items = template.all_items()
    total = len(items)
    done = sum(1 for it in items if _filled(entries.get(it.item_id)))
    issues = []
    for it in items:
        e = entries.get(it.item_id)
        if not e:
            continue
        if entry_is_issue(it, e.get("value"), e.get("status", "")):
            issues.append({"item_id": it.item_id, "label": it.label,
                           "value": e.get("value"), "note": e.get("note", "")})
    return {
        "total": total, "done": done,
        "completion_pct": round(100.0 * done / total, 0) if total else 100.0,
        "missing": [it.item_id for it in items if not _filled(entries.get(it.item_id))],
        "issues": issues,
    }


# ── PPM planner (Phase S) — date-based + condition-based (run hours) ──────
def ppm_status(sched: Dict[str, Any], today: str, latest_run_hours: float = None) -> Dict[str, Any]:
    """Compute due/overdue for one asset's PPM. Date-based from interval_days+last_done;
    condition-based from run_hours_limit+latest_run_hours. status ∈ ok|due_soon|overdue|unscheduled."""
    from datetime import date, timedelta
    out: Dict[str, Any] = {"asset": sched.get("asset"), "interval_days": sched.get("interval_days"),
                           "last_done": sched.get("last_done"), "run_hours_limit": sched.get("run_hours_limit"),
                           "latest_run_hours": latest_run_hours, "due_date": None, "days_remaining": None,
                           "hours_remaining": None, "overdue": False, "status": "unscheduled"}
    today_d = date.fromisoformat(today)
    statuses = []
    iv, ld = sched.get("interval_days"), sched.get("last_done")
    if iv and ld:
        due = date.fromisoformat(ld[:10]) + timedelta(days=int(iv))
        dr = (due - today_d).days
        out["due_date"] = due.isoformat(); out["days_remaining"] = dr
        statuses.append("overdue" if dr < 0 else ("due_soon" if dr <= 7 else "ok"))
    lim = sched.get("run_hours_limit")
    if lim and latest_run_hours is not None:
        hr = float(lim) - float(latest_run_hours)
        out["hours_remaining"] = round(hr, 1)
        statuses.append("overdue" if hr < 0 else ("due_soon" if hr <= 25 else "ok"))
    if statuses:
        out["status"] = "overdue" if "overdue" in statuses else (
            "due_soon" if "due_soon" in statuses else "ok")
        out["overdue"] = out["status"] == "overdue"
    return out


# ── issue lifecycle ───────────────────────────────────────────────────────
ISSUE_STATUSES = ["open", "assigned", "in_progress", "resolved"]
# Allowed targets from each status (reopen + quick-close permitted).
_ISSUE_NEXT = {
    "open": {"assigned", "in_progress", "resolved"},
    "assigned": {"in_progress", "resolved", "open"},
    "in_progress": {"resolved", "assigned", "open"},
    "resolved": {"open"},     # reopen
}


def valid_issue_transition(current: str, target: str) -> bool:
    return target in _ISSUE_NEXT.get(current, set())


def manager_digest(runs_view: List[Dict[str, Any]], date: str) -> str:
    """Plain-language WhatsApp digest of the day's checklists for the manager:
    completion per shift, flagged issues, what's not started, sign-off status."""
    daily = [r for r in runs_view if r.get("template_id", "").startswith("ANTHEM-SHIFT")]
    L = [f"*Checklist summary — {date}*", ""]
    all_issues = []
    if not runs_view:
        L.append("No checklists started yet today.")
        return "\n".join(L)
    for r in runs_view:
        emoji = "✅" if r["status"] == "submitted" and not r["issues"] else (
                "⚠️" if r["issues"] else "🟡")
        signed = len(r.get("signoffs", []))
        tail = f" · {len(r['issues'])} issue(s)" if r["issues"] else ""
        sign = f" · {signed} sign-off(s)" if signed else " · unsigned"
        who = f" · 👤 {r['assignee']}" if r.get("assignee") else " · ⚠️ unassigned"
        L.append(f"{emoji} {r['name']}: {r['completion_pct']:.0f}% ({r['status']}){who}{tail}{sign}")
        all_issues += [f"• {i['label']}" + (f": {i['value']}" if i.get('value') else "")
                       for i in r["issues"]]
    if all_issues:
        L += ["", "*Flagged:*"] + all_issues
    return "\n".join(L)
