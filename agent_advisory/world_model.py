"""
World Model Module
==================

This module implements the World Model for the BMS Agent, enabling it to simulate
future states of the building environment based on current state and proposed actions.

The World Model consists of:
1. StateTransitionModel: Predicts next state features (temp, pressure, etc.) given (state, action).
2. RewardModel: Predicts utility/cost of a state (wraps OutcomePredictor).
3. TrajectorySimulator: Simulates multi-step rollouts for planning.
"""

import logging
import numpy as np
import pandas as pd
import xgboost as xgb
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from agent_advisory.qatar.feature_engineer import QatarFeatureEngineer

logger = logging.getLogger("arvis.advisory.world_model")

@dataclass
class WorldState:
    """Represents the state of the world at a specific timestep"""
    timestamp: datetime
    features: Dict[str, float]
    raw_context: Dict[str, Any]  # Original BMS data for reference

@dataclass
class SimulatedTrajectory:
    """Result of a multi-step simulation"""
    initial_state: WorldState
    actions: List[str]
    predicted_states: List[WorldState]
    predicted_rewards: List[float]
    confidence_scores: List[float]
    
    @property
    def total_reward(self) -> float:
        return sum(self.predicted_rewards)
    
    @property
    def final_state(self) -> WorldState:
        return self.predicted_states[-1] if self.predicted_states else self.initial_state

class StateTransitionModel:
    """
    Predicts S_{t+1} given S_t and A_t using XGBoost regressors.
    One regressor per key feature (e.g., one for temp, one for energy).
    """
    
    def __init__(self, feature_engineer: Optional[QatarFeatureEngineer] = None):
        self.fe = feature_engineer or QatarFeatureEngineer()
        self.models: Dict[str, xgb.XGBRegressor] = {}
        self.target_features = [
            "zone_temp_avg_c", "total_power_kw", "cooling_load_pct", "chiller_efficiency_kw_ton"
        ]
        self.is_trained = False
        
    def train(self, historical_scenarios: List[Dict[str, Any]]):
        """
        Train transition models on historical (S_t, A_t) -> S_{t+1} pairs.
        In this synthetic setup, we generate 'next' states by applying actions to 'current' states.
        """
        logger.info(f"Preparing training data from {len(historical_scenarios)} scenarios...")
        
        X_rows = []
        Y_rows = {feat: [] for feat in self.target_features}
        
        for scene in historical_scenarios:
            context = scene.get("context", {})
            action = scene.get("operator_decision", "no_op")
            
            # 1. Prepare features at t
            # Base features from context
            features = []
            for feat_name in self.fe.get_feature_names():
                features.append(context.get(feat_name, 0.0))
            
            # Add action (one-hot or label encoded for simplicity in prototype)
            # For prototype: simple mapping
            action_map = {a: i for i, a in enumerate(["no_op", "reduce_load", "stage_down", "optimize_setpoints", "schedule_maintenance"])}
            action_code = action_map.get(action, 0)
            features.append(float(action_code))
            
            X_rows.append(features)
            
            # 2. Simulate/Observe state at t+1 
            # In a real system, we'd look at the record AFTER the action.
            # In our simulator, we use the predict_next_state heuristics (trained on real data later)
            # For THIS training, we use the 'outcome' data from the scenario if available
            # Or we simply use the simulator to generate the Y
            
            # For prototype training, we simulate the Y using our heuristic to show the pipeline works
            # Once we have real building logs, we would use scene_t and scene_t+1
            initial_state = WorldState(datetime.now(), context, {})
            next_state = self.predict_next_state(initial_state, action)
            
            for feat in self.target_features:
                Y_rows[feat].append(next_state.features.get(feat, 0.0))
        
        X = np.array(X_rows)
        
        for feat in self.target_features:
            logger.info(f"Training XGBRegressor for: {feat}")
            y = np.array(Y_rows[feat])
            model = xgb.XGBRegressor(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                objective='reg:squarederror'
            )
            model.fit(X, y)
            self.models[feat] = model
            
        self.is_trained = True
        logger.info("Transition Model training complete.")

    def predict_next_state(self, current_state: WorldState, action: str) -> WorldState:
        """
        Predict the next state vector using ML models (if trained) or heuristics.
        """
        next_timestamp = current_state.timestamp + timedelta(minutes=15)
        
        # If trained, use ML models for target features
        if self.is_trained and self.models:
            # Prepare feature vector (S_t + A_t)
            features = []
            for feat_name in self.fe.get_feature_names():
                features.append(current_state.features.get(feat_name, 0.0))
            
            action_map = {a: i for i, a in enumerate(["no_op", "reduce_load", "stage_down", "optimize_setpoints", "schedule_maintenance"])}
            action_code = action_map.get(action, 0)
            features.append(float(action_code))
            
            X = np.array([features])
            
            # Predict
            next_features = current_state.features.copy()
            for feat, model in self.models.items():
                pred = model.predict(X)[0]
                next_features[feat] = float(pred)
        else:
            # Fallback to Heuristics (Prototyping/Cold-start)
            next_features = current_state.features.copy()
            
            # 1. Action Effects
            if action == "reduce_load":
                # Reduces power (-10%), increases temp slightly (+0.2C)
                next_features["total_power_kw"] = next_features.get("total_power_kw", 0) * 0.90
                next_features["zone_temp_avg_c"] = next_features.get("zone_temp_avg_c", 23) + 0.2
                
            elif action == "stage_down":
                 # Big power drop (-25%), risk of temp rise (+0.5C)
                 next_features["total_power_kw"] = next_features.get("total_power_kw", 0) * 0.75
                 next_features["zone_temp_avg_c"] = next_features.get("zone_temp_avg_c", 23) + 0.5
                 
            elif action == "optimize_setpoints":
                 # Improved efficiency, same comfort
                 next_features["chiller_efficiency_kw_ton"] = next_features.get("chiller_efficiency_kw_ton", 0.6) * 0.95
                 
        # 3. Time evolution (Always update)
        hour = next_timestamp.hour
        next_features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        next_features["hour_cos"] = np.cos(2 * np.pi * hour / 24)
             
        return WorldState(
            timestamp=next_timestamp,
            features=next_features,
            raw_context={} 
        )

class WorldModel:
    """
    Main entry point for simulation and planning.
    """
    
    def __init__(self, transition_model: StateTransitionModel):
        self.transition_model = transition_model
        
    def simulate_action(self, initial_context: Dict, action: str, horizon: int = 4) -> SimulatedTrajectory:
        """
        Simulate the effect of an action over 'horizon' steps (e.g., 1 hour if step=15min).
        """
        # 1. Build initial WorldState from raw context
        fe = self.transition_model.fe
        # Assuming extract_features might work on raw dict or we manually build
        # For now, we assume initial_context has some numeric/raw data
        # We try to extract features IF feature engineer supports it, else use simple dict mapping
        try:
             # This depends on your FeatureEngineer implementation expecting specific keys
             # If it fails, fallback to simple mapping
             features_array = fe.extract_features(initial_context)
             # Convert array back to dict if needed, or update fe to specific extraction
             # For this prototype: Assume initial_context IS the feature dict or close to it
             features = initial_context.copy()
        except:
             features = initial_context.copy()
             
        initial_timestamp = initial_context.get("timestamp", datetime.now())
        if isinstance(initial_timestamp, str):
            try:
                initial_timestamp = datetime.fromisoformat(initial_timestamp)
            except:
                initial_timestamp = datetime.now()
                
        initial_state = WorldState(initial_timestamp, features, initial_context)
        
        states = [initial_state]
        rewards = []
        confidences = []
        actions_taken = []
        
        current_state = initial_state
        
        for i in range(horizon):
            # For t > 0, we assume NO-OP (system drift) unless it's a multi-step policy
            # Here we simulate: Action at t=0, then No-Op
            step_action = action if i == 0 else "no_op"
            actions_taken.append(step_action)
            
            # Predict next state
            next_state = self.transition_model.predict_next_state(current_state, step_action)
            states.append(next_state)
            
            # Calculate Reward (Utility) of the NEXT state
            # TODO: Use OutcomePredictor/RewardModel here. 
            # For prototype: Calculate simple utility
            # Utility = - (Power * Cost + Discomfort Penalty)
            power = next_state.features.get("total_power_kw", 0)
            temp = next_state.features.get("zone_temp_avg_c", 23)
            
            # Simple cost model: 0.2 QAR/kWh * 0.25h
            cost = power * 0.25 * 0.2 
            
            # Discomfort penalty if temp > 24 or < 20
            discomfort = 0
            if temp > 24: discomfort = (temp - 24) * 2.0
            if temp < 20: discomfort = (20 - temp) * 2.0
            
            # Reward is negative cost/penalty (higher is better)
            # Normalize for prototype
            step_reward = - (cost + discomfort)
            rewards.append(step_reward)
            
            # Confidence (degrades over time)
            step_conf = 0.9 * (0.85 ** i)
            confidences.append(step_conf)
            
            current_state = next_state
        
        return SimulatedTrajectory(
            initial_state=initial_state,
            actions=actions_taken,
            predicted_states=states[1:], # Return predicted steps (t+1..t+H)
            predicted_rewards=rewards,
            confidence_scores=confidences
        )
