"""
ML Lineage Helpers
==================

Utilities for injecting model lineage metadata into ML tool handler results.
Called on the success path of each ML handler to populate _ml_lineage.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger("arvis.ml.lineage")

_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        try:
            from agent_commercial.ml.model_registry import ModelRegistry
            _registry = ModelRegistry()
        except Exception as e:
            logger.debug(f"ModelRegistry unavailable: {e}")
    return _registry


def get_active_model_version(model_name: str) -> Optional[str]:
    reg = _get_registry()
    if reg is None:
        return None
    try:
        return reg.get_active_version(model_name)
    except Exception:
        return None


def extract_confidence_bounds(result: Dict) -> Optional[Dict[str, float]]:
    """Extract lower/upper confidence bounds from common result key patterns."""
    for lower_key in ("lower_bound", "ci_lower", "confidence_lower", "p10"):
        for upper_key in ("upper_bound", "ci_upper", "confidence_upper", "p90"):
            if lower_key in result and upper_key in result:
                try:
                    return {"lower": float(result[lower_key]), "upper": float(result[upper_key])}
                except (TypeError, ValueError):
                    pass
    if "confidence_interval" in result:
        ci = result["confidence_interval"]
        if isinstance(ci, (list, tuple)) and len(ci) == 2:
            try:
                return {"lower": float(ci[0]), "upper": float(ci[1])}
            except (TypeError, ValueError):
                pass
    return None


def get_training_window(model_name: str) -> Optional[str]:
    reg = _get_registry()
    if reg is None:
        return None
    try:
        version = reg.get_active_version(model_name)
        if version is None:
            return None
        _, metadata = reg.load_model(model_name, version)
        return metadata.get("training_window") or metadata.get("trained_at")
    except Exception:
        return None


def build_ml_lineage(
    model_name: str,
    result: Dict,
    algorithm: Optional[str] = None,
) -> Dict:
    """Build the _ml_lineage dict for injection into a successful ML result."""
    return {
        "model_id": model_name,
        "model_version": get_active_model_version(model_name),
        "algorithm": algorithm or result.get("model_used"),
        "confidence_bounds": extract_confidence_bounds(result),
        "drift_score": result.get("drift_score"),
        "training_window": get_training_window(model_name),
    }
