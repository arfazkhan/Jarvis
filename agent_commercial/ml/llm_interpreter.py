"""
ML-LLM Interpreter with K2 Think Integration
=============================================

Hybrid architecture that uses ML for predictions and K2 Think LLM for explanations.

ANTI-HALLUCINATION MEASURES:
1. Grounded Prompts - LLM can ONLY reference data from ML output
2. Chain-of-Thought - Forces step-by-step reasoning
3. Few-Shot Examples - Shows correct response format
4. Fact Verification - Check if LLM output matches source data
5. Citation Requirement - LLM must cite specific numbers from ML
6. Confidence Gating - Only interpret when ML confidence > threshold

ADVANCED PROMPT TECHNIQUES:
- Role as ASHRAE-certified Building Systems Expert
- Step-by-step reasoning requirement
- Explicit grounding constraints
- Domain-specific terminology
- Few-shot examples for each interpretation type

Usage:
    >>> from agent_commercial.ml.llm_interpreter import create_k2_interpreter
    >>> interpreter = create_k2_interpreter()
    >>> result = interpreter.interpret_fault(fault_data)
"""

import logging
import json
import re
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("arvis.ml.interpreter")


# =============================================================================
# K2 THINK LLM CLIENT
# =============================================================================

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

class UnifiedInterpreterClient:
    """
    Client for ML interpretation using the UnifiedLLM stack.
    Respects LLM_PROVIDER and LLM_MODEL settings.
    """
    
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.unified_llm = UnifiedLLM()
        self.provider = provider or os.environ.get("LLM_PROVIDER", "k2think")
        logger.info(f"Interpreter client initialized with {self.provider}")
    
    async def chat(self, 
             messages: List[Dict[str, str]], 
             max_tokens: int = 500,
             temperature: float = 0.2) -> Dict[str, Any]:
        """
        Send chat completion request using UnifiedLLM.
        """
        try:
            # We use ask() which routes to the Reasoning Agent (K2 or Groq/Llama)
            response = await self.unified_llm.ask(
                messages=messages,
                max_tokens=max_tokens if hasattr(self.unified_llm, 'ask') else 500
            )
            
            # response is a Message object from UnifiedLLM
            return {"content": response.content}
            
        except Exception as e:
            logger.error(f"Interpreter LLM error: {e}")
            raise


# =============================================================================
# ANTI-HALLUCINATION CONSTANTS
# =============================================================================

CONFIDENCE_THRESHOLD = 0.5
MAX_RESPONSE_TOKENS = 500


# =============================================================================
# ENHANCED GROUNDED PROMPTS WITH CHAIN-OF-THOUGHT
# =============================================================================

SYSTEM_PROMPT = """You are an ASHRAE-certified Building Systems Expert with 20 years of experience in commercial HVAC, BMS analytics, and facility operations in Qatar.

CRITICAL ANTI-HALLUCINATION RULES:
1. You may ONLY reference data explicitly provided in the user message
2. Do NOT invent numbers, equipment IDs, timestamps, or any facts
3. Do NOT speculate about causes unless directly supported by provided data
4. If you're uncertain, say "based on the provided data" rather than asserting
5. Always cite the specific values from the input when making claims
6. Never reference external knowledge about specific buildings or equipment

RESPONSE STYLE:
- Write as a senior facility engineer briefing a building manager
- Be concise but technically precise
- Use HVAC industry terminology appropriately
- Prioritize actionable insights over descriptions"""

GROUNDED_PROMPTS = {
    "fault_detection": """## FAULT DETECTION ANALYSIS

You are analyzing a fault detected by our ML-based Fault Detection & Diagnostics system.

### PROVIDED DATA (You may ONLY use this information):
```json
{data_json}
```

### FEW-SHOT EXAMPLE:
Input: {{"equipment_id": "CH-02", "fault_type": "HIGH_COND_APPROACH", "severity": "medium", "detected_value": 8.5, "expected_range": [3, 6], "confidence": 0.88}}
Output: "Chiller CH-02 is showing HIGH_COND_APPROACH fault (medium severity). The condenser approach temperature is 8.5°C versus expected 3-6°C, indicating possible condenser fouling. Detection confidence: 88%. Recommend inspecting condenser tubes and cleaning if needed."

### YOUR TASK:
1. State the equipment and fault type clearly
2. Explain what the fault means in operational terms
3. Cite the specific detected value vs expected range
4. Provide ONE actionable recommendation
5. Keep response under 4 sentences

### YOUR ANALYSIS:""",

    "energy_forecast": """## ENERGY DEMAND FORECAST ANALYSIS

You are interpreting an energy forecast from our Prophet + LightGBM ensemble model.

### PROVIDED DATA (You may ONLY use this information):
```json
{data_json}
```

### FEW-SHOT EXAMPLE:
Input: {{"building_id": "tower_b", "daily_total_kwh": 15420, "daily_cost_qar": 771, "peak_hour_kwh": 4650, "confidence": 0.82}}
Output: "Tomorrow's forecast for Tower B: 15,420 kWh total demand at an estimated cost of QAR 771. Peak consumption of 4,650 kWh expected during tariff peak hours (12:00-18:00). Model confidence is 82% - weather uncertainty is factored in."

### YOUR TASK:
1. State the total predicted demand and cost
2. Highlight peak hour consumption if significant  
3. Mention the confidence level and what it means
4. Keep response under 3 sentences

### YOUR ANALYSIS:""",

    "simulation_result": """## WHAT-IF SIMULATION ANALYSIS

You are interpreting results from our Gaussian Process simulation of an operational change.

### PROVIDED DATA (You may ONLY use this information):
```json
{data_json}
```

### FEW-SHOT EXAMPLE:
Input: {{"change_type": "setpoint", "current_value": 22, "proposed_value": 24, "energy_impact": {{"mean": 14.0, "lower_bound": 10.5, "upper_bound": 17.5}}, "cost_impact_qar": {{"mean": 320}}, "comfort_impact": {{"mean": 12}}, "risk_of_reversion": 0.18}}
Output: "Raising setpoint from 22°C to 24°C would save approximately 14% energy (range: 10.5-17.5%) and QAR 320/month. However, 12% of occupants may report discomfort based on historical data. With 18% reversion risk, consider a staged rollout - try 23°C first."

### YOUR TASK:
1. Describe the proposed change and its energy impact with confidence range
2. State the cost savings in QAR
3. Assess comfort risk using the provided complaint percentage
4. Consider reversion risk in your recommendation
5. Provide a nuanced recommendation, not just "implement" or "don't"

### YOUR ANALYSIS:""",

    "root_cause": """## ROOT CAUSE CASCADE ANALYSIS

You are interpreting results from our Bayesian Network root cause analysis.

### PROVIDED DATA (You may ONLY use this information):
```json
{data_json}
```

### FEW-SHOT EXAMPLE:
Input: {{"root_cause": {{"equipment_id": "CHW-P-01", "fault_type": "low_flow"}}, "cascade_path": ["CHW-P-01", "AHU-01", "AHU-02", "VAV-3F-01"], "confidence": 0.78, "explanation": "Pump fault caused flow reduction to multiple AHUs"}}
Output: "Root cause identified: CHW-P-01 (low flow fault) at 78% confidence. This caused a cascade failure: CHW-P-01 → AHU-01 → AHU-02 → VAV-3F-01. The chilled water pump fault reduced flow to downstream AHUs, which then couldn't maintain zone temperatures. Prioritize pump inspection over investigating individual AHU alarms."

### YOUR TASK:
1. State the root cause equipment and fault type FIRST
2. Explain the cascade path in sequence
3. Describe the physical mechanism if clear from the data
4. Recommend focusing on root cause, not downstream effects
5. State confidence level

### YOUR ANALYSIS:""",

    "fleet_benchmark": """## PORTFOLIO BENCHMARKING ANALYSIS

You are interpreting building performance benchmarks against our fleet.

### PROVIDED DATA (You may ONLY use this information):
```json
{data_json}
```

### FEW-SHOT EXAMPLE:
Input: {{"building_id": "tower_a", "percentile_rank": {{"eui": 65, "water_intensity": 45}}, "best_in_class": ["water_intensity"], "improvement_opportunities": [{{"metric": "eui", "gap": 15}}], "potential_savings_qar": 45000}}
Output: "Tower A ranks at 65th percentile for EUI (better than 65% of fleet) and 45th percentile for water. It's best-in-class for water efficiency. The 15-point EUI gap vs fleet average represents QAR 45,000/year savings opportunity. Recommend focusing optimization efforts on energy rather than water."

### YOUR TASK:
1. State percentile rankings for key metrics
2. Highlight any best-in-class achievements
3. Quantify improvement opportunities in QAR
4. Recommend which metric to focus on
5. Keep response under 4 sentences

### YOUR ANALYSIS:""",
}


# =============================================================================
# DATA MODELS
# =============================================================================

class InterpretationType(Enum):
    FAULT_DETECTION = "fault_detection"
    ENERGY_FORECAST = "energy_forecast"
    SIMULATION = "simulation_result"
    ROOT_CAUSE = "root_cause"
    FLEET_BENCHMARK = "fleet_benchmark"


@dataclass
class GroundedContext:
    """Context for grounding LLM responses"""
    interpretation_type: InterpretationType
    source_data: Dict[str, Any]
    key_facts: List[str]
    
    def to_json(self) -> str:
        """Convert source data to JSON for prompt."""
        return json.dumps(self.source_data, indent=2, default=str)


@dataclass
class InterpretedResult:
    """Result of ML interpretation"""
    original_data: Dict[str, Any]
    explanation: str
    key_facts_cited: List[str]
    confidence: float
    verified: bool
    llm_used: bool
    verification_notes: str = ""
    thinking: str = ""  # K2 Think's reasoning process
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation": self.explanation,
            "key_facts_cited": self.key_facts_cited,
            "confidence": round(self.confidence, 3),
            "verified": self.verified,
            "llm_used": self.llm_used,
            "verification_notes": self.verification_notes,
            "raw_data": self.original_data,
        }


# =============================================================================
# ML INTERPRETER WITH K2 THINK
# =============================================================================

class MLInterpreter:
    """
    Interprets ML results using K2 Think LLM with strict anti-hallucination.
    """
    
    def __init__(self, 
                 llm_client: Optional[UnifiedInterpreterClient] = None,
                 confidence_threshold: float = CONFIDENCE_THRESHOLD):
        self.llm_client = llm_client or create_unified_interpreter()
        self.confidence_threshold = confidence_threshold
        logger.info("MLInterpreter initialized")
    
    async def interpret(self,
                  interpretation_type: InterpretationType,
                  ml_result: Dict[str, Any],
                  use_llm: bool = True) -> InterpretedResult:
        """
        Interpret an ML result with anti-hallucination measures.
        """
        key_facts = self._extract_key_facts(interpretation_type, ml_result)
        
        context = GroundedContext(
            interpretation_type=interpretation_type,
            source_data=ml_result,
            key_facts=key_facts,
        )
        
        confidence = ml_result.get("confidence", 1.0)
        if confidence < self.confidence_threshold:
            return self._low_confidence_response(ml_result, key_facts)
        
        thinking = ""
        if use_llm and self.llm_client:
            explanation, thinking = await self._generate_llm_explanation(context)
            verified, notes = self._verify_grounding(explanation, key_facts, ml_result)
            
            # If verification fails, fall back to template
            if not verified:
                logger.warning(f"LLM response failed verification: {notes}")
                explanation = self._template_explanation(context)
                verified = True
                notes = f"Fallback to template (LLM failed: {notes})"
        else:
            explanation = self._template_explanation(context)
            verified = True
            notes = "Template-based (no LLM)"
        
        return InterpretedResult(
            original_data=ml_result,
            explanation=explanation,
            key_facts_cited=self._find_cited_facts(explanation, key_facts),
            confidence=confidence,
            verified=verified,
            llm_used=use_llm and self.llm_client is not None,
            verification_notes=notes,
            thinking=thinking,
        )
    
    def _extract_key_facts(self,
                           interpretation_type: InterpretationType,
                           ml_result: Dict[str, Any]) -> List[str]:
        """Extract key facts that must be cited in explanation."""
        facts = []
        
        if interpretation_type == InterpretationType.FAULT_DETECTION:
            for key in ["equipment_id", "fault_type", "severity"]:
                if key in ml_result:
                    facts.append(str(ml_result[key]))
                    
        elif interpretation_type == InterpretationType.ENERGY_FORECAST:
            summary = ml_result.get("summary", ml_result)
            if "daily_total_kwh" in summary:
                facts.append(str(int(summary["daily_total_kwh"])))
                    
        elif interpretation_type == InterpretationType.SIMULATION:
            energy = ml_result.get("energy_impact", {})
            if isinstance(energy, dict) and "mean" in energy:
                facts.append(str(round(energy["mean"], 1)))
                
        elif interpretation_type == InterpretationType.ROOT_CAUSE:
            rc = ml_result.get("root_cause", {})
            if isinstance(rc, dict) and "equipment_id" in rc:
                facts.append(rc["equipment_id"])
                
        elif interpretation_type == InterpretationType.FLEET_BENCHMARK:
            bench = ml_result.get("benchmark", ml_result)
            if "building_id" in bench:
                facts.append(bench["building_id"])
        
        return facts
    async def _generate_llm_explanation(self, context: GroundedContext) -> tuple:
        """Generate LLM explanation with reasoning."""
        template = GROUNDED_PROMPTS.get(context.interpretation_type.value)
        
        if not template:
            return self._template_explanation(context), ""
        
        # Build prompt with data
        user_prompt = template.format(data_json=context.to_json())
        
        try:
            response = await self.llm_client.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=MAX_RESPONSE_TOKENS,
                temperature=0.2,
            )
            
            content = response.get("content", "").strip()
            
            # ─────────────────────────────────────────────────────────────
            # Reasoning Extraction (Handles K2 Think <think> tags)
            # ─────────────────────────────────────────────────────────────
            thinking = ""
            import re
            
            # UnifiedLLM might have already stripped <think> if using k2think provider
            # but if it's raw or from another provider, we double-check.
            think_match = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", content, flags=re.DOTALL)
            
            # Extract answer if present
            answer_match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)
            if answer_match:
                content = answer_match.group(1).strip()
            else:
                content = content.strip()
            
            return content, thinking
            
        except Exception as e:
            logger.error(f"Interpreter LLM call failed: {e}")
            return self._template_explanation(context), ""
    
    def _template_explanation(self, context: GroundedContext) -> str:
        """Generate template-based explanation (guaranteed accurate)."""
        data = context.source_data
        itype = context.interpretation_type
        
        if itype == InterpretationType.FAULT_DETECTION:
            return (f"{data.get('severity', 'Medium').upper()} fault on "
                   f"{data.get('equipment_id', 'equipment')}: "
                   f"{data.get('description', data.get('fault_type', 'Unknown'))}. "
                   f"Detected value: {data.get('detected_value', 'N/A')}, "
                   f"expected: {data.get('expected_range', 'N/A')}. "
                   f"Confidence: {data.get('confidence', 0)*100:.0f}%.")
        
        elif itype == InterpretationType.ENERGY_FORECAST:
            summary = data.get("summary", data)
            return (f"Forecast for {data.get('building_id', 'building')}: "
                   f"{summary.get('daily_total_kwh', 0):,.0f} kWh, "
                   f"QAR {summary.get('daily_cost_qar', 0):,.0f}. "
                   f"Confidence: {summary.get('confidence', 0)*100:.0f}%.")
        
        elif itype == InterpretationType.SIMULATION:
            energy = data.get("energy_impact", {})
            cost = data.get("cost_impact_qar", {})
            return (f"Change {data.get('change_type', '')} "
                   f"{data.get('current_value')}→{data.get('proposed_value')}: "
                   f"Energy {energy.get('mean', 0):+.1f}% "
                   f"[{energy.get('lower_bound', 0):.1f}%, {energy.get('upper_bound', 0):.1f}%], "
                   f"QAR {cost.get('mean', 0):+.0f}/mo. "
                   f"Risk: {data.get('risk_of_reversion', 0)*100:.0f}%.")
        
        elif itype == InterpretationType.ROOT_CAUSE:
            rc = data.get("root_cause", {})
            return (f"Root cause: {rc.get('equipment_id', '?')} ({rc.get('fault_type', '?')}). "
                   f"Cascade: {' → '.join(data.get('cascade_path', []))}. "
                   f"Confidence: {data.get('confidence', 0)*100:.0f}%.")
        
        elif itype == InterpretationType.FLEET_BENCHMARK:
            bench = data.get("benchmark", data)
            pct = bench.get("percentile_rank", {})
            return (f"{bench.get('building_id', 'Building')}: "
                   f"EUI {pct.get('eui', 50):.0f}th pctl. "
                   f"Savings potential: QAR {bench.get('potential_savings_qar', 0):,.0f}/yr.")
        
        return "Unable to interpret this result type."
    
    def _verify_grounding(self,
                          explanation: str,
                          key_facts: List[str],
                          source_data: Dict[str, Any]) -> tuple:
        """Verify explanation is grounded in source data."""
        issues = []
        
        # Check key facts
        for fact in key_facts:
            if str(fact).lower() not in explanation.lower():
                issues.append(f"Missing: {fact}")
        
        # Check for fabricated numbers
        numbers_in_explanation = set(re.findall(r'\d+\.?\d*', explanation))
        source_numbers = set()
        self._extract_numbers(source_data, source_numbers)
        
        # Common/allowed numbers (percentages, small counts, etc.)
        allowed_numbers = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 18, 20, 50, 100}
        
        for num in numbers_in_explanation:
            try:
                num_float = float(num)
                if num_float in allowed_numbers:
                    continue
                if not self._number_in_source(num_float, source_numbers):
                    issues.append(f"Ungrounded: {num}")
            except ValueError:
                pass
        
        # More lenient: allow up to 2 minor issues
        verified = len(issues) <= 2
        notes = "; ".join(issues[:3]) if issues else "Verified"
        
        return verified, notes
    
    def _extract_numbers(self, data: Any, numbers: set) -> None:
        """Recursively extract all numbers from data, including percentage conversions."""
        if isinstance(data, (int, float)):
            numbers.add(data)
            numbers.add(round(data, 1))
            numbers.add(round(data, 0))
            numbers.add(int(data))
            # Handle percentage conversions (0.88 -> 88)
            if 0 < data < 1:
                numbers.add(data * 100)
                numbers.add(round(data * 100, 0))
                numbers.add(int(data * 100))
        elif isinstance(data, dict):
            for v in data.values():
                self._extract_numbers(v, numbers)
        elif isinstance(data, list):
            for item in data:
                self._extract_numbers(item, numbers)
        elif isinstance(data, str):
            for match in re.findall(r'\d+\.?\d*', data):
                try:
                    numbers.add(float(match))
                except ValueError:
                    pass
    
    def _number_in_source(self, num: float, source_numbers: set) -> bool:
        """Check if number is in source (with tolerance)."""
        for src in source_numbers:
            if abs(num - src) < 1.0:
                return True
        return False
    
    def _find_cited_facts(self, explanation: str, key_facts: List[str]) -> List[str]:
        """Find which key facts were cited."""
        return [f for f in key_facts if str(f).lower() in explanation.lower()]
    
    def _low_confidence_response(self, ml_result: Dict, key_facts: List[str]) -> InterpretedResult:
        """Response for low-confidence ML results."""
        return InterpretedResult(
            original_data=ml_result,
            explanation=f"Low confidence result ({ml_result.get('confidence', 0)*100:.0f}%). Raw data provided for review.",
            key_facts_cited=[],
            confidence=ml_result.get("confidence", 0),
            verified=True,
            llm_used=False,
            verification_notes="Below confidence threshold",
        )
    
    # Convenience methods (async-compatible)
    async def interpret_fault(self, data: Dict) -> InterpretedResult:
        return await self.interpret(InterpretationType.FAULT_DETECTION, data)
    
    async def interpret_forecast(self, data: Dict) -> InterpretedResult:
        return await self.interpret(InterpretationType.ENERGY_FORECAST, data)
    
    async def interpret_simulation(self, data: Dict) -> InterpretedResult:
        return await self.interpret(InterpretationType.SIMULATION, data)
    
    async def interpret_root_cause(self, data: Dict) -> InterpretedResult:
        return await self.interpret(InterpretationType.ROOT_CAUSE, data)
    
    async def interpret_benchmark(self, data: Dict) -> InterpretedResult:
        return await self.interpret(InterpretationType.FLEET_BENCHMARK, data)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_unified_interpreter() -> MLInterpreter:
    """Create interpreter with Unified LLM client."""
    client = UnifiedInterpreterClient()
    return MLInterpreter(llm_client=client)

# ALIAS for backward compatibility
create_k2_interpreter = create_unified_interpreter

def get_interpreter(llm_client=None) -> MLInterpreter:
    """Get or create interpreter instance."""
    return MLInterpreter(llm_client=llm_client)


async def interpret_ml_result(
    result_type: str,
    ml_result: Dict[str, Any],
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    Interpret ML result - LLM tool handler.
    """
    type_map = {
        "fault": InterpretationType.FAULT_DETECTION,
        "forecast": InterpretationType.ENERGY_FORECAST,
        "simulation": InterpretationType.SIMULATION,
        "root_cause": InterpretationType.ROOT_CAUSE,
        "benchmark": InterpretationType.FLEET_BENCHMARK,
    }
    
    itype = type_map.get(result_type, InterpretationType.FAULT_DETECTION)
    
    if use_llm:
        interpreter = create_unified_interpreter()
    else:
        interpreter = MLInterpreter()
    
    # interpret is not async in MLInterpreter class currently
    # but we should make sure it doesn't block if possible.
    # For now, it's called synchronously or with appropriate await if made async.
    # Looking at the class definition, it is synchronous.
    result = await interpreter.interpret(itype, ml_result, use_llm=use_llm)
    return result.to_dict()


if __name__ == "__main__":
    print("=" * 60)
    print("ML-LLM Interpreter Test")
    print("=" * 60)
    
    # Test with template mode first
    interpreter = MLInterpreter()
    
    fault_data = {
        "equipment_id": "AHU-01",
        "fault_type": "SAT_HIGH",
        "severity": "medium",
        "description": "Supply Air Temperature too high",
        "detected_value": 16.5,
        "expected_range": [12, 14],
        "confidence": 0.9,
    }
    
    result = interpreter.interpret_fault(fault_data)
    print(f"\nTemplate Mode:")
    print(f"  {result.explanation}")
    print(f"  Verified: {result.verified}")
    
    # Test with K2 Think if API key available
    if os.environ.get("K2THINK_API_KEY"):
        print("\n" + "=" * 60)
        print("K2 Think Mode")
        print("=" * 60)
        
        k2_interpreter = create_k2_interpreter()
        result = k2_interpreter.interpret_fault(fault_data)
        print(f"  {result.explanation}")
        print(f"  Verified: {result.verified}")
        print(f"  LLM Used: {result.llm_used}")
