from typing import List, Optional, Any
from agent_unified.tools.base import BaseTool
from .equipment import GetEquipmentStatus, ListEquipment
from .alarms import GetActiveAlarms, AcknowledgeAlarm
from .energy import AnalyzeEnergy, GetWastePatterns
from .gsas import GetGSASStatus

class BMSToolkit:
    """Factory for BMS tools with engine injection"""
    
    def __init__(
        self,
        bms_state=None,
        alarm_engine=None,
        energy_analyzer=None,
        skillbook=None
    ):
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.skillbook = skillbook
    
    def get_tools(self) -> List[BaseTool]:
        """Create all BMS tools with injected engines"""
        tools = [
            GetEquipmentStatus(bms_state=self.bms_state),
            ListEquipment(bms_state=self.bms_state),
            GetActiveAlarms(alarm_engine=self.alarm_engine),
            AcknowledgeAlarm(alarm_engine=self.alarm_engine),
            AnalyzeEnergy(energy_analyzer=self.energy_analyzer),
            GetWastePatterns(energy_analyzer=self.energy_analyzer),
            GetGSASStatus(bms_state=self.bms_state),
        ]
        return tools
