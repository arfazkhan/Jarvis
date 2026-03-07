"""
Formatters for converting raw backend system names to user-friendly UI strings.
"""

FRIENDLY_AGENTS = {
    "Energy_Agent": "Energy Optimizer",
    "Comfort_Agent": "Thermal Comfort Specialist",
    "Strategic_Agent": "Strategic AI",
    "Alarm_Agent": "Anomaly Detector",
    "Maintenance_Agent": "Predictive Maintenance Advisor",
    "Memory_Agent": "Knowledge Graph",
    "Sovereign_Agent": "Chief Building AI",
    "Fast_Router": "Quick Inquiry Router"
}

FRIENDLY_TOOLS = {
    # System / ML / Simulation
    "query_skillbook": "Consulting historical building skillbook...",
    "add_to_skillbook": "Recording new knowledge to skillbook...",
    "compare_to_fleet": "Comparing baseline with equivalent buildings...",
    "simulate_change": "Simulating environmental impact of proposed changes...",
    "correlate_events": "Correlating system events and logs...",
    "forecast_energy": "Running AI energy forecast...",
    "detect_equipment_faults": "Scanning equipment for hidden faults...",
    "analyze_root_cause": "Performing ML root cause analysis...",
    "simulate_with_uncertainty": "Running Monte Carlo impact simulations...",
    "find_similar_skills": "Cross-referencing historical problem solutions...",
    "benchmark_building_ml": "Benchmarking ML efficiency models...",
    
    # Maintenance
    "predict_maintenance": "Running predictive maintenance algorithms...",
    "predict_remaining_life": "Estimating remaining useful life for equipment...",
    "verify_maintenance_work": "Cross-checking recent maintenance logs...",
    
    # GSAS / Sustainability
    "get_gsas_status": "Checking GSAS sustainability compliance...",
    "get_gsas_improvement_priorities": "Calculating GSAS score improvement priorities...",
    "generate_gord_report": "Formatting data for GORD reporting...",
    
    # Equipment
    "get_equipment_status": "Checking live equipment telemetry...",
    "list_equipment": "Syncing equipment inventory...",
    "get_equipment_health": "Evaluating equipment health metrics...",
    "get_point_history": "Retrieving historical sensor telemetry...",
    "get_equipment_specs": "Looking up engineering specifications...",
    "get_dashboard_overview": "Refreshing dashboard overview metrics...",
    
    # Energy
    "analyze_energy": "Analyzing real-time energy consumption patterns...",
    "get_energy_anomalies": "Searching for localized energy anomalies...",
    "check_cost_impact": "Calculating financial cost impact of operations...",
    "get_burn_rate": "Calculating current utility burn rates...",
    "find_ghost_spaces": "Scanning for empty spaces consuming power...",
    "estimate_zone_occupancy": "Estimating human occupancy density by zone...",
    
    # Alarms
    "get_active_alarms": "Scanning active alarm registers...",
    "explain_alarm": "Analyzing alarm diagnostic context...",
    "acknowledge_alarm": "Attempting to acknowledge system alarm...",
    "analyze_cascade": "Tracing alarm cascade root-cause...",
    
    # Advisory / Strategy
    "get_advisory_recommendations": "Fetching highest confidence strategic recommendations...",
    "check_goals": "Evaluating alignment with building KPI goals...",
    "generate_briefing": "Compiling executive operations briefing...",
    "run_briefing": "Executing interactive briefing session...",
    "submit_feedback": "Logging operator feedback to neural core...",
    "get_trust_metrics": "Retrieving Swarm truth and confidence metrics..."
}

def format_agent_name(raw_name: str) -> str:
    return FRIENDLY_AGENTS.get(raw_name, raw_name.replace("_", " "))

def format_tool_name(raw_name: str) -> str:
    return FRIENDLY_TOOLS.get(raw_name, f"Executing tool: {raw_name.replace('_', ' ')}...")
