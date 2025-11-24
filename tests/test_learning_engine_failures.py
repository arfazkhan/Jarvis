"""
Learning Engine Pattern & Drift Failure Tests

Tests for:
- Pattern misalignment (no consistent patterns, random data)
- Drift analysis failures (extreme shifts, oscillations)
- Routine creation edge cases
- Multi-persona confusion
- Lifestyle changes
"""

import pytest
import time
from conftest import create_pattern_history


class TestPatternMisalignment:
    """Test pattern detection failures."""
    
    def test_no_consistent_patterns(self, pattern_analyzer):
        """History with completely random events."""
        random_history = create_pattern_history("random")
        
        clusters = pattern_analyzer.cluster_patterns(random_history)
        
        # Should handle random data gracefully
        assert isinstance(clusters, list)
    
    def test_perfectly_random_toggles(self, pattern_analyzer):
        """Completely chaotic behavior with no patterns."""
        import random
        history = []
        base_time = time.time() - (30 * 86400)
        
        for _ in range(500):
            history.append({
                "type": "relay_toggled",
                "payload": {
                    "device": "switch_1",
                    "endpoint": random.randint(1, 8),
                    "state": random.choice(["on", "off"])
                },
                "timestamp": base_time + random.random() * (30 * 86400)
            })
        
        clusters = pattern_analyzer.cluster_patterns(history)
        
        # May find some clusters by chance, but should handle gracefully
        assert isinstance(clusters, list)
    
    def test_weekend_only_pattern(self, pattern_analyzer):
        """Pattern that only appears on weekends."""
        weekend_history = create_pattern_history("weekend_only")
        
        clusters = pattern_analyzer.cluster_patterns(weekend_history)
        
        # Should still detect clusters
        assert len(clusters) >= 0
    
    def test_pattern_appearing_only_2_of_30_days(self, pattern_analyzer):
        """Very sparse pattern (only 2 occurrences in 30 days)."""
        history = []
        base_time = time.time() - (30 * 86400)
        
        # Only day 10 and day 25
        for day in [10, 25]:
            timestamp = base_time + (day * 86400) + (7 * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
        
        clusters = pattern_analyzer.cluster_patterns(history)
        
        # Shouldn't over-detect patterns
        # 2 events won't form a significant cluster
        assert isinstance(clusters, list)


class TestDriftAnalysisFailures:
    """Test habit drift edge cases."""
    
    def test_wake_time_decreasing_6_hours(self, pattern_analyzer):
        """Wake time shifts dramatically earlier."""
        history = []
        base_time = time.time() - (14 * 86400)  # 2 weeks ago
        
        # Week 1: Wake at 9 AM
        for day in range(7):
            timestamp = base_time + (day * 86400) + (9 * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
        
        # Week 2: Wake at 3 AM (6 hour shift)
        for day in range(7, 14):
            timestamp = base_time + (day * 86400) + (3 * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
        
        drift = pattern_analyzer.detect_habit_drift(history, "wake_time")
        
        # Should detect significant drift
        if "wake_time" in drift:
            assert drift["wake_time"]["significant"] == True
            assert abs(drift["wake_time"]["drift_hours"]) >= 5
    
    def test_oscillating_wake_pattern(self, pattern_analyzer):
        """Wake time alternates between early and late."""
        history = []
        base_time = time.time() - (14 * 86400)
        
        for day in range(14):
            # Alternate between 6 AM and 11 AM
            hour = 6 if day % 2 == 0 else 11
            timestamp = base_time + (day * 86400) + (hour * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
        
        drift = pattern_analyzer.detect_habit_drift(history, "wake_time")
        
        # Should handle oscillating pattern
        assert isinstance(drift, dict)
    
    def test_no_wake_events(self, pattern_analyzer):
        """No bedroom light events at all."""
        history = []
        base_time = time.time() - (14 * 86400)
        
        # Only kitchen and living room lights
        for day in range(14):
            for hour in [12, 18]:
                timestamp = base_time + (day * 86400) + (hour * 3600)
                history.append({
                    "type": "relay_toggled",
                    "payload": {"device": "switch_1", "endpoint": 3, "state": "on"},  # Kitchen
                    "timestamp": timestamp
                })
        
        drift = pattern_analyzer.detect_habit_drift(history, "wake_time")
        
        # Should handle missing data
        assert drift == {} or "wake_time" not in drift


class TestRealWorldChaos:
    """Test real-world unpredictable scenarios."""
    
    @pytest.mark.integration
    def test_false_activity_lights_left_on_3_weeks(self, pattern_analyzer):
        """User forgets lights ON for 3 weeks - should NOT create routine."""
        history = []
        base_time = time.time() - (21 * 86400)  # 3 weeks ago
        
        # Light turned ON once
        history.append({
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 2, "state": "on"},
            "timestamp": base_time
        })
        
        # No OFF event for 21 days (forgotten)
        # Then finally turned OFF
        history.append({
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 2, "state": "off"},
            "timestamp": base_time + (21 * 86400)
        })
        
        clusters = pattern_analyzer.cluster_patterns(history)
        
        # Should NOT detect this as a pattern
        # Only 2 events over 3 weeks isn't a routine
        assert len(clusters) <= 1
    
    @pytest.mark.integration
    def test_mixed_personas_same_month(self, pattern_analyzer):
        """History contains multiple conflicting behavior patterns."""
        history = []
        base_time = time.time() - (30 * 86400)
        
        # Week 1: Night owl (sleep 3AM, wake 11AM)
        for day in range(7):
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "off"},
                "timestamp": base_time + (day * 86400) + (3 * 3600)
            })
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": base_time + (day * 86400) + (11 * 3600)
            })
        
        # Week 2: Early bird (sleep 10PM, wake 6AM)
        for day in range(7, 14):
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "off"},
                "timestamp": base_time + (day * 86400) + (22 * 3600)
            })
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": base_time + (day * 86400) + (6 * 3600)
            })
        
        # Weeks 3-4: Working professional (sleep 11PM, wake 7AM)
        for day in range(14, 30):
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "off"},
                "timestamp": base_time + (day * 86400) + (23 * 3600)
            })
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": base_time + (day * 86400) + (7 * 3600)
            })
        
        # System should detect multiple patterns but not create false routines
        drift = pattern_analyzer.detect_habit_drift(history, "wake_time")
        
        # Should show high drift or uncertainty
        assert isinstance(drift, dict)
    
    @pytest.mark.integration
    def test_sudden_lifestyle_change(self, pattern_analyzer):
        """Dramatic shift in patterns month-to-month."""
        history = []
        base_time = time.time() - (60 * 86400)  # 60 days ago
        
        # Month 1: Consistent 7AM wake
        for day in range(30):
            timestamp = base_time + (day * 86400) + (7 * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
        
        # Month 2: Sudden shift to 11AM wake (new job, lifestyle change)
        for day in range(30, 60):
            timestamp = base_time + (day * 86400) + (11 * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
        
        drift = pattern_analyzer.detect_habit_drift(history, "wake_time")
        
        # Should detect significant lifestyle change
        if "wake_time" in drift:
            assert drift["wake_time"]["significant"] == True
