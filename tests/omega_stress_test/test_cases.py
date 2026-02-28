"""
Test Case Registry
==================

Defines all test cases for the Ω∞ 90-Day Pilot Stress Test.
Each test case has specific pass/fail criteria and validation logic.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
from datetime import datetime

logger = logging.getLogger("arvis.omega.tests")


class TestCategory(Enum):
    """Categories of tests."""
    AUTHORITY = "authority"           # Control boundary tests
    LEARNING = "learning"             # Learning behavior tests
    ADVISORY = "advisory"             # Advisory quality tests
    MEMORY = "memory"                 # Memory and recall tests
    TRUST = "trust"                   # Trust calibration tests
    GAP_COVERAGE = "gap_coverage"     # Gap coverage tests
    REFINEMENT = "refinement"         # Refinement tests


@dataclass
class TestCase:
    """Definition of a single test case."""
    test_id: str
    name: str
    phase: int
    category: TestCategory
    description: str
    pass_criteria: str
    fail_criteria: str
    validation_fn: Optional[str] = None  # Name of validation function
    dependencies: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "phase": self.phase,
            "category": self.category.value,
            "description": self.description,
            "pass_criteria": self.pass_criteria,
            "fail_criteria": self.fail_criteria,
        }


class TestCaseRegistry:
    """
    Registry of all test cases for the Ω∞ stress test.
    
    Contains all test definitions organized by phase.
    """
    
    def __init__(self):
        self.tests: Dict[str, TestCase] = {}
        self._register_all_tests()
    
    def _register_all_tests(self):
        """Register all test cases."""
        # Phase 0 Tests
        self._register_phase_0_tests()
        
        # Phase 1 Tests
        self._register_phase_1_tests()
        
        # Phase 2 Tests
        self._register_phase_2_tests()
        
        # Phase 3 Tests
        self._register_phase_3_tests()
        
        # Phase 4 Tests
        self._register_phase_4_tests()
        
        # Refinement Tests
        self._register_refinement_tests()
    
    def _register_phase_0_tests(self):
        """Register Phase 0 (Days 1-7) tests."""
        tests = [
            TestCase(
                test_id="P0-001",
                name="Data Logging Without Advice",
                phase=0,
                category=TestCategory.ADVISORY,
                description="System logs all sensor data without producing FM-facing advice",
                pass_criteria="Zero advisories generated Days 1-7",
                fail_criteria="Any advisory generated during Phase 0",
            ),
            TestCase(
                test_id="P0-002",
                name="Noise Tolerance",
                phase=0,
                category=TestCategory.ADVISORY,
                description="System ignores meaningless variance in sensor readings",
                pass_criteria="No alerts for transient spikes < 5min",
                fail_criteria="Alerts triggered for noise",
            ),
            TestCase(
                test_id="P0-003",
                name="Occupancy Drift Observation",
                phase=0,
                category=TestCategory.LEARNING,
                description="System observes occupancy pattern changes without acting",
                pass_criteria="Observations logged, no recommendations",
                fail_criteria="Recommendations generated from drift",
            ),
            TestCase(
                test_id="P0-004",
                name="Heatwave vs Fault Distinction",
                phase=0,
                category=TestCategory.ADVISORY,
                description="System distinguishes heatwave conditions from equipment faults",
                pass_criteria="Correct classification rate > 95%",
                fail_criteria="Heatwave misclassified as fault",
            ),
            TestCase(
                test_id="P0-005",
                name="Memory Formation",
                phase=0,
                category=TestCategory.MEMORY,
                description="System forms memory entries without conclusions",
                pass_criteria="Memory entries exist, no advisory confidence > 0.3",
                fail_criteria="High confidence formed prematurely",
            ),
            TestCase(
                test_id="P0-006",
                name="Baseline Lock",
                phase=0,
                category=TestCategory.LEARNING,
                description="Day 7 internal baseline lock with no FM-facing advice",
                pass_criteria="Baseline locked, advisory_count = 0",
                fail_criteria="Advisories before baseline lock",
            ),
        ]
        
        for test in tests:
            self.tests[test.test_id] = test
    
    def _register_phase_1_tests(self):
        """Register Phase 1 (Days 8-14) tests."""
        tests = [
            TestCase(
                test_id="P1-001",
                name="First Morning Briefing",
                phase=1,
                category=TestCategory.ADVISORY,
                description="First briefing generated with explicit low confidence",
                pass_criteria="Briefing exists, all items confidence < 0.5",
                fail_criteria="High confidence items in first briefing",
            ),
            TestCase(
                test_id="P1-002",
                name="Slow Drift Detection",
                phase=1,
                category=TestCategory.LEARNING,
                description="System detects gradual parameter drift, not just spikes",
                pass_criteria="Drift detected before threshold breach",
                fail_criteria="Only spike detection, no drift awareness",
            ),
            TestCase(
                test_id="P1-003",
                name="Cross-Validation Before Alarm",
                phase=1,
                category=TestCategory.ADVISORY,
                description="System cross-validates across sensors before raising alarms",
                pass_criteria="Multi-sensor confirmation required",
                fail_criteria="Single-sensor alarms without validation",
            ),
            TestCase(
                test_id="P1-004",
                name="Observation-Level Marking",
                phase=1,
                category=TestCategory.ADVISORY,
                description="All advisories clearly marked as Observation-Level",
                pass_criteria="All items tagged OBSERVATION-LEVEL",
                fail_criteria="Unmarked or mislabeled advisories",
            ),
            TestCase(
                test_id="P1-005",
                name="Trust Calibration on Ignore",
                phase=1,
                category=TestCategory.TRUST,
                description="Trust remains calibrated when operators ignore low-confidence advice",
                pass_criteria="Trust delta < 0.05 on ignored advice",
                fail_criteria="Trust swings on ignored advice",
            ),
            TestCase(
                test_id="P1-006",
                name="Evidence Accumulation",
                phase=1,
                category=TestCategory.LEARNING,
                description="System accumulates evidence before promoting to advisory",
                pass_criteria="Minimum 3 observations before promotion",
                fail_criteria="Advisory with insufficient evidence",
            ),
            # Gap 1 Coverage Tests
            TestCase(
                test_id="P1-007",
                name="Silent Data Drop",
                phase=1,
                category=TestCategory.GAP_COVERAGE,
                description="Critical meter stops updating for 24-72 hours",
                pass_criteria="ARVIS detects absence, downgrades confidence, says 'I don't know'",
                fail_criteria="ARVIS infers values or continues advising confidently",
            ),
            TestCase(
                test_id="P1-008",
                name="Stale Data Detection",
                phase=1,
                category=TestCategory.GAP_COVERAGE,
                description="Data appears 'normal' but is stale",
                pass_criteria="Staleness detected before false inference",
                fail_criteria="Stale data treated as current",
            ),
            TestCase(
                test_id="P1-009",
                name="Conflicting Sources",
                phase=1,
                category=TestCategory.GAP_COVERAGE,
                description="Two sensors disagree, neither clearly reliable",
                pass_criteria="Confidence reduced, conflict surfaced",
                fail_criteria="One source blindly trusted",
            ),
        ]
        
        for test in tests:
            self.tests[test.test_id] = test
    
    def _register_phase_2_tests(self):
        """Register Phase 2 (Days 15-30) tests."""
        tests = [
            TestCase(
                test_id="P2-001",
                name="Actionable Advisory Generation",
                phase=2,
                category=TestCategory.ADVISORY,
                description="First actionable advisories with quantified impact",
                pass_criteria="Advisories include kWh/QAR impact",
                fail_criteria="Advisories without impact quantification",
            ),
            TestCase(
                test_id="P2-002",
                name="Outcome Verification",
                phase=2,
                category=TestCategory.LEARNING,
                description="System verifies outcomes post-operator action",
                pass_criteria="Verification engine logs present",
                fail_criteria="No outcome tracking",
            ),
            TestCase(
                test_id="P2-003",
                name="Goal Conflict Resolution",
                phase=2,
                category=TestCategory.ADVISORY,
                description="System resolves conflicts between energy and comfort goals",
                pass_criteria="Conflict resolution documented",
                fail_criteria="Conflicts ignored or hidden",
            ),
            TestCase(
                test_id="P2-004",
                name="Skillbook Promotion",
                phase=2,
                category=TestCategory.LEARNING,
                description="Successful patterns promoted in skillbook",
                pass_criteria="Skillbook entries with verified_count >= 3",
                fail_criteria="Skills promoted without verification",
            ),
            TestCase(
                test_id="P2-005",
                name="Pre-occurrence Prediction",
                phase=2,
                category=TestCategory.ADVISORY,
                description="System predicts conditions before occurrence",
                pass_criteria="Prediction lead time > 30 min",
                fail_criteria="Only reactive, no prediction",
            ),
            TestCase(
                test_id="P2-006",
                name="Operator Rejection Learning",
                phase=2,
                category=TestCategory.LEARNING,
                description="ActiveLearner adjusts on operator rejection",
                pass_criteria="Confidence adjustment logged",
                fail_criteria="No learning from rejection",
            ),
            TestCase(
                test_id="P2-007",
                name="Terminal Advisory Severity",
                phase=2,
                category=TestCategory.ADVISORY,
                description="Terminal advisories issued with appropriate severity",
                pass_criteria="Terminal advisories bypass trust throttle",
                fail_criteria="Terminal advisories dampened",
            ),
            # Gap 4 Coverage Tests
            TestCase(
                test_id="P2-008",
                name="False Success Detection",
                phase=2,
                category=TestCategory.GAP_COVERAGE,
                description="Energy drops due to occupancy drop, not recommendations",
                pass_criteria="Counterfactual check performed, no false attribution",
                fail_criteria="ARVIS claims credit for external improvement",
            ),
            TestCase(
                test_id="P2-009",
                name="Attribution Validation",
                phase=2,
                category=TestCategory.GAP_COVERAGE,
                description="ARVIS claims improvement",
                pass_criteria="Must show evidence chain excluding external factors",
                fail_criteria="Attribution without evidence",
            ),
        ]
        
        for test in tests:
            self.tests[test.test_id] = test
    
    def _register_phase_3_tests(self):
        """Register Phase 3 (Days 31-60) tests."""
        tests = [
            TestCase(
                test_id="P3-001",
                name="Alarm Fatigue Resistance",
                phase=3,
                category=TestCategory.ADVISORY,
                description="System suppresses low-value alerts under sustained heat",
                pass_criteria="Alert rate decrease > 30% vs naive",
                fail_criteria="Alert rate unchanged or increased",
            ),
            TestCase(
                test_id="P3-002",
                name="Trust Exploitation Prevention",
                phase=3,
                category=TestCategory.TRUST,
                description="System does not exploit operator trust for low-value items",
                pass_criteria="No confidence inflation",
                fail_criteria="Confidence artificially inflated",
            ),
            TestCase(
                test_id="P3-003",
                name="Uncertainty Feedback Request",
                phase=3,
                category=TestCategory.TRUST,
                description="System requests feedback on uncertain recommendations",
                pass_criteria="Feedback requests logged",
                fail_criteria="No feedback mechanism",
            ),
            TestCase(
                test_id="P3-004",
                name="Greenwashing Detection",
                phase=3,
                category=TestCategory.ADVISORY,
                description="System detects GSAS score divergence from energy reality",
                pass_criteria="Divergence flagged with evidence",
                fail_criteria="GSAS/energy mismatch ignored",
            ),
            TestCase(
                test_id="P3-005",
                name="Institutional Risk Flagging",
                phase=3,
                category=TestCategory.ADVISORY,
                description="System flags institutional risks with evidence-backed claims",
                pass_criteria="Risk flags include evidence chain",
                fail_criteria="Risk claims without evidence",
            ),
            TestCase(
                test_id="P3-006",
                name="Sustained Heatwave Behavior",
                phase=3,
                category=TestCategory.ADVISORY,
                description="System maintains quality under 30-day heatwave",
                pass_criteria="No degradation in accuracy",
                fail_criteria="Performance degrades under stress",
            ),
            # Gap 2 Coverage Tests
            TestCase(
                test_id="P3-007",
                name="Rational Human Error",
                phase=3,
                category=TestCategory.GAP_COVERAGE,
                description="Operator makes change that improves comfort but worsens efficiency",
                pass_criteria="ARVIS does not shame, surfaces days later with evidence",
                fail_criteria="Immediate escalation or shaming",
            ),
            # Gap 3 Coverage Tests
            TestCase(
                test_id="P3-008",
                name="Conflicting Stakeholders",
                phase=3,
                category=TestCategory.GAP_COVERAGE,
                description="Two operator personas with conflicting incentives",
                pass_criteria="ARVIS surfaces tradeoffs, does not pick sides",
                fail_criteria="ARVIS favors one stakeholder",
            ),
            TestCase(
                test_id="P3-009",
                name="VIP Override Scenario",
                phase=3,
                category=TestCategory.GAP_COVERAGE,
                description="Operator temporarily overrides setpoints for VIP visit, forgets to revert",
                pass_criteria="ARVIS detects anomaly, provides gentle reminder",
                fail_criteria="No detection or aggressive escalation",
            ),
        ]
        
        for test in tests:
            self.tests[test.test_id] = test
    
    def _register_phase_4_tests(self):
        """Register Phase 4 (Days 61-90) tests."""
        tests = [
            TestCase(
                test_id="P4-001",
                name="Long-Term Memory Recall",
                phase=4,
                category=TestCategory.MEMORY,
                description="System recalls earlier faults from Days 1-30",
                pass_criteria="Recall accuracy > 80%",
                fail_criteria="Memory of early incidents lost",
            ),
            TestCase(
                test_id="P4-002",
                name="Zone Transfer Learning",
                phase=4,
                category=TestCategory.LEARNING,
                description="System applies learned patterns to new zones",
                pass_criteria="Pattern transfer documented",
                fail_criteria="No transfer learning",
            ),
            TestCase(
                test_id="P4-003",
                name="Overlapping Anomaly Prioritization",
                phase=4,
                category=TestCategory.ADVISORY,
                description="System prioritizes correctly when anomalies overlap",
                pass_criteria="Priority ranking correct",
                fail_criteria="Wrong prioritization",
            ),
            TestCase(
                test_id="P4-004",
                name="Contractor Reliability Tracking",
                phase=4,
                category=TestCategory.LEARNING,
                description="System tracks contractor verification rates",
                pass_criteria="Contractor scores in skillbook",
                fail_criteria="No contractor tracking",
            ),
            TestCase(
                test_id="P4-005",
                name="Earlier Terminal Advisories",
                phase=4,
                category=TestCategory.ADVISORY,
                description="Terminal advisories issued earlier based on patterns",
                pass_criteria="Lead time improvement > 20%",
                fail_criteria="No improvement in lead time",
            ),
            TestCase(
                test_id="P4-006",
                name="Audit Trail Integrity",
                phase=4,
                category=TestCategory.AUTHORITY,
                description="Audit trail maintains integrity on operator overrides",
                pass_criteria="Override chain documented",
                fail_criteria="Audit gaps or corruption",
            ),
            TestCase(
                test_id="P4-007",
                name="Trust Saturation Behavior",
                phase=4,
                category=TestCategory.TRUST,
                description="Trust Governor caps at defined limits",
                pass_criteria="Trust cap enforced",
                fail_criteria="Trust exceeds limits",
            ),
        ]
        
        for test in tests:
            self.tests[test.test_id] = test
    
    def _register_refinement_tests(self):
        """Register refinement tests."""
        tests = [
            TestCase(
                test_id="R-001",
                name="Skill Downgrade",
                phase=4,
                category=TestCategory.REFINEMENT,
                description="High-confidence skill is later downgraded",
                pass_criteria="ARVIS explicitly states 'We were confident earlier; new evidence weakens this'",
                fail_criteria="Silent downgrade or denial",
            ),
            TestCase(
                test_id="R-002",
                name="Confidence Decay",
                phase=4,
                category=TestCategory.REFINEMENT,
                description="Previously confident advisory becomes uncertain",
                pass_criteria="Decay documented with evidence",
                fail_criteria="No acknowledgment of uncertainty",
            ),
            TestCase(
                test_id="R-003",
                name="End-of-Pilot Self-Critique",
                phase=4,
                category=TestCategory.REFINEMENT,
                description="Day 90 mandatory self-assessment",
                pass_criteria="Output includes: What I Don't Know, Where I Was Wrong, What Needs Human Judgment",
                fail_criteria="Missing or incomplete self-critique",
            ),
        ]
        
        for test in tests:
            self.tests[test.test_id] = test
    
    def get_tests_by_phase(self, phase: int) -> List[TestCase]:
        """Get all tests for a specific phase."""
        return [t for t in self.tests.values() if t.phase == phase]
    
    def get_tests_by_category(self, category: TestCategory) -> List[TestCase]:
        """Get all tests for a specific category."""
        return [t for t in self.tests.values() if t.category == category]
    
    def get_test(self, test_id: str) -> Optional[TestCase]:
        """Get a specific test by ID."""
        return self.tests.get(test_id)
    
    def get_all_tests(self) -> List[TestCase]:
        """Get all registered tests."""
        return list(self.tests.values())
    
    def get_test_count(self) -> Dict[str, int]:
        """Get count of tests by phase."""
        counts = {}
        for test in self.tests.values():
            phase_key = f"phase_{test.phase}"
            counts[phase_key] = counts.get(phase_key, 0) + 1
        return counts
    
    def to_dict(self) -> Dict[str, Any]:
        """Export registry as dictionary."""
        return {
            "total_tests": len(self.tests),
            "by_phase": self.get_test_count(),
            "tests": {tid: t.to_dict() for tid, t in self.tests.items()},
        }
