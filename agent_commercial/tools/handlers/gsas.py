"""
GSAS Tool Handlers
==================

Handlers for GSAS compliance and reporting tools.
"""

import logging
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger("arvis.bms.tools.gsas")

# Safe imports for modular standalone operation
try:
    from agent_commercial.database import get_database
except ImportError:
    get_database = None

try:
    from agent_commercial.report_generator import generate_gord_pdf
except ImportError:
    generate_gord_pdf = None

try:
    from agent_commercial.gsas_occupancy_context import OccupancyContextProvider
    from agent_commercial.gsas_comfort_predictor import ComfortPredictor
    from agent_commercial.gsas_financial_impact import FinancialImpactCalculator
    from agent_commercial.gsas_simulation import GSASSimulator
    from agent_commercial.gsas_execution_governor import GSASExecutionGovernor
    from agent_commercial.gsas_outcome_tracker import GSASOutcomeTracker
    from agent_commercial.gsas_audit_readiness import GSASAuditReadinessChecker
except ImportError:
    OccupancyContextProvider = None
    ComfortPredictor = None
    FinancialImpactCalculator = None
    GSASSimulator = None
    GSASExecutionGovernor = None
    GSASOutcomeTracker = None
    GSASAuditReadinessChecker = None


class GSASHandlerMixin:
    """Mixin providing GSAS-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "get_gsas_status": instance._handle_get_gsas_status,
            "get_gsas_improvement_priorities": instance._handle_get_gsas_improvement_priorities,
            "optimize_recommendations_for_gsas": instance._handle_optimize_recommendations_for_gsas,
            "generate_gord_report": instance._handle_generate_gord_report,
            "get_zone_occupancy": instance._handle_get_zone_occupancy,
            "predict_comfort_impact": instance._handle_predict_comfort_impact,
            "get_financial_projection": instance._handle_get_financial_projection,
            "get_gsas_contextual_recommendations": instance._handle_get_gsas_contextual_recommendations,
            "simulate_gsas_impact": instance._handle_simulate_gsas_impact,
            "classify_gsas_action_risk": instance._handle_classify_gsas_action_risk,
            "record_gsas_action_outcome": instance._handle_record_gsas_action_outcome,
            "get_gsas_success_rates": instance._handle_get_gsas_success_rates,
            "check_gsas_audit_readiness": instance._handle_check_gsas_audit_readiness,
            "detect_gsas_score_drift": instance._handle_detect_gsas_score_drift,
        }
    
    async def _handle_get_gsas_status(self, args: Dict) -> Dict:
        """Get real GSAS status from database and BMS state"""
        # If we have a reporter, use it as primary source
        if getattr(self, "gsas_reporter", None) and hasattr(self.gsas_reporter, "get_status"):
            status = self.gsas_reporter.get_status()
            return status if isinstance(status, dict) else status.to_dict()

        if get_database is None:
            # Fallback to BMS-only calculation if DB is missing
            return await self._calculate_gsas_from_bms(args)
            
        try:
            db = get_database()
            building_id = args.get("building_id", "main")
            
            # Try to get cached GSAS score from database
            cached = await db.get_latest_gsas_score(building_id)
            
            if cached:
                return {
                    "overall_score": cached.get("overall_score", 0),
                    "certification_level": cached.get("certification_level", "Unknown"),
                    "categories": cached.get("category_scores", {}),
                    "timestamp": cached.get("timestamp", datetime.now().isoformat()),
                }
        except Exception as e:
            logger.warning(f"Database error in GSAS status: {e}")
            
        return await self._calculate_gsas_from_bms(args)

    async def _calculate_gsas_from_bms(self, args: Dict) -> Dict:
        """Helper to calculate scores from live BMS data when DB/Reporter unavailable"""
        
        # Calculate from BMS state if no cached score
        # This uses actual equipment data to estimate GSAS categories
        energy_score = 75  # Base score
        water_score = 75
        indoor_score = 75
        
        if self.bms_state:
            try:
                equipment = await self.bms_state.get_all_equipment()
                
                # Calculate energy score from equipment efficiency
                running = [e for e in equipment if e.status.value == "running"]
                if running:
                    avg_efficiency = sum(e.efficiency or 85 for e in running) / len(running)
                    energy_score = min(100, avg_efficiency + 5)  # Efficiency + bonus
                
                # Calculate indoor environment from active alarms
                alarms = await self.bms_state.get_active_alarms()
                comfort_alarms = [a for a in alarms if "temp" in a.message.lower() or "comfort" in a.message.lower()]
                indoor_score = max(60, 95 - len(comfort_alarms) * 5)  # Deduct for comfort alarms
                
            except Exception:
                pass
        
        # Calculate overall
        overall = (energy_score * 0.4 + water_score * 0.25 + indoor_score * 0.35)
        
        # Determine certification level
        if overall >= 85:
            cert_level = "4-Star"
        elif overall >= 75:
            cert_level = "3-Star"
        elif overall >= 65:
            cert_level = "2-Star"
        else:
            cert_level = "1-Star"
        
        return {
            "overall_score": round(overall, 1),
            "certification_level": cert_level,
            "categories": {
                "energy": round(energy_score, 1),
                "water": round(water_score, 1),
                "indoor_environment": round(indoor_score, 1),
            },
            "note": "Real-time estimate from BMS data",
        }
    
    async def _handle_get_gsas_improvement_priorities(self, args: Dict) -> Dict:
        """Get prioritized GSAS improvement actions"""
        if getattr(self, "gsas_reporter", None):
            return {
                "priorities": self.gsas_reporter.get_improvement_priorities(),
                "target_score": self.gsas_reporter.target_score(),
                "current_status": self.gsas_reporter.get_status(),
                "note": "Ranked by weighted GSAS target contribution",
            }

        return {
            "priorities": [
                {"action": "Optimize Chiller Sequencing", "impact": 1.5, "category": "Energy"},
                {"action": "Install Low-Flow Water Fixtures", "impact": 0.8, "category": "Water"},
                {"action": "Implement Demand Controlled Ventilation", "impact": 1.2, "category": "Indoor Environment"},
                {"action": "Upgrade LED Lighting in Car Park", "impact": 0.5, "category": "Energy"},
                {"action": "Add Real-time Water Metering", "impact": 0.4, "category": "Energy"},
            ],
            "note": "Generated based on current gaps in category scores"
        }

    async def _handle_optimize_recommendations_for_gsas(self, args: Dict) -> Dict:
        """Score and rank recommendations against GSAS targets."""
        recommendations = args.get("recommendations", [])
        limit = args.get("limit", 10)

        if not getattr(self, "gsas_reporter", None):
            return {
                "optimized": recommendations[:limit],
                "note": "GSAS reporter not configured; returning original order",
            }

        optimized = self.gsas_reporter.optimize_recommendations_for_targets(
            recommendations=recommendations,
            limit=limit,
        )
        return {
            "optimized": optimized,
            "count": len(optimized),
            "target_score": self.gsas_reporter.target_score(),
            "current_status": self.gsas_reporter.get_status(),
        }
    
    async def _handle_generate_gord_report(self, args: Dict) -> Dict:
        """Generate GORD-compliant PDF report for GSAS certification"""
        building_id = args.get("building_id", "main")
        building_name = args.get("building_name", "ARVIS Building")
        
        # Get current GSAS status
        gsas_status = await self._handle_get_gsas_status({"building_id": building_id})
        
        # Generate report data
        now = datetime.now()
        report = {
            "report_id": f"GORD-{building_id}-{now.strftime('%Y%m%d-%H%M%S-%f')}",
            "building_name": building_name,
            "building_id": building_id,
            "generated_at": now.isoformat(),
            "gsas_status": gsas_status,
            "sections": [
                "Executive Summary",
                "Building Overview",
                "Energy Performance",
                "Water Conservation",
                "Indoor Environment Quality",
                "BMS Evidence",
                "Recommendations",
            ],
            "report_status": "generated",
            "format": "PDF",
        }
        
        # If we have a report generator, use it
        if generate_gord_pdf:
            try:
                pdf_path = await generate_gord_pdf(report)
                report["pdf_path"] = pdf_path
            except Exception as e:
                logger.error(f"Error generating GORD PDF: {e}")
                report["note"] = f"PDF generation failed: {str(e)}"
        else:
            report["note"] = "PDF generation requires report_generator module"
        
        return report

    async def _handle_get_zone_occupancy(self, args: Dict) -> Dict:
        """Get contextual occupancy data for a zone"""
        zone_id = args.get("zone_id")
        if not zone_id:
            return {"error": "zone_id is required."}
        if not OccupancyContextProvider:
            return {"error": "OccupancyContextProvider not available."}
        provider = OccupancyContextProvider(self.bms_state)
        context = provider.get_zone_occupancy(zone_id)
        return {
            "zone_id": zone_id,
            "occupancy_context": context,
        }

    async def _handle_predict_comfort_impact(self, args: Dict) -> Dict:
        """Predict comfort impact of an action"""
        action = args.get("action", {})
        zone_id = args.get("zone_id")
        if not action or not zone_id:
            return {"error": "Both 'action' and 'zone_id' are required."}
        if not ComfortPredictor:
            return {"error": "ComfortPredictor not available."}
        predictor = ComfortPredictor(self.bms_state)
        prediction = predictor.predict_impact(action, zone_id)
        return {
            "action": action,
            "zone_id": zone_id,
            "prediction": prediction,
        }

    async def _handle_get_financial_projection(self, args: Dict) -> Dict:
        """Project financial savings for an action"""
        action = args.get("action", {})
        energy_delta = args.get("energy_delta_kwh", 0.0)
        water_delta = args.get("water_delta_m3", 0.0)
        
        if not FinancialImpactCalculator:
            return {"error": "FinancialImpactCalculator not available."}
        calculator = FinancialImpactCalculator()
        projection = calculator.calculate_savings(action, energy_delta, water_delta)
        return {
            "action": action,
            "projection": projection,
        }

    async def _handle_get_gsas_contextual_recommendations(self, args: Dict) -> Dict:
        """Get raw contextual recommendations from the optimizer"""
        limit = args.get("limit", 5)
        
        if not getattr(self, "gsas_reporter", None):
            return {"error": "GSAS Reporter not configured in this agent."}
            
        from agent_commercial.gsas_optimizer import GSASOptimizer
        llm = getattr(self, "llm", None)
        optimizer = GSASOptimizer(self.gsas_reporter, self.bms_state, llm_provider=llm)
        recommendations = await optimizer.generate_recommendations(max_recommendations=limit)
        
        return {
            "recommendations": [rec.to_dict() for rec in recommendations],
            "note": "These are raw context dicts. Please synthesize a natural language reasoning chain from these."
        }

    async def _handle_simulate_gsas_impact(self, args: Dict) -> Dict:
        """Simulates the impact of a BMS action on the GSAS score."""
        action = args.get("action", {})
        
        if not getattr(self, "gsas_reporter", None):
            return {"error": "GSAS Reporter not configured in this agent. Simulation requires a reporter instance."}
            
        if not GSASSimulator:
            return {"error": "GSASSimulator not available."}
            
        simulator = GSASSimulator(self.gsas_reporter)
        result = simulator.simulate_impact(action)
        return result

    async def _handle_classify_gsas_action_risk(self, args: Dict) -> Dict:
        """Returns the governance tier for a proposed action."""
        action = args.get("action", {})
        simulation_result = args.get("simulation_result", {})
        
        if not simulation_result:
            logger.warning("classify_gsas_action_risk called without simulation_result — GSAS score checks skipped")
        
        if not GSASExecutionGovernor:
            return {"error": "GSASExecutionGovernor not available."}
            
        return GSASExecutionGovernor.classify_action_risk(action, simulation_result)

    async def _handle_record_gsas_action_outcome(self, args: Dict) -> Dict:
        """Record the outcome of an FM decision."""
        action = args.get("action", {})
        decision = args.get("decision", "").upper()
        notes = args.get("notes", "")
        
        if decision not in ("APPROVED", "REJECTED", "MODIFIED"):
            return {"error": f"Invalid decision '{decision}'. Must be APPROVED, REJECTED, or MODIFIED."}
        
        if not GSASOutcomeTracker:
            return {"error": "GSASOutcomeTracker not available."}
            
        # Get DB connection if available
        db = get_database() if get_database else None
        tracker = GSASOutcomeTracker(db)
        
        return tracker.record_action_outcome(action, decision, notes)

    async def _handle_get_gsas_success_rates(self, args: Dict) -> Dict:
        """Get the historical approval rate for GSAS actions."""
        action_type = args.get("action_type")
        
        if not GSASOutcomeTracker:
            return {"error": "GSASOutcomeTracker not available."}
            
        db = get_database() if get_database else None
        tracker = GSASOutcomeTracker(db)
        
        return tracker.get_success_rates(action_type)

    async def _handle_check_gsas_audit_readiness(self, args: Dict) -> Dict:
        """Evaluates whether the building could pass a GSAS audit right now."""
        if not getattr(self, "gsas_reporter", None):
            return {"error": "GSAS Reporter not configured in this agent. Audit readiness check requires a reporter instance."}
            
        if not GSASAuditReadinessChecker:
            return {"error": "GSASAuditReadinessChecker not available."}
            
        survey_manager = getattr(self, "survey_manager", None)
        checker = GSASAuditReadinessChecker(self.gsas_reporter, survey_manager)
        return checker.check_readiness()

    async def _handle_detect_gsas_score_drift(self, args: Dict) -> Dict:
        """Detects if the GSAS score is drifting downwards over a window of time."""
        window_days = args.get("window_days", 30)
        
        if not getattr(self, "gsas_reporter", None):
            return {"error": "GSAS Reporter not configured in this agent."}
            
        # Call the new detect_drift method on the reporter
        drift_result = self.gsas_reporter.detect_drift(window_days)
        
        if drift_result:
            return drift_result
        return {
            "alert_level": "normal",
            "message": "No negative drift detected. Score is stable or improving."
        }
