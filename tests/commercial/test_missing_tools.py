
import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_commercial.tools_schema import get_bms_tools

def test():
    print("Fetching BMS Tools directly from schema...")
    raw_tools = get_bms_tools()
    
    print(f"Total Raw Tools: {len(raw_tools)}")
    
    # Simulate the logic in _generate_tool_calls
    tools_def = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"]
            }
        } 
        for tool in raw_tools
    ]
    
    print(f"Total Tools Def: {len(tools_def)}")
    
    names = [t["function"]["name"] for t in tools_def]
    
    if "list_equipment" in names:
        print("✅ list_equipment PRESENT in tools_def")
    else:
        print("❌ list_equipment MISSING from tools_def")

    if "get_point_history" in names:
        print("✅ get_point_history PRESENT in tools_def")
    else:
        print("❌ get_point_history MISSING from tools_def")
        
    # Check for empty parameters issue
    le = next((t for t in tools_def if t["function"]["name"] == "list_equipment"), None)
    if le:
        print("\nlist_equipment def:")
        print(json.dumps(le, indent=2))

if __name__ == "__main__":
    test()
