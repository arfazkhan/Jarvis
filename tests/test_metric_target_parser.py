import unittest
from agent_mission.utils.mission_utils import MetricTargetParser

class TestMetricTargetParser(unittest.TestCase):
    
    def test_parse_less_than_target(self):
        print("\n[Test] Parse '<' Target")
        
        operator, threshold, unit = MetricTargetParser.parse("< 30 minutes")
        
        self.assertEqual(operator, "<")
        self.assertEqual(threshold, 30.0)
        self.assertEqual(unit, "minutes")
        print("✅ '<' target parsed correctly")
    
    def test_parse_greater_than_target(self):
        print("\n[Test] Parse '>' Target")
        
        operator, threshold, unit = MetricTargetParser.parse("> 0.8")
        
        self.assertEqual(operator, ">")
        self.assertEqual(threshold, 0.8)
        self.assertEqual(unit, "")
        print("✅ '>' target parsed correctly")
    
    def test_create_validator_less_than(self):
        print("\n[Test] Create Validator '<'")
        
        validator = MetricTargetParser.create_validator("< 30")
        
        self.assertTrue(validator(25))
        self.assertFalse(validator(35))
        print("✅ '<' validator works")
    
    def test_create_validator_greater_than(self):
        print("\n[Test] Create Validator '>'")
        
        validator = MetricTargetParser.create_validator("> 0.8")
        
        self.assertTrue(validator(0.9))
        self.assertFalse(validator(0.7))
        print("✅ '>' validator works")
    
    def test_validate_metric(self):
        print("\n[Test] Validate Metric")
        
        # Test "< 30 minutes" with value 25
        self.assertTrue(MetricTargetParser.validate("< 30", 25))
        self.assertFalse(MetricTargetParser.validate("< 30", 35))
        
        # Test "> 0.8" with value 0.9
        self.assertTrue(MetricTargetParser.validate("> 0.8", 0.9))
        self.assertFalse(MetricTargetParser.validate("> 0.8", 0.7))
        
        print("✅ Metric validation works")

if __name__ == "__main__":
    unittest.main()
