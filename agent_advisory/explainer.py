"""
Explanation Engine
==================

This module provides human-readable explanations for agent decisions and recommendations.
It bridges the gap between raw data/simulations and operator mental models.

Capabilities:
1. Multi-level detail (Brief, Standard, Detailed).
2. Causal Chain Analysis (Why did we recommend this?).
3. Counterfactual Reasoning (What happens if we do nothing?).
4. Uncertainty Breakdown (Why is confidence X%).
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum

from agent_commercial.ml.llm_interpreter import create_k2_interpreter, InterpretationType
from agent_commercial.ml.llm_interpreter import create_k2_interpreter, InterpretationType
from agent_unified.llm import UnifiedLLM

logger = logging.getLogger("arvis.advisory.explainer")

class DetailLevel(Enum):
    BRIEF = "brief"      # One-liner for alerts
    STANDARD = "standard" # For general chat/briefings
    DETAILED = "detailed" # Technical deep-dive for engineers

class ExplanationEngine:
    """
    Orchestrates the generation of high-fidelity explanations.
    Uses K2 Think for reasoning and the World Model for causal grounding.
    """
    
    def __init__(self, world_model: Optional[Any] = None):
        self.interpreter = create_k2_interpreter()
        self.world_model = world_model
        # Use UnifiedLLM to respect LLM_PROVIDER and provide better reliability
        self.llm = UnifiedLLM()
        
    async def explain_recommendation(
        self,
        recommendation: Dict[str, Any],
        context: Dict[str, Any],
        level: DetailLevel = DetailLevel.STANDARD
    ) -> Dict[str, Any]:
        """
        Generate a multi-level explanation for a recommendation.
        """
        causal_chain = []
        counterfactual = None
        sim_data = {}
        
        if self.world_model:
            # 1. Project Future with Action
            action = recommendation.get("action_type", "no_op")
            traj = self.world_model.simulate_action(context, action, horizon=4)
            
            # 2. Project Future without Action (Counterfactual)
            no_op_traj = self.world_model.simulate_action(context, "no_op", horizon=4)
            
            causal_chain = self._extract_causal_path(context, traj)
            counterfactual = self._format_counterfactual(no_op_traj)
            
            sim_data = {
                "final_temp": traj.final_state.features.get("zone_temp_avg_c"),
                "total_cost_saved": (no_op_traj.total_reward - traj.total_reward) * -1, # Reward is negative cost
                "confidence": sum(traj.confidence_scores) / len(traj.confidence_scores)
            }
            
        # 3. Enhanced Prompting
        prompt = self._build_explanation_prompt(recommendation, causal_chain, counterfactual, sim_data, level)
        
        try:
            # Use UnifiedLLM for the narrative
            response = await self.llm.ask(
                messages=[{"role": "user", "content": prompt}],
                system_msgs=[{"role": "system", "content": "You are a Master Building Systems Engineer (ASHRAE Certified). Your goal is to explain complex BMS decisions to operators with varying technical levels."}]
            )
            
            explanation_text = response.content.strip()
            
            # Clean up <think> tags if they leak out
            import re
            explanation_text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", explanation_text, flags=re.DOTALL).strip()
            
        except Exception as e:
            logger.error(f"Explanation generation failed: {e}")
            explanation_text = f"Recommendation: {recommendation.get('description')}. Simulation projects improved efficiency."
            
        return {
            "text": explanation_text,
            "level": level.value,
            "causal_chain": causal_chain,
            "counterfactual": counterfactual,
            "sim_confidence": sim_data.get("confidence", 0)
        }
        
    def _extract_causal_path(self, initial_ctx: Dict, trajectory: Any) -> List[str]:
        """Convert trajectory delta into physical causal steps"""
        path = []
        initial_temp = initial_ctx.get("zone_temp_avg_c", 23)
        final_temp = trajectory.final_state.features.get("zone_temp_avg_c", 23)
        initial_power = initial_ctx.get("total_power_kw", 400)
        final_power = trajectory.final_state.features.get("total_power_kw", 400)
        
        actions = [a for a in trajectory.actions if a != "no_op"]
        primary_action = actions[0] if actions else "Adjustment"
        
        path.append(f"Execute {primary_action}")
        
        if final_power < initial_power:
            pct = (initial_power - final_power) / initial_power * 100
            path.append(f"Reduce power demand by {pct:.1f}%")
            
        if final_temp > initial_temp:
            path.append(f"Allow controlled thermal drift (+{final_temp - initial_temp:.1f}°C)")
        elif final_temp < initial_temp:
            path.append(f"Accelerate cooling stabilization (-{initial_temp - final_temp:.1f}°C)")
            
        path.append("Achieve target equilibrium")
        return path
        
    def _format_counterfactual(self, trajectory: Any) -> str:
        """Describe the 'Do Nothing' outcome"""
        final_temp = trajectory.final_state.features.get("zone_temp_avg_c", 23)
        final_power = trajectory.final_state.features.get("total_power_kw", 400)
        
        if final_temp > 25:
            return f"Delaying action risks a zone temperature surge to {final_temp:.1f}°C, likely triggering high-temperature alarms."
        elif final_power > 600:
            return f"Maintenance of status quo will result in sustained peak demand (~{final_power:.0f} kW) and higher Kahramaa charges."
        
        return "Minimal immediate risk, but efficiency remains sub-optimal compared to the target."

    def _build_explanation_prompt(self, rec, causal, cf, sim, level) -> str:
        return f"""
        EXPLAIN THIS RECOMMENDATION TO A BMS OPERATOR.
        
        ### RECOMMENDATION
        - Title: {rec.get('title')}
        - Description: {rec.get('description')}
        - Priority: {rec.get('priority', 'Medium')}
        
        ### PHYSICAL CAUSAL CHAIN
        {' -> '.join(causal)}
        
        ### WHAT IF WE DO NOTHING? (COUNTERFACTUAL)
        {cf}
        
        ### SIMULATION DATA
        - Predicted Cost Delta: QAR {sim.get('total_cost_saved', 0):.2f}
        - Simulation Confidence: {sim.get('confidence', 0)*100:.1f}%
        
        ### OUTPUT REQUIREMENTS
        - Detail Level: {level.value.upper()}
        - Language: English (keep it technical but accessible)
        - Format: 
            { 'One short, punchy sentence only.' if level == DetailLevel.BRIEF else '' }
            { 'A clear 3-sentence briefing including the causal chain.' if level == DetailLevel.STANDARD else '' }
            { 'A detailed technical breakdown including the physical mechanism and simulation uncertainty.' if level == DetailLevel.DETAILED else '' }
        
        DO NOT invent numbers. Use only the provided simulation data.
        """
