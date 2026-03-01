"""
Specialized Swarm Nodes for the ARVIS Commercial BMS.
These nodes replace the monolithic BMSLLMAgent, dividing its 
responsibilities into distinct domain experts.
"""

from typing import List, Dict, Any
from arvis_core.swarm.node import SwarmNode

def get_energy_agent(tools: List[Dict[str, Any]]) -> SwarmNode:
    """Agent specialized in energy analytics, forecasting, and cost optimization."""
    # Filter tools relevant to energy
    energy_tools = [t for t in tools if t['name'] in ['analyze_energy', 'forecast_energy', 'check_cost_impact', 'get_gsas_status']]
    
    return SwarmNode(
        name="Energy_Agent",
        role=(
            "You are the Energy Optimization Agent for ARVIS. "
            "Your sole focus is identifying energy waste, analyzing consumption drift, and proposing cost-saving measures. "
            "Always quantify your savings in kWh and monetary value. "
            "Do not concern yourself with equipment alarms unless they directly impact energy."
        ),
        tools=energy_tools
    )

def get_alarm_agent(tools: List[Dict[str, Any]]) -> SwarmNode:
    """Agent specialized in fault detection and alarm correlation."""
    alarm_tools = [t for t in tools if t['name'] in ['get_active_alarms', 'detect_equipment_faults', 'get_equipment_status']]
    
    return SwarmNode(
        name="Alarm_Agent",
        role=(
            "You are the Fault Verification Agent for ARVIS. "
            "Your goal is to investigate active alarms, correlate cascading faults to find the root cause, "
            "and verify equipment health. "
            "If another agent proposes an action, you must immediately check if the target equipment is currently faulting."
        ),
        tools=alarm_tools
    )

def get_maintenance_agent(tools: List[Dict[str, Any]]) -> SwarmNode:
    """Agent specialized in predictive maintenance and lifecycle tracking."""
    maintenance_tools = [t for t in tools if t['name'] in ['predict_remaining_life', 'verify_maintenance_work', 'list_equipment']]
    
    return SwarmNode(
        name="Maintenance_Agent",
        role=(
            "You are the Predictive Maintenance QA Agent for ARVIS. "
            "You oversee the lifecycle and structural integrity of physical equipment. "
            "Prioritize the Remaining Useful Life (RUL) of chillers and AHUs. "
            "You must flag any proposed actions that would excessively strain aging equipment."
        ),
        tools=maintenance_tools
    )

def get_comfort_agent(tools: List[Dict[str, Any]]) -> SwarmNode:
    """Agent specialized in tenant comfort and thermal simulation."""
    comfort_tools = [t for t in tools if t['name'] in ['simulate_change', 'find_ghost_spaces', 'get_equipment_status']]
    
    return SwarmNode(
        name="Comfort_Agent",
        role=(
            "You are the Thermal Comfort & Safety Agent for ARVIS. "
            "Your highest priority is ensuring physical spaces remain within safe and comfortable parameters. "
            "You are the ultimate veto on any energy savings. If a proposed energy optimization will cause a thermal safety breach "
            "(e.g. Server room over 24°C, or Patient room out of bounds), you must formally REJECT the proposal."
        ),
        tools=comfort_tools
    )
    
def get_all_swarm_nodes(tools: List[Dict[str, Any]]) -> List[SwarmNode]:
    """Returns all initialized nodes for the Commercial Queen."""
    return [
        get_energy_agent(tools),
        get_alarm_agent(tools),
        get_maintenance_agent(tools),
        get_comfort_agent(tools)
    ]
