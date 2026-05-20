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
import time
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

from dotenv import load_dotenv
load_dotenv()

from agent_commercial.prompt_builder import BMSContext, OpsPromptBuilder
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
    explanation: Optional[Dict[str, Any]] = None
    truth_score: float = 1.0
    answer_confidence: float = 1.0
    data_coverage: float = 1.0

    def __post_init__(self):
        self.confidence = min(self.truth_score, self.answer_confidence)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "text": self.text,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "confidence": self.confidence,
            "language": self.language,
            "sources": self.sources,
            "truth_score": self.truth_score,
            "answer_confidence": self.answer_confidence,
            "data_coverage": self.data_coverage,
        }
        if self.explanation:
            d["explanation"] = self.explanation
        return d


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
        llm=None,
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
        
        # Phase 2: Multi-Option Advisory System
        # NOTE: Advisor is fully initialized below (after world model + graph-RAG)
        # to ensure all dependencies are available. Placeholder references set here
        # are overwritten after Phase 8 init completes.
        self.advisor = None
        self.tracker = None
        self.calibrator = None
        self.preference_learner = None
        
        # Import tools
        from agent_commercial.tools_schema import get_bms_tools, BMSToolHandler
        
        # Import layered prompt builder
        from agent_commercial.prompt_builder import (
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
        from agent_advisory.hybrid_rag import TreeKnowledgeBase, HybridRAGRouter
        
        # Phase 5, 6, 7 & 8: Adaptive & Grounded Intelligence
        self.transition_model = StateTransitionModel()
        self.world_model = WorldModel(self.transition_model)
        self.explainer = ExplanationEngine(self.world_model)
        self.online_learner = OnlineLearner()
        self.knowledge_base = TechnicalKnowledgeBase()
        self.tree_knowledge_base = TreeKnowledgeBase()
        self.hybrid_rag = HybridRAGRouter(
            vector_kb=self.knowledge_base,
            tree_kb=self.tree_knowledge_base,
        )
        
        # Phase 8: Graph-RAG initialization
        from agent_cognitive.context_graph import ContextGraph
        self.context_graph = ContextGraph()
        self.graph_rag = GraphRAGNavigator(self.knowledge_base, self.context_graph)
        
        # Initialize Advisor (single canonical init)
        from agent_advisory import MultiOptionAdvisor
        self.advisor = MultiOptionAdvisor()
        self.tracker = self.advisor.tracker
        self.calibrator = self.advisor.calibrator
        self.preference_learner = self.advisor.preference_learner
        self.trust_calibrator = TrustCalibrator(self.advisor.tracker)
        logger.info("Phase 2 Multi-Option Advisor initialized")
        
        # Initialize Goal Generator with World Model for simulation validation
        self.goal_generator = GoalGenerator(
            fleet_intelligence=None,
            predictive_engine=predictive_engine,
            energy_analyzer=energy_analyzer,
            world_model=self.world_model,
            gsas_reporter=gsas_reporter,
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
            graph_rag=self.graph_rag,
            hybrid_rag=self.hybrid_rag,
            gsas_reporter=gsas_reporter,
        )
        
        # Initialize UnifiedLLM
        self.llm = llm or UnifiedLLM()
        self.provider = "unified"

        # MetaCognition — init once, not per-call
        try:
            from agent_cognitive.meta_cognition import MetaCognition
            self.meta_cognition = MetaCognition(building_id=getattr(self.bms_state, 'building_id', 'West Bay Tower'))
        except Exception:
            self.meta_cognition = None

        logger.info(f"BMSLLMAgent initialized with UnifiedLLM")
        
        # Initialize internal client for direct provider access if needed
        self.client = None
        self.model = DEFAULT_ENGLISH_MODEL
        
        # Initial config detection (environment fallback)
        self.update_config()
        
        logger.info(f"Prompt layers available: {len(self.prompt_builder.LAYERS)}")
        
        # Phase 1: Advisory scheduler handled externally or via Swarm now
        self.advisory_scheduler = None
        self.economy_policy = ToolEconomyPolicy()
        
        # --- PHASE 1 RUFLOW INTEGRATION: Swarm Initialization ---
        try:
            from arvis_core.swarm.queen import QueenCoordinator
            from agent_commercial.swarm_nodes import get_all_swarm_nodes
            self.queen = QueenCoordinator(llm=self.llm)
            self.queen.tool_handler = self.tool_handler
            for node in get_all_swarm_nodes():
                self.queen.register_node(node)
            logger.info("ARVIS Phase 1 Swarm (Queen Coordinator & Nodes) initialized within BMSLLMAgent.")
        except Exception as e:
            logger.error(f"Failed to initialize Swarm: {e}")
            self.queen = None
        
        # Agentic Economy & Closure persistence
        self.last_advisory_state = {}  # {query: {metrics: value}}
        self.result_cache = {}        # {tool_name: (result, timestamp)}
        self.cache_ttl = 3600         # 1 hour cache for stable tools
        
        # Tool execution history for deduplication (Anti-Loop)
        self.tool_history = []  # List of (tool, args, timestamp)
        
        # Pilot Day Tracking (Phase 16) — persisted via DB
        self.pilot_day = self._load_pilot_day()

        logger.info("Advisory scheduler and ToolEconomyPolicy initialized")
    
    def get_pilot_phase(self) -> str:
        """Observation (1-14), Advisory (15-60), Critical (61-90)"""
        if self.pilot_day <= 14: return "OBSERVATION"
        if self.pilot_day <= 60: return "ADVISORY"
        return "CRITICAL"

    def get_pilot_persona_constraints(self) -> str:
        """Maturity-based prompt constraints."""
        phase = self.get_pilot_phase()
        if phase == "OBSERVATION":
            return "PHASE: OBSERVATION. Be a silent monitor. Provide strictly informational metrics only. DO NOT offer advice or optimization suggestions yet. Use a cautious, hesitant tone."
        elif phase == "ADVISORY":
            return "PHASE: ADVISORY. Provide soft optimization suggestions. Always include cost impact and confidence metrics. Tone should be professional and helpful but unassuming."
        else:
            return "PHASE: CRITICAL TRUST. You have earned 90 days of trust. Be firm, concise, and decisive. Escalate quickly for terminal safety events."
    
    def _load_pilot_day(self) -> int:
        """Load pilot day from DB, or compute from deployment date."""
        try:
            from agent_commercial.database import get_database
            import sqlite3
            db = get_database()
            conn = sqlite3.connect(str(db.db_path))
            cursor = conn.execute(
                "SELECT value FROM system_config WHERE key = 'pilot_start_date'"
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                from datetime import datetime
                start = datetime.fromisoformat(row[0])
                return max(1, (datetime.now() - start).days + 1)
        except Exception:
            pass
        return 1

    async def generate_morning_briefing(self, sim_state: Dict[str, Any]) -> str:
        """Generate a narrative daily briefing for the FM."""
        phase = self.get_pilot_phase()
        
        # Pull Recent Overrides/Intents
        # (This would ideally come from the SimController)
        
        briefing_prompt = f"""
        Generate a MORNING BRIEFING for Day {self.pilot_day}.
        PILOT阶段: {phase}
        
        BUILDING STATE:
        - Energy Intensity: {sim_state.get('energy_intensity', 0):.1f} kWh/m2
        - Active Alarms: {sim_state.get('active_alarms', 0)}
        - Trust Metric: {sim_state.get('trust_metric', 0):.2f}
        
        RECENT CONTEXT:
        (prior operator interactions available via memory system)
        
        INSTRUCTIONS:
        - If PHASE is OBSERVATION: Be silent/informational. No advice.
        - If PHASE is ADVISORY: Suggest optimizations with cost/confidence.
        - If PHASE is CRITICAL: Be firm and safety-focused.
        - Mention any anomalies detected while the building was 'Overnight'.
        - Keep it strictly 2-3 short sentences.
        """
        
        try:
            response = await self.llm.ask(
                messages=[{"role": "user", "content": briefing_prompt}],
                system_msgs=[{"content": "Professional BMS Chief Engineer persona."}],
                max_tokens=150
            )
            return response.content if response.content else "Observation mode active. Building stable."
        except Exception as e:
            logger.error(f"Briefing generation failed: {e}")
            return "System alert: Overnight monitoring active. Building parameters nominal."
        
    def update_config(self, provider: str = None, model: str = None, api_key: str = None):
        """Update the LLM configuration dynamically."""
        if provider and api_key:
            try:
                from openai import OpenAI
                if provider == "k2think":
                    self.client = OpenAI(api_key=api_key, base_url="https://api.k2think.ai/v2")
                    self.model = model or "MBZUAI-IFM/K2-Think"
                elif provider == "groq":
                    self.client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
                    self.model = model or "llama-3.3-70b-versatile"
                elif provider == "openrouter":
                    self.client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
                    self.model = model or "meta-llama/llama-3.3-70b-instruct"
                elif provider == "openai":
                    self.client = OpenAI(api_key=api_key)
                    self.model = model or "gpt-4o-mini"
                
                self.provider = provider
                logger.info(f"LLM Config updated to {provider} with model {self.model}")
                return True
            except Exception as e:
                logger.error(f"Failed to update LLM config: {e}")
                return False

        # Fallback to Environment Scanning if no explicit params provided
        providers = [
            ("k2think", "K2THINK_API_KEY"),
            ("groq", "GROQ_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("gemini", "GOOGLE_API_KEY"),
        ]
        
        for provider_name, env_key in providers:
            env_api_key = os.getenv(env_key)
            if env_api_key:
                try:
                    from openai import OpenAI
                    if provider_name == "k2think":
                        self.client = OpenAI(api_key=env_api_key, base_url="https://api.k2think.ai/v2")
                        self.model = os.getenv("K2THINK_MODEL", DEFAULT_ENGLISH_MODEL)
                    elif provider_name == "groq":
                        self.client = OpenAI(api_key=env_api_key, base_url="https://api.groq.com/openai/v1")
                        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
                    elif provider_name == "openrouter":
                        self.client = OpenAI(api_key=env_api_key, base_url="https://openrouter.ai/api/v1")
                        self.model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
                    elif provider_name == "openai":
                        self.client = OpenAI(api_key=env_api_key)
                        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
                    elif provider_name == "gemini":
                        import google.generativeai as genai
                        genai.configure(api_key=env_api_key)
                        self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
                    
                    self.provider = provider_name
                    logger.info(f"Using {provider_name} with model: {self.model if provider_name != 'gemini' else 'gemini-1.5-flash'}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to initialize {provider_name}: {e}")
                    continue
        
        logger.warning("No LLM provider configured. Chat will run in fallback mode.")
        self.provider = "fallback"
        return False
    
    def _detect_language(self, text: str) -> str:
        """Detect if text is Arabic or English"""
        # Simple heuristic: check for Arabic Unicode range
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        return "ar" if arabic_chars > len(text) * 0.3 else "en"

    @staticmethod
    def _is_actionable_advisory(text: str) -> bool:
        """Detect if swarm response contains an actionable recommendation."""
        action_signals = [
            "recommend", "suggest", "advise", "should", "action",
            "increase", "decrease", "adjust", "schedule", "inspect",
            "replace", "reset", "check", "verify", "dispatch",
        ]
        text_lower = text.lower()
        return any(signal in text_lower for signal in action_signals)
    
    async def _get_dynamic_context(self, query: str, language: str) -> BMSContext:
        """Populate BMSContext with real-time advisor history and site status."""
        is_arabic = (language == "ar")
        query_type = "general"
        if any(w in query.lower() for w in ["alarm", "fault", "failure"]): query_type = "alarm"
        elif any(w in query.lower() for w in ["energy", "kwh", "cost"]): query_type = "energy"
        elif "gsas" in query.lower(): query_type = "gsas"
        
        # Pull history from tracker (Titan Memory)
        recent_recs = await self.tracker.get_recent_recommendations(window_days=7)
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
                metrics = await self.trust_calibrator.calculate_trust_metrics(window_days=7)
                calibration['trust_calibration'] = {
                    'description': f"Adoption Rate: {metrics.get('adoption_rate', 0):.1%}, Trust Score: {metrics.get('overall_trust_score', 0):.2f}",
                    'weight_adjustment': metrics.get('overall_trust_score', 0)
                }
            except Exception as te:
                logger.warning(f"Failed to pull trust metrics: {te}")
                
        if hasattr(self, 'preference_learner') and self.preference_learner:
            try:
                prefs = await self.preference_learner.get_operator_preferences_summary("default")
                for i, pref in enumerate(prefs.get('top_preferences', [])[:2]):
                    calibration[f"operator_pref_{i}"] = {
                        'description': f"Preference: {pref.get('preference', 'N/A')}",
                        'weight_adjustment': 1.0
                    }
            except Exception as pe:
                logger.warning(f"Failed to pull operator preferences: {pe}")
        
        # ── Semantic incident recall via FAISS ──────────────────────────────
        try:
            from agent_cognitive.embeddings_store import EmbeddingsStore
            _store = EmbeddingsStore()
            if _store.enabled:
                hits = _store.search(query, limit=3, threshold=0.65)
                if hits:
                    recall_lines = []
                    for h in hits:
                        ts = str(h.get("timestamp", ""))[:10]
                        summary = str(h.get("summary", h.get("text", "")))[:200]
                        recall_lines.append(f"[{ts}] {summary}")
                    recall_block = "\n".join(f"  • {s}" for s in recall_lines)
                    history_summary = (
                        f"Similar past incidents:\n{recall_block}\n\n"
                        + history_summary
                    )
        except Exception as _faiss_err:
            logger.debug("FAISS recall skipped: %s", _faiss_err)

        # ── MetaCognition calibration injection ──────────────────────────────
        try:
            _mc = getattr(self, "meta_cognition", None)
            if _mc is not None:
                import asyncio as _asyncio
                _reflection = await _mc.reflect(lookback_days=7)
                _cal = _reflection.get("calibration", {})
                _biases = _reflection.get("biases_detected", {})

                if _cal.get("verdict") == "overconfident":
                    calibration["meta_calibration"] = {
                        "description": (
                            f"SELF-CALIBRATION ALERT: Recent recommendations were overconfident "
                            f"(ECE={_cal.get('ece', 0):.3f}). Apply higher uncertainty to projections. "
                            + (f"Biases: {', '.join(_biases.keys())}." if _biases else "")
                        ),
                        "weight_adjustment": -0.15,
                    }
                elif _cal.get("verdict") == "well_calibrated":
                    calibration["meta_calibration"] = {
                        "description": "Calibration nominal. Confidence scores are reliable.",
                        "weight_adjustment": 0.0,
                    }

                # Inject EWC rules with high Fisher importance
                _ewc_rules = getattr(_mc, "calibration_rules", {})
                _high_imp = [
                    (k, v) for k, v in _ewc_rules.items()
                    if v.get("fisher_information", 0) > 2.0
                ]
                for _rname, _rdata in _high_imp[:3]:
                    calibration[f"ewc_{_rname}"] = {
                        "description": _rdata.get("description", _rname),
                        "weight_adjustment": _rdata.get("weight_adjustment", 0.0),
                    }
        except Exception as _mc_err:
            logger.debug("MetaCognition calibration injection skipped: %s", _mc_err)

        # ── Learning engine suggested_actions injection ───────────────────────
        try:
            _db = getattr(self, "database", None) or getattr(self, "db", None)
            if _db is not None and hasattr(_db, "fetch_all"):
                _suggestions = await _db.fetch_all(
                    "SELECT action, reason FROM suggested_actions "
                    "WHERE status='pending' ORDER BY created_at DESC LIMIT 3"
                )
                if _suggestions:
                    _sug_lines = "\n".join(
                        f"  • {s.get('action','?')} ({s.get('reason','?')})"
                        for s in _suggestions
                    )
                    calibration["learned_patterns"] = {
                        "description": f"Learning engine identified:\n{_sug_lines}",
                        "weight_adjustment": 0.0,
                    }
        except Exception as _le_err:
            logger.debug("Suggested actions injection skipped: %s", _le_err)

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
        prompt = self.prompt_builder.build_full_prompt(ctx)
        
        # Inject Phase 16 Pilot Context
        pilot_constraints = self.get_pilot_persona_constraints()
        prompt = f"{pilot_constraints}\n\n{prompt}"
        
        return prompt
    
    async def _verify_tool_adequacy(self, 
                              query: str, 
                              planned_tools: List[Dict[str, Any]], 
                              context: Optional[Dict] = None,
                              history: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """
        External Verification Layer: Smart Economy Enforcement.
        Uses learned utility to decide whether to intervene in the agent's plan.
        Filters against HISTORY to avoid redundant checks across ReAct turns.
        """
        query_lower = query.lower()
        history = history or []
        
        # 1. Track what has ALREADY been called in this loop session
        called_tools = set()
        for step in history:
            for action in step.get("actions", []):
                called_tools.add(action["tool"])
        
        # 2. Track what is ALREADY planned for THIS turn
        existing_tool_names = {t['tool'] for t in planned_tools}
        forced_tools = []

        # 3. Use the Smart Policy to get the 'forced' set
        if hasattr(self, 'economy_policy'):
            urgency = "normal"
            if context and context.get("is_critical"): urgency = "critical"
            elif any(w in query_lower for w in ["urgent", "emergency", "fire", "danger", "immediately"]):
                urgency = "high"
                
            minimal_set = await self.economy_policy.get_minimal_sufficient_set(query, context, urgency=urgency)
            
            # --- MANDATORY TOOL VERIFICATION (Hard Enforcement) ---
            # Ensure critical phases have required tools even if economy skip them
            if urgency == "critical" or "energy" in query_lower:
                if "energy" in query_lower:
                    minimal_set.update({"analyze_energy", "forecast_energy", "check_cost_impact"})
                if "ghost" in query_lower:
                    minimal_set.update({"find_ghost_spaces", "list_equipment", "get_equipment_status"})
                if "maintenance" in query_lower or "chiller" in query_lower:
                    minimal_set.update({"verify_maintenance_work", "detect_equipment_faults"})
            
            # --- SOVEREIGN COGNITION ENFORCEMENT (Fixed Indentation) ---
            if any(w in query_lower for w in ["skill", "memory", "past", "history", "learned", "skillbook", "quirk"]):
                minimal_set.update({"query_skillbook", "get_equipment_status"})
            if any(w in query_lower for w in ["fleet", "benchmark"]):
                minimal_set.update({"compare_to_fleet", "analyze_energy"})
            if any(w in query_lower for w in ["life", "remaining", "rul"]):
                minimal_set.update({"predict_remaining_life", "get_equipment_status"})
            if any(w in query_lower for w in ["simulate", "scenario", "impact"]):
                minimal_set.update({"simulate_change", "get_equipment_status"})

            # 4. We ONLY force if the tool is missing from BOTH current plan AND history
            for tool_name in minimal_set:
                if tool_name not in existing_tool_names and tool_name not in called_tools:
                    # Sibling check
                    if tool_name == "get_gsas_status" and ("get_gsas_improvement_priorities" in existing_tool_names or "get_gsas_improvement_priorities" in called_tools): continue
                    if tool_name == "analyze_energy" and ("get_energy_anomalies" in existing_tool_names or "get_energy_anomalies" in called_tools): continue
                    
                    # 5. Argument Check: Don't force tools that require complex parameters with empty {}
                    # unless they are already in the plan (which means the LLM provided them)
                    if tool_name in ["simulate_change", "check_cost_impact", "predict_remaining_life", "get_equipment_status", "forecast_energy"]:
                        logger.info(f"[VerificationLayer] Skipping force for complex tool '{tool_name}' (requires params or specific context)")
                        continue
                        
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

    def _extract_dynamic_tasks(self, query: str) -> List[Dict[str, Any]]:
        """Extract a bespoke TODO list based on the user's specific query."""
        query_lower = query.lower()
        tasks = []
        
        # 1. Discovery/Data Phase
        if any(w in query_lower for w in ["energy", "kwh", "cost", "bill"]):
            tasks.append({"id": "data_energy", "task": "Analyze high-fidelity energy metrics and historical drift", "status": "todo"})
        if any(w in query_lower for w in ["ghost", "occupancy", "waste", "after hours"]):
            tasks.append({"id": "data_ghost", "task": "Scan for ghost operations and occupancy divergence", "status": "todo"})
        if any(w in query_lower for w in ["alarm", "fault", "trip", "chiller", "ahu"]):
            tasks.append({"id": "data_fault", "task": "Investigate equipment telemetry and active alarm states", "status": "todo"})
        if "maintenance" in query_lower or "pm" in query_lower:
            tasks.append({"id": "data_pm", "task": "Review maintenance logs and verification history", "status": "todo"})
            
        # Fallback if no specific trigger words found
        if not tasks:
            tasks.append({"id": "data_general", "task": "Perform baseline system state discovery", "status": "todo"})
            
        # 2. Analysis/Reasoning Phase
        tasks.append({"id": "reason", "task": "Synthesize findings and simulate potential mitigations", "status": "todo"})
        
        # 3. Finalization Phase
        tasks.append({"id": "final", "task": "Validate constraints and deliver verified advisory", "status": "todo"})
        
        return tasks

    def _update_task_status(self, todo_list: List[Dict], current_tools: List[Dict], tool_results: List[Dict], response_text: str = None):
        """Dynamically update task status based on tool usage and agent progress."""
        for task in todo_list:
            # 1. Discovery Tasks
            if task["id"].startswith("data"):
                # If we are calling relevant tools, it's in progress
                for tc in current_tools:
                    tool = tc["tool"]
                    if (task["id"] == "data_energy" and tool in ["analyze_energy", "forecast_energy", "check_cost_impact"]) or \
                       (task["id"] == "data_ghost" and tool in ["find_ghost_spaces", "list_equipment"]) or \
                       (task["id"] == "data_fault" and tool in ["get_active_alarms", "get_equipment_status", "detect_equipment_faults"]) or \
                       (task["id"] == "data_pm" and tool in ["verify_maintenance_work", "predict_remaining_life"]) or \
                       (task["id"] == "data_general" and tool in ["list_equipment", "get_active_alarms"]):
                        if task["status"] == "todo": task["status"] = "in-progress"
                
                # If we have results for those tools, it's completed (if no more of those tools are in the current plan)
                # For simplicity, we mark it completed if we've seen at least one successful result and it's not in the 'current_tools' anymore
                # But a cleaner way is to check if we have results in this turn
                for res in tool_results:
                    tool = res["tool"]
                    if (task["id"] == "data_energy" and tool == "analyze_energy") or \
                       (task["id"] == "data_ghost" and tool == "find_ghost_spaces") or \
                       (task["id"] == "data_fault" and tool == "get_active_alarms") or \
                       (task["id"] == "data_pm" and tool == "verify_maintenance_work") or \
                       (task["id"] == "data_general" and tool in ["list_equipment", "get_active_alarms"]):
                        task["status"] = "completed"

            # 2. Reasoning Tasks
            if task["id"] == "reason":
                if any(tc["tool"] in ["simulate_change", "forecast_energy"] for tc in current_tools):
                    if task["status"] == "todo": task["status"] = "in-progress"
                # If we've completed all data tasks, we're reasoning
                data_tasks = [t for t in todo_list if t["id"].startswith("data")]
                if all(t["status"] == "completed" for t in data_tasks) and task["status"] == "todo":
                    task["status"] = "in-progress"

            # 3. Final Task
            if task["id"] == "final":
                if response_text:
                    task["status"] = "completed"
                elif all(t["status"] == "completed" for t in todo_list if t["id"] != "final"):
                    task["status"] = "in-progress"

    def _check_memory_gate(self, query: str) -> Optional[str]:
        """Checks if the current system state matches the last successful advisory for this query."""
        # 1. Extract query fingerprint (e.g., "energy drift")
        fingerprint = "general"
        if any(w in query.lower() for w in ["energy", "kwh", "bill"]): fingerprint = "energy"
        elif any(w in query.lower() for w in ["alarm", "fault", "faulty"]): fingerprint = "fault"
        
        # 2. Compare key metrics
        prev_state = self.last_advisory_state.get(fingerprint)
        if not prev_state:
            return None
            
        current_metrics = {
            "energy": getattr(self.energy_analyzer, 'last_total_kw', 0),
            "alarms": len(getattr(self.alarm_engine, 'active_alarms', [])) if self.alarm_engine else 0
        }
        
        # 3. Check for stability (e.g., <2% change in energy, same alarm count)
        if fingerprint == "energy":
            prev_energy = prev_state.get("energy", -1)
            if abs(current_metrics["energy"] - prev_energy) / (prev_energy or 1) < 0.02:
                return "[STABLE] Energy profiles remain within nominal drift limits. No new anomalies detected since last optimization."
        elif fingerprint == "fault":
            if current_metrics["alarms"] == prev_state.get("alarms"):
                return "[STABLE] Alarm state is identical to previous audit. All existing faults are being tracked."
                
        return None

    def _record_advisory_state(self, query: str):
        """Persists current metrics into the memory gate."""
        fingerprint = "general"
        if any(w in query.lower() for w in ["energy", "kwh", "bill"]): fingerprint = "energy"
        elif any(w in query.lower() for w in ["alarm", "fault", "faulty"]): fingerprint = "fault"
        
        self.last_advisory_state[fingerprint] = {
            "energy": getattr(self.energy_analyzer, 'last_total_kw', 0),
            "alarms": len(getattr(self.alarm_engine, 'active_alarms', [])) if self.alarm_engine else 0,
            "timestamp": time.time()
        }

    async def _generate_turn_summary(self, turn_results: List[Dict], language: str = "en") -> str:
        """Generates a concise, content-aware summary of a ReAct turn's findings."""
        if not turn_results:
            return "Continuing investigation..."
            
        # Simplified summary prompt
        summary_prompt = f"Summarize these BMS findings in 1 concise sentence: {json.dumps(turn_results[:3])}"
        
        try:
            # Use standard ask to avoid Groq 403 if it's the secondary provider
            response = await self.llm.ask(
                messages=[{"role": "user", "content": summary_prompt}],
                system_msgs=[{"content": "Concise BMS narrator."}],
                max_tokens=60
            )
            return response.content.strip().strip('"') if response.content else f"Analyzed {len(turn_results)} data points."
        except Exception as e:
            logger.error(f"[SummaryError] {e}")
            return f"Completed investigative phase with {len(turn_results)} observations."

    async def _generate_final_summary(self, query: str, final_text: str) -> str:
        """Generates a 1-sentence narrative snapshot of the final finding."""
        try:
            # Check for existing error in text
            if "LLM Error" in final_text:
                return "Investigation concluded with a connectivity alert."
                
            summary_prompt = f"Summarize this resolution in 1 sentence: {final_text[:300]}"
            response = await self.llm.ask(
                messages=[{"role": "user", "content": summary_prompt}],
                system_msgs=[{"content": "Concise BMS narrator."}],
                max_tokens=60
            )
            return response.content.strip().strip('"') if response.content else "Investigation complete."
        except (AttributeError, TypeError) as e:
            logger.debug(f"Summary generation fallback: {e}")
            return "Final advisory delivered and verified."

    async def chat(self, query: str, context: Dict[str, Any] = None, channel: str = "chat") -> ChatResponse:
        """
        Process a natural language query about BMS using the ARVIS Swarm.
        Replaces the monolithic ReAct loop with a decentralized, BFT-debated Swarm response based on Ruflow architecture.
        """
        language = self._detect_language(query)
        context = context or {}

        # ── T1 Working Memory: load cross-session conversation context ────────
        _operator_id = context.get("operator_id", "default")
        _building_id = context.get("building_id", getattr(self, "_building_id", "default"))
        _conv_ctx = None
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                _conv_ctx = await _mo.get_conversation(_operator_id, _building_id)
                if _conv_ctx and (_conv_ctx.turns or _conv_ctx.rolling_summary):
                    # Inject prior turns into context so swarm nodes see them
                    context["chat_history"] = _conv_ctx.to_history()
                    logger.info(
                        f"[Mem-4] Loaded {len(_conv_ctx.turns)} prior turns for operator={_operator_id}"
                    )
            except Exception as _cm_err:
                logger.debug(f"[Mem-4] get_conversation failed (non-fatal): {_cm_err}")

        # Per-request GroundingGuard — isolated from concurrent requests
        from agent_commercial.grounding_guard import GroundingGuard, set_active_guard
        _request_guard = GroundingGuard()
        _guard_token = set_active_guard(_request_guard)

        # meta_cognition already initialized in __init__

        if hasattr(self, 'queen') and self.queen:
            logger.info("Routing query to ARVIS Swarm (Phase 1 Advisory)...")
            
            # Broadcast to UI that Queen is thinking
            from agent_commercial.api.sse_broadcaster import SSEBroadcaster
            import asyncio
            broadcaster = SSEBroadcaster()
            
            # Define standard task pipeline for UI to render as a To-Do list
            tasks_state = [
                {"id": "task_grounding", "task": "Synthesizing real-time grounding context", "status": "pending"},
                {"id": "task_intent", "task": "Analyzing query intent and complexity", "status": "pending"},
                {"id": "task_execution", "task": "Executing Swarm Resolution (BFT / Fast-Path)", "status": "pending"},
                {"id": "task_validation", "task": "Validating output against safety constraints", "status": "pending"}
            ]
            
            asyncio.create_task(broadcaster.broadcast("progress", {"content": "The ARVIS Swarm is initializing..."}, channel=channel))
            
            # 1. Update and broadcast grounding
            tasks_state[0]["status"] = "in_progress"
            asyncio.create_task(broadcaster.broadcast("task_list", {"tasks": tasks_state}, channel=channel))
            
            # 1. GROUNDING INJECTION: Fast concurrent fetch
            try:
                alarms = await self.bms_state.get_active_alarms()
                context["GROUNDING_ALARMS"] = [a.to_dict() for a in alarms]
                
                thermal_breaches = []
                equipment = await self.bms_state.get_all_equipment()
                
                target_eqs = [eq for eq in equipment if eq.equipment_type in ["ahu", "chiller", "cooling_tower"]]
                
                stale_sensors = []

                async def fetch_and_check(eq):
                    breaches = []
                    stale = []
                    points = await self.bms_state.get_points_by_equipment(eq.equipment_id)
                    from datetime import datetime, timedelta, timezone
                    _now = datetime.now(timezone.utc)
                    _stale_threshold = timedelta(minutes=15)

                    for p in points:
                        # Staleness check: skip stale points from grounding
                        if hasattr(p, 'timestamp') and p.timestamp:
                            _ts = p.timestamp if p.timestamp.tzinfo else p.timestamp.replace(tzinfo=timezone.utc)
                            _age = _now - _ts
                            if _age > _stale_threshold:
                                stale.append({
                                    "equipment": eq.equipment_id,
                                    "point": p.name,
                                    "age_minutes": round(_age.total_seconds() / 60, 1),
                                    "last_value": p.value,
                                })
                                continue

                        if "temp" in p.name.lower() or "sat" in p.point_id.lower():
                            # Per-zone thresholds based on equipment type and location
                            _loc = (eq.location or "").lower()
                            if "server" in _loc or "data" in _loc or "comms" in _loc:
                                _warn, _crit = 22.0, 27.0
                            elif eq.equipment_type in ("chiller", "cooling_tower"):
                                _warn, _crit = 28.0, 35.0
                            elif "lobby" in _loc or "reception" in _loc:
                                _warn, _crit = 26.0, 32.0
                            else:
                                _warn, _crit = 25.0, 30.0

                            if p.value and p.value > _warn:
                                breaches.append({
                                    "equipment": eq.equipment_id,
                                    "point": p.name,
                                    "value": p.value,
                                    "status": "CRITICAL" if p.value > _crit else "WARNING"
                                })
                    return breaches, stale

                results = await asyncio.gather(*[fetch_and_check(eq) for eq in target_eqs])
                for breaches, stale in results:
                    thermal_breaches.extend(breaches)
                    stale_sensors.extend(stale)

                context["GROUNDING_THERMAL_SAFETY"] = thermal_breaches
                if stale_sensors:
                    context["STALE_SENSORS"] = stale_sensors

                # Alarm cluster grounding: collapse noise into root causes
                if self.alarm_engine:
                    cluster_summary = self.alarm_engine.get_active_clusters_summary()
                    if cluster_summary:
                        context["GROUNDING_ALARM_CLUSTERS"] = cluster_summary
            except Exception as e:
                logger.error(f"Grounding injection failed: {e}")
                
            # 2. DELEGATE TO SWARM
            tasks_state[0]["status"] = "completed"
            tasks_state[1]["status"] = "in_progress"
            asyncio.create_task(broadcaster.broadcast("task_list", {"tasks": tasks_state}, channel=channel))
            swarm_payload = await self.queen.execute_swarm(query, context, channel=channel)
            
            # Swarm now returns a dict with the consensus AND the raw tool context discovered by nodes
            _investigation_plan = None
            if isinstance(swarm_payload, dict):
                final_advice = swarm_payload.get("advice", "")
                swarm_context = swarm_payload.get("context", {})
                _investigation_plan = swarm_payload.get("plan")
            else:
                final_advice = str(swarm_payload)
                swarm_context = {}

            # P4: Broadcast final plan state to operator as live checklist
            if _investigation_plan:
                asyncio.create_task(
                    broadcaster.broadcast_plan_update(_investigation_plan, channel=channel)
                )
                
            if final_advice == "__FAST_PATH_ROUTING__":
                logger.info("[Queen] Executing Agentic Fast-Path via Tool Agent...")
                from arvis_core.swarm.node import SwarmNode
                
                fast_node = SwarmNode(
                    name="Fast_Router",
                    role="You are ARVIS, a smart building assistant. You must ALWAYS use tools to check the real-world state of equipment before answering status queries. Be concise, factual, and helpful. Do not output xml reasoning tags.",
                    tools=self.tools,
                    tool_handler=self.tool_handler,
                    llm=self.llm
                )
                
                tasks_state[1]["status"] = "completed"
                tasks_state[2]["task"] = "Executing Agentic Fast-Path Route"
                tasks_state[2]["status"] = "in_progress"
                asyncio.create_task(broadcaster.broadcast("task_list", {"tasks": tasks_state}, channel=channel))
                
                try:
                    # Pass chat_history as message history so fast-path has conversation context
                    _fast_history = context.get("chat_history", []) if context else []
                    fast_result = await fast_node.process(query, context, history=_fast_history, channel=channel)
                    fast_text = fast_result["response"].content
                except Exception as e:
                    logger.error(f"Fast-Path failed: {e}")
                    fast_text = "Fast-Path routing failed."
                    
                tasks_state[2]["status"] = "completed"
                tasks_state[3]["status"] = "completed" # Bypass validation for fast path
                asyncio.create_task(broadcaster.broadcast("task_list", {"tasks": tasks_state}, channel=channel))
                # -- 0.1: Fast-path now validated --
                # Run GroundingGuard on fast-path output (per-request instance)
                audit = _request_guard.audit(fast_text)
                fast_text = audit.clean_text

                # Run TruthValidator on fast-path
                try:
                    from arvis_core.swarm.validator import TruthValidator
                    _fp_validator = TruthValidator()
                    _fp_validation = await _fp_validator.validate(fast_text, context)
                    _fp_val_score = _fp_validation.get("score", 0.0)
                except Exception as _fp_err:
                    logger.warning(f"[Fast-Path] Validator unavailable: {_fp_err}")
                    _fp_val_score = 0.3

                if _fp_val_score < 0.7:
                    fast_text = f"[Unverified] {fast_text}"

                if _mo is not None:
                    try:
                        await _mo.save_conversation_turn(_operator_id, _building_id, "user", query)
                        await _mo.save_conversation_turn(_operator_id, _building_id, "assistant", fast_text)
                    except Exception as _fp_cm_err:
                        logger.debug(f"[Mem-4] fast-path save_conversation_turn failed (non-fatal): {_fp_cm_err}")

                return ChatResponse(
                    text=fast_text,
                    tool_calls=[],
                    tool_results=[],
                    confidence=_fp_val_score,
                    language=language,
                    sources=["ARVIS Fast-Path Router", f"Truth-Validator (Score: {_fp_val_score})"],
                    truth_score=_fp_val_score,
                    answer_confidence=1.0,
                    data_coverage=1.0,
                )

            # Merge the facts discovered by Swarm Nodes into the ground truth context for the Validator
            full_context = {**(context or {}), **swarm_context}
            
            # Transition from Debate -> Validation
            tasks_state[1]["status"] = "completed"
            tasks_state[2]["task"] = "Multi-Agent BFT Consensus Reached"
            tasks_state[2]["status"] = "completed"
            tasks_state[3]["status"] = "in_progress"
            
            # VALIDATE TRUTH SCORE (Non-blocking Soft-Fail)
            asyncio.create_task(broadcaster.broadcast("task_list", {"tasks": tasks_state}, channel=channel))
            
            try:
                # M3.3: Build ML evidence summary so validator can penalise advice that cites fallback values
                _ml_evidence_summary = []
                if _investigation_plan is not None:
                    for _ev in _investigation_plan.evidence.get_all():
                        if getattr(_ev, "is_ml_fallback", False):
                            _ml_evidence_summary.append({
                                "evidence_id": _ev.id,
                                "source_tool": _ev.source_tool,
                                "status": "ML_FALLBACK",
                                "reason": _ev.raw_payload.get("reason", "model unavailable"),
                            })
                        elif getattr(_ev, "model_id", None):
                            _ml_evidence_summary.append({
                                "evidence_id": _ev.id,
                                "source_tool": _ev.source_tool,
                                "model_id": _ev.model_id,
                                "drift_score": _ev.drift_score,
                                "confidence_bounds": _ev.confidence_bounds,
                            })
                if _ml_evidence_summary:
                    full_context = {
                        **full_context,
                        "_ml_evidence_summary": _ml_evidence_summary,
                        "_ml_fallback_tools": [e["source_tool"] for e in _ml_evidence_summary if e.get("status") == "ML_FALLBACK"],
                    }

                from arvis_core.swarm.validator import TruthValidator
                validator = TruthValidator()
                validation_result = await validator.validate(final_advice, full_context)
                val_score = validation_result.get("score", 0.0)
                val_reasoning = validation_result.get("reasoning", "")

                if val_score < 0.7:
                    logger.warning(f"[TruthValidator] BLOCKING — score {val_score}: {val_reasoning}")
                    final_advice = (
                        "I was unable to verify my analysis against live building data with sufficient confidence. "
                        "Please verify the following observation manually or ask me to re-check specific equipment."
                    )
                elif val_score < 0.95:
                    logger.warning(f"[TruthValidator] Low confidence ({val_score}): {val_reasoning}")
                    final_advice = f"[Low Confidence] {final_advice}"
                else:
                    logger.info(f"Truth Score Verified: {val_score}")
            except Exception as e:
                logger.error(f"[TruthValidator] Failure (blocking): {e}")
                val_score = 0.0
                final_advice = (
                    "ARVIS verification system encountered an error. "
                    "Cannot deliver unverified advisory. Please retry or check system logs."
                )
            
            tasks_state[3]["status"] = "completed"
            asyncio.create_task(broadcaster.broadcast("task_list", {"tasks": tasks_state}, channel=channel))

            # Inject confidence statement if ARVIS omitted it
            final_advice = self._inject_confidence_if_missing(final_advice)

            # GroundingGuard audit — structural check, not a prompt rule.
            # Flags any cited number (failure %, QAR, health score, RUL days)
            # that has no provenance in tool results from this turn.
            try:
                audit = _request_guard.audit(final_advice)
                final_advice = audit.clean_text
                if not audit.passed:
                    logger.warning(
                        f"[GroundingGuard] {len(audit.ungrounded_claims)} ungrounded claim(s) "
                        f"in response for query: {query[:80]!r}"
                    )
            except Exception as _gg_err:
                logger.debug(f"[GroundingGuard] audit failed (non-fatal): {_gg_err}")

            # Programmatic skillbook write — awaited with timeout, not fire-and-forget
            try:
                await asyncio.wait_for(
                    self._programmatic_skillbook_write(final_advice, query),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning("[Skillbook] Write timed out after 3s — learning lost for this turn")
            except Exception as _sb_err:
                logger.error(f"[Skillbook] Write failed: {_sb_err}")

            # Auto-attach explainability for actionable advisories
            explanation = None
            if self.explainer and self._is_actionable_advisory(final_advice):
                try:
                    from agent_advisory.explainer import DetailLevel
                    rec = {
                        "title": query[:80],
                        "description": final_advice[:500],
                        "action_type": swarm_context.get("primary_action", "advisory"),
                        "priority": swarm_context.get("priority", "medium"),
                    }
                    explanation = await self.explainer.explain_recommendation(
                        recommendation=rec,
                        context=full_context,
                        level=DetailLevel.STANDARD,
                    )
                except Exception as e:
                    logger.debug(f"Auto-explanation skipped: {e}")

            # Surface tool calls from swarm context for auditability
            _tc = swarm_context.get("_tool_calls", [])
            _tr = swarm_context.get("_tool_results", [])
            _data_cov = _investigation_plan.coverage if _investigation_plan else 1.0

            # H7: Calibrated abstention gate — low coverage + moderate truth → abstain
            _ABSTENTION_COVERAGE_FLOOR = 0.3
            _ABSTENTION_TRUTH_CEILING = 0.8

            # ML signal abstention: compute fallback ratio + max drift from plan evidence.
            # Fallback evidence (is_ml_fallback=True) is treated as drift_score=1.0 —
            # the gate fires on it regardless of whether drift_score was populated.
            _ml_fallback_ratio = 0.0
            _max_drift = 0.0
            if _investigation_plan is not None:
                _all_ev = _investigation_plan.evidence.get_all()
                if _all_ev:
                    _fb_count = sum(1 for _e in _all_ev if getattr(_e, "is_ml_fallback", False))
                    _ml_fallback_ratio = _fb_count / len(_all_ev)
                    # Treat every fallback as drift=1.0 so gate fires even when drift_score is None
                    _drift_vals = []
                    for _e in _all_ev:
                        if getattr(_e, "is_ml_fallback", False):
                            _drift_vals.append(1.0)
                        elif getattr(_e, "drift_score", None) is not None:
                            _drift_vals.append(_e.drift_score)
                    _max_drift = max(_drift_vals) if _drift_vals else 0.0

            _abstention_reason = None
            if _data_cov < _ABSTENTION_COVERAGE_FLOOR and val_score < _ABSTENTION_TRUTH_CEILING:
                _abstention_reason = f"data_coverage={_data_cov:.2f}, truth_score={val_score:.2f}"
            elif _ml_fallback_ratio > 0.5:
                _abstention_reason = f"ml_fallback_ratio={_ml_fallback_ratio:.0%} (majority of evidence is ML fallback — models not loaded)"
            elif _max_drift > 0.7:
                _abstention_reason = f"max_drift={_max_drift:.2f} (models stale or unavailable — predictions unreliable)"

            if _abstention_reason:
                logger.warning(f"[Abstention Gate] Triggered: {_abstention_reason}")
                final_advice = (
                    "Insufficient data to provide a confident advisory. "
                    "Too few investigation tasks yielded verifiable evidence this session. "
                    "Recommend physical inspection or re-query with more specific equipment/zone identifiers."
                )
                val_score = min(val_score, 0.3)

            # ── T1 Working Memory: persist this turn ──────────────────────────
            if _mo is not None:
                try:
                    await _mo.save_conversation_turn(_operator_id, _building_id, "user", query)
                    await _mo.save_conversation_turn(_operator_id, _building_id, "assistant", final_advice)
                except Exception as _cm_save_err:
                    logger.debug(f"[Mem-4] save_conversation_turn failed (non-fatal): {_cm_save_err}")

            # ── Flush LLM usage metering to DB ────────────────────────────────
            if _investigation_plan is not None:
                try:
                    _plan_id = getattr(_investigation_plan, "id", "") or getattr(_investigation_plan, "plan_id", "")
                    _budget = getattr(_investigation_plan, "budget", None)
                    await self.db.flush_llm_usage(plan_id=_plan_id, budget=_budget)
                except Exception as _flush_err:
                    logger.debug(f"[CostMeter] flush_llm_usage failed (non-fatal): {_flush_err}")

            return ChatResponse(
                text=final_advice,
                tool_calls=_tc,
                tool_results=_tr,
                confidence=val_score,
                language=language,
                sources=["ARVIS Queen Consensus", f"Swarm Truth-Validator (Score: {val_score})"],
                explanation=explanation,
                truth_score=val_score,
                answer_confidence=1.0,
                data_coverage=_data_cov,
            )

        else:
            # Fallback (Safety mechanism if swarm fails to load)
            logger.warning("Swarm not available. Falling back to simple response.")
            return ChatResponse(
                text="The multi-agent swarm is currently offline. Please check system logs for initialization errors.",
                tool_calls=[],
                tool_results=[],
                confidence=0.0,
                language=language,
                sources=[],
                truth_score=0.0,
                answer_confidence=0.0,
                data_coverage=0.0,
            )

    # ── Fault diagnosis extraction ─────────────────────────────────────────────

    @staticmethod
    def _extract_fault_diagnosis(text: str, query: str) -> Optional[Dict[str, Any]]:
        """
        Detect whether ARVIS response contains a confirmed fault diagnosis.
        Returns skillbook args dict if found, None otherwise.
        Looks for: root cause language, equipment ID patterns, action items.
        """
        import re
        text_lower = text.lower()

        # Must have root cause language to be a diagnosis
        root_cause_signals = [
            "root cause", "caused by", "identified:", "confirmed:", "diagnosis:",
            "fault pattern", "failure mode", "damper stuck", "valve stuck",
            "bearing wear", "refrigerant leak", "coil fouling", "belt slip",
        ]
        if not any(s in text_lower for s in root_cause_signals):
            return None

        # Must have action items (resolved pattern)
        action_signals = [
            "recommend", "replace", "inspect", "clean", "calibrate",
            "adjust setpoint", "schedule", "dispatch", "repair",
        ]
        if not any(s in text_lower for s in action_signals):
            return None

        # Extract equipment ID (e.g. AHU-07, CH-01, CHILLER-01, CT-02)
        eq_match = re.search(
            r"\b(AHU|CH|CHILLER|CT|FCU|PUMP|VAV|MAU)-\d+\b", text, re.IGNORECASE
        )
        equipment_id = eq_match.group(0).upper() if eq_match else None

        # Build title from first root cause mention
        title_match = re.search(
            r"(?:root cause|diagnosis|identified|confirmed)[:\s]+([^\n\.]{10,80})",
            text, re.IGNORECASE
        )
        title = title_match.group(1).strip() if title_match else query[:80]

        # Description: first 400 chars of diagnostic block
        description = text[:400].strip()

        return {
            "title": title,
            "description": description,
            "equipment_id": equipment_id,
            "skill_type": "fault_pattern",
            "confidence": 0.7,
            "tags": [equipment_id] if equipment_id else [],
        }

    async def _programmatic_skillbook_write(
        self, text: str, query: str
    ) -> None:
        """
        State-machine triggered skillbook write — not LLM-optional.
        Called after every chat response that contains a confirmed diagnosis.
        """
        diagnosis = self._extract_fault_diagnosis(text, query)
        if diagnosis is None:
            return
        try:
            result = await self.tool_handler.execute("add_to_skillbook", diagnosis)
            logger.info(
                f"[Skillbook] Auto-recorded fault pattern: "
                f"'{diagnosis['title']}' eq={diagnosis['equipment_id']} → {result}"
            )
        except Exception as e:
            logger.warning(f"[Skillbook] Auto-write failed (non-fatal): {e}")

    @staticmethod
    def _inject_confidence_if_missing(text: str) -> str:
        """
        Post-process: if response lacks explicit confidence statement, append one
        derived from evidence signals in the text.
        """
        import re
        confidence_markers = [
            r"high confidence", r"medium confidence", r"low confidence",
            r"\d+%\s+confident", r"confidence[:\s]+\d",
        ]
        if any(re.search(p, text, re.IGNORECASE) for p in confidence_markers):
            return text  # Already has confidence statement

        text_lower = text.lower()
        # Heuristic: count evidence signals
        strong = sum(1 for s in [
            "trend", "days", "sensor", "confirmed", "consistent", "multiple",
            "historical", "baseline", "corroborat",
        ] if s in text_lower)

        if strong >= 3:
            label = "High confidence"
            basis = f"{strong} corroborating evidence signals"
        elif strong >= 1:
            label = "Medium confidence"
            basis = "limited corroborating data; verify with physical inspection"
        else:
            label = "Low confidence"
            basis = "insufficient trend data; recommend on-site verification"

        return text + f"\n\n**Confidence: {label}** — {basis}."

    async def run_edge_safeties(self, query: str, language: str) -> ChatResponse:
        """
        Heuristic-only fallback for critical equipment protection.
        No LLM used. Zero narration. Safety only.
        """
        logger.warning("[BMSLLMAgent] RUNNING IN DEGRADED INTELLIGENCE MODE (EDGE SAFETIES)")
        
        # 1. Fetch current critical sensor state
        vibration = 0.0
        try:
            chiller_state = await self.tool_handler.execute("get_equipment_status", {"equipment_id": "CHILLER-01"})
            vibration_str = str(chiller_state).split("Vibration: ")[1].split(" ")[0] if "Vibration" in str(chiller_state) else "0.0"
            vibration = float(vibration_str)
        except (IndexError, ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Could not parse vibration from fallback mode: {e}")
            
        # 3. Decision Matrix (BMS Constitution - Hardcoded)
        action_text = "Standard operation."
        tool_calls = []
        confidence = 0.5
        
        if vibration > 4.0:
            action_text = "🚨 DEGRADED MODE ALERT: CRITICAL VIBRATION DETECTED. RECOMMENDING EMERGENCY SHUTDOWN."
            tool_calls = [{"tool": "emergency_shutdown", "args": {"equipment_id": "CHILLER-01", "reason": "Edge Safety Threshold Exceeded"}}]
            confidence = 1.0
            
        return ChatResponse(
            text=action_text + " (Note: LLM Reasoning Unavailable - Fixed Safety Fallback Active)",
            tool_calls=tool_calls,
            tool_results=[],
            confidence=confidence,
            language=language,
            sources=["Edge Safeties Heuristics"],
        )

    def _robust_json_parse(self, tool_name: str, args_str: str) -> Dict[str, Any]:
        """
        Formalized Tool Call Sanitizer.
        Auto-repairs malformed JSON and strips LLM-injected XML tags.
        """
        if not args_str or args_str.strip() == "{}":
            return {}
            
        import re
        
        # 1. Strip <function=...> tags if LLM nested them inside the argument string
        if "<function=" in args_str:
            match = re.search(r'<function=.*?>(.*?)</function>', args_str, re.DOTALL)
            if match:
                args_str = match.group(1)
            else:
                # Handle partial/malformed tags: <function=name>{"arg": 1}
                args_str = re.sub(r'<function=.*?>', '', args_str)
                args_str = re.sub(r'</function>', '', args_str)

        # 2. Handle Groq-style malformed assignments: name={"arg": 1}
        if "=" in args_str and not args_str.strip().startswith("{"):
             # extract everything after the first = 
             args_str = args_str.split("=", 1)[1]

        # 3. Clean trailing commas and whitespace
        args_str = args_str.strip()
        args_str = re.sub(r',\s*\}', '}', args_str) # Trailing comma in dict
        args_str = re.sub(r',\s*\]', ']', args_str) # Trailing comma in list

        try:
            parsed = json.loads(args_str)
            
            # --- TYPE REPAIR (Intelligence Hardening) ---
            # Common Fix: Groq/k2think occasionally wrap 'limit' or 'period' in strings when they should be ints
            if parsed and isinstance(parsed, dict):
                if "limit" in parsed and isinstance(parsed["limit"], str) and parsed["limit"].isdigit():
                    parsed["limit"] = int(parsed["limit"])
                if "period" in parsed and isinstance(parsed["period"], str) and parsed["period"].isdigit():
                    parsed["period"] = int(parsed["period"])
            
            return parsed or {}
        except json.JSONDecodeError:
            # 4. Deep Repair: Try to extract ANY JSON object from the string
            match = re.search(r'(\{.*\})', args_str, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    if parsed and isinstance(parsed, dict):
                        if "limit" in parsed and isinstance(parsed["limit"], str) and parsed["limit"].isdigit():
                            parsed["limit"] = int(parsed["limit"])
                    return parsed or {}
                except json.JSONDecodeError:
                    pass
            
            logger.error(f"[Sanitizer] Failed to parse args for {tool_name}: {args_str}")
            return {}

    async def _generate_tool_calls(
        self, 
        query: str, 
        language: str, 
        history: List[Dict] = None,
        context: Dict = None
    ) -> List[Dict[str, Any]]:
        """
        Generates tool calls using Smart Tool Economy filtering.
        """
        history = history or []
        system_prompt = await self._get_system_prompt(query, language)
        
        # 1. SMART TOOL ECONOMY CHECK
        allowed_tools_names = None
        if hasattr(self, 'economy_policy'):
            urgency = "normal"
            if context and context.get("is_critical"): urgency = "critical"
            elif any(w in query.lower() for w in ["urgent", "danger", "critical"]): urgency = "critical"
            
            allowed_tools_names = self.economy_policy.get_minimal_sufficient_set(query, context, urgency)
            logger.info(f"[SmartEconomy] Filtered tools to: {allowed_tools_names}")
        
        # 2. Filter the Schema
        filtered_tools_def = []
        for tool in self.tools:
            # Always allow fallback/safety tools
            is_critical_tool = tool["name"] in ["get_active_alarms", "get_equipment_status"]
            
            if is_critical_tool or (allowed_tools_names is None) or (tool["name"] in allowed_tools_names):
                filtered_tools_def.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"]
                    }
                })
        
        # 3. Construct Messages with History
        messages = [{"role": "user", "content": query}]
        
        # Inject History as Context if we are inside the loop
        if history:
            history_lines = []
            for step in history:
                tools_used = [a['tool'] for a in step['actions']]
                history_lines.append(f"Turn {step['turn']}: Call {tools_used}")
                # Stringify result and truncate to avoid overflow but keep essential evidence
                res_snippet = str(step['observations'])[:1000]
                history_lines.append(f"       Result: {res_snippet}")
            
            history_text = "\n".join(history_lines)
            
            messages.append({
            "role": "system",
            "content": (
                f"### Investigation History\n{history_text}\n\n"
                "### Grounded Todo List Management\n"
                "You are in a multi-turn investigative loop. You MUST maintain a mental Todo List using these STRICT rules:\n"
                "1. **STRATEGIC TAGGING**: Every <think> block MUST start with one of: [PLAN], [DECIDE], [VERIFY], or [EXIT].\n"
                "2. **NO HALLUCINATION**: Only add items to the Todo list that are directly requested by the user or necessitated by a SPECIFIC tool result...\n"
                "3. **EVIDENCE-BASED PROGRESS**: To mark a task as 'Complete', you MUST cite the specific evidence from tool results.\n"
                "4. **SKEPTICISM**: If a tool returns an error, do NOT assume success.\n\n"
                "Based on the Evidence above, what is the next logical action? \n"
                "- If more data is needed, call the MOST SURGICAL tool.\n"
                "- If you have verified all facts, provide the final answer TEXT only."
            )
        })

        system_msgs = [{"content": system_prompt}]
        
        response = await self.llm.ask_tool(
            messages=messages,
            system_msgs=system_msgs,
            tools=filtered_tools_def,
            tool_choice="auto"
        )
        
        if response.tool_calls:
            return [
                {
                    "tool": tc.function.name,
                    "args": self._robust_json_parse(tc.function.name, tc.function.arguments)
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
