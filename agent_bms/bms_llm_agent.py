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
from datetime import datetime

# Ensure project root is in path
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

from dotenv import load_dotenv
load_dotenv()

from agent_bms.prompt_builder import BMSContext, OpsPromptBuilder
from agent_advisory.economy import ToolEconomyPolicy

logger = logging.getLogger("arvis.bms.llm")


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

# Configuration
# Default to K2-Think for reasoning (English)
DEFAULT_ENGLISH_MODEL = "MBZUAI-IFM/K2-Think" 
# Default to Jais-V2 for Arabic (via OpenRouter or supported provider)
DEFAULT_ARABIC_MODEL = os.getenv("ARABIC_MODEL", "core42/jais-30b-chat-v3") 

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
        
        # Phase 2: Multi-Option Advisory System (Production Production)
        from agent_advisory import MultiOptionAdvisor
        
        # Initialize the full Advisor
        self.advisor = MultiOptionAdvisor()
        
        # We also keep Phase 1 components for backward compatibility/direct access
        self.tracker = self.advisor.tracker
        self.calibrator = self.advisor.calibrator
        self.preference_learner = self.advisor.preference_learner
        
        logger.info("Phase 2 Multi-Option Advisor initialized")
        
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
        
        # Phase 3: Proactive Layers (Goal Generator & Briefing Scheduler)
        from agent_advisory.goal_generator import GoalGenerator
        from agent_advisory.briefing_scheduler import BriefingScheduler
        from agent_advisory.feedback_loop import ActiveLearner
        from agent_advisory.world_model import WorldModel, StateTransitionModel
        from agent_advisory.explainer import ExplanationEngine
        from agent_advisory.online_learner import OnlineLearner
        from agent_advisory.trust_calibrator import TrustCalibrator
        from agent_advisory.knowledge_base import TechnicalKnowledgeBase, GraphRAGNavigator
        
        # Phase 5, 6, 7 & 8: Adaptive & Grounded Intelligence
        self.transition_model = StateTransitionModel()
        self.world_model = WorldModel(self.transition_model)
        self.explainer = ExplanationEngine(self.world_model)
        self.online_learner = OnlineLearner(self.world_model)
        self.knowledge_base = TechnicalKnowledgeBase()
        
        # Phase 8: Graph-RAG initialization
        from agent_cognitive.context_graph import ContextGraph
        self.context_graph = ContextGraph()
        self.graph_rag = GraphRAGNavigator(self.knowledge_base, self.context_graph)
        
        # Initialize Advisor with tracker
        from agent_advisory import MultiOptionAdvisor
        self.advisor = MultiOptionAdvisor()
        self.trust_calibrator = TrustCalibrator(self.advisor.tracker)
        
        # Initialize Goal Generator with World Model for simulation validation
        self.goal_generator = GoalGenerator(
            fleet_intelligence=None,
            predictive_engine=predictive_engine,
            energy_analyzer=energy_analyzer,
            world_model=self.world_model
        )
        
        # Initialize Briefing Scheduler
        self.briefing_scheduler = BriefingScheduler(self.goal_generator)
        # Start the scheduler
        self.briefing_scheduler.start()
        # Active Agency: Start dreaming about the building immediately
        building_id = getattr(self.bms_state, 'building_id', 'West Bay Tower')
        self.briefing_scheduler.add_building(building_id)
        
        # Initialize Feedback Loop (Active Learner)
        self.feedback_loop = ActiveLearner(self.tracker)
        
        logger.info("Phase 3 Proactive Layers initialized (GoalGenerator, BriefingScheduler, FeedbackLoop)")
        
        # Create tool handler - pass advisory components
        self.tool_handler = BMSToolHandler(
            bms_state=bms_state,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer,
            predictive_engine=predictive_engine,
            # Phase 1: Pass advisory components to tool handler
            recommendation_tracker=self.tracker,
            preference_learner=self.preference_learner,
            # Phase 2: Full Advisor
            advisor=self.advisor,
            # Phase 3 components
            goal_generator=self.goal_generator,
            briefing_scheduler=self.briefing_scheduler,
            feedback_loop=self.feedback_loop,
            # Phase 5: Explainer & World Model
            explainer=self.explainer,
            world_model=self.world_model,
            # Phase 6: Trust & Online Learning
            online_learner=self.online_learner,
            trust_calibrator=self.trust_calibrator,
            # Phase 7 & 8: Grounding & Graph-RAG
            knowledge_base=self.knowledge_base,
            graph_rag=self.graph_rag
        )
        
        # Initialize UnifiedLLM
        self.llm = UnifiedLLM()
        self.provider = "unified"
        # self.client removed in favor of UnifiedLLM
        
        logger.info(f"BMSLLMAgent initialized with UnifiedLLM")
        logger.info(f"Prompt layers available: {len(self.prompt_builder.LAYERS)}")
        
        # Phase 1: Start advisory scheduler for daily metrics
        from agent_bms.advisory_scheduler import start_advisory_scheduler
        self.advisory_scheduler = start_advisory_scheduler(
            tracker=self.tracker,
            calibrator=self.calibrator,
            preference_learner=self.preference_learner
        )
        self.economy_policy = ToolEconomyPolicy()
        logger.info("Advisory scheduler and ToolEconomyPolicy initialized")
    
    # _init_llm_client removed
        
        # Try providers in order of preference
        providers = [
            ("k2think", "K2THINK_API_KEY"),  # Priority for Ops Copilot
            ("groq", "GROQ_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("gemini", "GOOGLE_API_KEY"),
        ]
        
        for provider_name, env_key in providers:
            api_key = os.getenv(env_key)
            if api_key:
                try:
                    if provider_name == "k2think":
                        from openai import OpenAI
                        self.client = OpenAI(
                            api_key=api_key,
                            base_url="https://api.k2think.ai/v2"
                        )
                        self.provider = "k2think"
                        self.model = os.getenv("K2THINK_MODEL", DEFAULT_ENGLISH_MODEL)
                        logger.info(f"Using K2-Think with model: {self.model}")
                        return

                    elif provider_name == "groq":
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
    
    async def _get_dynamic_context(self, query: str, language: str) -> BMSContext:
        """Populate BMSContext with real-time advisor history and site status."""
        is_arabic = (language == "ar")
        query_type = "general"
        if any(w in query.lower() for w in ["alarm", "fault", "failure"]): query_type = "alarm"
        elif any(w in query.lower() for w in ["energy", "kwh", "cost"]): query_type = "energy"
        elif "gsas" in query.lower(): query_type = "gsas"
        
        # Pull history from tracker (Titan Memory)
        recent_recs = self.tracker.get_recent_recommendations(window_days=7)
        history_summary = "No recent trends analyzed."
        last_action = "No recent actions recorded."
        
        if recent_recs:
            last_action = recent_recs[0].recommended_action.get("action", "unknown")
            # Create a compact summary for the prompt
            summary_parts = []
            for r in recent_recs[:3]:
                ts = datetime.fromtimestamp(r.timestamp).strftime("%m/%d %H:%M")
                summary_parts.append(f"[{ts}] {r.recommended_action.get('action')}: {r.reasoning}")
            history_summary = " | ".join(summary_parts)

        # Get calibration & preferences from ACE
        calibration = {}
        if hasattr(self, 'trust_calibrator') and self.trust_calibrator:
            try:
                metrics = self.trust_calibrator.calculate_trust_metrics(window_days=7)
                calibration['trust_calibration'] = {
                    'description': f"Adoption Rate: {metrics.get('adoption_rate', 0):.1%}, Trust Score: {metrics.get('overall_trust_score', 0):.2f}",
                    'weight_adjustment': metrics.get('overall_trust_score', 0)
                }
            except Exception as te:
                logger.warning(f"Failed to pull trust metrics: {te}")
                
        if hasattr(self, 'preference_learner') and self.preference_learner:
            try:
                prefs = self.preference_learner.get_operator_preferences_summary("default")
                for i, pref in enumerate(prefs.get('top_preferences', [])[:2]):
                    calibration[f"operator_pref_{i}"] = {
                        'description': f"Preference: {pref.get('preference', 'N/A')}",
                        'weight_adjustment': 1.0
                    }
            except Exception as pe:
                logger.warning(f"Failed to pull operator preferences: {pe}")
        
        return BMSContext(
            building_id=getattr(self.bms_state, 'building_id', 'West Bay Tower'),
            is_critical=any(w in query.lower() for w in ["critical", "emergency", "icu", "patient"]),
            is_arabic=is_arabic,
            query_type=query_type,
            history_summary=history_summary,
            last_action_taken=last_action,
            active_calibration=calibration
        )

    async def _get_system_prompt(self, query: str, language: str) -> str:
        """Get context-aware dynamic system prompt."""
        ctx = await self._get_dynamic_context(query, language)
        return self.prompt_builder.build_full_prompt(ctx)
    
    def _verify_tool_adequacy(self, query: str, planned_tools: List[Dict[str, Any]], context: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        External Verification Layer: Smart Economy Enforcement.
        Uses learned utility to decide whether to intervene in the agent's plan.
        """
        query_lower = query.lower()
        existing_tool_names = {t['tool'] for t in planned_tools}
        forced_tools = []

        # Use the Smart Policy to get the 'forced' set
        if hasattr(self, 'economy_policy'):
            # Detect urgency from context or query
            urgency = "normal"
            if context and context.get("is_critical"):
                urgency = "critical"
            elif any(w in query_lower for w in ["urgent", "emergency", "fire", "danger", "immediately"]):
                urgency = "high"
                
            minimal_set = self.economy_policy.get_minimal_sufficient_set(query, context, urgency=urgency)
            
            # We ONLY force if the category is ENTIRELY missing
            # E.g. if we need GSAS, we only force GSAS status if NEITHER gsas tool was planned.
            for tool_name in minimal_set:
                if tool_name not in existing_tool_names:
                    # We check if a 'sibling' tool exists to avoid redundancy
                    if tool_name == "get_gsas_status" and "get_gsas_improvement_priorities" in existing_tool_names: continue
                    if tool_name == "analyze_energy" and "get_energy_anomalies" in existing_tool_names: continue
                    
                    forced_tools.append({"tool": tool_name, "args": {}})

        # Deduplication logic
        unique_forced = []
        for t in forced_tools:
            if t['tool'] not in existing_tool_names:
                unique_forced.append(t)
                existing_tool_names.add(t['tool'])

        if unique_forced:
            logger.warning(f"[VerificationLayer] ENFORCING TOOLS: {[t['tool'] for t in unique_forced]}")
            planned_tools.extend(unique_forced)
            
        return planned_tools

    async def chat(self, query: str, context: Dict[str, Any] = None) -> ChatResponse:
        """
        Process a natural language query about BMS.
        """
        language = self._detect_language(query)
        system_prompt = await self._get_system_prompt(query, language)
        
        if context:
            system_prompt += f"\n\nCurrent Context:\n{json.dumps(context)}"
        
        try:
            # 1. Normal Path (Intelligence)
            tool_calls = await self._generate_tool_calls(query, language)
            
            # --- VERIFICATION LAYER (EXTERNAL ENFORCEMENT) ---
            # "Trust but Verify" - Programmatically enforce tool checks for specific claims
            tool_calls = self._verify_tool_adequacy(query, tool_calls, context)
            # -------------------------------------------------
            
            tool_results = []
            for tc in tool_calls:
                result = await self.tool_handler.execute(tc["tool"], tc["args"])
                tool_results.append({"tool": tc["tool"], "result": result})
            
            # --- DATA DRIVEN ECONOMY: Record Utility ---
            if hasattr(self, 'economy_policy'):
                site_type = context.get('site_type') if context else "Standard"
                self.economy_policy.record_utility(query, site_type, tool_calls, [r['result'] for r in tool_results])

            if not tool_calls:
                text = await self._generate_text_response(query, language)
            else:
                text = await self._summarize_tool_results(query, tool_results, language)

            # 4. RECORD DECISION (Long Term Memory Update)
            try:
                self.tracker.log_recommendation(
                    context={"query": query, "tools": [tc['tool'] for tc in tool_calls]},
                    recommended_action={"action": text[:50] + "...", "raw_text": text},
                    confidence=0.9,
                    reasoning="Ops Copilot natural language interaction",
                    building_id=getattr(self.bms_state, 'building_id', 'West Bay Tower')
                )
            except Exception as le:
                logger.error(f"Failed to log decision to Skillbook: {le}")
            
            return ChatResponse(
                text=text,
                tool_calls=tool_calls,
                tool_results=tool_results,
                confidence=0.9,
                language=language,
                sources=["UnifiedLLM", "BMS Engines"],
            )
            
        except Exception as e:
            logger.error(f"LLM Path failed, triggering Edge Safeties: {e}")
            # 2. EMERGENCY PATH (Edge Safeties / Heuristics)
            return await self.run_edge_safeties(query, language)

    async def run_edge_safeties(self, query: str, language: str) -> ChatResponse:
        """
        Heuristic-only fallback for critical equipment protection.
        No LLM used. Zero narration. Safety only.
        """
        logger.warning("[BMSLLMAgent] RUNNING IN DEGRADED INTELLIGENCE MODE (EDGE SAFETIES)")
        
        # 1. Fetch current critical sensor state
        # (Assuming we have access to bms_state)
        vibration = 0.0
        try:
            chiller_state = await self.tool_handler.execute("get_equipment_status", {"equipment_id": "CHILLER-01"})
            vibration_str = str(chiller_state).split("Vibration: ")[1].split(" ")[0] if "Vibration" in str(chiller_state) else "0.0"
            vibration = float(vibration_str)
        except:
            pass
            
        # 2. Check Trends (Historical Evidence)
        tes_score = 0.0
        try:
            from agent_cognitive.meta_cognition import MetaCognition
            from agent.memory.orchestrator import MemoryOrchestrator
            
            # Using same persist dir as orchestrator
            memory = MemoryOrchestrator()
            brain = MetaCognition("degraded_mode") # Use generic or passed ID
            all_obs = memory.recall("vibration", memory_type="observation", limit=20)
            tes_score = brain.get_trend_evidence_score(all_obs, "vibration", r"Vibration: ([\d.]+)")
        except:
            pass

        # 3. Decision Matrix (BMS Constitution - Hardcoded)
        action_text = "Standard operation."
        tool_calls = []
        confidence = 0.5
        
        # Rule: Vibration Spike OR Rising Trend + High Value
        if vibration > 4.0:
            action_text = "🚨 DEGRADED MODE ALERT: CRITICAL VIBRATION DETECTED. RECOMMENDING EMERGENCY SHUTDOWN."
            tool_calls = [{"tool": "emergency_shutdown", "args": {"equipment_id": "CHILLER-01", "reason": "Edge Safety Threshold Exceeded"}}]
            confidence = 1.0
        elif vibration > 2.5 and tes_score > 0.3:
            action_text = "🚨 DEGRADED MODE ALERT: SUSTAINED VIBRATION DRIFT DETECTED. RECOMMENDING IMMEDIATE INSPECTION."
            tool_calls = [{"tool": "schedule_maintenance", "args": {"equipment_id": "CHILLER-01", "priority": "CRITICAL"}}]
            confidence = 0.85
            
        return ChatResponse(
            text=action_text + " (Note: LLM Reasoning Unavailable - Fixed Safety Fallback Active)",
            tool_calls=tool_calls,
            tool_results=[],
            confidence=confidence,
            language=language,
            sources=["Edge Safeties Heuristics"],
        )

    async def _generate_tool_calls(self, query: str, language: str) -> List[Dict[str, Any]]:
        """
        Generates tool calls using the specialized Tool Agent (Groq).
        """
        system_prompt = await self._get_system_prompt(query, language)
        messages = [{"role": "user", "content": query}]
        system_msgs = [{"content": system_prompt}]
        
        # Tools definitions
        tools_def = [
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
        
        response = await self.llm.ask_tool(
            messages=messages,
            system_msgs=system_msgs,
            tools=tools_def,
            tool_choice="auto"
        )
        
        if response.tool_calls:
            return [
                {
                    "tool": tc.function.name,
                    "args": json.loads(tc.function.arguments)
                } 
                for tc in response.tool_calls
            ]
        return []

    async def _generate_text_response(self, query: str, language: str) -> str:
        """
        Generates a direct text response using the Reasoning Agent.
        """
        system_prompt = await self._get_system_prompt(query, language)
        messages = [{"role": "user", "content": query}]
        system_msgs = [{"content": system_prompt}]
        
        response = await self.llm.ask(
            messages=messages,
            system_msgs=system_msgs
        )
        return response.content or ""

    async def _summarize_tool_results(self, query: str, tool_results: List[Dict], language: str) -> str:
        """
        Summarizes the tool execution results into a final answer.
        """
        # Brief result summary
        results_text = json.dumps(tool_results, indent=2)
        
        prompt = f"""
        User Query: {query}
        
        Tool Execution Results:
        {results_text}
        
        Based on these results, provide the final response in JSON format as per the Output Rules.
        """
        
        messages = [{"role": "user", "content": prompt}]
        system_msgs = [{"content": await self._get_system_prompt(query, language)}]
        
        response = await self.llm.ask(
            messages=messages,
            system_msgs=system_msgs
        )
        return response.content or ""

    def _fallback_response(self, query: str, language: str) -> ChatResponse:
        """Legacy fallback - now deprecated in favor of edge safeties"""
        return ChatResponse(
            text="Service Temporarily Unavailable",
            tool_calls=[],
            tool_results=[],
            confidence=0.0,
            language=language,
            sources=[]
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
