
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_commercial.tools_schema import get_bms_tools

try:
    tools = get_bms_tools()
    print(f"Found {len(tools)} tools.")
    names = [t['name'] for t in tools]
    print(f"Tools: {names}")
    
    if "list_equipment" in names:
        print("✅ list_equipment found")
        import json
        le_tool = next(t for t in tools if t['name'] == 'list_equipment')
        print(json.dumps(le_tool, indent=2))
    else:
        print("❌ list_equipment NOT found")
        
    if "get_point_history" in names:
        print("✅ get_point_history found")
    else:
        print("❌ get_point_history NOT found")
        
except Exception as e:
    print(f"Error loading tools: {e}")
