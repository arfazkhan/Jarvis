"""
FDD engine — runs the rule catalog over equipment frames.

Order per equipment:
  1. applicability (equipment kind, commissioned design, site parameters, points)
  2. sensor-validation sweep → per-sensor "untrustworthy" masks
  3. every mechanical rule, gated on proven operation, with samples from
     failed sensors removed (INVALID if too many are gone)
  4. confirmation (time-persistence) → PASS / FAIL

Nothing is assumed: a rule that cannot be judged says SKIP or INVALID and why.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from agent_commercial.fdd.finding import FaultFinding, Outcome
from agent_commercial.fdd.frame import EquipmentFrame, build_frame
from agent_commercial.fdd.gates import resolve_active_mask
from agent_commercial.fdd.rules import RULES, RuleContext, RuleSpec
from agent_commercial.fdd.rules.base import has
from agent_commercial.fdd.timeseries import confirm_fault, hours_true
from agent_commercial.semantics import PointRole, equipment_kind, get_role_registry

logger = logging.getLogger("arvis.fdd.engine")

# A mechanical rule whose running samples are mostly from failed sensors is not judged.
MAX_INVALID_SHARE = 0.5


def _roles_of(rule: RuleSpec) -> List[str]:
    names: List[str] = []
    for q in list(rule.required) + list(rule.optional):
        for x in (q if isinstance(q, tuple) else (q,)):
            names.append(x.value if isinstance(x, PointRole) else str(x))
    return names


def _missing(rule: RuleSpec, d: pd.DataFrame) -> List[str]:
    out = []
    for q in rule.required:
        options = q if isinstance(q, tuple) else (q,)
        if not any(has(d, x) for x in options):
            out.append("|".join(x.value if isinstance(x, PointRole) else str(x) for x in options))
    return out


class FDDEngine:
    def __init__(self, rules: Sequence[RuleSpec] = RULES, *, poll_seconds: float = 300.0,
                 allow_ungated: bool = False,
                 params_by_rule: Optional[Dict[str, Dict[str, float]]] = None,
                 enabled_rules: Optional[Iterable[str]] = None):
        self.rules = [r for r in rules if enabled_rules is None or r.id in set(enabled_rules)]
        self.poll_seconds = float(poll_seconds)
        self.allow_ungated = allow_ungated
        self.params_by_rule = params_by_rule or {}

    # ── one equipment ─────────────────────────────────────────────────────
    def evaluate(self, ef: EquipmentFrame) -> List[FaultFinding]:
        rules = [r for r in self.rules if ef.kind in r.equipment_kinds]
        invalid: Dict[str, pd.Series] = {}
        findings: List[FaultFinding] = []
        for rule in [r for r in rules if r.sensor_sweep]:
            f = self._run(rule, ef, invalid={})
            findings.append(f)
            for role, mask in f.metrics.pop("_confirmed_role_masks", {}).items():
                invalid[role] = (invalid[role] | mask) if role in invalid else mask
        for rule in [r for r in rules if not r.sensor_sweep]:
            findings.append(self._run(rule, ef, invalid))
        return findings

    def _finding(self, rule: RuleSpec, ef: EquipmentFrame, outcome: Outcome, reason: str = "",
                 **kw) -> FaultFinding:
        d = ef.frame
        used = {r: ef.points_used[r] for r in _roles_of(rule) if r in ef.points_used}
        return FaultFinding(
            rule_id=rule.id, title=rule.title, family=rule.family,
            equipment_id=ef.equipment_id, equipment_kind=ef.kind, outcome=outcome,
            reason=reason, summary=rule.summary, origin=rule.origin,
            root_cause_candidates=list(rule.root_cause_candidates),
            points_used=used,
            role_sources={r: ef.role_sources[r] for r in _roles_of(rule) if r in ef.role_sources},
            window_start=str(d.index.min()) if len(d) else None,
            window_end=str(d.index.max()) if len(d) else None,
            **kw)

    def _run(self, rule: RuleSpec, ef: EquipmentFrame, invalid: Dict[str, pd.Series]) -> FaultFinding:
        d = ef.frame
        if d.empty:
            return self._finding(rule, ef, Outcome.SKIP, "no telemetry in the analysis window")
        if rule.min_window_hours:
            span_h = (d.index.max() - d.index.min()).total_seconds() / 3600.0
            if span_h < rule.min_window_hours:
                return self._finding(rule, ef, Outcome.SKIP,
                                     f"needs ≥{rule.min_window_hours:g} h of data, have {span_h:.1f} h")
        if rule.requires_design:
            flag = ef.design_attributes.get(rule.requires_design)
            if flag is not True:
                state = "not declared" if flag is None else f"declared {flag!r}"
                return self._finding(rule, ef, Outcome.SKIP,
                                     f"design attribute '{rule.requires_design}' {state} for this unit")
        params = rule.resolved_params(self.params_by_rule.get(rule.id))
        missing_params = rule.missing_params(params)
        if missing_params:
            return self._finding(rule, ef, Outcome.SKIP,
                                 f"site parameter not configured: {', '.join(missing_params)}",
                                 params=params)
        missing = _missing(rule, d)
        if missing:
            return self._finding(rule, ef, Outcome.SKIP, f"missing points: {', '.join(missing)}",
                                 missing_roles=missing, params=params)

        active, gate_meta = resolve_active_mask(d, rule.id, rule.gate, poll_seconds=self.poll_seconds,
                                                params=params, allow_ungated=self.allow_ungated)
        fp = rule.fingerprint(params)
        if active is None:
            return self._finding(rule, ef, Outcome.SKIP, gate_meta.get("skip_reason", "not running"),
                                 params=params, params_fingerprint=fp,
                                 gate_source=gate_meta.get("gate_source", ""), metrics=gate_meta)

        ctx = RuleContext(poll_seconds=self.poll_seconds)
        try:
            raw = rule.compute(d, params, ctx)
        except Exception as e:  # a broken rule must be visible, not a silent PASS
            logger.warning("FDD rule %s failed on %s: %s", rule.id, ef.equipment_id, e)
            return self._finding(rule, ef, Outcome.SKIP, f"rule error: {type(e).__name__}: {e}",
                                 params=params, params_fingerprint=fp)
        raw = raw.reindex(d.index).fillna(False).astype(bool)
        confirm_s = float(params.get("confirm_seconds", rule.confirm_seconds) or 0.0)

        metrics: Dict[str, Any] = {**gate_meta, **ctx.notes}
        invalid_roles: List[str] = []
        invalid_n = 0
        if not rule.sensor_sweep:
            bad = pd.Series(False, index=d.index)
            for role in _roles_of(rule):
                m = invalid.get(role)
                if m is not None and bool((m & active).any()):
                    invalid_roles.append(role)
                    bad = bad | m.reindex(d.index).fillna(False)
            invalid_n = int((active & bad).sum())
            n_active = int(active.sum())
            active = active & ~bad
            if invalid_roles and (n_active == 0 or invalid_n / max(n_active, 1) > MAX_INVALID_SHARE):
                return self._finding(
                    rule, ef, Outcome.INVALID,
                    f"sensor validation failed for {', '.join(invalid_roles)} on "
                    f"{100 * invalid_n / max(n_active, 1):.0f}% of running samples",
                    invalid_roles=invalid_roles, invalid_sample_count=invalid_n,
                    params=params, params_fingerprint=fp, gate_source=gate_meta.get("gate_source", ""),
                    metrics=metrics)
        else:
            confirmed_roles: Dict[str, pd.Series] = {}
            evidence = []
            for role, rmask in ctx.per_role_masks.items():
                rc = confirm_fault(rmask.reindex(d.index).fillna(False) & active,
                                   poll_seconds=self.poll_seconds, confirm_seconds=confirm_s)
                confirmed_roles[role] = rc
                evidence.append({"role": role, "point_id": ef.points_used.get(role),
                                 "fault_hours": round(hours_true(rc, self.poll_seconds), 2),
                                 "faulted": bool(rc.any())})
            metrics["sensors"] = evidence
            metrics["_confirmed_role_masks"] = confirmed_roles
            invalid_roles = [e["role"] for e in evidence if e["faulted"]]

        confirmed = confirm_fault(raw & active, poll_seconds=self.poll_seconds, confirm_seconds=confirm_s)
        active_h = hours_true(active, self.poll_seconds)
        fault_h = hours_true(confirmed, self.poll_seconds)
        n_fault = int(confirmed.sum())
        idx = confirmed.index[confirmed]
        return self._finding(
            rule, ef, Outcome.FAIL if n_fault else Outcome.PASS,
            "" if n_fault else "no confirmed fault",
            fault_hours=round(fault_h, 2), fault_pct=round(100.0 * fault_h / active_h, 1) if active_h else 0.0,
            active_hours=round(active_h, 2), sample_count=int(active.sum()), fault_sample_count=n_fault,
            invalid_sample_count=invalid_n, invalid_roles=invalid_roles,
            first_fault=str(idx[0]) if n_fault else None, last_fault=str(idx[-1]) if n_fault else None,
            params=params, params_fingerprint=fp, gate_source=gate_meta.get("gate_source", ""),
            metrics=metrics)

    # ── whole building ────────────────────────────────────────────────────
    async def run_building(self, bms_state: Any, database: Any, *, hours: float = 24.0,
                           resample_seconds: Optional[int] = None,
                           equipment_ids: Optional[Iterable[str]] = None) -> List[FaultFinding]:
        """Evaluate every equipment with stored telemetry in the last ``hours``."""
        resample = int(resample_seconds or self.poll_seconds)
        registry = get_role_registry(bms_state)
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = await database._get_async_connection()
        async with conn.execute(
                "SELECT DISTINCT equipment_id FROM data_points "
                "WHERE timestamp > ? AND equipment_id IS NOT NULL AND equipment_id != ''",
                (cutoff,)) as cur:
            eq_ids = [r[0] for r in await cur.fetchall()]
        if equipment_ids is not None:
            wanted = set(equipment_ids)
            eq_ids = [e for e in eq_ids if e in wanted]

        frames: Dict[str, EquipmentFrame] = {}
        for eid in eq_ids:
            eq = None
            try:
                eq = await bms_state.get_equipment(eid)
            except Exception:
                eq = None
            kind = equipment_kind(getattr(eq, "equipment_type", None), eid)
            async with conn.execute(
                    "SELECT point_id, value, unit, timestamp FROM data_points "
                    "WHERE equipment_id = ? AND timestamp > ? ORDER BY timestamp ASC",
                    (eid, cutoff)) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
            frames[eid] = build_frame(
                eid, kind, rows, registry, resample_seconds=resample,
                design_attributes=getattr(eq, "design_attributes", None) or {},
                parent_id=getattr(eq, "parent_equipment_id", None))

        enrich_context(frames)
        findings: List[FaultFinding] = []
        for ef in frames.values():
            findings.extend(self.evaluate(ef))
        return findings


def enrich_context(frames: Dict[str, EquipmentFrame]) -> None:
    """Topology and building context used by cross-equipment rules."""
    sat = PointRole.SUPPLY_AIR_TEMP.value
    # Terminal units get their parent AHU's supply-air temperature.
    for ef in frames.values():
        parent = frames.get(ef.parent_id) if ef.parent_id else None
        if parent is not None and sat in parent.frame.columns and ef.kind in ("vav", "fcu"):
            ef.add_context("ctx:parent-supply-air-temp", parent.frame[sat])
    # Chillers get the building's largest cooling-valve position (any demand at all?).
    clg = PointRole.COOLING_VALVE.value
    valves = [ef.frame[clg] for ef in frames.values()
              if ef.kind in ("ahu", "fcu") and clg in ef.frame.columns]
    if valves:
        demand = pd.concat(valves, axis=1).max(axis=1)
        for ef in frames.values():
            if ef.kind == "chiller":
                ef.add_context("ctx:building-max-cooling-valve", demand)
                ef.frame.attrs["cooling_valves_considered"] = len(valves)
