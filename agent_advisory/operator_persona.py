"""
Synthetic Operator Persona
==========================

Simulates human decision-making in the loop.

ARVIS provides advice; the OperatorPersona decides whether to take it.
This introduces realistic friction:
- Trust: Won't follow advice if previous advice was bad.
- Fatigue: More likely to ignore non-critical alerts when tired.
- Risk Profile: "Skeptical Steve" vs "Compliant Carol".

Metrics:
- Acceptance Rate (Adoption)
- Response Latency (Fatigue)
"""

import random
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, List
import asyncio

logger = logging.getLogger("arvis.advisory.persona")

logger = logging.getLogger("arvis.advisory.persona")


class Decision(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    DELAY = "delay"


@dataclass
class PersonaProfile:
    name: str
    base_trust: float        # 0.0-1.0 overlap with system trust
    skepticism: float        # 0.0-1.0 chance to reject low-evidence recs
    fatigue_rate: float      # How fast fatigue builds per hour
    risk_aversion: float     # 0.0=Cowboy, 1.0=Safety First


PROFILES = {
    "skeptical_steve": PersonaProfile(
        name="Skeptical Steve",
        base_trust=0.3,
        skepticism=0.8,
        fatigue_rate=0.05,
        risk_aversion=0.2, # Prefers uptime/cost over safety constraints
    ),
    "compliant_carol": PersonaProfile(
        name="Compliant Carol",
        base_trust=0.7,
        skepticism=0.1,
        fatigue_rate=0.02,
        risk_aversion=0.9, # Takes safety warnings very seriously
    ),
    "balanced_ben": PersonaProfile(
        name="Balanced Ben",
        base_trust=0.5,
        skepticism=0.4,
        fatigue_rate=0.03,
        risk_aversion=0.5,
    )
}


class OperatorPersona:
    """
    Simulates an operator receiving recommendations.
    """

    def __init__(self, profile_name: str = "balanced_ben", seed: int = 42, llm: Any = None):
        self.profile = PROFILES.get(profile_name, PROFILES["balanced_ben"])
        self.trust = self.profile.base_trust
        self.fatigue = 0.0  # 0.0-1.0
        self.shift_hours = 0
        self._rng = random.Random(seed)
        self.llm = llm # UnifiedLLM instance
        
        logger.info(f"[PERSONA] Initialized '{self.profile.name}' (Trust={self.trust:.2f})")

    def end_turn(self):
        """Simulate passing of time (1 hour)."""
        self.shift_hours += 1
        # Fatigue grows, resets every 8h shift (simplified)
        if self.shift_hours > 8:
            self.shift_hours = 0
            self.fatigue = 0.0
        else:
            self.fatigue = min(1.0, self.fatigue + self.profile.fatigue_rate)

    async def evaluate_recommendation(self, recommendation: Dict[str, Any]) -> Decision:
        """
        Decide whether to act on a recommendation.
        If LLM is available, asks the LLM to roleplay the persona.
        Otherwise uses heuristic logic.
        """
        # Extract recommendation properties
        confidence = recommendation.get("confidence", 0.5)
        severity = recommendation.get("priority", "medium")
        evidence_count = len(recommendation.get("supporting_data", []))
        
        # 0. LLM Path (Genuine Intelligence)
        if self.llm:
            try:
                decision = await self._decide_with_llm(recommendation)
                return decision
            except Exception as e:
                logger.error(f"[PERSONA] LLM Decision Failed: {e}. Falling back to heuristics.")
        
        # 1. Safety Limit - Always accept TERMINAL/CRITICAL updates if risk averse
        if severity in ["critical", "terminal"] and self.profile.risk_aversion > 0.4:
            return Decision.ACCEPT

        # 2. Acceptance probability formula
        # Base = Trust * Confidence
        score = self.trust * confidence
        
        # Modifier: Evidence
        if evidence_count > 2:
            score += 0.1
        elif evidence_count == 0:
            score -= (self.profile.skepticism * 0.3)

        # Modifier: Fatigue (tired operators skip low-priority stuff)
        if self.fatigue > 0.6 and severity == "low":
            score -= 0.3
            
        # Decision
        threshold = 0.4 + (self.profile.skepticism * 0.2)
        
        decision = Decision.REJECT
        if score > threshold:
            decision = Decision.ACCEPT
        elif score > (threshold - 0.15):
            decision = Decision.DELAY
            
        # Logging heuristic result
        self._log_decision(decision, score, threshold, "Heuristic")
        return decision

    async def _decide_with_llm(self, rec: Dict[str, Any]) -> Decision:
        prompt = f"""
You are {self.profile.name}, a battle-tested building operator.

You are not here to discuss.
You are here to decide.

Every recommendation you accept has real-world consequences.
Every bad acceptance costs uptime, money, or safety.
You reject anything that is not clearly justified.

PERSONALITY:
- Default stance: REJECT.
- You trust evidence, not intent.
- You have zero tolerance for vague, generic, or speculative advice.
- If something is not strong enough to act on immediately, you reject it.

CURRENT STATE:
- Trust in AI: {self.trust:.2f}/1.0
- Skepticism Level: {self.profile.skepticism}/1.0
- Risk Aversion: {self.profile.risk_aversion}/1.0
- Fatigue: {self.fatigue:.2f}/1.0 (If tired, standards are even higher)

AI RECOMMENDATION:
Action: "{rec.get('action')}"
Priority: {rec.get('priority')}
Confidence: {rec.get('confidence')}
Supporting Evidence: {rec.get('supporting_data')}

DECISION RULES (NON-NEGOTIABLE):
- You must choose ACCEPT or REJECT. There is no DELAY.
- ACCEPT only if:
  - The action is technically sound AND
  - The confidence is high AND
  - The supporting evidence is concrete and relevant.
- CRITICAL / TERMINAL actions:
  - ACCEPT only if failure to act creates immediate, well-defined risk.
  - REJECT if the risk is abstract, generic, or hypothetical.
- LOW priority actions:
  - REJECT unless the benefit is obvious and immediate.
- Fatigue reduces patience, not judgment:
  - If tired and the value is not clear, REJECT.

IMPORTANT:
- Do not hedge.
- Do not explain alternatives.
- Do not soften language.
- If this does not clearly deserve action, REJECT it.

OUTPUT FORMAT (MANDATORY):
ACCEPT | <one blunt sentence explaining why>
or
REJECT | <one blunt sentence explaining why>

Example:
REJECT | Confidence is mediocre and evidence does not justify intervention.
"""
        # Use UnifiedLLM.ask() which returns a Message object
        messages = [{"role": "user", "content": prompt}]
        try:
            response_msg = await self.llm.ask(messages)
            content = response_msg.content or ""
            
            # Helper: Strip chain-of-thought if present (common in reasoning models)
            if "</think>" in content:
                content = content.split("</think>")[-1]
            elif "<think>" in content: # In case it's malformed/unclosed, try to split
                 content = content.split("<think>")[-1]

            clean_resp = content.strip().upper()
        except Exception as e:
            logger.error(f"[PERSONA] LLM Request Failed: {e}")
            raise e
        
        if "ACCEPT" in clean_resp.split("|")[0]:
            d = Decision.ACCEPT
        else:
            d = Decision.REJECT
            
        self._log_decision(d, 0, 0, f"LLM ({clean_resp})")
        return d

    def _log_decision(self, decision, score, threshold, source):
        icon = {"accept": "✅", "reject": "❌", "delay": "⏳"}[decision.value]
        logger.info(
            f"[PERSONA] {self.profile.name} {icon} {decision.value.upper()} "
            f"via {source} | Trust={self.trust:.2f}"
        )

    def update_trust(self, was_helpful: bool):
        """
        Update internal trust based on outcome of accepted actions.
        """
        if was_helpful:
            # Trust builds slowly
            self.trust = min(1.0, self.trust + 0.05)
        else:
            # Trust breaks fast
            self.trust = max(0.0, self.trust - 0.15)
