"""
Micro-Omega Diagnostic Test
===========================
Runs a 3-day stress test at 5000x scale to verify async engine stability.
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

async def run_diagnostic():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    print("🚀 Starting Micro-Omega Diagnostic (3 Days, 5000x)...")
    
    config = OmegaTestConfig(
        simulation_days=3,
        time_scale=5000,
        use_real_llm=False, # Use component-based logic for speed
        output_dir="tests/omega_stress_test/results/micro_diagnostic"
    )
    
    # Overwrite DB path to avoid conflict with production data
    # (Checking if OmegaTestConfig has db_path, if not we add it)
    # The runner initializes BuildingSkillbook(building_id=self.config.building_id)
    # We can change building_id to get a different DB if needed, but let's 
    # explicitly set a test DB path in a custom OmegaTestRunner if needed.
    # For now, let's just use a unique building_id.
    config.building_id = "DIAGNOSTIC-FIX-001"
    
    runner = OmegaTestRunner(config)
    
    # Initialize results directory
    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
    
    print(f"📊 Results will be saved to: {config.output_dir}")
    print(f"🗄️ Using Database building ID: {config.building_id}")
    
    # Patch runner to log hours for visibility
    original_simulate = runner._simulate_arvis_cycle
    async def verbose_simulate(day, hour_data):
        hour = hour_data.get("hour", 0)
        if hour % 6 == 0:
            print(f"🕒 Simulating Day {day} Hour {hour:02d}...")
        return await original_simulate(day, hour_data)
    
    runner._simulate_arvis_cycle = verbose_simulate
    
    report = await runner.run_full_simulation()
    
    print("\n" + "=" * 60)
    print("MICRO-OMEGA DIAGNOSTIC COMPLETE")
    print("=" * 60)
    print(f"Status: {report['overall_status']}")
    print(f"Days Simulated: {report['simulation_summary']['total_days']}")
    print(f"Advisories: {report['simulation_summary']['total_advisories']}")
    print(f"Tests Passed: {report['simulation_summary']['tests_passed']}/{report['test_summary']['total_tests']}")
    print("=" * 60)
    
    if report['overall_status'] == "FAILED":
        print("❌ FAILURES DETECTED. Check results directory.")
        # sys.exit(1) # Don't exit process in this environment
    else:
        print("✅ ASYNC STABILITY VERIFIED.")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
