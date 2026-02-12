"""
Verification for Phase 2.5: Utility Score Refactor
==================================================

Directly tests the ML models to ensure they:
1. Load correctly
2. Predict continuous utility scores (0.0-1.0) instead of classes
3. Rank options based on this utility score
"""

import sys
import logging
from pathlib import Path
import numpy as np

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_advisory.ml_models.outcome_predictor import OutcomePredictor
from agent_advisory.ml_models.preference_ranker import PreferenceRankingModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis.test.models")

def verify_models():
    # 1. Initialize OutcomePredictor
    logger.info("Initializing OutcomePredictor...")
    predictor = OutcomePredictor(model_path="models/advisory")
    
    if not predictor.is_trained:
        logger.warning("OutcomePredictor is not trained! Loading fallback/untrained.")
    
    # Mock Data
    context = {
        "outdoor_temp_c": 35.0,
        "cooling_load_pct": 80.0,
        "equipment_age_years": 5,
        "timestamp": "2024-06-15T14:00:00"
    }
    
    action = {
        "action_type": "reduce_load",
        "description": "Reduce load by 15%",
        "risk_score": 2,
        "estimated_cost_qar": 100
    }
    
    # 2. Test Prediction (Regression)
    logger.info("Testing Outcome Prediction...")
    prediction = predictor.predict(context, action)
    
    logger.info(f"Predicted Utility: {prediction.predicted_utility}")
    logger.info(f"Confidence: {prediction.confidence}")
    logger.info(f"Quality Label (Legacy): {prediction.predicted_quality}")
    
    if isinstance(prediction.predicted_utility, float):
        logger.info("✅ OutcomePredictor returns float utility score")
    else:
        logger.error(f"❌ OutcomePredictor returned {type(prediction.predicted_utility)}")
        
    if 0.0 <= prediction.predicted_utility <= 1.0:
        logger.info("✅ Utility score is properly bounded (0.0 - 1.0)")
    else:
        logger.error(f"❌ Utility score out of bounds: {prediction.predicted_utility}")

    # 3. Initialize Ranker
    logger.info("Initializing PreferenceRanker...")
    ranker = PreferenceRankingModel(model_path="models/advisory")
    
    options = [
        {"action_type": "reduce_load", "risk_score": 2},
        {"action_type": "shutdown", "risk_score": 5},
        {"action_type": "do_nothing", "risk_score": 3}
    ]
    
    # 4. Test Ranking
    logger.info("Testing Ranking...")
    ranked = ranker.rank_options(
        options=options,
        context=context,
        outcome_predictor=predictor
    )
    
    logger.info(f"Ranked {len(ranked)} options.")
    for r in ranked:
        logger.info(f"Rank {r.rank}: {r.option['action_type']} | Pref: {r.preference_score:.2f} | Util: {r.predicted_utility:.2f}")
        
    # Verify utility data passed through
    if hasattr(ranked[0], "predicted_utility") and isinstance(ranked[0].predicted_utility, float):
        logger.info("✅ Ranker correctly utilizes/passes utility score")
    else:
        logger.error("❌ Ranker missing utility score in output")

if __name__ == "__main__":
    verify_models()
