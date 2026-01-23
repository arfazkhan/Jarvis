"""
ARVIS Base Agent
================

Foundation agent class adapted from OpenManus pattern.

Provides:
- State machine (IDLE → RUNNING → FINISHED/ERROR)
- Memory management
- Step-based execution loop
- Stuck detection
"""

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from agent_unified.schema import AgentState, Memory, Message, Role


logger = logging.getLogger("arvis.unified.agent")


class ARVISBaseAgent(BaseModel, ABC):
    """
    Abstract base class for managing agent state and execution.
    
    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """
    
    # Core attributes
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Agent description")
    
    # Prompts
    system_prompt: Optional[str] = Field(None, description="System-level instruction")
    next_step_prompt: Optional[str] = Field(None, description="Prompt for next action")
    
    # Memory and state
    memory: Memory = Field(default_factory=Memory, description="Agent memory store")
    state: AgentState = Field(default=AgentState.IDLE, description="Current state")
    
    # Execution control
    max_steps: int = Field(default=20, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")
    duplicate_threshold: int = Field(default=2, description="Threshold for stuck detection")
    
    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra fields for flexibility
    
    @model_validator(mode="after")
    def initialize_agent(self) -> "ARVISBaseAgent":
        """Initialize agent with defaults if not provided"""
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self
    
    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """
        Context manager for safe agent state transitions.
        
        Args:
            new_state: The state to transition to during the context
            
        Yields:
            None
            
        Raises:
            ValueError: If the new_state is invalid
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")
        
        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR
            raise e
        finally:
            self.state = previous_state
    
    def update_memory(
        self,
        role: str,
        content: str,
        base64_image: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Add a message to the agent's memory.
        
        Args:
            role: Message role (user, system, assistant, tool)
            content: Message content
            base64_image: Optional base64 encoded image
            **kwargs: Additional message fields
        """
        message_creators = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
        }
        
        if role == "tool":
            msg = Message.tool_message(
                content=content,
                tool_call_id=kwargs.get("tool_call_id", ""),
                name=kwargs.get("name", ""),
                base64_image=base64_image
            )
        elif role in message_creators:
            msg = message_creators[role](content, base64_image) if role == "user" else message_creators[role](content)
        else:
            raise ValueError(f"Unsupported message role: {role}")
        
        self.memory.add_message(msg)
    
    async def run(self, request: Optional[str] = None) -> str:
        """
        Execute the agent's main loop asynchronously.
        
        Args:
            request: Optional initial user request
            
        Returns:
            String summarizing execution results
            
        Raises:
            RuntimeError: If agent is not in IDLE state
        """
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")
        
        if request:
            self.update_memory("user", request)
        
        results: List[str] = []
        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps 
                and self.state != AgentState.FINISHED
            ):
                self.current_step += 1
                logger.info(f"[{self.name}] Executing step {self.current_step}/{self.max_steps}")
                
                step_result = await self.step()
                
                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()
                
                results.append(f"Step {self.current_step}: {step_result}")
            
            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.IDLE
                results.append(f"Terminated: Reached max steps ({self.max_steps})")
        
        # Reset for next run
        self.current_step = 0
        return "\n".join(results) if results else "No steps executed"
    
    @abstractmethod
    async def step(self) -> str:
        """
        Execute a single step in the agent's workflow.
        
        Must be implemented by subclasses.
        
        Returns:
            String describing step result
        """
        pass
    
    def is_stuck(self) -> bool:
        """
        Check if the agent is stuck in a loop by detecting duplicate content.
        
        Returns:
            True if duplicate threshold exceeded
        """
        if len(self.memory.messages) < 2:
            return False
        
        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False
        
        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == Role.ASSISTANT.value and msg.content == last_message.content
        )
        
        return duplicate_count >= self.duplicate_threshold
    
    def handle_stuck_state(self) -> None:
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt = (
            "Observed duplicate responses. Consider new strategies and "
            "avoid repeating ineffective paths already attempted."
        )
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt or ''}"
        logger.warning(f"[{self.name}] Detected stuck state. Injecting strategy change prompt.")
    
    @property
    def messages(self) -> List[Message]:
        """Get all messages from memory"""
        return self.memory.messages
    
    @messages.setter
    def messages(self, value: List[Message]):
        """Set messages in memory"""
        self.memory.messages = value
    
    async def cleanup(self) -> None:
        """Cleanup resources. Override in subclasses if needed."""
        pass
