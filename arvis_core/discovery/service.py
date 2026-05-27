"""DiscoveryService — orchestration glue.

Responsibilities:
- Idempotency check (don't re-register already-known points)
- Rate-limit gate
- Probe via PointInventoryProvider
- BACnet object-type allowlist check
- Classify via HybridClassifier
- Two-person rule for writable points on critical equipment
- Auto-register (PROBATION) or escalate for operator approval
- All actions audited to DiscoveryAuditLog
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from arvis_core.discovery.audit import DiscoveryAuditLog
from arvis_core.discovery.classifier import (
    ClassificationResult,
    HybridClassifier,
    PointCriticality,
)
from arvis_core.discovery.registry import (
    ARVISPollRegistry,
    PointState,
    RegisteredPoint,
)
from arvis_core.discovery.security import (
    RateLimiter,
    is_allowed_object_type,
    is_critical_equipment,
)

logger = logging.getLogger("arvis.discovery.service")


@dataclass
class DiscoveryDecision:
    point_id: str
    classification: Optional[ClassificationResult]
    registered: bool
    requires_operator_approval: bool
    operator_notified: bool
    reason: str
    audit_entry_id: Optional[str] = None

    def to_dict(self) -> dict:
        cls_dict = None
        if self.classification is not None:
            cls_dict = {
                "criticality": self.classification.criticality.value,
                "cadence_seconds": self.classification.cadence_seconds,
                "confidence": self.classification.confidence,
                "method": self.classification.method,
                "reasoning": self.classification.reasoning,
            }
        return {
            "point_id": self.point_id,
            "classification": cls_dict,
            "registered": self.registered,
            "requires_operator_approval": self.requires_operator_approval,
            "operator_notified": self.operator_notified,
            "reason": self.reason,
            "audit_entry_id": self.audit_entry_id,
        }


class DiscoveryService:
    def __init__(
        self,
        provider,
        registry: ARVISPollRegistry,
        classifier: HybridClassifier,
        audit_log: DiscoveryAuditLog,
        rate_limiter: RateLimiter,
        agent_id: str = "discovery_agent",
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.classifier = classifier
        self.audit = audit_log
        self.rate_limiter = rate_limiter
        self.agent_id = agent_id

    async def discover_blind_spot(
        self, point_id: str, source: str = "reactive"
    ) -> DiscoveryDecision:
        """Main entry: probe a candidate point, classify, register or escalate."""
        equipment_id = point_id.split("/")[0] if "/" in point_id else "unknown"

        # 1. Idempotency
        if self.registry.is_registered(point_id):
            return DiscoveryDecision(
                point_id=point_id,
                classification=None,
                registered=False,
                requires_operator_approval=False,
                operator_notified=False,
                reason="already registered (idempotent)",
            )

        # 2. Rate-limit gate
        ok, reason = self.rate_limiter.check_and_record(self.agent_id, equipment_id)
        if not ok:
            entry = self.audit.append(
                self.agent_id, "rate_limited",
                {"reason": reason, "source": source},
                point_id=point_id, equipment_id=equipment_id, outcome="rejected",
            )
            return DiscoveryDecision(
                point_id, None, False, False, False, reason or "rate limited", entry,
            )

        # 3. Probe
        try:
            points = await self.provider.list_points(device_filter=equipment_id)
            point_meta = next((p for p in points if p.point_id == point_id), None)
        except Exception as e:
            self.audit.append(
                self.agent_id, "probe_failed",
                {"error": str(e), "source": source},
                point_id=point_id, equipment_id=equipment_id, outcome="error",
            )
            return DiscoveryDecision(
                point_id, None, False, False, False, f"probe failed: {e}",
            )

        if point_meta is None:
            self.audit.append(
                self.agent_id, "probe_not_found",
                {"source": source},
                point_id=point_id, equipment_id=equipment_id, outcome="not_found",
            )
            return DiscoveryDecision(
                point_id, None, False, False, False,
                "point not in BACnet inventory",
            )

        # 4. BACnet object-type allowlist
        bobj = getattr(point_meta, "bacnet_object_type", None)
        if bobj and not is_allowed_object_type(bobj):
            self.audit.append(
                self.agent_id, "object_type_rejected",
                {"object_type": bobj},
                point_id=point_id, equipment_id=equipment_id, outcome="rejected",
            )
            return DiscoveryDecision(
                point_id, None, False, False, False,
                f"object type {bobj} not allowed",
            )

        # 5. Classify
        cls = self.classifier.classify(point_meta)

        # 6. Two-person rule: writable points on critical equipment
        if (
            is_critical_equipment(equipment_id)
            and cls.criticality == PointCriticality.CRITICAL
            and bobj in ("analogOutput", "binaryOutput", "multiStateOutput")
        ):
            entry = self.audit.append(
                self.agent_id, "operator_approval_required",
                {
                    "reason": "writable point on critical equipment",
                    "classification": cls.criticality.value,
                    "object_type": bobj,
                },
                point_id=point_id, equipment_id=equipment_id,
                outcome="pending_approval",
            )
            return DiscoveryDecision(
                point_id, cls, False, True, True,
                "writable point on critical equipment — operator approval required",
                entry,
            )

        # 7. Unknown classification → operator approval
        if cls.criticality == PointCriticality.UNKNOWN:
            entry = self.audit.append(
                self.agent_id, "operator_approval_required",
                {"reason": "no rule match"},
                point_id=point_id, equipment_id=equipment_id,
                outcome="pending_approval",
            )
            return DiscoveryDecision(
                point_id, cls, False, True, True,
                "classification unknown — operator approval required", entry,
            )

        # 8. Auto-register (PROBATION). Critical monitoring-only on critical
        #    equipment is permitted (operator notified, no approval gate).
        reg = RegisteredPoint(
            point_id=point_id,
            equipment_id=equipment_id,
            cadence_seconds=cls.cadence_seconds,
            priority=cls.criticality.value,
            initial_value=getattr(point_meta, "last_value", None),
        )
        success, msg = self.registry.register(reg)
        if not success:
            return DiscoveryDecision(
                point_id, cls, False, False, False, msg,
            )

        entry = self.audit.append(
            self.agent_id, "auto_registered",
            {
                "cadence": cls.cadence_seconds,
                "criticality": cls.criticality.value,
                "confidence": cls.confidence,
                "method": cls.method,
                "probation_ends": reg.probation_ends_at,
                "source": source,
                "critical_equipment": is_critical_equipment(equipment_id),
            },
            point_id=point_id, equipment_id=equipment_id, outcome="registered",
        )

        notify = is_critical_equipment(equipment_id) or cls.criticality == PointCriticality.CRITICAL
        return DiscoveryDecision(
            point_id, cls, True, False, notify,
            "auto-registered (24h probation)", entry,
        )

    async def scheduled_inventory_scan(self) -> List[DiscoveryDecision]:
        """Hourly job: diff provider inventory vs registry; onboard unmapped
        critical points (rule-classified) without operator gate (monitoring-
        only path)."""
        decisions: List[DiscoveryDecision] = []
        try:
            inventory = await self.provider.list_points()
        except Exception as e:
            logger.warning("[Discovery] scheduled scan: provider failed: %s", e)
            return decisions

        for p in inventory:
            if self.registry.is_registered(p.point_id):
                continue
            cls = self.classifier.classify(p)
            if cls.criticality == PointCriticality.CRITICAL:
                d = await self.discover_blind_spot(p.point_id, source="scheduled")
                decisions.append(d)
        return decisions

    async def probation_review(self) -> None:
        """Periodic: promote clean probation points, quarantine anomalous ones."""
        for reg in self.registry.list_probation():
            if reg.anomaly_count >= 3:
                self.registry.quarantine(reg.point_id, "3 anomalies during probation")
                continue
            if time.time() >= reg.probation_ends_at:
                self.registry.promote_to_active(reg.point_id)


# ---- module-level singleton ------------------------------------------------

_discovery_service: Optional[DiscoveryService] = None


def init_discovery(
    provider,
    adapter,
    audit_db_path: str,
    training_db_path: str,
) -> DiscoveryService:
    """Boot-time initialization. Call once after PointInventoryProvider is up."""
    global _discovery_service
    audit = DiscoveryAuditLog(audit_db_path)
    registry = ARVISPollRegistry(adapter, audit)
    classifier = HybridClassifier(training_db_path)
    rate_limiter = RateLimiter()
    _discovery_service = DiscoveryService(
        provider, registry, classifier, audit, rate_limiter,
    )
    logger.info(
        "[Discovery] Service initialized. audit=%s training=%s",
        audit_db_path, training_db_path,
    )
    return _discovery_service


def get_discovery_service() -> DiscoveryService:
    if _discovery_service is None:
        raise RuntimeError(
            "Discovery service not initialized. Call "
            "arvis_core.discovery.init_discovery(...) at boot."
        )
    return _discovery_service
