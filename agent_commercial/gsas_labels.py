"""
GSAS Performance Labels
=======================

Generates official-style Energy Performance Labels (EPL) and 
Water Performance Labels (WPL) based on GSAS scores.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any

logger = logging.getLogger("arvis.gsas.labels")

@dataclass
class PerformanceLabel:
    label_id: str
    label_type: str  # EPL, WPL
    rating: str      # A, B, C, D, E, F
    score_value: float
    issued_at: str
    expiry_date: str

class LabelGenerator:
    """Generates compliance labels for building display."""
    
    def generate_epl(self, energy_score: float) -> PerformanceLabel:
        """Energy Performance Label."""
        rating = self._calculate_rating(energy_score)
        logger.info(f"Generated EPL: {rating} ({energy_score:.2f})")
        
        from datetime import datetime, timedelta
        issued = datetime.now()
        expiry = issued + timedelta(days=365)
        
        return PerformanceLabel(
            label_id=f"EPL-{issued.strftime('%Y%m%d')}",
            label_type="EPL",
            rating=rating,
            score_value=energy_score,
            issued_at=issued.isoformat(),
            expiry_date=expiry.isoformat()
        )

    def generate_wpl(self, water_score: float) -> PerformanceLabel:
        """Water Performance Label."""
        rating = self._calculate_rating(water_score)
        logger.info(f"Generated WPL: {rating} ({water_score:.2f})")
        
        from datetime import datetime, timedelta
        issued = datetime.now()
        expiry = issued + timedelta(days=365)
        
        return PerformanceLabel(
            label_id=f"WPL-{issued.strftime('%Y%m%d')}",
            label_type="WPL",
            rating=rating,
            score_value=water_score,
            issued_at=issued.isoformat(),
            expiry_date=expiry.isoformat()
        )

    def _calculate_rating(self, score: float) -> str:
        """Map normalized score (0-3) to A-F rating."""
        if score >= 2.5: return "A"
        if score >= 2.0: return "B"
        if score >= 1.5: return "C"
        if score >= 1.0: return "D"
        if score >= 0.5: return "E"
        return "F"
