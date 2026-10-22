"""
ML-Powered Tool Handlers
========================

Handlers for machine learning powered analytics tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.ml")


def _inject_lineage(result: Dict, model_name: str, algorithm: str = None) -> Dict:
    """Inject _ml_lineage into an ML result dict.

    Guarantees the `_ml_lineage` key is always present (schema requires it on
    every ML tool). On builder failure, falls back to a minimal lineage stub so
    output-schema validation never reports a missing key.
    """
    if not isinstance(result, dict):
        return result
    try:
        from agent_commercial.ml.lineage_helpers import build_ml_lineage
        result["_ml_lineage"] = build_ml_lineage(model_name, result, algorithm)
    except Exception as e:
        logger.debug(f"Lineage injection failed for {model_name}: {e}")
    # Guarantee key presence even if builder raised or returned falsy
    if not result.get("_ml_lineage"):
        result["_ml_lineage"] = {
            "model_id": model_name,
            "algorithm": algorithm,
            "available": result.get("ml_status") != "unavailable",
        }
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
        """Detect equipment faults with the rule-based FDD engine (ASHRAE G36
        rules, see agent_commercial/fdd) over the equipment's stored telemetry.

        Canonical response schema (always present):
          faults / faults_detected : confirmed faults (each an FDD finding)
          health_score : float | None — share of judged rules that passed (0–100);
                         None when no rule could be judged
          confidence   : None — rules are deterministic; each finding carries its
                         own evidence (points used, fault hours, window)
          equipment_id : str
          status       : fault | normal | unknown
        """
        equipment_id = args.get("equipment_id")
        fault_type = (args.get("fault_type") or "").lower()

        if not equipment_id:
            return {
                "error": "equipment_id is required",
                # Schema keys still present so callers never see KeyError
                "faults": [], "faults_detected": [],
                "health_score": None,
                "confidence": None,
                "equipment_id": None,
            }

        bms_state = getattr(self, "bms_state", None)
        if bms_state is not None:
            try:
                return _inject_lineage(
                    await self._run_rule_fdd(bms_state, equipment_id, fault_type, args),
                    "arvis_rule_fdd", "ashrae_g36_rules")
            except Exception as e:
                logger.error(f"Rule-based FDD failed for {equipment_id}: {e}")

        # Guaranteed-schema fallback — no repair needed downstream
        return _inject_lineage({
            "faults": [], "faults_detected": [],
            "health_score": None,
            "confidence": None,
            "equipment_id": equipment_id,
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "status": "unknown",
            "reason": "Rule-based FDD unavailable (no BMS state / telemetry store). "
                      "Cannot confirm equipment normality.",
            "required_for_ml": ["bms_state", "telemetry history"],
        }, "arvis_rule_fdd", "ashrae_g36_rules")

    async def _run_rule_fdd(self, bms_state, equipment_id: str, fault_type: str, args: Dict) -> Dict:
        from agent_commercial.database import get_database
        from agent_commercial.fdd import FDDEngine, Outcome
        from agent_commercial.fdd.store import save_findings

        hours = float(args.get("hours", 24))
        engine = FDDEngine(poll_seconds=float(args.get("resample_seconds", 300)))
        db = get_database()
        findings = await engine.run_building(bms_state, db, hours=hours, equipment_ids=[equipment_id])
        findings = [f for f in findings if f.equipment_id == equipment_id]
        cases = {}
        if findings:
            await save_findings(db, findings)
            from agent_commercial.fdd.diagnosis import process_findings
            eq = None
            try:
                eq = await bms_state.get_equipment(equipment_id)
            except Exception:
                eq = None
            parent = getattr(eq, "parent_equipment_id", None)
            touched = await process_findings(
                db, findings, parents={equipment_id: parent} if parent else {},
                designs={equipment_id: dict(getattr(eq, "design_attributes", None) or {})})
            cases = {c.rule_id: c for c in touched}

        def _match(f) -> bool:
            if not fault_type:
                return True
            text = f"{f.rule_id} {f.title} {f.family} {f.summary}".lower()
            return fault_type in text

        def _compact(f) -> Dict[str, Any]:
            case = cases.get(f.rule_id)
            diag = (case.diagnosis if case else {}) or {}
            return {"rule_id": f.rule_id, "fault_type": f.title, "family": f.family,
                    "summary": f.summary, "headline": f.headline(),
                    "fault_hours": f.fault_hours, "fault_pct": f.fault_pct,
                    "first_fault": f.first_fault, "last_fault": f.last_fault,
                    "points_used": f.points_used, "role_sources": f.role_sources,
                    "impact": f.impact, "scores": f.scores,
                    "root_cause_candidates": f.root_cause_candidates,
                    "diagnosis": {
                        "case_id": case.id if case else None,
                        "case_status": case.status if case else None,
                        "suppressed_by_case": case.suppressed_by if case else None,
                        "ranked_causes": (diag.get("posterior") or [])[:4],
                        "answered_from_data": {k: v for k, v in (case.answers if case else {}).items()
                                               if (case.answer_sources.get(k, "")).startswith("auto")},
                        "next_question_for_operator": diag.get("next_question"),
                        "kb_bust": diag.get("kb_bust", False),
                    },
                    "source_tool": f.source_tool, "origin": f.origin}

        fails = [f for f in findings if f.outcome is Outcome.FAIL and _match(f)]
        passed = [f for f in findings if f.outcome is Outcome.PASS]
        judged = len(passed) + len([f for f in findings if f.outcome is Outcome.FAIL])
        not_judged = [{"rule_id": f.rule_id, "outcome": f.outcome.value, "reason": f.reason}
                      for f in findings if f.outcome in (Outcome.SKIP, Outcome.INVALID)]
        faults = [_compact(f) for f in fails]
        if not findings:
            status = "unknown"
            reason = f"No stored telemetry for {equipment_id} in the last {hours:g} h."
        elif fails:
            status, reason = "fault", ""
        elif judged:
            status, reason = "normal", ""
        else:
            status, reason = "unknown", "No rule could be judged (see not_evaluated)."
        return {
            "equipment_id": equipment_id, "status": status, "reason": reason,
            "faults": faults, "faults_detected": faults,
            "health_score": round(100.0 * len(passed) / judged, 1) if judged else None,
            "confidence": None,
            "rules_passed": [f.rule_id for f in passed],
            "rules_failed": [f.rule_id for f in fails],
            "not_evaluated": not_judged,
            "invalid_sensors": sorted({r for f in findings for r in f.invalid_roles
                                       if f.family == "sensor"}),
            "window_hours": hours,
            "method": "rule-based FDD — ASHRAE Guideline 36 rules (open-fdd port) + ARVIS Gulf rules",
        }
    
    async def _handle_analyze_root_cause(self, args: Dict) -> Dict:
        """Use Bayesian Network for root cause analysis"""
        alarm_ids = args.get("alarm_ids", [])
        system_depth = args.get("system_depth", 3)
        
        if not alarm_ids:
            return {
                "error": "alarm_ids is required",
                "root_causes": [],
                "top_root_cause": None,
                "confidence": None,
                "cascade_prediction": [],
                "_ml_lineage": {"model_id": "bayesian_network", "available": False},
            }

        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "analyze_root_cause"):
            try:
                raw = await world_model.analyze_root_cause(
                    alarm_ids=alarm_ids,
                    depth=system_depth
                )
                if isinstance(raw, dict):
                    # Derive top_root_cause from root_causes list if engine omitted it
                    if not raw.get("top_root_cause"):
                        rcs = raw.get("root_causes") or []
                        if rcs and isinstance(rcs[0], dict):
                            raw["top_root_cause"] = rcs[0].get("equipment_id")
                        else:
                            raw["top_root_cause"] = None
                    raw.setdefault("root_causes", [])
                    raw.setdefault("cascade_prediction", [])
                    raw.setdefault("confidence", None)
                return _inject_lineage(raw, "bayesian_network", "pgmpy+dbn")
            except Exception as e:
                logger.error(f"Error in root cause analysis: {e}")

        return _inject_lineage({
            "ml_status": "unavailable",
            "fallback": True,
            "model_id": None,
            "alarm_ids": alarm_ids,
            "root_causes": [],
            "top_root_cause": None,
            "cascade_prediction": [],
            "confidence": None,
            "reason": "Bayesian Network (pgmpy) not available. Cannot infer causal relationships.",
            "required_for_ml": ["world_model", "pgmpy"],
        }, "bayesian_network", "pgmpy+dbn")
    
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

        # Equipment-scope: a skill learned on AHU-07 must not surface for a
        # chiller or a DIFFERENT AHU. Semantic recall over-triggers across
        # equipment; drop any skill that names an equipment id absent from the
        # query's target set. Equipment-agnostic skills (no id) are kept.
        import re as _re
        _equip_re = _re.compile(r'\b(?:CH|AHU|VAV|FCU|MTR|CHILLER|PUMP|CT)\b[-_\s]?\d+', _re.IGNORECASE)

        def _eqset(text):
            return {_re.sub(r'[-_\s]', '', m).upper().replace("CHILLER", "CH") for m in _equip_re.findall(text or "")}

        _q_equip = _eqset(query)

        def _normalize_skills_response(raw_results, used_embedding: bool, model_name: str):
            """Normalize any results list to schema-compliant response."""
            skills = []
            _dropped = 0
            for r in raw_results:
                _title = r.get("title", r.get("content", "")[:80])
                _desc = r.get("description", r.get("content", ""))
                if _q_equip:
                    _skill_eq = _eqset(_title) | _eqset(_desc)
                    _meta_eq = r.get("equipment_id")
                    if _meta_eq:
                        _skill_eq |= _eqset(str(_meta_eq))
                    if _skill_eq and not (_skill_eq & _q_equip):
                        _dropped += 1
                        continue  # names a different unit → off-scope, drop
                skills.append({
                    "skill_id": r.get("skill_id", r.get("id", "")),
                    "title": _title,
                    "skill_type": r.get("skill_type", r.get("source", "operational")),
                    "similarity_score": r.get("score", r.get("similarity_score", 0.0)),
                    "description": _desc,
                })
            if _dropped:
                logger.info(f"[ML] find_similar_skills equipment-scope: dropped {_dropped} off-equipment skill(s)")
            out = {
                "skills": skills,
                "total_matches": len(skills),
                "query_embedding_used": used_embedding,
            }
            if _dropped:
                out["dropped_off_scope"] = _dropped
            return out

        async def _explained(result: Dict) -> Dict:
            """An empty result says WHY it is empty, so the reflector can tell
            'no past experience' from 'the search missed it'."""
            if not result.get("skills"):
                from agent_commercial.tools.handlers.sovereign import explain_empty_retrieval
                result["retrieval"] = await explain_empty_retrieval(
                    query, dropped_off_scope=result.get("dropped_off_scope", 0))
            return result

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
                         "source": h.source, "equipment_type": equipment_type,
                         # surface equipment_id from metadata so the scope filter
                         # can drop off-equipment skills whose CONTENT omits the id
                         "equipment_id": (h.metadata or {}).get("equipment_id") if hasattr(h, "metadata") else None}
                        for h in hits
                    ]
                    result = _normalize_skills_response(raw_results, True, "MemoryOrchestrator:T5")
                    return _inject_lineage(await _explained(result), "semantic_skill_matcher", "orchestrator_t5")
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
                return _inject_lineage(await _explained(result), "semantic_skill_matcher", "sentence-transformers")
            except Exception as e:
                logger.error(f"Error finding similar skills: {e}")

        try:
            from agent_commercial.ml.building_embeddings import SemanticSkillMatcher
            _matcher = SemanticSkillMatcher()
            _matcher.load_model()
            _results = _matcher.find_similar(query=query, top_k=top_k)
            raw_results = [{"skill_id": sid, "score": float(score)} for sid, score in _results]
            result = _normalize_skills_response(raw_results, True, "SemanticSkillMatcher")
            return _inject_lineage(await _explained(result), "semantic_skill_matcher", "sentence-transformers")
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
                    "equipment_id": _sd.get("equipment_id"),
                })
            if raw_results:
                logger.info(
                    f"[ML] find_similar_skills local-skillbook fallback returned "
                    f"{len(raw_results)} skill(s) for query={query[:60]!r}"
                )
            result = _normalize_skills_response(raw_results, True, "local_skillbook_fallback")
            return _inject_lineage(await _explained(result), "semantic_skill_matcher", "local_skillbook")
        except Exception as _sb_err:
            logger.warning(f"Local skillbook fallback failed: {_sb_err}")

        return await _explained({
            "skills": [],
            "total_matches": 0,
            "query_embedding_used": False,
        })
    
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
