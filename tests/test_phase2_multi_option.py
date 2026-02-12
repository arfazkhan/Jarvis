"""
Phase 2: Multi-Option Analysis Integration Tests
==================================================

Comprehensive tests for the agentic, ML-backed advisory system.
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any, List


# ═══════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_context() -> Dict[str, Any]:
    """Sample operational context for testing"""
    return {
        "timestamp": datetime.now(),
        "outdoor_temp_c": 44.5,
        "outdoor_humidity_pct": 35,
        "solar_radiation_wm2": 850,
        "wind_speed_ms": 3.2,
        "sandstorm_active": False,
        "zone_temp_avg_c": 23.5,
        "zone_temp_variance": 0.8,
        "supply_air_temp_c": 12.5,
        "return_air_temp_c": 24.0,
        "chw_supply_temp_c": 6.5,
        "chw_delta_t_c": 5.5,
        "ahu_static_pressure_pa": 265,
        "vav_position_avg_pct": 72,
        "occupancy_ratio": 0.85,
        "cooling_load_pct": 78,
        "chiller_efficiency_kw_ton": 0.62,
        "total_power_kw": 580,
        "equipment_age_years": 6,
        "hours_since_maintenance": 1200,
        "fault_count_30d": 2,
        "reliability_score": 0.87,
        "building_id": "WBT-001",
    }


@pytest.fixture
def sample_action() -> Dict[str, Any]:
    """Sample action for testing"""
    return {
        "action_type": "reduce_load",
        "action_description": "Reduce cooling load by 15%",
        "equipment_id": "CH-01",
        "risk_score": 2,
        "comfort_score": 3,
        "energy_impact_pct": -12,
        "estimated_time_min": 20,
        "estimated_cost_qar": 150,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Qatar Context Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestQatarContext:
    """Test Qatar-specific context and helpers"""
    
    def test_building_profiles_exist(self):
        """Should have Qatar building profiles"""
        from agent_advisory.qatar import QATAR_BUILDINGS
        
        assert len(QATAR_BUILDINGS) >= 5
        assert "west_bay_tower_1" in QATAR_BUILDINGS
        assert "lusail_mixed_use" in QATAR_BUILDINGS
    
    def test_building_profile_attributes(self):
        """Building profiles should have required attributes"""
        from agent_advisory.qatar import QATAR_BUILDINGS, BuildingProfile
        
        for key, building in QATAR_BUILDINGS.items():
            assert isinstance(building, BuildingProfile)
            assert building.id
            assert building.name
            assert building.type
            assert building.floors > 0
            assert building.gfa_sqm > 0
            assert building.cooling_capacity_tons > 0
    
    def test_operator_personas_exist(self):
        """Should have operator personas for preference learning"""
        from agent_advisory.qatar import OPERATOR_PERSONAS
        
        assert len(OPERATOR_PERSONAS) >= 4
        assert "ahmed_senior_fm" in OPERATOR_PERSONAS
        assert "sarah_energy_manager" in OPERATOR_PERSONAS
    
    def test_operator_preference_scoring(self):
        """Operator personas should score options differently"""
        from agent_advisory.qatar import OPERATOR_PERSONAS
        
        action = {
            "risk_score": 2,
            "comfort_score": 4,
            "energy_impact_pct": -15,  # Saves energy
            "cost_qar": 500,
        }
        
        # Energy manager should score energy-saving actions higher
        sarah = OPERATOR_PERSONAS["sarah_energy_manager"]
        ahmed = OPERATOR_PERSONAS["ahmed_senior_fm"]
        
        sarah_score = sarah.preference_score(action)
        ahmed_score = ahmed.preference_score(action)
        
        # Sarah prioritizes energy, should score this higher
        assert sarah_score > 0
        assert ahmed_score > 0
        # Different personas = different scores
        assert sarah_score != ahmed_score
    
    def test_kahramaa_tariffs(self):
        """Should have KAHRAMAA electricity tariffs"""
        from agent_advisory.qatar import KAHRAMAA_TARIFFS, get_kahramaa_rate
        
        assert "commercial_private" in KAHRAMAA_TARIFFS
        assert KAHRAMAA_TARIFFS["commercial_private"] == 0.23
        
        rate = get_kahramaa_rate("commercial_office")
        assert rate > 0
    
    def test_calendar_helpers(self):
        """Calendar helpers should work correctly"""
        from agent_advisory.qatar import (
            is_qatar_working_day,
            is_summer,
            is_sandstorm_season,
        )
        
        # Test summer
        july = datetime(2024, 7, 15)
        december = datetime(2024, 12, 15)
        
        assert is_summer(july) == True
        assert is_summer(december) == False
        
        # Test sandstorm season
        april = datetime(2024, 4, 15)
        october = datetime(2024, 10, 15)
        
        assert is_sandstorm_season(april) == True
        assert is_sandstorm_season(october) == False


# ═══════════════════════════════════════════════════════════════════════════
# Feature Engineering Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFeatureEngineering:
    """Test feature extraction for ML models"""
    
    def test_feature_count(self, sample_context):
        """Should extract 50 features"""
        from agent_advisory.qatar import QatarFeatureEngineer
        
        fe = QatarFeatureEngineer()
        features = fe.extract_features(sample_context)
        
        assert len(features) == 50
        assert features.dtype.name.startswith("float")
    
    def test_feature_names(self):
        """Should have named features"""
        from agent_advisory.qatar import QatarFeatureEngineer
        
        fe = QatarFeatureEngineer()
        names = fe.get_feature_names()
        
        assert len(names) == 50
        assert "outdoor_temp_c" in names
        assert "is_summer" in names
        assert "reliability_score" in names
    
    def test_temporal_features(self):
        """Temporal features should be cyclical encoded"""
        from agent_advisory.qatar import QatarFeatureEngineer
        
        fe = QatarFeatureEngineer()
        
        # Morning context
        morning = {"timestamp": datetime(2024, 7, 15, 8, 0)}
        # Evening context
        evening = {"timestamp": datetime(2024, 7, 15, 20, 0)}
        
        morning_feat = fe.extract_features(morning)
        evening_feat = fe.extract_features(evening)
        
        # hour_sin and hour_cos should be different
        assert morning_feat[0] != evening_feat[0]
        assert morning_feat[1] != evening_feat[1]
    
    def test_action_feature_extraction(self, sample_action):
        """Should extract action features"""
        from agent_advisory.qatar.feature_engineer import ActionFeatureEngineer
        
        fe = ActionFeatureEngineer()
        features = fe.extract_features(sample_action)
        
        assert len(features) == 12
        assert features.dtype.name.startswith("float")


# ═══════════════════════════════════════════════════════════════════════════
# ML Models Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOutcomePredictor:
    """Test outcome prediction model"""
    
    def test_predictor_init(self):
        """Should initialize without errors"""
        from agent_advisory import OutcomePredictor
        
        predictor = OutcomePredictor()
        assert predictor is not None
    
    def test_predict_returns_prediction(self, sample_context, sample_action):
        """Should return OutcomePrediction"""
        from agent_advisory import OutcomePredictor, OutcomePrediction
        
        predictor = OutcomePredictor()
        result = predictor.predict(sample_context, sample_action)
        
        assert isinstance(result, OutcomePrediction)
        assert result.predicted_quality in ["poor", "acceptable", "good", "excellent"]
        assert 0 <= result.confidence <= 1
        assert len(result.quality_probabilities) == 4
    
    def test_heuristic_fallback(self, sample_context, sample_action):
        """Should use heuristics when model not trained"""
        from agent_advisory import OutcomePredictor
        
        predictor = OutcomePredictor()
        assert predictor.is_trained == False
        
        # Should still return predictions via heuristics
        result = predictor.predict(sample_context, sample_action)
        assert result.predicted_quality is not None


class TestPreferenceRanker:
    """Test preference ranking model"""
    
    def test_ranker_init(self):
        """Should initialize without errors"""
        from agent_advisory import PreferenceRankingModel
        
        ranker = PreferenceRankingModel()
        assert ranker is not None
    
    def test_rank_options(self, sample_context):
        """Should rank multiple options"""
        from agent_advisory import PreferenceRankingModel, RankedOption
        
        options = [
            {"action_type": "reduce_load", "risk_score": 2, "comfort_score": 3},
            {"action_type": "shutdown", "risk_score": 4, "comfort_score": 2},
            {"action_type": "investigate", "risk_score": 1, "comfort_score": 4},
        ]
        
        ranker = PreferenceRankingModel()
        ranked = ranker.rank_options(options, sample_context)
        
        assert len(ranked) == 3
        assert all(isinstance(r, RankedOption) for r in ranked)
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2
        assert ranked[2].rank == 3
    
    def test_learn_from_decision(self, sample_context):
        """Should accept decision feedback"""
        from agent_advisory import PreferenceRankingModel
        
        options = [
            {"action_type": "reduce_load"},
            {"action_type": "shutdown"},
        ]
        
        ranker = PreferenceRankingModel()
        
        # Should not raise
        ranker.learn_from_decision(
            options=options,
            chosen_index=0,
            context=sample_context,
            operator_id="test_operator"
        )


class TestContextualBandit:
    """Test exploration/exploitation"""
    
    def test_bandit_init(self):
        """Should initialize with exploration rate"""
        from agent_advisory import ContextualBandit
        
        bandit = ContextualBandit(exploration_rate=0.1)
        assert bandit.exploration_rate == 0.1
    
    def test_should_explore(self):
        """Should sometimes explore"""
        from agent_advisory import ContextualBandit
        
        bandit = ContextualBandit(exploration_rate=0.5)  # 50% explore
        
        # Run many times, should have some explores
        explores = sum(1 for _ in range(100) if bandit.should_explore())
        assert 20 < explores < 80  # Should be around 50
    
    def test_update_belief(self):
        """Should update success rate beliefs"""
        from agent_advisory import ContextualBandit
        
        bandit = ContextualBandit()
        
        # Initial success rate should be ~50%
        initial_rate = bandit.get_action_success_rate("reduce_load")
        assert 0.4 < initial_rate < 0.6
        
        # Add successes
        for _ in range(5):
            bandit.update_belief("reduce_load", True)
        
        # Success rate should increase
        new_rate = bandit.get_action_success_rate("reduce_load")
        assert new_rate > initial_rate


# ═══════════════════════════════════════════════════════════════════════════
# Agentic Components Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAgenticOptionGenerator:
    """Test LLM-based option generation"""
    
    def test_generator_init(self):
        """Should initialize without errors"""
        from agent_advisory import AgenticOptionGenerator
        
        generator = AgenticOptionGenerator(llm=None)
        assert generator is not None
    
    def test_fallback_options(self):
        """Should generate fallback options when LLM unavailable"""
        from agent_advisory import AgenticOptionGenerator, GeneratedOption
        
        generator = AgenticOptionGenerator(llm=None)
        options = generator._generate_fallback_options(
            issue_type="high_head_pressure",
            equipment_id="CH-01"
        )
        
        assert len(options) == 5
        assert all(isinstance(o, GeneratedOption) for o in options)
    
    def test_generated_option_to_dict(self):
        """GeneratedOption should convert to dict"""
        from agent_advisory import GeneratedOption
        
        option = GeneratedOption(
            action_type="reduce_load",
            action_description="Test action",
            equipment_id="CH-01",
            risk_score=2,
        )
        
        data = option.to_dict()
        assert data["action_type"] == "reduce_load"
        assert data["equipment_id"] == "CH-01"


# ═══════════════════════════════════════════════════════════════════════════
# Simulator Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestQatarBuildingSimulator:
    """Test synthetic data generation"""
    
    def test_simulator_init(self):
        """Should initialize with seed"""
        from agent_advisory.qatar import QatarBuildingSimulator
        
        sim = QatarBuildingSimulator(seed=42)
        assert sim is not None
    
    def test_simulate_weather(self):
        """Should generate realistic weather"""
        from agent_advisory.qatar import QatarBuildingSimulator
        
        sim = QatarBuildingSimulator(seed=42)
        
        # Summer day
        summer = datetime(2024, 7, 15, 14, 0)
        weather = sim.simulate_weather(summer)
        
        assert "outdoor_temp_c" in weather
        assert 30 < weather["outdoor_temp_c"] < 50  # Qatar summer range
        assert "outdoor_humidity_pct" in weather
        assert 0 < weather["outdoor_humidity_pct"] < 100
    
    def test_generate_scenario(self):
        """Should generate complete scenario"""
        from agent_advisory.qatar import QatarBuildingSimulator, SimulatedScenario
        
        sim = QatarBuildingSimulator(seed=42)
        scenario = sim.generate_scenario()
        
        assert isinstance(scenario, SimulatedScenario)
        assert scenario.scenario_id.startswith("SIM-")
        assert scenario.issue_type in sim.ISSUE_TYPES
        assert scenario.context is not None
        assert scenario.outcome_quality in ["poor", "acceptable", "good", "excellent"]
    
    def test_generate_multiple_scenarios(self):
        """Should generate batch of scenarios"""
        from agent_advisory.qatar import QatarBuildingSimulator
        
        sim = QatarBuildingSimulator(seed=42)
        scenarios = sim.generate_scenarios(n=10)
        
        assert len(scenarios) == 10
        
        # Should have variety
        issue_types = set(s.issue_type for s in scenarios)
        assert len(issue_types) > 1  # Multiple issue types


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Option Advisor Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiOptionAdvisor:
    """Integration tests for the main advisor"""
    
    def test_advisor_init(self):
        """Should initialize with all components"""
        from agent_advisory import MultiOptionAdvisor
        
        advisor = MultiOptionAdvisor()
        
        assert advisor.tracker is not None
        assert advisor.preference_learner is not None
        assert advisor.outcome_predictor is not None
        assert advisor.ranking_model is not None
        assert advisor.bandit is not None
        assert advisor.option_generator is not None
    
    @pytest.mark.asyncio
    async def test_get_advice(self, sample_context):
        """Should return advisory response"""
        from agent_advisory import MultiOptionAdvisor, AdvisoryResponse
        
        advisor = MultiOptionAdvisor()
        
        response = await advisor.get_advice(
            context=sample_context,
            issue_type="high_head_pressure",
            equipment_id="CH-01",
            operator_id="ahmed_senior_fm",
        )
        
        assert isinstance(response, AdvisoryResponse)
        assert len(response.options) > 0
        assert response.top_recommendation is not None
        assert response.recommendation_id is not None
        assert 0 <= response.calibrated_confidence <= 1
    
    @pytest.mark.asyncio
    async def test_record_decision(self, sample_context):
        """Should record operator decision"""
        from agent_advisory import MultiOptionAdvisor
        
        advisor = MultiOptionAdvisor()
        
        # Get advice
        response = await advisor.get_advice(
            context=sample_context,
            issue_type="high_head_pressure",
            equipment_id="CH-01",
        )
        
        options = [o.option for o in response.options]
        
        # Record decision - should not raise
        await advisor.record_decision(
            recommendation_id=response.recommendation_id,
            chosen_option_index=0,
            operator_id="test_operator",
            options=options,
        )
    
    @pytest.mark.asyncio 
    async def test_record_outcome(self, sample_context):
        """Should record outcome for learning"""
        from agent_advisory import MultiOptionAdvisor
        
        advisor = MultiOptionAdvisor()
        
        response = await advisor.get_advice(
            context=sample_context,
            issue_type="filter_clogged",
            equipment_id="AHU-01",
        )
        
        # Record outcome - should not raise
        await advisor.record_outcome(
            recommendation_id=response.recommendation_id,
            actual_outcome={"resolved": True},
            outcome_quality="good",
        )
    
    def test_advisory_response_formatting(self, sample_context):
        """AdvisoryResponse should format for display"""
        from agent_advisory.multi_option_advisor import AdvisoryResponse
        from agent_advisory import RankedOption
        from datetime import datetime
        
        response = AdvisoryResponse(
            issue_type="high_head_pressure",
            equipment_id="CH-01",
            timestamp=datetime.now(),
            options=[
                RankedOption(
                    option={"action_type": "reduce_load", "action_description": "Test"},
                    rank=1,
                    preference_score=0.85,
                    predicted_outcome="good",
                    confidence=0.75,
                ),
            ],
            top_recommendation=RankedOption(
                option={"action_type": "reduce_load", "action_description": "Test"},
                rank=1,
                preference_score=0.85,
                predicted_outcome="good",
                confidence=0.75,
            ),
            top_explanation="This is the recommended action.",
            recommendation_id="REC-001",
            building_id="WBT-001",
            operator_id="test",
            overall_confidence=0.75,
            calibrated_confidence=0.72,
            context_summary="Test context",
        )
        
        # Should format as string
        display = response.format_for_display()
        assert "Advisory:" in display
        assert "reduce_load" in display
        
        # Should convert to dict
        data = response.to_dict()
        assert data["issue_type"] == "high_head_pressure"
        assert len(data["options"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# End-to-End Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEndToEndFlow:
    """End-to-end tests simulating real usage"""
    
    @pytest.mark.asyncio
    async def test_full_advisory_flow(self):
        """Test complete advisory flow: advise -> decide -> outcome -> learn"""
        from agent_advisory import MultiOptionAdvisor
        from agent_advisory.qatar import QatarBuildingSimulator
        
        # Generate synthetic scenario
        sim = QatarBuildingSimulator(seed=42)
        scenario = sim.generate_scenario()
        
        # Get advice
        advisor = MultiOptionAdvisor()
        response = await advisor.get_advice(
            context=scenario.context,
            issue_type=scenario.issue_type,
            equipment_id=scenario.equipment_id,
        )
        
        assert len(response.options) > 0
        
        # Simulate operator choosing first option
        if response.options:
            await advisor.record_decision(
                recommendation_id=response.recommendation_id,
                chosen_option_index=0,
                operator_id=scenario.operator_id,
                options=[o.option for o in response.options],
            )
        
        # Simulate outcome
        await advisor.record_outcome(
            recommendation_id=response.recommendation_id,
            actual_outcome={"resolved": True},
            outcome_quality=scenario.outcome_quality,
        )
    
    @pytest.mark.asyncio
    async def test_multiple_scenarios(self):
        """Test advisor on multiple scenarios"""
        from agent_advisory import MultiOptionAdvisor
        from agent_advisory.qatar import QatarBuildingSimulator
        
        sim = QatarBuildingSimulator(seed=123)
        scenarios = sim.generate_scenarios(n=5)
        
        advisor = MultiOptionAdvisor()
        
        for scenario in scenarios:
            response = await advisor.get_advice(
                context=scenario.context,
                issue_type=scenario.issue_type,
                equipment_id=scenario.equipment_id,
            )
            
            # Each should get recommendations
            assert response.top_recommendation is not None


# ═══════════════════════════════════════════════════════════════════════════
# Run Tests
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
