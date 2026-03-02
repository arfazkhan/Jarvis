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
        Validates the generated advice against the provided context.
        Returns a dict with 'score' (0.0 to 1.0) and 'reasoning'.
        """
        if advice.startswith("I simulated your proposed action. I **STRONGLY ADVISE AGAINST IT**"):
            logger.info("[Validator] BFT Safety Veto detected. Bypassing grounding check. Auto-Approve.")
            return {"score": 1.0, "reasoning": "BFT Safety Veto approved."}
            
        logger.info("[Validator] Running Truth-Score evaluation on final advice...")
        
        prompt = (
            "You are a strict Truth-Score Validator.\n"
            "Read the generated advice and compare it to the ground truth context.\n"
            "If the advice invents a metric, building name, or alarm that is NOT in the context, your score is 0.0.\n"
            "If the advice is strictly grounded in the context, your score is 1.0.\n"
            "IMPORTANT: Your output MUST be EXACTLY a valid JSON object. Do NOT include ANY conversational text, tags, markdown formatting, or explanations.\n"
            "Format your response EXACTLY as follows:\n{\n  \"score\": 1.0,\n  \"reasoning\": \"Your reasoning here.\"\n}"
        )
        
        user_msg = (
            f"Context Data: {context}\n\n"
            f"Generated Advice: {advice}\n\n"
            "Evaluate the Truth-Score of this advice based strictly on the context."
        )
        
        try:
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": prompt}]
            )
            
            logger.info(f"[Validator] Raw ask_json result: {result}")
            
            # Handle case where LLM returns a JSON array instead of an object
            if isinstance(result, list) and len(result) > 0:
                result = result[0]
            elif not isinstance(result, dict):
                result = {}
                
            score = float(result.get("score", 0.0))
            
            # PHASE 4: EWC++ Penalty for Hallucination
            if score < 0.95:
                try:
                    from agent_cognitive.meta_cognition import MetaCognition
                    logger.warning(f"[Validator] Hallucination detected (Score: {score}). Applying EWC++ penalty.")
                    MetaCognition(building_id="default").update_ewc_weights(
                        rule_name="hallucination_penalty_rule",
                        new_weight=-0.5,
                        importance=2.0
                    )
                except Exception as e:
                    logger.error(f"[Validator] Failed to apply EWC++ penalty: {e}")
            
            return {"score": score, "reasoning": result.get("reasoning", "")}
        except Exception as e:
            logger.error(f"[Validator] Validation failed: {e}")
            return {"score": 0.0, "reasoning": str(e)}
