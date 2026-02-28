import re

def extract_critical_logs(log_path, output_path):
    critical_days = [
        "Day 1", "Day 3", "Day 5", "Day 6", "Day 8", "Day 9", 
        "Day 10", "Day 13", "Day 14"
    ]
    
    # Try opening with utf-16 first, as identified by BOM
    try:
        with open(log_path, 'r', encoding='utf-16', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"UTF-16 read failed: {e}. Trying utf-8.")
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
    extracted_logs = []
    capture = False
    buffer = []
    
    extracted_logs.append("============================================================")
    extracted_logs.append("CRITICAL RAW LOGS: ΩΔ IDENTITY FRACTURE")
    extracted_logs.append("============================================================\n")

    for line in lines:
        # Start capturing on a new Day Query
        if "[AGENT] Day" in line:
            # Check if this day is in our critical list
            is_critical = any(day in line for day in critical_days)
            
            if is_critical:
                capture = True
                if buffer:
                    extracted_logs.extend(buffer)
                    buffer = []
                extracted_logs.append("\n" + "-"*60)
                extracted_logs.append(line.strip())
            else:
                capture = False
                
        elif capture:
            # Keep capturing relevant lines until the next [PHYSICS] or [AGENT] block
            if "[PHYSICS] Advancing" in line:
                capture = False
                continue
                
            # Filter for high-signal lines
            if any(k in line for k in [
                "[EconomyPolicy]", 
                "[VerificationLayer]", 
                "HTTP Request", 
                "[LLM]", 
                "[AUDIT]", 
                "[RESPONSE]",
                "Logged recommendation",
                "[SmartEconomy]",
                "[AntiLoop]"
            ]):
                extracted_logs.append(line.strip())

    if not extracted_logs:
        extracted_logs.append("ERROR: No logs extracted. Check encoding or patterns.")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(extracted_logs))

if __name__ == "__main__":
    extract_critical_logs("e:\\Automation\\pilot_identity_fracture.log", "e:\\Automation\\identity_fracture_critical_logs.txt")
