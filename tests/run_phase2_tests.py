#!/usr/bin/env python3
"""
Quick Test Runner
=================

Run a subset of tests to verify infrastructure works.
"""

import sys
import subprocess
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

def run_tests(test_paths, description):
    """Run pytest on given paths."""
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print('=' * 60)
    
    cmd = ["python3", "-m", "pytest"] + test_paths + ["-v", "--tb=short", "-x"]
    
    result = subprocess.run(cmd, cwd="/home/workspace/Jarvis", capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    return result.returncode

def main():
    print("\n" + "=" * 60)
    print("  ARVIS PHASE 2 TEST VERIFICATION")
    print("=" * 60)
    
    exit_code = 0
    
    # Test 1: Infrastructure sanity
    rc = run_tests(
        ["tests/test_infrastructure_sanity.py"],
        "Phase 1 Infrastructure Tests"
    )
    exit_code = exit_code or rc
    
    # Test 2: Equipment tools
    rc = run_tests(
        ["tests/unit/test_tools/test_equipment_tools.py"],
        "Equipment Tool Tests"
    )
    exit_code = exit_code or rc
    
    # Test 3: Alarm tools
    rc = run_tests(
        ["tests/unit/test_tools/test_alarm_tools.py"],
        "Alarm Tool Tests"
    )
    exit_code = exit_code or rc
    
    print("\n" + "=" * 60)
    if exit_code == 0:
        print("  ✅ ALL TESTS PASSED")
    else:
        print("  ❌ SOME TESTS FAILED")
    print("=" * 60 + "\n")
    
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
