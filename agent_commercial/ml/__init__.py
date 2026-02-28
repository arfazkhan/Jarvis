"""
ARVIS ML Module
===============

Advanced Machine Learning components for ARVIS Ops Copilot.

Modules:
- energy_forecaster: Prophet + LightGBM for demand prediction
- fdd_autoencoder: Deep learning fault detection
- causal_inference: Bayesian networks for event correlation
- building_embeddings: Semantic skill matching
- building_archetypes: K-Means fleet clustering
"""

from typing import Optional

# Lazy imports to avoid loading heavy ML libraries until needed
_energy_forecaster = None
_fdd_autoencoder = None
_causal_engine = None


def get_energy_forecaster():
    """Get or create energy forecaster singleton."""
    global _energy_forecaster
    if _energy_forecaster is None:
        from agent_commercial.ml.energy_forecaster import EnergyForecaster
        _energy_forecaster = EnergyForecaster()
    return _energy_forecaster


def get_fdd_autoencoder():
    """Get or create FDD autoencoder singleton."""
    global _fdd_autoencoder
    if _fdd_autoencoder is None:
        from agent_commercial.ml.fdd_autoencoder import FDDAutoencoder
        _fdd_autoencoder = FDDAutoencoder()
    return _fdd_autoencoder


def get_causal_engine():
    """Get or create causal inference engine singleton."""
    global _causal_engine
    if _causal_engine is None:
        from agent_commercial.ml.causal_inference import CausalInferenceEngine
        _causal_engine = CausalInferenceEngine()
    return _causal_engine
