"""
BMS Tools Module
================

Class-based BMS tools for ARVIS unified agent.

Provides typed, injectable tool classes for:
- Equipment status and management
- Alarm handling and analysis
- Energy monitoring and optimization
- GSAS sustainability compliance
- Building skillbook (institutional memory)
- ML-powered analytics
- Operations (briefings, ghost detection, maintenance verification)
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

# Skillbook tools
from .skillbook import (
    QuerySkillbook,
    AddToSkillbook,
    FindSimilarSkills
)

# ML Analytics tools
from .ml_analytics import (
    ForecastEnergy,
    DetectEquipmentFaults,
    AnalyzeRootCause,
    SimulateWithUncertainty,
    BenchmarkBuildingML
)

# Operations tools
from .operations import (
    GenerateBriefing,
    FindGhostSpaces,
    EstimateZoneOccupancy,
    VerifyMaintenanceWork,
    AnalyzeCascade,
    CorrelateEvents,
    SimulateChange,
    PredictRemainingLife,
    PredictMaintenance,
    GetDashboardOverview,
    GetPointHistory,
    CompareToFleet
)


__all__ = [
    # Equipment
    "GetEquipmentStatus", "ListEquipment", "GetEquipmentHealth",
    # Alarms
    "GetActiveAlarms", "ExplainAlarm", "AcknowledgeAlarm",
    # Energy
    "AnalyzeEnergy", "GetEnergyAnomalies", "CheckCostImpact", "GetBurnRate",
    # GSAS
    "GetGSASStatus", "GetGSASImprovementPriorities", "GenerateGORDReport",
    # Skillbook
    "QuerySkillbook", "AddToSkillbook", "FindSimilarSkills",
    # ML Analytics
    "ForecastEnergy", "DetectEquipmentFaults", "AnalyzeRootCause",
    "SimulateWithUncertainty", "BenchmarkBuildingML",
    # Operations
    "GenerateBriefing", "FindGhostSpaces", "EstimateZoneOccupancy",
    "VerifyMaintenanceWork", "AnalyzeCascade", "CorrelateEvents",
    "SimulateChange", "PredictRemainingLife", "PredictMaintenance",
    "GetDashboardOverview", "GetPointHistory", "CompareToFleet",
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
        ml_engine: Optional[Any] = None,
        briefing_engine: Optional[Any] = None
    ):
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.gsas_reporter = gsas_reporter
        self.skillbook = skillbook
        self.ml_engine = ml_engine
        self.briefing_engine = briefing_engine
    
    def get_tools(self) -> List[BaseTool]:
        """
        Create all BMS tools with injected engines.
        
        Returns:
            List of fully configured BaseTool instances (33 tools total)
        """
        return [
            # ─── Equipment (3 tools) ───
            GetEquipmentStatus(bms_state=self.bms_state),
            ListEquipment(bms_state=self.bms_state),
            GetEquipmentHealth(bms_state=self.bms_state, ml_engine=self.ml_engine),
            
            # ─── Alarms (3 tools) ───
            GetActiveAlarms(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            ExplainAlarm(alarm_engine=self.alarm_engine, bms_state=self.bms_state, skillbook=self.skillbook),
            AcknowledgeAlarm(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            
            # ─── Energy (4 tools) ───
            AnalyzeEnergy(energy_analyzer=self.energy_analyzer),
            GetEnergyAnomalies(energy_analyzer=self.energy_analyzer),
            CheckCostImpact(energy_analyzer=self.energy_analyzer),
            GetBurnRate(energy_analyzer=self.energy_analyzer, bms_state=self.bms_state),
            
            # ─── GSAS (3 tools) ───
            GetGSASStatus(gsas_reporter=self.gsas_reporter, bms_state=self.bms_state),
            GetGSASImprovementPriorities(gsas_reporter=self.gsas_reporter),
            GenerateGORDReport(gsas_reporter=self.gsas_reporter),
            
            # ─── Skillbook (3 tools) ───
            QuerySkillbook(skillbook=self.skillbook),
            AddToSkillbook(skillbook=self.skillbook),
            FindSimilarSkills(skillbook=self.skillbook),
            
            # ─── ML Analytics (5 tools) ───
            ForecastEnergy(ml_engine=self.ml_engine),
            DetectEquipmentFaults(ml_engine=self.ml_engine, bms_state=self.bms_state),
            AnalyzeRootCause(ml_engine=self.ml_engine),
            SimulateWithUncertainty(ml_engine=self.ml_engine),
            BenchmarkBuildingML(ml_engine=self.ml_engine),
            
            # ─── Operations (12 tools) ───
            GenerateBriefing(briefing_engine=self.briefing_engine),
            FindGhostSpaces(bms_state=self.bms_state),
            EstimateZoneOccupancy(),
            VerifyMaintenanceWork(bms_state=self.bms_state),
            AnalyzeCascade(alarm_engine=self.alarm_engine),
            CorrelateEvents(),
            SimulateChange(),
            PredictRemainingLife(ml_engine=self.ml_engine),
            PredictMaintenance(ml_engine=self.ml_engine),
            GetDashboardOverview(bms_state=self.bms_state),
            GetPointHistory(bms_state=self.bms_state),
            CompareToFleet(),
        ]
    
    def get_tool_count(self) -> int:
        """Get total number of tools"""
        return 33
    
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
    
    def get_ml_tools(self) -> List[BaseTool]:
        """Get only ML-powered tools"""
        return [
            ForecastEnergy(ml_engine=self.ml_engine),
            DetectEquipmentFaults(ml_engine=self.ml_engine, bms_state=self.bms_state),
            AnalyzeRootCause(ml_engine=self.ml_engine),
            SimulateWithUncertainty(ml_engine=self.ml_engine),
            BenchmarkBuildingML(ml_engine=self.ml_engine),
            PredictRemainingLife(ml_engine=self.ml_engine),
            PredictMaintenance(ml_engine=self.ml_engine),
        ]
    
    def get_essential_tools(self) -> List[BaseTool]:
        """Get minimal essential tools for basic operation"""
        return [
            GetEquipmentStatus(bms_state=self.bms_state),
            ListEquipment(bms_state=self.bms_state),
            GetActiveAlarms(alarm_engine=self.alarm_engine, bms_state=self.bms_state),
            AnalyzeEnergy(energy_analyzer=self.energy_analyzer),
            GetDashboardOverview(bms_state=self.bms_state),
        ]
