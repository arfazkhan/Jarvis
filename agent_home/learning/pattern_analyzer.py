"""
Pattern Analyzer for Home Agent Learning Engine

Provides advanced pattern recognition capabilities:
- Anomaly detection
- Pattern clustering
- Habit drift detection
- Statistical analysis of behavior patterns
"""

import time
from datetime import datetime, timedelta
from collections import defaultdict
import statistics


class PatternAnalyzer:
    """Analyzes historical events to detect patterns, anomalies, and trends."""
    
    def __init__(self):
        self.baseline_patterns = {}
        self.anomaly_threshold = 2.0  # Standard deviations for anomaly detection
        
    def detect_anomalies(self, history, lookback_days=7):
        """
        Detect unusual events that deviate from established patterns.
        
        Returns list of anomalies with context.
        """
        anomalies = []
        now = time.time()
        recent_cutoff = now - (lookback_days * 86400)
        
        # Filter to recent history
        recent_events = [e for e in history if e.get("timestamp", 0) > recent_cutoff]
        
        if len(recent_events) < 10:
            return []  # Not enough data
        
        # Group events by type
        events_by_type = defaultdict(list)
        for event in recent_events:
            event_type = event.get("type")
            events_by_type[event_type].append(event)
        
        # Detect time-based anomalies for relay_toggled events
        if "relay_toggled" in events_by_type:
            relay_events = events_by_type["relay_toggled"]
            time_anomalies = self._detect_time_anomalies(relay_events)
            anomalies.extend(time_anomalies)
        
        # Detect frequency anomalies
        frequency_anomalies = self._detect_frequency_anomalies(events_by_type, recent_cutoff)
        anomalies.extend(frequency_anomalies)
        
        return anomalies
    
    def _detect_time_anomalies(self, events):
        """Detect events happening at unusual times."""
        anomalies = []
        
        # Group by endpoint and state
        by_endpoint_state = defaultdict(list)
        for event in events:
            endpoint = event.get("payload", {}).get("endpoint")
            state = event.get("payload", {}).get("state")
            timestamp = event.get("timestamp", 0)
            
            if endpoint and state:
                key = f"ep{endpoint}_{state}"
                hour = datetime.fromtimestamp(timestamp).hour
                by_endpoint_state[key].append(hour)
        
        # Calculate mean and std for each endpoint/state combo
        for key, hours in by_endpoint_state.items():
            if len(hours) < 5:
                continue
                
            mean_hour = statistics.mean(hours)
            if len(hours) > 1:
                std_hour = statistics.stdev(hours)
            else:
                std_hour = 0
            
            # Check if any event is more than 2 std devs away
            for i, hour in enumerate(hours):
                if std_hour > 0:
                    z_score = abs(hour - mean_hour) / std_hour
                    if z_score > self.anomaly_threshold:
                        anomalies.append({
                            "type": "time_anomaly",
                            "description": f"{key} at unusual time: {hour}:00 (normally ~{int(mean_hour)}:00)",
                            "severity": "medium" if z_score < 3 else "high",
                            "timestamp": events[i].get("timestamp")
                        })
        
        return anomalies
    
    def _detect_frequency_anomalies(self, events_by_type, start_time):
        """Detect unusual frequency of events."""
        anomalies = []
        duration_days = (time.time() - start_time) / 86400
        
        for event_type, events in events_by_type.items():
            events_per_day = len(events) / max(duration_days, 1)
            
            # Flag if extremely high or low frequency
            if event_type == "relay_toggled":
                if events_per_day > 50:  # More than 50 toggles per day seems high
                    anomalies.append({
                        "type": "frequency_anomaly",
                        "description": f"Unusually high relay toggle frequency: {events_per_day:.1f}/day",
                        "severity": "medium"
                    })
                elif events_per_day < 2 and len(events) > 0:  # Very low activity
                    anomalies.append({
                        "type": "frequency_anomaly",
                        "description": f"Unusually low activity: {events_per_day:.1f}/day",
                        "severity": "low"
                    })
        
        return anomalies
    
    def cluster_patterns(self, history, time_window_hours=2):
        """
        Group similar events together using time-based clustering.
        
        Returns clusters of events that tend to happen together.
        """
        clusters = []
        
        # Sort by timestamp
        sorted_events = sorted(history, key=lambda e: e.get("timestamp", 0))
        
        current_cluster = []
        last_timestamp = 0
        time_window_seconds = time_window_hours * 3600
        
        for event in sorted_events:
            timestamp = event.get("timestamp", 0)
            
            # Skip simulation/historical events if they're too old
            if time.time() - timestamp > (30 * 86400):
                continue
            
            # Start new cluster if gap is too large
            if current_cluster and (timestamp - last_timestamp) > time_window_seconds:
                if len(current_cluster) >= 2:  # Only keep clusters with multiple events
                    clusters.append({
                        "events": current_cluster.copy(),
                        "start_time": current_cluster[0].get("timestamp"),
                        "end_time": current_cluster[-1].get("timestamp"),
                        "event_count": len(current_cluster)
                    })
                current_cluster = []
            
            current_cluster.append(event)
            last_timestamp = timestamp
        
        # Add final cluster
        if len(current_cluster) >= 2:
            clusters.append({
                "events": current_cluster.copy(),
                "start_time": current_cluster[0].get("timestamp"),
                "end_time": current_cluster[-1].get("timestamp"),
                "event_count": len(current_cluster)
            })
        
        return clusters
    
    def detect_habit_drift(self, history, pattern_type="wake_time"):
        """
        Detect gradual changes in habits over time.
        
        Patterns:
        - wake_time: First bedroom light ON each day
        - bedtime: Last light OFF each day
        - dinner_time: Evening kitchen activity
        """
        trends = {}
        
        # Group events by day
        events_by_day = defaultdict(list)
        for event in history:
            timestamp = event.get("timestamp", 0)
            day = datetime.fromtimestamp(timestamp).date()
            events_by_day[day].append(event)
        
        # Analyze wake time drift
        if pattern_type == "wake_time":
            wake_times = []
            for day, events in sorted(events_by_day.items()):
                # Find first bedroom light ON
                for event in sorted(events, key=lambda e: e.get("timestamp", 0)):
                    if event.get("type") == "relay_toggled":
                        payload = event.get("payload") or {}
                        if payload.get("endpoint") == 1 and payload.get("state") == "on":
                            hour = datetime.fromtimestamp(event.get("timestamp")).hour
                            minute = datetime.fromtimestamp(event.get("timestamp")).minute
                            wake_times.append((day, hour + minute/60))
                            break
            
            if len(wake_times) >= 7:
                # Calculate weekly averages
                weekly_avgs = self._calculate_weekly_averages(wake_times)
                
                # Detect drift (getting later or earlier)
                if len(weekly_avgs) >= 2:
                    drift = weekly_avgs[-1] - weekly_avgs[0]
                    trends["wake_time"] = {
                        "current_avg": weekly_avgs[-1],
                        "previous_avg": weekly_avgs[0],
                        "drift_hours": drift,
                        "direction": "later" if drift > 0 else "earlier",
                        "significant": abs(drift) > 0.5  # More than 30 min change
                    }
        
        # Analyze bedtime drift
        elif pattern_type == "bedtime":
            bedtimes = []
            for day, events in sorted(events_by_day.items()):
                # Find last light OFF
                sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0), reverse=True)
                for event in sorted_events:
                    if event.get("type") == "relay_toggled":
                        payload = event.get("payload") or {}
                        if payload.get("state") == "off":
                            hour = datetime.fromtimestamp(event.get("timestamp")).hour
                            minute = datetime.fromtimestamp(event.get("timestamp")).minute
                            bedtimes.append((day, hour + minute/60))
                            break
            
            if len(bedtimes) >= 7:
                weekly_avgs = self._calculate_weekly_averages(bedtimes)
                if len(weekly_avgs) >= 2:
                    drift = weekly_avgs[-1] - weekly_avgs[0]
                    trends["bedtime"] = {
                        "current_avg": weekly_avgs[-1],
                        "previous_avg": weekly_avgs[0],
                        "drift_hours": drift,
                        "direction": "later" if drift > 0 else "earlier",
                        "significant": abs(drift) > 0.5
                    }
        
        return trends
    
    def _calculate_weekly_averages(self, time_series):
        """Calculate weekly averages from time series data."""
        if not time_series:
            return []
        
        # Group by week
        weekly_data = defaultdict(list)
        for day, value in time_series:
            week = day.isocalendar()[1]  # ISO week number
            weekly_data[week].append(value)
        
        # Calculate averages
        weekly_avgs = []
        for week in sorted(weekly_data.keys()):
            avg = statistics.mean(weekly_data[week])
            weekly_avgs.append(avg)
        
        return weekly_avgs
    
    def summarize_patterns(self, history):
        """
        Generate a human-readable summary of detected patterns.
        """
        summary = {
            "total_events": len(history),
            "anomalies": self.detect_anomalies(history),
            "clusters": self.cluster_patterns(history),
            "wake_drift": self.detect_habit_drift(history, "wake_time"),
            "bed_drift": self.detect_habit_drift(history, "bedtime")
        }
        
        return summary
    
    def get_top_patterns(self, history=None, limit=10):
        """
        Get top discovered patterns sorted by confidence/frequency.
        
        This method is called by the API to return discovered patterns.
        
        Args:
            history: Optional history list. If not provided, uses internal patterns.
            limit: Maximum number of patterns to return.
            
        Returns:
            List of pattern dictionaries with id, pattern, confidence, occurrences.
        """
        patterns = []
        
        # If history is provided, analyze it
        if history:
            # Get clusters as patterns
            clusters = self.cluster_patterns(history)
            for i, cluster in enumerate(clusters):
                # Calculate confidence based on cluster size
                confidence = min(0.95, 0.5 + (cluster["event_count"] * 0.05))
                
                # Generate pattern description from events
                event_types = set(e.get("type") for e in cluster["events"])
                description = f"Cluster of {cluster['event_count']} events: {', '.join(event_types)}"
                
                patterns.append({
                    "id": f"cluster_{i}",
                    "pattern": description,
                    "confidence": round(confidence, 2),
                    "occurrences": cluster["event_count"],
                    "last_seen": cluster.get("end_time"),
                    "type": "cluster"
                })
            
            # Get anomalies as patterns (lower confidence)
            anomalies = self.detect_anomalies(history)
            for i, anomaly in enumerate(anomalies):
                patterns.append({
                    "id": f"anomaly_{i}",
                    "pattern": anomaly.get("description", "Unknown anomaly"),
                    "confidence": 0.6,
                    "occurrences": 1,
                    "last_seen": anomaly.get("timestamp"),
                    "type": "anomaly",
                    "severity": anomaly.get("severity", "medium")
                })
            
            # Get habit drift as patterns
            wake_drift = self.detect_habit_drift(history, "wake_time")
            if wake_drift.get("wake_time", {}).get("significant"):
                drift_info = wake_drift["wake_time"]
                patterns.append({
                    "id": "wake_time_drift",
                    "pattern": f"Wake time drifting {drift_info['direction']} by {abs(drift_info['drift_hours']):.1f} hours",
                    "confidence": 0.75,
                    "occurrences": 7,  # Based on weekly analysis
                    "type": "habit_drift"
                })
        
        # Add any baseline patterns stored internally
        for pattern_id, data in self.baseline_patterns.items():
            patterns.append({
                "id": pattern_id,
                "pattern": data.get("description", ""),
                "confidence": data.get("confidence", 0.5),
                "occurrences": data.get("count", 0),
                "last_seen": data.get("last_seen"),
                "type": "baseline"
            })
        
        # Sort by confidence descending
        patterns.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return patterns[:limit]
    
    def add_pattern(self, pattern_id: str, description: str, confidence: float = 0.5):
        """
        Add a discovered pattern to the baseline patterns.
        
        Args:
            pattern_id: Unique identifier for the pattern
            description: Human-readable pattern description
            confidence: Confidence score (0-1)
        """
        self.baseline_patterns[pattern_id] = {
            "description": description,
            "confidence": confidence,
            "count": 1,
            "last_seen": time.time()
        }
    
    def promote_pattern(self, pattern_id: str) -> bool:
        """
        Promote a pattern to a higher confidence level.
        
        Args:
            pattern_id: ID of the pattern to promote
            
        Returns:
            True if pattern was found and promoted, False otherwise
        """
        if pattern_id in self.baseline_patterns:
            self.baseline_patterns[pattern_id]["confidence"] = min(
                1.0, 
                self.baseline_patterns[pattern_id]["confidence"] + 0.1
            )
            return True
        return False
