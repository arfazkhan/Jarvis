"""
ML-Powered Tool Handlers
========================

Handlers for machine learning powered analytics tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.ml")


def _inject_lineage(result: Dict, model_name: str, algorithm: str = None) -> Dict:
    """Inject _ml_lineage into a successful ML result dict."""
    try:
        from agent_commercial.ml.lineage_helpers import build_ml_lineage
        result["_ml_lineage"] = build_ml_lineage(model_name, result, algorithm)
    except Exception as e:
        logger.debug(f"Lineage injection failed for {model_name}: {e}")
    return result


class MLHandlerMixin:
    """Mixin providing ML-powered tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "forecast_energy": instance._handle_forecast_energy,
            "detect_equipment_faults": instance._handle_detect_equipment_faults,
            "analyze_root_cause": instance._handle_analyze_root_cause,
            "simulate_with_uncertainty": instance._handle_simulate_with_uncertainty,
            "find_similar_skills": instance._handle_find_similar_skills,
            "benchmark_building_ml": instance._handle_benchmark_building_ml,
        }
    
    async def _handle_forecast_energy(self, args: Dict) -> Dict:
        """Forecast energy demand using ML ensemble"""
        forecast_hours = args.get("forecast_hours", 24)
        building_id = args.get("building_id")
        include_confidence = args.get("include_confidence", True)
        
        predictive_engine = getattr(self, "predictive_engine", None)
        if predictive_engine and hasattr(predictive_engine, "forecast_energy"):
            try:
                raw = await predictive_engine.forecast_energy(
                    hours=forecast_hours,
                    building_id=building_id,
                    include_confidence=include_confidence
                )
                return _inject_lineage(raw, "energy_forecaster", "prophet+lightgbm")
            except Exception as e:
                logger.error(f"Error forecasting energy demand: {e}")

        # M5.4: Try MLFacade as unified fallback before returning ML_UNAVAILABLE
        try:
            from arvis_core.ml_facade import get_ml_facade, MLCapability
            result = await get_ml_facade().execute(MLCapability.ENERGY_FORECAST, args)
            if not result.fallback:
                return result.to_dict()
        except Exception as _fe:
            logger.debug(f"MLFacade energy forecast failed: {_fe}")

        return {
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "confidence": None,
            "error": "no_data",
            "reason": "No energy baseline trained. Minimum 14 days of meter history required for forecasting.",
            "required_for_ml": ["predictive_engine", "energy_forecaster"],
        }
    
    async def _handle_detect_equipment_faults(self, args: Dict) -> Dict:
        """Use ML to detect equipment faults"""
        equipment_id = args.get("equipment_id")
        fault_type = args.get("fault_type")
        
        if not equipment_id:
            return {"error": "equipment_id is required"}
        
        predictive_engine = getattr(self, "predictive_engine", None)
        if predictive_engine and hasattr(predictive_engine, "detect_faults"):
            try:
                raw = await predictive_engine.detect_faults(
                    equipment_id=equipment_id,
                    fault_type=fault_type
                )
                return _inject_lineage(raw, "fdd_autoencoder", "vae+isolation_forest")
            except Exception as e:
                logger.error(f"Error detecting faults for {equipment_id}: {e}")
        
        return {
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "equipment_id": equipment_id,
            "faults_detected": [],
            "status": "unknown",
            "confidence": None,
            "reason": "VAE fault detection model not loaded. Cannot confirm equipment normality.",
            "required_for_ml": ["predictive_engine", "fdd_autoencoder"],
        }
    
    async def _handle_analyze_root_cause(self, args: Dict) -> Dict:
        """Use Bayesian Network for root cause analysis"""
        alarm_ids = args.get("alarm_ids", [])
        system_depth = args.get("system_depth", 3)
        
        if not alarm_ids:
            return {"error": "alarm_ids is required"}
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "analyze_root_cause"):
            try:
                raw = await world_model.analyze_root_cause(
                    alarm_ids=alarm_ids,
                    depth=system_depth
                )
                return _inject_lineage(raw, "bayesian_network", "pgmpy+dbn")
            except Exception as e:
                logger.error(f"Error in root cause analysis: {e}")
        
        return {
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "alarm_ids": alarm_ids,
            "root_causes": [],
            "cascade_prediction": None,
            "confidence": None,
            "reason": "Bayesian Network (pgmpy) not available. Cannot infer causal relationships.",
            "required_for_ml": ["world_model", "pgmpy"],
        }
    
    async def _handle_simulate_with_uncertainty(self, args: Dict) -> Dict:
        """Advanced simulation with uncertainty bounds"""
        change_type = args.get("change_type")
        current_value = args.get("current_value")
        proposed_value = args.get("proposed_value")
        equipment_id = args.get("equipment_id")
        zone_id = args.get("zone_id")
        monte_carlo_samples = args.get("monte_carlo_samples", 1000)
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "simulate_with_uncertainty"):
            try:
                raw = await world_model.simulate_with_uncertainty(
                    change_type=change_type,
                    current_value=current_value,
                    proposed_value=proposed_value,
                    equipment_id=equipment_id,
                    zone_id=zone_id,
                    samples=monte_carlo_samples
                )
                return _inject_lineage(raw, "building_physics_sim", "monte_carlo")
            except Exception as e:
                logger.error(f"Error in uncertainty simulation: {e}")
        
        if current_value is None or proposed_value is None:
            return {"error": "Both 'current_value' and 'proposed_value' are required for simulation"}

        return {
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "confidence": None,
            "error": "no_data",
            "reason": "Simulation model unavailable. Cannot estimate impact without calibrated building physics model.",
            "required_for_ml": ["world_model", "building_physics"],
        }
    
    async def _handle_find_similar_skills(self, args: Dict) -> Dict:
        """Find similar skills via MemoryOrchestrator (T5), with semantic embeddings fallback.

        Always returns canonical schema: skills, total_matches, query_embedding_used.
        Error paths back-fill the keys to satisfy downstream schema validators (B11 fix).
        """
        query = args.get("query")
        top_k = args.get("top_k", 5)
        equipment_type = args.get("equipment_type")

        if not query:
            # B11: return canonical schema even on validation error
            return {
                "skills": [],
                "total_matches": 0,
                "query_embedding_used": False,
                "error": "query is required",
            }

        def _normalize_skills_response(raw_results, used_embedding: bool, model_name: str):
            """Normalize any results list to schema-compliant response."""
            skills = []
            for r in raw_results:
                skills.append({
                    "skill_id": r.get("skill_id", r.get("id", "")),
                    "title": r.get("title", r.get("content", "")[:80]),
                    "skill_type": r.get("skill_type", r.get("source", "operational")),
                    "similarity_score": r.get("score", r.get("similarity_score", 0.0)),
                    "description": r.get("description", r.get("content", "")),
                })
            return {
                "skills": skills,
                "total_matches": len(skills),
                "query_embedding_used": used_embedding,
            }

        # Mem-8: Primary path — MemoryOrchestrator T5 (institutional)
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                from arvis_core.memory.types import MemoryTier
                hits = await _mo.query(
                    query=query,
                    tiers=[MemoryTier.T5_INSTITUTIONAL],
                    top_k=top_k,
                )
                if hits:
                    raw_results = [
                        {"skill_id": h.id, "score": h.confidence, "content": h.content,
                         "source": h.source, "equipment_type": equipment_type}
                        for h in hits
                    ]
                    result = _normalize_skills_response(raw_results, True, "MemoryOrchestrator:T5")
                    return _inject_lineage(result, "semantic_skill_matcher", "orchestrator_t5")
            except Exception as e:
                logger.debug(f"find_similar_skills via orchestrator failed: {e}")

        knowledge_base = getattr(self, "knowledge_base", None)
        if knowledge_base and hasattr(knowledge_base, "find_similar_skills"):
            try:
                raw = await knowledge_base.find_similar_skills(
                    query=query, top_k=top_k, equipment_type=equipment_type
                )
                if isinstance(raw, dict) and "results" in raw:
                    result = _normalize_skills_response(raw["results"], True, "sentence-transformers")
                elif isinstance(raw, list):
                    result = _normalize_skills_response(raw, True, "sentence-transformers")
                else:
                    result = _normalize_skills_response([], True, "sentence-transformers")
                return _inject_lineage(result, "semantic_skill_matcher", "sentence-transformers")
            except Exception as e:
                logger.error(f"Error finding similar skills: {e}")

        try:
            from agent_commercial.ml.building_embeddings import SemanticSkillMatcher
            _matcher = SemanticSkillMatcher()
            _matcher.load_model()
            _results = _matcher.find_similar(query=query, top_k=top_k)
            raw_results = [{"skill_id": sid, "score": float(score)} for sid, score in _results]
            result = _normalize_skills_response(raw_results, True, "SemanticSkillMatcher")
            return _inject_lineage(result, "semantic_skill_matcher", "sentence-transformers")
        except Exception as _e:
            logger.debug(f"SemanticSkillMatcher fallback failed: {_e}")

        # ── Fix #2: Local Skillbook fallback ─────────────────────────────
        # Same gap as query_skillbook handler — observation distiller writes
        # to local Skillbook SQLite table that none of the above paths read.
        # Query it directly as last resort so P1-distilled skills surface in
        # P4+ queries instead of returning empty.
        try:
            from agent_commercial.skillbook import get_skillbook
            _sb = get_skillbook("default")
            await _sb.ensure_initialized()
            _ctx: Dict[str, Any] = {"situation_query": query, "query": query,
                                    "similarity_threshold": 0.2}
            if equipment_type:
                _ctx["equipment_type"] = equipment_type
            _skills = await _sb.get_relevant_skills(_ctx, limit=top_k)
            raw_results = []
            for _s in _skills:
                _sd = _s.to_dict()
                raw_results.append({
                    "skill_id": _sd.get("skill_id", ""),
                    "title": _sd.get("title", ""),
                    "skill_type": _sd.get("skill_type", "pattern"),
                    "score": float(_sd.get("confidence", 0.5)),
                    "description": _sd.get("description", ""),
                })
            if raw_results:
                logger.info(
                    f"[ML] find_similar_skills local-skillbook fallback returned "
                    f"{len(raw_results)} skill(s) for query={query[:60]!r}"
                )
            result = _normalize_skills_response(raw_results, True, "local_skillbook_fallback")
            return _inject_lineage(result, "semantic_skill_matcher", "local_skillbook")
        except Exception as _sb_err:
            logger.warning(f"Local skillbook fallback failed: {_sb_err}")

        return {
            "skills": [],
            "total_matches": 0,
            "query_embedding_used": False,
        }
    
    async def _handle_benchmark_building_ml(self, args: Dict) -> Dict:
        """Benchmark building using ML clustering"""
        building_id = args.get("building_id")
        comparison_scope = args.get("comparison_scope", "local_fleet")
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "benchmark_building"):
            try:
                raw = await world_model.benchmark_building(
                    building_id=building_id,
                    scope=comparison_scope
                )
                return _inject_lineage(raw, "building_embeddings", "kmeans+cosine")
            except Exception as e:
                logger.error(f"Error in building benchmarking: {e}")
        
        try:
            from agent_commercial.ml.building_embeddings import BuildingArchetypeClassifier
            _classifier = BuildingArchetypeClassifier()
            _features = args.get("building_features", {})
            if _features:
                _result = _classifier.classify(_features)
                raw = {**_result, "building_id": building_id, "scope": comparison_scope}
                return _inject_lineage(raw, "building_embeddings", "kmeans+cosine")
        except Exception as _e:
            logger.debug(f"BuildingArchetypeClassifier fallback failed: {_e}")

        return {
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "confidence": None,
            "error": "no_data",
            "reason": "Fleet benchmark data unavailable. No portfolio comparison possible without multi-building data.",
            "required_for_ml": ["world_model", "building_embeddings"],
        }
