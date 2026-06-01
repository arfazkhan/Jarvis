"""
Sovereign Cognition Tool Handlers
=================================

Handlers for sovereign cognition layer tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.sovereign")


class SovereignHandlerMixin:
    """Mixin providing sovereign cognition tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "query_skillbook": instance._handle_query_skillbook,
            "add_to_skillbook": instance._handle_add_to_skillbook,
            "compare_to_fleet": instance._handle_compare_to_fleet,
            "simulate_change": instance._handle_simulate_change,
            "correlate_events": instance._handle_correlate_events,
            "replay_investigation": instance._handle_replay_investigation,
        }
    

    
    async def _handle_query_skillbook(self, args: Dict) -> Dict:
        """Query the building's institutional memory via MemoryOrchestrator (T5)."""
        query = args.get("query")
        equipment_id = args.get("equipment_id")
        skill_type = args.get("skill_type")
        limit = args.get("limit", 5)

        if not query:
            return {"error": "query is required"}

        results = []

        # Mem-8: Primary path — MemoryOrchestrator T5 (institutional)
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                from arvis_core.memory.types import MemoryTier
                hits = await _mo.query(
                    query=query,
                    tiers=[MemoryTier.T5_INSTITUTIONAL],
                    top_k=limit,
                )
                for h in hits:
                    results.append({
                        "chunk_id": h.id,
                        "title": h.source,
                        "content": h.content,
                        "equipment_id": h.metadata.get("equipment_id"),
                        "skill_type": h.metadata.get("skill_type", skill_type or "pattern"),
                        "relevance": h.confidence,
                    })
            except Exception as e:
                logger.debug(f"query_skillbook via orchestrator failed: {e}")

        # Fallback: direct knowledge_base access if orchestrator not wired
        if not results:
            knowledge_base = getattr(self, "knowledge_base", None)
            if knowledge_base and hasattr(knowledge_base, "query_specs"):
                try:
                    manual_types = None
                    if skill_type:
                        _type_map = {
                            "pattern": "operator_pattern",
                            "fault_pattern": "operator_pattern",
                            "quirk": "operator_pattern",
                            "maintenance": "operator_pattern",
                            "optimization": "specs",
                            "contractor": "operator_pattern",
                        }
                        manual_types = [_type_map.get(skill_type, skill_type)]
                    raw = await knowledge_base.query_specs(
                        query=query,
                        equipment_id=equipment_id,
                        manual_types=manual_types,
                        limit=limit,
                    )
                    for r in raw:
                        relevance = 1.0 - float(r.get("distance", 0.5))
                        chunk_id = r.get("id", r.get("metadata", {}).get("id", ""))
                        results.append({
                            "chunk_id": chunk_id,
                            "title": r.get("metadata", {}).get("source", "Operator Pattern"),
                            "content": r.get("content", ""),
                            "equipment_id": r.get("metadata", {}).get("equipment_id"),
                            "skill_type": r.get("metadata", {}).get("manual_type", "pattern"),
                            "relevance": relevance,
                        })
                except Exception as e:
                    logger.error(f"query_skillbook via query_specs failed: {e}")

            if not results and knowledge_base and hasattr(knowledge_base, "query_skillbook"):
                try:
                    return await knowledge_base.query_skillbook(
                        query=query, equipment_id=equipment_id,
                        skill_type=skill_type, limit=limit,
                    )
                except Exception as e:
                    logger.error(f"query_skillbook native method failed: {e}")

        # ── Fix #2: Local Skillbook fallback ─────────────────────────────
        # The observation distiller writes skills directly into the
        # agent_commercial.skillbook.Skillbook SQLite table (via
        # skillbook.add_skill). NEITHER the MemoryOrchestrator T5 path NOR
        # the knowledge_base.query_specs path queries that table — they look
        # in different stores. Result: P1 wrote 6 skills, P4 got 0 matches.
        # This direct path closes the write→read gap.
        if not results:
            try:
                from agent_commercial.skillbook import get_skillbook
                _sb = get_skillbook("default")
                await _sb.ensure_initialized()
                _ctx: Dict[str, Any] = {}
                if query:
                    _ctx["situation_query"] = query
                    _ctx["query"] = query
                if equipment_id:
                    _ctx["equipment_id"] = equipment_id
                if skill_type:
                    _ctx["skill_type"] = skill_type
                # Lower similarity threshold so distiller-written skills surface
                _ctx["similarity_threshold"] = 0.2
                _skills = await _sb.get_relevant_skills(_ctx, limit=limit)
                for _s in _skills:
                    _sd = _s.to_dict()
                    results.append({
                        "chunk_id": _sd.get("skill_id", ""),
                        "title": _sd.get("title", ""),
                        "content": _sd.get("description", ""),
                        "equipment_id": _sd.get("equipment_id"),
                        "skill_type": _sd.get("skill_type", "pattern"),
                        "relevance": float(_sd.get("confidence", 0.5)),
                    })
                if results:
                    logger.info(
                        f"[Sovereign] Local skillbook fallback returned {len(results)} skill(s) "
                        f"for query={query[:60]!r}"
                    )
            except Exception as _sb_err:
                logger.warning(f"Local skillbook fallback failed: {_sb_err}")

        # Fallback: search in tracker
        if not results:
            tracker = getattr(self, "tracker", None)
            if tracker and hasattr(tracker, "search_skills"):
                try:
                    return await tracker.search_skills(query, limit=limit)
                except Exception as e:
                    logger.error(f"Error searching skills in tracker: {e}")

        if not results:
            return {
                "query": query,
                "skills": [],
                "summary": {"total": 0, "note": "No matching patterns found in institutional memory"},
            }

        # Equipment-scope: drop institutional skills that name a DIFFERENT unit
        # than the one under investigation (a learned AHU-07 fault must not
        # surface for a chiller or another AHU). Equipment-agnostic skills kept.
        try:
            import re as _re
            _eqre = _re.compile(r'\b(?:CH|AHU|VAV|FCU|MTR|CHILLER|PUMP|CT)\b[-_\s]?\d+', _re.IGNORECASE)

            def _eqset(t):
                return {_re.sub(r'[-_\s]', '', m).upper().replace("CHILLER", "CH") for m in _eqre.findall(t or "")}

            _q_eq = _eqset(query) | _eqset(str(equipment_id or ""))
            if _q_eq and isinstance(results, list):
                _kept = []
                _drop = 0
                for r in results:
                    _r_eq = _eqset(str(r.get("equipment_id") or "")) | _eqset(str(r.get("content") or "")) | _eqset(str(r.get("title") or ""))
                    if _r_eq and not (_r_eq & _q_eq):
                        _drop += 1
                        continue
                    _kept.append(r)
                if _drop:
                    logger.info(f"[Sovereign] query_skillbook equipment-scope: dropped {_drop} off-equipment skill(s)")
                results = _kept
        except Exception as _scope_err:
            logger.debug(f"[Sovereign] equipment-scope skipped: {_scope_err}")

        if not results:
            return {
                "query": query, "skills": [],
                "summary": {"total": 0, "note": "No on-equipment patterns in institutional memory"},
            }

        # RAG reranker: cross-encoder post-pass to improve result ordering
        try:
            from agent_commercial.ml.rag_optimizer import CrossEncoderReranker
            _reranker = CrossEncoderReranker()
            _candidates = results if isinstance(results, list) else results.get("results", [])
            if _candidates and len(_candidates) > 1:
                query_text = args.get("query", "") or args.get("spec_type", "")
                results = _reranker.rerank(query=query_text, candidates=_candidates, top_n=min(5, len(_candidates)))
                logger.debug(f"[Sovereign] CrossEncoder reranked {len(_candidates)} → {len(results)} results")
        except Exception as _rerank_err:
            logger.debug(f"[Sovereign] CrossEncoder reranking skipped: {_rerank_err}")

        # H5: Weak retrieval gate — if all results below confidence threshold, abstain
        _RETRIEVAL_THRESHOLD = 0.4
        strong_results = [r for r in results if r.get("relevance", 0) >= _RETRIEVAL_THRESHOLD]

        if results and not strong_results:
            return {
                "query": query,
                "skills": [],
                "summary": {
                    "total": 0,
                    "note": (
                        "Retrieval confidence too low to cite. "
                        "All matches scored below threshold — do NOT paraphrase from parametric memory. "
                        "State that institutional memory has no confident match for this query."
                    ),
                    "abstain_reason": "weak_retrieval",
                    "max_relevance": max(r.get("relevance", 0) for r in results),
                },
            }

        return {
            "query": query,
            "skills": strong_results if strong_results else results,
            "summary": {
                "total": len(strong_results if strong_results else results),
                "equipment_filter": equipment_id,
                "citation_note": "Each result includes chunk_id — cite it inline when referencing this data.",
            },
        }
    
    async def _handle_add_to_skillbook(self, args: Dict) -> Dict:
        """Record a new learning in the Skillbook.

        Writes to TechnicalKnowledgeBase.index_technical_snippet() which is the
        actual Chroma collection that query_skillbook reads from.
        """
        title = args.get("title")
        description = args.get("description")
        skill_type = args.get("skill_type")
        equipment_id = args.get("equipment_id")
        confidence = args.get("confidence", 0.5)
        tags = args.get("tags", [])

        if not title or not description or not skill_type:
            return {"error": "title, description, and skill_type are required"}

        knowledge_base = getattr(self, "knowledge_base", None)
        written = False

        if knowledge_base and hasattr(knowledge_base, "index_technical_snippet"):
            try:
                _type_map = {
                    "fault_pattern": "operator_pattern",
                    "quirk": "operator_pattern",
                    "maintenance": "operator_pattern",
                    "contractor": "operator_pattern",
                    "optimization": "specs",
                    "pattern": "operator_pattern",
                }
                knowledge_base.index_technical_snippet(
                    content=f"[{skill_type.upper()}] {title}\n\n{description}",
                    source=f"skillbook/{skill_type}",
                    equipment_id=equipment_id,
                    manual_type=_type_map.get(skill_type, "operator_pattern"),
                    chunk_type="procedure",
                    tags=[skill_type, f"confidence={confidence:.1f}"] + list(tags),
                )
                written = True
                logger.info(f"[Skillbook] Written: '{title}' eq={equipment_id} type={skill_type}")
            except Exception as e:
                logger.error(f"add_to_skillbook write failed: {e}")

        import uuid
        from datetime import datetime
        skill_id = f"skill_{uuid.uuid4().hex[:8]}"
        created_at = datetime.now().isoformat()

        # Always persist to SQLite skills table — canonical durable memory for
        # cross-equipment recall, temporal decay, and long-term institutional learning.
        building_id = args.get("building_id", "default")
        try:
            from agent_commercial.skillbook import get_skillbook
            _sb = get_skillbook(building_id)
            await _sb.ensure_initialized()
            added = await _sb.add_skill(
                skill_type=skill_type,
                title=title,
                description=description,
                equipment_id=equipment_id,
                confidence=confidence,
                tags=list(tags) if tags else [],
                created_by="arvis_auto",
            )
            if added:
                skill_id = added[0].skill_id
            written = True
            logger.info(
                f"[Skillbook] SQLite persisted: '{title}' eq={equipment_id} "
                f"id={skill_id} conf={confidence:.2f}"
            )
        except Exception as _sql_err:
            logger.warning(f"[Skillbook] SQLite write failed (non-fatal): {_sql_err}")

        if not written:
            # Fallback: try legacy add_skill if it exists
            if knowledge_base and hasattr(knowledge_base, "add_skill"):
                try:
                    return await knowledge_base.add_skill(
                        title=title, description=description, skill_type=skill_type,
                        equipment_id=equipment_id, confidence=confidence, tags=tags,
                    )
                except Exception as e:
                    logger.error(f"add_skill fallback failed: {e}")

        return {
            "status": "recorded" if written else "fallback_stored",
            "skill_id": skill_id,
            "title": title,
            "skill_type": skill_type,
            "equipment_id": equipment_id,
            "confidence": confidence,
            "created_at": created_at,
        }
    
    async def _handle_compare_to_fleet(self, args: Dict) -> Dict:
        """Benchmark building against portfolio fleet"""
        building_id = args.get("building_id")
        metric = args.get("metric", "energy_eui")
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "compare_to_fleet"):
            try:
                return await world_model.compare_to_fleet(
                    building_id=building_id,
                    metric=metric
                )
            except Exception as e:
                logger.error(f"Error in fleet comparison: {e}")
        
        return {
            "error": "no_data",
            "reason": "Fleet comparison requires world_model with multi-building portfolio data. Not yet available.",
            "building_id": building_id or "default",
        }
    
    async def _handle_simulate_change(self, args: Dict) -> Dict:
        """Predict impact of operational changes"""
        change_type = args.get("change_type")
        target = args.get("target")
        current_value = args.get("current_value")
        proposed_value = args.get("proposed_value")
        duration_hours = args.get("duration_hours", 24)
        
        if not change_type or target is None:
            return {"error": "change_type and target are required"}
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "simulate_change"):
            try:
                return await world_model.simulate_change(
                    change_type=change_type,
                    target=target,
                    current_value=current_value,
                    proposed_value=proposed_value,
                    duration_hours=duration_hours
                )
            except Exception as e:
                logger.error(f"Error in change simulation: {e}")
                # Fallback to local calculation on error
        
        return {
            "error": "no_data",
            "reason": "Change simulation requires calibrated world model. Cannot estimate impact without building physics baseline.",
            "change_type": change_type,
            "target": target,
        }
    
    async def _handle_correlate_events(self, args: Dict) -> Dict:
        """Find causal relationships across systems"""
        event_type = args.get("event_type")
        time_range = args.get("time_range", "last_24h")
        correlate_with = args.get("correlate_with", [])
        min_correlation = args.get("min_correlation", 0.5)
        
        if not event_type:
            return {"error": "event_type is required"}
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "correlate_events"):
            try:
                res = await world_model.correlate_events(
                    event_type=event_type,
                    time_range=time_range,
                    correlate_with=correlate_with,
                    min_correlation=min_correlation
                )
                if isinstance(res, dict):
                    # Schema keys: primary_cause, timeline, confidence
                    corrs = res.get("correlations") or []
                    if res.get("primary_cause") is None:
                        top = corrs[0] if corrs and isinstance(corrs[0], dict) else {}
                        res["primary_cause"] = top.get("cause") or top.get("equipment_id")
                    res.setdefault("timeline", res.get("events") or [])
                    if res.get("confidence") is None:
                        top = corrs[0] if corrs and isinstance(corrs[0], dict) else {}
                        res["confidence"] = top.get("correlation") or top.get("confidence") or 0.0
                return res
            except Exception as e:
                logger.error(f"Error in event correlation: {e}")

        # Fallback: basic correlation
        return {
            "event_type": event_type,
            "time_range": time_range,
            "correlations": [],
            "note": "Event correlation requires world_model module",
            # Schema keys
            "primary_cause": None,
            "timeline": [],
            "confidence": 0.0,
        }

    async def _handle_replay_investigation(self, args: Dict) -> Dict:
        """Replay a past investigation from the episodic archive (T2)."""
        import json as _json

        plan_id = args.get("plan_id")
        query_filter = args.get("query_filter")
        limit = args.get("limit", 10)

        db = getattr(self, "db", None)
        if db is None:
            return {"error": "Database not available for investigation replay"}

        if plan_id:
            try:
                plan_json_str = await db.load_investigation_plan_json(plan_id)
                if not plan_json_str:
                    return {"error": f"Investigation {plan_id} not found", "mode": "detail"}
                plan_data = _json.loads(plan_json_str) if isinstance(plan_json_str, str) else plan_json_str
                return {
                    "mode": "detail",
                    "plan_id": plan_id,
                    "plan": plan_data,
                }
            except Exception as e:
                logger.error(f"replay_investigation load failed: {e}")
                return {"error": str(e), "mode": "detail"}
        else:
            try:
                plans = await db.get_investigation_plans(
                    limit=limit,
                    query_filter=query_filter,
                )
                return {
                    "mode": "list",
                    "investigations": plans,
                    "total": len(plans),
                }
            except Exception as e:
                logger.error(f"replay_investigation list failed: {e}")
                return {"error": str(e), "mode": "list"}
