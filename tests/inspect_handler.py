import asyncio
import inspect
import os
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_commercial.tools import BMSToolHandler
from agent_commercial.skillbook import BuildingSkillbook

async def inspect_handler():
    sb = BuildingSkillbook(building_id="test")
    handler = BMSToolHandler(knowledge_base=sb)
    
    print(f"Handler Class: {type(handler)}")
    print(f"Bases: {type(handler).__bases__}")
    
    methods = ["_handle_get_equipment_status", "_handle_query_skillbook", "_handle_simulate_change"]
    for m in methods:
        attr = getattr(handler, m, None)
        if attr:
            sig = inspect.signature(attr)
            print(f"Method {m}: {sig}")
            # Check if it's bound
            print(f"  Is Bound: {inspect.ismethod(attr)}")
        else:
            print(f"Method {m} NOT FOUND")
            
    # Inspect add_skill
    add_skill_fn = sb.add_skill
    print(f"Skillbook.add_skill: {inspect.signature(add_skill_fn)}")
    print(f"  Is Bound: {inspect.ismethod(add_skill_fn)}")

if __name__ == "__main__":
    asyncio.run(inspect_handler())
