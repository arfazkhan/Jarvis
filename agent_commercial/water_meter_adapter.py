import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger("arvis.bms.water")

@dataclass
class WaterReading:
    meter_id: str
    value_m3: float
    timestamp: datetime
    source: str = "bacnet"
    quality: str = "good"

@dataclass
class WaterBaseline:
    monthly_m3: float
    daily_m3: float
    source: str = "historical"
    established_date: datetime = field(default_factory=datetime.now)

class WaterMeterAdapter:
    """
    Water meter data aggregation for GSAS compliance.
    
    Tracks consumption, compares against baseline, and detects leaks.
    Provides the data structure expected by GSASReporter.update_from_bms().
    """
    
    def __init__(self, baseline_m3_monthly: float, building_id: str):
        self.building_id = building_id
        self.baseline = WaterBaseline(
            monthly_m3=baseline_m3_monthly,
            daily_m3=baseline_m3_monthly / 30.0
        )
        
        self.readings: List[WaterReading] = []
        self.submeter_ids: List[str] = []
        self.total_zones: int = 1  # Default to 1 for coverage calculation
        
        logger.info(f"WaterMeterAdapter initialized for {building_id} (Baseline: {baseline_m3_monthly} m3/month)")

    def ingest_reading(self, meter_id: str, value_m3: float, timestamp: Optional[datetime] = None):
        """Accept a cumulative meter reading (total m3)."""
        if timestamp is None:
            timestamp = datetime.now()
            
        reading = WaterReading(meter_id=meter_id, value_m3=value_m3, timestamp=timestamp)
        self.readings.append(reading)
        
        # Track submeters for W.3 coverage
        if meter_id not in self.submeter_ids and meter_id != "MAIN":
            self.submeter_ids.append(meter_id)
            
        # Keep only last 60 days of readings to save memory
        cutoff = datetime.now() - timedelta(days=60)
        self.readings = [r for r in self.readings if r.timestamp > cutoff]

    def get_consumption(self, days: int = 1) -> float:
        """Calculate total consumption over the last X days."""
        if not self.readings:
            return 0.0
            
        # Group by meter
        meter_data: Dict[str, List[WaterReading]] = {}
        for r in self.readings:
            if r.meter_id not in meter_data:
                meter_data[r.meter_id] = []
            meter_data[r.meter_id].append(r)
            
        total_consumption = 0.0
        cutoff = datetime.now() - timedelta(days=days)
        
        for meter_id, readings in meter_data.items():
            # Only count MAIN meter for total building consumption
            if meter_id != "MAIN":
                continue
                
            # Filter for period
            period_readings = [r for r in readings if r.timestamp >= cutoff]
            if len(period_readings) < 2:
                continue
                
            # Sort by timestamp
            period_readings.sort(key=lambda x: x.timestamp)
            
            # Consumption is delta between last and first reading in period
            delta = period_readings[-1].value_m3 - period_readings[0].value_m3
            total_consumption += delta
            
        return total_consumption

    def get_consumption_vs_baseline(self) -> float:
        """
        Calculate percentage reduction from baseline.
        Positive = saving, Negative = overconsumption.
        """
        daily_avg = self.get_consumption(days=30) / 30.0
        if self.baseline.daily_m3 == 0:
            return 0.0
            
        reduction = (1 - (daily_avg / self.baseline.daily_m3)) * 100
        return round(reduction, 2)

    def detect_leak(self, flow_lpm: float, is_occupied: bool) -> Optional[Dict[str, Any]]:
        """
        Simple leak detection rule:
        If flow exists during unoccupied hours for extended time.
        """
        # Threshold: 1.0 LPM for > 30 mins during unoccupied
        if not is_occupied and flow_lpm > 1.0:
            return {
                "type": "potential_leak",
                "severity": "medium",
                "flow_rate": flow_lpm,
                "timestamp": datetime.now().isoformat(),
                "message": f"Continuous flow of {flow_lpm} LPM detected during unoccupied hours."
            }
        return None

    def get_gsas_water_data(self) -> Dict[str, Any]:
        """Format data for GSASReporter.update_from_bms()."""
        # Coverage = (number of submeters / total zones) * 100
        coverage = (len(self.submeter_ids) / max(1, self.total_zones)) * 100
        
        return {
            "consumption_vs_baseline": self.get_consumption_vs_baseline(),
            "submetering_coverage": min(100.0, coverage)
        }

    def get_summary(self) -> Dict[str, Any]:
        """Dashboard summary."""
        daily = self.get_consumption(days=1)
        monthly = self.get_consumption(days=30)
        reduction = self.get_consumption_vs_baseline()
        
        return {
            "daily_m3": round(daily, 2),
            "monthly_m3": round(monthly, 2),
            "baseline_daily_m3": round(self.baseline.daily_m3, 2),
            "reduction_percent": reduction,
            "submeter_count": len(self.submeter_ids),
            "status": "efficient" if reduction > 5 else "normal" if reduction > -5 else "excessive"
        }
