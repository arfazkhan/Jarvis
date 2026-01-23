"""
BMS LLM Agent
=============

LLM agent specifically configured for Ops Copilot mode.

This module wraps the main ARVIS LLMAgent and configures it with:
- BMS-specific tools (equipment status, alarms, energy, GSAS)
- Ops Copilot system prompt
- BMS tool executor integration

Usage:
    >>> agent = BMSLLMAgent(bms_state, alarm_engine, energy_analyzer, pm_engine)
    >>> response = await agent.chat("What's the status of chiller 1?")
    >>> print(response.text)
"""

import os
import sys
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Ensure project root is in path
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("arvis.bms.llm")


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ChatResponse:
    """Response from BMS LLM Agent"""
    text: str
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    confidence: float
    language: str  # "en" or "ar"
    sources: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "confidence": self.confidence,
            "language": self.language,
            "sources": self.sources,
        }


# ═══════════════════════════════════════════════════════════════════════════
# BMS LLM AGENT
# ═══════════════════════════════════════════════════════════════════════════

class BMSLLMAgent:
    """
    LLM Agent configured for BMS Ops Copilot mode.
    
    Provides natural language interface to BMS tools with:
    - Multi-provider support (Gemini, Groq, OpenAI, OpenRouter)
    - Automatic tool execution
    - Context-aware responses
    - Arabic language support
    """
    
    def __init__(
        self,
        bms_state=None,
        alarm_engine=None,
        energy_analyzer=None,
        predictive_engine=None,
        gsas_reporter=None,
    ):
        """
        Initialize the BMS LLM Agent.
        
        Args:
            bms_state: BMSStateEngine instance
            alarm_engine: AlarmEngine instance
            energy_analyzer: EnergyAnalyzer instance
            predictive_engine: PredictiveMaintenanceEngine instance
            gsas_reporter: GSASReporter instance
        """
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.pm_engine = predictive_engine
        self.gsas_reporter = gsas_reporter
        
        # Import tools
        from agent_bms.tools_schema import get_bms_tools, BMSToolHandler
        
        # Import layered prompt builder
        from agent_bms.prompt_builder import (
            get_ops_prompt_builder,
            get_ops_system_prompt,
            get_ops_critical_prompt,
            get_ops_energy_prompt,
            get_ops_maintenance_prompt,
        )
        
        self.tools = get_bms_tools()
        
        # Layered prompt builder for context-aware prompts
        self.prompt_builder = get_ops_prompt_builder()
        self.system_prompt_en = get_ops_system_prompt(compact=False, language="en")
        self.system_prompt_ar = get_ops_system_prompt(compact=True, language="ar")
        
        # Specialized prompts for different contexts
        self.critical_prompt = get_ops_critical_prompt()
        self.energy_prompt = get_ops_energy_prompt()
        self.maintenance_prompt = get_ops_maintenance_prompt()
        
        # Create tool handler
        self.tool_handler = BMSToolHandler(
            bms_state=bms_state,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer,
            predictive_engine=predictive_engine,
        )
        
        # Initialize LLM client based on available providers
        self.client = None
        self.provider = None
        self._init_llm_client()
        
        logger.info(f"BMSLLMAgent initialized with provider: {self.provider}")
        logger.info(f"Prompt layers available: {len(self.prompt_builder.LAYERS)}")
    
    def _init_llm_client(self):
        """Initialize the LLM client from available providers"""
        
        # Try providers in order of preference
        providers = [
            ("groq", "GROQ_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("gemini", "GOOGLE_API_KEY"),
        ]
        
        for provider_name, env_key in providers:
            api_key = os.getenv(env_key)
            if api_key:
                try:
                    if provider_name == "groq":
                        from openai import OpenAI
                        self.client = OpenAI(
                            api_key=api_key,
                            base_url="https://api.groq.com/openai/v1"
                        )
                        self.provider = "groq"
                        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
                        logger.info(f"Using Groq with model: {self.model}")
                        return
                        
                    elif provider_name == "openrouter":
                        from openai import OpenAI
                        self.client = OpenAI(
                            api_key=api_key,
                            base_url="https://openrouter.ai/api/v1"
                        )
                        self.provider = "openrouter"
                        self.model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
                        logger.info(f"Using OpenRouter with model: {self.model}")
                        return
                        
                    elif provider_name == "openai":
                        from openai import OpenAI
                        self.client = OpenAI(api_key=api_key)
                        self.provider = "openai"
                        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
                        logger.info(f"Using OpenAI with model: {self.model}")
                        return
                        
                    elif provider_name == "gemini":
                        import google.generativeai as genai
                        genai.configure(api_key=api_key)
                        self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
                        self.provider = "gemini"
                        logger.info("Using Google Gemini")
                        return
                        
                except Exception as e:
                    logger.warning(f"Failed to initialize {provider_name}: {e}")
                    continue
        
        logger.warning("No LLM provider configured. Chat will run in fallback mode.")
        self.provider = "fallback"
    
    def _detect_language(self, text: str) -> str:
        """Detect if text is Arabic or English"""
        # Simple heuristic: check for Arabic Unicode range
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        return "ar" if arabic_chars > len(text) * 0.3 else "en"
    
    def _get_system_prompt(self, language: str) -> str:
        """Get system prompt for the detected language"""
        return self.system_prompt_ar if language == "ar" else self.system_prompt_en
    
    async def chat(self, query: str, context: Dict[str, Any] = None) -> ChatResponse:
        """
        Process a natural language query about BMS.
        
        Args:
            query: User's question (English or Arabic)
            context: Optional additional context
            
        Returns:
            ChatResponse with text, tool results, etc.
        """
        # Detect language
        language = self._detect_language(query)
        system_prompt = self._get_system_prompt(language)
        
        # Add context to prompt if provided
        if context:
            context_str = json.dumps(context, indent=2)
            system_prompt += f"\n\nCurrent Context:\n{context_str}"
        
        # Generate response based on provider
        if self.provider == "fallback":
            return self._fallback_response(query, language)
        
        try:
            # Get tool calls from LLM
            tool_calls = await self._generate_tool_calls(system_prompt, query)
            
            # Execute tools
            tool_results = []
            for tc in tool_calls:
                result = await self.tool_handler.execute(tc["tool"], tc["args"])
                tool_results.append({
                    "tool": tc["tool"],
                    "result": result
                })
            
            # If no tools called, get direct response
            if not tool_calls:
                text = await self._generate_text_response(system_prompt, query)
            else:
                # Generate summary response from tool results
                text = await self._summarize_tool_results(query, tool_results, language)
                
                # Log successful query for learning (Titans Update loop)
                try:
                    from agent_bms.learning.learning_engine import get_learning_engine
                    learning = get_learning_engine()
                    learning.log_query_success(query, tool_calls)
                except Exception as le:
                    logger.debug(f"Learning engine log failed: {le}")
            
            return ChatResponse(
                text=text,
                tool_calls=tool_calls,
                tool_results=tool_results,
                confidence=0.9,
                language=language,
                sources=["BMS State Engine", "Ops Copilot"],
            )
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return ChatResponse(
                text=f"I encountered an error processing your request: {str(e)}",
                tool_calls=[],
                tool_results=[],
                confidence=0.0,
                language=language,
                sources=[],
            )
    
    async def _generate_tool_calls(self, system_prompt: str, query: str) -> List[Dict]:
        """Generate tool calls using the LLM"""
        
        if self.provider == "gemini":
            return await self._generate_gemini_tool_calls(system_prompt, query)
        
        elif self.client:
            return await self._generate_openai_tool_calls(system_prompt, query)
        
        return []
    
    async def _generate_openai_tool_calls(self, system_prompt: str, query: str) -> List[Dict]:
        """Generate tool calls using OpenAI-compatible API"""
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ]
            
            # Convert tools to OpenAI format
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"]
                    }
                }
                for tool in self.tools
            ]
            
            # Run in thread pool to make it async
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto"
                )
            )
            
            if not response.choices:
                return []
            
            message = response.choices[0].message
            
            if message.tool_calls:
                return [
                    {
                        "tool": tc.function.name,
                        "args": json.loads(tc.function.arguments)
                    }
                    for tc in message.tool_calls
                ]
            
            return []
            
        except Exception as e:
            logger.error(f"OpenAI tool generation failed: {e}")
            return []
    
    async def _generate_gemini_tool_calls(self, system_prompt: str, query: str) -> List[Dict]:
        """Generate tool calls using Gemini"""
        try:
            from google.generativeai import protos
            
            # Convert tools to Gemini format
            gemini_tools = []
            for tool in self.tools:
                params = tool["parameters"]
                properties = {}
                
                for prop_name, prop_def in params.get("properties", {}).items():
                    prop_type = prop_def.get("type", "string").upper()
                    properties[prop_name] = protos.Schema(
                        type=getattr(protos.Type, prop_type, protos.Type.STRING),
                        description=prop_def.get("description", "")
                    )
                
                gemini_tools.append(protos.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=protos.Schema(
                        type=protos.Type.OBJECT,
                        properties=properties,
                        required=params.get("required", [])
                    )
                ))
            
            chat = self.gemini_model.start_chat(history=[
                {"role": "user", "parts": [system_prompt]}
            ])
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: chat.send_message(query)
            )
            
            tool_calls = []
            for part in response.parts:
                if fn := part.function_call:
                    args = {key: value for key, value in fn.args.items()}
                    tool_calls.append({"tool": fn.name, "args": args})
            
            return tool_calls
            
        except Exception as e:
            logger.error(f"Gemini tool generation failed: {e}")
            return []
    
    async def _generate_text_response(self, system_prompt: str, query: str) -> str:
        """Generate a text-only response (no tools)"""
        
        if self.provider == "gemini":
            try:
                chat = self.gemini_model.start_chat(history=[
                    {"role": "user", "parts": [system_prompt]}
                ])
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: chat.send_message(query)
                )
                return response.text
            except Exception as e:
                logger.error(f"Gemini text generation failed: {e}")
                return "I couldn't generate a response."
        
        elif self.client:
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ]
                
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                    )
                )
                
                if response.choices:
                    return response.choices[0].message.content
                return "I couldn't generate a response."
                
            except Exception as e:
                logger.error(f"Text generation failed: {e}")
                return "I couldn't generate a response."
        
        return "No LLM provider configured."
    
    async def _summarize_tool_results(
        self, 
        query: str, 
        tool_results: List[Dict], 
        language: str
    ) -> str:
        """Generate a natural language summary of tool results"""
        
        # Build context from tool results
        results_str = json.dumps(tool_results, indent=2, default=str)
        
        summary_prompt = f"""Based on the following tool execution results, provide a concise, 
helpful response to the user's question. Use the data provided to give specific information.

User Question: {query}

Tool Results:
{results_str}

Respond in {'Arabic' if language == 'ar' else 'English'}. Be concise but informative.
If there are any issues or alarms, highlight them clearly."""
        
        return await self._generate_text_response(
            "You are a helpful BMS analyst. Summarize tool results for facility managers.",
            summary_prompt
        )
    
    def _fallback_response(self, query: str, language: str) -> ChatResponse:
        """Fallback response when no LLM is available"""
        
        # Try to match query to a tool
        query_lower = query.lower()
        
        if any(word in query_lower for word in ["alarm", "alert", "إنذار"]):
            return ChatResponse(
                text="To view alarms, I'll need to check the alarm engine. Please ensure an LLM provider is configured for full functionality.",
                tool_calls=[{"tool": "get_active_alarms", "args": {}}],
                tool_results=[],
                confidence=0.5,
                language=language,
                sources=["Fallback Mode"],
            )
        
        elif any(word in query_lower for word in ["chiller", "ahu", "equipment", "معدات"]):
            return ChatResponse(
                text="To check equipment status, I'll search the BMS state. Configure an LLM provider for natural language responses.",
                tool_calls=[{"tool": "list_equipment", "args": {}}],
                tool_results=[],
                confidence=0.5,
                language=language,
                sources=["Fallback Mode"],
            )
        
        elif any(word in query_lower for word in ["gsas", "compliance", "report"]):
            return ChatResponse(
                text="For GSAS compliance information, I can generate a report. Configure an LLM provider for detailed analysis.",
                tool_calls=[{"tool": "get_gsas_status", "args": {}}],
                tool_results=[],
                confidence=0.5,
                language=language,
                sources=["Fallback Mode"],
            )
        
        return ChatResponse(
            text="I'm running in fallback mode without an LLM provider. Please configure GROQ_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY for full functionality.",
            tool_calls=[],
            tool_results=[],
            confidence=0.0,
            language=language,
            sources=["Fallback Mode"],
        )


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

def create_bms_agent(
    bms_state=None,
    alarm_engine=None,
    energy_analyzer=None,
    predictive_engine=None,
) -> BMSLLMAgent:
    """Create a BMS LLM Agent with the given engines"""
    return BMSLLMAgent(
        bms_state=bms_state,
        alarm_engine=alarm_engine,
        energy_analyzer=energy_analyzer,
        predictive_engine=predictive_engine,
    )


# ═══════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import asyncio
    
    async def test():
        agent = BMSLLMAgent()
        
        test_queries = [
            "What's the status of the chillers?",
            "Show me active alarms",
            "How is energy consumption today?",
            "ما هي حالة المبنى؟",  # Arabic: What's the building status?
        ]
        
        for query in test_queries:
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print(f"{'='*60}")
            
            response = await agent.chat(query)
            print(f"Language: {response.language}")
            print(f"Response: {response.text}")
            print(f"Tools called: {[tc['tool'] for tc in response.tool_calls]}")
    
    asyncio.run(test())
