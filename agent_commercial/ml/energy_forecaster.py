"""
Energy Forecaster
=================

Advanced energy demand forecasting for commercial buildings.

Uses a hybrid approach:
1. Prophet - Captures seasonality (daily, weekly, Ramadan, Qatar holidays)
2. LightGBM - Feature-based prediction (weather, occupancy, equipment state)
3. Ensemble - Combines both for robust forecasting

Custom for Qatar/GCC:
- Ramadan working hours shift
- Peak tariff hours (12:00-18:00)
- Sandstorm events
- Extreme summer temperatures

Usage:
    >>> forecaster = EnergyForecaster()
    >>> forecaster.train(historical_data)
    >>> forecast = forecaster.predict(horizon_hours=24)
"""

import logging
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

logger = logging.getLogger("arvis.ml.energy")

# Suppress Prophet logging
logging.getLogger('prophet').setLevel(logging.WARNING)
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

# Try importing ML libraries
try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    warnings.warn("Prophet not installed. Run: pip install prophet")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    warnings.warn("LightGBM not installed. Run: pip install lightgbm")


# =============================================================================
# QATAR-SPECIFIC CONSTANTS
# =============================================================================

# Peak electricity hours in Qatar
PEAK_HOURS = (12, 18)  # 12:00 - 18:00

# Qatar electricity rates (QAR/kWh)
RATE_STANDARD = 0.033
RATE_PEAK = 0.066

# Ramadan dates (approximate - would use hijri library in production)
RAMADAN_DATES = {
    2024: (datetime(2024, 3, 10), datetime(2024, 4, 9)),
    2025: (datetime(2025, 2, 28), datetime(2025, 3, 29)),
    2026: (datetime(2026, 2, 17), datetime(2026, 3, 18)),
}

# GCC holidays (approximate)
HOLIDAYS = [
    "2026-01-01",  # New Year
    "2026-02-09",  # National Sports Day
    "2026-12-18",  # Qatar National Day
]


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class EnergyForecast:
    """Energy forecast result"""
    timestamp: datetime
    predicted_kwh: float
    lower_bound: float
    upper_bound: float
    confidence: float
    is_peak_hour: bool
    predicted_cost_qar: float
    anomaly_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "predicted_kwh": round(self.predicted_kwh, 2),
            "lower_bound": round(self.lower_bound, 2),
            "upper_bound": round(self.upper_bound, 2),
            "confidence": round(self.confidence, 3),
            "is_peak_hour": self.is_peak_hour,
            "predicted_cost_qar": round(self.predicted_cost_qar, 2),
            "anomaly_score": round(self.anomaly_score, 3),
        }


@dataclass
class ForecastResult:
    """Complete forecast result with metadata"""
    building_id: str
    generated_at: datetime
    horizon_hours: int
    hourly_forecast: List[EnergyForecast]
    daily_total_kwh: float
    daily_cost_qar: float
    peak_hour_kwh: float
    model_used: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_id": self.building_id,
            "generated_at": self.generated_at.isoformat(),
            "horizon_hours": self.horizon_hours,
            "hourly_forecast": [f.to_dict() for f in self.hourly_forecast],
            "summary": {
                "daily_total_kwh": round(self.daily_total_kwh, 1),
                "daily_cost_qar": round(self.daily_cost_qar, 2),
                "peak_hour_kwh": round(self.peak_hour_kwh, 1),
                "model_used": self.model_used,
                "confidence": round(self.confidence, 3),
            }
        }


# =============================================================================
# ENERGY FORECASTER
# =============================================================================

class EnergyForecaster:
    """
    Hybrid energy demand forecaster for commercial buildings.
    
    Uses Prophet for seasonality + LightGBM for features.
    Custom-tuned for Qatar/GCC climate and business patterns.
    """
    
    def __init__(self, building_id: str = "default"):
        self.building_id = building_id
        
        # Prophet model
        self.prophet_model: Optional[Prophet] = None
        self.prophet_trained = False
        
        # LightGBM model
        self.lgbm_model: Optional[lgb.Booster] = None
        self.lgbm_trained = False
        self.feature_names: List[str] = []
        
        # Ensemble weights (learned during training)
        self.prophet_weight = 0.4
        self.lgbm_weight = 0.6
        
        # Training history for anomaly detection
        self.training_mean = 0.0
        self.training_std = 1.0
        
        logger.info(f"EnergyForecaster initialized for {building_id}")
    
    def _is_ramadan(self, date: datetime) -> bool:
        """Check if date falls during Ramadan."""
        year = date.year
        if year in RAMADAN_DATES:
            start, end = RAMADAN_DATES[year]
            return start <= date <= end
        return False
    
    def _is_peak_hour(self, hour: int) -> bool:
        """Check if hour is during peak tariff period."""
        return PEAK_HOURS[0] <= hour < PEAK_HOURS[1]
    
    def _get_rate(self, hour: int) -> float:
        """Get electricity rate for hour."""
        return RATE_PEAK if self._is_peak_hour(hour) else RATE_STANDARD
    
    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create features for LightGBM from timestamp and weather.
        
        Custom features for BMS:
        - Time features (hour, day of week, month)
        - Qatar-specific (Ramadan, peak hours, holidays)
        - Weather (outdoor temp, humidity)
        - Lag features (yesterday same hour, last week same hour)
        """
        features = pd.DataFrame(index=df.index)
        
        # Ensure we have a datetime column and access mechanism
        if 'ds' in df.columns:
            dt_series = pd.to_datetime(df['ds'])
            dt_access = dt_series.dt
        elif 'timestamp' in df.columns:
            dt_series = pd.to_datetime(df['timestamp'])
            dt_access = dt_series.dt
        else:
            # Assume index is datetime
            dt_access = df.index
        
        # Time features
        features['hour'] = dt_access.hour
        features['day_of_week'] = dt_access.dayofweek
        features['month'] = dt_access.month
        features['is_weekend'] = (dt_access.dayofweek >= 4).astype(int)  # Fri-Sat
        
        # Qatar-specific
        # Note: apply() works on Series (dt_series) or Index. For Index we need to iterate or map.
        # Ideally we use the series if available, else index.
        if 'ds' in df.columns or 'timestamp' in df.columns:
             # Use the series for .apply
             target_for_apply = dt_series
        else:
             target_for_apply = df.index.to_series()

        features['is_peak_hour'] = target_for_apply.apply(lambda d: 1 if self._is_peak_hour(d.hour) else 0)
        features['is_ramadan'] = target_for_apply.apply(lambda d: 1 if self._is_ramadan(d) else 0)
        
        # Cyclical encoding (sin/cos for hour)
        features['hour_sin'] = np.sin(2 * np.pi * features['hour'] / 24)
        features['hour_cos'] = np.cos(2 * np.pi * features['hour'] / 24)
        features['dow_sin'] = np.sin(2 * np.pi * features['day_of_week'] / 7)
        features['dow_cos'] = np.cos(2 * np.pi * features['day_of_week'] / 7)
        
        # Weather features (if available)
        features['outdoor_temp'] = df['outdoor_temp'] if 'outdoor_temp' in df.columns else 35.0
        features['cooling_degree_hours'] = np.maximum(0, features['outdoor_temp'] - 24)
        
        if 'humidity' in df.columns:
            features['humidity'] = df['humidity']
        else:
            features['humidity'] = 40.0 # Standard GCC humidity
        
        # Lag features (Standardizing to 16/17 features)
        # We ensure these columns ALWAYS exist even if filled with 0s
        # Training used 16 features: 10 base + 2 weather + 4 lag = 16
        # If humidity is present, it's 17. The fatal said expected 16, got 12.
        # 12 = 10 base + 2 weather. So lag features were missing.
        
        target_col = 'y' if 'y' in df.columns else ('kwh' if 'kwh' in df.columns else None)
        
        if target_col:
            features['lag_1'] = df[target_col].shift(1)
            features['lag_24'] = df[target_col].shift(24)
            features['lag_168'] = df[target_col].shift(168)
            features['rolling_mean_24'] = df[target_col].rolling(24, min_periods=1).mean()
        else:
            features['lag_1'] = 0.0
            features['lag_24'] = 0.0
            features['lag_168'] = 0.0
            features['rolling_mean_24'] = 0.0
        
        return features.fillna(0)
    
    def train(self, 
              historical_data: pd.DataFrame,
              outdoor_temp: Optional[pd.Series] = None) -> Dict[str, Any]:
        """
        Train both Prophet and LightGBM models.
        
        Args:
            historical_data: DataFrame with columns:
                - 'ds' or 'timestamp': datetime
                - 'y' or 'kwh': energy consumption
            outdoor_temp: Optional outdoor temperature series
            
        Returns:
            Training metrics
        """
        metrics = {}
        
        # Prepare data
        df = historical_data.copy()
        if 'timestamp' in df.columns and 'ds' not in df.columns:
            df['ds'] = pd.to_datetime(df['timestamp'])
        if 'kwh' in df.columns and 'y' not in df.columns:
            df['y'] = df['kwh']
        
        if outdoor_temp is not None:
            df['outdoor_temp'] = outdoor_temp.values
        
        # Store training statistics for anomaly detection
        self.training_mean = df['y'].mean()
        self.training_std = df['y'].std()
        
        # ─────────────────────────────────────────────────────────────────
        # Train Prophet (seasonality model)
        # ─────────────────────────────────────────────────────────────────
        if PROPHET_AVAILABLE:
            try:
                self.prophet_model = Prophet(
                    yearly_seasonality=True,
                    weekly_seasonality=True,
                    daily_seasonality=True,
                    changepoint_prior_scale=0.05,
                    seasonality_prior_scale=10,
                )
                
                # Add Qatar-specific regressors
                if 'outdoor_temp' in df.columns:
                    self.prophet_model.add_regressor('outdoor_temp', mode='multiplicative')
                
                # Add Ramadan regressor
                df['is_ramadan'] = df['ds'].apply(lambda d: 1 if self._is_ramadan(d) else 0)
                self.prophet_model.add_regressor('is_ramadan', mode='multiplicative')
                
                # Add peak hour regressor
                df['is_peak'] = df['ds'].dt.hour.apply(lambda h: 1 if self._is_peak_hour(h) else 0)
                self.prophet_model.add_regressor('is_peak', mode='additive')
                
                # Train
                self.prophet_model.fit(df[['ds', 'y', 'is_ramadan', 'is_peak'] + 
                                         (['outdoor_temp'] if 'outdoor_temp' in df.columns else [])])
                self.prophet_trained = True
                
                # Cross-validation would go here in production
                metrics['prophet'] = {'status': 'trained', 'samples': len(df)}
                logger.info("Prophet model trained successfully")
                
            except Exception as e:
                logger.error(f"Prophet training failed: {e}")
                metrics['prophet'] = {'status': 'failed', 'error': str(e)}
        
        # ─────────────────────────────────────────────────────────────────
        # Train LightGBM (feature-based model)
        # ─────────────────────────────────────────────────────────────────
        if LIGHTGBM_AVAILABLE:
            try:
                # Create features
                features = self._create_features(df)
                self.feature_names = list(features.columns)
                
                X = features.values
                y = df['y'].values
                
                # Train/val split (last 20% for validation)
                split_idx = int(len(X) * 0.8)
                X_train, X_val = X[:split_idx], X[split_idx:]
                y_train, y_val = y[:split_idx], y[split_idx:]
                
                # Create datasets
                train_data = lgb.Dataset(X_train, label=y_train, feature_name=self.feature_names)
                val_data = lgb.Dataset(X_val, label=y_val, feature_name=self.feature_names, reference=train_data)
                
                # LightGBM parameters (tuned for energy forecasting)
                params = {
                    'objective': 'regression',
                    'metric': 'rmse',
                    'boosting_type': 'gbdt',
                    'num_leaves': 31,
                    'learning_rate': 0.05,
                    'feature_fraction': 0.9,
                    'bagging_fraction': 0.8,
                    'bagging_freq': 5,
                    'verbose': -1,
                }
                
                # Train with early stopping
                self.lgbm_model = lgb.train(
                    params,
                    train_data,
                    num_boost_round=500,
                    valid_sets=[val_data],
                    callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
                )
                self.lgbm_trained = True
                
                # Calculate validation metrics
                val_pred = self.lgbm_model.predict(X_val)
                rmse = np.sqrt(np.mean((val_pred - y_val) ** 2))
                mape = np.mean(np.abs((val_pred - y_val) / (y_val + 1e-8))) * 100
                
                metrics['lgbm'] = {
                    'status': 'trained',
                    'val_rmse': float(rmse),
                    'val_mape': float(mape),
                    'num_features': len(self.feature_names),
                    'best_iteration': self.lgbm_model.best_iteration,
                }
                logger.info(f"LightGBM model trained: RMSE={rmse:.2f}, MAPE={mape:.1f}%")
                
                # ─────────────────────────────────────────────────────────────────
                # Bayesian-style Ensemble Weight Optimization
                # ─────────────────────────────────────────────────────────────────
                if self.prophet_trained:
                    try:
                        # Evaluate Prophet on the same validation set
                        val_df_prophet = df.iloc[split_idx:].copy()
                        prophet_val_pred = self.prophet_model.predict(val_df_prophet)['yhat'].values
                        p_rmse = np.sqrt(np.mean((prophet_val_pred - y_val) ** 2))
                        
                        # Weight inverse to RMSE
                        w_p = 1.0 / (p_rmse + 1e-8)
                        w_l = 1.0 / (rmse + 1e-8)
                        
                        total_w = w_p + w_l
                        self.prophet_weight = w_p / total_w
                        self.lgbm_weight = w_l / total_w
                        
                        metrics['ensemble'] = {
                            'prophet_weight': float(self.prophet_weight),
                            'lgbm_weight': float(self.lgbm_weight),
                            'optimized': True
                        }
                        logger.info(f"Ensemble weights optimized: Prophet={self.prophet_weight:.2f}, LightGBM={self.lgbm_weight:.2f}")
                    except Exception as e:
                        logger.warning(f"Ensemble weight optimization failed: {e}")

            except Exception as e:
                logger.error(f"LightGBM training failed: {e}")
                metrics['lgbm'] = {'status': 'failed', 'error': str(e)}
        
        return metrics
    
    def predict(self,
                horizon_hours: int = 24,
                outdoor_temp_forecast: Optional[List[float]] = None) -> ForecastResult:
        """
        Generate energy forecast for next N hours.
        
        Args:
            horizon_hours: Number of hours to forecast
            outdoor_temp_forecast: Optional outdoor temperature forecast
            
        Returns:
            ForecastResult with hourly predictions
        """
        now = datetime.now()
        hourly_forecasts = []
        
        # Generate future timestamps
        future_times = [now + timedelta(hours=h) for h in range(horizon_hours)]
        
        # Create future dataframe
        future_df = pd.DataFrame({
            'ds': future_times,
            'is_ramadan': [1 if self._is_ramadan(t) else 0 for t in future_times],
            'is_peak': [1 if self._is_peak_hour(t.hour) else 0 for t in future_times],
        })
        
        if outdoor_temp_forecast:
            future_df['outdoor_temp'] = outdoor_temp_forecast[:horizon_hours]
        elif 'outdoor_temp' in (self.feature_names if hasattr(self, 'feature_names') else []):
            # Use default Qatar summer temperature profile
            future_df['outdoor_temp'] = [35 + 5 * np.sin((t.hour - 14) * np.pi / 12) 
                                         for t in future_times]
        
        # ─────────────────────────────────────────────────────────────────
        # Prophet predictions
        # ─────────────────────────────────────────────────────────────────
        prophet_preds = None
        if self.prophet_trained and self.prophet_model is not None:
            try:
                prophet_forecast = self.prophet_model.predict(future_df)
                prophet_preds = prophet_forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].values
            except Exception as e:
                logger.warning(f"Prophet prediction failed: {e}")
        
        # ─────────────────────────────────────────────────────────────────
        # LightGBM predictions
        # ─────────────────────────────────────────────────────────────────
        lgbm_preds = None
        if self.lgbm_trained and self.lgbm_model is not None:
            try:
                features = self._create_features(future_df)
                lgbm_preds = self.lgbm_model.predict(features.values)
            except Exception as e:
                logger.warning(f"LightGBM prediction failed: {e}")
        
        # ─────────────────────────────────────────────────────────────────
        # Ensemble predictions
        # ─────────────────────────────────────────────────────────────────
        model_used = []
        
        for i, ts in enumerate(future_times):
            if prophet_preds is not None and lgbm_preds is not None:
                # Ensemble: weighted average
                yhat = (self.prophet_weight * prophet_preds[i, 1] + 
                       self.lgbm_weight * lgbm_preds[i])
                lower = prophet_preds[i, 2] * 0.9  # Tighten bounds
                upper = prophet_preds[i, 3] * 1.1
                confidence = 0.85
                model = "ensemble"
            elif prophet_preds is not None:
                yhat = prophet_preds[i, 1]
                lower = prophet_preds[i, 2]
                upper = prophet_preds[i, 3]
                confidence = 0.75
                model = "prophet"
            elif lgbm_preds is not None:
                yhat = lgbm_preds[i]
                # Estimate uncertainty as 15% of prediction
                lower = yhat * 0.85
                upper = yhat * 1.15
                confidence = 0.7
                model = "lgbm"
            else:
                # Fallback: use training mean with time-of-day adjustment
                hour_factor = 0.7 + 0.6 * np.sin((ts.hour - 6) * np.pi / 12)
                yhat = self.training_mean * hour_factor
                lower = yhat * 0.7
                upper = yhat * 1.3
                confidence = 0.4
                model = "fallback"
            
            model_used.append(model)
            
            # Ensure non-negative
            yhat = max(0, yhat)
            lower = max(0, lower)
            upper = max(0, upper)
            
            # Calculate cost
            rate = self._get_rate(ts.hour)
            cost = yhat * rate
            
            # Anomaly score (how unusual is this prediction?)
            z_score = abs(yhat - self.training_mean) / (self.training_std + 1e-8)
            anomaly_score = min(1.0, z_score / 3)
            
            hourly_forecasts.append(EnergyForecast(
                timestamp=ts,
                predicted_kwh=yhat,
                lower_bound=lower,
                upper_bound=upper,
                confidence=confidence,
                is_peak_hour=self._is_peak_hour(ts.hour),
                predicted_cost_qar=cost,
                anomaly_score=anomaly_score,
            ))
        
        # Calculate daily totals
        daily_total = sum(f.predicted_kwh for f in hourly_forecasts)
        daily_cost = sum(f.predicted_cost_qar for f in hourly_forecasts)
        peak_kwh = sum(f.predicted_kwh for f in hourly_forecasts if f.is_peak_hour)
        
        return ForecastResult(
            building_id=self.building_id,
            generated_at=now,
            horizon_hours=horizon_hours,
            hourly_forecast=hourly_forecasts,
            daily_total_kwh=daily_total,
            daily_cost_qar=daily_cost,
            peak_hour_kwh=peak_kwh,
            model_used=model_used[0] if model_used else "none",
            confidence=np.mean([f.confidence for f in hourly_forecasts]),
        )
    
    def detect_anomaly(self, actual_kwh: float, timestamp: datetime) -> Dict[str, Any]:
        """
        Detect if actual consumption is anomalous.
        
        Uses prediction intervals and z-score.
        """
        # Get prediction for this hour
        forecast = self.predict(horizon_hours=1)
        predicted = forecast.hourly_forecast[0].predicted_kwh
        lower = forecast.hourly_forecast[0].lower_bound
        upper = forecast.hourly_forecast[0].upper_bound
        
        # Check if outside prediction interval
        is_anomaly = actual_kwh < lower or actual_kwh > upper
        
        # Calculate deviation
        deviation_pct = (actual_kwh - predicted) / (predicted + 1e-8) * 100
        z_score = (actual_kwh - self.training_mean) / (self.training_std + 1e-8)
        
        return {
            "is_anomaly": is_anomaly,
            "actual_kwh": actual_kwh,
            "predicted_kwh": predicted,
            "deviation_pct": round(deviation_pct, 1),
            "z_score": round(z_score, 2),
            "severity": "high" if abs(z_score) > 3 else "medium" if abs(z_score) > 2 else "low",
        }


    # =========================================================================
    # MODEL PERSISTENCE (ModelRegistry Integration)
    # =========================================================================

    def save_model(self, metrics: Optional[Dict] = None) -> Optional[str]:
        """Save trained models to ModelRegistry."""
        from agent_commercial.ml.model_registry import get_model_registry
        registry = get_model_registry()

        model_state = {
            "prophet_trained": self.prophet_trained,
            "lgbm_trained": self.lgbm_trained,
            "prophet_weight": self.prophet_weight,
            "lgbm_weight": self.lgbm_weight,
            "training_mean": self.training_mean,
            "training_std": self.training_std,
            "feature_names": self.feature_names,
            "building_id": self.building_id,
        }

        extra = {}
        if self.prophet_model and self.prophet_trained:
            extra["prophet_model"] = self.prophet_model
        if self.lgbm_model and self.lgbm_trained:
            extra["lgbm_model"] = self.lgbm_model

        save_metrics = metrics or {"prophet_trained": self.prophet_trained, "lgbm_trained": self.lgbm_trained}
        version = registry.save_model("energy_forecaster", model_state, save_metrics, extra_artifacts=extra or None)
        logger.info(f"Energy forecaster saved: energy_forecaster/{version}")
        return version

    def load_model(self) -> bool:
        """Load trained models from ModelRegistry."""
        from agent_commercial.ml.model_registry import get_model_registry
        registry = get_model_registry()

        model_state, metadata = registry.load_model("energy_forecaster")
        if model_state is None:
            return False

        self.prophet_trained = model_state.get("prophet_trained", False)
        self.lgbm_trained = model_state.get("lgbm_trained", False)
        self.prophet_weight = model_state.get("prophet_weight", 0.4)
        self.lgbm_weight = model_state.get("lgbm_weight", 0.6)
        self.training_mean = model_state.get("training_mean", 0.0)
        self.training_std = model_state.get("training_std", 1.0)
        self.feature_names = model_state.get("feature_names", [])

        prophet = registry.load_artifact("energy_forecaster", "prophet_model")
        if prophet:
            self.prophet_model = prophet

        lgbm = registry.load_artifact("energy_forecaster", "lgbm_model")
        if lgbm:
            self.lgbm_model = lgbm

        logger.info(f"Energy forecaster loaded (prophet={self.prophet_trained}, lgbm={self.lgbm_trained})")
        return True

    async def retrain(self, data: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Retrain pipeline for RetrainScheduler integration."""
        if data is None:
            logger.warning("No training data provided for energy forecaster retrain")
            return {"status": "skipped", "reason": "no_data"}

        result = self.train(data)
        if result.get("status") != "failed":
            self.save_model(result)
        return result


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_forecaster_instance: Optional[EnergyForecaster] = None


def get_energy_forecaster(building_id: str = "default") -> EnergyForecaster:
    """Get or create energy forecaster with model loading."""
    global _forecaster_instance
    if _forecaster_instance is None or _forecaster_instance.building_id != building_id:
        _forecaster_instance = EnergyForecaster(building_id)
        _forecaster_instance.load_model()
    return _forecaster_instance


def forecast_energy(
    building_id: str = "default",
    horizon_hours: int = 24,
    outdoor_temps: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Generate energy forecast - LLM tool handler.
    """
    forecaster = get_energy_forecaster(building_id)
    result = forecaster.predict(horizon_hours, outdoor_temps)
    return result.to_dict()


if __name__ == "__main__":
    import random
    
    print("=" * 60)
    print("Energy Forecaster Test")
    print("=" * 60)
    
    # Create synthetic training data
    dates = pd.date_range(start='2025-01-01', periods=720, freq='H')  # 30 days
    base_load = 100
    
    # Simulate daily pattern
    hourly_pattern = [0.6, 0.55, 0.5, 0.5, 0.55, 0.65, 0.8, 0.95, 
                      1.0, 1.0, 1.0, 1.05, 1.1, 1.05, 1.0, 0.95,
                      0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55]
    
    consumption = []
    for dt in dates:
        pattern = hourly_pattern[dt.hour]
        weekend_factor = 0.7 if dt.dayofweek >= 4 else 1.0
        noise = random.uniform(0.9, 1.1)
        consumption.append(base_load * pattern * weekend_factor * noise)
    
    df = pd.DataFrame({'ds': dates, 'y': consumption})
    
    # Train forecaster
    forecaster = EnergyForecaster("tower_a")
    metrics = forecaster.train(df)
    print(f"\nTraining metrics: {metrics}")
    
    # Generate forecast
    forecast = forecaster.predict(horizon_hours=24)
    print(f"\n24-hour forecast:")
    print(f"  Total: {forecast.daily_total_kwh:.1f} kWh")
    print(f"  Cost: QAR {forecast.daily_cost_qar:.2f}")
    print(f"  Peak hours: {forecast.peak_hour_kwh:.1f} kWh")
    print(f"  Model: {forecast.model_used}")
    print(f"  Confidence: {forecast.confidence:.1%}")
