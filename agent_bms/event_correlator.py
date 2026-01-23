"""
Event Correlator Engine
=======================

Cross-system event correlation for ARVIS Ops Copilot.

Correlates events across:
- BMS alarms
- Energy meter spikes
- Access control (badge events, door opens)
- Weather (sandstorms, temperature)
- Calendar (events, meetings)
- Maintenance logs

Usage:
    >>> correlator = EventCorrelator()
    >>> result = correlator.correlate(trigger_event)
    >>> print(result["causal_chain"])
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("arvis.bms.correlator")


# =============================================================================
# DATA MODELS
# =============================================================================

class EventSource(Enum):
    """Sources of events for correlation"""
    BMS_ALARM = "bms_alarm"
    ENERGY_METER = "energy_meter"
    ACCESS_CONTROL = "access_control"
    WEATHER = "weather"
    CALENDAR = "calendar"
    MAINTENANCE = "maintenance"
    HVAC = "hvac"
    LIGHTING = "lighting"


class ImpactCategory(Enum):
    """Categories of impact from correlated events"""
    ENERGY = "energy"
    COMFORT = "comfort"
    SAFETY = "safety"
    COST = "cost"
    PRODUCTIVITY = "productivity"


@dataclass
class Event:
    """A system event for correlation"""
    event_id: str
    source: EventSource
    timestamp: datetime
    event_type: str
    description: str
    equipment_id: Optional[str] = None
    zone_id: Optional[str] = None
    value: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source.value,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "description": self.description,
            "equipment_id": self.equipment_id,
            "zone_id": self.zone_id,
            "value": self.value,
            "metadata": self.metadata,
        }


@dataclass
class CausalLink:
    """A causal relationship between two events"""
    cause_event_id: str
    effect_event_id: str
    relationship: str  # "caused_by", "contributed_to", "correlated_with"
    confidence: float  # 0-1
    explanation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cause": self.cause_event_id,
            "effect": self.effect_event_id,
            "relationship": self.relationship,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


@dataclass
class CorrelationResult:
    """Result of event correlation analysis"""
    trigger_event: Event
    related_events: List[Event]
    causal_chain: List[CausalLink]
    impact: Dict[str, Any]
    insight: str
    recommendation: str
    confidence: float
    analysis_time: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger": self.trigger_event.to_dict(),
            "related_events": [e.to_dict() for e in self.related_events],
            "causal_chain": [c.to_dict() for c in self.causal_chain],
            "impact": self.impact,
            "insight": self.insight,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "analysis_time": self.analysis_time.isoformat(),
        }


# =============================================================================
# EVENT CORRELATOR ENGINE
# =============================================================================

class EventCorrelator:
    """
    Cross-system event correlation engine.
    
    Finds causal relationships between events from different systems
    to provide unified insights.
    
    Example:
        Fire drill at 14:20 →
        ├── Doors held open for 8 minutes
        ├── Outdoor air influx (sandstorm particles)
        ├── AHU-03 ramped to 100%
        └── Energy spike +45 kW
        
        Insight: Fire drills during sandstorms cause 3x energy spike.
    """
    
    # Time window for correlation (default 30 minutes)
    DEFAULT_CORRELATION_WINDOW = timedelta(minutes=30)
    
    # Causal relationship patterns
    CAUSAL_PATTERNS = {
        # Access control → HVAC
        ("access_control", "door_open"): [
            ("hvac", "load_increase", "Outdoor air influx through open door"),
            ("energy_meter", "spike", "HVAC working harder due to open door"),
        ],
        # Weather → HVAC
        ("weather", "temperature_spike"): [
            ("hvac", "load_increase", "Higher cooling load due to outdoor temp"),
            ("energy_meter", "spike", "Increased cooling energy"),
        ],
        ("weather", "sandstorm"): [
            ("hvac", "filter_load", "Increased particle load on filters"),
            ("hvac", "load_increase", "AHU running at higher capacity"),
        ],
        # Calendar → Occupancy → HVAC
        ("calendar", "event_start"): [
            ("access_control", "high_traffic", "Attendees arriving"),
            ("hvac", "load_increase", "Higher occupancy heat load"),
        ],
        # Maintenance → Equipment
        ("maintenance", "equipment_offline"): [
            ("bms_alarm", "equipment_fault", "Maintenance-related alarm"),
            ("hvac", "capacity_reduction", "Reduced system capacity"),
        ],
        # BMS alarm cascades
        ("bms_alarm", "chiller_trip"): [
            ("bms_alarm", "high_chw_temp", "Chilled water temp rising"),
            ("bms_alarm", "zone_high_temp", "Zones overheating"),
        ],
        ("bms_alarm", "ahu_fault"): [
            ("bms_alarm", "zone_high_temp", "Served zones overheating"),
            ("bms_alarm", "poor_iaq", "Reduced ventilation"),
        ],
    }
    
    def __init__(self, 
                 bms_state=None,
                 alarm_engine=None,
                 energy_analyzer=None):
        """
        Initialize the Event Correlator.
        
        Args:
            bms_state: BMSStateEngine for equipment topology
            alarm_engine: AlarmEngine for alarm history
            energy_analyzer: EnergyAnalyzer for consumption data
        """
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        
        # Event history buffer (last 24 hours)
        self.event_history: List[Event] = []
        self.max_history_hours = 24
        
        logger.info("EventCorrelator initialized")
    
    def add_event(self, event: Event) -> None:
        """Add an event to the history buffer."""
        self.event_history.append(event)
        self._cleanup_old_events()
    
    def _cleanup_old_events(self) -> None:
        """Remove events older than max_history_hours."""
        cutoff = datetime.now() - timedelta(hours=self.max_history_hours)
        self.event_history = [e for e in self.event_history if e.timestamp > cutoff]
    
    def correlate(self, 
                  trigger_event: Dict[str, Any],
                  time_window_minutes: int = 30,
                  sources: Optional[List[str]] = None) -> CorrelationResult:
        """
        Correlate a trigger event with related events from other systems.
        
        Args:
            trigger_event: The event that triggered the analysis
            time_window_minutes: Time window for correlation (default 30)
            sources: List of sources to include (default: all)
            
        Returns:
            CorrelationResult with causal chain and insights
        """
        # Parse trigger event
        trigger = self._parse_event(trigger_event)
        
        # Define correlation window
        window = timedelta(minutes=time_window_minutes)
        start_time = trigger.timestamp - window
        end_time = trigger.timestamp + window
        
        # Get events from all sources within window
        related_events = self._get_events_in_window(
            start_time, end_time, sources
        )
        
        # Build timeline
        timeline = self._build_timeline(trigger, related_events)
        
        # Infer causal relationships
        causal_chain = self._infer_causality(trigger, timeline)
        
        # Calculate impact
        impact = self._calculate_impact(trigger, causal_chain, timeline)
        
        # Generate insight and recommendation
        insight = self._generate_insight(trigger, causal_chain, impact)
        recommendation = self._generate_recommendation(trigger, causal_chain, impact)
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(causal_chain)
        
        return CorrelationResult(
            trigger_event=trigger,
            related_events=related_events,
            causal_chain=causal_chain,
            impact=impact,
            insight=insight,
            recommendation=recommendation,
            confidence=confidence,
        )
    
    def _parse_event(self, event_dict: Dict[str, Any]) -> Event:
        """Parse event dictionary into Event object."""
        source = EventSource(event_dict.get("source", "bms_alarm"))
        timestamp = event_dict.get("timestamp")
        
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now()
        
        return Event(
            event_id=event_dict.get("event_id", f"evt_{timestamp.timestamp()}"),
            source=source,
            timestamp=timestamp,
            event_type=event_dict.get("event_type", "unknown"),
            description=event_dict.get("description", ""),
            equipment_id=event_dict.get("equipment_id"),
            zone_id=event_dict.get("zone_id"),
            value=event_dict.get("value"),
            metadata=event_dict.get("metadata", {}),
        )
    
    def _get_events_in_window(self,
                              start_time: datetime,
                              end_time: datetime,
                              sources: Optional[List[str]] = None) -> List[Event]:
        """Get all events within time window from specified sources."""
        events = []
        
        # Filter from history buffer
        for event in self.event_history:
            if start_time <= event.timestamp <= end_time:
                if sources is None or event.source.value in sources:
                    events.append(event)
        
        # Get alarms from alarm engine
        if self.alarm_engine and (sources is None or "bms_alarm" in sources):
            try:
                alarms = self.alarm_engine.get_alarms_in_range(start_time, end_time)
                for alarm in alarms:
                    events.append(Event(
                        event_id=alarm.alarm_id,
                        source=EventSource.BMS_ALARM,
                        timestamp=alarm.timestamp,
                        event_type=alarm.alarm_type,
                        description=alarm.message,
                        equipment_id=alarm.equipment_id,
                        zone_id=alarm.zone_id,
                    ))
            except Exception as e:
                logger.debug(f"Could not get alarms: {e}")
        
        # Get energy spikes from analyzer
        if self.energy_analyzer and (sources is None or "energy_meter" in sources):
            try:
                spikes = self.energy_analyzer.get_spikes_in_range(start_time, end_time)
                for spike in spikes:
                    events.append(Event(
                        event_id=f"energy_{spike['timestamp']}",
                        source=EventSource.ENERGY_METER,
                        timestamp=spike['timestamp'],
                        event_type="spike",
                        description=f"Energy spike: {spike['delta_kw']} kW",
                        value=spike['delta_kw'],
                    ))
            except Exception as e:
                logger.debug(f"Could not get energy spikes: {e}")
        
        return sorted(events, key=lambda e: e.timestamp)
    
    def _build_timeline(self, trigger: Event, events: List[Event]) -> List[Event]:
        """Build chronological timeline including trigger."""
        all_events = events + [trigger]
        return sorted(all_events, key=lambda e: e.timestamp)
    
    def _infer_causality(self, trigger: Event, timeline: List[Event]) -> List[CausalLink]:
        """Infer causal relationships between events."""
        causal_links = []
        
        # Find trigger index in timeline
        trigger_idx = next(
            (i for i, e in enumerate(timeline) if e.event_id == trigger.event_id),
            -1
        )
        
        # Look for known causal patterns
        trigger_key = (trigger.source.value, trigger.event_type)
        if trigger_key in self.CAUSAL_PATTERNS:
            expected_effects = self.CAUSAL_PATTERNS[trigger_key]
            
            # Check if expected effects occurred after trigger
            for effect_source, effect_type, explanation in expected_effects:
                for event in timeline[trigger_idx + 1:] if trigger_idx >= 0 else timeline:
                    if (event.source.value == effect_source and 
                        effect_type in event.event_type):
                        causal_links.append(CausalLink(
                            cause_event_id=trigger.event_id,
                            effect_event_id=event.event_id,
                            relationship="caused_by",
                            confidence=0.8,
                            explanation=explanation,
                        ))
        
        # Look for temporal correlations (events close in time)
        for i, event in enumerate(timeline):
            if event.event_id == trigger.event_id:
                continue
            
            time_diff = abs((event.timestamp - trigger.timestamp).total_seconds())
            
            # Events within 5 minutes are likely correlated
            if time_diff < 300:
                # Check if same equipment or zone
                same_equipment = (
                    event.equipment_id and 
                    trigger.equipment_id and 
                    event.equipment_id == trigger.equipment_id
                )
                same_zone = (
                    event.zone_id and 
                    trigger.zone_id and 
                    event.zone_id == trigger.zone_id
                )
                
                if same_equipment or same_zone:
                    # Determine direction (cause or effect)
                    if event.timestamp < trigger.timestamp:
                        causal_links.append(CausalLink(
                            cause_event_id=event.event_id,
                            effect_event_id=trigger.event_id,
                            relationship="contributed_to",
                            confidence=0.6,
                            explanation=f"Preceded trigger by {int(time_diff)}s",
                        ))
                    else:
                        causal_links.append(CausalLink(
                            cause_event_id=trigger.event_id,
                            effect_event_id=event.event_id,
                            relationship="caused_by",
                            confidence=0.6,
                            explanation=f"Followed trigger by {int(time_diff)}s",
                        ))
        
        return causal_links
    
    def _calculate_impact(self, 
                          trigger: Event,
                          causal_chain: List[CausalLink],
                          timeline: List[Event]) -> Dict[str, Any]:
        """Calculate the impact of the correlated events."""
        impact = {
            "energy_kwh": 0,
            "energy_cost_qar": 0,
            "comfort_zones_affected": 0,
            "equipment_affected": [],
            "duration_minutes": 0,
        }
        
        # Calculate duration
        if timeline:
            first_event = min(timeline, key=lambda e: e.timestamp)
            last_event = max(timeline, key=lambda e: e.timestamp)
            impact["duration_minutes"] = int(
                (last_event.timestamp - first_event.timestamp).total_seconds() / 60
            )
        
        # Sum energy impact
        for event in timeline:
            if event.source == EventSource.ENERGY_METER and event.value:
                # kW * hours
                hours = impact["duration_minutes"] / 60
                impact["energy_kwh"] += event.value * hours
                # QAR calculation (0.033 standard, 0.066 peak)
                impact["energy_cost_qar"] += event.value * hours * 0.05  # Average rate
        
        # Count affected zones and equipment
        zones = set()
        equipment = set()
        for event in timeline:
            if event.zone_id:
                zones.add(event.zone_id)
            if event.equipment_id:
                equipment.add(event.equipment_id)
        
        impact["comfort_zones_affected"] = len(zones)
        impact["equipment_affected"] = list(equipment)
        
        return impact
    
    def _generate_insight(self,
                          trigger: Event,
                          causal_chain: List[CausalLink],
                          impact: Dict[str, Any]) -> str:
        """Generate human-readable insight from correlation."""
        if not causal_chain:
            return f"Event '{trigger.event_type}' occurred with no clear correlations."
        
        # Build insight
        causes = [c for c in causal_chain if c.relationship == "caused_by"]
        effects_count = len(causes)
        
        insight = f"Event '{trigger.event_type}'"
        
        if trigger.equipment_id:
            insight += f" on {trigger.equipment_id}"
        
        insight += f" triggered {effects_count} downstream effects"
        
        if impact["energy_kwh"] > 0:
            insight += f", causing ~{impact['energy_kwh']:.1f} kWh excess consumption"
        
        if impact["comfort_zones_affected"] > 0:
            insight += f" and affecting {impact['comfort_zones_affected']} zones"
        
        insight += "."
        
        return insight
    
    def _generate_recommendation(self,
                                  trigger: Event,
                                  causal_chain: List[CausalLink],
                                  impact: Dict[str, Any]) -> str:
        """Generate actionable recommendation."""
        if not causal_chain:
            return "Monitor for recurrence and document if pattern emerges."
        
        # Pattern-specific recommendations
        if trigger.source == EventSource.ACCESS_CONTROL:
            return "Consider scheduling door-open activities during cooler hours to reduce HVAC load."
        
        if trigger.source == EventSource.WEATHER:
            if "sandstorm" in trigger.event_type.lower():
                return "During sandstorms, consider temporarily sealing non-essential doors and increasing filter monitoring."
            return "Adjust HVAC pre-cooling schedule based on weather forecast."
        
        if trigger.source == EventSource.CALENDAR:
            return "Pre-condition spaces 30 minutes before scheduled events to reduce peak load."
        
        if trigger.source == EventSource.BMS_ALARM:
            return f"Address root cause ({trigger.event_type}) to prevent cascade alarms."
        
        # Generic recommendation
        if impact["energy_cost_qar"] > 100:
            return f"Pattern cost ~QAR {impact['energy_cost_qar']:.0f}. Consider preventive scheduling."
        
        return "Add pattern to Building Skillbook for future reference."
    
    def _calculate_confidence(self, causal_chain: List[CausalLink]) -> float:
        """Calculate overall confidence in correlation."""
        if not causal_chain:
            return 0.3
        
        # Average confidence of all links
        avg_confidence = sum(c.confidence for c in causal_chain) / len(causal_chain)
        
        # Boost for multiple corroborating links
        if len(causal_chain) >= 3:
            avg_confidence = min(avg_confidence + 0.1, 1.0)
        
        return round(avg_confidence, 2)


# =============================================================================
# LLM TOOL HANDLER
# =============================================================================

def correlate_events(
    trigger_event: Dict[str, Any],
    time_window_minutes: int = 30,
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Correlate a trigger event with related events from other systems.
    
    This is the LLM tool handler.
    
    Args:
        trigger_event: Event that triggered the analysis
            - source: bms_alarm, energy_meter, access_control, weather, calendar
            - event_type: Type of event
            - timestamp: When it occurred
            - equipment_id: Optional equipment ID
            - description: Description of event
        time_window_minutes: Window for finding related events (default 30)
        sources: Which sources to include (default: all)
        
    Returns:
        Correlation result with causal chain and recommendations
    """
    correlator = EventCorrelator()
    
    result = correlator.correlate(
        trigger_event=trigger_event,
        time_window_minutes=time_window_minutes,
        sources=sources,
    )
    
    return result.to_dict()


if __name__ == "__main__":
    # Test the correlator
    print("=" * 60)
    print("Event Correlator Test")
    print("=" * 60)
    
    correlator = EventCorrelator()
    
    # Add some history events
    correlator.add_event(Event(
        event_id="evt_1",
        source=EventSource.ACCESS_CONTROL,
        timestamp=datetime.now() - timedelta(minutes=10),
        event_type="door_open",
        description="Fire drill - all doors held open",
        zone_id="Zone-All",
    ))
    
    correlator.add_event(Event(
        event_id="evt_2",
        source=EventSource.HVAC,
        timestamp=datetime.now() - timedelta(minutes=5),
        event_type="load_increase",
        description="AHU-03 ramped to 100%",
        equipment_id="AHU-03",
    ))
    
    correlator.add_event(Event(
        event_id="evt_3",
        source=EventSource.ENERGY_METER,
        timestamp=datetime.now() - timedelta(minutes=3),
        event_type="spike",
        description="Energy spike detected",
        value=45.0,  # kW
    ))
    
    # Correlate the fire drill event
    result = correlator.correlate({
        "source": "access_control",
        "event_type": "door_open",
        "description": "Fire drill",
        "timestamp": datetime.now() - timedelta(minutes=10),
    })
    
    print(f"\nInsight: {result.insight}")
    print(f"Recommendation: {result.recommendation}")
    print(f"Confidence: {result.confidence}")
    print(f"Impact: {result.impact}")
