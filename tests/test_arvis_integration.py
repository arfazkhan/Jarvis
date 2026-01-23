
"""
Integration Test for ARVIS Ops Copilot - New Capabilities
"""
import sys
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis_test")

try:
    from agent_bms.event_correlator import EventCorrelator, Event
    from agent_bms.skillbook import get_skillbook, SkillType
    from agent_bms.briefing_engine import BriefingGenerator, BriefingPeriod
    from agent_bms.simulator import WhatIfSimulator, ChangeType
    from agent_bms.fleet_intelligence import get_fleet_intelligence
    from agent_bms.tools_schema import BMS_TOOLS
except ImportError as e:
    logger.error(f"❌ Import failed at top level: {e}")
    sys.exit(1)

def test_engines():
    """Test initializing all engines."""
    logger.info("Testing engine initialization...")
    try:
        # Event Correlator
        correlator = EventCorrelator()
        logger.info("✅ Event Correlator initialized")
        
        # Skillbook (using memory db or temp file)
        skillbook = get_skillbook("test_building")
        skillbook.add_skill("pattern", "Test Skill", "Description")
        logger.info("✅ Skillbook initialized and written to")
        
        # Briefing Generator
        briefing_gen = BriefingGenerator("test_building")
        briefing = briefing_gen.generate("overnight")
        logger.info(f"✅ Briefing generated: {len(briefing.critical)} critical items")
        
        # Simulator
        simulator = WhatIfSimulator("test_building")
        sim_result = simulator.simulate({
            "change_type": "setpoint", 
            "current_value": 22, 
            "proposed_value": 23
        })
        logger.info(f"✅ Simulation ran: {sim_result.recommendation}")
        
        # Fleet Intelligence
        fleet = get_fleet_intelligence(["b1", "b2"])
        fleet.update_metrics("b1", {"eui": 150})
        fleet.update_metrics("b2", {"eui": 120})
        benchmark = fleet.benchmark_building("b1")
        logger.info(f"✅ Fleet benchmark ran: b1 is {benchmark.percentile_rank['eui']}th percentile")
        
        return True
    except Exception as e:
        logger.error(f"❌ Engine test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tools_schema():
    """Verify new tools are in schema."""
    logger.info("Testing tools schema...")
    try:
        from agent_bms.tools_schema import BMS_TOOLS
        tool_names = [t["name"] for t in BMS_TOOLS]
        
        required = [
            "analyze_cascade",
            "predict_remaining_life",
            "correlate_events",
            "simulate_change",
            "generate_briefing",
            "query_skillbook",
            "compare_to_fleet"
        ]
        
        missing = [t for t in required if t not in tool_names]
        
        if missing:
            logger.error(f"❌ Missing tools: {missing}")
            return False
            
        logger.info(f"✅ All {len(required)} new tools found in schema")
        return True
    except Exception as e:
        logger.error(f"❌ Schema test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_engines() and test_tools_schema()
    sys.exit(0 if success else 1)
