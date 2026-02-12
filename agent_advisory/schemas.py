"""
Data Models for Advisory System
================================

Pydantic schemas for recommendations, trust metrics, and preferences.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import json


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def safe_json_dumps(obj: Any) -> str:
    """JSON dumps with datetime support"""
    return json.dumps(obj, cls=DateTimeEncoder)



class RecommendationStatus(str, Enum):
    """Status of a recommendation"""
    PENDING = "pending"           # Recommendation made, no operator response yet
    ACCEPTED = "accepted"         # Operator followed the recommendation
    REJECTED = "rejected"         # Operator chose different action
    MODIFIED = "modified"         # Operator modified the recommendation
    EXPIRED = "expired"           # Recommendation timed out


class OutcomeQuality(str, Enum):
    """Quality of recommendation outcome"""
    EXCELLENT = "excellent"       # Better than predicted
    GOOD = "good"                 # As predicted
    ACCEPTABLE = "acceptable"     # Slightly worse than predicted
    POOR = "poor"                 # Significantly worse than predicted
    UNKNOWN = "unknown"           # Outcome not yet known


@dataclass
class Recommendation:
    """A single recommendation made by ARVIS"""
    
    # Identity
    id: str
    timestamp: float
    
    # Context when recommendation was made
    context: Dict[str, Any]  # Alarm state, equipment status, etc.
    trigger_type: str        # "alarm", "scheduled_check", "proactive_scan"
    
    # What ARVIS recommended
    recommended_action: Dict[str, Any]
    confidence: float        # 0.0 - 1.0
    calibrated_confidence: Optional[float] = None
    reasoning: str = ""
    predicted_outcome: Optional[Dict[str, Any]] = None
    
    # What operator did
    status: RecommendationStatus = RecommendationStatus.PENDING
    human_action: Optional[Dict[str, Any]] = None
    decision_time: Optional[float] = None
    operator_id: Optional[str] = None
    
    # Actual outcome
    actual_outcome: Optional[Dict[str, Any]] = None
    outcome_quality: OutcomeQuality = OutcomeQuality.UNKNOWN
    outcome_measured_at: Optional[float] = None
    
    # Metadata
    building_id: str = "unknown"
    equipment_ids: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "context": safe_json_dumps(self.context),
            "trigger_type": self.trigger_type,
            "recommended_action": safe_json_dumps(self.recommended_action),
            "confidence": self.confidence,
            "calibrated_confidence": self.calibrated_confidence,
            "reasoning": self.reasoning,
            "predicted_outcome": safe_json_dumps(self.predicted_outcome) if self.predicted_outcome else None,
            "status": self.status.value,
            "human_action": safe_json_dumps(self.human_action) if self.human_action else None,
            "decision_time": self.decision_time,
            "operator_id": self.operator_id,
            "actual_outcome": safe_json_dumps(self.actual_outcome) if self.actual_outcome else None,
            "outcome_quality": self.outcome_quality.value,
            "outcome_measured_at": self.outcome_measured_at,
            "building_id": self.building_id,
            "equipment_ids": safe_json_dumps(self.equipment_ids),
            "tags": safe_json_dumps(self.tags),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recommendation":
        """Load from dictionary"""
        import json
        
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            context=json.loads(data["context"]) if isinstance(data["context"], str) else data["context"],
            trigger_type=data["trigger_type"],
            recommended_action=json.loads(data["recommended_action"]) if isinstance(data["recommended_action"], str) else data["recommended_action"],
            confidence=data["confidence"],
            calibrated_confidence=data.get("calibrated_confidence"),
            reasoning=data.get("reasoning", ""),
            predicted_outcome=json.loads(data["predicted_outcome"]) if data.get("predicted_outcome") and isinstance(data["predicted_outcome"], str) else data.get("predicted_outcome"),
            status=RecommendationStatus(data.get("status", "pending")),
            human_action=json.loads(data["human_action"]) if data.get("human_action") and isinstance(data["human_action"], str) else data.get("human_action"),
            decision_time=data.get("decision_time"),
            operator_id=data.get("operator_id"),
            actual_outcome=json.loads(data["actual_outcome"]) if data.get("actual_outcome") and isinstance(data["actual_outcome"], str) else data.get("actual_outcome"),
            outcome_quality=OutcomeQuality(data.get("outcome_quality", "unknown")),
            outcome_measured_at=data.get("outcome_measured_at"),
            building_id=data.get("building_id", "unknown"),
            equipment_ids=json.loads(data["equipment_ids"]) if data.get("equipment_ids") and isinstance(data["equipment_ids"], str) else data.get("equipment_ids", []),
            tags=json.loads(data["tags"]) if data.get("tags") and isinstance(data["tags"], str) else data.get("tags", []),
        )


@dataclass
class TrustMetrics:
    """Trust metrics for a time period"""
    
    date: str  # ISO date
    total_recommendations: int
    
    # Adoption metrics
    adoption_rate: float          # % of recommendations followed
    acceptance_count: int
    rejection_count: int
    modification_count: int
    
    # Accuracy metrics (when recommendation was followed)
    accuracy_when_followed: float  # % of time outcome matched prediction
    excellent_outcomes: int
    good_outcomes: int
    acceptable_outcomes: int
    poor_outcomes: int
    
    # Calibration metrics
    calibration_error: float       # Mean abs difference between confidence and accuracy
    calibration_buckets: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # e.g., {"0.8": {"stated": 0.8, "actual": 0.75, "count": 10}}
    
    # Regret metrics
    regret_rate: float = 0.0       # % of times operator wished they'd followed
    false_alarm_rate: float = 0.0  # % of high-confidence recs that were wrong
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "date": self.date,
            "total_recommendations": self.total_recommendations,
            "adoption_rate": self.adoption_rate,
            "acceptance_count": self.acceptance_count,
            "rejection_count": self.rejection_count,
            "modification_count": self.modification_count,
            "accuracy_when_followed": self.accuracy_when_followed,
            "excellent_outcomes": self.excellent_outcomes,
            "good_outcomes": self.good_outcomes,
            "acceptable_outcomes": self.acceptable_outcomes,
            "poor_outcomes": self.poor_outcomes,
            "calibration_error": self.calibration_error,
            "calibration_buckets": safe_json_dumps(self.calibration_buckets),
            "regret_rate": self.regret_rate,
            "false_alarm_rate": self.false_alarm_rate,
        }


@dataclass
class OperatorPreference:
    """A learned preference from operator behavior"""
    
    id: str
    timestamp: float
    operator_id: str
    
    # Context features
    context_type: str              # "alarm_response", "energy_optimization", etc.
    context_features: Dict[str, Any]  # Extracted features
    
    # What was chosen vs what was recommended
    agent_recommendation: Dict[str, Any]
    operator_choice: Dict[str, Any]
    is_agreement: bool
    
    # Inferred preference
    preference_signal: str         # Natural language: "Prefers graceful degradation over shutdown"
    confidence: float              # How confident we are in this inference
    
    # Outcome (if known)
    outcome_quality: Optional[OutcomeQuality] = None
    
    # Metadata
    building_id: str = "unknown"
    equipment_ids: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "operator_id": self.operator_id,
            "context_type": self.context_type,
            "context_features": safe_json_dumps(self.context_features),
            "agent_recommendation": safe_json_dumps(self.agent_recommendation),
            "operator_choice": safe_json_dumps(self.operator_choice),
            "is_agreement": self.is_agreement,
            "preference_signal": self.preference_signal,
            "confidence": self.confidence,
            "outcome_quality": self.outcome_quality.value if self.outcome_quality else None,
            "building_id": self.building_id,
            "equipment_ids": safe_json_dumps(self.equipment_ids),
        }
