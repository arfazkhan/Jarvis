"""
Alarm Engine
============

Intelligent alarm processing for BMS.

Capabilities:
- Alarm ingestion from BACnet events or polling
- Correlation-based clustering (group related alarms by root cause)
- Priority queue ranking (safety > comfort > energy)
- Nuisance alarm suppression (hunting, transient)
- Root cause analysis using equipment topology

This is rule-based + correlation analysis, not LLM-reliant.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from collections import defaultdict
import uuid

from agent_commercial.bms_data_model import (
    Alarm,
    AlarmSeverity,
    AlarmState,
    Equipment,
    EquipmentType,
    BMSDataPoint,
)

logger = logging.getLogger("arvis.bms.alarm")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AlarmCluster:
    """
    A group of correlated alarms with likely common root cause.
    
    Example: Chiller 1 trips → multiple zone high-temp alarms
    """
    cluster_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    alarm_ids: List[str] = field(default_factory=list)
    
    # Root cause analysis
    probable_root_cause: str = ""
    root_cause_equipment_id: str = ""
    root_cause_confidence: float = 0.0
    
    # Timing
    first_alarm_time: Optional[datetime] = None
    last_alarm_time: Optional[datetime] = None
    
    # Impact
    affected_equipment_count: int = 0
    affected_zones: List[str] = field(default_factory=list)
    
    # Priority (highest of contained alarms)
    priority: AlarmSeverity = AlarmSeverity.MEDIUM
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "alarm_count": len(self.alarm_ids),
            "probable_root_cause": self.probable_root_cause,
            "root_cause_equipment": self.root_cause_equipment_id,
            "root_cause_confidence": round(self.root_cause_confidence, 2),
            "affected_equipment": self.affected_equipment_count,
            "priority": self.priority.value,
            "first_alarm": self.first_alarm_time.isoformat() if self.first_alarm_time else None,
        }


@dataclass
class ProcessedAlarm:
    """
    An alarm after processing through the alarm engine.
    
    Includes priority ranking, cluster assignment, and context.
    """
    alarm: Alarm
    rank: int = 0                           # Priority rank (1 = highest)
    cluster_id: Optional[str] = None
    is_root_cause: bool = False
    suppressed: bool = False
    suppression_reason: Optional[str] = None
    
    # Additional context
    related_equipment: List[str] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = self.alarm.to_dict()
        d.update({
            "rank": self.rank,
            "cluster_id": self.cluster_id,
            "is_root_cause": self.is_root_cause,
            "suppressed": self.suppressed,
            "suggested_actions": self.suggested_actions,
        })
        return d


@dataclass
class RootCauseReport:
    """Root cause analysis report for an alarm or cluster"""
    alarm_id: str
    analysis_time: datetime = field(default_factory=datetime.now)
    
    # Root cause determination
    probable_cause: str = ""
    confidence: float = 0.0
    
    # Evidence
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    # Related alarms
    related_alarms: List[str] = field(default_factory=list)
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alarm_id": self.alarm_id,
            "probable_cause": self.probable_cause,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "related_alarms": self.related_alarms,
            "recommendations": self.recommendations,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ALARM ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class AlarmEngine:
    """
    Intelligent alarm processing engine.
    
    Capabilities:
    1. Ingest alarms from BACnet or polling
    2. Cluster related alarms by root cause
    3. Prioritize by impact (safety > comfort > energy > maintenance)
    4. Suppress nuisance alarms
    5. Generate root cause analysis
    
    Example:
        >>> engine = AlarmEngine()
        >>> engine.set_equipment_topology(equipment_list)
        >>> processed = engine.ingest_alarm(alarm)
        >>> clusters = engine.get_clusters()
        >>> queue = engine.get_priority_queue()
    """
    
    # Correlation window: alarms within this window may be related
    CORRELATION_WINDOW_SECONDS = 300  # 5 minutes
    
    # Suppression thresholds
    HUNTING_THRESHOLD = 3  # Alarms in/out > N times in 15 min = hunting
    HUNTING_WINDOW_SECONDS = 900  # 15 minutes
    
    def __init__(self):
        """Initialize alarm engine"""
        # Active alarms
        self.active_alarms: Dict[str, ProcessedAlarm] = {}
        self.alarm_history: List[Alarm] = []  # Last 24h
        
        # Clusters
        self.clusters: Dict[str, AlarmCluster] = {}
        
        # Equipment topology (for correlation)
        self.equipment: Dict[str, Equipment] = {}
        self.equipment_relationships: Dict[str, Set[str]] = defaultdict(set)  # eq -> related eq
        import numpy as np # For random/math if needed
        self.np = np
        
        # Suppression tracking
        self.alarm_toggle_count: Dict[str, List[datetime]] = defaultdict(list)
        
        # Statistics
        self.stats = {
            "alarms_processed": 0,
            "alarms_suppressed": 0,
            "clusters_created": 0,
        }
        
        self.llm_provider = None # Will be injected by OpsCopilot
        
        logger.info("AlarmEngine initialized")
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def set_equipment_topology(self, equipment_list: List[Equipment]) -> None:
        """
        Load equipment topology for correlation analysis.
        
        The engine uses parent/child relationships to correlate alarms.
        Example: Chiller 1 supplies CHW to AHU-1, AHU-2, AHU-3
                 If Chiller 1 trips, expect high-temp alarms from AHUs.
        """
        self.equipment = {e.equipment_id: e for e in equipment_list}
        
        # Build relationship graph
        for eq in equipment_list:
            # Parent -> children
            for child_id in eq.child_equipment_ids:
                self.equipment_relationships[eq.equipment_id].add(child_id)
                self.equipment_relationships[child_id].add(eq.equipment_id)
            
            # Parent relationship
            if eq.parent_equipment_id:
                self.equipment_relationships[eq.equipment_id].add(eq.parent_equipment_id)
                self.equipment_relationships[eq.parent_equipment_id].add(eq.equipment_id)
        
        logger.info(f"Loaded topology: {len(equipment_list)} equipment, "
                   f"{sum(len(r) for r in self.equipment_relationships.values())} relationships")
    
    # ═══════════════════════════════════════════════════════════════════════
    # ALARM INGESTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def ingest_alarm(self, alarm: Alarm) -> ProcessedAlarm:
        """
        Process an incoming alarm.
        
        Steps:
        1. Check for suppression (hunting, transient)
        2. Find or create cluster
        3. Calculate priority rank
        4. Generate suggestions
        
        Returns:
            ProcessedAlarm with enriched information
        """
        self.stats["alarms_processed"] += 1
        
        # Create processed alarm
        processed = ProcessedAlarm(alarm=alarm)
        
        # ─────────────────────────────────────────────────────────────────
        # 1. Check for suppression
        # ─────────────────────────────────────────────────────────────────
        suppression = self._check_suppression(alarm)
        if suppression:
            processed.suppressed = True
            processed.suppression_reason = suppression
            self.stats["alarms_suppressed"] += 1
            logger.debug(f"Alarm {alarm.alarm_id} suppressed: {suppression}")
        
        # ─────────────────────────────────────────────────────────────────
        # 2. Cluster analysis
        # ─────────────────────────────────────────────────────────────────
        cluster = await self._find_or_create_cluster(alarm)
        if cluster:
            processed.cluster_id = cluster.cluster_id
            processed.is_root_cause = (alarm.alarm_id == cluster.alarm_ids[0])
            alarm.cluster_id = cluster.cluster_id
        
        # ─────────────────────────────────────────────────────────────────
        # 3. Calculate priority
        # ─────────────────────────────────────────────────────────────────
        processed.rank = self._calculate_rank(alarm, processed.is_root_cause)
        
        # ─────────────────────────────────────────────────────────────────
        # 4. Generate suggestions
        # ─────────────────────────────────────────────────────────────────
        processed.suggested_actions = self._generate_suggestions(alarm)
        
        # ─────────────────────────────────────────────────────────────────
        # 5. Store
        # ─────────────────────────────────────────────────────────────────
        if alarm.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED):
            self.active_alarms[alarm.alarm_id] = processed
        
        # Add to history
        self.alarm_history.append(alarm)
        self._cleanup_history()
        
        return processed
    
    def resolve_alarm(self, alarm_id: str) -> bool:
        """Mark an alarm as resolved"""
        if alarm_id in self.active_alarms:
            self.active_alarms[alarm_id].alarm.state = AlarmState.RESOLVED
            self.active_alarms[alarm_id].alarm.resolved_at = datetime.now()
            del self.active_alarms[alarm_id]
            
            # Track for hunting detection
            self.alarm_toggle_count[alarm_id].append(datetime.now())
            
            return True
        return False
    
    # ═══════════════════════════════════════════════════════════════════════
    # SUPPRESSION
    # ═══════════════════════════════════════════════════════════════════════
    
    def _check_suppression(self, alarm: Alarm) -> Optional[str]:
        """
        Check if alarm should be suppressed.
        
        Reasons for suppression:
        - Hunting: Alarm toggling on/off frequently
        - Transient: Very short duration
        - Duplicate: Same alarm already active
        """
        # Check for hunting
        point_key = f"{alarm.equipment_id}:{alarm.source_point_id}"
        recent_toggles = self.alarm_toggle_count.get(point_key, [])
        
        # Clean old toggles
        cutoff = datetime.now() - timedelta(seconds=self.HUNTING_WINDOW_SECONDS)
        recent_toggles = [t for t in recent_toggles if t > cutoff]
        self.alarm_toggle_count[point_key] = recent_toggles
        
        if len(recent_toggles) >= self.HUNTING_THRESHOLD:
            return f"hunting ({len(recent_toggles)} toggles in 15 min)"
        
        # Check for duplicate
        for existing in self.active_alarms.values():
            if (existing.alarm.source_point_id == alarm.source_point_id and
                existing.alarm.equipment_id == alarm.equipment_id and
                existing.alarm.state == AlarmState.ACTIVE):
                return "duplicate alarm"
        
        return None
    
    # ═══════════════════════════════════════════════════════════════════════
    # CLUSTERING
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _find_or_create_cluster(self, alarm: Alarm) -> Optional[AlarmCluster]:
        """
        Find existing cluster for alarm or create new one.
        
        Clustering logic:
        1. Time correlation: Alarms within 5 minutes
        2. Equipment relationship: Parent/child or same zone
        3. Causality: Upstream equipment failures cause downstream issues
        """
        # Look for existing cluster to join
        for cluster in self.clusters.values():
            if self._should_join_cluster(alarm, cluster):
                cluster.alarm_ids.append(alarm.alarm_id)
                cluster.last_alarm_time = alarm.triggered_at
                cluster.affected_equipment_count = len(set(
                    self.active_alarms[aid].alarm.equipment_id 
                    for aid in cluster.alarm_ids 
                    if aid in self.active_alarms
                ))
                
                # Update severity if new alarm is higher
                if self._severity_rank(alarm.severity) < self._severity_rank(cluster.priority):
                    cluster.priority = alarm.severity
                
                return cluster
        
        # Create new cluster if alarm has related active alarms
        related_alarms = self._find_related_alarms(alarm)
        
        if related_alarms:
            cluster = AlarmCluster(
                alarm_ids=[alarm.alarm_id] + related_alarms,
                first_alarm_time=alarm.triggered_at,
                last_alarm_time=alarm.triggered_at,
                priority=alarm.severity,
            )
            
            # Determine root cause
            root_cause = await self._determine_root_cause(cluster)
            cluster.probable_root_cause = root_cause["cause"]
            cluster.root_cause_equipment_id = root_cause["equipment_id"]
            cluster.root_cause_confidence = root_cause["confidence"]
            
            self.clusters[cluster.cluster_id] = cluster
            self.stats["clusters_created"] += 1
            
            return cluster
        
        return None
    
    def _should_join_cluster(self, alarm: Alarm, cluster: AlarmCluster) -> bool:
        """Check if alarm should join existing cluster"""
        # Time check: within correlation window
        if cluster.last_alarm_time:
            time_delta = (alarm.triggered_at - cluster.last_alarm_time).total_seconds()
            if time_delta > self.CORRELATION_WINDOW_SECONDS:
                return False
        
        # Equipment relationship check
        cluster_equipment = set()
        for aid in cluster.alarm_ids:
            if aid in self.active_alarms:
                cluster_equipment.add(self.active_alarms[aid].alarm.equipment_id)
        
        # Check if alarm's equipment is related to any cluster equipment
        for eq_id in cluster_equipment:
            if self._are_equipment_related(alarm.equipment_id, eq_id):
                return True
        
        return False
    
    def _find_related_alarms(self, alarm: Alarm) -> List[str]:
        """Find active alarms related to this one"""
        related = []
        
        for aid, processed in self.active_alarms.items():
            if aid == alarm.alarm_id:
                continue
            
            other = processed.alarm
            
            # Time correlation
            time_delta = abs((alarm.triggered_at - other.triggered_at).total_seconds())
            if time_delta > self.CORRELATION_WINDOW_SECONDS:
                continue
            
            # Equipment relationship
            if self._are_equipment_related(alarm.equipment_id, other.equipment_id):
                related.append(aid)
        
        return related
    
    def _are_equipment_related(self, eq1_id: str, eq2_id: str) -> bool:
        """Check if two equipment are related (same system, parent/child, etc.)"""
        if eq1_id == eq2_id:
            return True
        
        # Check direct relationship
        if eq2_id in self.equipment_relationships.get(eq1_id, set()):
            return True
        
        # Check same zone (based on location)
        eq1 = self.equipment.get(eq1_id)
        eq2 = self.equipment.get(eq2_id)
        
        if eq1 and eq2 and eq1.location and eq2.location:
            # Same zone if first 2 parts of location match
            loc1_parts = eq1.location.split(",")[:2]
            loc2_parts = eq2.location.split(",")[:2]
            if loc1_parts == loc2_parts:
                return True
        
        return False
    
    async def _determine_root_cause(self, cluster: AlarmCluster) -> Dict[str, Any]:
        """
        Determine probable root cause of alarm cluster.
        
        Logic:
        1. Earliest alarm is likely root cause
        2. Upstream equipment failures cause downstream
        3. Higher-level equipment (Chiller > AHU > VAV)
        """
        if not cluster.alarm_ids:
            return {"cause": "Unknown", "equipment_id": "", "confidence": 0.0}
        
        # Get alarms sorted by time
        alarms = []
        for aid in cluster.alarm_ids:
            if aid in self.active_alarms:
                alarms.append(self.active_alarms[aid].alarm)
        
        if not alarms:
            return {"cause": "Unknown", "equipment_id": "", "confidence": 0.0}
        
        alarms.sort(key=lambda a: a.triggered_at)
        first_alarm = alarms[0]
        
        # Check equipment hierarchy
        equipment_types = {}
        for a in alarms:
            eq = self.equipment.get(a.equipment_id)
            if eq:
                equipment_types[a.equipment_id] = eq.equipment_type
        
        # Hierarchy: Chiller > AHU > VAV > FCU
        hierarchy = {
            EquipmentType.CHILLER: 1,
            EquipmentType.BOILER: 1,
            EquipmentType.COOLING_TOWER: 2,
            EquipmentType.PUMP: 3,
            EquipmentType.AHU: 4,
            EquipmentType.VAV: 5,
            EquipmentType.FCU: 5,
        }
        
        # Find highest-level equipment in cluster
        root_equipment_id = first_alarm.equipment_id
        root_level = 99
        
        for eq_id, eq_type in equipment_types.items():
            level = hierarchy.get(eq_type, 10)
            if level < root_level:
                root_level = level
                root_equipment_id = eq_id
        
        # Generate cause description
        root_eq = self.equipment.get(root_equipment_id)
        if root_eq:
            cause = f"{root_eq.equipment_type.value.replace('_', ' ').title()} fault: {first_alarm.message}"
        else:
            cause = first_alarm.message
        
        # Confidence based on timing alignment
        confidence = 0.8 if root_equipment_id == first_alarm.equipment_id else 0.6
        
        return {
            "cause": cause,
            "equipment_id": root_equipment_id,
            "confidence": confidence,
        }

    def set_llm_provider(self, provider: Any) -> None:
        """Set LLM provider for semantic analysis."""
        self.llm_provider = provider
        logger.info("AlarmEngine: Connected to Cognitive Layer (LLM)")

    async def _analyze_root_cause_with_llm(self, cluster: AlarmCluster) -> Dict[str, Any]:
        """
        Ask LLM to determine root cause when rules are uncertain.
        """
        if not self.llm_provider:
            return {"cause": "Unknown (Analysis Unavailable)", "confidence": 0.0}

        # Prepare context for LLM
        alarms_desc = []
        for aid in cluster.alarm_ids:
            if aid in self.active_alarms:
                a = self.active_alarms[aid].alarm
                # Use triggered_at instead of timestamp, and handle missing alarm_type
                atype = getattr(a, 'alarm_type', a.message)
                time_str = a.triggered_at.strftime("%H:%M:%S") if a.triggered_at else "Unknown"
                alarms_desc.append(f"- {time_str}: {a.equipment_id} ({atype}) - {a.message}")
        
        prompt = f"""
        Analyze this cluster of BMS alarms to find the semantic root cause.
        
        ALARMS:
        {chr(10).join(alarms_desc)}
        
        Topology:
        - Parent/Child links may be missing.
        - Look for causal keywords (e.g., 'Power Loss' -> 'Device Offline').
        
        Return JSON items: 'cause' (string) and 'confidence' (0.0-1.0).
        """
        
        try:
            # We assume provider has a simple 'reason' or 'chat' interface
            # Using UnifiedLLM.chat directly style
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            text = response.content
            
            # Simple parsing (robustness would require structured output)
            import json
            if "{" in text and "}" in text:
                json_str = text[text.find("{"):text.rfind("}")+1]
                data = json.loads(json_str)
                return {
                    "cause": data.get("cause", "LLM Analysis Failed"),
                    "equipment_id": cluster.root_cause_equipment_id, # Keep rule-based guess
                    "confidence": float(data.get("confidence", 0.5))
                }
        except Exception as e:
            logger.error(f"LLM Root Cause Analysis failed: {e}")
            
        return {"cause": "Unknown", "confidence": 0.0}
    
    # ═══════════════════════════════════════════════════════════════════════
    # PRIORITY RANKING
    # ═══════════════════════════════════════════════════════════════════════
    
    def _calculate_rank(self, alarm: Alarm, is_root_cause: bool) -> int:
        """
        Calculate priority rank for alarm.
        
        Factors:
        1. Severity (critical > high > medium > low)
        2. Impact type (safety > comfort > energy > maintenance)
        3. Root cause status (root cause ranked higher)
        4. Duration (older alarms rank lower if unaddressed)
        """
        base_rank = self._severity_rank(alarm.severity) * 100
        
        # Adjust for impact type
        impact_adjustment = 0
        if alarm.safety_impact > 0.5:
            impact_adjustment = -50  # Higher priority (lower rank number)
        elif alarm.comfort_impact > 0.5:
            impact_adjustment = -30
        elif alarm.energy_impact > 0.5:
            impact_adjustment = -10
        
        # Root cause bonus
        if is_root_cause:
            impact_adjustment -= 20
        
        # Duration penalty (old unaddressed alarms drop in priority)
        duration_hours = alarm.duration_minutes() / 60
        if duration_hours > 24:
            impact_adjustment += 10
        
        return max(1, base_rank + impact_adjustment)
    
    def _severity_rank(self, severity: AlarmSeverity) -> int:
        """Convert severity to numeric rank (lower = higher priority)"""
        return {
            AlarmSeverity.CRITICAL: 1,
            AlarmSeverity.HIGH: 2,
            AlarmSeverity.MEDIUM: 3,
            AlarmSeverity.LOW: 4,
            AlarmSeverity.INFO: 5,
        }.get(severity, 3)
    
    # ═══════════════════════════════════════════════════════════════════════
    # SUGGESTIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generate_suggestions(self, alarm: Alarm) -> List[str]:
        """Generate actionable suggestions for alarm"""
        suggestions = []
        
        # Equipment-specific suggestions
        eq = self.equipment.get(alarm.equipment_id)
        if eq:
            if eq.equipment_type == EquipmentType.CHILLER:
                suggestions.append("Check chilled water supply temperature")
                suggestions.append("Verify condenser water flow")
                suggestions.append("Review compressor status and pressures")
            elif eq.equipment_type == EquipmentType.AHU:
                suggestions.append("Check supply fan status and speed")
                suggestions.append("Verify damper positions")
                suggestions.append("Check filter differential pressure")
            elif eq.equipment_type == EquipmentType.VAV:
                suggestions.append("Check damper actuator operation")
                suggestions.append("Verify zone temperature sensor")
                suggestions.append("Check upstream AHU supply air temperature")
        
        # Severity-based suggestions
        if alarm.severity == AlarmSeverity.CRITICAL:
            suggestions.insert(0, "URGENT: Dispatch technician immediately")
        elif alarm.severity == AlarmSeverity.HIGH:
            suggestions.insert(0, "Schedule technician visit within 4 hours")
        
        return suggestions[:5]  # Max 5 suggestions
    
    # ═══════════════════════════════════════════════════════════════════════
    # QUERIES
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_priority_queue(self) -> List[ProcessedAlarm]:
        """Get all active alarms sorted by priority (highest first)"""
        alarms = [a for a in self.active_alarms.values() if not a.suppressed]
        alarms.sort(key=lambda a: a.rank)
        return alarms
    
    def get_clusters(self) -> List[AlarmCluster]:
        """Get all active alarm clusters"""
        # Filter to clusters with active alarms
        active_clusters = []
        for cluster in self.clusters.values():
            has_active = any(
                aid in self.active_alarms 
                for aid in cluster.alarm_ids
            )
            if has_active:
                active_clusters.append(cluster)
        
        return active_clusters
    
    def get_root_cause_analysis(self, alarm_id: str) -> RootCauseReport:
        """Generate detailed root cause analysis for an alarm"""
        alarm = None
        processed = self.active_alarms.get(alarm_id)
        
        if processed:
            alarm = processed.alarm
        else:
            # Check history
            for h in self.alarm_history:
                if h.alarm_id == alarm_id:
                    alarm = h
                    break
        
        if not alarm:
            return RootCauseReport(
                alarm_id=alarm_id,
                probable_cause="Alarm not found",
                confidence=0.0,
            )
        
        # Get cluster if exists
        cluster = None
        if alarm.cluster_id and alarm.cluster_id in self.clusters:
            cluster = self.clusters[alarm.cluster_id]
        
        # Build evidence
        evidence = []
        
        # Equipment info
        eq = self.equipment.get(alarm.equipment_id)
        if eq:
            evidence.append({
                "type": "equipment_info",
                "equipment_id": eq.equipment_id,
                "equipment_type": eq.equipment_type.value,
                "status": eq.status.value,
                "runtime_hours": eq.runtime_hours,
                "days_since_maintenance": (
                    (datetime.now() - eq.last_maintenance).days 
                    if eq.last_maintenance else None
                ),
            })
        
        # Related alarms
        related = []
        if cluster:
            related = [aid for aid in cluster.alarm_ids if aid != alarm_id]
        
        # Recommendations
        recommendations = []
        if cluster:
            recommendations.append(f"Focus on {cluster.root_cause_equipment_id} as probable root cause")
        recommendations.extend(self._generate_suggestions(alarm))
        
        return RootCauseReport(
            alarm_id=alarm_id,
            probable_cause=cluster.probable_root_cause if cluster else alarm.message,
            confidence=cluster.root_cause_confidence if cluster else 0.5,
            evidence=evidence,
            related_alarms=related,
            recommendations=recommendations,
        )
    
    def analyze(self) -> List[Dict[str, Any]]:
        """
        Analyze current alarm state and generate insights.
        
        Called by CognitiveLoop for periodic analysis.
        """
        insights = []
        
        # High priority alarms
        high_priority = [
            a for a in self.active_alarms.values()
            if not a.suppressed and a.alarm.severity in (AlarmSeverity.CRITICAL, AlarmSeverity.HIGH)
        ]
        
        if high_priority:
            insights.append({
                "type": "alarm_priority",
                "priority": "high",
                "message": f"{len(high_priority)} high-priority alarms require attention",
                "alarms": [a.to_dict() for a in high_priority[:5]],
            })
        
        # Cluster analysis
        clusters = self.get_clusters()
        for cluster in clusters:
            if len(cluster.alarm_ids) >= 3:
                insights.append({
                    "type": "alarm_cluster",
                    "priority": "medium",
                    "message": f"Alarm cluster: {len(cluster.alarm_ids)} related alarms",
                    "cluster": cluster.to_dict(),
                })
        
        # Suppression report
        suppressed_count = self.stats.get("alarms_suppressed", 0)
        if suppressed_count > 10:
            insights.append({
                "type": "suppression_report",
                "priority": "low",
                "message": f"{suppressed_count} nuisance alarms suppressed - review alarm configuration",
            })
        
        return insights
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════
    
    def _cleanup_history(self) -> None:
        """Remove alarm history older than 24 hours"""
        cutoff = datetime.now() - timedelta(hours=24)
        self.alarm_history = [a for a in self.alarm_history if a.triggered_at > cutoff]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get alarm engine statistics"""
        return {
            **self.stats,
            "active_alarms": len(self.active_alarms),
            "active_clusters": len([c for c in self.clusters.values() if any(
                aid in self.active_alarms for aid in c.alarm_ids
            )]),
            "suppressed_percentage": (
                self.stats["alarms_suppressed"] / max(1, self.stats["alarms_processed"]) * 100
            ),
        }
