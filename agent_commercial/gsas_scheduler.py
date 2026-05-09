"""
GSAS Recertification Scheduler
==============================

Automates reminders and compliance tracking for the 4-year 
GSAS Operations recertification cycle.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any

logger = logging.getLogger("arvis.gsas.scheduler")

class GSASScheduler:
    """Manages recertification milestones."""
    
    def __init__(self, last_cert_date: date = None):
        self.last_certification = last_cert_date or date.today()
        self.cycle_years = 4

    def get_timeline(self) -> List[Dict[str, Any]]:
        """Calculate key milestones for the 4-year cycle."""
        expiry = self.last_certification.replace(year=self.last_certification.year + self.cycle_years)
        
        milestones = [
            {
                "event": "Current Certification Issued",
                "date": self.last_certification.isoformat(),
                "status": "complete"
            },
            {
                "event": "Year 2 Operational Audit",
                "date": self.last_certification.replace(year=self.last_certification.year + 2).isoformat(),
                "status": "pending"
            },
            {
                "event": "Recertification Window Opens",
                "date": (expiry - timedelta(days=180)).isoformat(),
                "status": "pending"
            },
            {
                "event": "Certification Expiry",
                "date": expiry.isoformat(),
                "status": "critical"
            }
        ]
        
        # Determine current status
        today = date.today()
        for m in milestones:
            m_date = date.fromisoformat(m["date"])
            if m_date < today:
                m["status"] = "complete"
            elif (m_date - today).days < 30:
                m["status"] = "due_now"
                
        return milestones

    def get_days_to_expiry(self) -> int:
        expiry = self.last_certification.replace(year=self.last_certification.year + self.cycle_years)
        return (expiry - date.today()).days
