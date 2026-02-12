import re

log_path = 'tests_data/gauntlet_omega_cubed_results.txt'

try:
    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()
except UnicodeDecodeError:
    with open(log_path, 'r', encoding='utf-16') as f:
        content = f.read()

# Extract Day 1 Section
day1_match = re.search(r'Day 1.*?Analysis: (.*?)\n', content, re.DOTALL)
if day1_match:
    print("DAY 1 ANALYSIS:")
    print(day1_match.group(1))
else:
    print("DAY 1 NOT FOUND")
