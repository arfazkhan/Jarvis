"""
GSAS Occupant Satisfaction Surveys
==================================

Manages occupant feedback on thermal comfort, air quality, lighting, 
and acoustics for GSAS IE category compliance.
"""

import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger("arvis.gsas.surveys")

@dataclass
class SurveyResponse:
    """Individual feedback from a building occupant."""
    response_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    occupant_type: str = "staff" # staff, visitor, resident
    thermal_comfort: int = 3     # 1-5
    air_quality: int = 3        # 1-5
    lighting_quality: int = 3    # 1-5
    acoustic_comfort: int = 3    # 1-5
    comments: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

class SurveyManager:
    """Collects and aggregates occupant satisfaction data."""
    
    def __init__(self):
        self.responses: List[SurveyResponse] = []

    def add_response(self, response: SurveyResponse) -> None:
        self.responses.append(response)
        logger.info(f"Received survey response. Average comfort: {self._calc_avg(response)}")

    def _calc_avg(self, r: SurveyResponse) -> float:
        return (r.thermal_comfort + r.air_quality + r.lighting_quality + r.acoustic_comfort) / 4.0

    def get_satisfaction_rate(self) -> float:
        """
        Calculate the percentage of occupants satisfied (score >= 3).
        GSAS requires high satisfaction for IE points.
        """
        if not self.responses:
            return 0.0
            
        satisfied = [r for r in self.responses if self._calc_avg(r) >= 3.0]
        return (len(satisfied) / len(self.responses)) * 100

    def get_gsas_ie_data(self) -> Dict[str, Any]:
        """Aggregate data for IE scoring."""
        if not self.responses:
            return {"satisfaction_rate": 0, "response_count": 0}
            
        return {
            "satisfaction_rate": round(self.get_satisfaction_rate(), 1),
            "response_count": len(self.responses),
            "averages": {
                "thermal": sum(r.thermal_comfort for r in self.responses) / len(self.responses),
                "air": sum(r.air_quality for r in self.responses) / len(self.responses),
                "light": sum(r.lighting_quality for r in self.responses) / len(self.responses),
                "noise": sum(r.acoustic_comfort for r in self.responses) / len(self.responses)
            }
        }
