"""
Truth-Score Verification System for ARVIS Swarm.
Ensures outputs have a high truth score (>0.95) before user delivery by 
verifying claims against system context.
"""
import logging
from typing import Dict, Any, Optional

from agent_unified.llm import UnifiedLLM

logger = logging.getLogger("arvis.swarm.validator")

class TruthValidator:
    """Verifies generated advice against hallucinations."""
    
    def __init__(self):
        self.llm = UnifiedLLM()

    async def validate(self, advice: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Assigns a truth score to the advice based on available context.
        """
        logger.info("[Validator] Running Truth-Score evaluation on final advice...")
        
        prompt = (
            "You are a strict Truth-Score Validator.\n"
            "Read the generated advice and compare it to the ground truth context.\n"
            "If the advice invents a metric, building name, or alarm that is NOT in the context, your score is 0.0.\n"
            "If the advice is strictly grounded in the context, your score is 1.0.\n"
            "IMPORTANT: Your output MUST be EXACTLY a valid JSON object. Do NOT include ANY conversational text, tags, markdown formatting, or explanations.\n"
            "Format your response EXACTLY as follows:\n{\n  \"score\": 1.0,\n  \"reasoning\": \"Your reasoning here.\"\n}"
        )
        
        user_msg = f"CONTEXT: {context}\n\nADVICE: {advice}"
        
        try:
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": prompt}]
            )
            score = float(result.get("score", 0.0))
            return {"score": score, "reasoning": result.get("reasoning", "")}
        except Exception as e:
            logger.error(f"[Validator] Validation failed: {e}")
            return {"score": 0.0, "reasoning": str(e)}
