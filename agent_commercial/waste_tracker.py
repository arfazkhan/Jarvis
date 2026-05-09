"""
Waste Management Tracker
========================

Tracks waste generation, recycling, and diversion rates for GSAS MO.3 compliance.
Supports manual entry, document-extracted data, and future contractor APIs.
"""

import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Dict, List, Optional, Any

logger = logging.getLogger("arvis.gsas.waste")

@dataclass
class WasteRecord:
    """A single record of waste disposal/collection."""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    period_start: date = field(default_factory=date.today)
    period_end: date = field(default_factory=date.today)
    waste_type: str = "general"           # general, recyclable, organic, hazardous
    quantity_kg: float = 0.0
    disposal_method: str = "landfill"     # landfill, recycling, composting, incineration
    contractor: str = "Unknown"
    source: str = "manual"                # manual, ocr_extract, api
    evidence_file: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["period_start"] = self.period_start.isoformat()
        data["period_end"] = self.period_end.isoformat()
        data["created_at"] = self.created_at.isoformat()
        return data

class WasteTracker:
    """Manages waste records and calculates sustainability metrics."""
    
    def __init__(self):
        self.records: List[WasteRecord] = []

    def add_record(self, record: WasteRecord) -> None:
        """Add a new waste record to the tracker."""
        self.records.append(record)
        logger.info(f"Added waste record: {record.quantity_kg}kg of {record.waste_type} via {record.disposal_method}")

    def get_diversion_rate(self, days: int = 365) -> float:
        """
        Calculate the percentage of waste diverted from landfill.
        Formula: (Recycled + Composted) / Total Waste * 100
        """
        if not self.records:
            return 0.0
            
        cutoff = date.today().replace(year=date.today().year - 1) if days >= 365 else date.today() # Simplistic cutoff
        
        relevant_records = [r for r in self.records if r.period_end >= cutoff]
        if not relevant_records:
            return 0.0
            
        total_kg = sum(r.quantity_kg for r in relevant_records)
        if total_kg == 0:
            return 0.0
            
        diverted_kg = sum(r.quantity_kg for r in relevant_records if r.disposal_method in ["recycling", "composting"])
        
        rate = (diverted_kg / total_kg) * 100
        return round(rate, 2)

    def get_gsas_waste_data(self) -> Dict[str, Any]:
        """Format data for the GSASReporter."""
        return {
            "diversion_rate": self.get_diversion_rate(),
            "total_records": len(self.records),
            "last_record_date": self.records[-1].period_end.isoformat() if self.records else None
        }

    def get_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary breakdown for dashboard."""
        rate = self.get_diversion_rate(days)
        
        # Breakdown by type
        by_type = {}
        by_method = {}
        
        cutoff = date.today() # Filter here
        
        total_kg = 0
        for r in self.records:
            by_type[r.waste_type] = by_type.get(r.waste_type, 0.0) + r.quantity_kg
            by_method[r.disposal_method] = by_method.get(r.disposal_method, 0.0) + r.quantity_kg
            total_kg += r.quantity_kg
            
        return {
            "diversion_rate": rate,
            "total_kg": round(total_kg, 1),
            "breakdown_by_type": by_type,
            "breakdown_by_method": by_method,
            "record_count": len(self.records)
        }
