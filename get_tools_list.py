import json
from agent_commercial.tools import get_bms_tools

tools = get_bms_tools()
with open('e:/Automation/tools_list.md', 'w', encoding='utf-8') as f:
    for t in tools:
        name = t.get('name') or t.get('function', {}).get('name', 'Unknown')
        desc = t.get('description') or t.get('function', {}).get('description', 'No description')
        desc = desc.replace('\n', ' ').strip()
        f.write(f"- **`{name}`**: {desc}\n")
