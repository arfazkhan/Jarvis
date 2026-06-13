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
    cadence: str                           # daily | quarterly
    sections: List[Section]
    timing: str = ""                       # shift window, informational
    signoff_roles: List[str] = field(default_factory=list)
    per_asset: List[str] = field(default_factory=list)  # PPM: one run-block per asset

    def all_items(self) -> List[Item]:
        return [it for s in self.sections for it in s.items]

    def to_dict(self) -> Dict[str, Any]:
        return {"template_id": self.template_id, "name": self.name, "cadence": self.cadence,
                "timing": self.timing, "signoff_roles": self.signoff_roles,
                "per_asset": self.per_asset, "sections": [s.to_dict() for s in self.sections]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Template":
        return cls(template_id=str(d["template_id"]), name=str(d.get("name", "")),
                   cadence=str(d.get("cadence", "daily")),
                   sections=[Section.from_dict(s) for s in d.get("sections", [])],
                   timing=str(d.get("timing", "")), signoff_roles=list(d.get("signoff_roles", [])),
                   per_asset=list(d.get("per_asset", [])))


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


# convenience builders
def _tick(i, l): return Item(i, l, "tick")
def _read(i, l, unit): return Item(i, l, "reading", unit=unit)
def _state(i, l, options, alert=()): return Item(i, l, "state", options=list(options), alert_states=list(alert))


_DAILY_SIGNOFF = ["technician", "supervisor", "caretaker", "engineer", "president"]


# ── One Anthem Apartments — the four real documents ───────────────────────
def _shift1() -> Template:
    return Template(
        "ANTHEM-SHIFT-1", "Shift I — Daily Operations", "daily", timing="08:00 AM – 04:15 PM",
        signoff_roles=_DAILY_SIGNOFF, sections=[
            Section("Fire Pump Room", [
                _read("fp_diesel_fuel", "Diesel pump fuel level", "%"),
                _read("fp_coolant", "Coolant level", "%"),
                _read("fp_oil", "Oil level", "%"),
                _state("fp_main_pump", "Main pump", ["OK", "RUNNING", "FAULT"], alert=["FAULT"]),
                _state("fp_standby_pump", "Standby pump", ["OK", "RUNNING", "FAULT"], alert=["FAULT"]),
                _state("fp_jockey_pump", "Jockey pump", ["OK", "RUNNING", "FAULT"], alert=["FAULT"]),
            ]),
            Section("Swimming Pool", [
                _tick("pool_vacuum", "Vacuuming"),
                _read("pool_ph", "pH reading", "pH"),
                _tick("pool_backwash", "Backwash"),
                _state("pool_filtration", "Filtration", ["ON", "OFF"], alert=["OFF"]),
                _tick("pool_chlorination", "Chlorination"),
            ]),
            Section("General Facility", [
                _state("gen_electrical", "Electrical equipment status", ["OK", "FAULT"], alert=["FAULT"]),
                _state("gen_fire_alarm", "Fire alarm panel health (main ON / no fault)", ["ON", "OFF", "FAULT"], alert=["OFF", "FAULT"]),
                _tick("gen_mygate", "MyGate ticket monitoring"),
                _read("gen_oh_tank", "OH tank water level", "%"),
                _state("gen_borewell", "Borewell status", ["OK", "OFF"], alert=["OFF"]),
            ]),
        ])


def _shift2() -> Template:
    return Template(
        "ANTHEM-SHIFT-2", "Shift II — Daily Operations", "daily", timing="12:00 AM – 08:15 PM",
        signoff_roles=_DAILY_SIGNOFF, sections=[
            Section("Water Treatment Plant", [
                _tick("wtp_backwash", "WTP backwash"),
                _tick("wtp_chemical", "Chemical addition"),
                _state("wtp_filtration", "Filtration", ["ON", "OFF"], alert=["OFF"]),
                _state("wtp_leakage", "Leakage detected", ["NIL", "DETECTED"], alert=["DETECTED"]),
            ]),
            Section("Electrical Infrastructure", [
                _read("el_transformer", "Main transformer reading", "V"),
                _tick("el_room1", "Electrical room-1 inspection"),
                _tick("el_room1_msb", "Room-1 MSB inspection"),
                _tick("el_room1_ssb", "Room-1 SSB inspection"),
                _tick("el_room2", "Electrical room-2 inspection"),
                _tick("el_room2_msb", "Room-2 MSB inspection"),
                _tick("el_room2_ssb", "Room-2 SSB inspection"),
                _tick("el_room3", "Electrical room-3 inspection"),
                _tick("el_room3_msb", "Room-3 MSB inspection"),
                _tick("el_room3_ssb", "Room-3 SSB inspection"),
                _state("el_dg1_panel", "DG-1 panel", ["OK", "FAULT"], alert=["FAULT"]),
                _state("el_dg2_panel", "DG-2 panel", ["OK", "FAULT"], alert=["FAULT"]),
            ]),
            Section("General Operations", [
                _state("g2_fire_alarm", "Fire alarm panel health (main ON / no fault)", ["ON", "OFF", "FAULT"], alert=["OFF", "FAULT"]),
                _tick("g2_mygate", "MyGate ticket review"),
                _tick("g2_lift", "Lift shaft inspection"),
                _read("g2_gf_raw_tank", "GF raw tank water level", "%"),
                _read("g2_gf_filter_tank", "GF filter tank water level", "%"),
                _read("g2_oh_tank", "OH tank water level", "%"),
                _state("g2_japan_water", "Japan water status", ["OK", "NIL"], alert=["NIL"]),
                _state("g2_borewell", "Borewell pumping status", ["OK", "OFF"], alert=["OFF"]),
            ]),
        ])


def _shift3() -> Template:
    return Template(
        "ANTHEM-SHIFT-3", "Shift III — Daily Operations", "daily", timing="08:00 PM – 08:15 AM",
        signoff_roles=_DAILY_SIGNOFF, sections=[
            Section("Diesel Generators", [
                _state("dg1_status", "DG-1 monitoring", ["OK", "RUNNING", "FAULT"], alert=["FAULT"]),
                _state("dg2_status", "DG-2 monitoring", ["OK", "RUNNING", "FAULT"], alert=["FAULT"]),
                _read("dg_run_hours", "Run hours", "hrs"),
                _read("dg_battery_v", "Battery voltage", "V"),
                _read("dg_oil", "Oil level", "%"),
                _read("dg_coolant", "Coolant level", "%"),
                _read("dg_fuel", "Fuel level", "%"),
            ]),
            Section("Sewage Treatment Plant", [
                _tick("stp_psf_backwash", "PSF backwash"),
                _tick("stp_acf_backwash", "ACF backwash"),
                _tick("stp_chemical", "Chemical dosing"),
                _state("stp_blower", "Blower inspection", ["OK", "FAULT"], alert=["FAULT"]),
                _state("stp_sludge", "Sludge monitoring", ["NORMAL", "HIGH"], alert=["HIGH"]),
                _state("stp_leakage", "Leakage check", ["NIL", "DETECTED"], alert=["DETECTED"]),
                _state("stp_overflow", "Overflow check", ["NIL", "DETECTED"], alert=["DETECTED"]),
            ]),
            Section("Night Operations", [
                _tick("night_duct", "Duct inspection"),
                _tick("night_server", "Server room inspection"),
                _tick("night_amenities", "Amenities closing/opening"),
                _state("night_fire", "Fire system check", ["OK", "FAULT"], alert=["FAULT"]),
                _state("night_water", "Water system check", ["OK", "FAULT"], alert=["FAULT"]),
            ]),
        ])


def _ppm() -> Template:
    """Quarterly preventive maintenance — asset-based. One run covers a panel asset;
    the 10 sections are applied per asset (transformer/MSB/SSB/DG/distribution panels)."""
    return Template(
        "ANTHEM-PPM", "Quarterly Preventive Maintenance", "quarterly",
        timing="Every 3 months",
        signoff_roles=["technician", "engineer", "president"],
        per_asset=["Transformer Panel", "MSB", "SSB", "DG Panel", "Distribution Panel"],
        sections=[
            Section("1. Safety & Preparation", [
                _tick("ppm_work_permit", "Work permit obtained"),
                _tick("ppm_isolation", "Isolation done"),
                _tick("ppm_loto", "LOTO applied"),
                _tick("ppm_ppe", "PPE worn"),
            ]),
            Section("2. Cleaning & Physical Inspection", [
                _state("ppm_dust", "Dust", ["CLEAN", "DUSTY"], alert=["DUSTY"]),
                _state("ppm_moisture", "Moisture", ["DRY", "WET"], alert=["WET"]),
                _state("ppm_corrosion", "Corrosion", ["NIL", "FOUND"], alert=["FOUND"]),
                _state("ppm_panel_condition", "Panel condition", ["OK", "DAMAGED"], alert=["DAMAGED"]),
            ]),
            Section("3. Mechanical Tightness", [
                _state("ppm_busbars", "Busbars", ["TIGHT", "LOOSE"], alert=["LOOSE"]),
                _state("ppm_cable_term", "Cable terminations", ["TIGHT", "LOOSE"], alert=["LOOSE"]),
                _state("ppm_earth_bars", "Earth bars", ["TIGHT", "LOOSE"], alert=["LOOSE"]),
            ]),
            Section("4. Thermal Inspection", [
                _state("ppm_hotspots", "Hotspots", ["NIL", "FOUND"], alert=["FOUND"]),
                _state("ppm_load_balance", "Load balance", ["OK", "IMBALANCED"], alert=["IMBALANCED"]),
                _state("ppm_overheating", "Overheating", ["NIL", "FOUND"], alert=["FOUND"]),
            ]),
            Section("5. Electrical Components", [
                _state("ppm_breakers", "Breakers", ["OK", "FAULT"], alert=["FAULT"]),
                _state("ppm_relays", "Relays", ["OK", "FAULT"], alert=["FAULT"]),
                _state("ppm_contactors", "Contactors", ["OK", "FAULT"], alert=["FAULT"]),
                _state("ppm_lamps", "Indicator lamps", ["OK", "FAULT"], alert=["FAULT"]),
            ]),
            Section("6. Earthing & Protection", [
                _read("ppm_earth_resistance", "Earthing resistance", "ohm"),
                _state("ppm_elcb", "ELCB/RCCB testing", ["PASS", "FAIL"], alert=["FAIL"]),
            ]),
            Section("7. Wiring & Insulation", [
                _state("ppm_loose_wiring", "Loose wiring", ["NIL", "FOUND"], alert=["FOUND"]),
                _state("ppm_insulation", "Damaged insulation", ["NIL", "FOUND"], alert=["FOUND"]),
                _state("ppm_burn_marks", "Burn marks", ["NIL", "FOUND"], alert=["FOUND"]),
            ]),
            Section("8. Metering", [
                _read("ppm_voltage", "Voltage", "V"),
                _read("ppm_current", "Current", "A"),
                _read("ppm_frequency", "Frequency", "Hz"),
                _read("ppm_pf", "Power factor", ""),
            ]),
            Section("9. Documentation", [
                _tick("ppm_labels", "Labels present"),
                _tick("ppm_circuit_id", "Circuit identification"),
                _tick("ppm_warning_signs", "Warning signs"),
            ]),
            Section("10. Corrective Actions", [
                Item("ppm_issues_found", "Issues found", "note"),
                Item("ppm_actions_taken", "Actions taken", "note"),
                Item("ppm_pending_work", "Pending work", "note"),
            ]),
        ])


# Phase-S asset tagging: map item_id → the canonical asset it's about, so readings/issues
# can be rolled up into per-asset history + health. (Shared DG readings → DG-1 primary.)
_ANTHEM_ASSET_MAP: Dict[str, str] = {
    # Shift I
    "fp_diesel_fuel": "FIRE-PUMP", "fp_coolant": "FIRE-PUMP", "fp_oil": "FIRE-PUMP",
    "fp_main_pump": "FIRE-PUMP", "fp_standby_pump": "FIRE-PUMP", "fp_jockey_pump": "FIRE-PUMP",
    "pool_vacuum": "POOL", "pool_ph": "POOL", "pool_backwash": "POOL",
    "pool_filtration": "POOL", "pool_chlorination": "POOL",
    "gen_fire_alarm": "FIRE-PANEL", "gen_oh_tank": "OH-TANK", "gen_borewell": "BOREWELL",
    # Shift II
    "wtp_backwash": "WTP", "wtp_chemical": "WTP", "wtp_filtration": "WTP", "wtp_leakage": "WTP",
    "el_transformer": "TRANSFORMER", "el_dg1_panel": "DG-1", "el_dg2_panel": "DG-2",
    "g2_fire_alarm": "FIRE-PANEL", "g2_lift": "LIFT", "g2_gf_raw_tank": "GF-RAW-TANK",
    "g2_gf_filter_tank": "GF-FILTER-TANK", "g2_oh_tank": "OH-TANK", "g2_borewell": "BOREWELL",
    # Shift III
    "dg1_status": "DG-1", "dg2_status": "DG-2", "dg_run_hours": "DG-1", "dg_battery_v": "DG-1",
    "dg_oil": "DG-1", "dg_coolant": "DG-1", "dg_fuel": "DG-1",
    "stp_psf_backwash": "STP", "stp_acf_backwash": "STP", "stp_chemical": "STP",
    "stp_blower": "STP", "stp_sludge": "STP", "stp_leakage": "STP", "stp_overflow": "STP",
}


def _tag_assets(templates: List[Template], amap: Dict[str, str]) -> List[Template]:
    for t in templates:
        for it in t.all_items():
            if it.item_id in amap:
                it.asset = amap[it.item_id]
    return templates


# building_id → its templates. Add new buildings here as they onboard.
_BUILDING_TEMPLATES: Dict[str, List[Template]] = {
    "one-anthem": _tag_assets([_shift1(), _shift2(), _shift3(), _ppm()], _ANTHEM_ASSET_MAP),
}


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
