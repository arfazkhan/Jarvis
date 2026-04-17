"""
Base Agent Node for the ARVIS Swarm.
Represents a single, specialized agent (e.g., Energy Agent, Safety Agent)
that focuses on a specific domain using specific tools.
"""

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

logger = logging.getLogger("arvis.swarm.node")

class SwarmNode(BaseModel):
    """
    A single specialized agent within the ARVIS Swarm.
    """
    name: str = Field(..., description="The name of the agent node (e.g., 'Thermal_Comfort_Agent').")
    role: str = Field(..., description="The system prompt describing the agent's specialization and constraints.")
    tools: List[Dict[str, Any]] = Field(default_factory=list, description="The specific tools this agent has access to.")
    
    tool_handler: Any = Field(default=None, exclude=True)
    llm: Any = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None, history: Optional[List[Dict]] = None, channel: str = "chat") -> Dict[str, Any]:
        """
        Processes a query within the agent's specific domain using a ReAct loop.
        Returns a dict with 'response' (Message) and 'history' (evidence list).
        """
        logger.info(f"[Node: {self.name}] Processing query: {query[:50]}...")
        
        system_msgs = [{"role": "system", "content": self.role}]
        if context:
            import json
            system_msgs.append({
                "role": "system", 
                "content": f"Global Context:\n{json.dumps(context, default=str)}"
            })

        messages = history or []
        messages.append({"role": "user", "content": query})
        
        max_turns = 3
        current_turn = 0
        
        while current_turn < max_turns:
            try:
                # We use ask_tool if the node has tools, otherwise standard ask
                if self.tools and self.tool_handler:
                    # Convert to OpenAI tool schema format for UnifiedLLM
                    tools_def = [
                        {
                            "type": "function",
                            "function": {
                                "name": t["name"],
                                "description": t["description"],
                                "parameters": t["parameters"]
                            }
                        } for t in self.tools
                    ]
                    response = await self.llm.ask_tool(
                        messages=messages,
                        system_msgs=system_msgs,
                        tools=tools_def,
                        tool_choice="auto",
                        channel=channel
                    )
                else:
                    response = await self.llm.ask(
                        messages=messages,
                        system_msgs=system_msgs,
                        channel=channel
                    )
                    
                # If no tool calls, this is the final answer
                if not response.tool_calls:
                    return {"response": response, "history": messages}
                    
                # If there are tool calls, execute them
                messages.append({"role": "assistant", "content": response.content, "tool_calls": response.model_dump().get("tool_calls")})
                
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    args_str = tool_call.function.arguments
                    logger.info(f"[Node: {self.name}] Executing tool: {tool_name}")
                    
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        if args is None:
                            args = {}
                        
                        if self.tool_handler:
                            result = await self.tool_handler.execute(tool_name, args)
                        else:
                            result = "Error: Tool handler not configured for this node."
                    except Exception as e:
                        result = f"Error executing tool {tool_name}: {str(e)}"
                        
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": str(result)
                    })
                
                current_turn += 1
                
            except Exception as e:
                logger.error(f"[Node: {self.name}] Failed to process query on turn {current_turn}: {e}")
                return {
                    "response": Message(role="assistant", content=f"[{self.name}] internal error: {str(e)}"),
                    "history": messages
                }
                
        logger.warning(f"[Node: {self.name}] Max Agent turns ({max_turns}) reached.")
        # Force a final plain answer via generic ask to summarize
        messages.append({"role": "user", "content": "Please synthesize a final proposal based on your observations so far."})
        final_response = await self.llm.ask(messages=messages, system_msgs=system_msgs, channel=channel)
        return {"response": final_response, "history": messages}
