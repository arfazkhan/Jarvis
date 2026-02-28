"""
Multi-Option Advisor
=====================

The main Phase 2 integration point: combines all components
to generate, rank, and present multiple options to operators.

This is the agentic, ML-backed advisor system.

Components integrated:
- AgenticOptionGenerator (LLM reasoning)
- ScenarioRetriever (RAG)
- OutcomePredictor (XGBoost)
- PreferenceRankingModel (LightGBM)
- ContextualBandit (exploration)
- QatarFeatureEngineer (features)
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Phase 1 imports
from agent_advisory.recommendation_tracker import RecommendationTracker
from agent_advisory.preference_learner import PreferenceLearningEngine

# Phase 2 imports
from agent_advisory.agentic.option_generator import (
    AgenticOptionGenerator,
    GeneratedOption,
)
from agent_advisory.agentic.scenario_retriever import ScenarioRetriever
from agent_advisory.ml_models.outcome_predictor import (
    OutcomePredictor,
    OutcomePrediction,
)
from agent_advisory.ml_models.preference_ranker import (
    PreferenceRankingModel,
    RankedOption,
    ContextualBandit,
)
from agent_advisory.qatar.feature_engineer import QatarFeatureEngineer
from agent_advisory.qatar.context import (
    get_building_profile,
    get_kahramaa_rate,
    QATAR_BUILDINGS,
)

logger = logging.getLogger("arvis.advisory.multi_option")


@dataclass
class AdvisoryResponse:
    """Complete advisory response with ranked options"""
    issue_type: str
    equipment_id: str
    timestamp: datetime
    
    # Options (ranked by preference)
    options: List[RankedOption]
    
    # Top recommendation
    top_recommendation: RankedOption
    top_explanation: str
    
    # Metadata
    recommendation_id: str  # From Phase 1 tracker
    building_id: str
    operator_id: str
    
    # Confidence/calibration
    overall_confidence: float
    calibrated_confidence: float
    
    # Context summary
    context_summary: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "equipment_id": self.equipment_id,
            "timestamp": self.timestamp.isoformat(),
            "options": [o.to_dict() for o in self.options],
            "top_recommendation": self.top_recommendation.to_dict(),
            "top_explanation": self.top_explanation,
            "recommendation_id": self.recommendation_id,
            "building_id": self.building_id,
            "operator_id": self.operator_id,
            "confidence": round(self.overall_confidence, 3),
            "calibrated_confidence": round(self.calibrated_confidence, 3),
            "context_summary": self.context_summary,
        }
    
    def format_for_display(self) -> str:
        """Format as human-readable string"""
        lines = [
            f"## Advisory: {self.issue_type}",
            f"**Equipment:** {self.equipment_id}",
            f"**Confidence:** {self.calibrated_confidence:.0%}",
            "",
            "### 🎯 Top Recommendation",
            f"**{self.top_recommendation.option.get('action_description', 'N/A')}**",
            f"- Risk: {self.top_recommendation.option.get('risk_score', 'N/A')}/5",
            f"- Utility Score: {self.top_recommendation.predicted_utility:.2f}",
            f"{self.top_explanation}",
            "",
            "### 📋 All Options",
        ]
        
        for opt in self.options:
            action = opt.option.get('action_type', 'unknown')
            desc = opt.option.get('action_description', 'N/A')
            lines.append(f"{opt.rank}. **{action}** - {desc}")
            lines.append(f"   Preference: {opt.preference_score:.0%} | Utility: {opt.predicted_utility:.2f}")
        
        return "\n".join(lines)


class MultiOptionAdvisor:
    """
    Agentic multi-option advisory system.
    
    Generates, ranks, and presents multiple options for operational issues.
    Uses ML models and LLM reasoning - no hardcoded rules.
    
    Usage:
        advisor = MultiOptionAdvisor()
        response = await advisor.get_advice(
            context=current_context,
            issue_type="high_head_pressure",
            equipment_id="CH-01",
            operator_id="ahmed"
        )
    """
    
    def __init__(
        self,
        tracker: Optional[RecommendationTracker] = None,
        calibrator = None,
        preference_learner: Optional[PreferenceLearningEngine] = None,
        db_path: Optional[str] = None,
        model_path: Optional[str] = None,
        llm = None
    ):
        """
        Initialize multi-option advisor.
        
        Args:
            tracker: Phase 1 recommendation tracker
            calibrator: Phase 1 trust calibrator
            preference_learner: Phase 1 preference learner
            db_path: Path for databases
            model_path: Path for ML models
            llm: UnifiedLLM instance
        """
        # Phase 1 components
        self.tracker = tracker or RecommendationTracker(db_path=db_path)
        self.calibrator = calibrator
        self.preference_learner = preference_learner
        
        if self.preference_learner is None:
            self.preference_learner = PreferenceLearningEngine(db_path=db_path)
        
        # Phase 2: ML models
        # Use provided path or default to "models/advisory"
        effective_model_path = model_path or "models/advisory"
        self.outcome_predictor = OutcomePredictor(model_path=effective_model_path)
        self.ranking_model = PreferenceRankingModel(model_path=effective_model_path)
        self.bandit = ContextualBandit(exploration_rate=0.1)
        
        # Phase 2: Agentic components
        self.scenario_retriever = ScenarioRetriever()
        self.option_generator = AgenticOptionGenerator(
            llm=llm,
            scenario_retriever=self.scenario_retriever
        )
        
        # Feature engineering
        self.feature_engineer = QatarFeatureEngineer()
        
        # Default building
        self.default_building_id = "WBT-001"
        
        logger.info("MultiOptionAdvisor initialized with all Phase 2 components")
    
    async def get_advice(
        self,
        context: Dict[str, Any],
        issue_type: str,
        equipment_id: str,
        operator_id: str = "default",
        building_id: Optional[str] = None,
        num_options: int = 5,
        include_exploration: bool = True
    ) -> AdvisoryResponse:
        """
        Get multi-option advice for an operational issue.
        
        Args:
            context: Current operational context
            issue_type: Type of issue (e.g., "high_head_pressure")
            equipment_id: Equipment identifier
            operator_id: Operator to advise
            building_id: Building identifier (optional)
            num_options: Number of options to generate
            include_exploration: Whether to apply exploration
            
        Returns:
            AdvisoryResponse with ranked options
        """
        timestamp = datetime.now()
        building_id = building_id or self.default_building_id
        
        # Get building profile
        building_profile = get_building_profile(building_id)
        if building_profile:
            building_dict = building_profile.to_dict()
        else:
            building_dict = {"id": building_id}
        
        # ─────────────────────────────────────────────────────────────────
        # Step 1: Generate Options (Agentic LLM)
        # ─────────────────────────────────────────────────────────────────
        logger.info("Generating options for %s on %s", issue_type, equipment_id)
        
        generated_options = await self.option_generator.generate_options(
            context=context,
            issue_type=issue_type,
            equipment_id=equipment_id,
            building_profile=building_dict,
            num_options=num_options
        )
        
        # Convert to dict format for ranking
        options_as_dicts = [opt.to_dict() for opt in generated_options]
        
        # ─────────────────────────────────────────────────────────────────
        # Step 2: Rank by Preference (ML)
        # ─────────────────────────────────────────────────────────────────
        logger.info("Ranking options for operator %s", operator_id)
        
        ranked_options = self.ranking_model.rank_options(
            options=options_as_dicts,
            context=context,
            operator_id=operator_id,
            outcome_predictor=self.outcome_predictor
        )
        
        # ─────────────────────────────────────────────────────────────────
        # Step 3: Apply Exploration (Contextual Bandit)
        # ─────────────────────────────────────────────────────────────────
        if include_exploration:
            ranked_options = self.bandit.reorder_for_exploration(ranked_options)
        
        # ─────────────────────────────────────────────────────────────────
        # Step 4: Calculate Confidence
        # ─────────────────────────────────────────────────────────────────
        top_option = ranked_options[0] if ranked_options else None
        
        overall_confidence = 0.7  # Default
        if top_option:
            overall_confidence = top_option.preference_score * 0.5 + top_option.confidence * 0.5
        
        # Calibrate confidence using Phase 1
        calibrated_confidence = overall_confidence
        if self.calibrator:
            calibrated_confidence = self.calibrator.calibrate_confidence(overall_confidence)
        
        # ─────────────────────────────────────────────────────────────────
        # Step 5: Log to Phase 1 Tracker
        # ─────────────────────────────────────────────────────────────────
        recommendation_id = await self.tracker.log_recommendation(
            context=context,
            recommended_action=top_option.option if top_option else {},
            confidence=overall_confidence,
            calibrated_confidence=calibrated_confidence,
            reasoning=top_option.explanation if top_option else "",
            trigger_type=issue_type,
            building_id=building_id,
            equipment_ids=[equipment_id],
            tags=["phase2", "multi_option"],
        )
        
        # Add scenario to retriever for future RAG
        if top_option:
            self.scenario_retriever.add_scenario(
                scenario_id=recommendation_id,
                context=context,
                issue_type=issue_type,
                operator_action=top_option.option.get("action_type", "unknown"),
                outcome_quality="pending",  # Will be updated later
            )
        
        # ─────────────────────────────────────────────────────────────────
        # Step 6: Build Response
        # ─────────────────────────────────────────────────────────────────
        context_summary = self._build_context_summary(context, issue_type)
        top_explanation = self._generate_top_explanation(
            top_option, context, issue_type
        ) if top_option else ""
        
        response = AdvisoryResponse(
            issue_type=issue_type,
            equipment_id=equipment_id,
            timestamp=timestamp,
            options=ranked_options,
            top_recommendation=top_option or RankedOption(
                option={}, rank=0, preference_score=0
            ),
            top_explanation=top_explanation,
            recommendation_id=recommendation_id,
            building_id=building_id,
            operator_id=operator_id,
            overall_confidence=overall_confidence,
            calibrated_confidence=calibrated_confidence,
            context_summary=context_summary,
        )
        
        logger.info(
            "Advisory generated: %s options, top=%s, confidence=%.2f",
            len(ranked_options),
            top_option.option.get("action_type") if top_option else "none",
            calibrated_confidence
        )
        
        return response
    
    async def record_decision(
        self,
        recommendation_id: str,
        chosen_option_index: int,
        operator_id: str,
        options: Optional[List[Dict]] = None
    ):
        """
        Record operator's decision for learning.
        
        Args:
            recommendation_id: From the advisory response
            chosen_option_index: Which option was chosen (0-based)
            operator_id: Who chose
            options: Original options list
        """
        # Get the recommendation from tracker
        rec = await self.tracker.get_recommendation(recommendation_id)
        
        if rec and options:
            chosen_option = options[chosen_option_index] if chosen_option_index < len(options) else None
            
            if chosen_option:
                # Log to Phase 1 tracker
                await self.tracker.log_operator_decision(
                    recommendation_id=recommendation_id,
                    operator_choice=chosen_option,
                    operator_id=operator_id
                )
                
                # Update ranking model
                self.ranking_model.learn_from_decision(
                    options=options,
                    chosen_index=chosen_option_index,
                    context=rec.context,
                    operator_id=operator_id
                )
                
                # Log to Phase 1 preference learner
                await self.preference_learner.record_decision(
                    context=rec.context,
                    agent_recommendation=rec.recommended_action,
                    operator_choice=chosen_option,
                    operator_id=operator_id
                )
                
                logger.info(
                    "Recorded decision: rec=%s, choice=%d (%s)",
                    recommendation_id, chosen_option_index,
                    chosen_option.get("action_type", "unknown")
                )
    
    async def record_outcome(
        self,
        recommendation_id: str,
        actual_outcome: Dict[str, Any],
        outcome_quality: str = "good"
    ):
        """
        Record the actual outcome for learning.
        
        Args:
            recommendation_id: From the advisory response
            actual_outcome: What actually happened
            outcome_quality: "excellent", "good", "acceptable", or "poor"
        """
        from agent_advisory.schemas import OutcomeQuality
        
        quality_map = {
            "excellent": OutcomeQuality.EXCELLENT,
            "good": OutcomeQuality.GOOD,
            "acceptable": OutcomeQuality.ACCEPTABLE,
            "poor": OutcomeQuality.POOR,
        }
        
        quality = quality_map.get(outcome_quality, OutcomeQuality.UNKNOWN)
        
        # Log to Phase 1 tracker
        await self.tracker.log_outcome(
            recommendation_id=recommendation_id,
            actual_outcome=actual_outcome,
            outcome_quality=quality
        )
        
        # Get recommendation to update bandit
        rec = await self.tracker.get_recommendation(recommendation_id)
        if rec and rec.recommended_action:
            action_type = rec.recommended_action.get("action_type", "unknown")
            was_successful = outcome_quality in ["excellent", "good"]
            self.bandit.update_belief(action_type, was_successful)
        
        # Update outcome predictor (in production, would batch retrain)
        # For now, just log
        logger.info(
            "Recorded outcome: rec=%s, quality=%s",
            recommendation_id, outcome_quality
        )
    
    def _build_context_summary(
        self,
        context: Dict[str, Any],
        issue_type: str
    ) -> str:
        """Build human-readable context summary"""
        parts = [f"Issue: {issue_type}"]
        
        if "outdoor_temp_c" in context:
            parts.append(f"Outdoor: {context['outdoor_temp_c']}°C")
        
        if "cooling_load_pct" in context:
            parts.append(f"Cooling Load: {context['cooling_load_pct']}%")
        
        if "zone_temp_avg_c" in context:
            parts.append(f"Zone Temp: {context['zone_temp_avg_c']}°C")
        
        return " | ".join(parts)
    
    def _generate_top_explanation(
        self,
        top_option: RankedOption,
        context: Dict[str, Any],
        issue_type: str
    ) -> str:
        """Generate explanation for top recommendation"""
        action = top_option.option.get("action_type", "unknown")
        mechanism = top_option.option.get("mechanism", "")
        outcome = top_option.predicted_outcome or "good"
        confidence = top_option.confidence
        
        parts = [
            f"Recommended action: **{action}**.",
        ]
        
        if mechanism:
            parts.append(f"This works by {mechanism[:100]}...")
        
        parts.append(
            f"Predicted outcome: {outcome} (confidence: {confidence:.0%})."
        )
        
        # Add Qatar context if relevant
        outdoor_temp = context.get("outdoor_temp_c", 35)
        if outdoor_temp > 42:
            parts.append(
                "Note: Extreme heat conditions - prioritizing equipment protection."
            )
        
        return " ".join(parts)


# Convenience function
async def get_multi_option_advice(
    context: Dict[str, Any],
    issue_type: str,
    equipment_id: str,
    operator_id: str = "default",
    **kwargs
) -> AdvisoryResponse:
    """
    Convenience function to get multi-option advice.
    
    Creates a temporary advisor instance.
    For production, reuse a single MultiOptionAdvisor instance.
    """
    advisor = MultiOptionAdvisor()
    return await advisor.get_advice(
        context=context,
        issue_type=issue_type,
        equipment_id=equipment_id,
        operator_id=operator_id,
        **kwargs
    )
