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

    def to_dict(self) -> Dict[str, Any]:
        return {"item_id": self.item_id, "label": self.label, "kind": self.kind,
                "unit": self.unit, "options": self.options, "alert_states": self.alert_states}


@dataclass
class Section:
    name: str
    items: List[Item]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "items": [i.to_dict() for i in self.items]}


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


# building_id → its templates. Add new buildings here as they onboard.
_BUILDING_TEMPLATES: Dict[str, List[Template]] = {
    "one-anthem": [_shift1(), _shift2(), _shift3(), _ppm()],
}


def templates_for(building_id: str = "one-anthem") -> List[Template]:
    return _BUILDING_TEMPLATES.get(building_id, [])


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
    items = template.all_items()
    total = len(items)
    done = sum(1 for it in items if it.item_id in entries)
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
        "missing": [it.item_id for it in items if it.item_id not in entries],
        "issues": issues,
    }


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
        L.append(f"{emoji} {r['name']}: {r['completion_pct']:.0f}% ({r['status']}){tail}{sign}")
        all_issues += [f"• {i['label']}" + (f": {i['value']}" if i.get('value') else "")
                       for i in r["issues"]]
    if all_issues:
        L += ["", "*Flagged:*"] + all_issues
    return "\n".join(L)
