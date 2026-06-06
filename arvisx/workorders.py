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
    Asset, Priority, Risk, Severity, WorkOrder, WorkOrderStatus,
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

    def set_status(self, wo_id: str, status: WorkOrderStatus, by: str = "operator") -> Optional[WorkOrder]:
        with self._lock:
            wo = next((w for w in self._by_sig.values() if w.wo_id == wo_id), None)
            if wo is None:
                return None
            wo.status = status
            wo.updated_at = datetime.now()
            wo.history.append({"ts": wo.updated_at.isoformat(), "event": f"status→{status.value}", "by": by})
            return wo


def sync_workorders(assets: List[Asset], store: WorkOrderStore, now: Optional[datetime] = None) -> Dict[str, int]:
    """Reconcile work orders against the current risks: open new, refresh existing,
    reopen recurrences, auto-close cleared ones. Returns a counts summary."""
    now = now or datetime.now()
    rep = build_report(assets, now)
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
                adv = _rules_floor(asset, [risk]) if asset else None
                wid = store._next_id()
                store._by_sig[sig] = WorkOrder(
                    wo_id=wid, asset_id=risk.asset_id, asset_name=risk.asset_name,
                    service=risk.service, title=risk.message, priority=_PRIORITY[risk.severity],
                    severity=risk.severity,
                    cause=(adv.root_cause if adv else risk.detail or risk.message),
                    recommended_action=(adv.recommended_action if adv else "Inspect the asset."),
                    status=WorkOrderStatus.OPEN, signature=sig,
                    created_at=now, updated_at=now, last_seen_at=now,
                    history=[{"ts": now.isoformat(), "event": "opened", "by": "arvisx"}],
                )
                counts["opened"] += 1
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
