"""
Ω∞ Omega Infinity: Full 90-Day Stress Test
=========================================
Executes the complete ARVIS validation suite under extreme time scaling.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tests.omega_stress_test.omega_test_runner import OmegaTestRunner, OmegaTestConfig

async def run_infinity():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("omega_infinity_execution.log"),
            logging.StreamHandler()
        ]
    )
    
    print("\n" + "█" * 80)
    print("   Ω∞ ARVIS OMEGA INFINITY: 90-DAY STRESS TEST INITIALIZING")
    print("█" * 80 + "\n")
    
    config = OmegaTestConfig(
        simulation_days=90,
        time_scale=5000,
        use_real_llm=True,  # Full cognitive immersion
        output_dir="tests/omega_stress_test/results/infinity_run"
    )
    
    # Use production-scale building ID for the final run
    config.building_id = "DOHA-TOWER-001"
    
    runner = OmegaTestRunner(config)
    
    # Initialize results directory
    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
    
    print(f"🚀 SCALE: {config.time_scale}x (5000x targeted)")
    print(f"🧠 INTELLIGENCE: REAL LLM (Unified)")
    print(f"📊 OUTPUT: {config.output_dir}")
    print(f"🗄️ BUILDING: {config.building_id}")
    print("-" * 80)
    
    # Patch runner for cleaner console output
    original_simulate = runner._simulate_arvis_cycle
    async def verbose_simulate(day, hour_data):
        hour = hour_data.get("hour", 0)
        if hour == 0:
            print(f"📅 STARTING DAY {day:02d}...")
        elif hour % 6 == 0:
            # Check if there were advisories today for progress feedback
            print(f"   🕒 Day {day} Hour {hour:02d} | Scaling active...")
        return await original_simulate(day, hour_data)
    
    runner._simulate_arvis_cycle = verbose_simulate
    
    try:
        report = await runner.run_full_simulation()
        
        print("\n" + "█" * 80)
        print("   Ω∞ OMEGA INFINITY COMPLETE")
        print("█" * 80)
        print(f"   Final Status: {report.get('overall_status', 'UNKNOWN')}")
        print(f"   Total Advisories: {report.get('simulation_summary', {}).get('total_advisories', 0)}")
        print(f"   Tests Passed: {report.get('simulation_summary', {}).get('tests_passed', 0)}/{report.get('test_summary', {}).get('total_tests', 0)}")
        print(f"   Results saved to: {config.output_dir}")
        print("█" * 80 + "\n")
        
    except KeyboardInterrupt:
        print("\n⚠️ Simulation interrupted by user.")
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_infinity())
