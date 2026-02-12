"""
Maintenance Verification Engine
================================

Physics-based verification of maintenance work orders.

The "Truth Serum":
- Compares pre/post maintenance telemetry
- Uses physics to verify if work was actually done
- Catches "Ghost Maintenance" (ticked box, no work)

This turns ARVIS from a "Monitor" into an "Auditor."
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger("arvis.bms.verification")


# ═══════════════════════════════════════════════════════════════════════════
# VERIFICATION STATUS
# ═══════════════════════════════════════════════════════════════════════════

class VerificationStatus(Enum):
    """Work order verification status"""
    VERIFIED = "verified"          # Work done, improvement measured
    WEAK = "weak"                  # Work possibly done, marginal improvement
    FAILED = "failed"              # No improvement - suspected ghost maintenance
    PENDING = "pending"            # Waiting for post-maintenance data
    NO_DATA = "no_data"            # Insufficient sensor data
    UNKNOWN = "unknown"            # No physics model for this task type


@dataclass
class VerificationResult:
    """Result of maintenance work verification"""
    work_order_id: str
    equipment_id: str
    task_type: str
    status: VerificationStatus
    confidence: float
    metric_name: str
    value_before: Optional[float]
    value_after: Optional[float]
    improvement_pct: float
    expected_improvement_pct: float
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    recommendation_id: Optional[str] = None  # Phase 1: Link to recommendation tracker
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "equipment_id": self.equipment_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "confidence": round(self.confidence, 2),
            "metric_name": self.metric_name,
            "value_before": round(self.value_before, 2) if self.value_before else None,
            "value_after": round(self.value_after, 2) if self.value_after else None,
            "improvement_pct": round(self.improvement_pct * 100, 1),
            "expected_improvement_pct": round(self.expected_improvement_pct * 100, 1),
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }
    
    def format_message(self) -> str:
        """Format as user-friendly verification report"""
        status_icons = {
            VerificationStatus.VERIFIED: "✅",
            VerificationStatus.WEAK: "⚠️",
            VerificationStatus.FAILED: "❌",
            VerificationStatus.PENDING: "⏳",
            VerificationStatus.NO_DATA: "📊",
            VerificationStatus.UNKNOWN: "❓",
        }
        icon = status_icons.get(self.status, "❓")
        
        return (
            f"{icon} **Verification: {self.status.value.upper()}**\n"
            f"• Work Order: {self.work_order_id}\n"
            f"• Equipment: {self.equipment_id}\n"
            f"• Task: {self.task_type}\n"
            f"• Metric: {self.metric_name}\n"
            f"• Before: {self.value_before}\n"
            f"• After: {self.value_after}\n"
            f"• Improvement: {self.improvement_pct * 100:.1f}% (Expected: {self.expected_improvement_pct * 100:.0f}%+)\n"
            f"\n{self.message}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# PHYSICS MODELS FOR VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VerificationRule:
    """Physics-based rule for verifying a maintenance task"""
    task_type: str
    metric_name: str
    expected_direction: str  # "decrease" or "increase"
    min_improvement_pct: float
    description: str


# Maintenance tasks with measurable physical outcomes
VERIFICATION_RULES: Dict[str, VerificationRule] = {
    # ─────────────────────────────────────────────────────────────────
    # FILTER MAINTENANCE
    # ─────────────────────────────────────────────────────────────────
    "filter_cleaning": VerificationRule(
        task_type="filter_cleaning",
        metric_name="static_pressure_drop",
        expected_direction="decrease",
        min_improvement_pct=0.10,  # 10% reduction in pressure drop
        description="Clean filter should reduce airflow resistance"
    ),
    "filter_replacement": VerificationRule(
        task_type="filter_replacement",
        metric_name="static_pressure_drop",
        expected_direction="decrease",
        min_improvement_pct=0.20,  # 20% for new filter
        description="New filter significantly reduces pressure drop"
    ),
    
    # ─────────────────────────────────────────────────────────────────
    # COIL MAINTENANCE
    # ─────────────────────────────────────────────────────────────────
    "coil_cleaning": VerificationRule(
        task_type="coil_cleaning",
        metric_name="approach_temperature",
        expected_direction="decrease",
        min_improvement_pct=0.15,  # 15% better heat transfer
        description="Clean coil should reduce approach temperature"
    ),
    "condenser_cleaning": VerificationRule(
        task_type="condenser_cleaning",
        metric_name="condenser_approach",
        expected_direction="decrease",
        min_improvement_pct=0.10,
        description="Clean condenser improves heat rejection"
    ),
    
    # ─────────────────────────────────────────────────────────────────
    # MECHANICAL MAINTENANCE
    # ─────────────────────────────────────────────────────────────────
    "belt_replacement": VerificationRule(
        task_type="belt_replacement",
        metric_name="fan_vibration",
        expected_direction="decrease",
        min_improvement_pct=0.15,
        description="New belt reduces vibration and noise"
    ),
    "belt_tensioning": VerificationRule(
        task_type="belt_tensioning",
        metric_name="fan_vibration",
        expected_direction="decrease",
        min_improvement_pct=0.08,
        description="Properly tensioned belt reduces vibration"
    ),
    "bearing_lubrication": VerificationRule(
        task_type="bearing_lubrication",
        metric_name="motor_temperature",
        expected_direction="decrease",
        min_improvement_pct=0.05,
        description="Lubricated bearings run cooler"
    ),
    
    # ─────────────────────────────────────────────────────────────────
    # REFRIGERATION
    # ─────────────────────────────────────────────────────────────────
    "refrigerant_charge": VerificationRule(
        task_type="refrigerant_charge",
        metric_name="superheat",
        expected_direction="decrease",
        min_improvement_pct=0.20,
        description="Proper charge normalizes superheat"
    ),
    
    # ─────────────────────────────────────────────────────────────────
    # EFFICIENCY IMPROVEMENTS
    # ─────────────────────────────────────────────────────────────────
    "chiller_service": VerificationRule(
        task_type="chiller_service",
        metric_name="cop",  # Coefficient of Performance
        expected_direction="increase",
        min_improvement_pct=0.05,
        description="Service should improve chiller efficiency"
    ),
    "vfd_tuning": VerificationRule(
        task_type="vfd_tuning",
        metric_name="power_consumption",
        expected_direction="decrease",
        min_improvement_pct=0.10,
        description="Optimized VFD reduces energy use"
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# MAINTENANCE VERIFIER
# ═══════════════════════════════════════════════════════════════════════════

class MaintenanceVerifier:
    """
    Physics-based verification of maintenance work orders.
    
    Compares pre/post telemetry to verify if maintenance actually
    improved equipment performance.
    
    Usage:
        >>> verifier = MaintenanceVerifier()
        >>> result = await verifier.verify_work_order(
        ...     work_order_id="WO-2024-0042",
        ...     equipment_id="AHU-01",
        ...     task_type="filter_cleaning",
        ...     pre_data={"static_pressure_drop": 250},  # Pa
        ...     post_data={"static_pressure_drop": 185}, # Pa
        ... )
        >>> print(result.format_message())
    """
    
    # Time windows for data collection
    PRE_MAINTENANCE_WINDOW_HOURS = 24
    POST_MAINTENANCE_WINDOW_HOURS = 4
    MIN_STABLE_READINGS = 3
    
    def __init__(self, recommendation_tracker=None):
        # Store pending work orders
        self.pending_verifications: Dict[str, Dict] = {}
        self.completed_verifications: List[VerificationResult] = []
        
        # Phase 1: Advisory System Integration
        self.tracker = recommendation_tracker
        
        logger.info("MaintenanceVerifier initialized with %d task rules", 
                    len(VERIFICATION_RULES))
    
    def get_supported_tasks(self) -> List[str]:
        """Get list of task types that can be verified"""
        return list(VERIFICATION_RULES.keys())
    
    async def verify_work_order(
        self,
        work_order_id: str,
        equipment_id: str,
        task_type: str,
        pre_data: Dict[str, float],
        post_data: Dict[str, float],
    ) -> VerificationResult:
        """
        Verify if maintenance work was actually performed.
        
        Uses physics to compare pre/post telemetry and determine
        if measurable improvement occurred.
        
        Args:
            work_order_id: Work order identifier
            equipment_id: Equipment that was serviced
            task_type: Type of maintenance performed
            pre_data: Telemetry snapshot before maintenance
            post_data: Telemetry snapshot after maintenance
            
        Returns:
            VerificationResult with verdict
        """
        # Check if we have a rule for this task
        if task_type not in VERIFICATION_RULES:
            return VerificationResult(
                work_order_id=work_order_id,
                equipment_id=equipment_id,
                task_type=task_type,
                status=VerificationStatus.UNKNOWN,
                confidence=0.0,
                metric_name="N/A",
                value_before=None,
                value_after=None,
                improvement_pct=0.0,
                expected_improvement_pct=0.0,
                message=f"No verification model for task type '{task_type}'. Cannot verify."
            )
        
        rule = VERIFICATION_RULES[task_type]
        metric_key = rule.metric_name
        
        # Get values
        val_before = pre_data.get(metric_key)
        val_after = post_data.get(metric_key)
        
        # Check data availability
        if val_before is None or val_after is None:
            return VerificationResult(
                work_order_id=work_order_id,
                equipment_id=equipment_id,
                task_type=task_type,
                status=VerificationStatus.NO_DATA,
                confidence=0.0,
                metric_name=metric_key,
                value_before=val_before,
                value_after=val_after,
                improvement_pct=0.0,
                expected_improvement_pct=rule.min_improvement_pct,
                message=f"Insufficient data: '{metric_key}' not available in pre or post snapshots."
            )
        
        # Calculate improvement
        if rule.expected_direction == "decrease":
            # Lower is better (pressure drop, vibration, temperature)
            improvement = (val_before - val_after) / val_before if val_before != 0 else 0
        else:
            # Higher is better (COP, efficiency)
            improvement = (val_after - val_before) / val_before if val_before != 0 else 0
        
        # Determine verdict
        if improvement >= rule.min_improvement_pct:
            status = VerificationStatus.VERIFIED
            confidence = min(0.95, 0.7 + improvement)
            message = (
                f"✅ **Work Verified.** The {metric_key} improved by {improvement * 100:.1f}%. "
                f"{rule.description}. Good work by the maintenance team!"
            )
        elif improvement > 0:
            status = VerificationStatus.WEAK
            confidence = 0.6
            message = (
                f"⚠️ **Marginal Improvement.** The {metric_key} improved by only {improvement * 100:.1f}% "
                f"(expected {rule.min_improvement_pct * 100:.0f}%+). "
                f"Work may be incomplete or equipment condition is poor."
            )
        elif improvement > -0.05:
            # No change (within 5% noise)
            status = VerificationStatus.FAILED
            confidence = 0.85
            message = (
                f"❌ **No Improvement Detected.** The {metric_key} remains at {val_after} "
                f"(was {val_before} before). **Suspected Ghost Maintenance.** "
                f"Flagging work order {work_order_id} for review."
            )
        else:
            # Actually got worse
            status = VerificationStatus.FAILED
            confidence = 0.90
            message = (
                f"❌ **Performance Degraded!** The {metric_key} INCREASED from {val_before} to {val_after}. "
                f"Either work was done incorrectly, or wrong data recorded. "
                f"Immediate review required for {equipment_id}."
            )
        
        result = VerificationResult(
            work_order_id=work_order_id,
            equipment_id=equipment_id,
            task_type=task_type,
            status=status,
            confidence=confidence,
            metric_name=metric_key,
            value_before=val_before,
            value_after=val_after,
            improvement_pct=improvement,
            expected_improvement_pct=rule.min_improvement_pct,
            message=message,
        )
        
        # Store for history
        self.completed_verifications.append(result)
        
        # Phase 1: Log outcome to advisory system
        if self.tracker and hasattr(result, 'recommendation_id'):
            # Map verification status to outcome quality
            from agent_advisory.schemas import OutcomeQuality
            
            quality_map = {
                VerificationStatus.VERIFIED: OutcomeQuality.EXCELLENT,
                VerificationStatus.WEAK: OutcomeQuality.ACCEPTABLE,
                VerificationStatus.FAILED: OutcomeQuality.POOR,
                VerificationStatus.NO_DATA: OutcomeQuality.UNKNOWN,
                VerificationStatus.UNKNOWN: OutcomeQuality.UNKNOWN,
            }
            
            outcome_quality = quality_map.get(result.status, OutcomeQuality.UNKNOWN)
            
            # Log to tracker if there's a linked recommendation
            self.tracker.log_outcome(
                recommendation_id=result.recommendation_id,
                actual_outcome={
                    "work_order_id": work_order_id,
                    "equipment_id": equipment_id,
                    "task_type": task_type,
                    "improvement_pct": improvement,
                    "metric_name": metric_key,
                    "value_before": val_before,
                    "value_after": val_after,
                },
                outcome_quality=outcome_quality
            )
        
        # Log
        logger.info(
            "Verification %s: WO %s, Equipment %s, Task %s -> %s (%.1f%% improvement)",
            result.status.value, work_order_id, equipment_id, task_type,
            "PASS" if status == VerificationStatus.VERIFIED else "FAIL",
            improvement * 100
        )
        
        return result
    
    def register_pending_work(
        self,
        work_order_id: str,
        equipment_id: str,
        task_type: str,
        maintenance_time: datetime,
        pre_data: Dict[str, float],
    ):
        """
        Register a work order for future verification.
        
        Call this BEFORE maintenance starts with the pre-maintenance data.
        Then call verify_pending() after maintenance completes.
        """
        self.pending_verifications[work_order_id] = {
            "equipment_id": equipment_id,
            "task_type": task_type,
            "maintenance_time": maintenance_time,
            "pre_data": pre_data,
            "registered_at": datetime.now(),
        }
        
        logger.info("Registered pending verification: %s", work_order_id)
    
    async def verify_pending(
        self,
        work_order_id: str,
        post_data: Dict[str, float],
    ) -> Optional[VerificationResult]:
        """
        Verify a previously registered work order.
        """
        if work_order_id not in self.pending_verifications:
            logger.warning("Work order %s not found in pending", work_order_id)
            return None
        
        pending = self.pending_verifications.pop(work_order_id)
        
        return await self.verify_work_order(
            work_order_id=work_order_id,
            equipment_id=pending["equipment_id"],
            task_type=pending["task_type"],
            pre_data=pending["pre_data"],
            post_data=post_data,
        )
    
    def get_verification_summary(
        self,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Get summary of verification results"""
        cutoff = datetime.now() - timedelta(days=days)
        recent = [v for v in self.completed_verifications if v.timestamp > cutoff]
        
        verified = sum(1 for v in recent if v.status == VerificationStatus.VERIFIED)
        failed = sum(1 for v in recent if v.status == VerificationStatus.FAILED)
        weak = sum(1 for v in recent if v.status == VerificationStatus.WEAK)
        
        return {
            "period_days": days,
            "total_verified": len(recent),
            "passed": verified,
            "failed": failed,
            "weak": weak,
            "pass_rate": (verified / len(recent) * 100) if recent else 0,
            "suspected_ghost_maintenance": failed,
        }


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS (LLM Tool Integration)
# ═══════════════════════════════════════════════════════════════════════════

async def verify_maintenance_work(
    work_order_id: str,
    equipment_id: str,
    task_type: str,
    pre_data: Dict[str, float],
    post_data: Dict[str, float],
) -> Dict[str, Any]:
    """
    Verify if maintenance work was actually done.
    
    This is the LLM tool handler.
    """
    verifier = MaintenanceVerifier()
    result = await verifier.verify_work_order(
        work_order_id=work_order_id,
        equipment_id=equipment_id,
        task_type=task_type,
        pre_data=pre_data,
        post_data=post_data,
    )
    
    return {
        "verification": result.to_dict(),
        "formatted_message": result.format_message(),
        "is_ghost_maintenance": result.status == VerificationStatus.FAILED,
    }


def get_verifiable_tasks() -> List[Dict[str, str]]:
    """Get list of maintenance tasks that can be verified"""
    return [
        {
            "task_type": rule.task_type,
            "metric": rule.metric_name,
            "description": rule.description,
        }
        for rule in VERIFICATION_RULES.values()
    ]
