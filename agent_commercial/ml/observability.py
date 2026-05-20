"""
ML Observability
================

Per-model health dashboard, fallback rate tracking, drift curves.
Exposed via SSE broadcaster for frontend dashboard.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.ml.observability")

_MAX_HISTORY = 200  # per-model rolling window


class MLObservability:
    """
    Tracks ML call outcomes (success/failure, latency, drift) per model.
    Thread-safe reads; single-threaded writes (event loop only).
    """

    def __init__(self):
        self._calls: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_HISTORY))
        self._fallback_counts: Dict[str, int] = defaultdict(int)
        self._total_counts: Dict[str, int] = defaultdict(int)
        self._drift_history: Dict[str, Deque[Tuple[float, float]]] = defaultdict(lambda: deque(maxlen=50))

    def record_ml_call(
        self,
        model_id: str,
        success: bool,
        latency_ms: float,
        fallback: bool = False,
        drift_score: Optional[float] = None,
    ) -> None:
        """Record one ML call outcome."""
        ts = time.time()
        self._calls[model_id].append({
            "ts": ts,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "fallback": fallback,
            "drift_score": drift_score,
        })
        self._total_counts[model_id] += 1
        if fallback or not success:
            self._fallback_counts[model_id] += 1
        if drift_score is not None:
            self._drift_history[model_id].append((ts, drift_score))

    def get_model_health(self, model_id: str) -> Dict[str, Any]:
        """Health snapshot for one model."""
        calls = list(self._calls[model_id])
        total = self._total_counts[model_id]
        fallbacks = self._fallback_counts[model_id]

        if not calls:
            return {"model_id": model_id, "status": "no_data", "total_calls": 0}

        recent = calls[-20:]
        recent_success = sum(1 for c in recent if c["success"] and not c["fallback"])
        recent_fallback = sum(1 for c in recent if c["fallback"])
        recent_latencies = [c["latency_ms"] for c in recent if c["success"]]
        avg_latency = round(sum(recent_latencies) / len(recent_latencies), 1) if recent_latencies else None

        fallback_rate = fallbacks / total if total > 0 else 0.0
        drift_points = list(self._drift_history[model_id])
        latest_drift = drift_points[-1][1] if drift_points else None

        if fallback_rate > 0.5:
            status = "degraded"
        elif latest_drift is not None and latest_drift > 0.7:
            status = "stale"
        elif recent_success == 0 and len(recent) > 0:
            status = "down"
        else:
            status = "healthy"

        return {
            "model_id": model_id,
            "status": status,
            "total_calls": total,
            "fallback_rate": round(fallback_rate, 3),
            "recent_fallbacks": recent_fallback,
            "avg_latency_ms": avg_latency,
            "latest_drift": round(latest_drift, 3) if latest_drift is not None else None,
            "drift_curve": [(round(ts, 0), round(d, 3)) for ts, d in drift_points[-10:]],
        }

    def get_model_health_dashboard(self) -> Dict[str, Any]:
        """Aggregate health for all tracked models."""
        all_models = set(self._calls.keys()) | set(self._total_counts.keys())
        models_health = {mid: self.get_model_health(mid) for mid in all_models}

        degraded = [m for m, h in models_health.items() if h["status"] in ("degraded", "down", "stale")]
        healthy = [m for m, h in models_health.items() if h["status"] == "healthy"]

        # Also pull retrain scheduler status
        scheduler_status = {}
        try:
            from agent_commercial.ml.retrain_scheduler import get_retrain_scheduler
            scheduler_status = get_retrain_scheduler().get_status()
        except Exception:
            pass

        return {
            "overall_status": "degraded" if degraded else "healthy",
            "models": models_health,
            "degraded_models": degraded,
            "healthy_models": healthy,
            "retrain_scheduler": scheduler_status,
        }

    def get_fallback_rate(self, model_id: str) -> float:
        total = self._total_counts[model_id]
        if total == 0:
            return 0.0
        return self._fallback_counts[model_id] / total


_observability_instance: Optional[MLObservability] = None


def get_ml_observability() -> MLObservability:
    global _observability_instance
    if _observability_instance is None:
        _observability_instance = MLObservability()
    return _observability_instance
