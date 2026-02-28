
import sys
import os
import traceback

print("--- DIAGNOSING IMPORTS ---")
sys.path.append(os.getcwd())
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
print(f"CWD: {os.getcwd()}")
print(f"Sys Path: {sys.path[:3]}")

try:
    print("1. Importing agent_advisory...")
    import agent_advisory
    print("   SUCCESS")
except:
    traceback.print_exc()

try:
    print("2. Importing agent_advisory.explainer...")
    from agent_advisory import explainer
    print("   SUCCESS")
except:
    traceback.print_exc()

try:
    print("3. Importing agent_commercial.tools_schema...")
    from agent_commercial import tools_schema
    print("   SUCCESS")
except:
    traceback.print_exc()

try:
    print("4. Importing agent_commercial.bms_llm_agent...")
    from agent_commercial import bms_llm_agent
    print("   SUCCESS")
except:
    traceback.print_exc()
