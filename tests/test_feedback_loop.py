
import pytest
from unittest.mock import MagicMock
from agent_advisory.feedback_loop import ActiveLearner, Recommendation, RecommendationStatus
from agent_advisory.recommendation_tracker import RecommendationTracker

class TestFeedbackLoop:
    
    @pytest.fixture
    def mock_tracker(self):
        tracker = MagicMock(spec=RecommendationTracker)
        
        # Setup mock recommendations
        
        # Rec 1: Rejected (Disagreement)
        r1 = MagicMock(spec=Recommendation)
        r1.id = "r1"
        r1.status = RecommendationStatus.REJECTED
        r1.recommended_action = {"action": "shutdown"}
        
        # Rec 2: Accepted Low Confidence (Verification)
        r2 = MagicMock(spec=Recommendation)
        r2.id = "r2"
        r2.status = RecommendationStatus.ACCEPTED
        r2.confidence = 0.55
        r2.recommended_action = {"action": "setpoint_change"}
        
        # Rec 3: Accepted High Confidence (No Feedback needed)
        r3 = MagicMock(spec=Recommendation)
        r3.id = "r3"
        r3.status = RecommendationStatus.ACCEPTED
        r3.confidence = 0.95
        
        tracker.get_recent_recommendations.return_value = [r1, r2, r3]
        return tracker

    def test_feedback_opportunities(self, mock_tracker):
        learner = ActiveLearner(mock_tracker)
        
        requests = learner.check_for_feedback_opportunities()
        
        assert len(requests) == 2
        
        # Check Disagreement Request
        r_disagree = next(r for r in requests if r.recommendation_id == "r1")
        assert r_disagree.question_type == "choice_rationale"
        assert "why" in r_disagree.question_text.lower() or "reason" in r_disagree.question_text.lower()
        
        # Check Verification Request
        r_verify = next(r for r in requests if r.recommendation_id == "r2")
        assert r_verify.question_type == "outcome_verification"
        assert "uncertain" in r_verify.question_text.lower()

if __name__ == "__main__":
    pytest.main([__file__])
