"""
ArvisX work-order engine (Phase 3).

Turns active risks into trackable tickets. Each work order carries the grounded
(rules-floor, deterministic) advisory — cause + recommended action — so an FM or
vendor gets context, not just an alert. Lifecycle: open → ack → in_progress → done,
with dedup (one open WO per asset+risk-kind), auto-close when the risk clears, and
reopen on recurrence. No new ticket every poll for the same standing problem.

Deterministic + sync (uses the rules floor, not the LLM) so ticketing never blocks
on a model call.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Dict, List, Optional

from arvisx.advisory import _rules_floor
from arvisx.health import build_report
from arvisx.models import (
    Asset, Priority, Risk, ServiceType, Severity, WorkOrder, WorkOrderStatus,
)

_PRIORITY = {
    Severity.CRITICAL: Priority.P1,
    Severity.WARNING: Priority.P2,
    Severity.MAINTENANCE: Priority.P3,
    Severity.INFO: Priority.P4,
}
_ACTIVE = (WorkOrderStatus.OPEN, WorkOrderStatus.ACK, WorkOrderStatus.IN_PROGRESS)


def risk_signature(risk: Risk) -> str:
    """Stable (asset, risk-kind) key: the message with the asset name stripped and
    numbers normalized, so the same standing problem maps to one ticket across polls."""
    stem = risk.message.replace(risk.asset_name, "").strip().lower()
    stem = re.sub(r"\d+", "#", stem)               # '8600h' / '11 days' → '#h' / '# days'
    stem = re.sub(r"\s+", " ", stem).strip(" -:")
    return f"{risk.asset_id}::{stem}"


class WorkOrderStore:
    def __init__(self):
        self._by_sig: Dict[str, WorkOrder] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def _next_id(self) -> str:
        self._seq += 1
        return f"WO-{self._seq:04d}"

    def all(self) -> List[WorkOrder]:
        with self._lock:
            return sorted(self._by_sig.values(),
                          key=lambda w: (w.priority.value, w.created_at))

    def get(self, wo_id: str) -> Optional[WorkOrder]:
        return next((w for w in self._by_sig.values() if w.wo_id == wo_id), None)

    def close_with_cause(self, wo_id: str, actual_cause: str, action: str = "",
                         skillbook=None, by: str = "vendor") -> Optional[WorkOrder]:
        """Outcome feedback: close a ticket with the CONFIRMED cause → teach the skillbook
        so the next occurrence on this equipment class leads with the real cause."""
        with self._lock:
            wo = next((w for w in self._by_sig.values() if w.wo_id == wo_id), None)
            if wo is None:
                return None
            wo.status = WorkOrderStatus.DONE
            wo.updated_at = datetime.now()
            wo.cause = actual_cause or wo.cause
            if action:
                wo.recommended_action = action
            wo.history.append({"ts": wo.updated_at.isoformat(),
                               "event": f"closed — confirmed cause: {actual_cause}", "by": by})
        if skillbook is not None and wo.asset_type:
            symptom = wo.signature.split("::", 1)[1] if "::" in wo.signature else wo.title.lower()
            skillbook.record_confirmed(wo.asset_type, symptom, actual_cause,
                                       action or wo.recommended_action, source=by)
        return wo

    def save_to(self, db) -> None:
        from dataclasses import asdict
        for wo in self._by_sig.values():
            db.save_work_order(wo.wo_id, wo.signature, wo.status.value, asdict(wo))

    def load_from(self, db) -> int:
        for d in db.load_work_orders():
            try:
                wo = WorkOrder(
                    wo_id=d["wo_id"], asset_id=d["asset_id"], asset_name=d["asset_name"],
                    service=ServiceType(d["service"]), title=d["title"],
                    priority=Priority(d["priority"]), severity=Severity(d["severity"]),
                    cause=d["cause"], recommended_action=d["recommended_action"],
                    status=WorkOrderStatus(d["status"]), signature=d["signature"],
                    asset_type=d.get("asset_type", ""),
                    created_at=datetime.fromisoformat(d["created_at"]),
                    updated_at=datetime.fromisoformat(d["updated_at"]),
                    last_seen_at=datetime.fromisoformat(d["last_seen_at"]),
                    assignee=d.get("assignee"), history=d.get("history", []),
                )
                self._by_sig[wo.signature] = wo
                n = int(wo.wo_id.split("-")[1]) if "-" in wo.wo_id else 0
                self._seq = max(self._seq, n)
            except Exception:
                continue
        return len(self._by_sig)

    def set_status(self, wo_id: str, status: WorkOrderStatus, by: str = "operator") -> Optional[WorkOrder]:
        with self._lock:
            wo = next((w for w in self._by_sig.values() if w.wo_id == wo_id), None)
            if wo is None:
                return None
            wo.status = status
            wo.updated_at = datetime.now()
            wo.history.append({"ts": wo.updated_at.isoformat(), "event": f"status→{status.value}", "by": by})
            return wo


def open_work_order(store: WorkOrderStore, asset: Asset, risk: Risk, db=None, skillbook=None,
                    now: Optional[datetime] = None) -> WorkOrder:
    """Create ONE work order for a specific asset+risk (the per-risk 'Create work order'
    button), deduped by signature — returns the existing open WO if one already exists."""
    now = now or datetime.now()
    sig = risk_signature(risk)
    with store._lock:
        wo = store._by_sig.get(sig)
        if wo is not None and wo.status in _ACTIVE:
            return wo
        adv = _rules_floor(asset, [risk]) if asset else None
        wid = store._next_id()
        wo = WorkOrder(
            wo_id=wid, asset_id=risk.asset_id, asset_name=risk.asset_name, service=risk.service,
            title=risk.message, priority=_PRIORITY[risk.severity], severity=risk.severity,
            cause=(adv.root_cause if adv else risk.message),
            recommended_action=(adv.recommended_action if adv else (risk.detail or "Inspect.")),
            status=WorkOrderStatus.OPEN, signature=sig,
            asset_type=(asset.asset_type.value if asset else ""),
            created_at=now, updated_at=now, last_seen_at=now,
            history=[{"ts": now.isoformat(), "event": "opened (manual)", "by": "operator"}])
        store._by_sig[sig] = wo
    if db is not None:
        db.log_event(risk.asset_id, risk.asset_name, risk.service.value, risk.severity.value,
                     risk.message, risk.detail, now)
    if skillbook is not None and asset is not None and adv is not None:
        skillbook.record(asset, risk, adv.root_cause, adv.recommended_action, confirmed=False)
    return wo


def sync_workorders(assets: List[Asset], store: WorkOrderStore, now: Optional[datetime] = None,
                    zones=None, baselines=None, virtual: bool = False, fusion: bool = False,
                    db=None, skillbook=None) -> Dict[str, int]:
    """Reconcile work orders against the current risks: open new, refresh existing,
    reopen recurrences, auto-close cleared ones. Covers ALL risk sources — asset rules,
    drift, virtual sensors, ghost (zones), and fusion — when those flags/inputs are passed.
    Returns a counts summary."""
    now = now or datetime.now()
    rep = build_report(assets, now, baselines=baselines, virtual=virtual, zones=zones, fusion=fusion)
    by_id = {a.asset_id: a for a in assets}
    counts = {"opened": 0, "reopened": 0, "refreshed": 0, "auto_closed": 0}
    active_sigs = set()

    with store._lock:
        for risk in rep.risks:
            sig = risk_signature(risk)
            active_sigs.add(sig)
            wo = store._by_sig.get(sig)
            if wo is None:
                asset = by_id.get(risk.asset_id)
                # Asset risks → rules-floor advisory; ghost/fusion risks (zone or
                # already-grounded) carry their own cause+action in the risk detail.
                adv = _rules_floor(asset, [risk]) if asset else None
                wid = store._next_id()
                store._by_sig[sig] = WorkOrder(
                    wo_id=wid, asset_id=risk.asset_id, asset_name=risk.asset_name,
                    service=risk.service, title=risk.message, priority=_PRIORITY[risk.severity],
                    severity=risk.severity,
                    cause=(adv.root_cause if adv else risk.message),
                    recommended_action=(adv.recommended_action if adv else (risk.detail or "Inspect.")),
                    status=WorkOrderStatus.OPEN, signature=sig,
                    asset_type=(asset.asset_type.value if asset else ""),
                    created_at=now, updated_at=now, last_seen_at=now,
                    history=[{"ts": now.isoformat(), "event": "opened", "by": "arvisx"}],
                )
                counts["opened"] += 1
                # Institutional memory: log the fault event + record the (unconfirmed) pattern.
                if db is not None:
                    db.log_event(risk.asset_id, risk.asset_name, risk.service.value,
                                 risk.severity.value, risk.message, risk.detail, now)
                if skillbook is not None and asset is not None and adv is not None:
                    skillbook.record(asset, risk, adv.root_cause, adv.recommended_action, confirmed=False)
            elif wo.status in (WorkOrderStatus.DONE, WorkOrderStatus.CANCELLED):
                # Risk came back after the ticket was closed → reopen the same WO.
                wo.status = WorkOrderStatus.OPEN
                wo.updated_at = wo.last_seen_at = now
                wo.history.append({"ts": now.isoformat(), "event": "reopened (risk recurred)", "by": "arvisx"})
                counts["reopened"] += 1
            else:
                wo.last_seen_at = now
                counts["refreshed"] += 1

        # Auto-close active WOs whose risk is no longer present.
        for sig, wo in store._by_sig.items():
            if sig not in active_sigs and wo.status in _ACTIVE:
                wo.status = WorkOrderStatus.DONE
                wo.updated_at = now
                wo.history.append({"ts": now.isoformat(), "event": "auto-closed (risk cleared)", "by": "arvisx"})
                counts["auto_closed"] += 1

    return counts
