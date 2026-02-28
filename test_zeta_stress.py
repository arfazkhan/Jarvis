import asyncio
import logging
import sys
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
sys.path.append("e:\\Automation")

# MOCK HEAVY LIBRARIES (Same as original gauntlet to speed up)
import sys
from unittest.mock import MagicMock
sys.modules["tensorflow"] = None
sys.modules["chromadb"] = MagicMock()
sys.modules["agent_advisory.ml.ranking"] = MagicMock()
sys.modules["agent_advisory.online_learner"] = MagicMock()
try:
    sys.modules["agent_advisory.online_learner"].OnlineLearner = MagicMock
except:
    pass

# Imports
from agent_commercial.main import OpsCopilot
from agent_commercial.bms_data_model import AlarmSeverity
from agent_commercial.alarm_engine import Alarm
from agent_commercial.event_correlator import Event, EventSource, EventCorrelator

@dataclass
class ScenarioResult:
    name: str
    cause_found: str
    cause_confidence: float
    correlation_found: bool
    correlation_confidence: float
    insight: str

class ZetaStressTester:
    def __init__(self):
        self.copilot = None
        self.real_llm = None
        
    async def setup_system(self):
        """Initialize a fresh system for each run"""
        print("   > Initializing System...")
        self.copilot = OpsCopilot(mode="api_only")
        
        # Ensure Event Correlator
        if not hasattr(self.copilot, 'event_correlator') or self.copilot.event_correlator is None:
             self.copilot.event_correlator = EventCorrelator()
             
        # Connect Real LLM
        self.real_llm = self.copilot.llm_agent.llm
        self.copilot.alarm_engine.set_llm_provider(self.real_llm)
        self.copilot.event_correlator.set_llm_provider(self.real_llm)
        
        # Setup Topology
        await self.copilot._register_simulated_equipment()
        eq_list = await self.copilot.state_engine.get_all_equipment()
        self.copilot.alarm_engine.set_equipment_topology(eq_list)
        
    async def run_scenario(self, name: str, weather_desc: str, alarm_msg: str, maintenance_mode: bool = False) -> ScenarioResult:
        print(f"\n⚡ RUNNING SCENARIO: {name} ⚡")
        print(f"   Context: Weather='{weather_desc}', Alarm='{alarm_msg}', Maint={maintenance_mode}")
        
        await self.setup_system()
        timestamp = datetime.now()
        
        # 1. Inject Weather
        if weather_desc:
            evt = Event(
                event_id="weather_evt",
                source=EventSource.WEATHER,
                timestamp=timestamp - timedelta(minutes=10),
                event_type="Weather Update",
                description=weather_desc
            )
            self.copilot.event_correlator.add_event(evt)
            
        if maintenance_mode:
            maint_evt = Event(
                event_id="maint_mode",
                source=EventSource.BMS_ALARM, # Using generic alarm/system source as proxy
                timestamp=timestamp - timedelta(minutes=30),
                event_type="Maintenance",
                description="Chiller-01 placed in manual maintenance mode for coil cleaning."
            )
            self.copilot.event_correlator.add_event(maint_evt)
            
        # 3. Trigger Alarm
        alarm = Alarm(
            alarm_id="chiller_trip",
            equipment_id="CH-01",
            severity=AlarmSeverity.CRITICAL,
            message=alarm_msg,
            triggered_at=timestamp
        )
        await self.copilot.alarm_engine.ingest_alarm(alarm)
        
        # Force Cluster
        if not self.copilot.alarm_engine.get_clusters():
            from agent_commercial.alarm_engine import AlarmCluster
            cluster = AlarmCluster(cluster_id="force_cluster", alarm_ids=["chiller_trip"], root_cause_equipment_id="CH-01")
            self.copilot.alarm_engine.clusters["force_cluster"] = cluster
            
        # 4. Analyze Root Cause (Alarm Engine)
        cluster = self.copilot.alarm_engine.get_clusters()[0]
        rc_result = await self.copilot.alarm_engine._analyze_root_cause_with_llm(cluster)
        
        # 5. Analyze Correlation (Event Correlator)
        correlation = await self.copilot.event_correlator.correlate(alarm.to_dict())
        
        return ScenarioResult(
            name=name,
            cause_found=rc_result.get('cause', 'Unknown'),
            cause_confidence=rc_result.get('confidence', 0.0),
            correlation_found=correlation.confidence > 0.6,
            correlation_confidence=correlation.confidence,
            insight=correlation.insight
        )

async def main():
    tester = ZetaStressTester()
    results = []
    
    # SCENARIO A: BASELINE (The Shamal)
    # Expect: High confidence link to weather
    results.append(await tester.run_scenario(
        "Baseline (Shamal)", 
        "Severe Dust Storm (Shamal). Visibility < 500m. PM2.5 > 600. Temp 48C.",
        "High Discharge Pressure Trip"
    ))
    
    # SCENARIO B: PLACEBO (Clear Sky)
    # Expect: Low confidence link to weather (or different cause like internal failure)
    results.append(await tester.run_scenario(
        "Placebo (Clear Sky)",
        "Clear sky. Temp 32C. Humidity 40%. Wind Calm.",
        "High Discharge Pressure Trip"
    ))
    
    # SCENARIO C: CONFLICT (Maintenance Mode)
    # Expect: High confidence link to Maintenance content, IGNORING weather if present or finding it consistent
    results.append(await tester.run_scenario(
        "Conflict (Maintenance)",
        "Clear sky. Temp 35C.",
        "High Discharge Pressure Trip",
        maintenance_mode=True
    ))
    
    output_str = "\n\n📊 STRESS TEST RESULTS 📊\n"
    output_str += "==================================================\n"
    output_str += f"{'SCENARIO':<25} | {'CAUSE':<30} | {'CONF (RC)':<10} | {'CONF (CORR)':<10} | {'INSIGHT'}\n"
    output_str += "-" * 120 + "\n"
    
    for r in results:
        insight_short = r.insight[:40] + "..." if len(r.insight) > 40 else r.insight
        cause_short = r.cause_found[:28] + ".." if len(r.cause_found) > 28 else r.cause_found
        output_str += f"{r.name:<25} | {cause_short:<30} | {r.cause_confidence:<10.2f} | {r.correlation_confidence:<10.2f} | {insight_short}\n"
        
    print(output_str)
    with open("e:\\Automation\\stress_results.txt", "w", encoding="utf-8") as f:
        f.write(output_str)

if __name__ == "__main__":
    asyncio.run(main())
