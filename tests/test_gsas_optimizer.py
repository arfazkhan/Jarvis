#!/usr/bin/env python3
"""
Test: GSAS Optimizer
====================

Tests the GSAS optimizer:
1. Gap analysis
2. Recommendation generation
3. Action scoring
4. ABI integration
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_commercial.gsas_reporter import GSASReporter, GSASCategory, GSASStarRating
from agent_commercial.gsas_optimizer import GSASOptimizer, GSASGap, GSASRecommendation


class MockBMSState:
    """Mock BMS state for testing."""
    
    async def get_equipment_list(self):
        return [
            {"equipment_id": "CH-01", "equipment_type": "chiller"},
            {"equipment_id": "AHU-01", "equipment_type": "ahu"},
            {"equipment_id": "CT-01", "equipment_type": "cooling_tower"},
        ]


async def test_gap_analysis():
    """Test gap identification."""
    print("\n" + "=" * 60)
    print("TEST 1: Gap Analysis")
    print("=" * 60)
    
    reporter = GSASReporter(building_id="TEST-BLDG-001", target_rating=GSASStarRating.FOUR_STAR)
    reporter.initialize_criteria()  # <-- Add this
    
    # Set some scores
    reporter.set_criterion_score("E.1", 1.5)  # Gap of 1.5
    reporter.set_criterion_score("E.2", 2.0)  # Gap of 1.0
    reporter.set_criterion_score("IE.1", 2.5)  # Gap of 0.5
    reporter.set_criterion_score("IE.2", 1.0)  # Gap of 2.0
    reporter.set_criterion_score("MO.1", 2.0)  # Gap of 1.0
    
    optimizer = GSASOptimizer(reporter, target_rating=GSASStarRating.FOUR_STAR)
    gaps = await optimizer.analyze_gaps()
    
    print(f"\nFound {len(gaps)} gaps:")
    for gap in gaps[:5]:
        print(f"  {gap.criterion_id}: {gap.criterion_name}")
        print(f"    Current: {gap.current_points:.1f}/{gap.max_points:.1f}")
        print(f"    Gap: {gap.gap_points:.1f} points ({gap.gap_percentage:.1f}%)")
        print(f"    BMS-controllable: {gap.is_bms_controllable}")
        print(f"    Priority: {gap.priority}")
    
    assert len(gaps) > 0, "Should find gaps"
    
    bms_controllable = [g for g in gaps if g.is_bms_controllable]
    print(f"\n✅ BMS-controllable gaps: {len(bms_controllable)}")
    
    return True


async def test_recommendation_generation():
    """Test recommendation generation."""
    print("\n" + "=" * 60)
    print("TEST 2: Recommendation Generation")
    print("=" * 60)
    
    reporter = GSASReporter(building_id="TEST-BLDG-001", target_rating=GSASStarRating.FOUR_STAR)
    reporter.initialize_criteria()  # Initialize criteria
    reporter.set_criterion_score("E.1", 1.5)  # Energy gap
    reporter.set_criterion_score("IE.2", 1.0)  # IAQ gap
    
    bms_state = MockBMSState()
    optimizer = GSASOptimizer(reporter, bms_state=bms_state, target_rating=GSASStarRating.FOUR_STAR)
    
    recommendations = await optimizer.generate_recommendations(max_recommendations=5)
    
    print(f"\nGenerated {len(recommendations)} recommendations:")
    for rec in recommendations:
        print(f"\n  [{rec.recommendation_id}] {rec.title}")
        print(f"  Category: {rec.category} | Criterion: {rec.target_criterion}")
        print(f"  Estimated gain: {rec.estimated_points_gain:.2f} points")
        print(f"  Star impact: +{rec.estimated_star_impact:.3f} stars")
        print(f"  Confidence: {rec.confidence:.0%}")
        print(f"  Cost: {rec.cost_estimate} | Effort: {rec.effort_estimate}")
        print(f"  BMS actions: {len(rec.bms_actions)}")
        for action in rec.bms_actions:
            print(f"    - {action.get('action_type')}")
    
    assert len(recommendations) > 0, "Should generate recommendations"
    
    # Check that recommendations have positive impact
    for rec in recommendations:
        assert rec.estimated_points_gain > 0, "Recommendations should have positive impact"
        assert rec.confidence > 0.5, "Confidence should be reasonable"
    
    print("\n✅ All recommendations have positive estimated impact")
    
    return True


async def test_action_scoring():
    """Test scoring individual actions for GSAS impact."""
    print("\n" + "=" * 60)
    print("TEST 3: Action Scoring")
    print("=" * 60)
    
    reporter = GSASReporter(building_id="TEST-BLDG-001", target_rating=GSASStarRating.FOUR_STAR)
    reporter.initialize_criteria()  # Initialize criteria
    reporter.set_criterion_score("E.1", 1.5)
    reporter.set_criterion_score("IE.2", 1.0)
    
    optimizer = GSASOptimizer(reporter, target_rating=GSASStarRating.FOUR_STAR)
    
    # Score some actions
    actions = [
        {"action_type": "setpoint_optimization", "description": "Optimize CHW supply temp"},
        {"action_type": "demand_limiting", "description": "Implement demand limiting"},
        {"action_type": "ventilation_optimization", "description": "DCV control"},
        {"action_type": "unknown_action", "description": "Some random action"},
    ]
    
    for action in actions:
        score = await optimizer.score_action_for_gsas(action)
        print(f"\n  Action: {action['action_type']}")
        print(f"    GSAS-aligned: {score['gsas_aligned']}")
        print(f"    Matching criteria: {score['matching_criteria']}")
        print(f"    Estimated gain: {score['estimated_points_gain']:.2f} points")
    
    # Check that energy actions are aligned
    energy_action = await optimizer.score_action_for_gsas({"action_type": "setpoint_optimization"})
    assert energy_action["gsas_aligned"], "Energy action should be GSAS-aligned"
    
    # Check that unknown actions are not aligned
    unknown_action = await optimizer.score_action_for_gsas({"action_type": "unknown_action"})
    assert not unknown_action["gsas_aligned"], "Unknown action should not be GSAS-aligned"
    
    print("\n✅ Action scoring correctly identifies GSAS-aligned actions")
    
    return True


async def test_implementation_tracking():
    """Test recommendation implementation tracking."""
    print("\n" + "=" * 60)
    print("TEST 4: Implementation Tracking")
    print("=" * 60)
    
    reporter = GSASReporter(building_id="TEST-BLDG-001", target_rating=GSASStarRating.FOUR_STAR)
    reporter.initialize_criteria()  # Initialize criteria
    reporter.set_criterion_score("E.1", 1.5)
    
    optimizer = GSASOptimizer(reporter, target_rating=GSASStarRating.FOUR_STAR)
    recommendations = await optimizer.generate_recommendations(max_recommendations=3)
    
    # Mark first recommendation as implemented
    if recommendations:
        rec_id = recommendations[0].recommendation_id
        optimizer.mark_implemented(rec_id)
        print(f"\n  Marked {rec_id} as implemented")
    
    status = optimizer.get_status()
    print(f"\n  Optimizer Status:")
    print(f"    Target rating: {status['target_rating']} stars")
    print(f"    Total recommendations: {status['total_recommendations']}")
    print(f"    Implemented: {status['implemented_count']}")
    print(f"    Estimated points from implementations: {status['estimated_points_implemented']:.2f}")
    
    assert status["implemented_count"] >= 1, "Should track implementations"
    
    print("\n✅ Implementation tracking works")
    
    return True


async def test_category_focus():
    """Test focusing on specific category."""
    print("\n" + "=" * 60)
    print("TEST 5: Category Focus")
    print("=" * 60)
    
    reporter = GSASReporter(building_id="TEST-BLDG-001", target_rating=GSASStarRating.FOUR_STAR)
    reporter.initialize_criteria()  # Initialize criteria
    reporter.set_criterion_score("E.1", 1.5)  # Energy gap
    reporter.set_criterion_score("IE.2", 1.0)  # IAQ gap
    reporter.set_criterion_score("W.1", 1.0)  # Water gap
    
    optimizer = GSASOptimizer(reporter, target_rating=GSASStarRating.FOUR_STAR)
    
    # Generate recommendations focused on Energy only
    energy_recs = await optimizer.generate_recommendations(
        max_recommendations=5,
        focus_category="E",
    )
    
    print(f"\n  Energy-focused recommendations: {len(energy_recs)}")
    for rec in energy_recs:
        print(f"    {rec.recommendation_id}: {rec.category} - {rec.title}")
        assert rec.category == "E", "All should be energy category"
    
    # Generate recommendations focused on Indoor Environment
    ie_recs = await optimizer.generate_recommendations(
        max_recommendations=5,
        focus_category="IE",
    )
    
    print(f"\n  Indoor Environment-focused recommendations: {len(ie_recs)}")
    for rec in ie_recs:
        print(f"    {rec.recommendation_id}: {rec.category} - {rec.title}")
        assert rec.category == "IE", "All should be IE category"
    
    print("\n✅ Category focus works correctly")
    
    return True


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("GSAS Optimizer Test Suite")
    print("=" * 60)
    
    tests = [
        ("Gap Analysis", test_gap_analysis),
        ("Recommendation Generation", test_recommendation_generation),
        ("Action Scoring", test_action_scoring),
        ("Implementation Tracking", test_implementation_tracking),
        ("Category Focus", test_category_focus),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, "PASS", None))
            print(f"\n✅ {name}: PASS")
        except AssertionError as e:
            results.append((name, "FAIL", str(e)))
            print(f"\n❌ {name}: FAIL - {e}")
        except Exception as e:
            results.append((name, "ERROR", str(e)))
            print(f"\n❌ {name}: ERROR - {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, status, _ in results if status == "PASS")
    total = len(results)
    print(f"  Passed: {passed}/{total}")
    
    for name, status, error in results:
        if status != "PASS":
            print(f"  ❌ {name}: {error}")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
