"""
Validation Monitor
==================

Tracks pass/fail criteria throughout the 90-day simulation.
Generates validation reports and monitors test case execution.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from enum import Enum

from tests.omega_stress_test.metrics import (
    TrustMetrics,
    ValidationMetrics,
    PassFailStatus,
    SimulationDay,
)

logger = logging.getLogger("arvis.omega.validation")


@dataclass
class TestCaseResult:
    """Result of a single test case execution."""
    test_id: str
    name: str
    phase: int
    status: PassFailStatus
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "phase": self.phase,
            "status": self.status.value,
            "message": self.message,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
        }


class ValidationMonitor:
    """
    Monitors and records validation criteria throughout the simulation.
    
    Responsibilities:
    - Track all test case results
    - Monitor pass/fail criteria
    - Record daily metrics
    - Generate validation reports
    """
    
    def __init__(self, output_dir: str = "tests/omega_stress_test/results"):
        """
        Initialize validation monitor.
        
        Args:
            output_dir: Directory to store results
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Metrics tracking
        self.trust_metrics = TrustMetrics()
        self.validation_metrics = ValidationMetrics()
        
        # Test case results
        self.test_results: Dict[str, TestCaseResult] = {}
        
        # Daily records
        self.daily_records: List[SimulationDay] = []
        
        # Phase summaries
        self.phase_summaries: Dict[int, Dict[str, Any]] = {}
        
        # Audit log
        self.audit_log: List[Dict[str, Any]] = []
        
        logger.info(f"ValidationMonitor initialized, output_dir={output_dir}")
    
    # =========================================================================
    # TEST CASE MANAGEMENT
    # =========================================================================
    
    def register_test(self, test_id: str, name: str, phase: int):
        """Register a test case for tracking."""
        self.test_results[test_id] = TestCaseResult(
            test_id=test_id,
            name=name,
            phase=phase,
            status=PassFailStatus.PENDING,
            message="Test not yet executed",
        )
        self.validation_metrics.record_test_result(test_id, PassFailStatus.PENDING)
    
    def record_test_result(
        self,
        test_id: str,
        passed: bool,
        message: str,
        evidence: Optional[Dict[str, Any]] = None
    ):
        """Record the result of a test case."""
        status = PassFailStatus.PASS if passed else PassFailStatus.FAIL
        
        if test_id in self.test_results:
            self.test_results[test_id].status = status
            self.test_results[test_id].message = message
            self.test_results[test_id].evidence = evidence or {}
            self.test_results[test_id].timestamp = datetime.now()
        else:
            self.test_results[test_id] = TestCaseResult(
                test_id=test_id,
                name=test_id,
                phase=0,
                status=status,
                message=message,
                evidence=evidence or {},
            )
        
        self.validation_metrics.record_test_result(test_id, status)
        
        self._audit_log("test_result", {
            "test_id": test_id,
            "status": status.value,
            "message": message,
        })
        
        logger.info(f"Test {test_id}: {status.value} - {message}")
    
    # =========================================================================
    # DAILY METRICS RECORDING
    # =========================================================================
    
    def record_day(self, day: SimulationDay):
        """Record metrics for a simulation day."""
        self.daily_records.append(day)
        
        # Update trust metrics
        self.trust_metrics.record_day(
            day.day_number,
            day.trust_score,
            "nominal"  # Would come from trust governor
        )
        
        # Update validation metrics
        if day.silent_briefing:
            self.validation_metrics.record_silent_briefing(day.day_number)
        else:
            for _ in range(day.advisory_count):
                self.validation_metrics.record_advisory(day.day_number)
        
        self._audit_log("day_record", day.to_dict())
    
    def record_advisory(self, day: int, advisory: Dict[str, Any]):
        """Record an advisory generated on a specific day."""
        self.validation_metrics.record_advisory(day)
        
        # Check for evidence backing
        has_evidence = len(advisory.get("evidence", [])) > 0
        self.validation_metrics.record_confidence(has_evidence)
        
        self._audit_log("advisory", {
            "day": day,
            "advisory_id": advisory.get("id", "unknown"),
            "severity": advisory.get("severity", "unknown"),
            "has_evidence": has_evidence,
        })
    
    def record_operator_response(
        self,
        day: int,
        advisory_id: str,
        accepted: bool,
        successful: Optional[bool] = None
    ):
        """Record operator response to an advisory."""
        self.trust_metrics.record_recommendation(accepted, successful)
        
        self._audit_log("operator_response", {
            "day": day,
            "advisory_id": advisory_id,
            "accepted": accepted,
            "successful": successful,
        })
    
    def record_control_attempt(self, context: Dict[str, Any]):
        """
        Record a control command attempt (CRITICAL FAILURE).
        
        This is an immediate fail condition.
        """
        self.validation_metrics.record_control_attempt()
        
        self._audit_log("CONTROL_ATTEMPT", {
            "context": context,
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.critical(f"CONTROL ATTEMPT DETECTED: {context}")
    
    def record_noise_alert(self, alert: Dict[str, Any]):
        """Record an alert triggered by noise."""
        self.validation_metrics.record_noise_alert()
        
        self._audit_log("noise_alert", alert)
    
    def record_memory_recall(self, success: bool, details: Dict[str, Any]):
        """Record a memory recall attempt."""
        self.validation_metrics.record_recall(success)
        
        self._audit_log("memory_recall", {
            "success": success,
            "details": details,
        })
    
    def record_skill_downgrade(
        self,
        skill_id: str,
        old_confidence: float,
        new_confidence: float,
        reason: str
    ):
        """Record a skill being downgraded (Refinement 2)."""
        self.validation_metrics.record_skill_downgrade(
            skill_id, old_confidence, new_confidence, reason
        )
        
        self._audit_log("skill_downgrade", {
            "skill_id": skill_id,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence,
            "reason": reason,
        })
    
    # =========================================================================
    # PHASE MANAGEMENT
    # =========================================================================
    
    def start_phase(self, phase: int, description: str):
        """Mark the start of a phase."""
        self._audit_log("phase_start", {
            "phase": phase,
            "description": description,
        })
        
        logger.info(f"=== Phase {phase} Started: {description} ===")
    
    def end_phase(self, phase: int) -> Dict[str, Any]:
        """Mark the end of a phase and generate summary."""
        # Get all test results for this phase
        phase_tests = [
            t for t in self.test_results.values()
            if t.phase == phase
        ]
        
        passed = sum(1 for t in phase_tests if t.status == PassFailStatus.PASS)
        failed = sum(1 for t in phase_tests if t.status == PassFailStatus.FAIL)
        pending = sum(1 for t in phase_tests if t.status == PassFailStatus.PENDING)
        
        # Get days in this phase
        phase_days = [
            d for d in self.daily_records
            if self._get_phase(d.day_number) == phase
        ]
        
        summary = {
            "phase": phase,
            "tests_total": len(phase_tests),
            "tests_passed": passed,
            "tests_failed": failed,
            "tests_pending": pending,
            "days_in_phase": len(phase_days),
            "trust_start": phase_days[0].trust_score if phase_days else None,
            "trust_end": phase_days[-1].trust_score if phase_days else None,
            "total_advisories": sum(d.advisory_count for d in phase_days),
            "silent_briefing_days": sum(1 for d in phase_days if d.silent_briefing),
        }
        
        self.phase_summaries[phase] = summary
        
        self._audit_log("phase_end", summary)
        
        logger.info(
            f"=== Phase {phase} Complete: "
            f"{passed} passed, {failed} failed, {pending} pending ==="
        )
        
        return summary
    
    def _get_phase(self, day: int) -> int:
        """Determine which phase a day belongs to."""
        if day <= 7:
            return 0
        elif day <= 14:
            return 1
        elif day <= 30:
            return 2
        elif day <= 60:
            return 3
        else:
            return 4
    
    # =========================================================================
    # PASS/FAIL CHECKING
    # =========================================================================
    
    def check_pass_criteria(self) -> Dict[str, bool]:
        """Check all pass criteria."""
        return self.validation_metrics.check_pass_criteria()
    
    def check_fail_criteria(self) -> Dict[str, bool]:
        """Check all fail criteria."""
        return self.validation_metrics.check_fail_criteria()
    
    def get_overall_status(self) -> PassFailStatus:
        """
        Determine overall pass/fail status.
        
        Returns FAIL if any test failed.
        Returns PASS if all tests passed.
        Otherwise returns PENDING.
        
        Note: Test case results take precedence over derived metrics
        since test cases represent explicit validation criteria.
        """
        # Check if any test failed
        failed_tests = sum(
            1 for t in self.test_results.values()
            if t.status == PassFailStatus.FAIL
        )
        if failed_tests > 0:
            return PassFailStatus.FAIL
        
        # Check if all tests passed
        passed_tests = sum(
            1 for t in self.test_results.values()
            if t.status == PassFailStatus.PASS
        )
        pending_tests = sum(
            1 for t in self.test_results.values()
            if t.status == PassFailStatus.PENDING
        )
        
        # If all tests passed, return PASS
        if passed_tests > 0 and pending_tests == 0 and failed_tests == 0:
            return PassFailStatus.PASS
        
        return PassFailStatus.PENDING
    
    # =========================================================================
    # REPORTING
    # =========================================================================
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive validation report."""
        report = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_days": len(self.daily_records),
                "phases_completed": len(self.phase_summaries),
            },
            
            "overall_status": self.get_overall_status().value,
            
            "pass_criteria": self.check_pass_criteria(),
            "fail_criteria": self.check_fail_criteria(),
            
            "trust_metrics": self.trust_metrics.to_dict(),
            "validation_metrics": self.validation_metrics.to_dict(),
            
            "phase_summaries": self.phase_summaries,
            
            "test_results": {
                test_id: result.to_dict()
                for test_id, result in self.test_results.items()
            },
            
            "daily_summary": [
                day.to_dict() for day in self.daily_records[-7:]  # Last 7 days
            ],
            
            "critical_events": [
                event for event in self.audit_log
                if event["type"] in ["CONTROL_ATTEMPT", "skill_downgrade"]
            ],
        }
        
        return report
    
    def save_report(self, filename: str = "omega_validation_report.json"):
        """Save validation report to file."""
        report = self.generate_report()
        
        filepath = self.output_dir / filename
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"Validation report saved to {filepath}")
        
        return filepath
    
    def save_audit_log(self, filename: str = "omega_audit_log.jsonl"):
        """Save audit log to file."""
        filepath = self.output_dir / filename
        
        with open(filepath, 'w') as f:
            for event in self.audit_log:
                f.write(json.dumps(event, default=str) + "\n")
        
        logger.info(f"Audit log saved to {filepath}")
        
        return filepath
    
    def _audit_log(self, event_type: str, data: Dict[str, Any]):
        """Add entry to audit log."""
        self.audit_log.append({
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        })
    
    # =========================================================================
    # GAP COVERAGE TEST HELPERS
    # =========================================================================
    
    def check_silent_data_drop(
        self,
        sensor_id: str,
        last_update: datetime,
        current_time: datetime,
        threshold_hours: int = 24
    ) -> bool:
        """
        Check if a sensor has stopped updating (Gap 1: Silent Data Drop).
        
        Returns True if data drop detected.
        """
        hours_since_update = (current_time - last_update).total_seconds() / 3600
        
        if hours_since_update > threshold_hours:
            self._audit_log("silent_data_drop", {
                "sensor_id": sensor_id,
                "hours_since_update": hours_since_update,
                "threshold_hours": threshold_hours,
            })
            return True
        
        return False
    
    def check_false_success(
        self,
        advisory: Dict[str, Any],
        baseline_expected: float,
        actual_value: float
    ) -> bool:
        """
        Check if an advisory claims false success (Gap 4: False Success).
        
        Returns True if false success detected.
        """
        claimed_impact = advisory.get("claimed_impact", 0)
        actual_improvement = actual_value - baseline_expected
        
        # ARVIS can only claim improvement beyond baseline
        if claimed_impact > actual_improvement * 1.1:  # 10% margin
            self._audit_log("false_success", {
                "advisory_id": advisory.get("id"),
                "claimed_impact": claimed_impact,
                "actual_improvement": actual_improvement,
            })
            return True
        
        return False
    
    def check_stakeholder_conflict(
        self,
        advisory: Dict[str, Any],
        stakeholder_scores: Dict[str, float]
    ) -> bool:
        """
        Check if advisory creates stakeholder conflict (Gap 3).
        
        Returns True if conflict detected.
        """
        values = list(stakeholder_scores.values())
        if len(values) < 2:
            return False
        
        max_score = max(values)
        min_score = min(values)
        
        # Conflict if one stakeholder strongly approves and another disapproves
        if (max_score - min_score) > 0.3:
            self._audit_log("stakeholder_conflict", {
                "advisory_id": advisory.get("id"),
                "scores": stakeholder_scores,
                "conflict_magnitude": max_score - min_score,
            })
            return True
        
        return False
