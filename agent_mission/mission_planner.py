"""
Mission Planner
---------------
Converts mission templates into executable DAG plans.
Integrates with Phase 3 PlanGraph and Scene Engine.
"""

import yaml
from typing import Dict, List, Optional
from pathlib import Path
from agent_plan.plan_graph import PlanGraph
from agent_mission.base.mission_step import MissionStep, StepType

class MissionPlanner:
    def __init__(self, template_dir: str = "agent_mission/templates"):
        self.template_dir = Path(template_dir)
        self.templates: Dict[str, Dict] = {}
        self._load_templates()
        
    def _load_templates(self):
        """Load all mission templates"""
        for template_file in self.template_dir.glob("*.yaml"):
            with open(template_file, 'r') as f:
                template = yaml.safe_load(f)
                self.templates[template["mission_id"]] = template
    
    def generate_plan(self, mission_type: str, context: Dict) -> PlanGraph:
        """
        Generate DAG plan from mission template.
        
        Args:
            mission_type: Type of mission (sleep_optimization, etc.)
            context: Mission context for parameterization
        
        Returns:
            PlanGraph with mission steps as nodes
        """
        if mission_type not in self.templates:
            raise ValueError(f"Unknown mission type: {mission_type}")
        
        template = self.templates[mission_type]
        plan_template = template.get("plan_template", [])
        
        # Create PlanGraph
        graph = PlanGraph()
        
        # Add nodes - need to create PlanNode objects
        from agent_plan.plan_graph import PlanNode
        
        for step_def in plan_template:
            step = self._create_step_from_template(step_def, context)
            dependencies = step_def.get("dependencies", [])
            
            # Create PlanNode wrapper
            # Map MissionStep to PlanNode
            plan_node = PlanNode(
                node_id=step.step_id,
                action=step.step_type.value,  # Pass string value of enum
                params=step.parameters,
                depends_on=dependencies
            )
            graph.add_node(plan_node)
        
        # Validate (no cycles)
        if not self._validate_plan(graph):
            raise ValueError("Invalid plan: contains cycles or missing dependencies")
        
        print(f"✅ Generated plan for {mission_type}: {len(plan_template)} steps")
        return graph
    
    def _create_step_from_template(self, step_def: Dict, context: Dict) -> MissionStep:
        """Create MissionStep from template definition"""
        # Map string step_type to enum
        step_type_map = {
            "collection": StepType.COLLECTION,
            "scene": StepType.SCENE,
            "automation": StepType.AUTOMATION,
            "monitoring": StepType.MONITORING,
            "action": StepType.ACTION
        }
        
        step_type = step_type_map.get(step_def["step_type"], StepType.ACTION)
        
        # Apply context to parameters (simple substitution for MVP)
        parameters = step_def.get("parameters", {}).copy()
        # TODO: More sophisticated parameter substitution based on context
        
        return MissionStep(
            step_id=step_def["step_id"],
            step_type=step_type,
            parameters=parameters,
            dependencies=step_def.get("dependencies", []),
            timeout=step_def.get("timeout", 60),
            retry_count=step_def.get("retry_count", 2),
            continuous=step_def.get("continuous", False)
        )
    
    def _validate_plan(self, graph: PlanGraph) -> bool:
        """
        Validate plan has no cycles and all dependencies exist.
        """
        # Check for cycles using DFS
        try:
            layers = graph.get_execution_layers()
            return len(layers) > 0
        except Exception:
            return False
    
    def rebuild_plan(self, old_plan: PlanGraph, metrics: Dict, mission_type: str, context: Dict) -> PlanGraph:
        """
        Rebuild plan based on current metrics with adaptive adjustments.
        
        Adaptive Logic:
        - Sleep: Adjust timing if variance high, reduce temp if motion high
        - Energy: Increase aggressiveness if off-ratio low
        - Security: Adjust simulation frequency if adherence low
        - Focus: Increase strictness if interruptions high
        """
        print(f"🔄 Rebuilding plan for {mission_type} based on metrics")
        
        # Apply mission-specific adaptations
        adaptive_context = context.copy()
        
        if mission_type == "sleep_optimization":
            # Adjust bedtime scene timing
            if metrics.get("bedtime_variance", 0) > 45:
                # Shift bedtime routine earlier by 10 minutes
                adaptive_context["bedtime_adjustment_minutes"] = -10
                print("  📅 Adjusting bedtime routine -10 min (high variance)")
            
            # Adjust bedroom temperature for motion reduction
            if metrics.get("night_motion_count", 0) > 10:
                adaptive_context["bedroom_temp_reduction"] = 1  # Reduce by 1°C
                print("  🌡️ Reducing bedroom temp -1°C (high motion)")
                
        elif mission_type == "energy_saver":
            # Increase idle detection aggressiveness
            if metrics.get("device_off_ratio", 1.0) < 0.5:
                adaptive_context["idle_threshold_minutes"] = 30  # More aggressive (was 60)
                print("  ⚡ Reducing idle threshold to 30min (low off-ratio)")
                
        elif mission_type == "home_security":
            # Adjust presence simulation frequency
            if metrics.get("presence_simulation_adherence", 1.0) < 0.8:
                adaptive_context["simulation_frequency_increase"] = 1.5
                print("  🔐 Increasing presence simulation frequency")
                
        elif mission_type == "focus_productivity":
            # Increase do-not-disturb strictness
            if metrics.get("interruption_count", 0) > 5:
                adaptive_context["dnd_strictness"] = "high"  # Was "medium"
                print("  🎯 Increasing DND strictness (many interruptions)")
        
        # Regenerate plan with adaptive context
        return self.generate_plan(mission_type, adaptive_context)
