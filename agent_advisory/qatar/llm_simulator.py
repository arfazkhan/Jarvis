"""
LLM-Enhanced Qatar Building Simulator
====================================

Extends the base QatarBuildingSimulator with "superpowers" from the UnifiedLLM.
Uses LLM reasoning to:
1. Generate realistic 'hidden' faults and cascading failures.
2. Create complex operator rationales for decisions.
3. Inject realistic sensor noise and anomalies based on weather narratives.
"""

import logging
import json
import random
from typing import List, Dict, Any, Optional
from datetime import datetime

from .simulator import QatarBuildingSimulator, SimulatedScenario
from agent_unified.llm import UnifiedLLM
from agent_bms.prompt_builder import get_ops_simulation_prompt

logger = logging.getLogger("arvis.advisory.llm_simulator")

class LLMEnhancedSimulator(QatarBuildingSimulator):
    """
    Supercharged simulator that uses LLM to generate more realistic edge cases.
    """
    
    def __init__(self, seed: Optional[int] = None):
        super().__init__(seed)
        self.llm = UnifiedLLM()
        
    async def generate_enhanced_scenario(self, building_id: str = "main") -> SimulatedScenario:
        """
        Generate a scenario where the issue and context are validated/enhanced by LLM.
        """
        # 1. Start with base scenario
        base_scenario = self.generate_scenario(building=next(b for b in self.buildings if b.id == building_id))
        
        # 2. Use LLM to 'Narrativize' and 'Complexify' the scenario
        # 2. Use LLM to 'Narrativize' and 'Complexify' the scenario
        base_scenario_text = f"""
        - Issue: {base_scenario.issue_type}
        - Equipment: {base_scenario.equipment_id}
        - Weather: {base_scenario.context['outdoor_temp_c']}C, {base_scenario.context['outdoor_humidity_pct']}% humidity
        - Building: {base_scenario.building_id}
        """
        
        prompt = get_ops_simulation_prompt(base_scenario_text)
        
        try:
            enhancements = await self.llm.ask_json([{"role": "user", "content": prompt}])
            
            # Update context with LLM 'noise' and data
            base_scenario.context.update(enhancements.get("enhanced_context", {}))
            base_scenario.context["narrative"] = enhancements.get("narrative", "")
            base_scenario.context["hidden_fault"] = enhancements.get("hidden_fault", "none")
            
        except Exception as e:
            logger.error(f"LLM enhancement failed after retries: {e}")
            # Fallback to base scenario
            
        return base_scenario

    async def generate_diverse_dataset(self, n: int) -> List[SimulatedScenario]:
        """Generate n enhanced scenarios"""
        scenarios = []
        for _ in range(n):
            # Pick random building
            b = random.choice(self.buildings)
            scenarios.append(await self.generate_enhanced_scenario(b.id))
        return scenarios
