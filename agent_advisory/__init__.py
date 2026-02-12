"""
ARVIS Advisory System
=====================

Advisory-first agentic AI components for ARVIS.

This module provides:
- **Phase 1:** Recommendation tracking and trust calibration
- **Phase 2:** Multi-option analysis with ML-backed ranking

Phase 1: Foundation Layer (Self-Monitoring & Trust)
Phase 2: Multi-Option Analysis (Agentic ML-Backed Advisor)
"""

# Phase 1: Foundation
from agent_advisory.recommendation_tracker import RecommendationTracker
from agent_advisory.trust_calibrator import TrustCalibrator
from agent_advisory.preference_learner import PreferenceLearningEngine

# Phase 2: Multi-Option Analysis
from agent_advisory.multi_option_advisor import (
    MultiOptionAdvisor,
    AdvisoryResponse,
    get_multi_option_advice,
)

# Phase 2: ML Models
from agent_advisory.ml_models import (
    OutcomePredictor,
    OutcomePrediction,
    PreferenceRankingModel,
    RankedOption,
    ContextualBandit,
)

# Phase 2: Agentic Components
from agent_advisory.agentic import (
    AgenticOptionGenerator,
    GeneratedOption,
    ScenarioRetriever,
)

# Phase 2: Qatar Context
from agent_advisory.qatar import (
    QatarFeatureEngineer,
    QatarBuildingSimulator,
    QATAR_BUILDINGS,
    OPERATOR_PERSONAS,
)

__all__ = [
    # Phase 1
    "RecommendationTracker",
    "TrustCalibrator", 
    "PreferenceLearningEngine",
    
    # Phase 2: Main Advisor
    "MultiOptionAdvisor",
    "AdvisoryResponse",
    "get_multi_option_advice",
    
    # Phase 2: ML Models
    "OutcomePredictor",
    "OutcomePrediction",
    "PreferenceRankingModel",
    "RankedOption",
    "ContextualBandit",
    
    # Phase 2: Agentic
    "AgenticOptionGenerator",
    "GeneratedOption",
    "ScenarioRetriever",
    
    # Phase 2: Qatar
    "QatarFeatureEngineer",
    "QatarBuildingSimulator",
    "QATAR_BUILDINGS",
    "OPERATOR_PERSONAS",
]

