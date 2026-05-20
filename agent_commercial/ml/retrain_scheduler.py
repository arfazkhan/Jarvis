"""
Retrain Scheduler — Model Performance Monitor & Auto-Retrain Triggers
======================================================================

Monitors model performance drift and triggers retraining when:
- Time-based: model exceeds max staleness
- Performance-based: accuracy degrades beyond threshold
- Data-based: enough new data has accumulated since last train

Usage:
    scheduler = RetrainScheduler()
    await scheduler.check_triggers()  # Call hourly from cognitive loop
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from agent_commercial.ml.model_registry import get_model_registry

logger = logging.getLogger("arvis.ml.retrain_scheduler")


TRIGGER_CONFIG = {
    "energy_forecaster": {
        "max_staleness_days": 7,
        "performance_metric": "mape",
        "performance_threshold": 0.15,
        "min_new_samples": 1000,
    },
    "fdd_autoencoder": {
        "max_staleness_days": 30,
        "performance_metric": "false_positive_rate",
        "performance_threshold": 0.10,
        "min_new_samples": 500,
    },
    "causal_inference": {
        "max_staleness_days": 30,
        "performance_metric": "edge_confidence",
        "performance_threshold": 0.5,
        "min_new_samples": 50,
    },
    "ml_simulator": {
        "max_staleness_days": 90,
        "performance_metric": "mae",
        "performance_threshold": 0.2,
        "min_new_samples": 200,
    },
}


class RetrainScheduler:
    """Monitors model staleness and performance, triggers retraining."""

    def __init__(self):
        self.registry = get_model_registry()
        self._sample_counters: Dict[str, int] = {}
        self._performance_log: Dict[str, List[float]] = {}
        self._last_check: Optional[datetime] = None

    def record_sample(self, model_name: str, count: int = 1) -> None:
        """Record new training-eligible samples for a model."""
        self._sample_counters[model_name] = self._sample_counters.get(model_name, 0) + count

    def record_performance(self, model_name: str, metric_value: float) -> None:
        """Record a performance measurement (rolling window of 50)."""
        if model_name not in self._performance_log:
            self._performance_log[model_name] = []
        self._performance_log[model_name].append(metric_value)
        if len(self._performance_log[model_name]) > 50:
            self._performance_log[model_name] = self._performance_log[model_name][-50:]

    async def check_triggers(self) -> List[Dict[str, Any]]:
        """
        Check all trigger conditions. Call hourly.

        Returns list of models needing retraining with reasons.
        """
        self._last_check = datetime.now()
        triggered = []

        for model_name, config in TRIGGER_CONFIG.items():
            reasons = []

            # 1. Time-based trigger
            _, metadata = self.registry.load_model(model_name)
            if metadata:
                created = metadata.get("created_at", "")
                if created:
                    try:
                        model_date = datetime.fromisoformat(created)
                        days_old = (datetime.now() - model_date).days
                        if days_old > config["max_staleness_days"]:
                            reasons.append(f"stale ({days_old}d > {config['max_staleness_days']}d)")
                    except ValueError:
                        pass

            # 2. Performance-based trigger
            perf_values = self._performance_log.get(model_name, [])
            if len(perf_values) >= 10:
                import numpy as np
                recent_perf = np.mean(perf_values[-10:])
                threshold = config["performance_threshold"]
                if recent_perf > threshold:
                    reasons.append(f"{config['performance_metric']}={recent_perf:.3f} > {threshold}")

            # 3. Data-based trigger
            new_samples = self._sample_counters.get(model_name, 0)
            if new_samples >= config["min_new_samples"]:
                reasons.append(f"{new_samples} new samples accumulated")

            if reasons:
                triggered.append({
                    "model_name": model_name,
                    "reasons": reasons,
                    "timestamp": datetime.now().isoformat(),
                })
                logger.info(f"[RetrainScheduler] {model_name} needs retraining: {', '.join(reasons)}")

        return triggered

    async def retrain_model(self, model_name: str) -> Dict[str, Any]:
        """
        Execute retraining pipeline for a specific model.

        Each model has its own training logic; this dispatches to the right one.
        """
        logger.info(f"[RetrainScheduler] Starting retrain for: {model_name}")

        try:
            if model_name == "energy_forecaster":
                from agent_commercial.ml.energy_forecaster import get_energy_forecaster
                forecaster = get_energy_forecaster()
                result = await forecaster.retrain()
            elif model_name == "fdd_autoencoder":
                from agent_commercial.ml.fdd_autoencoder import get_fdd_engine
                fdd = get_fdd_engine()
                result = await fdd.retrain()
            elif model_name == "causal_inference":
                from agent_commercial.ml.causal_inference import get_causal_engine
                engine = get_causal_engine()
                result = await engine.retrain()
            elif model_name == "ml_simulator":
                from agent_commercial.ml.ml_simulator import get_simulator
                sim = get_simulator()
                result = await sim.retrain()
            else:
                return {"status": "error", "reason": f"Unknown model: {model_name}"}

            # Reset sample counter after successful retrain
            self._sample_counters[model_name] = 0
            logger.info(f"[RetrainScheduler] Retrain complete for {model_name}")

            # M6.2: Record retrain event in audit trail via model registry metadata
            try:
                new_version = self.registry.get_active_version(model_name)
                logger.info(f"[RetrainScheduler] {model_name} active version after retrain: {new_version}")
            except Exception:
                pass

            return {"status": "success", "model": model_name, "result": result, "retrained_at": datetime.now().isoformat()}

        except Exception as e:
            logger.error(f"[RetrainScheduler] Retrain failed for {model_name}: {e}")
            return {"status": "error", "model": model_name, "reason": str(e)}

    async def on_drift_detected(self, model_id: str, drift_score: float, threshold: float = 0.5) -> Optional[Dict[str, Any]]:
        """
        Immediate retrain trigger when drift exceeds threshold.
        Called by prediction_engine/forecaster at detection time — no hourly delay.
        Returns retrain result if triggered, None otherwise.
        """
        if drift_score <= threshold:
            return None
        model_name = model_id.split(":")[0] if ":" in model_id else model_id
        if model_name not in TRIGGER_CONFIG:
            model_name = "energy_forecaster"  # default fallback
        logger.info(
            f"[RetrainScheduler] IMMEDIATE drift trigger: {model_id} "
            f"drift={drift_score:.3f} > {threshold}"
        )
        self.record_performance(model_name, drift_score)
        return await self.retrain_model(model_name)

    async def check_and_execute(self) -> List[Dict[str, Any]]:
        """Check triggers and immediately execute retraining for any triggered models. Call hourly."""
        triggered = await self.check_triggers()
        results = []
        for entry in triggered:
            result = await self.retrain_model(entry["model_name"])
            result["trigger_reasons"] = entry["reasons"]
            results.append(result)
        return results

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status summary."""
        return {
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "sample_counters": dict(self._sample_counters),
            "models_tracked": list(TRIGGER_CONFIG.keys()),
            "performance_samples": {k: len(v) for k, v in self._performance_log.items()},
        }


_scheduler_instance: Optional[RetrainScheduler] = None


def get_retrain_scheduler() -> RetrainScheduler:
    """Get singleton retrain scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = RetrainScheduler()
    return _scheduler_instance
