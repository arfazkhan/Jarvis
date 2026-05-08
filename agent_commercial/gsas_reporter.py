"""
GSAS Compliance Reporter
========================

Qatar's Global Sustainability Assessment System (GSAS) compliance tracking
and reporting for commercial buildings.

GSAS Categories Covered:
- UC: Urban Connectivity
- S: Site
- E: Energy
- W: Water
- M: Materials
- IE: Indoor Environment
- CE: Cultural & Economic Value
- MO: Management & Operations

This module:
1. Tracks compliance metrics across categories
2. Calculates scores based on GSAS v2.1 methodology
3. Generates compliance reports (PDF/HTML)
4. Provides improvement recommendations
5. Projects star rating (1-6 stars)

Reference: GSAS v2.1 Technical Guidelines (GORD)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import json

logger = logging.getLogger("arvis.bms.gsas")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class GSASCategory(Enum):
    """GSAS assessment categories"""
    URBAN_CONNECTIVITY = "UC"
    SITE = "S"
    ENERGY = "E"
    WATER = "W"
    MATERIALS = "M"
    INDOOR_ENVIRONMENT = "IE"
    CULTURAL_ECONOMIC = "CE"
    MANAGEMENT_OPERATIONS = "MO"


class GSASStarRating(Enum):
    """GSAS certification levels"""
    ONE_STAR = 1      # 0.5 - 1.0
    TWO_STAR = 2      # 1.0 - 1.5
    THREE_STAR = 3    # 1.5 - 2.0
    FOUR_STAR = 4     # 2.0 - 2.5
    FIVE_STAR = 5     # 2.5 - 2.75
    SIX_STAR = 6      # 2.75 - 3.0


class CriterionStatus(Enum):
    """Status of a criterion"""
    NOT_APPLICABLE = "not_applicable"
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    ACHIEVED = "achieved"
    EXCEEDS = "exceeds"


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GSASCriterion:
    """Individual GSAS criterion"""
    criterion_id: str           # e.g., "E.1", "W.3"
    name: str                   # e.g., "Energy Demand Performance"
    category: GSASCategory
    
    # Scoring
    max_points: float = 3.0
    current_points: float = 0.0
    weight: float = 1.0
    
    # Status
    status: CriterionStatus = CriterionStatus.NOT_STARTED
    
    # Evidence
    evidence: List[str] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)
    
    # BMS-measurable
    is_bms_measurable: bool = False  # Can be tracked via BMS data
    bms_metric_ids: List[str] = field(default_factory=list)
    
    @property
    def score_percentage(self) -> float:
        """Score as percentage of max"""
        return (self.current_points / self.max_points * 100) if self.max_points > 0 else 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "name": self.name,
            "category": self.category.value,
            "max_points": self.max_points,
            "current_points": self.current_points,
            "score_percentage": round(self.score_percentage, 1),
            "status": self.status.value,
            "is_bms_measurable": self.is_bms_measurable,
        }


@dataclass
class GSASCategoryScore:
    """Aggregated score for a category"""
    category: GSASCategory
    category_name: str
    
    # Scores
    achieved_points: float = 0.0
    max_points: float = 0.0
    weighted_score: float = 0.0
    
    # Criteria
    total_criteria: int = 0
    achieved_criteria: int = 0
    
    # Status
    on_track: bool = True
    needs_attention: List[str] = field(default_factory=list)
    
    @property
    def percentage(self) -> float:
        return (self.achieved_points / self.max_points * 100) if self.max_points > 0 else 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "category_name": self.category_name,
            "achieved_points": round(self.achieved_points, 2),
            "max_points": round(self.max_points, 2),
            "percentage": round(self.percentage, 1),
            "weighted_score": round(self.weighted_score, 3),
            "on_track": self.on_track,
            "needs_attention": self.needs_attention,
        }


@dataclass
class GSASReport:
    """Complete GSAS assessment report"""
    report_id: str = field(default_factory=lambda: f"GSAS-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    building_id: str = ""
    building_name: str = ""
    
    # Assessment period
    assessment_date: datetime = field(default_factory=datetime.now)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    
    # Scores
    overall_score: float = 0.0          # 0.0 - 3.0
    star_rating: GSASStarRating = GSASStarRating.ONE_STAR
    target_rating: GSASStarRating = GSASStarRating.THREE_STAR
    
    # Category breakdown
    category_scores: Dict[str, GSASCategoryScore] = field(default_factory=dict)
    
    # Criteria
    criteria: Dict[str, GSASCriterion] = field(default_factory=dict)
    
    # Analysis
    strengths: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    
    # Projections
    projected_score_30d: float = 0.0
    projected_rating_30d: Optional[GSASStarRating] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "building_id": self.building_id,
            "building_name": self.building_name,
            "assessment_date": self.assessment_date.isoformat(),
            "overall_score": round(self.overall_score, 3),
            "star_rating": self.star_rating.value,
            "target_rating": self.target_rating.value,
            "category_scores": {k: v.to_dict() for k, v in self.category_scores.items()},
            "strengths": self.strengths,
            "improvements": self.improvements,
            "recommendations": self.recommendations,
        }


@dataclass
class GSASOperationalImpact:
    """GSAS impact estimate for an operational recommendation."""
    category: str
    criteria: List[str]
    target_delta: float
    impact_score: float
    confidence: float
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "criteria": self.criteria,
            "target_delta": round(self.target_delta, 3),
            "impact_score": round(self.impact_score, 3),
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
        }


# ═══════════════════════════════════════════════════════════════════════════
# GSAS REPORTER
# ═══════════════════════════════════════════════════════════════════════════

class GSASReporter:
    """
    GSAS compliance tracking and reporting.
    
    Integrates with BMS data to automatically track energy, water, and
    indoor environment metrics that contribute to GSAS scoring.
    
    Example:
        >>> reporter = GSASReporter(building_id="QNB-TOWER-01")
        >>> reporter.initialize_criteria()
        >>> reporter.update_from_bms(energy_data, water_data, iaq_data)
        >>> report = reporter.generate_report()
        >>> print(f"Current rating: {report.star_rating.value} stars")
    """
    
    # GSAS v2.1 category weights (approximate)
    CATEGORY_WEIGHTS = {
        GSASCategory.ENERGY: 0.24,
        GSASCategory.WATER: 0.16,
        GSASCategory.INDOOR_ENVIRONMENT: 0.16,
        GSASCategory.SITE: 0.10,
        GSASCategory.MATERIALS: 0.14,
        GSASCategory.MANAGEMENT_OPERATIONS: 0.10,
        GSASCategory.URBAN_CONNECTIVITY: 0.05,
        GSASCategory.CULTURAL_ECONOMIC: 0.05,
    }
    
    # Star rating thresholds
    STAR_THRESHOLDS = [
        (0.5, GSASStarRating.ONE_STAR),
        (1.0, GSASStarRating.TWO_STAR),
        (1.5, GSASStarRating.THREE_STAR),
        (2.0, GSASStarRating.FOUR_STAR),
        (2.5, GSASStarRating.FIVE_STAR),
        (2.75, GSASStarRating.SIX_STAR),
    ]

    OPERATIONAL_RECOMMENDATION_MAP = {
        GSASCategory.ENERGY: {
            "criteria": ["E.1", "E.2", "E.3", "E.5", "E.6", "MO.2"],
            "keywords": [
                "energy", "kwh", "kw", "tariff", "peak", "chiller", "ahu",
                "hvac", "schedule", "sequencing", "lighting", "overcooling",
                "setback", "after-hours", "after hours", "efficiency",
            ],
        },
        GSASCategory.WATER: {
            "criteria": ["W.1", "W.3"],
            "keywords": ["water", "m3", "meter", "leak", "flow", "irrigation"],
        },
        GSASCategory.INDOOR_ENVIRONMENT: {
            "criteria": ["IE.1", "IE.2"],
            "keywords": [
                "comfort", "temperature", "thermal", "humidity", "co2",
                "iaq", "ventilation", "occupant", "complaint",
            ],
        },
        GSASCategory.MANAGEMENT_OPERATIONS: {
            "criteria": ["MO.1", "MO.2", "MO.4"],
            "keywords": [
                "maintenance", "pm", "commissioning", "calibration", "fault",
                "alarm", "documentation", "evidence", "verify", "operator",
            ],
        },
    }
    
    def __init__(
        self,
        building_id: str = "default",
        building_name: str = "Commercial Building",
        target_rating: GSASStarRating = GSASStarRating.THREE_STAR,
    ):
        self.building_id = building_id
        self.building_name = building_name
        self.target_rating = target_rating
        
        # Criteria storage
        self.criteria: Dict[str, GSASCriterion] = {}
        
        # Historical data for trend analysis
        self.history: List[Dict[str, Any]] = []
        
        # BMS data references
        self.energy_baseline_kwh: float = 0.0
        self.water_baseline_m3: float = 0.0
        
        logger.info(f"GSASReporter initialized for {building_id}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def initialize_criteria(self) -> None:
        """
        Initialize all GSAS criteria with default values.
        
        Based on GSAS v2.1 for Commercial Buildings.
        """
        # ─────────────────────────────────────────────────────────────────
        # ENERGY (E) - 24% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("E.1", "Energy Demand Performance", GSASCategory.ENERGY,
                           max_points=3.0, is_bms_measurable=True,
                           bms_metric_ids=["energy_consumption", "energy_baseline"])
        self._add_criterion("E.2", "Primary Energy & CO2", GSASCategory.ENERGY,
                           max_points=3.0, is_bms_measurable=True)
        self._add_criterion("E.3", "Energy Monitoring", GSASCategory.ENERGY,
                           max_points=2.0, is_bms_measurable=True,
                           bms_metric_ids=["meter_count", "submetering"])
        self._add_criterion("E.4", "Renewable Energy", GSASCategory.ENERGY,
                           max_points=3.0)
        self._add_criterion("E.5", "District Cooling", GSASCategory.ENERGY,
                           max_points=2.0, is_bms_measurable=True)
        self._add_criterion("E.6", "Efficient Lighting", GSASCategory.ENERGY,
                           max_points=2.0)
        
        # ─────────────────────────────────────────────────────────────────
        # WATER (W) - 16% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("W.1", "Water Demand Performance", GSASCategory.WATER,
                           max_points=3.0, is_bms_measurable=True,
                           bms_metric_ids=["water_consumption"])
        self._add_criterion("W.2", "Water Recycling", GSASCategory.WATER,
                           max_points=3.0)
        self._add_criterion("W.3", "Water Monitoring", GSASCategory.WATER,
                           max_points=2.0, is_bms_measurable=True)
        self._add_criterion("W.4", "Landscaping Water", GSASCategory.WATER,
                           max_points=2.0)
        
        # ─────────────────────────────────────────────────────────────────
        # INDOOR ENVIRONMENT (IE) - 16% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("IE.1", "Thermal Comfort", GSASCategory.INDOOR_ENVIRONMENT,
                           max_points=3.0, is_bms_measurable=True,
                           bms_metric_ids=["zone_temp", "humidity"])
        self._add_criterion("IE.2", "Indoor Air Quality", GSASCategory.INDOOR_ENVIRONMENT,
                           max_points=3.0, is_bms_measurable=True,
                           bms_metric_ids=["co2_level", "outdoor_air"])
        self._add_criterion("IE.3", "Natural Ventilation", GSASCategory.INDOOR_ENVIRONMENT,
                           max_points=2.0)
        self._add_criterion("IE.4", "Daylighting", GSASCategory.INDOOR_ENVIRONMENT,
                           max_points=2.0)
        self._add_criterion("IE.5", "Acoustic Quality", GSASCategory.INDOOR_ENVIRONMENT,
                           max_points=2.0)
        self._add_criterion("IE.6", "Views", GSASCategory.INDOOR_ENVIRONMENT,
                           max_points=1.0)
        
        # ─────────────────────────────────────────────────────────────────
        # MATERIALS (M) - 14% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("M.1", "Regional Materials", GSASCategory.MATERIALS,
                           max_points=2.0)
        self._add_criterion("M.2", "Recycled Materials", GSASCategory.MATERIALS,
                           max_points=2.0)
        self._add_criterion("M.3", "Material Reuse", GSASCategory.MATERIALS,
                           max_points=2.0)
        self._add_criterion("M.4", "Life Cycle Assessment", GSASCategory.MATERIALS,
                           max_points=3.0)
        
        # ─────────────────────────────────────────────────────────────────
        # SITE (S) - 10% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("S.1", "Land Preservation", GSASCategory.SITE,
                           max_points=2.0)
        self._add_criterion("S.2", "Landscaping", GSASCategory.SITE,
                           max_points=2.0)
        self._add_criterion("S.3", "Heat Island Effect", GSASCategory.SITE,
                           max_points=2.0)
        self._add_criterion("S.4", "Light Pollution", GSASCategory.SITE,
                           max_points=1.0)
        
        # ─────────────────────────────────────────────────────────────────
        # MANAGEMENT & OPERATIONS (MO) - 10% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("MO.1", "Commissioning", GSASCategory.MANAGEMENT_OPERATIONS,
                           max_points=2.0, is_bms_measurable=True)
        self._add_criterion("MO.2", "Energy Management", GSASCategory.MANAGEMENT_OPERATIONS,
                           max_points=2.0, is_bms_measurable=True)
        self._add_criterion("MO.3", "Waste Management", GSASCategory.MANAGEMENT_OPERATIONS,
                           max_points=2.0)
        self._add_criterion("MO.4", "Facility Management", GSASCategory.MANAGEMENT_OPERATIONS,
                           max_points=2.0, is_bms_measurable=True,
                           bms_metric_ids=["maintenance_compliance"])
        
        # ─────────────────────────────────────────────────────────────────
        # URBAN CONNECTIVITY (UC) - 5% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("UC.1", "Public Transportation", GSASCategory.URBAN_CONNECTIVITY,
                           max_points=2.0)
        self._add_criterion("UC.2", "Amenity Access", GSASCategory.URBAN_CONNECTIVITY,
                           max_points=2.0)
        
        # ─────────────────────────────────────────────────────────────────
        # CULTURAL & ECONOMIC (CE) - 5% weight
        # ─────────────────────────────────────────────────────────────────
        self._add_criterion("CE.1", "Heritage & Culture", GSASCategory.CULTURAL_ECONOMIC,
                           max_points=2.0)
        self._add_criterion("CE.2", "Economic Impact", GSASCategory.CULTURAL_ECONOMIC,
                           max_points=2.0)
        
        logger.info(f"Initialized {len(self.criteria)} GSAS criteria")
    
    def _add_criterion(
        self,
        criterion_id: str,
        name: str,
        category: GSASCategory,
        max_points: float = 3.0,
        is_bms_measurable: bool = False,
        bms_metric_ids: Optional[List[str]] = None,
    ) -> None:
        """Add a criterion to tracking"""
        self.criteria[criterion_id] = GSASCriterion(
            criterion_id=criterion_id,
            name=name,
            category=category,
            max_points=max_points,
            is_bms_measurable=is_bms_measurable,
            bms_metric_ids=bms_metric_ids or [],
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # BMS DATA INTEGRATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def update_from_bms(
        self,
        energy_data: Optional[Dict[str, Any]] = None,
        water_data: Optional[Dict[str, Any]] = None,
        iaq_data: Optional[Dict[str, Any]] = None,
        maintenance_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Update GSAS scores based on BMS data.
        
        Args:
            energy_data: Energy consumption metrics
            water_data: Water consumption metrics
            iaq_data: Indoor air quality metrics
            maintenance_data: Maintenance compliance data
        """
        if energy_data:
            self._update_energy_criteria(energy_data)
        
        if water_data:
            self._update_water_criteria(water_data)
        
        if iaq_data:
            self._update_iaq_criteria(iaq_data)
        
        if maintenance_data:
            self._update_maintenance_criteria(maintenance_data)
        
        logger.debug("Updated GSAS scores from BMS data")
    
    def _update_energy_criteria(self, data: Dict[str, Any]) -> None:
        """Update energy-related criteria"""
        # E.1 Energy Demand Performance
        if "consumption_vs_baseline" in data:
            reduction = data["consumption_vs_baseline"]  # % reduction
            if reduction >= 40:
                self._set_score("E.1", 3.0, CriterionStatus.EXCEEDS)
            elif reduction >= 30:
                self._set_score("E.1", 2.0, CriterionStatus.ACHIEVED)
            elif reduction >= 20:
                self._set_score("E.1", 1.5, CriterionStatus.ACHIEVED)
            elif reduction >= 10:
                self._set_score("E.1", 1.0, CriterionStatus.IN_PROGRESS)
            else:
                self._set_score("E.1", 0.5, CriterionStatus.IN_PROGRESS)
        
        # E.3 Energy Monitoring
        if "submetering_coverage" in data:
            coverage = data["submetering_coverage"]  # %
            if coverage >= 90:
                self._set_score("E.3", 2.0, CriterionStatus.EXCEEDS)
            elif coverage >= 70:
                self._set_score("E.3", 1.5, CriterionStatus.ACHIEVED)
            elif coverage >= 50:
                self._set_score("E.3", 1.0, CriterionStatus.IN_PROGRESS)
    
    def _update_water_criteria(self, data: Dict[str, Any]) -> None:
        """Update water-related criteria"""
        if "consumption_vs_baseline" in data:
            reduction = data["consumption_vs_baseline"]
            if reduction >= 30:
                self._set_score("W.1", 3.0, CriterionStatus.EXCEEDS)
            elif reduction >= 20:
                self._set_score("W.1", 2.0, CriterionStatus.ACHIEVED)
            elif reduction >= 10:
                self._set_score("W.1", 1.0, CriterionStatus.IN_PROGRESS)
    
    def _update_iaq_criteria(self, data: Dict[str, Any]) -> None:
        """Update indoor environment criteria"""
        # IE.1 Thermal Comfort
        if "comfort_compliance" in data:
            compliance = data["comfort_compliance"]  # %
            if compliance >= 95:
                self._set_score("IE.1", 3.0, CriterionStatus.EXCEEDS)
            elif compliance >= 85:
                self._set_score("IE.1", 2.0, CriterionStatus.ACHIEVED)
            elif compliance >= 75:
                self._set_score("IE.1", 1.0, CriterionStatus.IN_PROGRESS)
        
        # IE.2 Indoor Air Quality
        if "co2_compliance" in data:
            co2_ok = data["co2_compliance"]  # %
            if co2_ok >= 98:
                self._set_score("IE.2", 3.0, CriterionStatus.EXCEEDS)
            elif co2_ok >= 90:
                self._set_score("IE.2", 2.0, CriterionStatus.ACHIEVED)
            elif co2_ok >= 80:
                self._set_score("IE.2", 1.0, CriterionStatus.IN_PROGRESS)
    
    def _update_maintenance_criteria(self, data: Dict[str, Any]) -> None:
        """Update maintenance-related criteria"""
        if "pm_compliance" in data:
            compliance = data["pm_compliance"]  # %
            if compliance >= 95:
                self._set_score("MO.4", 2.0, CriterionStatus.EXCEEDS)
            elif compliance >= 80:
                self._set_score("MO.4", 1.5, CriterionStatus.ACHIEVED)
            elif compliance >= 60:
                self._set_score("MO.4", 1.0, CriterionStatus.IN_PROGRESS)
    
    def _set_score(
        self,
        criterion_id: str,
        points: float,
        status: CriterionStatus,
        evidence: Optional[List[str]] = None,
    ) -> None:
        """Set score for a criterion"""
        if criterion_id in self.criteria:
            c = self.criteria[criterion_id]
            c.current_points = min(points, c.max_points)
            c.status = status
            c.last_updated = datetime.now()
            if evidence:
                c.evidence.extend(evidence)
    
    def set_criterion_score(
        self,
        criterion_id: str,
        points: float,
        evidence: Optional[List[str]] = None,
    ) -> bool:
        """
        Manually set a criterion score.
        
        For criteria not measurable via BMS.
        """
        if criterion_id not in self.criteria:
            return False
        
        status = CriterionStatus.ACHIEVED
        if points >= self.criteria[criterion_id].max_points:
            status = CriterionStatus.EXCEEDS
        elif points <= 0:
            status = CriterionStatus.NOT_STARTED
        
        self._set_score(criterion_id, points, status, evidence)
        return True
    
    # ═══════════════════════════════════════════════════════════════════════
    # SCORING
    # ═══════════════════════════════════════════════════════════════════════
    
    def calculate_overall_score(self) -> float:
        """
        Calculate weighted overall GSAS score.
        
        Returns:
            Score from 0.0 to 3.0
        """
        weighted_sum = 0.0
        total_weight = 0.0
        
        for category, weight in self.CATEGORY_WEIGHTS.items():
            category_criteria = [
                c for c in self.criteria.values()
                if c.category == category
            ]
            
            if not category_criteria:
                continue
            
            # Calculate category score
            total_points = sum(c.current_points for c in category_criteria)
            max_points = sum(c.max_points for c in category_criteria)
            
            if max_points > 0:
                normalized = (total_points / max_points) * 3.0  # Normalize to 0-3
                weighted_sum += normalized * weight
                total_weight += weight
        
        if total_weight > 0:
            return weighted_sum / total_weight * 3.0
        return 0.0
    
    def get_star_rating(self, score: float) -> GSASStarRating:
        """Convert score to star rating"""
        for threshold, rating in self.STAR_THRESHOLDS:
            if score < threshold:
                # Return previous rating
                idx = self.STAR_THRESHOLDS.index((threshold, rating))
                if idx > 0:
                    return self.STAR_THRESHOLDS[idx - 1][1]
                return GSASStarRating.ONE_STAR
        return GSASStarRating.SIX_STAR

    def target_score(self) -> float:
        """Minimum overall score needed for the configured target rating."""
        target_value = self.target_rating.value
        thresholds = {
            GSASStarRating.ONE_STAR.value: 0.5,
            GSASStarRating.TWO_STAR.value: 1.0,
            GSASStarRating.THREE_STAR.value: 1.5,
            GSASStarRating.FOUR_STAR.value: 2.0,
            GSASStarRating.FIVE_STAR.value: 2.5,
            GSASStarRating.SIX_STAR.value: 2.75,
        }
        return thresholds.get(target_value, 1.5)

    def score_operational_recommendation(self, recommendation: Dict[str, Any]) -> GSASOperationalImpact:
        """
        Score how much an operational recommendation helps GSAS targets.

        This closes the loop between reporting and operations: advisory goals
        can now be ranked by compliance impact, not only cost or risk.
        """
        category = self._infer_operational_category(recommendation)
        criteria_ids = self._matching_criteria(category)
        current_score = self.calculate_overall_score()
        target_gap = max(0.0, self.target_score() - current_score)
        weighted_gain = self._estimate_weighted_gain(category, criteria_ids, recommendation)
        confidence = self._estimate_impact_confidence(recommendation, criteria_ids)
        evidence = self._build_operational_evidence(category, criteria_ids, recommendation, target_gap)

        return GSASOperationalImpact(
            category=category.value,
            criteria=criteria_ids,
            target_delta=weighted_gain,
            impact_score=min(1.0, weighted_gain / max(target_gap, 0.15)) if weighted_gain > 0 else 0.0,
            confidence=confidence,
            evidence=evidence,
        )

    def optimize_recommendations_for_targets(
        self,
        recommendations: List[Dict[str, Any]],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Attach GSAS impact to recommendations and rank by target contribution."""
        optimized = []
        for rec in recommendations:
            impact = self.score_operational_recommendation(rec)
            enriched = dict(rec)
            enriched["gsas_impact"] = impact.to_dict()
            optimized.append(enriched)

        optimized.sort(
            key=lambda r: (
                r["gsas_impact"]["impact_score"],
                r["gsas_impact"]["confidence"],
                r["gsas_impact"]["target_delta"],
            ),
            reverse=True,
        )
        return optimized[:limit]
    
    def calculate_category_scores(self) -> Dict[str, GSASCategoryScore]:
        """Calculate scores for each category"""
        scores = {}
        
        category_names = {
            GSASCategory.ENERGY: "Energy",
            GSASCategory.WATER: "Water",
            GSASCategory.INDOOR_ENVIRONMENT: "Indoor Environment",
            GSASCategory.SITE: "Site",
            GSASCategory.MATERIALS: "Materials",
            GSASCategory.MANAGEMENT_OPERATIONS: "Management & Operations",
            GSASCategory.URBAN_CONNECTIVITY: "Urban Connectivity",
            GSASCategory.CULTURAL_ECONOMIC: "Cultural & Economic Value",
        }
        
        for category in GSASCategory:
            criteria = [c for c in self.criteria.values() if c.category == category]
            
            if not criteria:
                continue
            
            achieved = sum(c.current_points for c in criteria)
            max_pts = sum(c.max_points for c in criteria)
            achieved_count = sum(1 for c in criteria if c.status in 
                                (CriterionStatus.ACHIEVED, CriterionStatus.EXCEEDS))
            
            # Identify items needing attention
            needs_attention = [
                c.name for c in criteria
                if c.status in (CriterionStatus.NOT_STARTED, CriterionStatus.IN_PROGRESS)
                and c.weight > 0.5
            ]
            
            # Determine if on track
            target_percentage = 66  # Aiming for ~2/3 of max
            on_track = (achieved / max_pts * 100) >= target_percentage if max_pts > 0 else False
            
            scores[category.value] = GSASCategoryScore(
                category=category,
                category_name=category_names.get(category, category.value),
                achieved_points=achieved,
                max_points=max_pts,
                weighted_score=(achieved / max_pts * 3.0) if max_pts > 0 else 0.0,
                total_criteria=len(criteria),
                achieved_criteria=achieved_count,
                on_track=on_track,
                needs_attention=needs_attention[:3],  # Top 3
            )
        
        return scores

    def _infer_operational_category(self, recommendation: Dict[str, Any]) -> GSASCategory:
        text = " ".join(
            str(recommendation.get(key, ""))
            for key in ("title", "description", "goal_type", "source_engine", "recommended_action", "action")
        )
        for action in recommendation.get("suggested_actions", []) or []:
            text += f" {action}"
        text = text.lower()

        best_category = GSASCategory.MANAGEMENT_OPERATIONS
        best_hits = 0
        for category, config in self.OPERATIONAL_RECOMMENDATION_MAP.items():
            hits = sum(1 for keyword in config["keywords"] if keyword in text)
            if hits > best_hits:
                best_hits = hits
                best_category = category
        return best_category

    def _matching_criteria(self, category: GSASCategory) -> List[str]:
        mapped = self.OPERATIONAL_RECOMMENDATION_MAP.get(category, {}).get("criteria", [])
        return [criterion_id for criterion_id in mapped if criterion_id in self.criteria]

    def _estimate_weighted_gain(
        self,
        category: GSASCategory,
        criteria_ids: List[str],
        recommendation: Dict[str, Any],
    ) -> float:
        if not criteria_ids:
            return 0.0

        category_weight = self.CATEGORY_WEIGHTS.get(category, 0.1)
        remaining_gain = 0.0
        for criterion_id in criteria_ids:
            criterion = self.criteria.get(criterion_id)
            if criterion:
                remaining_gain += max(0.0, criterion.max_points - criterion.current_points)

        max_remaining = sum(self.criteria[c].max_points for c in criteria_ids if c in self.criteria) or 1.0
        measurable_bonus = 1.15 if any(self.criteria[c].is_bms_measurable for c in criteria_ids if c in self.criteria) else 1.0
        action_strength = self._estimate_action_strength(recommendation)
        normalized_gain = min(1.0, remaining_gain / max_remaining)

        return normalized_gain * category_weight * action_strength * measurable_bonus

    def _estimate_action_strength(self, recommendation: Dict[str, Any]) -> float:
        priority = str(recommendation.get("priority", "")).lower()
        savings = float(recommendation.get("potential_savings_qar", 0) or 0)
        goal_type = str(recommendation.get("goal_type", "")).lower()

        strength = 0.45
        if priority in ("critical", "high"):
            strength += 0.15
        if goal_type in ("efficiency", "compliance", "optimization"):
            strength += 0.15
        if savings >= 50000:
            strength += 0.2
        elif savings >= 10000:
            strength += 0.1
        return min(1.0, strength)

    def _estimate_impact_confidence(self, recommendation: Dict[str, Any], criteria_ids: List[str]) -> float:
        confidence = 0.55
        if criteria_ids:
            confidence += 0.15
        if recommendation.get("equipment_ids"):
            confidence += 0.1
        if recommendation.get("source_engine") in ("energy", "predictive", "fleet"):
            confidence += 0.1
        if recommendation.get("potential_savings_qar", 0):
            confidence += 0.05
        return min(0.95, confidence)

    def _build_operational_evidence(
        self,
        category: GSASCategory,
        criteria_ids: List[str],
        recommendation: Dict[str, Any],
        target_gap: float,
    ) -> List[str]:
        evidence = [
            f"Mapped recommendation to GSAS category {category.value}",
            f"Current target gap: {target_gap:.2f} GSAS score points",
        ]
        if criteria_ids:
            criterion_names = [
                f"{criterion_id} {self.criteria[criterion_id].name}"
                for criterion_id in criteria_ids if criterion_id in self.criteria
            ]
            evidence.append("Relevant criteria: " + "; ".join(criterion_names))
        if recommendation.get("source_engine"):
            evidence.append(f"Source engine: {recommendation['source_engine']}")
        return evidence
    
    # ═══════════════════════════════════════════════════════════════════════
    # REPORTING
    # ═══════════════════════════════════════════════════════════════════════
    
    def generate_report(self) -> GSASReport:
        """Generate comprehensive GSAS compliance report"""
        overall_score = self.calculate_overall_score()
        star_rating = self.get_star_rating(overall_score)
        category_scores = self.calculate_category_scores()
        
        # Identify strengths and improvements
        strengths = []
        improvements = []
        recommendations = []
        
        for cat_id, cat_score in category_scores.items():
            if cat_score.percentage >= 70:
                strengths.append(f"{cat_score.category_name}: {cat_score.percentage:.0f}% achieved")
            elif cat_score.percentage < 50:
                improvements.append(f"{cat_score.category_name} needs improvement ({cat_score.percentage:.0f}%)")
                
                # Add specific recommendations
                for criterion_name in cat_score.needs_attention:
                    recommendations.append({
                        "category": cat_score.category_name,
                        "criterion": criterion_name,
                        "action": f"Review and improve {criterion_name}",
                        "impact": "medium",
                    })
        
        # Generate report
        report = GSASReport(
            building_id=self.building_id,
            building_name=self.building_name,
            assessment_date=datetime.now(),
            overall_score=overall_score,
            star_rating=star_rating,
            target_rating=self.target_rating,
            category_scores=category_scores,
            criteria=self.criteria,
            strengths=strengths,
            improvements=improvements,
            recommendations=recommendations,
        )
        
        # Add to history
        self.history.append({
            "date": datetime.now().isoformat(),
            "score": overall_score,
            "rating": star_rating.value,
        })
        
        logger.info(f"Generated GSAS report: {overall_score:.2f} ({star_rating.value} stars)")
        
        return report
    
    def get_status(self) -> Dict[str, Any]:
        """Get current GSAS status summary"""
        overall_score = self.calculate_overall_score()
        star_rating = self.get_star_rating(overall_score)
        category_scores = self.calculate_category_scores()
        
        return {
            "overall_score": round(overall_score, 2),
            "star_rating": star_rating.value,
            "target_rating": self.target_rating.value,
            "on_track": star_rating.value >= self.target_rating.value,
            "categories": {k: v.to_dict() for k, v in category_scores.items()},
            "bms_measurable_count": sum(
                1 for c in self.criteria.values() if c.is_bms_measurable
            ),
            "next_assessment": (datetime.now() + timedelta(days=30)).isoformat(),
        }
    
    def get_improvement_priorities(self) -> List[Dict[str, Any]]:
        """Get prioritized list of improvements"""
        priorities = []
        
        for criterion in self.criteria.values():
            if criterion.status in (CriterionStatus.NOT_STARTED, CriterionStatus.IN_PROGRESS):
                potential_gain = criterion.max_points - criterion.current_points
                category_weight = self.CATEGORY_WEIGHTS.get(criterion.category, 0.1)
                impact_score = potential_gain * category_weight
                
                priorities.append({
                    "criterion_id": criterion.criterion_id,
                    "criterion_name": criterion.name,
                    "category": criterion.category.value,
                    "current_points": criterion.current_points,
                    "potential_gain": potential_gain,
                    "impact_score": round(impact_score, 3),
                    "is_bms_measurable": criterion.is_bms_measurable,
                })
        
        # Sort by impact
        priorities.sort(key=lambda x: x["impact_score"], reverse=True)
        
        return priorities[:10]  # Top 10
    
    def generate_html_report(self) -> str:
        """Generate HTML version of the report"""
        report = self.generate_report()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>GSAS Compliance Report - {self.building_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ background: #1a5f7a; color: white; padding: 20px; }}
                .score {{ font-size: 48px; font-weight: bold; }}
                .category {{ margin: 20px 0; padding: 15px; border-left: 4px solid #1a5f7a; }}
                .on-track {{ border-color: #28a745; }}
                .needs-attention {{ border-color: #dc3545; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>GSAS Compliance Report</h1>
                <p>{self.building_name} | {report.assessment_date.strftime('%B %d, %Y')}</p>
            </div>
            
            <div style="text-align: center; margin: 40px 0;">
                <div class="score">{report.overall_score:.2f}</div>
                <p>Overall Score | {report.star_rating.value} Star Rating</p>
                <p>Target: {report.target_rating.value} Stars</p>
            </div>
            
            <h2>Category Scores</h2>
            <table>
                <tr><th>Category</th><th>Score</th><th>Status</th></tr>
        """
        
        for cat_id, cat_score in report.category_scores.items():
            status = "✓ On Track" if cat_score.on_track else "⚠ Needs Attention"
            html += f"""
                <tr>
                    <td>{cat_score.category_name}</td>
                    <td>{cat_score.percentage:.0f}%</td>
                    <td>{status}</td>
                </tr>
            """
        
        html += """
            </table>
            
            <h2>Key Recommendations</h2>
            <ul>
        """
        
        for rec in report.recommendations[:5]:
            html += f"<li><strong>{rec['category']}</strong>: {rec['action']}</li>"
        
        html += """
            </ul>
            
            <footer style="margin-top: 40px; color: #666;">
                <p>Generated by ARVIS Ops Copilot | GSAS v2.1 Methodology</p>
            </footer>
        </body>
        </html>
        """
        
        return html

    # ═══════════════════════════════════════════════════════════════════════
    # GORD PDF REPORT GENERATION (Operations Certification)
    # ═══════════════════════════════════════════════════════════════════════
    
    def generate_gord_pdf(
        self,
        output_path: str = None,
        include_evidence: bool = True,
        certification_type: str = "operations",
    ) -> str:
        """
        Generate GORD-compliant PDF report for GSAS Operations certification.
        
        This is the report that Facility Managers submit to GORD for 
        Operations certification renewal. Auto-generating this report
        saves weeks of manual work.
        
        Args:
            output_path: Where to save the PDF (default: reports/GSAS_GORD_Report_<date>.pdf)
            include_evidence: Include BMS data evidence
            certification_type: "operations" or "construction"
            
        Returns:
            Path to generated PDF file
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm, mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                PageBreak, Image, HRFlowable
            )
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        except ImportError:
            logger.warning("reportlab not installed. Run: pip install reportlab")
            return self._generate_pdf_fallback(output_path)
        
        import os
        from datetime import datetime
        
        # Generate report data
        report = self.generate_report()
        
        # Set output path
        if not output_path:
            os.makedirs("reports", exist_ok=True)
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"reports/GSAS_GORD_Report_{self.building_id}_{date_str}.pdf"
        
        # Create document
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
        )
        
        # Styles
        styles = getSampleStyleSheet()
        
        # Custom styles
        styles.add(ParagraphStyle(
            name='GORDTitle',
            fontSize=24,
            leading=28,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=colors.HexColor('#1a5f7a'),
            fontName='Helvetica-Bold'
        ))
        
        styles.add(ParagraphStyle(
            name='GORDSubtitle',
            fontSize=14,
            leading=18,
            alignment=TA_CENTER,
            spaceAfter=20,
            textColor=colors.gray
        ))
        
        styles.add(ParagraphStyle(
            name='SectionHeader',
            fontSize=14,
            leading=18,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor('#1a5f7a'),
            fontName='Helvetica-Bold'
        ))
        
        styles.add(ParagraphStyle(
            name='GORDBody',
            fontSize=10,
            leading=14,
            spaceAfter=8,
        ))
        
        # Build content
        content = []
        
        # ─────────────────────────────────────────────────────────────────
        # COVER PAGE
        # ─────────────────────────────────────────────────────────────────
        
        content.append(Spacer(1, 3*cm))
        content.append(Paragraph(
            "GSAS Operations Certification",
            styles['GORDTitle']
        ))
        content.append(Paragraph(
            "Compliance Assessment Report",
            styles['GORDSubtitle']
        ))
        
        content.append(Spacer(1, 2*cm))
        
        # Building Info Table
        building_data = [
            ["Building Name:", self.building_name],
            ["Building ID:", self.building_id],
            ["Assessment Date:", report.assessment_date.strftime("%B %d, %Y")],
            ["Report ID:", report.report_id],
            ["Certification Type:", certification_type.title()],
            ["GSAS Version:", "v2.1"],
        ]
        
        building_table = Table(building_data, colWidths=[5*cm, 10*cm])
        building_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        content.append(building_table)
        
        content.append(Spacer(1, 2*cm))
        
        # Score Summary Box
        score_data = [
            ["Overall Score", f"{report.overall_score:.2f} / 3.00"],
            ["Star Rating", f"{'★' * report.star_rating.value}{'☆' * (6 - report.star_rating.value)} ({report.star_rating.value} Stars)"],
            ["Target Rating", f"{report.target_rating.value} Stars"],
            ["Compliance Status", "ON TRACK ✓" if report.star_rating.value >= report.target_rating.value else "NEEDS ATTENTION"],
        ]
        
        score_table = Table(score_data, colWidths=[7*cm, 8*cm])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5f7a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#1a5f7a')),
        ]))
        content.append(score_table)
        
        content.append(Spacer(1, 2*cm))
        
        # Submission Info
        content.append(Paragraph(
            "<i>Prepared for submission to Gulf Organisation for Research & Development (GORD)</i>",
            styles['GORDSubtitle']
        ))
        content.append(Paragraph(
            f"<i>Generated by ARVIS Ops Copilot on {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
            styles['GORDSubtitle']
        ))
        
        content.append(PageBreak())
        
        # ─────────────────────────────────────────────────────────────────
        # EXECUTIVE SUMMARY
        # ─────────────────────────────────────────────────────────────────
        
        content.append(Paragraph("1. Executive Summary", styles['SectionHeader']))
        content.append(HRFlowable(width="100%", color=colors.HexColor('#1a5f7a')))
        
        summary_text = f"""
        This report presents the GSAS Operations certification assessment for 
        <b>{self.building_name}</b>. The building achieved an overall score of 
        <b>{report.overall_score:.2f}</b>, corresponding to a <b>{report.star_rating.value}-Star</b> rating.
        """
        content.append(Paragraph(summary_text, styles['GORDBody']))
        
        if report.star_rating.value >= report.target_rating.value:
            content.append(Paragraph(
                "✓ The building <b>meets the target certification level</b> and is recommended for Operations certification renewal.",
                styles['GORDBody']
            ))
        else:
            content.append(Paragraph(
                f"⚠ The building is <b>{report.target_rating.value - report.star_rating.value} star(s) below target</b>. Improvement actions are recommended before certification submission.",
                styles['GORDBody']
            ))
        
        content.append(Spacer(1, 0.5*cm))
        
        # Key Strengths
        if report.strengths:
            content.append(Paragraph("<b>Key Strengths:</b>", styles['GORDBody']))
            for strength in report.strengths[:3]:
                content.append(Paragraph(f"• {strength}", styles['GORDBody']))
        
        # Areas for Improvement
        if report.improvements:
            content.append(Paragraph("<b>Areas Requiring Attention:</b>", styles['GORDBody']))
            for improvement in report.improvements[:3]:
                content.append(Paragraph(f"• {improvement}", styles['GORDBody']))
        
        content.append(Spacer(1, 1*cm))
        
        # ─────────────────────────────────────────────────────────────────
        # CATEGORY BREAKDOWN
        # ─────────────────────────────────────────────────────────────────
        
        content.append(Paragraph("2. Category Score Breakdown", styles['SectionHeader']))
        content.append(HRFlowable(width="100%", color=colors.HexColor('#1a5f7a')))
        
        # Category table
        cat_header = ["Category", "Weight", "Score", "Max", "%", "Status"]
        cat_data = [cat_header]
        
        for cat_id, cat_score in report.category_scores.items():
            weight = self.CATEGORY_WEIGHTS.get(cat_score.category, 0) * 100
            status = "✓" if cat_score.on_track else "⚠"
            cat_data.append([
                cat_score.category_name,
                f"{weight:.0f}%",
                f"{cat_score.achieved_points:.1f}",
                f"{cat_score.max_points:.1f}",
                f"{cat_score.percentage:.0f}%",
                status
            ])
        
        cat_table = Table(cat_data, colWidths=[5*cm, 2*cm, 2*cm, 2*cm, 2*cm, 2*cm])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5f7a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        content.append(cat_table)
        
        content.append(PageBreak())
        
        # ─────────────────────────────────────────────────────────────────
        # DETAILED CRITERIA SCORES
        # ─────────────────────────────────────────────────────────────────
        
        content.append(Paragraph("3. Detailed Criteria Assessment", styles['SectionHeader']))
        content.append(HRFlowable(width="100%", color=colors.HexColor('#1a5f7a')))
        
        # Group criteria by category
        for category in GSASCategory:
            cat_criteria = [c for c in self.criteria.values() if c.category == category]
            if not cat_criteria:
                continue
            
            cat_name = {
                GSASCategory.ENERGY: "Energy (E)",
                GSASCategory.WATER: "Water (W)",
                GSASCategory.INDOOR_ENVIRONMENT: "Indoor Environment (IE)",
                GSASCategory.SITE: "Site (S)",
                GSASCategory.MATERIALS: "Materials (M)",
                GSASCategory.MANAGEMENT_OPERATIONS: "Management & Operations (MO)",
                GSASCategory.URBAN_CONNECTIVITY: "Urban Connectivity (UC)",
                GSASCategory.CULTURAL_ECONOMIC: "Cultural & Economic Value (CE)",
            }.get(category, category.value)
            
            content.append(Paragraph(f"<b>{cat_name}</b>", styles['GORDBody']))
            
            criteria_data = [["ID", "Criterion", "Score", "Max", "Status", "BMS?"]]
            for c in cat_criteria:
                bms = "Yes" if c.is_bms_measurable else "No"
                status_icon = {
                    CriterionStatus.EXCEEDS: "★",
                    CriterionStatus.ACHIEVED: "✓",
                    CriterionStatus.IN_PROGRESS: "◐",
                    CriterionStatus.NOT_STARTED: "○",
                    CriterionStatus.NOT_APPLICABLE: "N/A",
                }.get(c.status, "?")
                
                criteria_data.append([
                    c.criterion_id,
                    c.name[:30],  # Truncate long names
                    f"{c.current_points:.1f}",
                    f"{c.max_points:.1f}",
                    status_icon,
                    bms
                ])
            
            criteria_table = Table(criteria_data, colWidths=[1.5*cm, 6*cm, 1.5*cm, 1.5*cm, 1.5*cm, 1.5*cm])
            criteria_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
            ]))
            content.append(criteria_table)
            content.append(Spacer(1, 0.5*cm))
        
        content.append(PageBreak())
        
        # ─────────────────────────────────────────────────────────────────
        # BMS EVIDENCE (if included)
        # ─────────────────────────────────────────────────────────────────
        
        if include_evidence:
            content.append(Paragraph("4. BMS Data Evidence", styles['SectionHeader']))
            content.append(HRFlowable(width="100%", color=colors.HexColor('#1a5f7a')))
            
            content.append(Paragraph(
                "The following data points were automatically collected from the Building Management System (BMS) "
                "to support the GSAS criteria scoring:",
                styles['GORDBody']
            ))
            
            bms_criteria = [c for c in self.criteria.values() if c.is_bms_measurable]
            
            evidence_data = [["Criterion", "Metric IDs", "Last Updated", "Auto-scored"]]
            for c in bms_criteria:
                metrics = ", ".join(c.bms_metric_ids) if c.bms_metric_ids else "N/A"
                updated = c.last_updated.strftime("%Y-%m-%d") if c.last_updated else "N/A"
                evidence_data.append([
                    f"{c.criterion_id}: {c.name[:25]}",
                    metrics[:30],
                    updated,
                    "Yes"
                ])
            
            evidence_table = Table(evidence_data, colWidths=[5*cm, 5*cm, 3*cm, 2*cm])
            evidence_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5f7a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
            ]))
            content.append(evidence_table)
            
            content.append(Spacer(1, 0.5*cm))
            content.append(Paragraph(
                "<i>BMS integration enables continuous compliance monitoring and reduces manual data collection effort.</i>",
                styles['GORDBody']
            ))
        
        content.append(PageBreak())
        
        # ─────────────────────────────────────────────────────────────────
        # RECOMMENDATIONS
        # ─────────────────────────────────────────────────────────────────
        
        content.append(Paragraph("5. Improvement Recommendations", styles['SectionHeader']))
        content.append(HRFlowable(width="100%", color=colors.HexColor('#1a5f7a')))
        
        priorities = self.get_improvement_priorities()
        
        if priorities:
            content.append(Paragraph(
                "The following improvements are recommended to enhance the GSAS score, "
                "listed in order of impact:",
                styles['GORDBody']
            ))
            
            rec_data = [["Priority", "Criterion", "Category", "Potential Gain", "BMS Trackable"]]
            for i, p in enumerate(priorities[:10], 1):
                rec_data.append([
                    str(i),
                    f"{p['criterion_id']}: {p['criterion_name'][:25]}",
                    p['category'],
                    f"+{p['potential_gain']:.1f} pts",
                    "Yes" if p['is_bms_measurable'] else "No"
                ])
            
            rec_table = Table(rec_data, colWidths=[1.5*cm, 6*cm, 3*cm, 2.5*cm, 2.5*cm])
            rec_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5f7a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
            ]))
            content.append(rec_table)
        else:
            content.append(Paragraph(
                "No significant improvement opportunities identified. The building is performing well across all categories.",
                styles['GORDBody']
            ))
        
        content.append(Spacer(1, 1*cm))
        
        # ─────────────────────────────────────────────────────────────────
        # CERTIFICATION STATEMENT
        # ─────────────────────────────────────────────────────────────────
        
        content.append(Paragraph("6. Certification Statement", styles['SectionHeader']))
        content.append(HRFlowable(width="100%", color=colors.HexColor('#1a5f7a')))
        
        content.append(Paragraph(
            f"""
            This report has been automatically generated based on data from the Building Management System 
            and manual inputs. The overall GSAS score of <b>{report.overall_score:.2f}</b> qualifies the building 
            for a <b>{report.star_rating.value}-Star</b> Operations Certification.
            """,
            styles['GORDBody']
        ))
        
        content.append(Spacer(1, 1*cm))
        
        # Signature block
        sig_data = [
            ["Facility Manager:", "_" * 30, "Date:", "_" * 15],
            ["", "", "", ""],
            ["GORD Reviewer:", "_" * 30, "Date:", "_" * 15],
        ]
        sig_table = Table(sig_data, colWidths=[3.5*cm, 6*cm, 2*cm, 4*cm])
        sig_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ]))
        content.append(sig_table)
        
        content.append(Spacer(1, 1*cm))
        
        # Footer
        content.append(HRFlowable(width="100%", color=colors.gray))
        content.append(Paragraph(
            f"<i>Report generated by ARVIS Ops Copilot | GSAS v2.1 Methodology | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
            ParagraphStyle('Footer', fontSize=8, textColor=colors.gray, alignment=TA_CENTER)
        ))
        
        # Build PDF
        doc.build(content)
        
        logger.info(f"Generated GORD PDF report: {output_path}")
        return output_path
    
    def _generate_pdf_fallback(self, output_path: str) -> str:
        """Fallback when reportlab is not available"""
        # Generate HTML instead and return path
        html_content = self.generate_html_report()
        
        import os
        os.makedirs("reports", exist_ok=True)
        
        if not output_path:
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"reports/GSAS_Report_{self.building_id}_{date_str}.html"
        else:
            output_path = output_path.replace('.pdf', '.html')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.warning(f"PDF generation unavailable. Generated HTML report: {output_path}")
        return output_path


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def generate_gsas_report_for_gord(
    building_id: str,
    building_name: str,
    energy_data: Dict = None,
    water_data: Dict = None,
    iaq_data: Dict = None,
    output_path: str = None,
) -> str:
    """
    Quick function to generate a GORD-compliant PDF report.
    
    This is the main entry point for automated report generation.
    
    Usage:
        >>> pdf_path = generate_gsas_report_for_gord(
        ...     building_id="QNB-TOWER-01",
        ...     building_name="QNB Tower - West Bay",
        ...     energy_data={"consumption_vs_baseline": 25},
        ...     water_data={"consumption_vs_baseline": 15},
        ... )
        >>> print(f"Report saved to: {pdf_path}")
    """
    reporter = GSASReporter(building_id, building_name)
    reporter.initialize_criteria()
    reporter.update_from_bms(energy_data, water_data, iaq_data)
    return reporter.generate_gord_pdf(output_path)
