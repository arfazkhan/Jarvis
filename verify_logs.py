
import json
import os

log_file = "glass_box_audit.jsonl"
if not os.path.exists(log_file):
    print(f"Log file {log_file} not found.")
    exit(1)

with open(log_file, "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

lines = text.splitlines()
print(f"Total lines: {len(lines)}")

for i, line in enumerate(lines):
    if not line.strip(): continue
    try:
        evt = json.loads(line)
        event_name = evt.get("event")
        data_str = evt.get("data", "{}")
        try:
            inner_data = json.loads(data_str)
        except:
            inner_data = data_str
            
        print(f"Line {i+1}: [{event_name}]")
        if event_name == "think":
            print(f"  -> Thought Content: {inner_data.get('content') or inner_data.get('reasoning')}")
        elif event_name == "plan":
            print(f"  -> Planned Tools: {inner_data.get('planned_tools')}")
            print(f"  -> Plan Reasoning: {inner_data.get('reasoning')}")
        elif event_name == "tool_use":
            tool_name = inner_data.get('tool')
            print(f"  -> Tool: {tool_name}")
            if tool_name == "think":
                print(f"     Args: {inner_data.get('args')}")
        else:
            print(f"  -> Data: {inner_data}")
    except Exception as e:
        print(f"Line {i+1}: Error parsing JSON: {e}")
