import unittest
from unittest.mock import MagicMock
from agent_mission.mission_inference import MissionInference
from agent_sensors.sensor_models import HomeSituation, HomePresence, SleepState

class TestMissionInference(unittest.TestCase):
    
    def setUp(self):
        self.inference = MissionInference()
    
    def test_sleep_optimization_inference(self):
        print("\n[Test] Sleep Optimization Inference")
        
        # Mock situation
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.home_presence.state = "home"
        situation.activity_hint = "relaxing"  # Add missing attribute
        
        # High bedtime variance pattern
        patterns = {
            "bedtime_variance_minutes": 50,
            "irregular_sleep_count": 4
        }
        
        recommendations = self.inference.infer_mission(situation, patterns)
        
        # Should recommend sleep optimization
        sleep_recs = [r for r in recommendations if r["mission_type"] == "sleep_optimization"]
        self.assertEqual(len(sleep_recs), 1)
        self.assertGreater(sleep_recs[0]["confidence"], 0.5)
        print(f"✅ Sleep optimization recommended (confidence: {sleep_recs[0]['confidence']:.2f})")
    
    def test_energy_saver_inference(self):
        print("\n[Test] Energy Saver Inference")
        
        # Mock situation: user away
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.home_presence.state = "away"
        situation.activity_hint = None  # Add missing attribute
        
        # Away for 3 hours with idle devices
        patterns = {
            "away_duration_hours": 3,
            "idle_device_count": 5
        }
        
        recommendations = self.inference.infer_mission(situation, patterns)
        
        # Should recommend energy saver
        energy_recs = [r for r in recommendations if r["mission_type"] == "energy_saver"]
        self.assertEqual(len(energy_recs), 1)
        self.assertGreater(energy_recs[0]["confidence"], 0.7)
        print(f"✅ Energy saver recommended (confidence: {energy_recs[0]['confidence']:.2f})")
    
    def test_home_security_inference(self):
        print("\n[Test] Home Security Inference")
        
        # Mock situation: user away
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.home_presence.state = "away"
        situation.activity_hint = None  # Add missing attribute
        
        # Away for 2 hours
        patterns = {
            "away_duration_hours": 2
        }
        
        recommendations = self.inference.infer_mission(situation, patterns)
        
        # Should recommend security
        security_recs = [r for r in recommendations if r["mission_type"] == "home_security"]
        self.assertEqual(len(security_recs), 1)
        self.assertGreater(security_recs[0]["confidence"], 0.5)
        print(f"✅ Home security recommended (confidence: {security_recs[0]['confidence']:.2f})")
    
    def test_focus_productivity_inference(self):
        print("\n[Test] Focus & Productivity Inference")
        
        # Mock situation: working
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.home_presence.state = "home"
        situation.activity_hint = "working"
        
        # High work pattern consistency
        patterns = {
            "work_pattern_consistency": 0.85
        }
        
        recommendations = self.inference.infer_mission(situation, patterns)
        
        # Should recommend focus
        focus_recs = [r for r in recommendations if r["mission_type"] == "focus_productivity"]
        self.assertEqual(len(focus_recs), 1)
        self.assertGreater(focus_recs[0]["confidence"], 0.5)
        print(f"✅ Focus productivity recommended (confidence: {focus_recs[0]['confidence']:.2f})")
    
    def test_debounce_mechanism(self):
        print("\n[Test] Debounce Mechanism (48hr)")
        
        # Mock situation
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.home_presence.state = "away"
        situation.activity_hint = None  # Add missing attribute
        
        patterns = {"away_duration_hours": 3}
        
        # First inference - should recommend
        recs1 = self.inference.infer_mission(situation, patterns)
        security_recs = [r for r in recs1 if r["mission_type"] == "home_security"]
        self.assertEqual(len(security_recs), 1)
        
        # Mark as triggered
        self.inference.mark_auto_triggered("home_security")
        
        # Second inference immediately - should be blocked by debounce
        recs2 = self.inference.infer_mission(situation, patterns)
        security_recs_2 = [r for r in recs2 if r["mission_type"] == "home_security"]
        self.assertEqual(len(security_recs_2), 0)
        print("✅ Debounce prevents immediate re-triggering")
    
    def test_low_confidence_no_recommendation(self):
        print("\n[Test] Low Confidence = No Recommendation")
        
        # Mock situation with weak signals
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.home_presence.state = "home"
        situation.activity_hint = "relaxing"
        
        # Low variance, low anomalies
        patterns = {
            "bedtime_variance_minutes": 15,
            "irregular_sleep_count": 0,
            "idle_device_count": 1
        }
        
        recommendations = self.inference.infer_mission(situation, patterns)
        
        # Should have no recommendations (all below 0.5 threshold)
        self.assertEqual(len(recommendations), 0)
        print("✅ No recommendations when confidence is low")

if __name__ == "__main__":
    unittest.main()
