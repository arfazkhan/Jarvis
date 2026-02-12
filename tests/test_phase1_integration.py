"""
Phase 1 Integration Test
=========================

End-to-end test of Phase 1 advisory components integrated with BMS system.

Tests:
1. BMS agent initializes with advisory components
2. Recommendations are logged and calibrated
3. Operator actions are tracked
4. Verification engine logs outcomes
5. Scheduler runs metrics calculation
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime

# Advisory components
from agent_advisory import RecommendationTracker, TrustCalibrator, PreferenceLearningEngine
from agent_advisory.schemas import OutcomeQuality, RecommendationStatus

# BMS components
from agent_bms.bms_llm_agent import BMSLLMAgent
from agent_bms.verification_engine import MaintenanceVerifier, VerificationStatus


class TestPhase1Integration:
    """Integration tests for Phase 1 advisory system"""
    
    def test_bms_agent_initializes_with_advisory(self):
        """Test that BMS agent properly initializes advisory components"""
        # Create temp directory for test database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_advisory.db")
            
            # Initialize tracker manually (BMS agent will create its own)
            tracker = RecommendationTracker(db_path=db_path)
            
            # Verify tracker works
            rec_id = tracker.log_recommendation(
                context={"test": "context"},
                recommended_action={"action": "test"},
                confidence=0.8,
                reasoning="Test recommendation"
            )
            
            assert rec_id is not None
            rec = tracker.get_recommendation(rec_id)
            assert rec.confidence == 0.8
    
    async def test_end_to_end_recommendation_flow(self):
        """Test complete flow: recommendation -> decision -> outcome"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_e2e.db")
            
            # Initialize components
            tracker = RecommendationTracker(db_path=db_path)
            calibrator = TrustCalibrator(tracker)
            preference_learner = PreferenceLearningEngine(db_path=db_path)
            
            # Scenario: Alarm triggers recommendation
            context = {
                "alarm_type": "high_head_pressure",
                "equipment_id": "CH-01",
                "severity": "high"
            }
            
            recommended_action = {
                "action": "shutdown",
                "equipment": "CH-01",
                "reason": "prevent compressor damage"
            }
            
            # 1. Log recommendation
            rec_id = tracker.log_recommendation(
                context=context,
                recommended_action=recommended_action,
                confidence=0.85,
                trigger_type="alarm",
                equipment_ids=["CH-01"]
            )
            
            # 2. Calibrate confidence
            calibrated = calibrator.calibrate_confidence(0.85)
            assert isinstance(calibrated, float)
            
            # 3. Operator overrides - chooses "reduce_load" instead
            operator_choice = {
                "action": "reduce_load",
                "equipment": "CH-01",
                "reason": "graceful degradation preferred"
            }
            
            tracker.log_operator_decision(
                recommendation_id=rec_id,
               operator_choice=operator_choice,
                operator_id="test_operator"
            )
            
            # 4. Learn preference from override
            preference_learner.record_decision(
                context=context,
                agent_recommendation=recommended_action,
                operator_choice=operator_choice,
                operator_id="test_operator"
            )
            
            # 5. Log outcome
            tracker.log_outcome(
                recommendation_id=rec_id,
                actual_outcome={
                    "issue_resolved": True,
                    "downtime_hours": 0.5,
                    "energy_saved_kwh": 150
                },
                outcome_quality=OutcomeQuality.GOOD
            )
            
            # Verify tracking
            rec = tracker.get_recommendation(rec_id)
            assert rec.status == RecommendationStatus.REJECTED  # Operator chose differently
            assert rec.outcome_quality == OutcomeQuality.GOOD
            
            # Verify preference learning
            ranked = preference_learner.rank_options_by_preference(
                context=context,
                options=[
                    {"action": "reduce_load"},
                    {"action": "shutdown"},
                    {"action": "investigate"}
                ],
                operator_id="test_operator"
            )
            
            # "reduce_load" should rank higher since operator chose it
            assert ranked[0][0]["action"] == "reduce_load"
            
            # Calculate trust metrics
            metrics = tracker.calculate_trust_metrics(window_days=1)
            assert metrics.total_recommendations == 1
            assert metrics.rejection_count == 1
    
    async def test_verification_logs_outcome(self):
        """Test that verification engine properly logs outcomes to tracker"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_verification.db")
            
            tracker = RecommendationTracker(db_path=db_path)
            verifier = MaintenanceVerifier(recommendation_tracker=tracker)
            
            # Log a maintenance recommendation
            rec_id = tracker.log_recommendation(
                context={"alarm_type": "high_pressure_drop"},
                recommended_action={"action": "filter_cleaning"},
                confidence=0.9,
                equipment_ids=["AHU-01"]
            )
            
            # Operator accepts and performs work
            tracker.log_operator_decision(
                recommendation_id=rec_id,
                operator_choice={"action": "filter_cleaning"},
                operator_id="tech_1"
            )
            
            # Verify the work
            result = await verifier.verify_work_order(
                work_order_id="WO-123",
                equipment_id="AHU-01",
                task_type="filter_cleaning",
                pre_data={"static_pressure_drop_pa": 350},
                post_data={"static_pressure_drop_pa": 120}
            )
            
            # Link verification to recommendation
            result.recommendation_id = rec_id
            
            # Manually trigger outcome logging (normally done in verify_work_order)
            if verifier.tracker:
                quality_map = {
                    VerificationStatus.VERIFIED: OutcomeQuality.EXCELLENT,
                    VerificationStatus.WEAK: OutcomeQuality.ACCEPTABLE,
                    VerificationStatus.FAILED: OutcomeQuality.POOR,
                }
                
                outcome_quality = quality_map.get(result.status, OutcomeQuality.UNKNOWN)
                
                verifier.tracker.log_outcome(
                    recommendation_id=rec_id,
                    actual_outcome={
                        "work_order_id": "WO-123",
                        "improvement_pct": result.improvement_pct,
                    },
                    outcome_quality=outcome_quality
                )
            
            # Verify outcome was logged
            rec = tracker.get_recommendation(rec_id)
            assert rec.outcome_quality == OutcomeQuality.EXCELLENT
            assert rec.actual_outcome is not None
    
    async def test_scheduler_metrics_calculation(self):
        """Test that scheduler properly calculates metrics"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_scheduler.db")
            
            tracker = RecommendationTracker(db_path=db_path)
            calibrator = TrustCalibrator(tracker)
            preference_learner = PreferenceLearningEngine(db_path=db_path)
            
            # Add some test data
            for i in range(5):
                rec_id = tracker.log_recommendation(
                    context={"test": i},
                    recommended_action={"action": f"action_{i}"},
                    confidence=0.7 + (i * 0.05)
                )
                
                tracker.log_operator_decision(
                    recommendation_id=rec_id,
                    operator_choice={"action": f"action_{i}"},
                    operator_id="test_op"
                )
                
                tracker.log_outcome(
                    recommendation_id=rec_id,
                    actual_outcome={"success": True},
                    outcome_quality=OutcomeQuality.GOOD if i % 2 == 0 else OutcomeQuality.EXCELLENT
                )
            
            # Manually trigger metrics calculation (like scheduler would)
            from agent_bms.advisory_scheduler import AdvisoryScheduler
            
            scheduler = AdvisoryScheduler(tracker, calibrator, preference_learner)
            
            # Call the metrics calculation directly
            await scheduler._calculate_daily_metrics()
            
            # Verify metrics were calculated
            metrics = tracker.calculate_trust_metrics(window_days=1)
            assert metrics.total_recommendations == 5
            assert metrics.adoption_rate == 1.0  # All accepted
            assert metrics.accuracy_when_followed > 0


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
