"""
Outcome Prediction Model
=========================

XGBoost-based model to predict outcome quality BEFORE action is taken.
This is ML-backed prediction, not rule-based.

The model learns from:
- Historical context features
- Action features  
- Actual outcomes

Features are extracted by QatarFeatureEngineer.
"""

import numpy as np
import pickle
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("arvis.advisory.ml.outcome")

# Lazy import to handle missing dependencies
xgb = None


def _ensure_xgboost():
    """Lazy import XGBoost"""
    global xgb
    if xgb is None:
        try:
            import xgboost as xgboost_module
            xgb = xgboost_module
        except ImportError:
            logger.warning("XGBoost not installed. Using fallback predictor.")
            return False
    return True


@dataclass
class OutcomePrediction:
    """Predicted outcome for an action"""
    predicted_utility: float  # Continuous score 0.0-1.0
    confidence: float
    # Legacy support (mapped from utility)
    predicted_quality: str 
    feature_importances: Dict[str, float]
    explanation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_utility": round(self.predicted_utility, 3),
            "predicted_quality": self.predicted_quality,
            "confidence": round(self.confidence, 3),
            "top_factors": dict(list(self.feature_importances.items())[:5]),
            "explanation": self.explanation,
        }


class OutcomePredictor:
    """
    ML model to predict action outcomes.
    
    Uses XGBoost with calibrated probabilities to predict:
    - outcome quality (excellent/good/acceptable/poor)
    - confidence in prediction
    
    The model is trained on historical data:
    - Context features (50 from QatarFeatureEngineer)
    - Action features (12 from ActionFeatureEngineer)
    - Outcome labels
    """
    
    QUALITY_LABELS = ["poor", "acceptable", "good", "excellent"]
    QUALITY_TO_INT = {"poor": 0, "acceptable": 1, "good": 2, "excellent": 3}
    INT_TO_QUALITY = {0: "poor", 1: "acceptable", 2: "good", 3: "excellent"}
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize outcome predictor.
        
        Args:
            model_path: Path to saved model file or directory (optional)
        """
        self.model = None
        self.feature_names: List[str] = []
        self.is_trained = False
        self.model_path = model_path
        
        # Import feature engineers
        from agent_advisory.qatar.feature_engineer import (
            QatarFeatureEngineer, ActionFeatureEngineer
        )
        self.context_fe = QatarFeatureEngineer()
        self.action_fe = ActionFeatureEngineer()
        
        # Load model if path is a file
        model_file = self._resolve_model_path(model_path)
        if model_file and model_file.exists() and model_file.is_file():
            self.load(str(model_file))
        else:
            self._init_model()
        
        logger.info("OutcomePredictor initialized (trained=%s)", self.is_trained)
    
    def _resolve_model_path(self, path: Optional[str]) -> Optional[Path]:
        """Resolve model path - handles both file and directory"""
        if not path:
            return None
        p = Path(path)
        if p.is_file():
            return p
        if p.is_dir():
            # Look for model file in directory
            model_file = p / "outcome_predictor.pkl"
            return model_file
        return p
    
    def _init_model(self):
        """Initialize appropriate model architecture"""
        if not _ensure_xgboost():
            return
            
        from xgboost import XGBRegressor
        
        # Initialize Regressor instead of Classifier
        self.model = XGBRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5,
            objective='reg:squarederror',
            n_jobs=-1,
            random_state=42
        )
        
        # Feature names
        self.feature_names = (
            self.context_fe.get_feature_names() +
            self.action_fe.ACTION_FEATURE_NAMES
        )
    
    def predict(
        self,
        context: Dict[str, Any],
        action: Dict[str, Any]
    ) -> OutcomePrediction:
        """
        Predict outcome for a context-action pair.
        
        Args:
            context: Current operational context
            action: Proposed action
            
        Returns:
            OutcomePrediction with quality, confidence, and explanation
        """
        # Extract features
        context_features = self.context_fe.extract_features(context)
        action_features = self.action_fe.extract_features(action)
        features = np.concatenate([context_features, action_features])
        
        if self.model is None or not self.is_trained:
            # Fallback: heuristic-based prediction
            return self._heuristic_predict(context, action, features)
        
        # Predict utility score
        X = features.reshape(1, -1)
        utility_score = float(self.model.predict(X)[0])
        utility_score = max(0.0, min(1.0, utility_score))  # Clip to 0-1
        
        # Map utility to quality label for backward compatibility
        quality = "poor"
        if utility_score > 0.8:
            quality = "excellent"
        elif utility_score > 0.6:
            quality = "good"
        elif utility_score > 0.4:
            quality = "acceptable"
            
        # Feature importances
        importances = self._get_feature_importances(features)
        
        # Generate explanation
        explanation = self._generate_explanation(
            quality, utility_score, importances, context, action
        )
        
        return OutcomePrediction(
            predicted_utility=utility_score,
            confidence=utility_score, # For regression, score proxy for confidence
            predicted_quality=quality,
            feature_importances=importances,
            explanation=explanation,
        )
    
    def predict_batch(
        self,
        contexts: List[Dict[str, Any]],
        actions: List[Dict[str, Any]]
    ) -> List[OutcomePrediction]:
        """Predict outcomes for multiple context-action pairs"""
        return [
            self.predict(ctx, act)
            for ctx, act in zip(contexts, actions)
        ]
    
    def train(
        self,
        contexts: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
        utilities: List[float],
        validation_split: float = 0.2
    ):
        """
        Train the outcome predictor on historical data (Regression).
        
        Args:
            contexts: List of context dictionaries
            actions: List of action dictionaries
            utilities: List of operational utility scores (0.0-1.0)
        """
        if not _ensure_xgboost():
            logger.warning("Cannot train without XGBoost")
            return
        
        # Extract features
        X = []
        for ctx, act in zip(contexts, actions):
            ctx_feat = self.context_fe.extract_features(ctx)
            act_feat = self.action_fe.extract_features(act)
            X.append(np.concatenate([ctx_feat, act_feat]))
        X = np.array(X)
        
        # Target is utility score
        y = np.array(utilities)
        
        # Train/validation split
        n_val = int(len(X) * validation_split)
        if n_val > 0:
            indices = np.random.permutation(len(X))
            train_idx, val_idx = indices[n_val:], indices[:n_val]
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]
            
            # Re-init model to clear previous state
            self._init_model()
            
            self.model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False
            )
        else:
            self._init_model()
            self.model.fit(X, y)
            
        self.is_trained = True
        logger.info("OutcomePredictor trained on %d samples", len(X))
        
        # Cache feature names for explanation
        if len(X) > 0:
            self.feature_names = (
                self.context_fe.get_feature_names() +
                self.action_fe.get_feature_names()
            )
    
    def update(
        self,
        context: Dict[str, Any],
        action: Dict[str, Any],
        actual_outcome: str
    ):
        """
        Update model with a single new observation.
        
        For online learning, we accumulate samples and periodically retrain.
        """
        # In production, would use incremental learning or sample buffer
        # For now, just log
        logger.debug(
            "New outcome data: %s -> %s",
            action.get("action_type", "unknown"),
            actual_outcome
        )
    
    def save(self, path: Optional[str] = None) -> Optional[str]:
        """Save model to disk"""
        if self.model is None:
            logger.warning("No model to save")
            return None

        try:
            from agent_commercial.ml.model_registry import get_model_registry
            registry = get_model_registry()
            version = registry.save_model(
                name="outcome_predictor",
                model=self.model,
                metrics={"is_trained": self.is_trained, "n_features": len(self.feature_names)},
                extra_artifacts={"feature_names": self.feature_names},
            )
            logger.info("OutcomePredictor saved via ModelRegistry: %s", version)
            return version
        except Exception as e:
            logger.warning("ModelRegistry save failed, falling back to pickle: %s", e)

        # Pickle fallback
        if path is None:
            path = self.model_path
        if path is None:
            path = "outcome_predictor.pkl"

        p = Path(path)
        if p.is_dir() or (not p.exists() and not p.suffix):
            p.mkdir(parents=True, exist_ok=True)
            p = p / "outcome_predictor.pkl"

        data = {
            "model": self.model,
            "feature_names": self.feature_names,
            "is_trained": self.is_trained,
        }
        with open(p, 'wb') as f:
            pickle.dump(data, f)
        logger.info("OutcomePredictor saved to %s", p)
        return str(p)

    def load(self, path: Optional[str] = None) -> bool:
        """Load model from disk"""
        try:
            from agent_commercial.ml.model_registry import get_model_registry
            registry = get_model_registry()
            model, metadata = registry.load_model("outcome_predictor")
            if model is not None:
                self.model = model
                self.is_trained = metadata.get("metrics", {}).get("is_trained", True)
                feature_names_artifact = registry.load_artifact("outcome_predictor", "feature_names")
                if feature_names_artifact is not None:
                    self.feature_names = feature_names_artifact
                logger.info("OutcomePredictor loaded via ModelRegistry")
                return True
        except Exception as e:
            logger.debug("ModelRegistry load failed, trying pickle fallback: %s", e)

        # Pickle fallback
        if path is None:
            return False
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.feature_names = data["feature_names"]
        self.is_trained = data.get("is_trained", True)
        logger.info("OutcomePredictor loaded from %s", path)
        return True
    
    def _heuristic_predict(
        self,
        context: Dict[str, Any],
        action: Dict[str, Any],
        features: np.ndarray
    ) -> OutcomePrediction:
        """Fallback heuristic prediction when model not trained"""
        # Simple heuristics based on action risk and context
        risk = action.get("risk_score", 3)
        equipment_reliability = context.get("reliability_score", 0.8)
        
        # Base probability adjusted by risk and reliability
        if risk <= 2 and equipment_reliability > 0.7:
            probs = [0.05, 0.15, 0.40, 0.40]  # Likely good/excellent
        elif risk >= 4:
            probs = [0.30, 0.35, 0.25, 0.10]  # Risky, might be poor
        else:
            probs = [0.10, 0.30, 0.40, 0.20]  # Average
        
        best_idx = np.argmax(probs)
        predicted_quality = self.INT_TO_QUALITY[best_idx]
        
        return OutcomePrediction(
            predicted_quality=predicted_quality,
            confidence=probs[best_idx],
            quality_probabilities={
                self.INT_TO_QUALITY[i]: probs[i] for i in range(4)
            },
            feature_importances={"risk_score": 0.5, "reliability_score": 0.3},
            explanation=f"Predicted {predicted_quality} outcome based on risk level and equipment reliability. (Heuristic mode - train model for better predictions)",
        )
    
    def _get_feature_importances(self, features: np.ndarray) -> Dict[str, float]:
        """Get feature importances for this prediction"""
        if self.model is None:
            return {}
        
        try:
            importances = self.model.feature_importances_
            # Get top 10 important features
            top_indices = np.argsort(importances)[-10:][::-1]
            
            return {
                self.feature_names[i]: float(importances[i])
                for i in top_indices
                if importances[i] > 0.01
            }
        except Exception:
            return {}
    
    def _generate_explanation(
        self,
        quality: str,
        confidence: float,
        importances: Dict[str, float],
        context: Dict[str, Any],
        action: Dict[str, Any]
    ) -> str:
        """Generate human-readable explanation"""
        parts = []
        
        # Quality assessment
        if quality in ["excellent", "good"]:
            parts.append(f"This action is predicted to have a {quality} outcome")
        else:
            parts.append(f"Caution: This action may result in {quality} outcome")
        
        # Confidence
        if confidence > 0.8:
            parts.append(f"with high confidence ({confidence:.0%})")
        elif confidence > 0.6:
            parts.append(f"with moderate confidence ({confidence:.0%})")
        else:
            parts.append(f"with low confidence ({confidence:.0%})")
        
        # Top factors
        if importances:
            top_factors = list(importances.keys())[:3]
            parts.append(f". Key factors: {', '.join(top_factors)}")
        
        return " ".join(parts) + "."
