"""
Preference Ranking Model
=========================

LightGBM-based learning-to-rank model for option ranking.
Learns operator preferences from historical decisions.

This is NOT rule-based - the model learns patterns:
- Which option types operators prefer
- How preferences vary by context
- Individual operator biases
"""

import numpy as np
import pickle
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger("arvis.advisory.ml.ranking")

# Lazy import
lgb = None


def _ensure_lightgbm():
    """Lazy import LightGBM"""
    global lgb
    if lgb is None:
        try:
            import lightgbm as lightgbm_module
            lgb = lightgbm_module
        except ImportError:
            logger.warning("LightGBM not installed. Using fallback ranker.")
            return False
    return True


@dataclass
class RankedOption:
    """An option with its ranking score"""
    option: Dict[str, Any]
    rank: int
    preference_score: float  # 0-1, higher is more preferred
    preference_score: float  # 0-1, higher is more preferred
    predicted_utility: float = 0.0
    predicted_outcome: str = "unknown" # Legacy
    confidence: float = 0.0
    explanation: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "option": self.option,
            "preference_score": round(self.preference_score, 3),
            "preference_score": round(self.preference_score, 3),
            "predicted_utility": round(self.predicted_utility, 3),
            "predicted_outcome": self.predicted_outcome,
            "confidence": round(self.confidence, 3),
            "explanation": self.explanation,
        }


class PreferenceRankingModel:
    """
    Learn-to-rank model for operator preferences.
    
    Uses LightGBM LambdaMART to learn:
    - Which options operators tend to choose
    - How preferences vary by context (time, urgency, equipment)
    - Individual operator biases
    
    The model is trained on (context, options, chosen_index) tuples.
    """
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize preference ranker.
        
        Args:
            model_path: Path to saved model file or directory (optional)
        """
        self.model = None
        self.is_trained = False
        self.model_path = model_path
        
        # Training examples buffer
        self.training_examples: List[Dict] = []
        
        # Per-operator preference history (for cold start)
        self.operator_history: Dict[str, List[Dict]] = defaultdict(list)
        
        # Feature engineers
        from agent_advisory.qatar.feature_engineer import (
            QatarFeatureEngineer, ActionFeatureEngineer
        )
        self.context_fe = QatarFeatureEngineer()
        self.action_fe = ActionFeatureEngineer()
        
        # Load or initialize
        model_file = self._resolve_model_path(model_path)
        if model_file and model_file.exists() and model_file.is_file():
            self.load(str(model_file))
        else:
            self._init_model()
        
        logger.info("PreferenceRankingModel initialized (trained=%s)", self.is_trained)
    
    def _resolve_model_path(self, path: Optional[str]) -> Optional[Path]:
        """Resolve model path - handles both file and directory"""
        if not path:
            return None
        p = Path(path)
        if p.is_file():
            return p
        if p.is_dir():
            model_file = p / "preference_ranker.pkl"
            return model_file
        return p
    
    def _init_model(self):
        """Initialize LightGBM ranker"""
        if not _ensure_lightgbm():
            self.model = None
            return
        
        self.model = lgb.LGBMRanker(
            objective='lambdarank',
            metric='ndcg',
            n_estimators=100,
            num_leaves=31,
            learning_rate=0.1,
            min_child_samples=10,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
        )
    
    def rank_options(
        self,
        options: List[Dict[str, Any]],
        context: Dict[str, Any],
        operator_id: str = "default",
        outcome_predictor = None
    ) -> List[RankedOption]:
        """
        Rank options by predicted operator preference.
        
        Args:
            options: List of option dictionaries
            context: Current operational context
            operator_id: Operator to rank for
            outcome_predictor: Optional OutcomePredictor for outcome predictions
            
        Returns:
            List of RankedOptions, sorted by preference (best first)
        """
        if not options:
            return []
        
        # Extract context features
        context_features = self.context_fe.extract_features(context)
        
        # Score each option
        scored_options = []
        
        for option in options:
            # Extract action features
            action_features = self.action_fe.extract_features(option)
            
            # Combine features
            features = np.concatenate([context_features, action_features])
            
            # Get preference score
            if self.model is not None and self.is_trained:
                score = float(self.model.predict(features.reshape(1, -1))[0])
            else:
                # Fallback: use operator persona or heuristics
                score = self._heuristic_score(option, context, operator_id)
            
            # Get outcome prediction if available
            predicted_outcome = "unknown"
            predicted_utility = 0.0
            outcome_confidence = 0.0
            
            if outcome_predictor:
                pred = outcome_predictor.predict(context, option)
                predicted_utility = pred.predicted_utility
                predicted_outcome = pred.predicted_quality
                outcome_confidence = pred.confidence
            
            scored_options.append({
                "option": option,
                "score": score,
                "predicted_utility": predicted_utility,
                "predicted_outcome": predicted_outcome,
                "outcome_confidence": outcome_confidence,
            })
        
        # Sort by score (descending)
        scored_options.sort(key=lambda x: x["score"], reverse=True)
        
        # Normalize scores to 0-1
        scores = [o["score"] for o in scored_options]
        min_score, max_score = min(scores), max(scores)
        score_range = max_score - min_score if max_score > min_score else 1
        
        # Create ranked options
        ranked = []
        for rank, item in enumerate(scored_options, 1):
            normalized_score = (item["score"] - min_score) / score_range
            
            ranked.append(RankedOption(
                option=item["option"],
                rank=rank,
                preference_score=normalized_score,
                predicted_utility=item["predicted_utility"],
                predicted_outcome=item["predicted_outcome"],
                confidence=item["outcome_confidence"],
                explanation=self._generate_rank_explanation(
                    rank, item["option"], normalized_score, item["predicted_utility"]
                ),
            ))
        
        return ranked
    
    def learn_from_decision(
        self,
        options: List[Dict[str, Any]],
        chosen_index: int,
        context: Dict[str, Any],
        operator_id: str = "default"
    ):
        """
        Learn from an operator's decision.
        
        Args:
            options: List of options that were presented
            chosen_index: Index of the option the operator chose (0-based)
            context: Context at decision time
            operator_id: Who made the decision
        """
        # Store in operator history
        self.operator_history[operator_id].append({
            "timestamp": datetime.now().isoformat(),
            "context": context,
            "options": options,
            "chosen_index": chosen_index,
        })
        
        # Add to training buffer
        self.training_examples.append({
            "context": context,
            "options": options,
            "chosen_index": chosen_index,
            "operator_id": operator_id,
        })
        
        # Keep only recent history
        max_history = 1000
        if len(self.operator_history[operator_id]) > max_history:
            self.operator_history[operator_id] = (
                self.operator_history[operator_id][-max_history:]
            )
        
        logger.debug(
            "Learned decision: operator=%s chose option %d of %d",
            operator_id, chosen_index, len(options)
        )
    
    def _train_model(self):
        """Train model using buffered examples"""
        if self.training_examples:
            self.train(self.training_examples)
    
    def train(
        self,
        decision_data: List[Dict[str, Any]]
    ):
        """
        Train the ranking model on historical decisions.
        
        Args:
            decision_data: List of decision records with keys:
                - context: Dict
                - options: List[Dict]
                - chosen_index: int
                - operator_id: str
        """
        if not _ensure_lightgbm():
            logger.warning("Cannot train without LightGBM")
            return
        
        if len(decision_data) < 10:
            logger.warning("Not enough data to train (need at least 10 decisions)")
            return
        
        # Prepare training data
        X = []  # Features
        y = []  # Relevance labels
        groups = []  # Query groups
        
        for record in decision_data:
            context = record["context"]
            options = record["options"]
            chosen_idx = record["chosen_index"]
            
            context_features = self.context_fe.extract_features(context)
            group_size = 0
            
            for i, option in enumerate(options):
                action_features = self.action_fe.extract_features(option)
                features = np.concatenate([context_features, action_features])
                X.append(features)
                
                # Relevance: 2 for chosen, 1 for others
                y.append(2 if i == chosen_idx else 1)
                group_size += 1
            
            groups.append(group_size)
        
        X = np.array(X)
        y = np.array(y)
        
        # Train
        self.model.fit(X, y, group=groups)
        self.is_trained = True
        
        logger.info(
            "PreferenceRankingModel trained on %d decisions, %d option pairs",
            len(decision_data), len(X)
        )
    
    def save(self, path: Optional[str] = None):
        """Save model to disk"""
        # Resolve path
        if path is None:
            path = self.model_path
        if path is None:
            path = "preference_ranker.pkl"
            
        p = Path(path)
        if p.is_dir() or (not p.exists() and not p.suffix):
            p.mkdir(parents=True, exist_ok=True)
            p = p / "preference_ranker.pkl"
            
        data = {
            "model": self.model,
            "is_trained": self.is_trained,
            "operator_history": dict(self.operator_history),
        }
        with open(p, 'wb') as f:
            pickle.dump(data, f)
        logger.info("PreferenceRankingModel saved to %s", p)
    
    def load(self, path: str):
        """Load model from disk"""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.is_trained = data.get("is_trained", True)
        self.operator_history = defaultdict(list, data.get("operator_history", {}))
        logger.info("PreferenceRankingModel loaded from %s", path)
    
    def _heuristic_score(
        self,
        option: Dict[str, Any],
        context: Dict[str, Any],
        operator_id: str
    ) -> float:
        """
        Fallback heuristic scoring when model not trained.
        
        Uses operator personas if available, otherwise balanced scoring.
        """
        # Try to get operator persona
        from agent_advisory.qatar.context import get_operator_persona
        
        persona = get_operator_persona(operator_id)
        
        if persona:
            return persona.preference_score(option)
        
        # Default balanced scoring
        score = 0.5
        
        # Prefer lower risk
        risk = option.get("risk_score", 3)
        score -= (risk - 3) * 0.1
        
        # Prefer better comfort
        comfort = option.get("comfort_score", 3)
        score += (comfort - 3) * 0.08
        
        # Prefer energy savings
        energy = option.get("energy_impact_pct", 0)
        if energy < 0:  # Saves energy
            score += 0.1
        
        # Lower cost is better
        cost = option.get("cost_qar", 0)
        if cost < 500:
            score += 0.1
        elif cost > 2000:
            score -= 0.1
        
        return max(0, min(1, score))
    
    def _generate_rank_explanation(
        self,
        rank: int,
        option: Dict[str, Any],
        score: float,
        utility: float
    ) -> str:
        """Generate explanation for ranking"""
        action = option.get("action_type", option.get("action", "action"))
        
        if rank == 1:
            return f"Top recommendation: {action} - best match for operator preferences"
        elif rank <= 3:
            return f"Alternative {rank}: {action} - viable option with some tradeoffs"
        else:
            return f"Option {rank}: {action} - available if other options not suitable"


class ContextualBandit:
    """
    Contextual bandit for exploration/exploitation.
    
    Ensures ARVIS keeps learning by occasionally exploring
    less-certain options rather than always showing the same top pick.
    
    Uses Thompson Sampling with Beta priors per action type.
    """
    
    def __init__(self, exploration_rate: float = 0.1):
        """
        Initialize contextual bandit.
        
        Args:
            exploration_rate: Probability of exploration (0-1)
        """
        self.exploration_rate = exploration_rate
        
        # Beta distribution parameters per action type
        # (successes, failures)
        self.action_beliefs: Dict[str, Tuple[float, float]] = defaultdict(
            lambda: (1.0, 1.0)  # Uniform prior
        )
        
        logger.info("ContextualBandit initialized (exploration_rate=%.2f)", exploration_rate)
    
    def should_explore(self) -> bool:
        """Decide whether to explore this time"""
        return np.random.random() < self.exploration_rate
    
    def reorder_for_exploration(
        self,
        ranked_options: List[RankedOption]
    ) -> List[RankedOption]:
        """
        Potentially reorder options to explore less-certain ones.
        
        Uses Thompson Sampling to occasionally promote lower-ranked options.
        """
        if not ranked_options or len(ranked_options) < 2:
            return ranked_options
        
        if not self.should_explore():
            return ranked_options
        
        # Thompson Sampling: sample from beta distributions
        sampled_scores = []
        for opt in ranked_options:
            action_type = opt.option.get("action_type", "unknown")
            alpha, beta = self.action_beliefs[action_type]
            sampled = np.random.beta(alpha, beta)
            sampled_scores.append((sampled, opt))
        
        # Sort by sampled scores (descending)
        sampled_scores.sort(key=lambda x: x[0], reverse=True)
        
        # Update ranks
        reordered = []
        for new_rank, (_, opt) in enumerate(sampled_scores, 1):
            reordered.append(RankedOption(
                option=opt.option,
                rank=new_rank,
                preference_score=opt.preference_score,
                predicted_outcome=opt.predicted_outcome,
                confidence=opt.confidence,
                explanation=opt.explanation + " (exploration)",
            ))
        
        logger.debug("Exploration: reordered options for learning")
        return reordered
    
    def update_belief(
        self,
        action_type: str,
        was_successful: bool
    ):
        """
        Update beta distribution for action type based on outcome.
        
        Args:
            action_type: Type of action taken
            was_successful: Whether outcome was good
        """
        alpha, beta = self.action_beliefs[action_type]
        
        if was_successful:
            alpha += 1
        else:
            beta += 1
        
        self.action_beliefs[action_type] = (alpha, beta)
        
        logger.debug(
            "Updated belief for %s: success_rate=%.2f",
            action_type, alpha / (alpha + beta)
        )
    
    def get_action_success_rate(self, action_type: str) -> float:
        """Get current estimated success rate for action type"""
        alpha, beta = self.action_beliefs[action_type]
        return alpha / (alpha + beta)
