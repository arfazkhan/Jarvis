import json
from typing import Any, List, Optional
from pydantic import Field

from .react import ARVISReActAgent
from agent_unified.schema import AgentState, Message, ToolCall, ToolChoice
from agent_unified.tools.collection import ToolCollection

class ARVISToolAgent(ARVISReActAgent):
    """Agent capable of executing tools"""
    
    available_tools: ToolCollection = Field(default_factory=lambda: ToolCollection())
    tool_choices: ToolChoice = ToolChoice.AUTO
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])
    
    # Current tool calls from last think()
    tool_calls: List[ToolCall] = Field(default_factory=list)
    
    async def think(self) -> bool:
        """Generate tool calls via LLM"""
        # Build messages for LLM
        messages = [msg.model_dump() for msg in self.memory.messages]
        
        if self.next_step_prompt:
            messages.append({"role": "user", "content": self.next_step_prompt})
        
        # Call LLM with tools
        try:
             # Use UnifiedLLM to ask with tools
             # Note: We must inject self.llm in the subclass or pass it in
             if not hasattr(self, 'llm'):
                 return False
                 
             response = await self.llm.ask_tool(
                 messages=messages,
                 system_msgs=[{"role": "system", "content": self.system_prompt}] if self.system_prompt else None,
                 tools=self.available_tools.to_params(),
                 tool_choice=self.tool_choices.value
             )
             
             # Extract tool calls
             if response.tool_calls:
                 self.tool_calls = response.tool_calls
                 # Store assistant message with tool calls
                 self.memory.add_message(Message.from_tool_calls(response.tool_calls, response.content or ""))
                 return True
             
             # No tools - just text response
             if response.content:
                 self.update_memory("assistant", response.content)
            
             return False

        except Exception as e:
             # Fallback error handling
             self.update_memory("assistant", f"I encountered an error: {str(e)}")
             return False
    
    async def act(self) -> str:
        """Execute tool calls"""
        results = []
        
        for tc in self.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments) or {}
            
            # Execute tool
            result = await self.available_tools.execute(name, **args)
            
            # Store result
            self.memory.add_message(
                Message.tool_message(str(result), tc.id, name)
            )
            
            # Handle special tools
            if name in self.special_tool_names:
                await self._handle_special_tool(name, result)
            
            results.append(f"{name}: {result}")
        
        self.tool_calls = []
        return "\n".join(results)
    
    async def _handle_special_tool(self, name: str, result: Any):
        """Handle special tool execution"""
        if name == "terminate":
            self.state = AgentState.FINISHED
