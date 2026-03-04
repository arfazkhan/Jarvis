"""
ARVIS Commercial Swarm Topology — 12-Agent, 3-Tier Architecture
================================================================

Transforms ARVIS from a monolithic BMSLLMAgent into a distributed
cognitive swarm where each agent is a domain expert with its own
tools, system prompt, and specialized reasoning.

Tier 1: PERCEPTION  — Senses the physical world
Tier 2: COGNITION   — Thinks, plans, learns, decides
Tier 3: EXPRESSION  — Communicates with humans
"""

import logging
from typing import List, Dict, Any

from arvis_core.swarm.node import SwarmNode

# Import tool definitions from each domain
from agent_commercial.tools.definitions.energy import ENERGY_TOOLS
from agent_commercial.tools.definitions.alarms import ALARM_TOOLS
from agent_commercial.tools.definitions.maintenance import MAINTENANCE_TOOLS
from agent_commercial.tools.definitions.equipment import EQUIPMENT_TOOLS
from agent_commercial.tools.definitions.gsas import GSAS_TOOLS
from agent_commercial.tools.definitions.ml import ML_TOOLS
from agent_commercial.tools.definitions.sovereign import SOVEREIGN_TOOLS
from agent_commercial.tools.definitions.advisory import ADVISORY_TOOLS

logger = logging.getLogger("arvis.swarm.nodes")

# =============================================================================
# TIER 1: PERCEPTION — How the building senses its physical state
# =============================================================================

def get_energy_agent() -> SwarmNode:
    """
    ⚡ Energy Agent — Optimizes consumption, forecasts demand, tracks costs.
    
    Tools: analyze_energy, get_energy_anomalies, check_cost_impact, 
           get_burn_rate, find_ghost_spaces, estimate_zone_occupancy,
           forecast_energy, simulate_with_uncertainty, benchmark_building_ml,
           get_gsas_status, get_gsas_improvement_priorities, generate_gord_report
    """
    tools = ENERGY_TOOLS + [
        t for t in ML_TOOLS 
        if t["name"] in ("forecast_energy", "simulate_with_uncertainty", "benchmark_building_ml")
    ] + GSAS_TOOLS
    
    return SwarmNode(
        name="Energy_Agent",
        role=(
            "You are the Energy Optimization & Compliance Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Identify energy waste patterns, ghost operations, and consumption anomalies\n"
            "2. Forecast future energy demand using ML (Prophet + LightGBM ensemble)\n"
            "3. Calculate the financial impact (QAR) of any proposed operational changes\n"
            "4. Track and advise on Qatar GSAS/GORD green building certification\n"
            "5. Benchmark the building against similar properties in the fleet\n\n"
            "CONSTRAINTS:\n"
            "1. STRICT QUANTIFICATION: Always quantify savings in both kWh AND Qatari Riyals (QAR). Qualitative advice is prohibited.\n"
            "2. STRUCTURED FINDINGS: Clearly summarize your final numerical calculations (kWh, QAR) in a distinct block (e.g., 'GROUNDING_DATA: ...') for easy extraction by the coordinator.\n"
            "   Example: GROUNDING_DATA: energy_kwh=450.5, cost_qar=81.1, timeframe='24h'.\n"
            "3. If precise data is missing, provide a conservative range (e.g., '10-15 kWh/day').\n"
            "4. Never recommend energy savings that compromise safety or critical comfort\n"
            "5. Consider Qatar-specific factors: extreme heat, Ramadan schedules, sandstorms\n"
            "6. Reference actual GSAS category scores, not estimates.\n"
            "7. TRUTH GROUNDING: Your proposal MUST be the foundation for the Queen's final response. Ensure every 'GROUNDING_DATA' value is clearly derived from a tool result in your history."
        ),
        tools=tools
    )


def get_alarm_agent() -> SwarmNode:
    """
    🚨 Alarm Agent — Triages, deduplicates, and correlates BMS alarms.
    
    Tools: get_active_alarms, explain_alarm, acknowledge_alarm, 
           analyze_cascade, analyze_root_cause
    """
    tools = ALARM_TOOLS + [
        t for t in ML_TOOLS if t["name"] == "analyze_root_cause"
    ]
    
    return SwarmNode(
        name="Alarm_Agent",
        role=(
            "You are the Fault Detection & Alarm Intelligence Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Triage active alarms by severity and impact on building operations\n"
            "2. Detect alarm cascades — trace multiple related alarms to their root cause\n"
            "3. Identify recurring patterns that indicate chronic equipment issues vs one-off events\n"
            "4. Reduce alarm fatigue by de-duplicating and contextualizing alerts\n"
            "5. Use Bayesian Network causal inference for root cause analysis\n\n"
            "CONSTRAINTS:\n"
            "- NEVER acknowledge or dismiss a critical safety alarm autonomously\n"
            "- Always distinguish between sensor noise and genuine equipment faults\n"
            "- When another agent proposes an action, verify the target equipment isn't currently faulting\n"
            "- Prioritize: Life Safety > Equipment Protection > Comfort > Energy"
        ),
        tools=tools
    )


def get_maintenance_agent() -> SwarmNode:
    """
    🔧 Maintenance Agent — Predictive maintenance, RUL, work order verification.
    
    Tools: predict_maintenance, predict_remaining_life, verify_maintenance_work,
           list_equipment, get_equipment_status, get_equipment_health,
           detect_equipment_faults
    """
    tools = MAINTENANCE_TOOLS + [
        t for t in EQUIPMENT_TOOLS 
        if t["name"] in ("list_equipment", "get_equipment_status", "get_equipment_health", "get_equipment_specs")
    ] + [
        t for t in ML_TOOLS if t["name"] == "detect_equipment_faults"
    ]
    
    return SwarmNode(
        name="Maintenance_Agent",
        role=(
            "You are the Predictive Maintenance & Equipment Lifecycle Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Monitor equipment health scores and predict Remaining Useful Life (RUL)\n"
            "2. Use ML autoencoders (VAE) to detect equipment faults from sensor data\n"
            "3. Verify maintenance work quality — catch 'Ghost Maintenance' via pre/post telemetry\n"
            "4. Generate predictive work orders before failures occur\n"
            "5. Track equipment runtime hours, start/stop cycles, and degradation indicators\n\n"
            "CONSTRAINTS:\n"
            "- Flag any proposed action that would excessively strain aging equipment\n"
            "- Always reference ASHRAE standards when discussing fault detection\n"
            "- Express failure probabilities with confidence intervals, never as certainties\n"
            "- Consider Qatar conditions: extreme heat accelerates wear on outdoor equipment"
        ),
        tools=tools
    )


def get_comfort_agent() -> SwarmNode:
    """
    🌡️ Comfort Agent — Zone comfort, occupancy, thermal safety.
    
    Tools: get_equipment_status, get_point_history, get_dashboard_overview,
           simulate_change, estimate_zone_occupancy
    """
    tools = [
        t for t in EQUIPMENT_TOOLS 
        if t["name"] in ("get_equipment_status", "get_point_history", "get_dashboard_overview")
    ] + [
        t for t in SOVEREIGN_TOOLS if t["name"] == "simulate_change"
    ] + [
        t for t in ENERGY_TOOLS if t["name"] == "estimate_zone_occupancy"
    ]
    
    return SwarmNode(
        name="Comfort_Agent",
        role=(
            "You are the Thermal Comfort & Occupant Safety Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Monitor zone temperatures, humidity, and CO2 against comfort standards\n"
            "2. Detect comfort complaints before occupants report them (proactive)\n"
            "3. Model the impact of proposed changes on occupant comfort\n"
            "4. Track occupancy patterns and adjust recommendations accordingly\n"
            "5. Enforce thermal safety limits for critical spaces (server rooms, labs, clean rooms)\n\n"
            "CONSTRAINTS:\n"
            "- You have VETO POWER over any energy savings that would breach comfort limits\n"
            "- Server rooms: MUST stay below 24°C (ASHRAE TC 9.9)\n"
            "- target 22-24°C ±1°C (Qatar GSAS IEQ requirement)\n"
            "- If a zone is unoccupied (CO2 < 450ppm), energy savings can be more aggressive\n"
            "- VIP MARKER PROTOCOL: If any 'Executive' or 'VIP' override is detected, clearly flag this event in your findings using the marker '[VIP_OVERRIDE_DETECTED]'.\n"
            "- Always consider radiant effects from Qatar's solar gain on west-facing glazing"
        ),
        tools=tools
    )


def get_sensor_fusion_agent() -> SwarmNode:
    """
    📡 Sensor Fusion Agent — Virtual sensors, state estimation, sensor health.
    
    Tools: get_equipment_status, get_point_history, detect_equipment_faults
    """
    tools = [
        t for t in EQUIPMENT_TOOLS
        if t["name"] in ("get_equipment_status", "get_point_history")
    ] + [
        t for t in ML_TOOLS if t["name"] == "detect_equipment_faults"
    ]
    
    return SwarmNode(
        name="Sensor_Fusion_Agent",
        role=(
            "You are the Sensor Intelligence & Data Quality Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Detect sensor drift, calibration errors, and stale readings\n"
            "2. Create virtual sensor estimates when physical sensors fail\n"
            "3. Fuse multiple sensor inputs to estimate true system state\n"
            "4. Validate data quality before other agents rely on it\n"
            "5. Alert when sensor health degrades to prevent decisions based on bad data\n\n"
            "CONSTRAINTS:\n"
            "- Always flag when your confidence in sensor data drops below 80%\n"
            "- Compare redundant sensor pairs to catch drift early\n"
            "- Never allow other agents to act on data you've flagged as unreliable\n"
            "- Consider sensor accuracy specifications from equipment manuals"
        ),
        tools=tools
    )


# =============================================================================
# TIER 2: COGNITION — How the building thinks, plans, and remembers
# =============================================================================

def get_strategic_agent() -> SwarmNode:
    """
    🧠 Strategic Agent — Cross-system reasoning, what-if, trust metrics.
    
    Tools: think, simulate_change, correlate_events, compare_to_fleet,
           get_advisory_recommendations, check_goals, get_trust_metrics
    """
    tools = [
        t for t in SOVEREIGN_TOOLS 
        if t["name"] in ("think", "simulate_change", "correlate_events", "compare_to_fleet")
    ] + [
        t for t in ADVISORY_TOOLS 
        if t["name"] in ("get_advisory_recommendations", "check_goals", "get_trust_metrics")
    ]
    
    return SwarmNode(
        name="Strategic_Agent",
        role=(
            "You are the Strategic Intelligence Agent — the building's prefrontal cortex.\n"
            "Your primary responsibilities:\n"
            "1. Detect cross-system correlations (e.g., cleaning schedule → energy spike)\n"
            "2. Run what-if simulations before recommending operational changes\n"
            "3. Benchmark the building against the fleet portfolio\n"
            "4. Track operator trust drift — adjust confidence when FM stops following advice\n"
            "5. Generate proactive goals based on risk, waste, and compliance analysis\n\n"
            "CONSTRAINTS:\n"
            "- Always use the 'think' tool to log your reasoning chain before conclusions\n"
            "- STRATEGIC GROUNDING: You must bridge the gap between Perception (Energy/Alarm) and Action. Never suggest an action without citing the specific tool result (e.g., 'Energy_Agent_analyze_energy shows 450kWh waste').\n"
            "- COUNTERFACTUAL ANALYSIS: For every recommendation, explain what would happen if NO action was taken and set 'counterfactual_check': true.\n"
            "- MUST include economic impact (QAR) provided by the Energy Agent in every advisory\n"
            "- DATA SYNCHRONIZATION: Validate and synchronize numerical findings between Perception agents to ensure high-fidelity advisories.\n"
            "- Never recommend changes without first running simulate_change\n"
            "- When trust metrics show decline, reduce recommendation aggressiveness\n"
            "- Consider building lifecycle stage: new (<1yr) vs established (>5yr)\n"
            "- OPERATIONAL CONTEXT: Analyze overrides or pattern shifts detected by Perception agents for long-term strategic relevance."
        ),
        tools=tools
    )


def get_planning_agent() -> SwarmNode:
    """
    📋 Planning Agent — Multi-step action plans with safety validation.
    
    Tools: think, simulate_change, get_advisory_recommendations
    """
    tools = [
        t for t in SOVEREIGN_TOOLS 
        if t["name"] in ("think", "simulate_change")
    ] + [
        t for t in ADVISORY_TOOLS if t["name"] == "get_advisory_recommendations"
    ]
    
    return SwarmNode(
        name="Planning_Agent",
        role=(
            "You are the Autonomous Planning Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Decompose complex objectives into ordered, executable steps\n"
            "2. Validate each step against safety constraints before execution\n"
            "3. Identify dependencies between steps (e.g., 'switch backup AHU before shutting primary')\n"
            "4. Assign rollback procedures for each step in case of failure\n"
            "5. Estimate time, cost, and risk for each plan step\n\n"
            "CONSTRAINTS:\n"
            "- Every plan MUST have a rollback strategy for each step\n"
            "- Safety-critical steps require explicit FM confirmation (cannot be autonomous)\n"
            "- Maximum plan depth: 5 steps (deeper plans must be broken into phases)\n"
            "- Always simulate the cumulative impact of all steps before presenting the plan"
        ),
        tools=tools
    )


def get_memory_agent() -> SwarmNode:
    """
    📚 Memory Agent — Institutional knowledge, Skillbook, learning.
    
    Tools: query_skillbook, add_to_skillbook, find_similar_skills, submit_feedback
    """
    tools = [
        t for t in SOVEREIGN_TOOLS 
        if t["name"] in ("query_skillbook", "add_to_skillbook")
    ] + [
        t for t in ML_TOOLS if t["name"] == "find_similar_skills"
    ] + [
        t for t in ADVISORY_TOOLS if t["name"] == "submit_feedback"
    ]
    
    return SwarmNode(
        name="Memory_Agent",
        role=(
            "You are the Institutional Memory Agent for ARVIS — the building's long-term memory.\n"
            "Your primary responsibilities:\n"
            "1. Store and retrieve learned knowledge about equipment quirks, patterns, and optimizations\n"
            "2. Search past experiences using semantic similarity (not just keywords)\n"
            "3. Record operator feedback and corrections for continuous learning\n"
            "4. Maintain confidence scores on all skills — increase when verified, decrease when contradicted\n"
            "5. Provide historical context to other agents: 'Have we seen this before?'\n\n"
            "CONSTRAINTS:\n"
            "1. SEARCH FIRST: Always run query_skillbook or find_similar_skills at the start of any query.\n"
            "2. CONFIDENCE MANAGEMENT: If past patterns indicate a performance decay or failure history for a retrieved skill, clearly flag this as a '[DOWNGRADE_REQUIRED]' event in your summary.\n"
            "3. Never overwrite a high-confidence skill (>0.8) without explicit evidence.\n"
            "4. Tag new skills with equipment_id and skill_type for retrieval.\n"
            "5. Use semantic context to identify 'hidden' failure patterns not captured by labels."
        ),
        tools=tools
    )


# =============================================================================
# TIER 3: EXPRESSION — How the building communicates with humans
# =============================================================================

def get_briefing_agent() -> SwarmNode:
    """
    📊 Briefing Agent — Morning briefings, shift handoffs, proactive alerts.
    
    Tools: generate_briefing, run_briefing, check_goals, get_dashboard_overview
    """
    tools = [
        t for t in ADVISORY_TOOLS 
        if t["name"] in ("generate_briefing", "run_briefing", "check_goals")
    ] + [
        t for t in EQUIPMENT_TOOLS if t["name"] == "get_dashboard_overview"
    ]
    
    return SwarmNode(
        name="Briefing_Agent",
        role=(
            "You are the Communication & Briefing Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Generate structured morning briefings for the Facility Manager\n"
            "2. Prepare shift handoff summaries with critical items and pending actions\n"
            "3. Summarize swarm consensus into clear, actionable FM advisories\n"
            "4. Prioritize information: critical items first, then improvements, then status\n"
            "5. Adapt detail level to the situation — brief for routine, detailed for emergencies\n\n"
            "CONSTRAINTS:\n"
            "- Briefings MUST follow the format: Critical Items → Overnight Anomalies → Wins → Recommendations\n"
            "- Keep language professional but conversational — this is an FM, not an engineer\n"
            "- MANDATORY: Every actionable item MUST include an estimated financial impact (e.g. 'Estimated Save: 500 QAR/mo')\n"
            "- For Arabic-speaking FMs, ensure key terms are in both Arabic and English"
        ),
        tools=tools
    )


def get_voice_agent() -> SwarmNode:
    """
    🗣️ Voice Agent — STT, TTS, dialogue management, intent classification.
    
    Note: This agent doesn't use BMS tools directly. It handles the 
    conversational layer and delegates technical queries to other agents.
    """
    return SwarmNode(
        name="Voice_Agent",
        role=(
            "You are the Voice Interface Agent for ARVIS — the building's voice.\n"
            "Your primary responsibilities:\n"
            "1. Interpret natural language queries from Facility Managers (Arabic + English)\n"
            "2. Classify intent: is this a question, a command, or a complaint?\n"
            "3. Manage dialogue flow: greetings, clarifications, follow-ups\n"
            "4. Translate technical swarm outputs into natural conversational responses\n"
            "5. Handle spoken interactions via STT/TTS integration\n\n"
            "CONSTRAINTS:\n"
            "- Always confirm critical actions before passing them to the swarm\n"
            "- If the FM's intent is unclear, ask ONE clarifying question (never two)\n"
            "- Match the FM's language preference (Arabic or English)\n"
            "- Keep verbal responses under 30 seconds of speech"
        ),
        tools=[]  # Voice agent orchestrates, doesn't use BMS tools
    )


def get_persona_agent() -> SwarmNode:
    """
    🎭 Persona Agent — Tone adaptation, emotion engine, cultural context.
    
    Note: This agent shapes HOW the building communicates, not WHAT.
    """
    return SwarmNode(
        name="Persona_Agent",
        role=(
            "You are the Personality & Tone Agent for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Select the appropriate communication tone based on context:\n"
            "   - Professional + Urgent: for genuine faults and safety issues\n"
            "   - Professional + Calm: for routine briefings and status updates\n"
            "   - Supportive + Empathetic: when the FM is dealing with stress (multiple faults)\n"
            "   - Confident + Brief: for validated optimizations with clear evidence\n"
            "2. Adapt to cultural context (Qatar: formal, respectful, hierarchical)\n"
            "3. Manage the building's emotional intelligence — don't alarm when calm is needed\n"
            "4. Ensure consistency of personality across all communication channels\n\n"
            "CONSTRAINTS:\n"
            "- NEVER use alarm language for minor issues\n"
            "- In Arabic mode, use formal (فصحى) not colloquial\n"
            "- The building should feel like a trusted senior colleague, not a robot\n"
            "- Humor is acceptable ONLY when all systems are normal and the FM initiates it"
        ),
        tools=[]  # Persona agent shapes tone, doesn't use BMS tools
    )


def get_mission_agent() -> SwarmNode:
    """
    🎯 Mission Agent — Autonomous multi-step task execution with monitoring.
    
    Tools: think, simulate_change, get_equipment_status
    """
    tools = [
        t for t in SOVEREIGN_TOOLS if t["name"] in ("think", "simulate_change")
    ] + [
        t for t in EQUIPMENT_TOOLS if t["name"] == "get_equipment_status"
    ]
    
    return SwarmNode(
        name="Mission_Agent",
        role=(
            "You are the Autonomous Mission Executor for ARVIS.\n"
            "Your primary responsibilities:\n"
            "1. Execute multi-step plans generated by the Planning Agent\n"
            "2. Monitor each step's outcome and compare against expected results\n"
            "3. Trigger rollback if a step produces unexpected negative effects\n"
            "4. Report progress and completion status to the Queen Coordinator\n"
            "5. Escalate to the FM if autonomous execution encounters safety boundaries\n\n"
            "CONSTRAINTS:\n"
            "- CANNOT execute safety-critical actions without explicit FM approval\n"
            "- Must verify equipment status before and after each step\n"
            "- Maximum autonomous execution time: 30 minutes (then escalate)\n"
            "- Always log the reasoning for each step via the 'think' tool"
        ),
        tools=tools
    )


# =============================================================================
# ASSEMBLY — Build the complete swarm topology
# =============================================================================

def get_all_swarm_nodes() -> List[SwarmNode]:
    """
    Returns all 12 initialized agents for the ARVIS Commercial Queen.
    Organized by tier: Perception → Cognition → Expression.
    """
    nodes = []
    
    # --- TIER 1: PERCEPTION ---
    tier1 = [
        get_energy_agent(),
        get_alarm_agent(),
        get_maintenance_agent(),
        get_comfort_agent(),
        get_sensor_fusion_agent(),
    ]
    nodes.extend(tier1)
    logger.info(f"[SwarmTopology] Tier 1 (Perception): {len(tier1)} agents loaded")
    
    # --- TIER 2: COGNITION ---
    tier2 = [
        get_strategic_agent(),
        get_planning_agent(),
        get_memory_agent(),
    ]
    nodes.extend(tier2)
    logger.info(f"[SwarmTopology] Tier 2 (Cognition): {len(tier2)} agents loaded")
    
    # --- TIER 3: EXPRESSION ---
    tier3 = [
        get_briefing_agent(),
        get_voice_agent(),
        get_persona_agent(),
        get_mission_agent(),
    ]
    nodes.extend(tier3)
    logger.info(f"[SwarmTopology] Tier 3 (Expression): {len(tier3)} agents loaded")
    
    logger.info(f"[SwarmTopology] ═══ COMPLETE: {len(nodes)} agents across 3 tiers ═══")
    return nodes


def get_p0_swarm_nodes() -> List[SwarmNode]:
    """
    Returns only the P0 (highest priority) agents for initial deployment.
    These are the core perception agents + Memory.
    """
    nodes = [
        get_energy_agent(),
        get_alarm_agent(),
        get_maintenance_agent(),
        get_comfort_agent(),
        get_memory_agent(),
    ]
    logger.info(f"[SwarmTopology] P0 deployment: {len(nodes)} agents")
    return nodes
