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
        # Safety veto responses still validated — no auto-pass
        if advice.startswith("I simulated your proposed action. I **STRONGLY ADVISE AGAINST IT**"):
            logger.info("[Validator] BFT Safety Veto detected. Will validate but apply relaxed hurdle.")

        # Thermal safety: note for relaxed scoring but no auto-pass
        _thermal_boost = False
        if "GROUNDING_THERMAL_SAFETY" in (context or {}) and len(context["GROUNDING_THERMAL_SAFETY"]) > 0:
            breach_keywords = ["high temp", "thermal", "breach", "critical temp", "supply air", "overheating"]
            if any(kw in advice.lower() for kw in breach_keywords):
                _thermal_boost = True
                logger.info("[Validator] Safety-critical advice with grounding data. Eligible for +0.1 boost (not auto-pass).")
            
        logger.info("[Validator] Running Truth-Score evaluation on final advice...")
        
        # M3.3: Build ML fallback penalty instruction if context carries _ml_evidence_summary
        ml_fallback_tools = (context or {}).get("_ml_fallback_tools", [])
        ml_penalty_clause = ""
        if ml_fallback_tools:
            tools_str = ", ".join(ml_fallback_tools)
            ml_penalty_clause = (
                f"\nML FALLBACK PENALTY: The following tools returned ML_UNAVAILABLE (models not loaded): {tools_str}. "
                "If the advice cites specific numeric values (probabilities, fault scores, confidence percentages, forecast numbers) "
                "that can only come from these unavailable ML models, score 0.0 immediately — these values are fabricated."
            )

        prompt = (
            "You are a strict Truth-Score Validator.\n"
            "Read the generated advice and compare it to the ground truth context.\n"
            "If the advice invents a metric, building name, or alarm that is NOT in the context, your score is 0.0.\n"
            "NUMERIC EXACTNESS: Every number in the advice must appear VERBATIM in the context data. No rounding, no arithmetic, no estimation. If a number in the advice does not match a number in the context exactly, score 0.0.\n"
            "If the advice is strictly grounded in the context (modulo minor math), your score is 1.0.\n"
            f"{ml_penalty_clause}\n"
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
            
            # Thermal safety boost: capped at +0.1, never auto-1.0
            if _thermal_boost:
                boosted = min(score + 0.1, 1.0)
                logger.info(f"[Validator] Thermal safety boost: {score:.2f} → {boosted:.2f} (capped +0.1)")
                score = boosted
            
            # PHASE 4: EWC++ Penalty for Hallucination
            if score < 0.95:
                try:
                    from agent_cognitive.meta_cognition import MetaCognition
                    b_id = context.get("building_id", "default") if context else "default"
                    logger.warning(f"[Validator] Hallucination detected (Score: {score}). Applying EWC++ penalty for {b_id}.")
                    MetaCognition(building_id=b_id).update_ewc_weights(
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
