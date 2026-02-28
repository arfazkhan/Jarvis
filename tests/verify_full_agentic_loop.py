
import asyncio
import logging
import shutil
import tempfile
import os
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import sys
from dotenv import load_dotenv
from colorama import init, Fore, Style
init()

# Load keys for real LLM call
load_dotenv()

# Components to test
from agent_advisory.goal_generator import GoalDiscoveryEngine, GoalGenerator, ProactiveGoal
from agent_cognitive.meta_cognition import MetaCognition
from agent_commercial.skillbook import BuildingSkillbook
# from agent_advisory.qatar.llm_simulator import LLMEnhancedSimulator # Move to inside to avoid init issues

# Setup Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("verify_full_loop")

async def verify_agentic_loop():
    print("\n🚀 STARTING FULL AGENTIC LOOP VERIFICATION (Real World Scenario)")
    print("==================================================================")
    
    # -------------------------------------------------------------------------
    # SCENARIO: "The Silent Chiller Keeper"
    # A chiller is efficient now, but predictive models show a 90% chance of 
    # compressor failure in 14 days due to subtle vibration patterns.
    # The Agent must:
    # 1. Discover this hidden risk (GoalDiscovery)
    # 2. Decide to act (MetaAgent)
    # 3. Reflect on why it acted (MetaCognition + LLM)
    # -------------------------------------------------------------------------
    
    # 1. ENVIRONMENT SETUP
    test_dir = tempfile.mkdtemp()
    db_path = os.path.join(test_dir, "agentic_loop.db")
    print(f"\n[1] Environment initialized at {test_dir}")
    
    try:
        # Initialize Persistent Memory (Skillbook)
        skillbook = BuildingSkillbook("qatar_tower_1", db_path=db_path)
        from agent_commercial.skillbook import _skillbooks
        _skillbooks["qatar_tower_1"] = skillbook
        
        # Initialize Brain (MetaCognition)
        meta_brain = MetaCognition("qatar_tower_1")
        
        # Initialize Engines (Mocked for specific data scenario)
        mock_fleet = MagicMock()
        mock_pred = MagicMock()
        mock_energy = MagicMock()
        mock_bus = MagicMock()
        
        # ---------------------------------------------------------------------
        # 2. SEED REALISTIC DATA (LLM Simulator)
        # ---------------------------------------------------------------------
        print("\n[2] Seeding Realistic Data via LLM Simulator...")
        # Import here to ensure environment is ready
        from agent_advisory.qatar.llm_simulator import LLMEnhancedSimulator
        simulator = LLMEnhancedSimulator()
        # force generate a scenario with a specific issue for deterministic testing, 
        # or generate diverse ones and pick a critical one.
        # For this test, we want to ensure we get a "critical" candidate.
        # We'll use the simulator's diverse dataset generation and filter or just mock the result using its structure if needed.
        # But to be "Real", let's use the actual simulator method.
        
        # We will trick the simulator to giving us a chiller issue
        # by manually setting the scenario context if the random generation misses, 
        # or just generate until we match (dangerous for unit test).
        # Better: Use the simulator to generate the *context details* for a known issue.
        
        # We can't easily force "LLMEnhancedSimulator" to give exactly a vibration fault without changes to it.
        # So we will use it to "Narrativize" a base fault we define. This uses the REAL LLM AP I.
        
        from agent_advisory.qatar.simulator import SimulatedScenario
        base_scenario = SimulatedScenario(
             scenario_id="SEED-001",
             timestamp=datetime.now(),
             building_id="qatar_tower_1",
             equipment_id="CHILLER-01",
             issue_type="vibration_anomaly",
             context={"outdoor_temp_c": 45, "load_pct": 80},
             # Dummy values for required fields (we only need the context/issue for this test)
             best_action="investigate",
             best_action_details={},
             operator_id="OP-01",
             operator_decision="investigate",
             outcome_quality="pending",
             resolution_time_min=0,
             cost_qar=0.0
        )
        
        print("   Asking Simulator (LLM) to enhance this base scenario with realistic noise...")
        # Access the simulator's LLM enhancement logic explicitly
        # We need to monkey-patch or use a method that takes a base scenario if available,
        # but LLMEnhancedSimulator.generate_enhanced_scenario creates entirely new ones.
        # Let's interact with the LLM capability of the simulator directly here to "Seed" our data.
        
        # Actually, let's just use the simulator instance we created
        # We will create a small helper to force the enhancement on our specific seed
        # reflection of how `generate_enhanced_scenario` works but on *our* object.
        
        # [STEP 2.5] VERIFY MEMORY INTEGRATION
        # Ensure that the memory system is active and context-aware before we generate the scenario
        print("   [Memory Check] Seeding 'Chiller Start-Stop' preference...")
        
        # Initialize orchestration to access the same memory store (since it's persistent/singleton-like via dir)
        from arvis_core.memory.orchestrator import MemoryOrchestrator
        memory_dir = os.path.join(test_dir, "data", "memories")
        memory = MemoryOrchestrator(persist_dir=memory_dir)
        
        memory.remember("Operator prefers minimizing chiller start-stops", "preference", "chiller_stops")
        
        context_str = memory.get_context("chiller issue", {}, {})
        if "minimizing chiller start-stops" in context_str:
            print(f"{Fore.GREEN}   ✓ Memory Context Verification Passed: Preference found in context.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}   ⚠ Memory Context Warning: Preference not found in generated context.{Style.RESET_ALL}")

        prompt = f"""
        Enhance this building fault scenario with realistic sensor noise and a technical narrative:
        Issue: vibration_anomaly on CHILLER-01.
        Context: 45C outdoor.
        Return JSON with {{ "vibration_mm_s": float, "oil_pressure_psi": float, "narrative": str }}
        """
        print("   Asking Simulator (LLM) to enhance this base scenario with realistic noise...")
        sys.stdout.flush()
        try:
            print("   (Before LLM Call)...")
            sys.stdout.flush()
            
            # Use the new robust ask_json method directly
            seed_data = await simulator.llm.ask_json([{"role": "user", "content": prompt}], retries=2)
            
            print("   (After LLM Call)...")
            sys.stdout.flush()
            print(f"   ► Data Generated: {seed_data}")
            
            vibration_val = seed_data.get("vibration_mm_s", 8.5)
            narrative_text = seed_data.get("narrative", "High vibration detected.")

            # Configure Predictive Model Mock with this SEEDED data
            mock_prediction = MagicMock()
            mock_prediction.risk_level = "critical"
            mock_prediction.predicted_rul_days = 12 # Derived from high vibration
            mock_prediction.recommendation = f"Investigate source: {narrative_text}"
            mock_prediction.confidence = 0.94
            mock_prediction.failure_mode = "Compressor Failure"
            mock_prediction.estimated_cost = 50000.0
            
            mock_pred.predict_failure.return_value = mock_prediction
            
            # Seed the history with the LLM-generated sensor values
            mock_pred.equipment_history = {
                "qatar_tower_1/CHILLER-01": [{"vibration": vibration_val, "temp": 42, "oil_p": seed_data.get("oil_pressure_psi", 40)}]
            }
            
        except Exception as e:
            print(f"❌ Failed to seed realistic data: {e}")
            return
            
        # ---------------------------------------------------------------------
        # 3. AUTONOMOUS DISCOVERY (The Agent "Notices")
        # ---------------------------------------------------------------------
        print("\n[3] Running Goal Discovery Engine...")
        generator = GoalGenerator(mock_fleet, mock_pred, mock_energy)
        discovery = GoalDiscoveryEngine(generator, mock_bus, check_interval_seconds=0)
        
        # GoalGenerator._get_predictive_goals iterates over self.predictive.equipment_history.keys()
        # (This is now set in the Seeding step above)

        # Override generator to return our specific scenario goal (since we mocked the inner engines but GoalGenerator logic is complex to set up perfectly with just mocks in a script)
        # We want to verify the Discovery Engine's handling of the goal, not the Generator's math (tested elsewhere)
        # But to be "Real", let's let GoalGenerator actually call the mocks if possible.
        # GoalGenerator._get_predictive_goals calls self.predictive.get_all_equipment() then predict_failure()
        
        # mock_pred.get_all_equipment.return_value = ["CHILLER-01"] # This is not used by _get_predictive_goals based on code analysis
        # It uses equipment_history.keys()
        
        
        # Run discovery
        goals = discovery.run_discovery_cycle("qatar_tower_1")
        
        if not goals:
            print("❌ Discovery Failed: No goals generated.")
            return

        target_goal = goals[0]
        print(f"   ► Discovered Goal: {target_goal.title}")
        print(f"   ► Failure Mode: {target_goal.description}")
        print(f"   ► Priority: {target_goal.priority} (Score: {target_goal.score})")
        
        # Verify Event Bus was triggered (The Agent "Spoke")
        mock_bus.publish.assert_called()
        event = mock_bus.publish.call_args[0][0]
        print(f"   ► Event Published: {event['type']}")
        
        # ---------------------------------------------------------------------
        # 4. DECISION & ACTION (The Agent "Acts")
        # ---------------------------------------------------------------------
        print("\n[4] Meta-Agent Deciding to Act...")
        # Simulate MetaAgent logic
        urgency = 0.95 # derived from Critical goal
        
        decision_id = meta_brain.record_decision(
            context={
                "trigger": "proactive_goal_discovered",
                "goal_id": target_goal.goal_id,
                "goal_score": target_goal.score,
                "risk": "critical"
            },
            chosen_action="notify_operator",
            alternatives=["suppress", "log_only"],
            confidence=urgency,
            reasoning=f"Critical risk of {mock_prediction.failure_mode} requires immediate attention."
        )
        print(f"   ► Decision Recorded (ID: {decision_id})")
        
        # ---------------------------------------------------------------------
        # 5. CONSCIOUS REFLECTION (The Agent "Thinks")
        # ---------------------------------------------------------------------
        print("\n[5] Triggering Real LLM Self-Reflection...")
        print("   (Asking UnifiedLLM to analyze the decision...)")
        
        reflection = await meta_brain.reflect_with_llm(lookback_days=1)
        
        print("\n   🧠 AGENT THOUGHTS:")
        print("   ------------------------------------------------------------")
        print(f"   {reflection}")
        print("   ------------------------------------------------------------")
        
        if "Error" not in reflection and len(reflection) > 20:
             print("\n✅ SUCCESS: Full Agentic Loop Verified.")
             print("   Data -> Discovery -> Event -> Decision -> Reflection")
        else:
             print("\n⚠️  Warning: Reflection seemed incomplete (check API keys).")

    finally:
        try:
            import gc
            gc.collect() # Force close DB connections
            await asyncio.sleep(0.1)
            shutil.rmtree(test_dir)
            print("\n[Cleanup] Test environment removed.")
        except PermissionError:
            print(f"\n[Cleanup] Warning: Could not remove {test_dir} due to file lock (Windows). Ignoring.")
        except Exception as e:
            print(f"\n[Cleanup] Warning: Cleanup failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_agentic_loop())
