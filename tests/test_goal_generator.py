
import pytest
from unittest.mock import MagicMock, Mock
from datetime import datetime, timedelta
from agent_advisory.goal_generator import GoalGenerator, GoalScorer, ProactiveGoal
from agent_bms.predictive_maintenance import FailurePrediction

class TestGoalGenerator:
    
    @pytest.fixture
    def mock_engines(self):
        fleet = MagicMock()
        predictive = MagicMock()
        energy = MagicMock()
        
        # Setup Predictive Mock
        predictive.equipment_history = {"b1/chiller-01": ["feature_obj"]}
        
        prediction = FailurePrediction(
            equipment_id="b1/chiller-01",
            failure_probability=0.9,
            risk_level="critical",
            predicted_rul_days=5,
            confidence=0.8,
            recommendation="Fix it now",
            contributing_factors=[]
        )
        predictive.predict_failure.return_value = prediction
        
        # Setup Energy Mock
        pattern = MagicMock()
        pattern.building_id = "b1"
        pattern.pattern_type = "after_hours_hvac"
        pattern.estimated_waste_qar_annual = 15000
        pattern.description = "AC running at night"
        pattern.equipment_ids = ["ahu-01"]
        energy.identify_waste_patterns.return_value = [pattern]
        
        estimate = MagicMock()
        estimate.annual_savings_qar = 15000
        estimate.recommendation = "Adjust schedule"
        energy.estimate_savings.return_value = estimate
        
        # Setup Fleet Mock
        bench_result = MagicMock()
        bench_result.improvement_opportunities = [{
            "metric": "eui",
            "percentile": 20,
            "target": 120,
            "action": "Retrofit"
        }]
        fleet.benchmark_building.return_value = bench_result
        
        return fleet, predictive, energy

    def test_goal_scorer(self):
        scorer = GoalScorer()
        
        # Critical risk imminent
        s1 = scorer.calculate_score("risk_mitigation", 20000, "critical", 2)
        assert s1 > 0.9  # Should be very high
        
        # Low priority efficiency
        s2 = scorer.calculate_score("efficiency", 1000, "low", 30)
        assert s2 < s1

    def test_generate_goals(self, mock_engines):
        fleet, predictive, energy = mock_engines
        generator = GoalGenerator(fleet, predictive, energy)
        
        goals = generator.generate_goals("b1")
        
        assert len(goals) == 3
        
        # Verify Predictive Goal
        pred_goal = next(g for g in goals if g.source_engine == "predictive")
        assert pred_goal.priority == "critical"
        assert "Prevent Failure" in pred_goal.title
        
        # Verify Energy Goal
        energy_goal = next(g for g in goals if g.source_engine == "energy")
        assert energy_goal.potential_savings_qar == 15000
        
        # Verify Fleet Goal
        fleet_goal = next(g for g in goals if g.source_engine == "fleet")
        assert fleet_goal.goal_type == "optimization"

if __name__ == "__main__":
    pytest.main([__file__])
