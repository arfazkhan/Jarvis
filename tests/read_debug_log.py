import re

log_path = 'tests_data/gauntlet_omega_cubed_results.txt'

try:
    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()
except UnicodeDecodeError:
    with open(log_path, 'r', encoding='utf-16') as f:
        content = f.read()

# Extract Debug Section
debug_match = re.search(r'(--- DEBUG: SYSTEM PROMPT \(Day 7\) ---.*?)--- END DEBUG ---', content, re.DOTALL)
if debug_match:
    print("FOUND DEBUG PROMPT:")
    prompt_text = debug_match.group(1)
    # Print first 2000 chars of prompt to check for Legitimacy Anchor
    print(prompt_text[:2000]) 
    if "LEGITIMACY ANCHOR" in prompt_text:
        print("\n✅ LEGITIMACY ANCHOR FOUND IN PROMPT")
    else:
        print("\n❌ LEGITIMACY ANCHOR NOT FOUND IN PROMPT")
else:
    print("DEBUG SECTION NOT FOUND")

# Extract Results
results_match = re.search(r'(=== Ω³ RESULTS ===.*)', content, re.DOTALL)
if results_match:
    print("\n" + results_match.group(1))
else:
    print("RESULTS NOT FOUND")
