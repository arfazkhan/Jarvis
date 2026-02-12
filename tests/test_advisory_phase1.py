"""
Test Advisory System - Phase 1
===============================

Unit tests for recommendation tracking, trust calibration, and preference learning.
"""

import pytest
import time
from pathlib import Path
import tempfile

from agent_advisory.recommendation_tracker import RecommendationTracker
from agent_advisory.trust_calibrator import TrustCalibrator
from agent_advisory.preference_learner import PreferenceLearningEngine
from agent_advisory.schemas import RecommendationStatus, OutcomeQuality


class TestRecommendationTracker:
    """Test recommendation tracking"""
    
    def setup_method(self):
        """Create temporary database for each test"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tracker = RecommendationTracker(db_path=self.temp_db.name)
    
    def teardown_method(self):
        """Clean up"""
        Path(self.temp_db.name).unlink(missing_ok=True)
    
    def test_log_recommendation(self):
        """Test logging a recommendation"""
        rec_id = self.tracker.log_recommendation(
            context={"alarm_type": "high_head_pressure"},
            recommended_action={"action": "shutdown", "equipment": "CH-01"},
            confidence=0.85,
            reasoning="High risk of compressor damage",
            predicted_outcome={"energy_savings_kwh": 0}
        )
        
        assert rec_id is not None
        assert len(rec_id) == 36  # UUID length
        
        # Verify it's in database
        rec = self.tracker.get_recommendation(rec_id)
        assert rec is not None
        assert rec.confidence == 0.85
        assert rec.reasoning == "High risk of compressor damage"
    
    def test_log_operator_decision_accepted(self):
        """Test operator accepting recommendation"""
        rec_id = self.tracker.log_recommendation(
            context={},
            recommended_action={"action": "shutdown"},
            confidence=0.9
        )
        
        # Operator follows recommendation
        self.tracker.log_operator_decision(
            recommendation_id=rec_id,
            operator_choice={"action": "shutdown"},
            operator_id="test_operator"
        )
        
        rec = self.tracker.get_recommendation(rec_id)
        assert rec.status == RecommendationStatus.ACCEPTED
        assert rec.operator_id == "test_operator"
    
    def test_log_operator_decision_rejected(self):
        """Test operator rejecting recommendation"""
        rec_id = self.tracker.log_recommendation(
            context={},
            recommended_action={"action": "shutdown"},
            confidence=0.9
        )
        
        # Operator chooses different action
        self.tracker.log_operator_decision(
            recommendation_id=rec_id,
            operator_choice={"action": "reduce_load"},
            operator_id="test_operator"
        )
        
        rec = self.tracker.get_recommendation(rec_id)
        assert rec.status == RecommendationStatus.REJECTED
    
    def test_log_outcome(self):
        """Test logging outcome"""
        rec_id = self.tracker.log_recommendation(
            context={},
            recommended_action={"action": "shutdown"},
            confidence=0.9
        )
        
        self.tracker.log_outcome(
            recommendation_id=rec_id,
            actual_outcome={"downtime_hours": 2},
            outcome_quality=OutcomeQuality.GOOD
        )
        
        rec = self.tracker.get_recommendation(rec_id)
        assert rec.outcome_quality == OutcomeQuality.GOOD
        assert rec.actual_outcome["downtime_hours"] == 2
    
    def test_calculate_trust_metrics_empty(self):
        """Test trust metrics with no data"""
        metrics = self.tracker.calculate_trust_metrics(window_days=30)
        
        assert metrics.total_recommendations == 0
        assert metrics.adoption_rate == 0.0
    
    def test_calculate_trust_metrics_with_data(self):
        """Test trust metrics with sample data"""
        
        # Create 10 recommendations
        for i in range(10):
            rec_id = self.tracker.log_recommendation(
                context={},
                recommended_action={"action": "test"},
                confidence=0.8
            )
            
            # Half accepted, half rejected
            if i < 5:
                self.tracker.log_operator_decision(
                    rec_id,
                    operator_choice={"action": "test"},
                    operator_id="test"
                )
                self.tracker.log_outcome(
                    rec_id,
                    actual_outcome={},
                    outcome_quality=OutcomeQuality.GOOD
                )
            else:
                self.tracker.log_operator_decision(
                    rec_id,
                    operator_choice={"action": "other"},
                    operator_id="test"
                )
        
        time.sleep(0.1)  # Ensure timestamps differ
        metrics = self.tracker.calculate_trust_metrics(window_days=1)
        
        assert metrics.total_recommendations == 10
        assert metrics.acceptance_count == 5
        assert metrics.rejection_count == 5
        assert metrics.adoption_rate == 0.5
        assert metrics.accuracy_when_followed == 1.0  # All accepted ones were GOOD


class TestTrustCalibrator:
    """Test trust calibration"""
    
    def setup_method(self):
        """Setup"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tracker = RecommendationTracker(db_path=self.temp_db.name)
        
        # Add some calibration data
        self._create_calibration_data()
        
        self.calibrator = TrustCalibrator(
            self.tracker,
            calibration_window_days=1,
            min_samples_per_bucket=2
        )
    
    def teardown_method(self):
        """Clean up"""
        Path(self.temp_db.name).unlink(missing_ok=True)
    
    def _create_calibration_data(self):
        """Create sample data for calibration"""
        
        # At 0.8 confidence, we're only right 60% of time
        for i in range(10):
            rec_id = self.tracker.log_recommendation(
                context={},
                recommended_action={"action": "test"},
                confidence=0.8
            )
            self.tracker.log_operator_decision(
                rec_id,
                operator_choice={"action": "test"},
                operator_id="test"
            )
            # 6 good, 4 poor = 60% accuracy
            quality = OutcomeQuality.GOOD if i < 6 else OutcomeQuality.POOR
            self.tracker.log_outcome(
                rec_id,
                actual_outcome={},
                outcome_quality=quality
            )
    
    def test_calibrate_confidence(self):
        """Test confidence calibration"""
        
        # We stated 0.8, but were only right 0.6 of time
        calibrated = self.calibrator.calibrate_confidence(0.8)
        
        # Should be close to 0.6
        assert 0.55 <= calibrated <= 0.65
    
    def test_no_calibration_for_unseen_bucket(self):
        """Test that unseen buckets return raw confidence"""
        
        # No data at 0.3 confidence
        calibrated = self.calibrator.calibrate_confidence(0.3)
        assert calibrated == 0.3
    
    def test_should_show_recommendation(self):
        """Test recommendation threshold"""
        
        # High confidence - should show
        assert self.calibrator.should_show_recommendation(0.9, threshold=0.65)
        
        # Low confidence - should not show
        assert not self.calibrator.should_show_recommendation(0.4, threshold=0.65)
    
    def test_get_confidence_explanation(self):
        """Test confidence explanation"""
        
        explanation = self.calibrator.get_confidence_explanation(0.8)
        
        assert explanation["raw_confidence"] == 0.8
        assert explanation["calibration_applied"] == True
        assert explanation["sample_count"] > 0


class TestPreferenceLearner:
    """Test preference learning"""
    
    def setup_method(self):
        """Setup"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.learner = PreferenceLearningEngine(db_path=self.temp_db.name)
    
    def teardown_method(self):
        """Clean up"""
        Path(self.temp_db.name).unlink(missing_ok=True)
    
    def test_record_agreement(self):
        """Test recording when operator agrees"""
        
        self.learner.record_decision(
            context={"alarm_type": "high_head_pressure"},
            agent_recommendation={"action": "shutdown"},
            operator_choice={"action": "shutdown"},
            operator_id="test_op"
        )
        
        summary = self.learner.get_operator_preferences_summary("test_op")
        assert summary["total_decisions"] == 1
        assert summary["agreement_count"] == 1
        assert summary["override_count"] == 0
    
    def test_record_override(self):
        """Test recording when operator overrides"""
        
        self.learner.record_decision(
            context={"alarm_type": "high_head_pressure"},
            agent_recommendation={"action": "shutdown"},
            operator_choice={"action": "reduce_load"},
            operator_id="test_op"
        )
        
        summary = self.learner.get_operator_preferences_summary("test_op")
        assert summary["total_decisions"] == 1
        assert summary["override_count"] == 1
        assert summary["override_rate"] == 1.0
    
    def test_rank_options_by_preference(self):
        """Test option ranking"""
        
        # Record that operator always chooses "reduce_load" over "shutdown"
        for _ in range(3):
            self.learner.record_decision(
                context={"alarm_type": "high_head_pressure"},
                agent_recommendation={"action": "shutdown"},
                operator_choice={"action": "reduce_load"},
                operator_id="test_op"
            )
        
        # Rank options
        ranked = self.learner.rank_options_by_preference(
            context={"alarm_type": "high_head_pressure"},
            options=[
                {"action": "shutdown"},
                {"action": "reduce_load"},
                {"action": "investigate"}
            ],
            operator_id="test_op"
        )
        
        # "reduce_load" should be ranked first
        assert ranked[0][0]["action"] == "reduce_load"
        assert ranked[0][1] > 0  # Non-zero score
    
    def test_preference_inference(self):
        """Test preference signal inference"""
        
        self.learner.record_decision(
            context={"alarm_type": "high_head_pressure"},
            agent_recommendation={"action": "shutdown"},
            operator_choice={"action": "reduce_load"},
            operator_id="test_op"
        )
        
        summary = self.learner.get_operator_preferences_summary("test_op")
        
        # Should have inferred a preference
        assert len(summary["top_preferences"]) > 0
        assert "graceful degradation" in summary["top_preferences"][0]["preference"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
