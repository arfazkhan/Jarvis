"""
ML Facade
=========

Unified entry point for all ARVIS ML capabilities.
Routes to correct backend (commercial/ml, cognitive/prediction_engine, advisory/ml_models).
Wraps results with lineage. Records drift into RetrainScheduler.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("arvis.ml_facade")


class MLCapability(str, Enum):
    ENERGY_FORECAST = "energy_forecast"
    FAULT_DETECTION = "fault_detection"
    ROOT_CAUSE = "root_cause"
    UNCERTAINTY_SIM = "uncertainty_sim"
    SKILL_SEARCH = "skill_search"
    BUILDING_BENCHMARK = "building_benchmark"
    DRIFT_REPORT = "drift_report"
    OUTCOME_PREDICT = "outcome_predict"
    PREFERENCE_RANK = "preference_rank"


@dataclass
class MLResult:
    capability: str
    payload: Dict[str, Any]
    fallback: bool = False
    lineage: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"capability": self.capability, "fallback": self.fallback, **self.payload}
        if self.lineage:
            d["_ml_lineage"] = self.lineage
        if self.error:
            d["error"] = self.error
        return d


class MLFacade:
    """
    Single entry point to all ML capabilities.
    Callers never reach into individual ML modules directly.
    """

    def __init__(self):
        self._predictive_engine = None
        self._world_model = None
        self._knowledge_base = None

    # ── Lazy engine accessors ─────────────────────────────────────────────────

    def _get_predictive_engine(self):
        if self._predictive_engine is None:
            try:
                from agent_commercial.bms_llm_agent import get_agent_instance
                agent = get_agent_instance()
                self._predictive_engine = getattr(agent, "predictive_engine", None)
            except Exception:
                pass
        return self._predictive_engine

    def _get_world_model(self):
        if self._world_model is None:
            try:
                from agent_commercial.bms_llm_agent import get_agent_instance
                agent = get_agent_instance()
                self._world_model = getattr(agent, "world_model", None)
            except Exception:
                pass
        return self._world_model

    # ── Main dispatch ─────────────────────────────────────────────────────────

    async def execute(self, capability: MLCapability, params: Dict[str, Any]) -> MLResult:
        """Route to correct backend, wrap result with lineage, record drift."""
        try:
            if capability == MLCapability.ENERGY_FORECAST:
                return await self._energy_forecast(params)
            elif capability == MLCapability.FAULT_DETECTION:
                return await self._fault_detection(params)
            elif capability == MLCapability.ROOT_CAUSE:
                return await self._root_cause(params)
            elif capability == MLCapability.UNCERTAINTY_SIM:
                return await self._uncertainty_sim(params)
            elif capability == MLCapability.SKILL_SEARCH:
                return await self._skill_search(params)
            elif capability == MLCapability.BUILDING_BENCHMARK:
                return await self._building_benchmark(params)
            elif capability == MLCapability.DRIFT_REPORT:
                return await self._drift_report(params)
            elif capability == MLCapability.OUTCOME_PREDICT:
                return await self._outcome_predict(params)
            elif capability == MLCapability.PREFERENCE_RANK:
                return await self._preference_rank(params)
            else:
                return MLResult(capability=capability, payload={}, fallback=True, error=f"Unknown capability: {capability}")
        except Exception as e:
            logger.error(f"[MLFacade] {capability} failed: {e}")
            return MLResult(capability=capability, payload={}, fallback=True, error=str(e))

    # ── Capability implementations ────────────────────────────────────────────

    async def _energy_forecast(self, params: Dict) -> MLResult:
        engine = self._get_predictive_engine()
        if engine and hasattr(engine, "forecast_energy"):
            raw = await engine.forecast_energy(
                hours=params.get("forecast_hours", 24),
                building_id=params.get("building_id"),
                include_confidence=params.get("include_confidence", True),
            )
            lineage = self._build_lineage("energy_forecaster", raw, "prophet+lightgbm")
            return MLResult(capability=MLCapability.ENERGY_FORECAST, payload=raw, lineage=lineage)
        return MLResult(capability=MLCapability.ENERGY_FORECAST, payload={}, fallback=True,
                        error="predictive_engine unavailable")

    async def _fault_detection(self, params: Dict) -> MLResult:
        engine = self._get_predictive_engine()
        if engine and hasattr(engine, "detect_faults"):
            raw = await engine.detect_faults(
                equipment_id=params.get("equipment_id"),
                fault_type=params.get("fault_type"),
            )
            lineage = self._build_lineage("fdd_autoencoder", raw, "vae+isolation_forest")
            return MLResult(capability=MLCapability.FAULT_DETECTION, payload=raw, lineage=lineage)
        # Direct FDD fallback
        try:
            from agent_commercial.ml.fdd_autoencoder import get_fdd_engine
            fdd = get_fdd_engine()
            equipment_id = params.get("equipment_id", "unknown")
            raw = fdd.detect(equipment_id=equipment_id, sensor_data=params.get("sensor_data", {}))
            lineage = self._build_lineage("fdd_autoencoder", raw if isinstance(raw, dict) else {}, "pytorch_vae")
            return MLResult(capability=MLCapability.FAULT_DETECTION,
                            payload=raw if isinstance(raw, dict) else {"result": raw}, lineage=lineage)
        except Exception as e:
            logger.debug(f"[MLFacade] FDD direct fallback failed: {e}")
        return MLResult(capability=MLCapability.FAULT_DETECTION, payload={}, fallback=True,
                        error="fdd_autoencoder unavailable")

    async def _root_cause(self, params: Dict) -> MLResult:
        world_model = self._get_world_model()
        if world_model and hasattr(world_model, "analyze_root_cause"):
            raw = await world_model.analyze_root_cause(
                alarm_ids=params.get("alarm_ids", []),
                depth=params.get("system_depth", 3),
            )
            lineage = self._build_lineage("bayesian_network", raw, "pgmpy+dbn")
            return MLResult(capability=MLCapability.ROOT_CAUSE, payload=raw, lineage=lineage)
        return MLResult(capability=MLCapability.ROOT_CAUSE, payload={}, fallback=True,
                        error="bayesian_network unavailable")

    async def _uncertainty_sim(self, params: Dict) -> MLResult:
        world_model = self._get_world_model()
        if world_model and hasattr(world_model, "simulate_with_uncertainty"):
            raw = await world_model.simulate_with_uncertainty(**params)
            lineage = self._build_lineage("building_physics_sim", raw, "monte_carlo")
            return MLResult(capability=MLCapability.UNCERTAINTY_SIM, payload=raw, lineage=lineage)
        return MLResult(capability=MLCapability.UNCERTAINTY_SIM, payload={}, fallback=True,
                        error="world_model unavailable")

    async def _skill_search(self, params: Dict) -> MLResult:
        try:
            from agent_commercial.ml.building_embeddings import SemanticSkillMatcher
            matcher = SemanticSkillMatcher()
            matcher.load_model()
            results = matcher.find_similar(query=params.get("query", ""), top_k=params.get("top_k", 5))
            raw = {"results": [{"skill_id": sid, "score": float(s)} for sid, s in results], "query": params.get("query")}
            lineage = self._build_lineage("semantic_skill_matcher", raw, "sentence-transformers")
            return MLResult(capability=MLCapability.SKILL_SEARCH, payload=raw, lineage=lineage)
        except Exception as e:
            return MLResult(capability=MLCapability.SKILL_SEARCH, payload={}, fallback=True, error=str(e))

    async def _building_benchmark(self, params: Dict) -> MLResult:
        try:
            from agent_commercial.ml.building_embeddings import BuildingArchetypeClassifier
            classifier = BuildingArchetypeClassifier()
            features = params.get("building_features", {})
            raw = classifier.classify(features) if features else {}
            lineage = self._build_lineage("building_embeddings", raw, "kmeans+cosine")
            return MLResult(capability=MLCapability.BUILDING_BENCHMARK, payload=raw, lineage=lineage)
        except Exception as e:
            return MLResult(capability=MLCapability.BUILDING_BENCHMARK, payload={}, fallback=True, error=str(e))

    async def _drift_report(self, params: Dict) -> MLResult:
        try:
            from agent_cognitive.prediction_engine import PredictionEngine
            building_id = params.get("building_id", "default")
            engine = PredictionEngine(building_id=building_id)
            report = await engine.compute_drift(time_window_hours=params.get("window_hours", 24))
            return MLResult(capability=MLCapability.DRIFT_REPORT, payload=report.to_dict(),
                            lineage={"model_id": report.model_id})
        except Exception as e:
            return MLResult(capability=MLCapability.DRIFT_REPORT, payload={}, fallback=True, error=str(e))

    async def _outcome_predict(self, params: Dict) -> MLResult:
        try:
            from agent_advisory.ml_models.outcome_predictor import OutcomePredictor
            predictor = OutcomePredictor()
            predictor.load()
            raw = predictor.predict(params.get("features", {}))
            return MLResult(capability=MLCapability.OUTCOME_PREDICT,
                            payload=raw if isinstance(raw, dict) else {"prediction": raw},
                            lineage={"model_id": "outcome_predictor"})
        except Exception as e:
            return MLResult(capability=MLCapability.OUTCOME_PREDICT, payload={}, fallback=True, error=str(e))

    async def _preference_rank(self, params: Dict) -> MLResult:
        try:
            from agent_advisory.ml_models.preference_ranker import PreferenceRankingModel
            ranker = PreferenceRankingModel()
            ranker.load()
            candidates = params.get("candidates", [])
            raw = ranker.rank(candidates, params.get("context", {}))
            return MLResult(capability=MLCapability.PREFERENCE_RANK,
                            payload=raw if isinstance(raw, dict) else {"ranked": raw},
                            lineage={"model_id": "preference_ranker"})
        except Exception as e:
            return MLResult(capability=MLCapability.PREFERENCE_RANK, payload={}, fallback=True, error=str(e))

    # ── Lineage builder ───────────────────────────────────────────────────────

    def _build_lineage(self, model_name: str, result: Dict, algorithm: str) -> Dict:
        try:
            from agent_commercial.ml.lineage_helpers import build_ml_lineage
            return build_ml_lineage(model_name, result, algorithm)
        except Exception:
            return {"model_id": model_name, "algorithm": algorithm}

    # ── Health dashboard ──────────────────────────────────────────────────────

    def get_health(self) -> Dict[str, Any]:
        """Per-capability health check. Lightweight — no model loading."""
        health = {}
        checks = {
            "energy_forecaster": ("agent_commercial.ml.energy_forecaster", "get_energy_forecaster"),
            "fdd_autoencoder": ("agent_commercial.ml.fdd_autoencoder", "get_fdd_engine"),
            "retrain_scheduler": ("agent_commercial.ml.retrain_scheduler", "get_retrain_scheduler"),
            "model_registry": ("agent_commercial.ml.model_registry", "get_model_registry"),
        }
        for name, (module, fn) in checks.items():
            try:
                import importlib
                mod = importlib.import_module(module)
                getattr(mod, fn)()
                health[name] = "ok"
            except Exception as e:
                health[name] = f"unavailable: {e}"

        try:
            from agent_commercial.ml.retrain_scheduler import get_retrain_scheduler
            health["retrain_scheduler_status"] = get_retrain_scheduler().get_status()
        except Exception:
            pass

        return health


_facade_instance: Optional[MLFacade] = None


def get_ml_facade() -> MLFacade:
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = MLFacade()
    return _facade_instance
