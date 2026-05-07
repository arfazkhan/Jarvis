"""
GSAS Optimizer — Closing the Loop
===================================

GSAS shouldn't just be a reporter. It should DRIVE operations.

This optimizer:
1. Reads current GSAS gaps vs target
2. Generates actionable BMS-level recommendations
3. Prioritizes by impact potential
4. Integrates with ABI predictions
5. Tracks projected impact

Usage:
    optimizer = GSASOptimizer(gsas_reporter, bms_state)
    recommendations = await optimizer.generate_recommendations()
    
    # Or integrate with ABI
    await optimizer.hook_into_abi(abi_orchestrator)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.gsas.optimizer")


@dataclass
class GSASGap:
    """Identified gap between current and target GSAS score."""
    category: str
    criterion_id: str
    criterion_name: str
    current_points: float
    max_points: float
    gap_points: float
    gap_percentage: float
    is_bms_controllable: bool
    priority: int = 0  # Higher = more urgent
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "criterion_id": self.criterion_id,
            "criterion_name": self.criterion_name,
            "current_points": self.current_points,
            "max_points": self.max_points,
            "gap_points": round(self.gap_points, 2),
            "gap_percentage": round(self.gap_percentage, 1),
            "is_bms_controllable": self.is_bms_controllable,
            "priority": self.priority,
        }


@dataclass
class GSASRecommendation:
    """Actionable recommendation to improve GSAS score."""
    recommendation_id: str
    title: str
    description: str
    category: str
    target_criterion: str
    
    # Impact projection
    estimated_points_gain: float
    estimated_star_impact: float  # e.g., 0.2 stars
    confidence: float  # 0.0 - 1.0
    
    # Implementation
    bms_actions: List[Dict[str, Any]]  # Concrete actions
    cost_estimate: str  # "Low", "Medium", "High"
    effort_estimate: str  # "Immediate", "Week", "Month"
    
    # Tracking
    status: str = "proposed"  # proposed, accepted, implemented, verified
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "target_criterion": self.target_criterion,
            "estimated_points_gain": round(self.estimated_points_gain, 2),
            "estimated_star_impact": round(self.estimated_star_impact, 3),
            "confidence": round(self.confidence, 2),
            "bms_actions": self.bms_actions,
            "cost_estimate": self.cost_estimate,
            "effort_estimate": self.effort_estimate,
            "status": self.status,
            "created_at": self.created_at,
        }


class GSASOptimizer:
    """
    Generates GSAS-targeted recommendations from current building state.
    
    Design Principles:
    - GSAS targets are ACTIVE constraints, not passive reports
    - Every recommendation should project its GSAS impact
    - BMS operations should be scored against GSAS goals
    """
    
    # BMS-controllable criteria with direct action mappings
    BMS_CONTROLLABLE = {
        "E.1": {  # Energy Demand Performance
            "name": "Energy Demand Performance",
            "actions": [
                {
                    "type": "setpoint_optimization",
                    "description": "Optimize CHW supply temperature setpoint",
                    "params": {"equipment_type": "chiller", "setpoint": "chw_supply_temp"},
                    "impact_factor": 0.3,
                },
                {
                    "type": "schedule_optimization",
                    "description": "Reduce after-hours HVAC runtime",
                    "params": {"schedule_type": "hvac", "action": "reduce_unoccupied"},
                    "impact_factor": 0.2,
                },
                {
                    "type": "economizer_tuning",
                    "description": "Enable free cooling when outdoor conditions favorable",
                    "params": {"equipment_type": "ahu", "enable_economizer": True},
                    "impact_factor": 0.25,
                },
            ],
        },
        "E.2": {  # Energy Consumption Performance
            "name": "Energy Consumption Performance",
            "actions": [
                {
                    "type": "demand_limiting",
                    "description": "Implement demand limiting during peak hours",
                    "params": {"limit_kw": "auto", "peak_hours": [12, 18]},
                    "impact_factor": 0.35,
                },
                {
                    "type": "chiller_staging",
                    "description": "Optimize chiller staging for partial loads",
                    "params": {"strategy": "efficiency_first"},
                    "impact_factor": 0.2,
                },
            ],
        },
        "IE.1": {  # Thermal Comfort
            "name": "Thermal Comfort Performance",
            "actions": [
                {
                    "type": "supply_temp_reset",
                    "description": "Implement supply air temperature reset based on demand",
                    "params": {"equipment_type": "ahu", "reset_strategy": "demand_based"},
                    "impact_factor": 0.25,
                },
                {
                    "type": "zone_temp_optimization",
                    "description": "Fine-tune zone temperature setpoints within comfort band",
                    "params": {"temp_range_c": [22, 24]},
                    "impact_factor": 0.15,
                },
            ],
        },
        "IE.2": {  # Indoor Air Quality
            "name": "Indoor Air Quality",
            "actions": [
                {
                    "type": "ventilation_optimization",
                    "description": "Adjust outdoor air damper based on CO2 levels",
                    "params": {"control_mode": "demand_control_ventilation", "co2_setpoint_ppm": 800},
                    "impact_factor": 0.3,
                },
                {
                    "type": "filter_monitoring",
                    "description": "Monitor filter pressure drop for replacement timing",
                    "params": {"dp_threshold_pa": 400},
                    "impact_factor": 0.1,
                },
            ],
        },
        "W.1": {  # Water Consumption
            "name": "Water Consumption Performance",
            "actions": [
                {
                    "type": "cooling_tower_optimization",
                    "description": "Optimize cooling tower cycles of concentration",
                    "params": {"target_cycles": 5},
                    "impact_factor": 0.3,
                },
            ],
        },
        "MO.1": {  # Maintenance Management
            "name": "Maintenance Management",
            "actions": [
                {
                    "type": "predictive_maintenance",
                    "description": "Implement predictive maintenance schedule",
                    "params": {"use_predictions": True, "advance_days": 30},
                    "impact_factor": 0.25,
                },
                {
                    "type": "fault_detection",
                    "description": "Enable real-time fault detection alerts",
                    "params": {"sensitivity": "high"},
                    "impact_factor": 0.15,
                },
            ],
        },
    }
    
    # Priority weights for each category
    CATEGORY_WEIGHTS = {
        "E": 3.0,   # Energy - highest impact
        "IE": 2.5,  # Indoor Environment - comfort matters
        "MO": 2.0,  # Management & Operations
        "W": 1.5,   # Water
        "S": 1.0,   # Site
        "UC": 0.5,  # Urban Connectivity - less BMS controllable
        "M": 0.5,   # Materials - design-phase mostly
        "CE": 0.5,  # Cultural & Economic - hard to influence via ops
    }
    
    def __init__(
        self,
        gsas_reporter: Any,
        bms_state: Optional[Any] = None,
        target_rating: int = 4,  # Default target: 4 stars
    ):
        from agent_commercial.gsas_reporter import GSASStarRating
        
        self.gsas_reporter = gsas_reporter
        self.bms_state = bms_state
        
        # Convert int to GSASStarRating enum if needed
        if isinstance(target_rating, int):
            self.target_rating = GSASStarRating(target_rating)
        else:
            self.target_rating = target_rating
        
        self._recommendations: List[GSASRecommendation] = []
        self._implemented: List[str] = []
        self._recommendation_counter = 0
    
    async def analyze_gaps(self) -> List[GSASGap]:
        """Identify all gaps between current and target GSAS scores."""
        status = self.gsas_reporter.get_status()
        current_score = status.get("overall_score", 0.0)
        target_score = self._target_score_for_rating(self.target_rating)
        
        gaps = []
        category_scores = status.get("categories", {})
        
        for cat_code, cat_data in category_scores.items():
            achieved = cat_data.get("achieved_points", 0.0)
            maximum = cat_data.get("max_points", 0.0)
            
            if maximum <= 0:
                continue
            
            # Get criteria for this category
            criteria = self._get_criteria_for_category(cat_code)
            
            for crit_id, crit_data in criteria.items():
                crit_achieved = crit_data.get("current_points", 0.0)
                crit_max = crit_data.get("max_points", 3.0)
                crit_gap = crit_max - crit_achieved
                
                if crit_gap <= 0:
                    continue  # Already achieved
                
                # Check if BMS-controllable
                is_controllable = crit_id in self.BMS_CONTROLLABLE
                
                # Calculate priority
                category_weight = self.CATEGORY_WEIGHTS.get(cat_code, 1.0)
                priority = int(crit_gap * category_weight * 10)
                
                gaps.append(GSASGap(
                    category=cat_code,
                    criterion_id=crit_id,
                    criterion_name=crit_data.get("name", crit_id),
                    current_points=crit_achieved,
                    max_points=crit_max,
                    gap_points=crit_gap,
                    gap_percentage=(crit_gap / crit_max * 100) if crit_max > 0 else 0,
                    is_bms_controllable=is_controllable,
                    priority=priority,
                ))
        
        # Sort by priority (highest first)
        gaps.sort(key=lambda g: g.priority, reverse=True)
        return gaps
    
    async def generate_recommendations(
        self,
        max_recommendations: int = 10,
        focus_category: Optional[str] = None,
    ) -> List[GSASRecommendation]:
        """Generate prioritized recommendations to close GSAS gaps."""
        gaps = await self.analyze_gaps()
        
        # Filter by category if specified
        if focus_category:
            gaps = [g for g in gaps if g.category == focus_category]
        
        # Filter to BMS-controllable
        controllable_gaps = [g for g in gaps if g.is_bms_controllable]
        
        recommendations = []
        
        for gap in controllable_gaps[:max_recommendations]:
            recs = await self._generate_recommendations_for_gap(gap)
            recommendations.extend(recs)
        
        # Sort by estimated impact
        recommendations.sort(
            key=lambda r: r.estimated_points_gain * r.confidence,
            reverse=True,
        )
        
        self._recommendations = recommendations[:max_recommendations]
        return self._recommendations
    
    async def _generate_recommendations_for_gap(
        self,
        gap: GSASGap,
    ) -> List[GSASRecommendation]:
        """Generate specific recommendations for a single gap."""
        if gap.criterion_id not in self.BMS_CONTROLLABLE:
            return []
        
        mapping = self.BMS_CONTROLLABLE[gap.criterion_id]
        actions = mapping.get("actions", [])
        recommendations = []
        
        for action in actions:
            self._recommendation_counter += 1
            rec_id = f"GSAS-REC-{self._recommendation_counter:04d}"
            
            # Estimate impact
            base_impact = gap.gap_points * action.get("impact_factor", 0.2)
            confidence = await self._estimate_confidence(gap, action)
            estimated_points = base_impact * confidence
            
            # Estimate star impact
            current_score = self.gsas_reporter.get_status().get("overall_score", 0.0)
            target_score = self._target_score_for_rating(self.target_rating)
            star_impact = estimated_points / (target_score - current_score) if (target_score - current_score) > 0 else 0
            
            recommendations.append(GSASRecommendation(
                recommendation_id=rec_id,
                title=action.get("description", f"Improve {gap.criterion_name}"),
                description=f"Action to improve GSAS criterion {gap.criterion_id} ({gap.criterion_name}). "
                           f"Current: {gap.current_points:.1f}/{gap.max_points:.1f} points. "
                           f"Gap: {gap.gap_points:.1f} points.",
                category=gap.category,
                target_criterion=gap.criterion_id,
                estimated_points_gain=estimated_points,
                estimated_star_impact=min(star_impact, 0.5),  # Cap at 0.5 stars per action
                confidence=confidence,
                bms_actions=[{
                    "action_type": action.get("type"),
                    "params": action.get("params", {}),
                    "target_equipment": self._infer_target_equipment(action),
                }],
                cost_estimate=self._estimate_cost(action),
                effort_estimate=self._estimate_effort(action),
            ))
        
        return recommendations
    
    async def _estimate_confidence(
        self,
        gap: GSASGap,
        action: Dict[str, Any],
    ) -> float:
        """Estimate confidence that this action will achieve the projected impact."""
        base_confidence = 0.7  # Default
        
        # Adjust based on BMS state availability
        if self.bms_state:
            # Check if relevant equipment exists
            target_eq = self._infer_target_equipment(action)
            if target_eq and await self._equipment_exists(target_eq):
                base_confidence += 0.1
        
        # Adjust based on action type
        high_confidence_types = {"setpoint_optimization", "schedule_optimization", "demand_limiting"}
        if action.get("type") in high_confidence_types:
            base_confidence += 0.1
        
        return min(base_confidence, 0.95)
    
    async def _equipment_exists(self, equipment_type: str) -> bool:
        """Check if equipment type exists in BMS state."""
        if not self.bms_state:
            return False
        # Simplified check - in real implementation, query BMS state
        return True
    
    def _infer_target_equipment(self, action: Dict[str, Any]) -> Optional[str]:
        """Infer target equipment type from action."""
        params = action.get("params", {})
        if "equipment_type" in params:
            return params["equipment_type"]
        if "chiller" in action.get("description", "").lower():
            return "chiller"
        if "ahu" in action.get("description", "").lower():
            return "ahu"
        if "cooling_tower" in action.get("description", "").lower():
            return "cooling_tower"
        return None
    
    def _estimate_cost(self, action: Dict[str, Any]) -> str:
        """Estimate implementation cost."""
        low_cost_types = {"setpoint_optimization", "schedule_optimization", "zone_temp_optimization"}
        medium_cost_types = {"demand_limiting", "economizer_tuning", "supply_temp_reset"}
        
        action_type = action.get("type", "")
        if action_type in low_cost_types:
            return "Low"
        elif action_type in medium_cost_types:
            return "Medium"
        else:
            return "Medium"
    
    def _estimate_effort(self, action: Dict[str, Any]) -> str:
        """Estimate implementation effort."""
        immediate_types = {"setpoint_optimization", "zone_temp_optimization", "demand_limiting"}
        week_types = {"schedule_optimization", "economizer_tuning", "supply_temp_reset"}
        
        action_type = action.get("type", "")
        if action_type in immediate_types:
            return "Immediate"
        elif action_type in week_types:
            return "Week"
        else:
            return "Week"
    
    def _get_criteria_for_category(self, category_code: str) -> Dict[str, Dict[str, Any]]:
        """Get all criteria for a category from GSAS reporter."""
        criteria = {}
        
        if not hasattr(self.gsas_reporter, "criteria"):
            return criteria
        
        for crit_id, crit in self.gsas_reporter.criteria.items():
            if crit.category.value == category_code:
                criteria[crit_id] = {
                    "name": crit.name,
                    "current_points": crit.current_points,
                    "max_points": crit.max_points,
                    "status": crit.status.value,
                }
        
        return criteria
    
    def _target_score_for_rating(self, rating) -> float:
        """Get target score for desired star rating."""
        from agent_commercial.gsas_reporter import GSASStarRating
        
        # Handle both enum and int
        if isinstance(rating, GSASStarRating):
            rating_val = rating.value
        else:
            rating_val = int(rating)
        
        # GSAS star rating thresholds
        thresholds = {
            1: 0.5,
            2: 1.0,
            3: 1.5,
            4: 2.0,
            5: 2.5,
            6: 2.75,
        }
        return thresholds.get(rating_val, 2.0)
    
    async def hook_into_abi(self, abi_orchestrator: Any) -> None:
        """
        Hook GSAS optimizer into ABI orchestrator.
        
        This ensures:
        - Predictions consider GSAS targets
        - Recommendations are scored against GSAS impact
        - ABI loop validates GSAS improvement
        """
        if not hasattr(abi_orchestrator, "register_optimizer"):
            logger.warning("ABI orchestrator does not support optimizer registration")
            return
        
        abi_orchestrator.register_optimizer("gsas", self)
        logger.info("GSAS optimizer hooked into ABI loop")
    
    async def score_action_for_gsas(
        self,
        action: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Score a proposed action for its GSAS impact."""
        action_type = action.get("action_type", "")
        
        # Find matching criteria
        matching_criteria = []
        estimated_gain = 0.0
        
        for crit_id, mapping in self.BMS_CONTROLLABLE.items():
            for act in mapping.get("actions", []):
                if act.get("type") == action_type:
                    matching_criteria.append(crit_id)
                    # Estimate gain based on current gap
                    gaps = await self.analyze_gaps()
                    for gap in gaps:
                        if gap.criterion_id == crit_id:
                            estimated_gain += gap.gap_points * act.get("impact_factor", 0.2)
        
        return {
            "action_type": action_type,
            "matching_criteria": matching_criteria,
            "estimated_points_gain": round(estimated_gain, 2),
            "gsas_aligned": len(matching_criteria) > 0,
        }
    
    def mark_implemented(self, recommendation_id: str) -> None:
        """Mark a recommendation as implemented."""
        self._implemented.append(recommendation_id)
        for rec in self._recommendations:
            if rec.recommendation_id == recommendation_id:
                rec.status = "implemented"
                logger.info(f"GSAS recommendation {recommendation_id} marked as implemented")
    
    def get_status(self) -> Dict[str, Any]:
        """Get optimizer status."""
        proposed = [r for r in self._recommendations if r.status == "proposed"]
        implemented = [r for r in self._recommendations if r.status == "implemented"]
        
        total_estimated_gain = sum(r.estimated_points_gain for r in implemented)
        
        return {
            "target_rating": self.target_rating,
            "total_recommendations": len(self._recommendations),
            "proposed_count": len(proposed),
            "implemented_count": len(implemented),
            "estimated_points_implemented": round(total_estimated_gain, 2),
            "recommendations": [r.to_dict() for r in self._recommendations[:5]],
        }
