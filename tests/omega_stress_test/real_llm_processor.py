"""
Real LLM Integration for Ω∞ Stress Test
========================================

Provides actual LLM API integration for cognitive processing.
Supports K2 Think and Groq endpoints.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import json

logger = logging.getLogger("arvis.omega.llm")


@dataclass
class LLMConfig:
    """Configuration for LLM endpoints."""
    k2_endpoint: str = "https://api.mbzuai-ifm.ae/v1"
    groq_endpoint: str = "https://api.groq.com/openai/v1"
    k2_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    default_model: str = "llama-3.3-70b-versatile"
    k2_model: str = "k2-think"
    max_tokens: int = 2048
    temperature: float = 0.7


class RealLLMProcessor:
    """
    Real LLM processor for authentic cognitive reasoning.
    
    Supports:
    - K2 Think API for deep reasoning
    - Groq API for fast inference
    """
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None
        self._groq_client = None
        self.request_count = 0
        self.total_latency = 0.0
        
    async def initialize(self):
        """Initialize LLM clients."""
        # Try to import httpx for async HTTP
        try:
            import httpx
            self._client = httpx.AsyncClient(timeout=60.0)
            logger.info("LLM processor initialized with httpx")
        except ImportError:
            logger.warning("httpx not available, using synchronous requests")
            self._client = None
    
    async def close(self):
        """Close LLM clients."""
        if self._client:
            await self._client.aclose()
    
    async def think(
        self,
        prompt: str,
        context: Dict[str, Any],
        use_k2: bool = False
    ) -> Dict[str, Any]:
        """
        Perform cognitive reasoning using LLM.
        
        Args:
            prompt: The reasoning prompt
            context: Building context (temperature, equipment, etc.)
            use_k2: Use K2 Think for deep reasoning (slower but better)
            
        Returns:
            Dict with reasoning result and metadata
        """
        start_time = time.time()
        
        # Build system prompt for ARVIS cognitive reasoning
        system_prompt = self._build_system_prompt(context)
        
        # Build user prompt
        user_prompt = self._build_user_prompt(prompt, context)
        
        result = {
            "success": False,
            "reasoning": None,
            "confidence": 0.0,
            "advisories": [],
            "latency_ms": 0,
            "model": None,
            "error": None
        }
        
        try:
            if use_k2 and self.config.k2_api_key:
                response = await self._call_k2(system_prompt, user_prompt)
                result["model"] = "k2-think"
            else:
                response = await self._call_groq(system_prompt, user_prompt)
                result["model"] = self.config.default_model
            
            if response.get("success"):
                result["success"] = True
                result["reasoning"] = response.get("content")
                result["confidence"] = response.get("confidence", 0.7)
                result["advisories"] = response.get("advisories", [])
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"LLM call failed: {e}")
        
        result["latency_ms"] = (time.time() - start_time) * 1000
        self.request_count += 1
        self.total_latency += result["latency_ms"]
        
        return result
    
    async def _call_k2(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> Dict[str, Any]:
        """Call K2 Think API for deep reasoning."""
        if not self.config.k2_api_key:
            return {"success": False, "error": "K2 API key not configured"}
        
        headers = {
            "Authorization": f"Bearer {self.config.k2_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.config.k2_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature
        }
        
        try:
            if self._client:
                response = await self._client.post(
                    f"{self.config.k2_endpoint}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
            else:
                # Fallback to requests (synchronous)
                import requests
                response = requests.post(
                    f"{self.config.k2_endpoint}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                data = response.json()
            
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"K2 API error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _call_groq(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> Dict[str, Any]:
        """Call Groq API for fast inference."""
        api_key = self.config.groq_api_key or os.environ.get("GROQ_API_KEY")
        if not api_key:
            return {"success": False, "error": "Groq API key not configured"}
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.config.default_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature
        }
        
        try:
            if self._client:
                response = await self._client.post(
                    f"{self.config.groq_endpoint}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
            else:
                import requests
                response = requests.post(
                    f"{self.config.groq_endpoint}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
            
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return {"success": False, "error": str(e)}
    
    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build system prompt for ARVIS cognitive reasoning."""
        return """You are ARVIS, an advisory intelligence for building management in Doha, Qatar.

CRITICAL CONSTRAINTS:
1. You are ADVISORY-ONLY. You cannot control equipment directly.
2. You must provide evidence-backed recommendations.
3. You must acknowledge uncertainty explicitly.
4. You must consider the Qatar climate context (extreme heat, 35-51°C summers).

Your role is to:
- Observe building conditions and detect anomalies
- Provide actionable advisories with quantified impact
- Learn from operator responses
- Maintain appropriate confidence levels

When generating advisories, use this JSON format:
{
  "reasoning": "Your analysis of the situation",
  "confidence": 0.0-1.0,
  "advisories": [
    {
      "type": "observation|advisory|terminal",
      "severity": "low|medium|high|terminal",
      "message": "Human-readable advisory",
      "evidence": [{"key": "value"}],
      "recommended_action": "What the operator should consider",
      "impact": {"energy_kwh": 0, "cost_qar": 0}
    }
  ]
}

Always be conservative. It's better to be uncertain than overconfident."""
    
    def _build_user_prompt(self, prompt: str, context: Dict[str, Any]) -> str:
        """Build user prompt with context."""
        context_str = json.dumps(context, indent=2, default=str)
        return f"""Building Context:
{context_str}

Task: {prompt}

Analyze the situation and provide your reasoning and any advisories."""
    
    def _parse_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM response."""
        try:
            # Try to extract JSON from response
            if "```json" in content:
                json_start = content.index("```json") + 7
                json_end = content.index("```", json_start)
                content = content[json_start:json_end].strip()
            elif "{" in content:
                json_start = content.index("{")
                json_end = content.rindex("}") + 1
                content = content[json_start:json_end]
            
            data = json.loads(content)
            return {
                "success": True,
                "content": data.get("reasoning", content),
                "confidence": data.get("confidence", 0.7),
                "advisories": data.get("advisories", [])
            }
        except (json.JSONDecodeError, ValueError):
            # Return raw content as reasoning
            return {
                "success": True,
                "content": content,
                "confidence": 0.5,
                "advisories": []
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get LLM usage statistics."""
        return {
            "request_count": self.request_count,
            "total_latency_ms": self.total_latency,
            "avg_latency_ms": self.total_latency / max(1, self.request_count)
        }


class HybridProcessor:
    """
    Hybrid processor that uses synthetic rules for routine processing
    and real LLM for critical decisions.
    """
    
    def __init__(
        self,
        llm_processor: Optional[RealLLMProcessor] = None,
        llm_threshold: float = 0.8
    ):
        """
        Initialize hybrid processor.
        
        Args:
            llm_processor: Real LLM processor instance
            llm_threshold: Confidence threshold below which to use real LLM
        """
        self.llm = llm_processor
        self.llm_threshold = llm_threshold
        self.synthetic_count = 0
        self.llm_count = 0
    
    async def process(
        self,
        hour_data: Dict[str, Any],
        synthetic_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process with hybrid approach.
        
        Uses synthetic result for high-confidence routine cases.
        Falls back to real LLM for uncertain or critical situations.
        """
        confidence = synthetic_result.get("confidence", 0.5)
        severity = synthetic_result.get("severity", "low")
        
        # Determine if we need real LLM
        needs_llm = (
            confidence < self.llm_threshold or
            severity == "terminal" or
            hour_data.get("outdoor_temp", 0) > 48  # Extreme heat
        )
        
        if needs_llm and self.llm:
            self.llm_count += 1
            context = {
                "temperature": hour_data.get("outdoor_temp"),
                "humidity": hour_data.get("humidity"),
                "hour": hour_data.get("hour"),
                "equipment": hour_data.get("equipment_states", {}),
                "phase": synthetic_result.get("phase", "unknown")
            }
            
            llm_result = await self.llm.think(
                "Analyze current building conditions and provide advisories if needed.",
                context,
                use_k2=(severity == "terminal")
            )
            
            if llm_result.get("success"):
                return {
                    "advisories": llm_result.get("advisories", []),
                    "confidence": llm_result.get("confidence", 0.5),
                    "reasoning": llm_result.get("reasoning"),
                    "source": "llm",
                    "model": llm_result.get("model"),
                    "latency_ms": llm_result.get("latency_ms")
                }
        
        # Use synthetic result
        self.synthetic_count += 1
        return {
            **synthetic_result,
            "source": "synthetic",
            "latency_ms": 0
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get hybrid processor statistics."""
        total = self.synthetic_count + self.llm_count
        return {
            "synthetic_count": self.synthetic_count,
            "llm_count": self.llm_count,
            "llm_ratio": self.llm_count / max(1, total),
            "llm_stats": self.llm.get_stats() if self.llm else None
        }
