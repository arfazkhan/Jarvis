import re

def test_regex():
    answer = "The 30XW models have cooling capacities ranging from 300 to 1500 kW."
    # Standard word-boundary number search
    candidates = re.findall(r'\b\d+(?:\.\d+)?\b', answer)
    print(f"Candidates with \\b: {candidates}")

    # 30XW check
    s = "30XW"
    print(f"Match '30' in '30XW' with \\b: {re.findall(r'\\b\\d+\\b', s)}")

test_regex()
