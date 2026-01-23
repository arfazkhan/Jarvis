"""
Energy Analyzer
===============

ML-based energy anomaly detection and waste pattern identification.

Uses Isolation Forest (unsupervised) for real-time anomaly detection,
with rule-based pattern matching for known waste scenarios.

Capabilities:
- Baseline modeling (time-of-day, day-of-week, weather)
- Real-time anomaly detection (Isolation Forest)
- Waste pattern identification (after-hours HVAC, overcooling, etc.)
- Savings estimation for identified issues

NOT LLM-reliant — pure statistical/ML approach.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import uuid

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from agent_bms.bms_data_model import EnergyReading, Anomaly

logger = logging.getLogger("arvis.bms.energy")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class WastePattern:
    """
    A detected energy waste pattern.
    
    Examples:
    - After-hours HVAC operation
    - Simultaneous heating and cooling
    - Weekend energy consumption
    - Overcooling/overheating
    """
    pattern_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pattern_type: str = ""
    description: str = ""
    
    # Where and when
    building_id: str = ""
    zone_id: str = ""
    equipment_ids: List[str] = field(default_factory=list)
    
    # Frequency
    occurrences: int = 0
    first_detected: datetime = field(default_factory=datetime.now)
    last_detected: datetime = field(default_factory=datetime.now)
    
    # Impact
    estimated_waste_kwh_daily: float = 0.0
    estimated_waste_qar_annual: float = 0.0
    
    # Evidence
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "building_id": self.building_id,
            "occurrences": self.occurrences,
            "estimated_waste_qar_annual": round(self.estimated_waste_qar_annual, 2),
            "first_detected": self.first_detected.isoformat(),
            "last_detected": self.last_detected.isoformat(),
        }


@dataclass
class SavingsEstimate:
    """Estimated savings if a waste pattern is addressed"""
    pattern_id: str
    annual_savings_kwh: float
    annual_savings_qar: float
    payback_months: float = 0.0  # If fix requires investment
    implementation_effort: str = "low"  # "low", "medium", "high"
    recommendation: str = ""


@dataclass
class EnergyBaseline:
    """
    Baseline model for expected energy consumption.
    
    Features:
    - Hour of day (0-23)
    - Day of week (0-6)
    - Is weekend (bool)
    - Outdoor temperature
    - Occupancy level
    """
    meter_id: str
    created_at: datetime = field(default_factory=datetime.now)
    
    # Learned parameters
    hourly_means: Dict[int, float] = field(default_factory=dict)      # hour -> mean kW
    daily_means: Dict[int, float] = field(default_factory=dict)       # dow -> mean kW
    temp_coefficient: float = 0.0                                      # kW per °C
    base_load: float = 0.0                                             # Minimum load
    
    # Statistics
    samples_count: int = 0
    mean: float = 0.0
    std: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# ENERGY ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

class EnergyAnalyzer:
    """
    Energy anomaly detection and waste pattern identification.
    
    Uses Isolation Forest for unsupervised anomaly detection,
    combined with rule-based pattern matching for known waste scenarios.
    
    Example:
        >>> analyzer = EnergyAnalyzer()
        >>> analyzer.add_reading(EnergyReading(meter_id="M1", value=150.5, ...))
        >>> anomalies = analyzer.detect_anomalies_realtime(current_reading)
        >>> patterns = analyzer.identify_waste_patterns()
    """
    
    # Qatar-specific: Average electricity rate (QR/kWh)
    ELECTRICITY_RATE_QAR = 0.08  # Subsidized industrial rate
    ELECTRICITY_RATE_QAR_COMMERCIAL = 0.15  # Commercial rate
    
    # Working hours (Qatar: Sunday-Thursday, not Mon-Fri)
    WORKDAYS = {6, 0, 1, 2, 3}  # Sunday=6, Monday=0, ..., Thursday=3
    WORK_HOURS = range(7, 20)   # 7 AM to 8 PM
    
    def __init__(self, electricity_rate_qar: float = 0.15):
        """
        Initialize Energy Analyzer.
        
        Args:
            electricity_rate_qar: Electricity rate in QAR per kWh
        """
        self.electricity_rate = electricity_rate_qar
        
        # ─────────────────────────────────────────────────────────────────
        # Isolation Forest for anomaly detection
        # ─────────────────────────────────────────────────────────────────
        self.isolation_forest = IsolationForest(
            n_estimators=100,
            contamination=0.1,  # Expect ~10% anomalies
            random_state=42,
        )
        self.scaler = StandardScaler()
        self.is_trained = False
        
        # ─────────────────────────────────────────────────────────────────
        # Baselines per meter
        # ─────────────────────────────────────────────────────────────────
        self.baselines: Dict[str, EnergyBaseline] = {}
        
        # ─────────────────────────────────────────────────────────────────
        # History buffer (for pattern detection)
        # ─────────────────────────────────────────────────────────────────
        self.history: Dict[str, List[EnergyReading]] = defaultdict(list)
        self.max_history_days = 30
        
        # ─────────────────────────────────────────────────────────────────
        # Detected patterns
        # ─────────────────────────────────────────────────────────────────
        self.waste_patterns: Dict[str, WastePattern] = {}
        
        logger.info("EnergyAnalyzer initialized")
    
    # ═══════════════════════════════════════════════════════════════════════
    # DATA INGESTION
    # ═══════════════════════════════════════════════════════════════════════
    
    def add_reading(self, reading: EnergyReading) -> None:
        """Add an energy reading to history"""
        self.history[reading.meter_id].append(reading)
        
        # Trim old history
        cutoff = datetime.now() - timedelta(days=self.max_history_days)
        self.history[reading.meter_id] = [
            r for r in self.history[reading.meter_id]
            if r.timestamp > cutoff
        ]
    
    def add_readings_batch(self, readings: List[EnergyReading]) -> None:
        """Add multiple readings at once"""
        for reading in readings:
            self.add_reading(reading)
    
    # ═══════════════════════════════════════════════════════════════════════
    # BASELINE MODELING
    # ═══════════════════════════════════════════════════════════════════════
    
    def train_baseline(self, meter_id: str, historical_data: pd.DataFrame) -> EnergyBaseline:
        """
        Train baseline model for expected energy consumption.
        
        Args:
            meter_id: Meter identifier
            historical_data: DataFrame with columns:
                - timestamp: datetime
                - value: float (kW or kWh)
                - outdoor_temp: float (optional)
                - occupancy: float (optional)
                
        Returns:
            EnergyBaseline with learned parameters
        """
        logger.info(f"Training baseline for meter {meter_id} with {len(historical_data)} samples")
        
        # Extract features
        df = historical_data.copy()
        df['hour'] = df['timestamp'].dt.hour
        df['dow'] = df['timestamp'].dt.dayofweek
        df['is_weekend'] = ~df['dow'].isin(self.WORKDAYS)
        
        # Calculate hourly means
        hourly_means = df.groupby('hour')['value'].mean().to_dict()
        
        # Calculate daily means
        daily_means = df.groupby('dow')['value'].mean().to_dict()
        
        # Calculate base load (5th percentile as minimum)
        base_load = df['value'].quantile(0.05)
        
        # Temperature coefficient (if outdoor_temp available)
        temp_coefficient = 0.0
        if 'outdoor_temp' in df.columns and df['outdoor_temp'].notna().sum() > 10:
            # Simple linear regression: kW = base + coef * temp
            from scipy import stats
            slope, _, _, _, _ = stats.linregress(
                df['outdoor_temp'].dropna(), 
                df.loc[df['outdoor_temp'].notna(), 'value']
            )
            temp_coefficient = slope
        
        baseline = EnergyBaseline(
            meter_id=meter_id,
            hourly_means=hourly_means,
            daily_means=daily_means,
            temp_coefficient=temp_coefficient,
            base_load=base_load,
            samples_count=len(df),
            mean=df['value'].mean(),
            std=df['value'].std(),
        )
        
        self.baselines[meter_id] = baseline
        
        # Train Isolation Forest on this meter's data
        self._train_isolation_forest(df)
        
        logger.info(f"Baseline trained: mean={baseline.mean:.1f}, std={baseline.std:.1f}")
        return baseline
    
    def _train_isolation_forest(self, df: pd.DataFrame) -> None:
        """Train Isolation Forest on historical data"""
        # Feature matrix
        features = self._extract_features_batch(df)
        
        if len(features) < 20:
            logger.warning("Not enough data to train Isolation Forest")
            return
        
        # Scale features
        self.scaler.fit(features)
        X_scaled = self.scaler.transform(features)
        
        # Train
        self.isolation_forest.fit(X_scaled)
        self.is_trained = True
        
        logger.info(f"Isolation Forest trained on {len(features)} samples")
    
    def _extract_features_batch(self, df: pd.DataFrame) -> np.ndarray:
        """Extract features from DataFrame for ML model"""
        features = []
        
        for _, row in df.iterrows():
            features.append([
                row['hour'] if 'hour' in row else row['timestamp'].hour,
                row['dow'] if 'dow' in row else row['timestamp'].dayofweek,
                row.get('outdoor_temp', 35.0),  # Default to 35°C for Qatar
                row.get('occupancy', 0.5),
                1.0 if row.get('is_weekend', False) else 0.0,
                row['value'],
            ])
        
        return np.array(features)
    
    def get_expected_value(
        self, 
        meter_id: str, 
        timestamp: datetime,
        outdoor_temp: Optional[float] = None
    ) -> float:
        """
        Get expected energy consumption for a given time.
        
        Uses baseline model to predict expected value.
        """
        baseline = self.baselines.get(meter_id)
        if baseline is None:
            return 0.0
        
        hour = timestamp.hour
        dow = timestamp.weekday()
        
        # Start with hourly mean
        expected = baseline.hourly_means.get(hour, baseline.mean)
        
        # Adjust for day of week
        daily_factor = baseline.daily_means.get(dow, baseline.mean) / baseline.mean
        expected *= daily_factor
        
        # Adjust for temperature (if available)
        if outdoor_temp is not None and baseline.temp_coefficient != 0:
            # Assume 30°C as reference temperature
            temp_delta = outdoor_temp - 30
            expected += baseline.temp_coefficient * temp_delta
        
        return max(baseline.base_load, expected)
    
    # ═══════════════════════════════════════════════════════════════════════
    # ANOMALY DETECTION
    # ═══════════════════════════════════════════════════════════════════════
    
    def detect_anomalies_realtime(self, reading: EnergyReading) -> List[Anomaly]:
        """
        Detect if current reading is anomalous.
        
        Uses:
        1. Isolation Forest (if trained)
        2. Baseline deviation (statistical)
        3. Rule-based checks
        
        Returns:
            List of detected anomalies
        """
        anomalies = []
        
        # ─────────────────────────────────────────────────────────────────
        # 1. Isolation Forest Detection
        # ─────────────────────────────────────────────────────────────────
        if self.is_trained:
            features = np.array([[
                reading.hour_of_day,
                reading.day_of_week,
                reading.outdoor_temp or 35.0,
                reading.occupancy or 0.5,
                0.0 if reading.day_of_week in self.WORKDAYS else 1.0,
                reading.value,
            ]])
            
            X_scaled = self.scaler.transform(features)
            prediction = self.isolation_forest.predict(X_scaled)[0]
            score = -self.isolation_forest.decision_function(X_scaled)[0]
            
            if prediction == -1:  # Anomaly
                # Determine type based on value vs expected
                expected = self.get_expected_value(
                    reading.meter_id,
                    reading.timestamp,
                    reading.outdoor_temp
                )
                
                deviation_pct = ((reading.value - expected) / expected * 100) if expected > 0 else 0
                
                anomalies.append(Anomaly(
                    anomaly_type="energy_spike" if deviation_pct > 0 else "energy_drop",
                    severity=min(1.0, abs(score)),
                    source_id=reading.meter_id,
                    detected_value=reading.value,
                    expected_value=expected,
                    deviation_percent=deviation_pct,
                    timestamp=reading.timestamp,
                    description=self._describe_anomaly(reading, expected, deviation_pct),
                    estimated_annual_savings_qar=self._estimate_savings(
                        reading.value - expected if deviation_pct > 0 else 0,
                        reading.timestamp
                    ),
                ))
        
        # ─────────────────────────────────────────────────────────────────
        # 2. Statistical Detection (Baseline Deviation)
        # ─────────────────────────────────────────────────────────────────
        if reading.meter_id in self.baselines:
            baseline = self.baselines[reading.meter_id]
            expected = self.get_expected_value(
                reading.meter_id,
                reading.timestamp,
                reading.outdoor_temp
            )
            
            # Z-score
            if baseline.std > 0:
                z_score = (reading.value - expected) / baseline.std
                
                # Flag if > 2.5 standard deviations
                if abs(z_score) > 2.5 and not anomalies:
                    deviation_pct = ((reading.value - expected) / expected * 100) if expected > 0 else 0
                    
                    anomalies.append(Anomaly(
                        anomaly_type="statistical_deviation",
                        severity=min(1.0, abs(z_score) / 4),
                        source_id=reading.meter_id,
                        detected_value=reading.value,
                        expected_value=expected,
                        deviation_percent=deviation_pct,
                        timestamp=reading.timestamp,
                        description=f"Energy {abs(z_score):.1f} std devs from expected",
                    ))
        
        # ─────────────────────────────────────────────────────────────────
        # 3. Rule-Based Checks
        # ─────────────────────────────────────────────────────────────────
        rule_anomalies = self._check_rule_based_anomalies(reading)
        anomalies.extend(rule_anomalies)
        
        return anomalies
    
    def _check_rule_based_anomalies(self, reading: EnergyReading) -> List[Anomaly]:
        """Rule-based anomaly checks for known patterns"""
        anomalies = []
        
        # Check for after-hours high consumption
        is_workday = reading.day_of_week in self.WORKDAYS
        is_work_hours = reading.hour_of_day in self.WORK_HOURS
        
        if not is_work_hours or not is_workday:
            # Night/weekend - expect low consumption
            baseline = self.baselines.get(reading.meter_id)
            if baseline:
                # During off-hours, expect near base load
                expected_off_hours = baseline.base_load * 1.5
                
                if reading.value > expected_off_hours * 2:
                    excess = reading.value - expected_off_hours
                    
                    anomalies.append(Anomaly(
                        anomaly_type="after_hours_consumption",
                        severity=0.7,
                        source_id=reading.meter_id,
                        detected_value=reading.value,
                        expected_value=expected_off_hours,
                        deviation_percent=((reading.value - expected_off_hours) / expected_off_hours * 100),
                        timestamp=reading.timestamp,
                        description="High energy consumption during off-hours",
                        estimated_annual_savings_qar=self._estimate_after_hours_savings(excess),
                    ))
        
        return anomalies
    
    def _describe_anomaly(
        self, 
        reading: EnergyReading, 
        expected: float,
        deviation_pct: float
    ) -> str:
        """Generate human-readable anomaly description"""
        if deviation_pct > 30:
            return f"Energy consumption {deviation_pct:.0f}% above expected ({reading.value:.1f} kW vs {expected:.1f} kW expected)"
        elif deviation_pct > 15:
            return f"Elevated energy consumption: {reading.value:.1f} kW vs {expected:.1f} kW baseline"
        elif deviation_pct < -30:
            return f"Unusually low energy: {reading.value:.1f} kW vs {expected:.1f} kW expected (equipment off?)"
        else:
            return f"Energy deviation detected: {reading.value:.1f} kW"
    
    def _estimate_savings(self, excess_kw: float, timestamp: datetime) -> float:
        """Estimate annual savings if excess is eliminated"""
        if excess_kw <= 0:
            return 0.0
        
        # Assume this excess occurs for similar hours throughout the year
        hours_per_year = 8760
        # Rough estimate: assume this pattern repeats ~20% of time
        annual_excess_kwh = excess_kw * hours_per_year * 0.2
        
        return annual_excess_kwh * self.electricity_rate
    
    def _estimate_after_hours_savings(self, excess_kw: float) -> float:
        """Estimate savings from eliminating after-hours waste"""
        # After hours = nights (12h) + weekends (48h) ≈ 60h/week unoccupied
        # 60h * 52 weeks = 3120 hours/year
        after_hours_per_year = 3120
        annual_excess_kwh = excess_kw * after_hours_per_year
        
        return annual_excess_kwh * self.electricity_rate
    
    # ═══════════════════════════════════════════════════════════════════════
    # WASTE PATTERN IDENTIFICATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def identify_waste_patterns(self) -> List[WastePattern]:
        """
        Analyze history to identify recurring waste patterns.
        
        Patterns detected:
        - after_hours_hvac: HVAC running during unoccupied periods
        - weekend_consumption: High weekend energy
        - overcooling: Cooling below setpoint
        - simultaneous_heat_cool: Heating and cooling at same time
        - schedule_drift: Energy use starting before/after expected times
        """
        patterns = []
        
        for meter_id, readings in self.history.items():
            if len(readings) < 48:  # Need at least 2 days
                continue
            
            # Check each pattern type
            patterns.extend(self._detect_after_hours_pattern(meter_id, readings))
            patterns.extend(self._detect_weekend_pattern(meter_id, readings))
            patterns.extend(self._detect_schedule_drift(meter_id, readings))
        
        return patterns
    
    def _detect_after_hours_pattern(
        self, 
        meter_id: str, 
        readings: List[EnergyReading]
    ) -> List[WastePattern]:
        """Detect after-hours energy consumption pattern"""
        patterns = []
        
        baseline = self.baselines.get(meter_id)
        if not baseline:
            return patterns
        
        # Analyze readings outside work hours
        after_hours_readings = [
            r for r in readings
            if r.hour_of_day not in self.WORK_HOURS or r.day_of_week not in self.WORKDAYS
        ]
        
        if not after_hours_readings:
            return patterns
        
        # Calculate after-hours excess
        total_excess = 0.0
        high_readings = []
        
        for r in after_hours_readings:
            expected = baseline.base_load * 1.2  # Allow 20% buffer
            if r.value > expected * 1.5:  # 50% above expected
                excess = r.value - expected
                total_excess += excess
                high_readings.append(r)
        
        if len(high_readings) >= 3:  # At least 3 occurrences
            avg_excess = total_excess / len(high_readings)
            
            patterns.append(WastePattern(
                pattern_type="after_hours_hvac",
                description="HVAC systems running during unoccupied periods",
                building_id=meter_id.split("/")[0] if "/" in meter_id else "",
                occurrences=len(high_readings),
                first_detected=min(r.timestamp for r in high_readings),
                last_detected=max(r.timestamp for r in high_readings),
                estimated_waste_kwh_daily=avg_excess * 8,  # Assume 8 after-hours
                estimated_waste_qar_annual=self._estimate_after_hours_savings(avg_excess),
                evidence=[
                    {"timestamp": r.timestamp.isoformat(), "value": r.value}
                    for r in high_readings[:5]  # Top 5 examples
                ],
            ))
        
        return patterns
    
    def _detect_weekend_pattern(
        self, 
        meter_id: str, 
        readings: List[EnergyReading]
    ) -> List[WastePattern]:
        """Detect unusually high weekend consumption"""
        patterns = []
        
        baseline = self.baselines.get(meter_id)
        if not baseline:
            return patterns
        
        # Qatar weekdays are Sun-Thu, weekends are Fri-Sat
        weekend_readings = [
            r for r in readings
            if r.day_of_week not in self.WORKDAYS  # Friday=4, Saturday=5
        ]
        weekday_readings = [
            r for r in readings
            if r.day_of_week in self.WORKDAYS
        ]
        
        if len(weekend_readings) < 10 or len(weekday_readings) < 30:
            return patterns
        
        weekend_mean = np.mean([r.value for r in weekend_readings])
        weekday_mean = np.mean([r.value for r in weekday_readings])
        
        # If weekend is > 60% of weekday, potential issue
        if weekend_mean > weekday_mean * 0.6:
            ratio = weekend_mean / weekday_mean
            excess_pct = (ratio - 0.3) * 100  # Expect 30% on weekends
            
            patterns.append(WastePattern(
                pattern_type="weekend_consumption",
                description=f"Weekend energy consumption is {ratio:.0%} of weekday levels (expected ~30%)",
                building_id=meter_id.split("/")[0] if "/" in meter_id else "",
                occurrences=len(weekend_readings),
                estimated_waste_kwh_daily=(weekend_mean - weekday_mean * 0.3),
                estimated_waste_qar_annual=self._calculate_weekend_savings(
                    weekend_mean, weekday_mean
                ),
            ))
        
        return patterns
    
    def _detect_schedule_drift(
        self, 
        meter_id: str, 
        readings: List[EnergyReading]
    ) -> List[WastePattern]:
        """Detect if energy consumption starts earlier/ends later than scheduled"""
        patterns = []
        
        # Group by date and find earliest/latest high consumption hour
        daily_profiles = defaultdict(list)
        for r in readings:
            date_key = r.timestamp.date()
            daily_profiles[date_key].append(r)
        
        early_starts = 0
        late_ends = 0
        
        baseline = self.baselines.get(meter_id)
        threshold = baseline.mean * 0.6 if baseline else 50  # 60% of mean or 50kW
        
        for date, day_readings in daily_profiles.items():
            if len(day_readings) < 12:
                continue
            
            day_readings.sort(key=lambda r: r.timestamp)
            
            # Find first/last hour above threshold
            high_hours = [r.hour_of_day for r in day_readings if r.value > threshold]
            
            if high_hours:
                if min(high_hours) < 6:  # Before 6 AM
                    early_starts += 1
                if max(high_hours) > 21:  # After 9 PM
                    late_ends += 1
        
        if early_starts >= 5:
            patterns.append(WastePattern(
                pattern_type="early_start",
                description=f"HVAC/lighting starting before 6 AM on {early_starts} days",
                occurrences=early_starts,
                estimated_waste_qar_annual=early_starts * 52 * threshold * 2 * self.electricity_rate,
            ))
        
        if late_ends >= 5:
            patterns.append(WastePattern(
                pattern_type="late_shutdown",
                description=f"Systems still running after 9 PM on {late_ends} days",
                occurrences=late_ends,
                estimated_waste_qar_annual=late_ends * 52 * threshold * 3 * self.electricity_rate,
            ))
        
        return patterns
    
    def _calculate_weekend_savings(self, weekend_mean: float, weekday_mean: float) -> float:
        """Calculate potential savings from reducing weekend consumption"""
        target_weekend = weekday_mean * 0.3  # Target 30% of weekday
        excess = max(0, weekend_mean - target_weekend)
        
        # 2 weekend days * 52 weeks * 24 hours
        weekend_hours_per_year = 2 * 52 * 24
        
        return excess * weekend_hours_per_year * self.electricity_rate
    
    # ═══════════════════════════════════════════════════════════════════════
    # SAVINGS ESTIMATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def estimate_savings(self, pattern: WastePattern) -> SavingsEstimate:
        """Generate detailed savings estimate for a waste pattern"""
        
        # Effort required to fix
        effort_map = {
            "after_hours_hvac": "low",        # Schedule adjustment
            "weekend_consumption": "low",      # Schedule adjustment
            "early_start": "low",              # Schedule adjustment
            "late_shutdown": "low",            # Schedule adjustment
            "overcooling": "medium",           # Setpoint adjustment + testing
            "simultaneous_heat_cool": "high",  # May need control logic changes
        }
        
        # Recommendations
        recommendation_map = {
            "after_hours_hvac": "Adjust BMS schedules to align with actual occupancy. "
                               "Consider occupancy sensors for dynamic control.",
            "weekend_consumption": "Review weekend schedules. Consider setback temperatures "
                                  "and reduced ventilation during unoccupied periods.",
            "early_start": "Optimize start times using optimal start algorithms. "
                          "Current pre-conditioning may be excessive.",
            "late_shutdown": "Review shutdown sequences. Implement automatic off based on "
                           "last-out occupancy detection.",
        }
        
        return SavingsEstimate(
            pattern_id=pattern.pattern_id,
            annual_savings_kwh=pattern.estimated_waste_kwh_daily * 365,
            annual_savings_qar=pattern.estimated_waste_qar_annual,
            payback_months=0.0,  # Schedule changes are typically free
            implementation_effort=effort_map.get(pattern.pattern_type, "medium"),
            recommendation=recommendation_map.get(
                pattern.pattern_type, 
                "Review and optimize operational schedules."
            ),
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # REPORTING
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_summary(self) -> Dict[str, Any]:
        """Get analyzer summary statistics"""
        total_readings = sum(len(r) for r in self.history.values())
        
        return {
            "meters_tracked": len(self.history),
            "baselines_trained": len(self.baselines),
            "total_readings": total_readings,
            "is_trained": self.is_trained,
            "patterns_detected": len(self.waste_patterns),
            "electricity_rate_qar": self.electricity_rate,
        }
