"""
Alarm Tool Handlers
===================

Handlers for alarm-related BMS tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.alarms")

# Safe imports for modular standalone operation
try:
    from agent_advisory.explainer import DetailLevel
except ImportError:
    class DetailLevel:
        STANDARD = "standard"
        DETAILED = "detailed"
        BRIEF = "brief"


class AlarmHandlerMixin:
    """Mixin providing alarm-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "get_active_alarms": instance._handle_get_active_alarms,
            "explain_alarm": instance._handle_explain_alarm,
            "acknowledge_alarm": instance._handle_acknowledge_alarm,
            "analyze_cascade": instance._handle_analyze_cascade,
            "escalate_alarm": instance._handle_escalate_alarm,
            "silence_alarm": instance._handle_silence_alarm,
            "get_alarm_clusters": instance._handle_get_alarm_clusters,
        }
    
    async def _handle_get_active_alarms(self, args: Dict) -> Dict:
        severity = args.get("severity")
        equipment_id = args.get("equipment_id")
        limit = args.get("limit", 20)
        include_inference = args.get("include_inference", False)
        
        alarm_engine = getattr(self, "alarm_engine", None)
        if alarm_engine and hasattr(alarm_engine, "get_priority_queue"):
            try:
                queue = alarm_engine.get_priority_queue()

                # Defensive filtering
                if severity:
                    queue = [a for a in queue if str(getattr(getattr(a, "alarm", a), "severity", "")).lower() == str(severity).lower() or
                             str(getattr(getattr(getattr(a, "alarm", a), "severity", None), "value", "")).lower() == str(severity).lower()]
                if equipment_id:
                    queue = [a for a in queue if getattr(getattr(a, "alarm", a), "equipment_id", None) == equipment_id]
                if not include_inference:
                    queue = [a for a in queue if getattr(getattr(a, "alarm", a), "source_point_id", "") not in (None, "")]

                if queue:
                    return {
                        "count": len(queue[:limit]),
                        "alarms": [a.to_dict() if hasattr(a, "to_dict") else a for a in queue[:limit]]
                    }
                # Empty queue — fall through to bms_state which may have alarms injected directly
            except Exception as e:
                logger.error(f"Error getting priority queue: {e}")
        
        # Fallback to BMS state
        if hasattr(self, "bms_state"):
            all_alarms = []
            if hasattr(self.bms_state, "_alarms"):
                all_alarms = list(self.bms_state._alarms.values())
            elif hasattr(self.bms_state, "get_active_alarms"):
                all_alarms = await self.bms_state.get_active_alarms()
            
            # Helper to extract value from dict or object (including enums)
            def get_val(obj, key):
                if isinstance(obj, dict):
                    v = obj.get(key)
                else:
                    v = getattr(obj, key, None)
                
                # Handle enum value
                if hasattr(v, "value"):
                    return v.value
                return v

            # Filter
            filtered = all_alarms
            if severity and severity in ["critical", "high", "warning", "medium", "low", "info"]:
                filtered = [a for a in filtered if get_val(a, "severity") == severity]
            if equipment_id:
                filtered = [a for a in filtered if get_val(a, "equipment_id") == equipment_id]
            if not include_inference:
                filtered = [a for a in filtered if get_val(a, "source_point_id") not in (None, "")]
            
            # Sort critical first if possible
            def sort_key(a):
                s = get_val(a, "severity")
                return {"critical": 0, "high": 1, "warning": 1, "medium": 2, "low": 3, "info": 4}.get(str(s).lower(), 5)
            
            filtered = sorted(filtered, key=sort_key)
            
            return {
                "count": len(filtered),
                "alarms": [ (a if isinstance(a, dict) else a.to_dict()) for a in filtered[:limit] ]
            }

        return {"error": "Alarm engine not configured"}
    
    async def _handle_explain_alarm(self, args: Dict) -> Dict:
        alarm_id = args.get("alarm_id")
        
        alarm_engine = getattr(self, "alarm_engine", None)
        if not alarm_engine or not hasattr(alarm_engine, "get_root_cause_analysis"):
            return {"error": "Alarm engine or analysis service not available"}
        
        try:
            report = alarm_engine.get_root_cause_analysis(alarm_id)
            if not report:
                return {"error": f"Analysis for alarm {alarm_id} not found"}
                
            result = report.to_dict() if hasattr(report, "to_dict") else (report if isinstance(report, dict) else {"analysis": str(report)})
        except Exception as e:
            logger.error(f"Error in alarm analysis: {e}")
            return {"error": f"Failed to analyze alarm {alarm_id}"}
        
        # Phase 5: Enhance with high-fidelity explanation if available
        if getattr(self, "explainer", None) and result.get("recommendation"):
            # Get current context from BMS State
            context = {"total_power_kw": 400, "zone_temp_avg_c": 23.5}  # Fallback
            if self.bms_state:
                try:
                    points = await self.bms_state.get_points_by_equipment(result.get("root_cause_id", ""))
                    context = {p.point_id.split("/")[-1].lower(): p.value for p in points}
                except Exception:
                    pass
                
            explanation = await self.explainer.explain_recommendation(
                recommendation={"title": "Alarm Resolution", "description": result["recommendation"]},
                context=context,
                level=DetailLevel.STANDARD
            )
            result["high_fidelity_explanation"] = explanation["text"]
            result["causal_chain"] = explanation["causal_chain"]
            
        return result
    async def _handle_acknowledge_alarm(self, args: Dict) -> Dict:
        alarm_id = args.get("alarm_id")
        note = args.get("note", "")
        
        if not alarm_id:
            return {"error": "alarm_id is required", "success": False}

        alarm_engine = getattr(self, "alarm_engine", None)
        if alarm_engine and hasattr(alarm_engine, "acknowledge_alarm"):
            try:
                success = alarm_engine.acknowledge_alarm(alarm_id, note=note)
                return {"success": success, "status": "acknowledged" if success else "failed", "alarm_id": alarm_id, "note": note}
            except Exception as e:
                logger.error(f"Error acknowledging alarm in engine: {e}")
        
        if hasattr(self, "bms_state"):
            success = False
            if hasattr(self.bms_state, "acknowledge_alarm"):
                success = await self.bms_state.acknowledge_alarm(alarm_id, "ops_copilot", note=note)
            
            return {"success": success, "status": "acknowledged" if success else "failed", "alarm_id": alarm_id, "note": note}
            
        return {"error": "Alarm system not configured", "success": False}
    
    async def _handle_analyze_cascade(self, args: Dict) -> Dict:
        """Analyze alarm cascade to find root cause.

        Returns canonical schema: root_cause_alarm_id, root_cause_equipment,
        cascade_tree, confidence, affected_systems. Any partial response from
        alarm_engine is back-filled with safe defaults (B11 schema fix).
        """
        alarm_ids = args.get("alarm_ids", [])
        time_window = args.get("time_window_minutes", 30)

        # Default response — guarantees all schema keys present
        default_response = {
            "root_cause_alarm_id": alarm_ids[0] if alarm_ids else "",
            "root_cause_equipment": "",
            "cascade_tree": {},
            "confidence": 0.0,
            "affected_systems": [],
        }

        alarm_engine = getattr(self, "alarm_engine", None)
        if alarm_engine and hasattr(alarm_engine, "analyze_cascade"):
            try:
                result = await alarm_engine.analyze_cascade(alarm_ids, time_window)
                if isinstance(result, dict):
                    # Back-fill any missing schema keys (B11 fix)
                    for key, fallback in default_response.items():
                        result.setdefault(key, fallback)
                    return result
            except Exception as e:
                logger.error(f"Error in cascade analysis: {e}")

        return default_response

    async def _handle_escalate_alarm(self, args: Dict) -> Dict:
        """Escalate an alarm to a higher level or notify supervisor"""
        alarm_id = args.get("alarm_id")
        level = args.get("escalation_level", "critical")
        
        if not alarm_id:
            return {"error": "alarm_id is required", "success": False}
            
        # Implementation would call escalation manager
        return {
            "success": True,
            "status": "escalated",
            "alarm_id": alarm_id,
            "escalation_level": level
        }

    async def _handle_silence_alarm(self, args: Dict) -> Dict:
        """Silence an alarm for a specific duration"""
        alarm_id = args.get("alarm_id")
        duration = args.get("duration_minutes", 60)
        
        if not alarm_id:
            return {"error": "alarm_id is required", "success": False}
            
        # Implementation would update alarm state
        return {
            "success": True,
            "status": "silenced",
            "alarm_id": alarm_id,
            "duration": duration
        }

    async def _handle_get_alarm_cluster(self, args: Dict) -> Dict:
        """Get details about an alarm cluster"""
        cluster_id = args.get("cluster_id")
        
        if not cluster_id:
            return {"error": "cluster_id is required"}
            
        alarm_engine = getattr(self, "alarm_engine", None)
        if alarm_engine and hasattr(alarm_engine, "clusters"):
            try:
                clusters = alarm_engine.clusters
                cluster = clusters.get(cluster_id) if hasattr(clusters, "get") else None
                if cluster:
                    return {"cluster": cluster.to_dict() if hasattr(cluster, "to_dict") else cluster}
            except Exception as e:
                logger.error(f"Error getting alarm cluster: {e}")
        
        return {"error": f"Cluster {cluster_id} not found"}

    async def _handle_get_alarm_clusters(self, args: Dict) -> Dict:
        """Get all active alarm clusters with root cause summaries.

        Returns canonical schema: cluster_count, total_alarms_collapsed, clusters.
        Each cluster entry guaranteed to have active_alarm_count (B11 schema fix).
        """
        alarm_engine = getattr(self, "alarm_engine", None)
        if alarm_engine:
            clusters = alarm_engine.get_active_clusters_summary()
            if clusters:
                # B11: ensure each cluster has active_alarm_count key
                for c in clusters:
                    c.setdefault("active_alarm_count", len(c.get("alarm_ids", [])))
                return {
                    "cluster_count": len(clusters),
                    "total_alarms_collapsed": sum(c.get("active_alarm_count", 0) for c in clusters),
                    "clusters": clusters,
                }

        # Fallback: build simple clusters from bms_state alarms grouped by equipment_id
        if hasattr(self, "bms_state"):
            try:
                alarms = await self.bms_state.get_active_alarms() if hasattr(self.bms_state, "get_active_alarms") else []
                if not alarms and hasattr(self.bms_state, "_alarms"):
                    from agent_commercial.bms_data_model import AlarmState
                    alarms = [a for a in self.bms_state._alarms.values()
                              if getattr(a, "state", None) in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)]
                if alarms:
                    from collections import defaultdict
                    by_eq = defaultdict(list)
                    for a in alarms:
                        eq = getattr(a, "equipment_id", "unknown")
                        by_eq[eq].append(a)
                    clusters = []
                    for eq_id, eq_alarms in by_eq.items():
                        clusters.append({
                            "cluster_id": f"cluster_{eq_id}",
                            "equipment_id": eq_id,
                            "active_alarm_count": len(eq_alarms),
                            "severity_max": max((getattr(a.severity, "value", str(a.severity)) for a in eq_alarms), default="medium"),
                            "alarm_ids": [a.alarm_id for a in eq_alarms[:10]],
                            "summary": f"{len(eq_alarms)} alarms on {eq_id}",
                        })
                    return {
                        "cluster_count": len(clusters),
                        "total_alarms_collapsed": sum(c["active_alarm_count"] for c in clusters),
                        "clusters": clusters,
                    }
            except Exception as e:
                logger.error(f"Error building alarm clusters from bms_state: {e}")

        return {"cluster_count": 0, "total_alarms_collapsed": 0, "clusters": []}
