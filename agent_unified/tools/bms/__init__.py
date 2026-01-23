"""
BMS Tools Module
================

Class-based BMS tools for ARVIS unified agent.

Provides typed, injectable tool classes for:
- Equipment status and management
- Alarm handling and analysis
- Energy monitoring and optimization
- GSAS sustainability compliance
"""

from typing import Any, List, Optional

from agent_unified.tools.base import BaseTool

# Equipment tools
from .equipment import (
    GetEquipmentStatus,
    ListEquipment,
    GetEquipmentHealth
)

# Alarm tools
from .alarms import (
    GetActiveAlarms,
    ExplainAlarm,
    AcknowledgeAlarm
)

# Energy tools
from .energy import (
    AnalyzeEnergy,
    GetEnergyAnomalies,
    CheckCostImpact,
    GetBurnRate
)

# GSAS tools
from .gsas import (
    GetGSASStatus,
    GetGSASImprovementPriorities,
    GenerateGORDReport
)


__all__ = [
    # Equipment
    "GetEquipmentStatus",
    "ListEquipment", 
    "GetEquipmentHealth",
    # Alarms
    "GetActiveAlarms",
    "ExplainAlarm",
    "AcknowledgeAlarm",
    # Energy
    "AnalyzeEnergy",
    "GetEnergyAnomalies",
    "CheckCostImpact",
    "GetBurnRate",
    # GSAS
    "GetGSASStatus",
    "GetGSASImprovementPriorities",
    "GenerateGORDReport",
    # Factory
    "BMSToolkit"
]


class BMSToolkit:
    """
    Factory for creating BMS tools with injected engines.
    
    Usage:
        toolkit = BMSToolkit(
            bms_state=state_engine,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer
        )
        tools = toolkit.get_tools()
    """
    
    def __init__(
        self,
        bms_state: Optional[Any] = None,
        alarm_engine: Optional[Any] = None,
        energy_analyzer: Optional[Any] = None,
        gsas_reporter: Optional[Any] = None,
        skillbook: Optional[Any] = None,
        ml_engine: Optional[Any] = None
    ):
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.gsas_reporter = gsas_reporter
        self.skillbook = skillbook
        self.ml_engine = ml_engine
    
    def get_tools(self) -> List[BaseTool]:
        """
        Create all BMS tools with injected engines.
        
        Returns:
            List of fully configured BaseTool instances
        """
        return [
            # Equipment tools
            GetEquipmentStatus(bms_state=self.bms_state),
            ListEquipment(bms_state=self.bms_state),
            GetEquipmentHealth(bms_state=self.bms_state, ml_engine=self.ml_engine),
            
            # Alarm tools
            GetActiveAlarms(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            ExplainAlarm(
                alarm_engine=self.alarm_engine, 
                bms_state=self.bms_state,
                skillbook=self.skillbook
            ),
            AcknowledgeAlarm(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            
            # Energy tools
            AnalyzeEnergy(energy_analyzer=self.energy_analyzer),
            GetEnergyAnomalies(energy_analyzer=self.energy_analyzer),
            CheckCostImpact(energy_analyzer=self.energy_analyzer),
            GetBurnRate(energy_analyzer=self.energy_analyzer, bms_state=self.bms_state),
            
            # GSAS tools
            GetGSASStatus(gsas_reporter=self.gsas_reporter, bms_state=self.bms_state),
            GetGSASImprovementPriorities(gsas_reporter=self.gsas_reporter),
            GenerateGORDReport(gsas_reporter=self.gsas_reporter),
        ]
    
    def get_equipment_tools(self) -> List[BaseTool]:
        """Get only equipment-related tools"""
        return [
            GetEquipmentStatus(bms_state=self.bms_state),
            ListEquipment(bms_state=self.bms_state),
            GetEquipmentHealth(bms_state=self.bms_state, ml_engine=self.ml_engine),
        ]
    
    def get_alarm_tools(self) -> List[BaseTool]:
        """Get only alarm-related tools"""
        return [
            GetActiveAlarms(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            ExplainAlarm(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            AcknowledgeAlarm(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
        ]
    
    def get_energy_tools(self) -> List[BaseTool]:
        """Get only energy-related tools"""
        return [
            AnalyzeEnergy(energy_analyzer=self.energy_analyzer),
            GetEnergyAnomalies(energy_analyzer=self.energy_analyzer),
            CheckCostImpact(energy_analyzer=self.energy_analyzer),
            GetBurnRate(energy_analyzer=self.energy_analyzer, bms_state=self.bms_state),
        ]
