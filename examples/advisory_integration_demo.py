"""
Advisory System Integration Example
====================================

Demonstrates how to integrate Phase 1 advisory components with existing BMS agent.

This shows:
1. How to log recommendations when ARVIS makes them
2. How to track operator decisions
3. How to use calibrated confidence scores
4. How to rank options by operator preference
"""

import asyncio
import logging
from typing import Dict, Any

from agent_advisory.recommendation_tracker import RecommendationTracker
from agent_advisory.trust_calibrator import TrustCalibrator
from agent_advisory.preference_learner import PreferenceLearningEngine
from agent_advisory.schemas import OutcomeQuality

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AdvisoryIntegrationExample:
    """Example integration of advisory system with BMS"""
    
    def __init__(self):
        """Initialize advisory components"""
        # Phase 1 components
        self.tracker = RecommendationTracker()
        self.calibrator = TrustCalibrator(self.tracker)
        self.preference_learner = PreferenceLearningEngine()
        
        logger.info("Advisory system initialized")
    
    async def handle_alarm_with_advisory(
        self,
        alarm_context: Dict[str, Any],
        operator_id: str = "demo_operator"
    ):
        """
        Example: Handle an alarm with advisory system integration.
        
        This demonstrates the full flow:
        1. Generate recommendation
        2. Calibrate confidence
        3. Rank options by preference
        4. Track recommendation
        5. Simulate operator decision
        6. Learn from decision
        """
        
        logger.info(f"\n{'='*60}")
        logger.info("ALARM DETECTED")
        logger.info(f"{'='*60}")
        logger.info(f"Context: {alarm_context}")
        
        # Step 1: Generate recommendation (normally from LLM)
        # For demo, we'll create a simple recommendation
        recommended_action = {
            "action": "shutdown",
            "equipment": alarm_context.get("equipment_id"),
            "reason": "High head pressure detected"
        }
        
        raw_confidence = 0.85  # From ML model
        reasoning = (
            "High head pressure (165 psi) detected on chiller. "
            "Condenser water flow is normal. "
            "Likely compressor issue requiring immediate shutdown."
        )
        
        predicted_outcome = {
            "equipment_damage_avoided": 0.9,
            "downtime_hours": 2.0,
            "energy_savings_kwh": 0
        }
        
        # Step 2: Calibrate confidence
        calibrated_confidence = self.calibrator.calibrate_confidence(raw_confidence)
        
        logger.info(f"\n📊 CONFIDENCE CALIBRATION")
        logger.info(f"Raw confidence: {raw_confidence:.1%}")
        logger.info(f"Calibrated confidence: {calibrated_confidence:.1%}")
        
        # Get explanation
        conf_explanation = self.calibrator.get_confidence_explanation(raw_confidence)
        logger.info(f"Calibration explanation: {conf_explanation['explanation']}")
        
        # Step 3: Generate alternative options
        alternative_options = [
            {"action": "shutdown", "equipment": alarm_context["equipment_id"]},
            {"action": "reduce_load", "equipment": alarm_context["equipment_id"], "target": 0.7},
            {"action": "investigate", "equipment": alarm_context["equipment_id"], "duration_minutes": 30}
        ]
        
        # Rank by operator preference
        ranked_options = self.preference_learner.rank_options_by_preference(
            context=alarm_context,
            options=alternative_options,
            operator_id=operator_id
        )
        
        logger.info(f"\n🎯 OPTIONS RANKED BY PREFERENCE ({operator_id}):")
        for i, (option, score) in enumerate(ranked_options, 1):
            logger.info(f"  {i}. {option['action']}: {score:.1%} preference")
        
        # Step 4: Log recommendation
        rec_id = self.tracker.log_recommendation(
            context=alarm_context,
            recommended_action=recommended_action,
            confidence=raw_confidence,
            calibrated_confidence=calibrated_confidence,
            reasoning=reasoning,
            predicted_outcome=predicted_outcome,
            trigger_type="alarm"
        )
        
        logger.info(f"\n✅ Recommendation logged: {rec_id}")
        
        # Step 5: Simulate operator decision
        # In real system, this would come from actual operator action
        await asyncio.sleep(0.5)  # Simulate thinking time
        
        # For demo, operator chooses second-ranked option
        operator_choice = ranked_options[1][0]
        
        logger.info(f"\n👤 OPERATOR DECISION")
        logger.info(f"Operator chose: {operator_choice['action']}")
        logger.info(f"ARVIS recommended: {recommended_action['action']}")
        
        self.tracker.log_operator_decision(
            recommendation_id=rec_id,
            operator_choice=operator_choice,
            operator_id=operator_id
        )
        
        # Step 6: Learn preference
        self.preference_learner.record_decision(
            context=alarm_context,
            agent_recommendation=recommended_action,
            operator_choice=operator_choice,
            operator_id=operator_id
        )
        
        logger.info("✅ Preference learned from override")
        
        # Step 7: Simulate outcome verification (after some time)
        await asyncio.sleep(0.5)  # Simulate waiting for outcome
        
        actual_outcome = {
            "issue_resolved": True,
            "downtime_hours": 0.5,  # Less downtime than predicted
            "equipment_damage_avoided": 1.0
        }
        
        # Operator's choice was better than predicted
        outcome_quality = OutcomeQuality.EXCELLENT
        
        self.tracker.log_outcome(
            recommendation_id=rec_id,
            actual_outcome=actual_outcome,
            outcome_quality=outcome_quality
        )
        
        logger.info(f"\n📈 OUTCOME VERIFIED")
        logger.info(f"Quality: {outcome_quality.value}")
        logger.info(f"Result: {actual_outcome}")
        
        # Show updated metrics
        metrics = self.tracker.calculate_trust_metrics(window_days=1)
        logger.info(f"\n📊 UPDATED TRUST METRICS")
        logger.info(f"Total recommendations: {metrics.total_recommendations}")
        logger.info(f"Adoption rate: {metrics.adoption_rate:.1%}")
        logger.info(f"Accuracy when followed: {metrics.accuracy_when_followed:.1%}")
        logger.info(f"Calibration error: {metrics.calibration_error:.2f}")
        
        # Show operator preferences
        pref_summary = self.preference_learner.get_operator_preferences_summary(operator_id)
        logger.info(f"\n👤 OPERATOR PREFERENCES ({operator_id})")
        logger.info(f"Total decisions: {pref_summary['total_decisions']}")
        logger.info(f"Override rate: {pref_summary['override_rate']:.1%}")
        if pref_summary.get('insights'):
            logger.info("Insights:")
            for insight in pref_summary['insights']:
                logger.info(f"  - {insight}")


async def main():
    """Run demo"""
    
    demo = AdvisoryIntegrationExample()
    
    # Simulate 3 alarms to build up data
    alarm_contexts = [
        {
            "alarm_type": "high_head_pressure",
            "equipment_id": "CH-01",
            "severity": "critical",
            "value": 165,
            "threshold": 150
        },
        {
            "alarm_type": "high_head_pressure",
            "equipment_id": "CH-02",
            "severity": "warning",
            "value": 155,
            "threshold": 150
        },
        {
            "alarm_type": "high_head_pressure",
            "equipment_id": "CH-01",
            "severity": "critical",
            "value": 170,
            "threshold": 150
        }
    ]
    
    for i, alarm in enumerate(alarm_contexts, 1):
        logger.info(f"\n\n{'#'*60}")
        logger.info(f"SCENARIO {i}/3")
        logger.info(f"{'#'*60}")
        
        await demo.handle_alarm_with_advisory(alarm)
        
        await asyncio.sleep(1)  # Pause between scenarios
    
    logger.info(f"\n\n{'='*60}")
    logger.info("DEMO COMPLETE")
    logger.info(f"{'='*60}")
    logger.info("\nPhase 1 components demonstrated:")
    logger.info("✅ Recommendation tracking")
    logger.info("✅ Trust calibration")
    logger.info("✅ Preference learning")
    logger.info("\nNext steps: Integrate with actual BMS LLM agent")


if __name__ == "__main__":
    asyncio.run(main())
