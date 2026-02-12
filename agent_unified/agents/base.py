from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional, AsyncGenerator
from pydantic import BaseModel, Field

from agent_unified.schema import AgentState, Message, Memory
# Placeholder import for UnifiedLLM until we create it
# from agent_unified.llm import UnifiedLLM 

class ARVISBaseAgent(BaseModel, ABC):
    """Base agent with state management and memory"""
    
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    next_step_prompt: Optional[str] = None
    
    # llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    memory: Memory = Field(default_factory=Memory)
    state: AgentState = AgentState.IDLE
    
    max_steps: int = 20
    current_step: int = 0
    duplicate_threshold: int = 2
    
    class Config:
        arbitrary_types_allowed = True
    
    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Safe state transitions"""
        previous = self.state
        self.state = new_state
        try:
            yield
        except Exception:
            self.state = AgentState.ERROR
            raise
        finally:
            self.state = previous
    
    def update_memory(self, role: str, content: str, **kwargs):
        """Add message to memory"""
        msg = Message(role=role, content=content, **kwargs)
        self.memory.add_message(msg)
    
    async def run(self, request: Optional[str] = None) -> str:
        """Main execution loop"""
        if request:
            self.update_memory("user", request)
        
        results = []
        async with self.state_context(AgentState.RUNNING):
            while self.current_step < self.max_steps and self.state != AgentState.FINISHED:
                self.current_step += 1
                result = await self.step()
                
                if self.is_stuck():
                    self.handle_stuck_state()
                
                results.append(f"Step {self.current_step}: {result}")
        
        self.current_step = 0
        return "\n".join(results)

    async def run_streaming(self, request: str) -> "AsyncGenerator[str, None]":
        """Streaming execution loop (Phase 6 MVP Placeholder)"""
        # In a real implementation, this would yield tokens from the LLM
        # For now, we just yield the full result step-by-step
        if request:
            self.update_memory("user", request)
            
        async with self.state_context(AgentState.RUNNING):
             while self.current_step < self.max_steps and self.state != AgentState.FINISHED:
                self.current_step += 1
                result = await self.step()
                yield result + "\n"
        
        self.current_step = 0

    @abstractmethod
    async def step(self) -> str:
        """Single execution step"""
        pass
    
    def is_stuck(self) -> bool:
        """Detect duplicate responses"""
        if len(self.memory.messages) < 2:
            return False
        
        last = self.memory.messages[-1]
        if not last.content:
            return False
        
        count = sum(
            1 for msg in self.memory.messages[:-1]
            if msg.role == "assistant" and msg.content == last.content
        )
        return count >= self.duplicate_threshold
    
    def handle_stuck_state(self):
        """Inject strategy change"""
        self.next_step_prompt = (
            "Duplicate responses detected. Try a different approach.\n"
            + (self.next_step_prompt or "")
        )
