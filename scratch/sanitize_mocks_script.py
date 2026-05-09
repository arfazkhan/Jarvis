import sys
from pathlib import Path

# Load original content
mocks_path = Path("e:/Automation/tests/mocks.py")
content = mocks_path.read_text(encoding="utf-8")
lines = content.splitlines()

# Extract segments
# Segment 1: Header and Primary Mocks (1-1314)
primary_mocks = lines[:1314]

# Segment 2: Alarm Engine (1319-1349)
alarm_engine = lines[1318:1349]

# Segment 3: Unique Mocks (OnlineLearner, PredictiveMaintenance, BMSStateEngineV2, etc.)
# I'll just find them by searching for the class definitions and grabbing their blocks.

unique_classes = [
    "class MockOnlineLearner:",
    "class MockPredictiveMaintenanceEngine:",
    "class MockBMSStateEngineV2:",
    "class MockEquipment:",
    "class MockDataPoint:",
    "class MockAlarm:",
    "class MockEnum:",
    "class MockGSASOptimizer:",
]

output_lines = primary_mocks + [""] + alarm_engine + [""]

added_classes = set()

current_class = None
class_lines = []

for line in lines[1349:]:
    if line.startswith("class "):
        if current_class:
            # Check if this class is in our unique list and NOT already added
            class_name = current_class.split("(")[0].split(":")[0].strip()
            if current_class in unique_classes and class_name not in added_classes:
                output_lines.extend(class_lines)
                output_lines.append("")
                added_classes.add(class_name)
        
        current_class = line
        class_lines = [line]
    elif current_class:
        class_lines.append(line)

# Add the last class if it qualifies
if current_class:
    class_name = current_class.split("(")[0].split(":")[0].strip()
    if current_class in unique_classes and class_name not in added_classes:
        output_lines.extend(class_lines)

# Write to a temporary file first
new_content = "\n".join(output_lines)
Path("e:/Automation/scratch/sanitized_mocks.py").write_text(new_content, encoding="utf-8")
print(f"Sanitized mocks written to scratch/sanitized_mocks.py. Total lines: {len(output_lines)}")
