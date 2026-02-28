"""
ARVIS ML-LLM Hybrid Battle Test
================================

Aggressive testing with real-world ideal and practical scenarios.
Tests the full ML-LLM pipeline with K2 Think integration.
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment FIRST (critical for K2 Think API key)
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

print("=" * 70)
print("ARVIS ML-LLM HYBRID BATTLE TEST")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"K2THINK_API_KEY: {'✅ Set' if os.environ.get('K2THINK_API_KEY') else '❌ Missing'}")
print(f"K2THINK_MODEL: {os.environ.get('K2THINK_MODEL', 'Not set')}")
print("=" * 70)

from agent_commercial.tools_schema import BMSToolHandler


# =============================================================================
# TEST SCENARIOS
# =============================================================================

FAULT_DETECTION_SCENARIOS = [
    # Scenario 1: AHU with frozen coil (extreme cold SAT)
    {
        "name": "AHU Frozen Coil",
        "description": "AHU-03 supply air temp too cold, possible frozen coil",
        "args": {
            "equipment_id": "AHU-03",
            "equipment_type": "ahu",
            "sensor_data": {
                "sat": 8.5,           # Way too cold (should be ~14°C)
                "sat_setpoint": 14,
                "rat": 24.0,
                "mat": 16.0,
                "fan_speed": 1450,
                "damper_position": 90,
                "filter_dp": 180,      # Normal
            }
        },
        "expected": ["SAT", "cold", "coil"],
    },
    # Scenario 2: Chiller with condenser fouling
    {
        "name": "Chiller Condenser Fouling",
        "description": "CH-01 high condenser approach temp indicates fouling",
        "args": {
            "equipment_id": "CH-01",
            "equipment_type": "chiller",
            "sensor_data": {
                "evap_approach": 3.5,         # Normal
                "condenser_approach": 8.2,    # HIGH - fouling!
                "lift": 32,                   # Normal
                "chws_temp": 6.5,
                "chwr_temp": 12.0,
                "cws_temp": 32.0,
                "cwr_temp": 37.5,
            }
        },
        "expected": ["condenser", "approach", "fouling"],
    },
    # Scenario 3: VAV stuck damper
    {
        "name": "VAV Stuck Damper",
        "description": "VAV-Floor3-01 damper stuck while zone overheating",
        "args": {
            "equipment_id": "VAV-F3-01",
            "equipment_type": "vav",
            "sensor_data": {
                "damper_pos": 35,
                "prev_damper_pos": 35,       # Same as current - stuck!
                "zone_temp": 26.5,           # Hot!
                "zone_setpoint": 22,
                "airflow_cfm": 180,
            }
        },
        "expected": ["damper", "stuck", "zone"],
    },
    # Scenario 4: AHU dirty filter
    {
        "name": "AHU Dirty Filter",
        "description": "AHU-01 high filter differential pressure",
        "args": {
            "equipment_id": "AHU-01",
            "equipment_type": "ahu",
            "sensor_data": {
                "sat": 14.2,
                "sat_setpoint": 14,
                "rat": 24.0,
                "mat": 18.0,
                "fan_speed": 1520,           # Running harder
                "damper_position": 75,
                "filter_dp": 380,            # HIGH - dirty filter!
            }
        },
        "expected": ["filter", "pressure", "clean"],
    },
]

SIMULATION_SCENARIOS = [
    # Scenario 1: Raise setpoint during peak hours (energy saving)
    {
        "name": "Peak Hour Setpoint Raise",
        "description": "Raise cooling setpoint from 22°C to 24°C during peak tariff",
        "args": {
            "change_type": "setpoint",
            "current_value": 22,
            "proposed_value": 24,
            "building_id": "HQ-Tower",
        },
        "expected_keys": ["energy_impact", "cost_impact_qar", "risk_of_reversion"],
    },
    # Scenario 2: Lower setpoint for executive floor (comfort priority)
    {
        "name": "Executive Floor Comfort",
        "description": "Lower setpoint from 23°C to 21°C for CEO floor",
        "args": {
            "change_type": "setpoint",
            "current_value": 23,
            "proposed_value": 21,
            "building_id": "HQ-Tower",
        },
        "expected_keys": ["energy_impact", "comfort_impact"],
    },
    # Scenario 3: Night setback schedule change
    {
        "name": "Night Setback Optimization",
        "description": "Extend night setback from 10PM to 8PM during Ramadan",
        "args": {
            "change_type": "schedule",
            "current_value": 22,        # Start at 10PM (22:00)
            "proposed_value": 20,       # Start at 8PM (20:00)
            "building_id": "Office-A",
        },
        "expected_keys": ["energy_impact", "simulation"],
    },
]

ROOT_CAUSE_SCENARIOS = [
    # Scenario 1: Chiller cascade - one chiller trips, causes cascade
    {
        "name": "Chiller Trip Cascade",
        "description": "CH-02 trip causes cascade across cooling system",
        "args": {
            "alarm_ids": [
                "ALM-CH02-TRIP",       # Root cause
                "ALM-CHW-LOW-PRESS",   # Effect
                "ALM-AHU01-HIGH-SAT",  # Effect
                "ALM-AHU02-HIGH-SAT",  # Effect
                "ALM-ZONE-HIGH-TEMP",  # Effect
            ],
            "time_window_minutes": 30,
        },
        "expected": ["cascade", "root", "chiller"],
    },
    # Scenario 2: Power fluctuation cascade
    {
        "name": "Power Fluctuation Cascade",
        "description": "Utility power fluctuation causes multiple equipment faults",
        "args": {
            "alarm_ids": [
                "ALM-POWER-FLUCT",
                "ALM-VFD-01-FAULT",
                "ALM-VFD-02-FAULT",
                "ALM-CH01-OVERCURRENT",
            ],
            "time_window_minutes": 15,
        },
        "expected": ["power", "cascade", "cause"],
    },
]

SKILL_MATCH_SCENARIOS = [
    {
        "name": "Summer Startup Issue",
        "description": "Find skills about chiller issues in hot weather",
        "args": {
            "query": "chiller won't start when outdoor temperature above 45°C",
            "building_id": "HQ-Tower",
            "top_k": 3,
        },
    },
    {
        "name": "Energy Spike Investigation",
        "description": "Find skills about unexpected energy increase",
        "args": {
            "query": "energy consumption suddenly increased by 20% over weekend",
            "building_id": "Office-A",
            "top_k": 3,
        },
    },
]

BENCHMARK_SCENARIOS = [
    {
        "name": "Office Tower Benchmark",
        "description": "Benchmark office tower against fleet",
        "args": {
            "building_id": "HQ-Tower",
            "include_recommendations": True,
        },
    },
]


# =============================================================================
# TEST RUNNER
# =============================================================================

async def run_fault_detection_tests(handler: BMSToolHandler) -> dict:
    """Run fault detection scenarios"""
    print("\n" + "=" * 70)
    print("TEST 1: FAULT DETECTION (FDDAutoencoder + ASHRAE RP-1312)")
    print("=" * 70)
    
    results = {"passed": 0, "failed": 0, "details": []}
    
    for scenario in FAULT_DETECTION_SCENARIOS:
        print(f"\n📋 Scenario: {scenario['name']}")
        print(f"   Description: {scenario['description']}")
        
        start = time.time()
        result = await handler.execute('detect_equipment_faults', scenario['args'])
        elapsed = time.time() - start
        
        # Check results
        success = True
        notes = []
        
        if 'error' in result:
            success = False
            notes.append(f"❌ Error: {result['error']}")
        else:
            # Check if faults detected when expected
            faults = result.get('faults', [])
            faults_detected = result.get('faults_detected', False)
            
            notes.append(f"   Faults detected: {faults_detected}")
            notes.append(f"   Equipment: {result.get('equipment_id')}")
            
            if faults:
                for f in faults[:2]:  # Show first 2 faults
                    notes.append(f"   ⚠️ {f.get('fault_type', 'Unknown')}: {f.get('description', 'No desc')}")
            
            # Check interpretation
            if 'interpretation' in result:
                interp = result['interpretation'][:150] + "..." if len(result.get('interpretation', '')) > 150 else result.get('interpretation', '')
                notes.append(f"   🤖 Interpretation: {interp}")
                notes.append(f"   ✓ Verified: {result.get('interpretation_verified', False)}")
        
        print("\n".join(notes))
        print(f"   ⏱️ Elapsed: {elapsed:.2f}s")
        
        if success:
            results["passed"] += 1
            print("   ✅ PASSED")
        else:
            results["failed"] += 1
            print("   ❌ FAILED")
        
        results["details"].append({
            "scenario": scenario['name'],
            "success": success,
            "elapsed": elapsed,
            "result": result,
        })
    
    return results


async def run_simulation_tests(handler: BMSToolHandler) -> dict:
    """Run what-if simulation scenarios"""
    print("\n" + "=" * 70)
    print("TEST 2: WHAT-IF SIMULATION (GP + Monte Carlo)")
    print("=" * 70)
    
    results = {"passed": 0, "failed": 0, "details": []}
    
    for scenario in SIMULATION_SCENARIOS:
        print(f"\n📋 Scenario: {scenario['name']}")
        print(f"   Description: {scenario['description']}")
        
        start = time.time()
        result = await handler.execute('simulate_with_uncertainty', scenario['args'])
        elapsed = time.time() - start
        
        success = True
        notes = []
        
        if 'error' in result:
            success = False
            notes.append(f"   ❌ Error: {result['error']}")
        else:
            sim = result.get('simulation', {})
            
            # Energy impact
            if 'energy_impact' in sim:
                ei = sim['energy_impact']
                notes.append(f"   ⚡ Energy Impact: {ei.get('mean', 0):.1f}% [{ei.get('lower_bound', 0):.1f}%, {ei.get('upper_bound', 0):.1f}%]")
            
            # Cost impact
            if 'cost_impact_qar' in sim:
                ci = sim['cost_impact_qar']
                notes.append(f"   💰 Cost Impact: {ci.get('mean', 0):.0f} QAR/month")
            
            # Risk
            notes.append(f"   ⚠️ Risk of Reversion: {sim.get('risk_of_reversion', 0)*100:.1f}%")
            
            # Interpretation
            if 'interpretation' in result:
                interp = result['interpretation'][:150] + "..." if len(result.get('interpretation', '')) > 150 else result.get('interpretation', '')
                notes.append(f"   🤖 Interpretation: {interp}")
                notes.append(f"   ✓ Verified: {result.get('interpretation_verified', False)}")
        
        print("\n".join(notes))
        print(f"   ⏱️ Elapsed: {elapsed:.2f}s")
        
        if success:
            results["passed"] += 1
            print("   ✅ PASSED")
        else:
            results["failed"] += 1
            print("   ❌ FAILED")
        
        results["details"].append({
            "scenario": scenario['name'],
            "success": success,
            "elapsed": elapsed,
        })
    
    return results


async def run_root_cause_tests(handler: BMSToolHandler) -> dict:
    """Run root cause analysis scenarios"""
    print("\n" + "=" * 70)
    print("TEST 3: ROOT CAUSE ANALYSIS (Bayesian Network)")
    print("=" * 70)
    
    results = {"passed": 0, "failed": 0, "details": []}
    
    for scenario in ROOT_CAUSE_SCENARIOS:
        print(f"\n📋 Scenario: {scenario['name']}")
        print(f"   Description: {scenario['description']}")
        
        start = time.time()
        result = await handler.execute('analyze_root_cause', scenario['args'])
        elapsed = time.time() - start
        
        success = True
        notes = []
        
        if 'error' in result:
            success = False
            notes.append(f"   ❌ Error: {result['error']}")
        else:
            notes.append(f"   Alarms analyzed: {result.get('alarm_count', 0)}")
            
            analysis = result.get('analysis', {})
            if 'root_causes' in analysis:
                for rc in analysis['root_causes'][:2]:
                    notes.append(f"   🎯 Root cause: {rc.get('equipment_id')} (prob: {rc.get('probability', 0):.0%})")
            
            if 'interpretation' in result:
                interp = result['interpretation'][:150] + "..."
                notes.append(f"   🤖 Interpretation: {interp}")
        
        print("\n".join(notes))
        print(f"   ⏱️ Elapsed: {elapsed:.2f}s")
        
        if success:
            results["passed"] += 1
            print("   ✅ PASSED")
        else:
            results["failed"] += 1
            print("   ❌ FAILED")
        
        results["details"].append({
            "scenario": scenario['name'],
            "success": success,
            "elapsed": elapsed,
        })
    
    return results


async def run_skill_matching_tests(handler: BMSToolHandler) -> dict:
    """Run semantic skill matching scenarios"""
    print("\n" + "=" * 70)
    print("TEST 4: SEMANTIC SKILL MATCHING (Sentence Transformers)")
    print("=" * 70)
    
    results = {"passed": 0, "failed": 0, "details": []}
    
    for scenario in SKILL_MATCH_SCENARIOS:
        print(f"\n📋 Scenario: {scenario['name']}")
        print(f"   Query: {scenario['args']['query']}")
        
        start = time.time()
        result = await handler.execute('find_similar_skills', scenario['args'])
        elapsed = time.time() - start
        
        success = True
        notes = []
        
        if 'error' in result:
            success = False
            notes.append(f"   ❌ Error: {result['error']}")
        else:
            matches = result.get('matches', [])
            notes.append(f"   Found {len(matches)} matching skills")
            
            for m in matches[:2]:
                notes.append(f"   📖 {m.get('title', 'Untitled')} (similarity: {m.get('similarity', 0):.0%})")
        
        print("\n".join(notes))
        print(f"   ⏱️ Elapsed: {elapsed:.2f}s")
        
        if success:
            results["passed"] += 1
            print("   ✅ PASSED")
        else:
            results["failed"] += 1
            print("   ❌ FAILED")
        
        results["details"].append({
            "scenario": scenario['name'],
            "success": success,
            "elapsed": elapsed,
        })
    
    return results


async def run_benchmark_tests(handler: BMSToolHandler) -> dict:
    """Run building benchmark scenarios"""
    print("\n" + "=" * 70)
    print("TEST 5: BUILDING BENCHMARKING (K-Means Clustering)")
    print("=" * 70)
    
    results = {"passed": 0, "failed": 0, "details": []}
    
    for scenario in BENCHMARK_SCENARIOS:
        print(f"\n📋 Scenario: {scenario['name']}")
        print(f"   Building: {scenario['args']['building_id']}")
        
        start = time.time()
        result = await handler.execute('benchmark_building_ml', scenario['args'])
        elapsed = time.time() - start
        
        success = True
        notes = []
        
        if 'error' in result:
            success = False
            notes.append(f"   ❌ Error: {result['error']}")
        else:
            classification = result.get('classification', {})
            notes.append(f"   🏢 Archetype: {classification.get('archetype', 'Unknown')}")
            notes.append(f"   📊 Cluster: {classification.get('cluster', 'N/A')}")
            
            if 'recommendations' in result:
                notes.append(f"   💡 Recommendations: {len(result.get('recommendations', []))} items")
            
            if 'interpretation' in result:
                interp = result['interpretation'][:150] + "..."
                notes.append(f"   🤖 Interpretation: {interp}")
        
        print("\n".join(notes))
        print(f"   ⏱️ Elapsed: {elapsed:.2f}s")
        
        if success:
            results["passed"] += 1
            print("   ✅ PASSED")
        else:
            results["failed"] += 1
            print("   ❌ FAILED")
        
        results["details"].append({
            "scenario": scenario['name'],
            "success": success,
            "elapsed": elapsed,
        })
    
    return results


async def run_llm_interpreter_battle_test() -> dict:
    """Battle test the LLM interpreter specifically"""
    print("\n" + "=" * 70)
    print("TEST 6: LLM INTERPRETER BATTLE TEST (K2 Think)")
    print("=" * 70)
    
    from agent_commercial.ml.llm_interpreter import create_k2_interpreter
    
    results = {"passed": 0, "failed": 0, "details": []}
    
    # Test cases with intentionally tricky data
    test_cases = [
        {
            "name": "Basic Fault Interpretation",
            "type": "fault",
            "data": {
                "equipment_id": "CH-01",
                "fault_type": "HIGH_COND_APPROACH",
                "severity": "medium",
                "description": "Condenser approach temperature above threshold",
                "detected_value": 9.2,
                "expected_range": [3, 6],
                "confidence": 0.88,
            },
        },
        {
            "name": "Low Confidence Fault",
            "type": "fault",
            "data": {
                "equipment_id": "AHU-05",
                "fault_type": "POSSIBLE_LEAK",
                "severity": "low",
                "description": "Possible refrigerant leak suspected",
                "detected_value": 2.1,
                "expected_range": [0, 1],
                "confidence": 0.45,  # Below threshold - should use template
            },
        },
        {
            "name": "Simulation with Extreme Values",
            "type": "simulation",
            "data": {
                "building_id": "Test-Building",
                "change_type": "setpoint",
                "current_value": 18,
                "proposed_value": 28,  # 10°C change - extreme!
                "simulation": {
                    "energy_impact": {"mean": -42.0, "lower_bound": -35.0, "upper_bound": -49.0},
                    "cost_impact_qar": {"mean": -15000, "lower_bound": -12000, "upper_bound": -18000},
                    "risk_of_reversion": 0.95,  # Very high risk
                },
            },
        },
    ]
    
    interpreter = create_k2_interpreter()
    
    for tc in test_cases:
        print(f"\n📋 Test: {tc['name']}")
        
        start = time.time()
        try:
            if tc['type'] == 'fault':
                result = await interpreter.interpret_fault(tc['data'])
            elif tc['type'] == 'simulation':
                result = await interpreter.interpret_simulation(tc['data'])
            else:
                result = await interpreter.interpret_fault(tc['data'])
            
            elapsed = time.time() - start
            
            print(f"   LLM Used: {result.llm_used}")
            print(f"   Verified: {result.verified}")
            print(f"   Confidence: {result.confidence:.0%}")
            print(f"   Explanation: {result.explanation[:120]}...")
            print(f"   ⏱️ Elapsed: {elapsed:.2f}s")
            
            if result.verified or not result.llm_used:
                results["passed"] += 1
                print("   ✅ PASSED")
            else:
                results["failed"] += 1
                print(f"   ❌ FAILED - Verification: {result.verification_notes}")
            
            results["details"].append({
                "test": tc['name'],
                "llm_used": result.llm_used,
                "verified": result.verified,
                "elapsed": elapsed,
            })
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"   ❌ ERROR: {e}")
            results["failed"] += 1
            results["details"].append({
                "test": tc['name'],
                "error": str(e),
                "elapsed": elapsed,
            })
    
    return results


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all battle tests"""
    handler = BMSToolHandler()
    
    all_results = {}
    total_passed = 0
    total_failed = 0
    
    # Run all test suites
    all_results["fault_detection"] = await run_fault_detection_tests(handler)
    all_results["simulation"] = await run_simulation_tests(handler)
    all_results["root_cause"] = await run_root_cause_tests(handler)
    all_results["skill_matching"] = await run_skill_matching_tests(handler)
    all_results["benchmark"] = await run_benchmark_tests(handler)
    all_results["llm_interpreter"] = await run_llm_interpreter_battle_test()
    
    # Summary
    print("\n" + "=" * 70)
    print("BATTLE TEST SUMMARY")
    print("=" * 70)
    
    for suite_name, results in all_results.items():
        passed = results["passed"]
        failed = results["failed"]
        total_passed += passed
        total_failed += failed
        status = "✅" if failed == 0 else "⚠️"
        print(f"{status} {suite_name.upper()}: {passed}/{passed+failed} passed")
    
    print("-" * 70)
    total = total_passed + total_failed
    success_rate = (total_passed / total * 100) if total > 0 else 0
    print(f"TOTAL: {total_passed}/{total} passed ({success_rate:.0f}%)")
    
    if total_failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print(f"\n⚠️ {total_failed} tests need attention")
    
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
