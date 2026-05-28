"""
Fleet Intelligence Engine
=========================

Cross-building analytics and best practice sharing for building portfolios.

Capabilities:
- Benchmark building against fleet
- Cross-pollinate optimization insights
- Identify best practices and laggards
- Share learnings across buildings

Usage:
    >>> fleet = FleetIntelligence(["tower_a", "tower_b", "tower_c"])
    >>> benchmark = fleet.benchmark_building("tower_a")
    >>> print(benchmark["percentile_rank"])
"""

import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("arvis.bms.fleet")


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class BuildingMetrics:
    """Performance metrics for a building"""
    building_id: str
    building_name: str
    eui: float  # Energy Use Intensity (kWh/m²/year)
    water_intensity: float  # m³/m²/year
    gsas_score: float  # 0-100
    equipment_count: int
    active_alarms: int
    mtbf_hours: float  # Mean Time Between Failures
    optimization_savings_qar: float
    square_footage: float = 10000.0  # m² (GFA)
    occupancy_type: str = "office"  # office, retail, hospital, mixed, residential
    gsas_star_rating: float = 0.0  # e.g., 3.0 for 3 stars
    gsas_disqualification_risk: bool = False  # True if E or W is in warning zone
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_id": self.building_id,
            "building_name": self.building_name,
            "eui": round(self.eui, 1),
            "water_intensity": round(self.water_intensity, 3),
            "gsas_score": round(self.gsas_score, 1),
            "equipment_count": self.equipment_count,
            "active_alarms": self.active_alarms,
            "mtbf_hours": round(self.mtbf_hours, 0),
            "optimization_savings_qar": round(self.optimization_savings_qar, 0),
            "square_footage": self.square_footage,
            "occupancy_type": self.occupancy_type,
            "gsas_star_rating": round(self.gsas_star_rating, 2),
            "gsas_disqualification_risk": self.gsas_disqualification_risk,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class BenchmarkResult:
    """Result of benchmarking a building against fleet"""
    building_id: str
    percentile_rank: Dict[str, float]  # Metric -> percentile (0-100)
    best_in_class: List[Dict[str, Any]]  # Metrics where building is best
    improvement_opportunities: List[Dict[str, Any]]  # Areas to improve
    potential_savings_qar: float
    fleet_avg: Dict[str, float]
    fleet_best: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_id": self.building_id,
            "percentile_rank": self.percentile_rank,
            "best_in_class": self.best_in_class,
            "improvement_opportunities": self.improvement_opportunities,
            "potential_savings_qar": round(self.potential_savings_qar, 0),
            "fleet_avg": self.fleet_avg,
            "fleet_best": self.fleet_best,
        }


@dataclass
class SharedInsight:
    """An insight that can be shared across buildings"""
    insight_id: str
    source_building: str
    insight_type: str  # optimization, quirk, failure_pattern
    title: str
    description: str
    conditions: Dict[str, Any]  # When this insight applies
    impact: Dict[str, Any]  # Measured impact
    confidence: float
    applicable_buildings: List[str]
    gsas_criterion: Optional[str] = None  # Tag insight with GSAS relevance (e.g., "E.1")
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "source_building": self.source_building,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "conditions": self.conditions,
            "impact": self.impact,
            "confidence": round(self.confidence, 2),
            "applicable_buildings": self.applicable_buildings,
            "gsas_criterion": self.gsas_criterion,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# FLEET INTELLIGENCE ENGINE
# =============================================================================

class FleetIntelligence:
    """
    Cross-building analytics and best practice sharing.
    
    For portfolios with multiple buildings, learns what works
    in one building and suggests it for others.
    """
    
    def __init__(self,
                 building_ids: List[str],
                 db_path: Optional[str] = None):
        """
        Initialize Fleet Intelligence.
        
        Args:
            building_ids: List of building IDs in the fleet
            db_path: Path to fleet database
        """
        self.building_ids = building_ids
        
        # Database path. Honors ARVIS_DB_PATH for per-run isolation.
        if db_path is None:
            import os as _os
            _env_db = _os.getenv("ARVIS_DB_PATH", "").strip()
            if _env_db:
                db_path = _env_db
            else:
                db_dir = Path(__file__).parent / "data"
                db_dir.mkdir(exist_ok=True)
                db_path = str(db_dir / "arvis_bms.db")

        self.db_path = db_path
        self._init_database()
        
        # Metrics cache
        self._metrics_cache: Dict[str, BuildingMetrics] = {}
        
        logger.info(f"FleetIntelligence initialized with {len(building_ids)} buildings")
    
    def _get_conn(self):
        """Helper to get a thread-safe connection with timeout and WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_database(self) -> None:
        """Initialize fleet database tables."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fleet_metrics (
                    building_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL,
                    timestamp TEXT,
                    PRIMARY KEY (building_id, metric_name)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fleet_insights (
                    insight_id TEXT PRIMARY KEY,
                    source_building TEXT NOT NULL,
                    insight_type TEXT,
                    title TEXT,
                    description TEXT,
                    conditions TEXT,
                    impact TEXT,
                    confidence REAL,
                    applicable_buildings TEXT,
                    gsas_criterion TEXT,
                    created_at TEXT
                )
            """)
            
            try:
                conn.execute("ALTER TABLE fleet_insights ADD COLUMN gsas_criterion TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            conn.commit()
    
    def add_building(self, building_id: str) -> None:
        """Add a building to the fleet."""
        if building_id not in self.building_ids:
            self.building_ids.append(building_id)
            logger.info(f"Added building to fleet: {building_id}")
    
    def update_metrics(self, building_id: str, metrics: Dict[str, float]) -> None:
        """Update metrics for a building."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout=60000")
            for name, value in metrics.items():
                conn.execute("""
                    INSERT OR REPLACE INTO fleet_metrics 
                    (building_id, metric_name, metric_value, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (building_id, name, value, datetime.now().isoformat()))
            conn.commit()
        
        # Invalidate cache
        if building_id in self._metrics_cache:
            del self._metrics_cache[building_id]
    
    def get_metrics(self, building_id: str) -> BuildingMetrics:
        """Get current metrics for a building."""
        if building_id in self._metrics_cache:
            cache = self._metrics_cache[building_id]
            # Check if cache is fresh (< 1 hour)
            if (datetime.now() - cache.timestamp).total_seconds() < 3600:
                return cache
        
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT metric_name, metric_value 
                FROM fleet_metrics 
                WHERE building_id = ?
            """, (building_id,))
            
            metrics = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Build metrics object with defaults
        building_metrics = BuildingMetrics(
            building_id=building_id,
            building_name=self._get_building_name(building_id),
            eui=metrics.get("eui", 150),
            water_intensity=metrics.get("water_intensity", 0.5),
            gsas_score=metrics.get("gsas_score", 70),
            equipment_count=int(metrics.get("equipment_count", 50)),
            active_alarms=int(metrics.get("active_alarms", 5)),
            mtbf_hours=metrics.get("mtbf_hours", 2000),
            optimization_savings_qar=metrics.get("optimization_savings_qar", 0),
            square_footage=metrics.get("square_footage", 10000.0),
            occupancy_type=self._get_occupancy_type(building_id, metrics),
            gsas_star_rating=metrics.get("gsas_star_rating", 0.0),
            gsas_disqualification_risk=bool(metrics.get("gsas_disqualification_risk", 0)),
        )
        
        self._metrics_cache[building_id] = building_metrics
        return building_metrics
    
    def _get_building_name(self, building_id: str) -> str:
        """Get building display name from DB or derive from ID."""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "SELECT name FROM fleet_buildings WHERE building_id = ?", (building_id,)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception:
            pass
        return building_id.replace("_", " ").title()

    def _get_occupancy_type(self, building_id: str, metrics: Dict[str, float]) -> str:
        """Get occupancy type from DB or infer from metrics."""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "SELECT occupancy_type FROM fleet_buildings WHERE building_id = ?", (building_id,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]
        except Exception:
            pass
        return "office"

    def register_building(
        self,
        building_id: str,
        name: str,
        square_footage: float,
        occupancy_type: str = "office",
        location: str = "",
    ) -> None:
        """Register a building with its physical characteristics."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fleet_buildings (
                    building_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    square_footage REAL NOT NULL,
                    occupancy_type TEXT DEFAULT 'office',
                    location TEXT DEFAULT '',
                    registered_at TEXT
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO fleet_buildings
                (building_id, name, square_footage, occupancy_type, location, registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (building_id, name, square_footage, occupancy_type, location, datetime.now().isoformat()))
            conn.commit()

        self.update_metrics(building_id, {"square_footage": square_footage})
        self.add_building(building_id)
        logger.info(f"Registered building: {name} ({building_id}), {square_footage}m², type={occupancy_type}")
    
    def benchmark_building(self, 
                          building_id: str,
                          metrics: Optional[List[str]] = None) -> BenchmarkResult:
        """
        Benchmark a building against the fleet.
        
        Args:
            building_id: Building to benchmark
            metrics: Metrics to compare (default: all)
            
        Returns:
            BenchmarkResult with rankings and opportunities
        """
        if metrics is None:
            metrics = ["eui", "water_intensity", "gsas_score", "mtbf_hours"]
        
        # Get all building metrics
        fleet_data = [self.get_metrics(bid) for bid in self.building_ids]
        target = next((m for m in fleet_data if m.building_id == building_id), None)
        
        if not target:
            target = self.get_metrics(building_id)
            fleet_data.append(target)
        
        # Calculate percentiles
        percentile_rank = {}
        fleet_avg = {}
        fleet_best = {}
        best_in_class = []
        opportunities = []
        
        for metric in metrics:
            values = [getattr(m, metric) for m in fleet_data]
            target_value = getattr(target, metric)
            
            # Calculate percentile (higher is better for GSAS, lower for EUI)
            if metric in ["gsas_score", "gsas_star_rating", "mtbf_hours", "optimization_savings_qar"]:
                # Higher is better
                percentile = sum(1 for v in values if v <= target_value) / len(values) * 100
                best_value = max(values)
            else:
                # Lower is better (EUI, water, alarms)
                percentile = sum(1 for v in values if v >= target_value) / len(values) * 100
                best_value = min(values)
            
            percentile_rank[metric] = round(percentile, 1)
            fleet_avg[metric] = round(sum(values) / len(values), 2)
            fleet_best[metric] = round(best_value, 2)
            
            # Check if best in class
            if target_value == best_value:
                best_in_class.append({
                    "metric": metric,
                    "value": target_value,
                    "description": f"Best in fleet for {metric}",
                })
            
            # Identify opportunities
            if percentile < 50:
                gap = abs(target_value - fleet_avg[metric])
                opportunities.append({
                    "metric": metric,
                    "current": target_value,
                    "target": fleet_avg[metric],
                    "gap": round(gap, 2),
                    "percentile": percentile_rank[metric],
                    "action": self._get_improvement_action(metric, target_value, fleet_avg[metric]),
                })
        
        # Estimate potential savings
        potential_savings = self._estimate_savings(target, opportunities)
        
        return BenchmarkResult(
            building_id=building_id,
            percentile_rank=percentile_rank,
            best_in_class=best_in_class,
            improvement_opportunities=sorted(opportunities, key=lambda x: x["percentile"]),
            potential_savings_qar=potential_savings,
            fleet_avg=fleet_avg,
            fleet_best=fleet_best,
        )
    
    def _get_improvement_action(self, 
                                metric: str,
                                current: float,
                                target: float) -> str:
        """Get improvement action for a metric gap."""
        actions = {
            "eui": f"Reduce EUI by {abs(current - target):.0f} kWh/m²/year through optimization",
            "water_intensity": f"Reduce water use by {abs(current - target):.2f} m³/m²/year",
            "gsas_score": f"Improve GSAS score by {abs(target - current):.0f} points",
            "mtbf_hours": "Improve preventive maintenance to increase MTBF",
            "active_alarms": f"Reduce active alarms by {abs(current - target):.0f}",
        }
        return actions.get(metric, f"Improve {metric} to match fleet average")
    
    def _estimate_savings(self,
                          target: BuildingMetrics,
                          opportunities: List[Dict]) -> float:
        """Estimate potential savings from improvements using actual building area."""
        savings = 0
        area = target.square_footage

        for opp in opportunities:
            if opp["metric"] == "eui":
                eui_reduction = abs(opp["gap"])
                savings += eui_reduction * area * 0.05  # QAR 0.05/kWh average
            elif opp["metric"] == "water_intensity":
                water_reduction = abs(opp["gap"])
                savings += water_reduction * area * 4.8  # QAR 4.8/m³

        return savings
    
    def cross_pollinate_insights(self) -> List[SharedInsight]:
        """
        Share learnings across buildings.
        
        Finds optimizations that worked in one building
        and suggests them for similar buildings.
        """
        insights = []
        
        # Get high-confidence insights from skillbooks
        for building_id in self.building_ids:
            try:
                from agent_commercial.skillbook import get_skillbook
                skillbook = get_skillbook(building_id)
                
                # Get high-confidence optimizations
                optimizations = skillbook.get_optimization_history()
                for opt in optimizations:
                    if opt.confidence >= 0.8 and opt.evidence.get("savings_qar_month", 0) > 1000:
                        # This is a significant, verified optimization
                        # Suggest it to other buildings
                        applicable = [bid for bid in self.building_ids if bid != building_id]
                        
                        impact = {"savings_qar_month": opt.evidence.get("savings_qar_month", 0)}
                        gsas_criterion = opt.evidence.get("gsas_criterion")
                        if gsas_criterion:
                            impact["gsas_score_delta"] = opt.evidence.get("gsas_score_delta", 0)
                            
                        insights.append(SharedInsight(
                            insight_id=f"fleet_{opt.skill_id}",
                            source_building=building_id,
                            insight_type="optimization",
                            title=opt.title,
                            description=opt.description,
                            conditions={"equipment_type": opt.equipment_id.split("-")[0] if opt.equipment_id else None},
                            impact=impact,
                            confidence=opt.confidence,
                            applicable_buildings=applicable,
                            gsas_criterion=gsas_criterion,
                        ))
                        
            except Exception as e:
                logger.debug(f"Could not get skillbook for {building_id}: {e}")
        
        # Save insights to database
        for insight in insights:
            self._save_insight(insight)
        
        return insights
    
    def _save_insight(self, insight: SharedInsight) -> None:
        """Save insight to database."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO fleet_insights
                (insight_id, source_building, insight_type, title, description,
                 conditions, impact, confidence, applicable_buildings, gsas_criterion, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                insight.insight_id,
                insight.source_building,
                insight.insight_type,
                insight.title,
                insight.description,
                json.dumps(insight.conditions),
                json.dumps(insight.impact),
                insight.confidence,
                json.dumps(insight.applicable_buildings),
                insight.gsas_criterion,
                insight.created_at.isoformat(),
            ))
            conn.commit()
    
    def get_insights_for_building(self, building_id: str) -> List[SharedInsight]:
        """Get insights applicable to a specific building."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT 
                    insight_id, source_building, insight_type, title, description,
                    conditions, impact, confidence, applicable_buildings, created_at,
                    gsas_criterion
                FROM fleet_insights
                WHERE applicable_buildings LIKE ?
                ORDER BY confidence DESC
            """, (f'%"{building_id}"%',))
            
            target_archetype = self.detect_archetype(building_id)["archetype"]
            
            insights = []
            for row in cursor.fetchall():
                source_building = row[1]
                base_confidence = row[7]
                
                # Transfer confidence adjustment based on archetype match
                source_archetype = self.detect_archetype(source_building)["archetype"]
                adjusted_confidence = base_confidence if source_archetype == target_archetype else base_confidence * 0.8
                
                insights.append(SharedInsight(
                    insight_id=row[0],
                    source_building=source_building,
                    insight_type=row[2],
                    title=row[3],
                    description=row[4],
                    conditions=json.loads(row[5]) if row[5] else {},
                    impact=json.loads(row[6]) if row[6] else {},
                    confidence=adjusted_confidence,
                    applicable_buildings=json.loads(row[8]) if row[8] else [],
                    created_at=datetime.fromisoformat(row[9]),
                    gsas_criterion=row[10] if len(row) > 10 else None
                ))
            
            return sorted(insights, key=lambda x: x.confidence, reverse=True)
    
    def detect_archetype(self, building_id: str) -> Dict[str, Any]:
        """
        Classify building as gulf_tower, mall_retail, hospital_24x7, campus_distributed, or mixed_use.
        Based on occupancy pattern, cooling demand profile, energy density, water intensity.
        """
        metrics = self.get_metrics(building_id)
        
        # Simplified classification logic based on available metrics
        archetype = "mixed_use"
        defaults = {"temp_setpoint": 23.0, "co2_threshold": 800}
        
        if metrics.eui > 300 and metrics.water_intensity > 2.0:
            archetype = "hospital_24x7"
            defaults = {"temp_setpoint": 22.0, "co2_threshold": 600}
        elif metrics.eui > 250:
            archetype = "mall_retail"
            defaults = {"temp_setpoint": 24.0, "co2_threshold": 1000}
        elif metrics.eui < 150 and metrics.equipment_count > 500:
            archetype = "campus_distributed"
            defaults = {"temp_setpoint": 24.0, "co2_threshold": 900}
        elif metrics.equipment_count > 200:
            archetype = "gulf_tower"
            defaults = {"temp_setpoint": 23.5, "co2_threshold": 800}
            
        return {
            "building_id": building_id,
            "archetype": archetype,
            "optimization_defaults": defaults,
            "confidence": 0.85
        }
    
    def get_all_metrics(self) -> List[BuildingMetrics]:
        """Batch-fetch metrics for all buildings in one DB query."""
        if not self.building_ids:
            return []

        placeholders = ",".join("?" for _ in self.building_ids)
        with self._get_conn() as conn:
            cursor = conn.execute(
                f"SELECT building_id, metric_name, metric_value FROM fleet_metrics WHERE building_id IN ({placeholders})",
                self.building_ids,
            )
            rows = cursor.fetchall()

        by_building: Dict[str, Dict[str, float]] = {}
        for bid, metric_name, metric_value in rows:
            if bid not in by_building:
                by_building[bid] = {}
            by_building[bid][metric_name] = metric_value

        results = []
        for bid in self.building_ids:
            m = by_building.get(bid, {})
            bm = BuildingMetrics(
                building_id=bid,
                building_name=self._get_building_name(bid),
                eui=m.get("eui", 150),
                water_intensity=m.get("water_intensity", 0.5),
                gsas_score=m.get("gsas_score", 70),
                equipment_count=int(m.get("equipment_count", 50)),
                active_alarms=int(m.get("active_alarms", 5)),
                mtbf_hours=m.get("mtbf_hours", 2000),
                optimization_savings_qar=m.get("optimization_savings_qar", 0),
                square_footage=m.get("square_footage", 10000.0),
                occupancy_type=self._get_occupancy_type(bid, m),
                gsas_star_rating=m.get("gsas_star_rating", 0.0),
                gsas_disqualification_risk=bool(m.get("gsas_disqualification_risk", 0)),
            )
            self._metrics_cache[bid] = bm
            results.append(bm)
        return results

    def get_fleet_summary(self) -> Dict[str, Any]:
        """Get summary of fleet performance."""
        metrics = self.get_all_metrics()
        
        if not metrics:
            return {"buildings": 0, "error": "No buildings in fleet"}
        
        gsas_compliant_count = sum(1 for m in metrics if m.gsas_star_rating >= 1.0)
        disqualification_exposure = sum(1 for m in metrics if m.gsas_disqualification_risk)
        
        return {
            "buildings": len(metrics),
            "avg_eui": round(sum(m.eui for m in metrics) / len(metrics), 1),
            "avg_gsas_score": round(sum(m.gsas_score for m in metrics) / len(metrics), 1),
            "avg_gsas_star_rating": round(sum(m.gsas_star_rating for m in metrics) / len(metrics), 2),
            "gsas_compliance_coverage_percent": round((gsas_compliant_count / len(metrics)) * 100, 1),
            "disqualification_exposure_count": disqualification_exposure,
            "total_equipment": sum(m.equipment_count for m in metrics),
            "total_active_alarms": sum(m.active_alarms for m in metrics),
            "total_optimization_savings": round(sum(m.optimization_savings_qar for m in metrics), 0),
            "best_eui": {"building": min(metrics, key=lambda m: m.eui).building_id,
                        "value": min(m.eui for m in metrics)},
            "best_gsas": {"building": max(metrics, key=lambda m: m.gsas_score).building_id,
                         "value": max(m.gsas_score for m in metrics)},
        }
    
    def identify_best_practices(self) -> List[Dict[str, Any]]:
        """Identify what top-performing buildings are doing."""
        metrics = [self.get_metrics(bid) for bid in self.building_ids]
        
        if len(metrics) < 3:
            return []
        
        # Sort by EUI (lower is better)
        by_eui = sorted(metrics, key=lambda m: m.eui)
        top_performers = by_eui[:max(1, len(by_eui) // 3)]
        
        practices = []
        for building in top_performers:
            practices.append({
                "building_id": building.building_id,
                "building_name": building.building_name,
                "eui": building.eui,
                "rank": by_eui.index(building) + 1,
                "practices": self._get_building_practices(building.building_id),
            })
        
        return practices
    
    def _get_building_practices(self, building_id: str) -> List[str]:
        """Get documented practices for a building."""
        try:
            from agent_commercial.skillbook import get_skillbook
            skillbook = get_skillbook(building_id)
            optimizations = skillbook.get_optimization_history()
            return [opt.title for opt in optimizations if opt.confidence >= 0.7]
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug(f"Skillbook lookup fallback for {building_id}: {e}")
            return []


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_fleet: Optional[FleetIntelligence] = None


def get_fleet_intelligence(building_ids: Optional[List[str]] = None) -> FleetIntelligence:
    """Get or create fleet intelligence instance."""
    global _fleet
    
    if _fleet is None:
        if building_ids is None:
            building_ids = []
            try:
                from pathlib import Path
                import sqlite3
                db_path = str(Path(__file__).parent / "data" / "arvis_bms.db")
                with sqlite3.connect(db_path, timeout=30.0) as conn:
                    conn.execute("PRAGMA busy_timeout=60000")
                    cursor = conn.execute("SELECT DISTINCT building_id FROM fleet_metrics")
                    building_ids = [row[0] for row in cursor.fetchall()]
            except Exception:
                pass
            if not building_ids:
                building_ids = ["default_building"]
        _fleet = FleetIntelligence(building_ids)
    elif building_ids:
        for bid in building_ids:
            _fleet.add_building(bid)
    
    return _fleet


# =============================================================================
# LLM TOOL HANDLER
# =============================================================================

def compare_to_fleet(
    building_id: str,
    metrics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Benchmark a building against the portfolio fleet.
    
    This is the LLM tool handler.
    
    Args:
        building_id: Building to benchmark
        metrics: Metrics to compare (default: eui, water, gsas, mtbf)
        
    Returns:
        Benchmark results with rankings and improvement opportunities
    """
    fleet = get_fleet_intelligence()
    fleet.add_building(building_id)
    
    result = fleet.benchmark_building(building_id, metrics)
    summary = fleet.get_fleet_summary()
    
    return {
        "benchmark": result.to_dict(),
        "fleet_summary": summary,
    }


if __name__ == "__main__":
    # Test fleet intelligence
    print("=" * 60)
    print("Fleet Intelligence Test")
    print("=" * 60)
    
    # Create fleet with mock buildings
    fleet = FleetIntelligence(["tower_a", "tower_b", "tower_c", "tower_d", "tower_e"])
    
    # Update metrics for each building
    fleet.update_metrics("tower_a", {
        "eui": 142,
        "water_intensity": 0.45,
        "gsas_score": 76,
        "mtbf_hours": 2400,
    })
    
    fleet.update_metrics("tower_b", {
        "eui": 118,  # Best
        "water_intensity": 0.52,
        "gsas_score": 82,
        "mtbf_hours": 3200,
    })
    
    fleet.update_metrics("tower_c", {
        "eui": 155,
        "water_intensity": 0.38,  # Best
        "gsas_score": 71,
        "mtbf_hours": 1800,
    })
    
    fleet.update_metrics("tower_d", {
        "eui": 198,  # Worst
        "water_intensity": 0.65,
        "gsas_score": 68,
        "mtbf_hours": 1200,
    })
    
    fleet.update_metrics("tower_e", {
        "eui": 135,
        "water_intensity": 0.48,
        "gsas_score": 79,
        "mtbf_hours": 2800,
    })
    
    # Benchmark tower_a
    result = fleet.benchmark_building("tower_a")
    
    print(f"\n📊 Benchmark: Tower A vs Fleet")
    print(f"\nPercentile Rankings:")
    for metric, pct in result.percentile_rank.items():
        print(f"   {metric}: {pct:.0f}th percentile")
    
    if result.best_in_class:
        print(f"\n🏆 Best in Class:")
        for item in result.best_in_class:
            print(f"   {item['metric']}")
    
    if result.improvement_opportunities:
        print(f"\n📈 Improvement Opportunities:")
        for opp in result.improvement_opportunities[:3]:
            print(f"   {opp['metric']}: {opp['current']} → {opp['target']} ({opp['action']})")
    
    print(f"\n💰 Potential Savings: QAR {result.potential_savings_qar:,.0f}/year")
    
    # Fleet summary
    summary = fleet.get_fleet_summary()
    print(f"\n📋 Fleet Summary:")
    print(f"   Buildings: {summary['buildings']}")
    print(f"   Avg EUI: {summary['avg_eui']} kWh/m²/year")
    print(f"   Best EUI: {summary['best_eui']['building']} ({summary['best_eui']['value']})")
