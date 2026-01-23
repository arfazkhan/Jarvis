"""
ARVIS Tool Call Agent
=====================

Agent capable of executing LLM tool calls.

Extends ReActAgent with:
- LLM integration for tool call generation
- Tool execution and result handling
- Special tool handling (terminate, ask_human)
"""

import json
import logging
from typing import Any, List, Optional

from pydantic import Field

from agent_unified.schema import AgentState, Message, ToolCall, ToolChoice, Function
from agent_unified.tools.base import ToolResult
from agent_unified.tools.collection import ToolCollection
from agent_unified.llm import UnifiedLLM
from .react import ARVISReActAgent


logger = logging.getLogger("arvis.unified.toolcall")

TOOL_CALL_REQUIRED = "Tool calls required but none provided"


class ARVISToolAgent(ARVISReActAgent):
    """
    Agent that can execute tool/function calls.
    
    Extends ReActAgent with:
    - LLM tool calling via think()
    - Multi-tool execution via act()
    - Special tool handling (terminate, etc.)
    """
    
    # LLM client
    llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    
    # Tools
    available_tools: ToolCollection = Field(default_factory=ToolCollection)
    tool_choices: ToolChoice = Field(default=ToolChoice.AUTO)
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])
    
    # Current pending tool calls
    tool_calls: List[ToolCall] = Field(default_factory=list)
    
    # Tool execution settings
    parallel_tool_calls: bool = Field(default=True, description="Execute tools in parallel")
    max_observe: int = Field(default=10000, description="Max chars in tool observation")
    
    async def think(self) -> bool:
        """
        Generate tool calls via LLM.
        
        Returns:
            True if tool calls were generated
        """
        # Build messages for LLM
        messages = [msg.to_dict() for msg in self.memory.messages]
        
        # Add next step prompt if present
        if self.next_step_prompt:
            messages.append({"role": "user", "content": self.next_step_prompt})
        
        # Get system messages
        system_msgs = None
        if self.system_prompt:
            system_msgs = [{"role": "system", "content": self.system_prompt}]
        
        try:
            # Call LLM with tools
            response = await self.llm.ask_tool(
                messages=messages,
                system_msgs=system_msgs,
                tools=self.available_tools.to_params() if len(self.available_tools) > 0 else None,
                tool_choice=self.tool_choices.value
            )
            
            # Check for tool calls in response
            if hasattr(response, 'tool_calls') and response.tool_calls:
                self.tool_calls = [
                    ToolCall(
                        id=tc.id,
                        function=Function(
                            name=tc.function.name,
                            arguments=tc.function.arguments
                        )
                    )
                    for tc in response.tool_calls
                ]
                
                # Store assistant message with tool calls
                self.memory.add_message(
                    Message.from_tool_calls(response.tool_calls, response.content or "")
                )
                
                logger.info(f"[{self.name}] Generated {len(self.tool_calls)} tool calls")
                return True
            
            # No tool calls - store text response
            if hasattr(response, 'content') and response.content:
                self.update_memory("assistant", response.content)
            
            return False
            
        except Exception as e:
            logger.error(f"[{self.name}] Error in think(): {e}")
            self.update_memory("assistant", f"Error generating response: {str(e)}")
            return False
    
    async def act(self) -> str:
        """
        Execute pending tool calls.
        
        Returns:
            String describing execution results
        """
        if not self.tool_calls:
            return "No tool calls to execute"
        
        results = []
        
        for tc in self.tool_calls:
            name = tc.function.name
            
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                logger.error(f"[{self.name}] Invalid JSON in tool args: {e}")
                args = {}
            
            # Execute tool
            result = await self.execute_tool(name, tc.id, **args)
            
            # Handle special tools
            if self._is_special_tool(name):
                await self._handle_special_tool(name, result)
            
            results.append(f"{name}: {result}")
        
        # Clear pending calls
        self.tool_calls = []
        
        return "\n".join(results)
    
    async def execute_tool(self, name: str, tool_call_id: str, **kwargs) -> ToolResult:
        """
        Execute a single tool call with error handling.
        
        Args:
            name: Tool name
            tool_call_id: Tool call ID for result tracking
            **kwargs: Tool arguments
            
        Returns:
            ToolResult from execution
        """
        logger.info(f"[{self.name}] Executing tool: {name}")
        
        try:
            result = await self.available_tools.execute(name, **kwargs)
            
            # Truncate if too long
            result_str = str(result)
            if len(result_str) > self.max_observe:
                result_str = result_str[:self.max_observe] + "... (truncated)"
            
            # Store tool result in memory
            self.memory.add_message(
                Message.tool_message(
                    content=result_str,
                    tool_call_id=tool_call_id,
                    name=name
                )
            )
            
            return result
            
        except Exception as e:
            error_msg = f"Tool execution error: {str(e)}"
            logger.error(f"[{self.name}] {error_msg}")
            
            self.memory.add_message(
                Message.tool_message(
                    content=error_msg,
                    tool_call_id=tool_call_id,
                    name=name
                )
            )
            
            return ToolResult(error=error_msg)
    
    def _is_special_tool(self, name: str) -> bool:
        """Check if tool is special (triggers state change)"""
        return name in self.special_tool_names
    
    async def _handle_special_tool(self, name: str, result: Any) -> None:
        """
        Handle special tool execution.
        
        Args:
            name: Tool name
            result: Tool result
        """
        if name == "terminate":
            logger.info(f"[{self.name}] Terminate tool called - finishing execution")
            self.state = AgentState.FINISHED
    
    async def run(self, request: Optional[str] = None) -> str:
        """Run the agent with cleanup when done"""
        try:
            result = await super().run(request)
            return result
        finally:
            await self.cleanup()
    
    async def cleanup(self) -> None:
        """Clean up tool resources"""
        for tool in self.available_tools:
            if hasattr(tool, 'cleanup'):
                await tool.cleanup()
