
import subprocess
import os
import sys

def run_test():
    result = subprocess.run([sys.executable, "tests/gauntlet_omega.py"], capture_output=True, text=True, encoding='utf-8')
    if "FAILURE" in result.stdout:
        return False, result.stdout
    return True, result.stdout

successes = 0
total = 5

print(f"Starting {total}-run reliability check...")

for i in range(total):
    print(f"Run {i+1}/{total}...", end="", flush=True)
    pass_test, output = run_test()
    if pass_test:
        successes += 1
        print(" PASS")
    else:
        print(" FAIL")
        # Save failure log
        with open(f"tests_data/reliability_fail_{i+1}.txt", "w", encoding='utf-8') as f:
            f.write(output)

print(f"\nReliability Score: {successes}/{total}")
if successes == total:
    print("STOCHASTIC FAILURE ELIMINATED.")
    exit(0)
else:
    print("STOCHASTIC FAILURE STILL PRESENT.")
    exit(1)
