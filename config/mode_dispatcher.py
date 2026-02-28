"""
ARVIS Mode Dispatcher
=====================

Central module that handles mode-based configuration for ARVIS.

Modes:
    - residential: Home automation (smart home, lights, routines)
    - commercial:  BMS Ops Copilot (chillers, AHUs, energy, GSAS)

This module provides:
    - Mode detection from environment
    - Mode-specific tools schema
    - Mode-specific system prompts
    - Mode-specific tool execution
"""

import os
import sys
import logging
from typing import Dict, Any, List, Callable, Optional
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("arvis.mode")


# ═══════════════════════════════════════════════════════════════════════════
# MODE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

class ArvisMode(Enum):
    """Available ARVIS operational modes"""
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    

@dataclass
class ModeConfig:
    """Configuration for a specific ARVIS mode"""
    mode: ArvisMode
    name: str
    description: str
    tools_module: str
    prompt_module: str
    cognitive_enabled: bool = True
    features: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# MODE CONFIGURATIONS
# ═══════════════════════════════════════════════════════════════════════════

MODES: Dict[ArvisMode, ModeConfig] = {
    ArvisMode.RESIDENTIAL: ModeConfig(
        mode=ArvisMode.RESIDENTIAL,
        name="ARVIS Home",
        description="Smart home automation assistant",
        tools_module="agent.llm_agent.tools_schema",
        prompt_module="agent.llm_agent.prompt",
        cognitive_enabled=True,
        features=[
            "device_control",      # Lights, switches, fans
            "timers",              # Delayed actions
            "routines",            # Automated workflows
            "memory",              # User preferences
            "home_assistant",      # HA integration
            "voice",               # Voice control
        ]
    ),
    
    ArvisMode.COMMERCIAL: ModeConfig(
        mode=ArvisMode.COMMERCIAL,
        name="ARVIS Ops Copilot",
        description="AI-powered Building Management System advisor",
        tools_module="agent_commercial.tools_schema",
        prompt_module="agent_commercial.tools_schema",  # Prompts are in same file
        cognitive_enabled=True,
        features=[
            "equipment_monitoring",  # Chillers, AHUs, VAVs
            "predictive_maintenance", # Failure prediction
            "energy_analysis",       # Waste detection
            "alarm_management",      # Intelligent alarming
            "gsas_compliance",       # Qatar sustainability
            "bacnet",                # BACnet integration
        ]
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# MODE DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════

class ModeDispatcher:
    """
    Singleton dispatcher that manages ARVIS operational mode.
    
    Usage:
        dispatcher = ModeDispatcher.get_instance()
        
        # Get current mode
        mode = dispatcher.mode
        
        # Get tools for current mode
        tools = dispatcher.get_tools_schema()
        
        # Get system prompt
        prompt = dispatcher.get_system_prompt()
        
        # Execute a tool call
        result = dispatcher.execute_tool(tool_name, **args)
    """
    
    _instance: Optional["ModeDispatcher"] = None
    
    @classmethod
    def get_instance(cls) -> "ModeDispatcher":
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)"""
        cls._instance = None
    
    def __init__(self):
        # Detect mode from environment
        mode_str = os.getenv("ARVIS_MODE", "residential").lower()
        
        try:
            self._mode = ArvisMode(mode_str)
        except ValueError:
            logger.warning(f"Unknown ARVIS_MODE '{mode_str}', defaulting to residential")
            self._mode = ArvisMode.RESIDENTIAL
        
        self._config = MODES[self._mode]
        self._tools_cache: Optional[List[Dict]] = None
        self._prompt_cache: Optional[str] = None
        self._tool_executor: Optional[Any] = None
        
        logger.info(f"ARVIS Mode: {self._config.name} ({self._mode.value})")
    
    @property
    def mode(self) -> ArvisMode:
        """Current operational mode"""
        return self._mode
    
    @property
    def config(self) -> ModeConfig:
        """Current mode configuration"""
        return self._config
    
    @property
    def is_residential(self) -> bool:
        return self._mode == ArvisMode.RESIDENTIAL
    
    @property
    def is_commercial(self) -> bool:
        return self._mode == ArvisMode.COMMERCIAL
    
    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Get the tools schema for current mode.
        
        Returns:
            List of tool definitions in OpenAI function calling format
        """
        if self._tools_cache is not None:
            return self._tools_cache
        
        if self._mode == ArvisMode.RESIDENTIAL:
            from agent_home.llm_agent.tools_schema import TOOLS_SCHEMA
            self._tools_cache = TOOLS_SCHEMA
            
        elif self._mode == ArvisMode.COMMERCIAL:
            from agent_commercial.tools_schema import get_bms_tools
            self._tools_cache = get_bms_tools()
        
        return self._tools_cache or []
    
    def get_system_prompt(self, language: str = "en") -> str:
        """
        Get the system prompt for current mode.
        
        Args:
            language: "en" for English, "ar" for Arabic
            
        Returns:
            System prompt string
        """
        if self._mode == ArvisMode.RESIDENTIAL:
            from agent_home.llm_agent.prompt import get_system_prompt
            return get_system_prompt()
            
        elif self._mode == ArvisMode.COMMERCIAL:
            from agent_commercial.tools_schema import OPS_COPILOT_SYSTEM_PROMPT, OPS_COPILOT_SYSTEM_PROMPT_AR
            return OPS_COPILOT_SYSTEM_PROMPT_AR if language == "ar" else OPS_COPILOT_SYSTEM_PROMPT
        
        return ""
    
    def get_tool_executor(self) -> Any:
        """
        Get the tool executor instance for current mode.
        
        Returns:
            ToolExecutor instance (residential) or BMSToolHandler (commercial)
        """
        if self._tool_executor is not None:
            return self._tool_executor
        
        if self._mode == ArvisMode.RESIDENTIAL:
            from agent_home.llm_agent.executor import ToolExecutor
            self._tool_executor = ToolExecutor()
            
        elif self._mode == ArvisMode.COMMERCIAL:
            from agent_commercial.tools_schema import BMSToolHandlerSync
            self._tool_executor = BMSToolHandlerSync()
        
        return self._tool_executor
    
    def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a tool by name with given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            **kwargs: Tool arguments
            
        Returns:
            Tool execution result
        """
        executor = self.get_tool_executor()
        
        if self._mode == ArvisMode.RESIDENTIAL:
            return executor.execute(tool_name, **kwargs)
            
        elif self._mode == ArvisMode.COMMERCIAL:
            return executor.handle_tool_call(tool_name, kwargs)
        
        return {"error": f"Unknown mode: {self._mode}"}
    
    def get_greeting(self) -> str:
        """Get mode-specific greeting"""
        if self._mode == ArvisMode.RESIDENTIAL:
            return "Hello! I'm ARVIS, your smart home assistant. How can I help you today?"
        else:
            return "Welcome to ARVIS Ops Copilot. I'm your AI advisor for building management. How can I assist you today?"
    
    def get_capabilities(self) -> List[str]:
        """Get list of capabilities for current mode"""
        return self._config.features


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_mode() -> ArvisMode:
    """Get current ARVIS mode"""
    return ModeDispatcher.get_instance().mode


def is_residential() -> bool:
    """Check if running in residential mode"""
    return ModeDispatcher.get_instance().is_residential


def is_commercial() -> bool:
    """Check if running in commercial (BMS) mode"""
    return ModeDispatcher.get_instance().is_commercial


def get_tools() -> List[Dict[str, Any]]:
    """Get tools schema for current mode"""
    return ModeDispatcher.get_instance().get_tools_schema()


def get_prompt(language: str = "en") -> str:
    """Get system prompt for current mode"""
    return ModeDispatcher.get_instance().get_system_prompt(language)


def execute_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """Execute a tool in current mode"""
    return ModeDispatcher.get_instance().execute_tool(tool_name, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# INITIALIZATION CHECK
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Quick test
    dispatcher = ModeDispatcher.get_instance()
    
    print(f"\n{'='*60}")
    print(f"ARVIS Mode: {dispatcher.config.name}")
    print(f"Description: {dispatcher.config.description}")
    print(f"{'='*60}")
    print(f"\nCapabilities:")
    for feature in dispatcher.get_capabilities():
        print(f"  - {feature}")
    
    print(f"\nTools available: {len(dispatcher.get_tools_schema())}")
    print(f"\nGreeting: {dispatcher.get_greeting()}")
