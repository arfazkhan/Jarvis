from unittest.mock import MagicMock

from agent_advisory.goal_generator import GoalGenerator
from agent_commercial.gsas_reporter import GSASReporter, GSASStarRating


def _reporter():
    reporter = GSASReporter(building_id="b1", target_rating=GSASStarRating.THREE_STAR)
    reporter.initialize_criteria()
    reporter.update_from_bms(
        energy_data={"consumption_vs_baseline": 8, "submetering_coverage": 45},
        iaq_data={"comfort_compliance": 78, "co2_compliance": 82},
        maintenance_data={"pm_compliance": 70},
    )
    return reporter


def test_gsas_reporter_scores_operational_recommendations():
    reporter = _reporter()

    impact = reporter.score_operational_recommendation({
        "title": "Fix After Hours HVAC",
        "description": "AHU-01 is running at night with no occupancy",
        "goal_type": "efficiency",
        "source_engine": "energy",
        "priority": "high",
        "potential_savings_qar": 15000,
        "equipment_ids": ["AHU-01"],
        "suggested_actions": ["Adjust schedule"],
    })

    assert impact.category == "E"
    assert "E.1" in impact.criteria
    assert impact.target_delta > 0
    assert impact.impact_score > 0
    assert impact.confidence >= 0.8
    assert any("Relevant criteria" in item for item in impact.evidence)


def test_goal_generator_attaches_gsas_impact_and_boosts_energy_goals():
    energy = MagicMock()
    pattern = MagicMock()
    pattern.building_id = "b1"
    pattern.pattern_type = "after_hours_hvac"
    pattern.estimated_waste_qar_annual = 15000
    pattern.description = "AHU running after hours"
    pattern.equipment_ids = ["AHU-01"]
    energy.identify_waste_patterns.return_value = [pattern]

    estimate = MagicMock()
    estimate.annual_savings_qar = 15000
    estimate.recommendation = "Adjust HVAC schedule"
    energy.estimate_savings.return_value = estimate

    generator = GoalGenerator(
        energy_analyzer=energy,
        gsas_reporter=_reporter(),
    )

    goals = generator.generate_goals("b1")

    assert len(goals) == 1
    goal = goals[0]
    assert goal.gsas_impact["category"] == "E"
    assert goal.gsas_impact["target_delta"] > 0
    assert any("Track GSAS impact" in action for action in goal.suggested_actions)


def test_gsas_optimization_ranks_target_relevant_recommendations_first():
    reporter = _reporter()

    optimized = reporter.optimize_recommendations_for_targets([
        {
            "title": "Paint lobby wall",
            "description": "Cosmetic refresh",
            "goal_type": "general",
            "source_engine": "manual",
        },
        {
            "title": "Optimize Chiller Sequencing",
            "description": "Reduce peak energy and improve HVAC efficiency",
            "goal_type": "efficiency",
            "source_engine": "energy",
            "priority": "high",
            "potential_savings_qar": 40000,
            "equipment_ids": ["CH-01"],
        },
    ])

    assert optimized[0]["title"] == "Optimize Chiller Sequencing"
    assert optimized[0]["gsas_impact"]["category"] == "E"
    assert optimized[0]["gsas_impact"]["impact_score"] > optimized[1]["gsas_impact"]["impact_score"]
