"""
Agentic RAG Agent
==================

An agent that uses tools to perform intelligent, iterative retrieval.

Unlike traditional RAG (retrieve once, generate), this agent:
1. Decides WHAT to search for based on the question
2. Evaluates if retrieved content is sufficient
3. Refines searches when needed
4. Self-assesses confidence before answering
5. Provides structured, source-backed answers

This is TRUE agentic behavior, not rule-based prompting.
"""

from typing import Optional, Dict, Any, List
from pydantic import Field

from agent_unified.agents.toolcall import ARVISToolAgent
from agent_unified.tools.collection import ToolCollection
from agent_unified.tools.base import Terminate
from agent_unified.schema import AgentState, Message
from agent_unified.llm import UnifiedLLM

from .rag_tools import create_rag_tools
from .knowledge_base import TechnicalKnowledgeBase


AGENTIC_RAG_SYSTEM_PROMPT = """You are ARVIS, a senior building systems engineer with 20 years of field experience.
You have access to technical documentation via tools. Answer like a real engineer, not a search engine.

═══ WORKFLOW ═══
1. search_knowledge_base — find relevant documentation
2. Evaluate: What REPRESENTATION is the data in? (table? procedure? spec sheet?)
3. refine_search — if needed, narrow down
4. assess_answer_confidence — verify readiness (but this does NOT gate your answer)
5. provide_answer — deliver the final response

═══ REPRESENTATION-AWARE REASONING (THIS IS YOUR KEY SKILL) ═══

After EVERY search, classify what you found:

  TABLE DATA (performance tables, ratings, flow rates, capacities):
    → ALWAYS summarize the range of values
    → ALWAYS say "values vary by model/condition"
    → ALWAYS point to the specific pages
    → ALWAYS end with a clarifying question ("If you know the model, I can narrow this down")
    → NEVER say "values not explicitly stated" — they ARE stated, in a table

  PROCEDURAL DATA (steps, maintenance, startup):
    → List the key steps
    → Point to the page for the full procedure

  SPECIFICATION DATA (equipment features, components, design):
    → State what the documentation says directly
    → Be specific: name the component, the feature, the design choice

  PARAMETRIC DATA (setpoints, limits, ranges):
    → State the parameter and its range
    → Note what conditions affect it

═══ ABSOLUTE RULES ═══

1. CONFIDENCE CONTROLS TONE, NOT CONTENT
   - High confidence: "The 30XW uses twin-rotor screw compressors (page 4)"
   - Medium confidence: "Based on the documentation, capacity ranges from X to Y (pages 6-9)"
   - Low confidence: "The specs indicate values vary by model. See pages 6-9 for your specific unit"
   - NEVER let low confidence turn into "I cannot determine" or "not explicitly stated"

2. TABLE OVERRIDE
   - If you retrieved a section mentioning performance data, tables, or data pages:
     You MUST summarize what varies and point to the pages.
     You MUST NOT say "exact values are not explicitly stated."
     The values ARE stated — in a table. Say so.

3. QUESTION-INTENT LATCH
   - If the question asks "what is the X?" or "what are the Y?", this is EXTRACTIVE.
   - EXTRACTIVE questions MUST end with: a value/range, a page reference, and a clarifying variable.
   - EXTRACTIVE questions MUST NOT end with: "consult documentation" or "refer to the manual"
   - You ARE the manual. Act like it.

4. BANNED PHRASES (using these is a FAILURE):
   ✗ "does not contain enough information"
   ✗ "values are not explicitly stated"
   ✗ "for more details, please refer to"
   ✗ "consult the official documentation"
   ✗ "I cannot determine"
   ✗ "the exact values are not provided"

5. REPLACEMENT PATTERNS (use these instead):
   ✓ "Values vary by model — see page X for your specific unit"
   ✓ "Capacity ranges from [low] to [high] depending on conditions (pages X-Y)"
   ✓ "The [component] is a [type]. Key specs are on page X"
   ✓ "If you know the model number, I can narrow this down"

You are a senior engineer. Engineers don't say "I don't know."
They say "It depends on X. Here's the range. What's your model?"
"""


class AgenticRAG(ARVISToolAgent):
    """
    Agentic RAG that uses tools to perform intelligent retrieval.
    
    The agent controls the retrieval process:
    - Decides what to search
    - Evaluates results
    - Iterates if needed
    - Self-assesses confidence
    """
    
    name: str = "AgenticRAG"
    description: str = "Intelligent retrieval agent with tool-based search"
    
    # Knowledge base reference
    knowledge_base: Optional[TechnicalKnowledgeBase] = None
    
    # LLM instance for tool calling
    llm: Optional[Any] = None
    
    # Max iterations to prevent infinite loops
    max_iterations: int = 8
    current_iteration: int = 0
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(
        self,
        knowledge_base: TechnicalKnowledgeBase,
        llm: Optional[UnifiedLLM] = None,
        **kwargs
    ):
        # Create LLM first
        _llm = llm or UnifiedLLM()

        # Create RAG tools with knowledge base injected
        rag_tools = create_rag_tools(knowledge_base, llm=_llm)
        tool_collection = ToolCollection(*rag_tools, Terminate())
        
        super().__init__(
            system_prompt=AGENTIC_RAG_SYSTEM_PROMPT,
            available_tools=tool_collection,
            llm=_llm,
            knowledge_base=knowledge_base,
            **kwargs
        )
    
    async def query(self, question: str, context: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
        """
        Answer a question using agentic retrieval.
        
        Args:
            question: The technician's question
            context: Optional additional context
            verbose: Print detailed trace of each iteration
            
        Returns:
            Dict with answer, sources, confidence, and retrieval trace
        """
        import json as _json
        
        # Reset state for new query
        self.state = AgentState.RUNNING
        self.current_iteration = 0
        self.memory.clear()
        
        # Add the question to memory
        user_message = question
        if context:
            user_message = f"{question}\n\nContext: {context}"
        
        self.update_memory("user", user_message)
        
        # Run the agent loop
        trace = []
        while self.state == AgentState.RUNNING and self.current_iteration < self.max_iterations:
            self.current_iteration += 1
            
            if verbose:
                print(f"\n      ╭── Iteration {self.current_iteration} ──────────────────────────")
            
            # Think: decide what tool to use
            should_act = await self.think()
            
            if should_act:
                # Capture tool calls BEFORE act() clears them
                planned_calls = []
                for tc in self.tool_calls:
                    try:
                        args = _json.loads(tc.function.arguments)
                    except:
                        args = tc.function.arguments
                    planned_calls.append({
                        "tool": tc.function.name,
                        "args": args
                    })
                    
                    if verbose:
                        print(f"      │ 🧠 THINK → call {tc.function.name}")
                        # Pretty print args
                        if isinstance(args, dict):
                            for k, v in args.items():
                                val = str(v)[:80]
                                print(f"      │    {k}: {val}")
                        else:
                            print(f"      │    args: {str(args)[:100]}")
                
                # Act: execute the tool
                result = await self.act()
                
                if verbose:
                    # Show result preview for each tool
                    result_lines = result.split("\n")
                    for line in result_lines:
                        if ":" in line:
                            tool_name = line.split(":")[0].strip()
                            tool_output = ":".join(line.split(":")[1:]).strip()
                            # Parse output to show key info
                            try:
                                parsed = _json.loads(tool_output)
                                if isinstance(parsed, dict):
                                    if "found" in parsed:
                                        print(f"      │ ⚡ ACT  ← {tool_name}: found {parsed['found']} results")
                                    elif "recommendation" in parsed:
                                        print(f"      │ ⚡ ACT  ← {tool_name}: {parsed['recommendation']} (confidence: {parsed.get('confidence', '?')})")
                                    elif "answer" in parsed:
                                        answer_preview = parsed["answer"][:80]
                                        print(f"      │ ⚡ ACT  ← {tool_name}: \"{answer_preview}...\"")
                                    elif "Terminating" in str(parsed):
                                        print(f"      │ ⚡ ACT  ← {tool_name}: done")
                                    else:
                                        print(f"      │ ⚡ ACT  ← {tool_name}: {str(parsed)[:100]}")
                                else:
                                    print(f"      │ ⚡ ACT  ← {tool_name}: {str(tool_output)[:100]}")
                            except:
                                print(f"      │ ⚡ ACT  ← {tool_name}: {str(tool_output)[:100]}")
                
                trace.append({
                    "iteration": self.current_iteration,
                    "tools_called": planned_calls,
                    "result_preview": result[:300] if result else ""
                })
                
                if verbose:
                    print(f"      ╰─────────────────────────────────────────")
                
                # Check if we got a provide_answer call
                if "provide_answer" in result or "terminate" in result.lower():
                    break
            else:
                # No tool call - agent gave a direct response
                if verbose:
                    # Show what the agent said instead
                    last_msg = self.memory.messages[-1] if self.memory.messages else None
                    if last_msg and last_msg.content:
                        print(f"      │ 💬 DIRECT: {last_msg.content[:120]}...")
                    print(f"      ╰─────────────────────────────────────────")
                
                trace.append({
                    "iteration": self.current_iteration,
                    "tools_called": [],
                    "direct_response": True
                })
                break
        
        # Extract the final answer from memory
        final_answer = self._extract_final_answer()
        
        return {
            "question": question,
            "answer": final_answer.get("answer", "Unable to generate answer"),
            "sources": final_answer.get("sources", []),
            "confidence": final_answer.get("confidence", "unknown"),
            "iterations": self.current_iteration,
            "trace": trace,
            "is_agentic": True
        }
    
    def _extract_final_answer(self) -> Dict[str, Any]:
        """Extract the final answer from agent memory"""
        # Look for provide_answer tool result in memory
        for msg in reversed(self.memory.messages):
            if msg.role == "tool" and msg.content:
                try:
                    import json
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and "answer" in data:
                        return data
                except:
                    pass
            elif msg.role == "assistant" and msg.content:
                # Direct text response
                return {
                    "answer": msg.content,
                    "sources": [],
                    "confidence": "medium"
                }
        
        return {"answer": "No answer generated", "sources": [], "confidence": "none"}


async def agentic_query(
    question: str,
    knowledge_base: TechnicalKnowledgeBase,
    llm: Optional[UnifiedLLM] = None
) -> Dict[str, Any]:
    """
    Convenience function for single agentic queries.
    
    Args:
        question: The question to answer
        knowledge_base: The knowledge base to search
        llm: Optional LLM instance
        
    Returns:
        Answer dict with sources and confidence
    """
    agent = AgenticRAG(knowledge_base=knowledge_base, llm=llm)
    return await agent.query(question)
