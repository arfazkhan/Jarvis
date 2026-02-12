"""
ML Model Training Pipeline
===========================

Generate synthetic data and train ML models for Phase 2.

Usage:
    python -m agent_advisory.training.train_models --scenarios 5000

This script:
1. Generates synthetic scenarios using QatarBuildingSimulator
2. Trains OutcomePredictor (XGBoost)
3. Trains PreferenceRankingModel (LightGBM)
4. Evaluates performance and saves models
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple
import json

import numpy as np

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent_advisory.qatar.simulator import QatarBuildingSimulator, SimulatedScenario
from agent_advisory.qatar.feature_engineer import QatarFeatureEngineer, ActionFeatureEngineer
from agent_advisory.ml_models.outcome_predictor import OutcomePredictor
from agent_advisory.ml_models.preference_ranker import PreferenceRankingModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("arvis.training")


class MLTrainingPipeline:
    """
    End-to-end training pipeline for Phase 2 ML models.
    """
    
    OUTCOME_MAP = {
        "poor": 0,
        "acceptable": 1,
        "good": 2,
        "excellent": 3,
    }
    
    def __init__(self, model_dir: str = None, seed: int = 42):
        """
        Initialize training pipeline.
        
        Args:
            model_dir: Directory to save trained models
            seed: Random seed for reproducibility
        """
        self.model_dir = Path(model_dir or "models/advisory")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.seed = seed
        
        # Components
        self.simulator = QatarBuildingSimulator(seed=seed)
        self.context_fe = QatarFeatureEngineer()
        self.action_fe = ActionFeatureEngineer()
        
        # Models
        self.outcome_predictor = OutcomePredictor(model_path=str(self.model_dir))
        self.ranking_model = PreferenceRankingModel(model_path=str(self.model_dir))
        
        # Training data
        self.scenarios: List[SimulatedScenario] = []
        self.X_outcome = None
        self.y_outcome = None
        self.ranking_data = []
        
        logger.info("Training pipeline initialized")
    
    def generate_data(self, n_scenarios: int = 5000) -> None:
        """
        Generate synthetic training data.
        
        Args:
            n_scenarios: Number of scenarios to generate
        """
        logger.info("Generating %d synthetic scenarios...", n_scenarios)
        
        self.scenarios = self.simulator.generate_scenarios(n=n_scenarios)
        
        logger.info("Generated %d scenarios", len(self.scenarios))
        
        # Log distribution
        outcome_dist = {}
        issue_dist = {}
        for s in self.scenarios:
            outcome_dist[s.outcome_quality] = outcome_dist.get(s.outcome_quality, 0) + 1
            issue_dist[s.issue_type] = issue_dist.get(s.issue_type, 0) + 1
        
        logger.info("Outcome distribution: %s", outcome_dist)
        logger.info("Top 5 issues: %s", dict(sorted(issue_dist.items(), key=lambda x: -x[1])[:5]))
    
    def prepare_outcome_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare data for outcome prediction model.
        
        Returns:
            X: Feature matrix (n_samples, n_features)
            y: Outcome labels (n_samples,)
        """
        logger.info("Preparing outcome prediction data...")
        
        X_list = []
        y_list = []
        
        for scenario in self.scenarios:
            # Extract context features
            context_features = self.context_fe.extract_features(scenario.context)
            
            # Extract action features
            action_features = self.action_fe.extract_features(scenario.best_action_details)
            
            # Combine features
            combined = np.concatenate([context_features, action_features])
            X_list.append(combined)
            
            # Label: utility score (continuous 0-1)
            y_list.append(scenario.utility_score)
        
        self.X_outcome = np.array(X_list)
        self.y_outcome = np.array(y_list)
        
        logger.info("Outcome data: X=%s, y=%s", self.X_outcome.shape, self.y_outcome.shape)
        
        return self.X_outcome, self.y_outcome
    
    def prepare_ranking_data(self) -> List[Dict]:
        """
        Prepare data for preference ranking model.
        
        Returns:
            List of training examples with context, options, and chosen index
        """
        logger.info("Preparing ranking data...")
        
        self.ranking_data = []
        
        # Group scenarios by similar context
        context_groups = {}
        for scenario in self.scenarios:
            key = (scenario.building_id, scenario.issue_type)
            if key not in context_groups:
                context_groups[key] = []
            context_groups[key].append(scenario)
        
        # For each group, create ranking examples
        for key, scenarios in context_groups.items():
            if len(scenarios) < 2:
                continue
            
            # Use first scenario's context as the query
            base_scenario = scenarios[0]
            
            # Create options from different actions taken
            options = []
            for s in scenarios[:5]:  # Max 5 options per group
                options.append({
                    "action_type": s.operator_decision,
                    "outcome_quality": s.outcome_quality,
                    "outcome_utility": s.utility_score,
                    **s.best_action_details
                })
            
            if len(options) < 2:
                continue
            
            # Best option is the one with highest utility
            best_idx = max(range(len(options)), 
                          key=lambda i: options[i]["outcome_utility"])
            
            self.ranking_data.append({
                "context": base_scenario.context,
                "options": options,
                "chosen_index": best_idx,
                "operator_id": base_scenario.operator_id,
            })
        
        logger.info("Ranking data: %d examples", len(self.ranking_data))
        
        return self.ranking_data
    
    def train_outcome_predictor(self) -> Dict[str, float]:
        """
        Train the outcome prediction model.
        
        Returns:
            Performance metrics
        """
        logger.info("Training OutcomePredictor...")
        
        # Split scenarios
        n_samples = len(self.scenarios)
        n_train = int(n_samples * 0.8)
        
        import random
        shuffled = self.scenarios.copy()
        random.seed(self.seed)
        random.shuffle(shuffled)
        
        train_scenarios = shuffled[:n_train]
        test_scenarios = shuffled[n_train:]
        
        # Prepare training data (OutcomePredictor handles feature extraction)
        train_ctx = [s.context for s in train_scenarios]
        train_act = [s.best_action_details for s in train_scenarios]
        train_util = [s.utility_score for s in train_scenarios]
        
        # Train
        self.outcome_predictor.train(train_ctx, train_act, train_util)
        
        # Evaluate
        metrics = self._evaluate_outcome_predictor_scenarios(test_scenarios)
        
        # Save
        self.outcome_predictor.save()
        
        logger.info("OutcomePredictor trained: MAE=%.4f", metrics["mae"])
        
        return metrics
    
    def _evaluate_outcome_predictor_scenarios(
        self, 
        scenarios: List[SimulatedScenario]
    ) -> Dict[str, float]:
        """Evaluate outcome predictor on test scenarios"""
        predictions = []
        confidences = []
        actuals = []
        
        for scenario in scenarios:
            # Predict
            result = self.outcome_predictor.predict(
                scenario.context, 
                scenario.best_action_details
            )
            
            # Record
            predicted_util = result.predicted_utility
            actual_util = scenario.utility_score
            
            predictions.append(predicted_util)
            confidences.append(result.confidence)
            actuals.append(actual_util)
        
        predictions = np.array(predictions)
        actuals = np.array(actuals)
        
        # Calculate regression metrics
        mae = np.mean(np.abs(predictions - actuals))
        mse = np.mean((predictions - actuals) ** 2)
        
        # Approximate accuracy (within 0.1 of actual utility)
        correct_approx = np.mean(np.abs(predictions - actuals) < 0.15)
        
        return {
            "mae": mae,
            "mse": mse,
            "accuracy_approx": correct_approx,
            "n_test_samples": len(actuals),
        }
    
    def train_ranking_model(self) -> Dict[str, float]:
        """
        Train the preference ranking model.
        
        Returns:
            Performance metrics
        """
        logger.info("Training PreferenceRankingModel...")
        
        if not self.ranking_data:
            self.prepare_ranking_data()
        
        # Split data
        n_samples = len(self.ranking_data)
        n_train = int(n_samples * 0.8)
        
        np.random.shuffle(self.ranking_data)
        train_data = self.ranking_data[:n_train]
        test_data = self.ranking_data[n_train:]
        
        # Train by simulating decisions
        for example in train_data:
            self.ranking_model.learn_from_decision(
                options=example["options"],
                chosen_index=example["chosen_index"],
                context=example["context"],
                operator_id=example["operator_id"]
            )
        
        # Force train if we have enough data
        if len(self.ranking_model.training_examples) >= 50:
            self.ranking_model._train_model()
        
        # Evaluate
        metrics = self._evaluate_ranking_model(test_data)
        
        # Save
        self.ranking_model.save()
        
        logger.info("PreferenceRankingModel trained: precision@1=%.2f%%", 
                   metrics.get("precision_at_1", 0) * 100)
        
        return metrics
    
    def _evaluate_ranking_model(self, test_data: List[Dict]) -> Dict[str, float]:
        """Evaluate ranking model on test set"""
        correct_at_1 = 0
        correct_in_top_2 = 0
        ndcg_scores = []
        
        for example in test_data:
            # Rank options
            ranked = self.ranking_model.rank_options(
                options=example["options"],
                context=example["context"],
                operator_id=example["operator_id"]
            )
            
            # Check if correct option is ranked first
            chosen_option = example["options"][example["chosen_index"]]
            
            if ranked:
                top_action = ranked[0].option.get("action_type", "")
                if top_action == chosen_option.get("action_type", ""):
                    correct_at_1 += 1
                
                if len(ranked) >= 2:
                    top_2_actions = [r.option.get("action_type", "") for r in ranked[:2]]
                    if chosen_option.get("action_type", "") in top_2_actions:
                        correct_in_top_2 += 1
        
        n_test = len(test_data)
        
        return {
            "precision_at_1": correct_at_1 / n_test if n_test > 0 else 0,
            "precision_at_2": correct_in_top_2 / n_test if n_test > 0 else 0,
            "n_test_samples": n_test,
        }
    
    def run_full_training(self, n_scenarios: int = 5000) -> Dict[str, Any]:
        """
        Run the complete training pipeline.
        
        Returns:
            Combined metrics for all models
        """
        start_time = datetime.now()
        
        logger.info("=" * 60)
        logger.info("ARVIS Phase 2 ML Training Pipeline")
        logger.info("=" * 60)
        
        # Generate data
        self.generate_data(n_scenarios)
        
        # Prepare datasets
        self.prepare_outcome_data()
        self.prepare_ranking_data()
        
        # Train models
        outcome_metrics = self.train_outcome_predictor()
        ranking_metrics = self.train_ranking_model()
        
        # Summary
        duration = (datetime.now() - start_time).total_seconds()
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": duration,
            "n_scenarios": n_scenarios,
            "outcome_predictor": outcome_metrics,
            "preference_ranker": ranking_metrics,
            "models_saved_to": str(self.model_dir),
        }
        
        # Save results
        results_path = self.model_dir / "training_results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info("=" * 60)
        logger.info("TRAINING COMPLETE")
        logger.info("=" * 60)
        logger.info("Duration: %.1f seconds", duration)
        logger.info("Scenarios: %d", n_scenarios)
        logger.info("")
        logger.info("OutcomePredictor:")
        logger.info("  MAE: %.4f", outcome_metrics["mae"])
        logger.info("  Accuracy (approx): %.2f%%", outcome_metrics["accuracy_approx"] * 100)
        logger.info("")
        logger.info("PreferenceRanker:")
        logger.info("  Precision@1: %.2f%%", ranking_metrics.get("precision_at_1", 0) * 100)
        logger.info("  Precision@2: %.2f%%", ranking_metrics.get("precision_at_2", 0) * 100)
        logger.info("")
        logger.info("Models saved to: %s", self.model_dir)
        
        return results


def main():
    parser = argparse.ArgumentParser(description="Train ARVIS Phase 2 ML Models")
    parser.add_argument(
        "--scenarios", "-n",
        type=int,
        default=5000,
        help="Number of synthetic scenarios to generate"
    )
    parser.add_argument(
        "--model-dir", "-o",
        type=str,
        default="models/advisory",
        help="Directory to save trained models"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Random seed for reproducibility"
    )
    
    args = parser.parse_args()
    
    pipeline = MLTrainingPipeline(
        model_dir=args.model_dir,
        seed=args.seed
    )
    
    results = pipeline.run_full_training(n_scenarios=args.scenarios)
    
    return results


if __name__ == "__main__":
    main()
