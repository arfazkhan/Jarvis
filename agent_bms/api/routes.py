"""
ARVIS Ops Copilot REST API
==========================

FastAPI-based REST API for the Ops Copilot dashboard and integrations.

Endpoints:
- Dashboard: Overview, active alarms, energy metrics
- Equipment: Status, history, health predictions
- Insights: AI-generated recommendations
- Chat: Natural language queries
- Maintenance: Predictions, scheduling
- GSAS: Compliance status and reports

This API serves both the web dashboard and the LLM tool executor.
"""

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger("arvis.bms.api")


# ═══════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS (Request/Response Schemas)
# ═══════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """Natural language query request"""
    query: str = Field(..., description="User's question in English or Arabic")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")


class ChatResponse(BaseModel):
    """Natural language response"""
    response: str
    confidence: float = Field(..., ge=0, le=1)
    sources: List[str] = []
    suggested_actions: List[str] = []


class EquipmentStatusResponse(BaseModel):
    """Equipment status details"""
    equipment_id: str
    name: str
    equipment_type: str
    status: str
    location: str
    runtime_hours: float
    efficiency: Optional[float]
    active_alarms: int
    last_maintenance: Optional[str]
    data_points: List[Dict[str, Any]]


class AlarmResponse(BaseModel):
    """Active alarm details"""
    alarm_id: str
    equipment_id: str
    message: str
    severity: str
    state: str
    triggered_at: str
    duration_minutes: float
    cluster_id: Optional[str]
    suggested_actions: List[str]


class InsightResponse(BaseModel):
    """AI-generated insight"""
    insight_id: str
    insight_type: str
    title: str
    description: str
    priority: str
    confidence: float
    recommended_action: str
    estimated_impact: str
    created_at: str


class MaintenancePredictionResponse(BaseModel):
    """Predictive maintenance output"""
    equipment_id: str
    equipment_name: str
    failure_probability: float
    risk_level: str
    predicted_rul_days: int
    confidence: float
    recommendation: str
    contributing_factors: List[Dict[str, Any]]


class DashboardOverview(BaseModel):
    """Dashboard summary data"""
    timestamp: str
    equipment_total: int
    equipment_running: int
    equipment_fault: int
    active_alarms_critical: int
    active_alarms_high: int
    active_alarms_total: int
    energy_today_kwh: float
    energy_vs_baseline_percent: float
    insights_pending: int
    maintenance_due_7d: int


# ═══════════════════════════════════════════════════════════════════════════
# API APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

def create_api(
    bms_state=None,
    alarm_engine=None,
    energy_analyzer=None,
    predictive_engine=None,
    llm_agent=None,
) -> FastAPI:
    """
    Create the FastAPI application with all routes.
    
    Args:
        bms_state: BMSStateEngine instance
        alarm_engine: AlarmEngine instance
        energy_analyzer: EnergyAnalyzer instance
        predictive_engine: PredictiveMaintenanceEngine instance
        llm_agent: LLMAgent instance for chat
        
    Returns:
        Configured FastAPI app
    """
    
    app = FastAPI(
        title="ARVIS Ops Copilot API",
        description="AI-powered Building Management System advisory platform",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    
    # CORS for dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Store engine references
    app.state.bms_state = bms_state
    app.state.alarm_engine = alarm_engine
    app.state.energy_analyzer = energy_analyzer
    app.state.predictive_engine = predictive_engine
    app.state.llm_agent = llm_agent
    
    # ═══════════════════════════════════════════════════════════════════════
    # DASHBOARD ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/v1/dashboard/overview", response_model=DashboardOverview)
    async def get_dashboard_overview():
        """Get dashboard summary metrics"""
        from agent_bms.database import get_database
        
        state = app.state.bms_state
        alarm_eng = app.state.alarm_engine
        predictive_eng = app.state.predictive_engine
        db = get_database()
        
        if not state:
            raise HTTPException(503, "BMS state engine not initialized")
        
        # Get counts
        snapshot = await state.get_snapshot()
        active_alarms = await state.get_active_alarms()
        
        critical_count = sum(1 for a in active_alarms if a.severity.value == "critical")
        high_count = sum(1 for a in active_alarms if a.severity.value == "high")
        
        # Equipment by status
        status_counts = snapshot.get("equipment_by_status", {})
        
        # Real energy data from database
        energy_today = db.get_energy_today()
        energy_baseline = db.get_energy_baseline_comparison()
        
        # Real insights count (active high-priority alarms)
        insights_pending = db.get_pending_insights_count()
        
        # Real maintenance due count
        maintenance_due = len(db.get_equipment_requiring_maintenance(days=7))
        
        return DashboardOverview(
            timestamp=datetime.now().isoformat(),
            equipment_total=snapshot.get("equipment_count", 0),
            equipment_running=status_counts.get("running", 0),
            equipment_fault=status_counts.get("fault", 0),
            active_alarms_critical=critical_count,
            active_alarms_high=high_count,
            active_alarms_total=len(active_alarms),
            energy_today_kwh=energy_today,
            energy_vs_baseline_percent=energy_baseline,
            insights_pending=insights_pending,
            maintenance_due_7d=maintenance_due,
        )
    
    @app.get("/api/v1/dashboard/alarms/active", response_model=List[AlarmResponse])
    async def get_active_alarms(
        limit: int = Query(50, ge=1, le=200),
        severity: Optional[str] = Query(None, description="Filter by severity")
    ):
        """Get active alarms sorted by priority"""
        alarm_eng = app.state.alarm_engine
        
        if not alarm_eng:
            return []
        
        queue = alarm_eng.get_priority_queue()
        
        # Filter by severity if specified
        if severity:
            queue = [a for a in queue if a.alarm.severity.value == severity]
        
        # Convert to response
        return [
            AlarmResponse(
                alarm_id=a.alarm.alarm_id,
                equipment_id=a.alarm.equipment_id,
                message=a.alarm.message,
                severity=a.alarm.severity.value,
                state=a.alarm.state.value,
                triggered_at=a.alarm.triggered_at.isoformat(),
                duration_minutes=a.alarm.duration_minutes(),
                cluster_id=a.cluster_id,
                suggested_actions=a.suggested_actions,
            )
            for a in queue[:limit]
        ]

    # New endpoint add:
    @app.post("/api/v1/alarms/{alarm_id}/acknowledge")
    async def acknowledge_alarm(alarm_id: str):
        """Acknowledge an active alarm"""
        alarm_eng = app.state.alarm_engine
        
        if not alarm_eng:
            raise HTTPException(503, "Alarm engine not initialized")
            
        success = alarm_eng.acknowledge_alarm(alarm_id)
        if not success:
            raise HTTPException(404, f"Alarm {alarm_id} not found or already acknowledged")
            
        return {"status": "acknowledged", "alarm_id": alarm_id}
    
    # ═══════════════════════════════════════════════════════════════════════
    # EQUIPMENT ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/v1/equipment", response_model=List[Dict[str, Any]])
    async def list_equipment(
        equipment_type: Optional[str] = None,
        status: Optional[str] = None,
        location: Optional[str] = None,
    ):
        """List all equipment with optional filters"""
        state = app.state.bms_state
        
        if not state:
            return []
        
        equipment = await state.get_all_equipment()
        
        # Apply filters
        if equipment_type:
            equipment = [e for e in equipment if e.equipment_type.value == equipment_type]
        if status:
            equipment = [e for e in equipment if e.status.value == status]
        if location:
            equipment = [e for e in equipment if location.lower() in e.location.lower()]
        
        return [e.to_dict() for e in equipment]
    
    @app.get("/api/v1/equipment/{equipment_id}", response_model=EquipmentStatusResponse)
    async def get_equipment_details(equipment_id: str):
        """Get detailed equipment status"""
        state = app.state.bms_state
        
        if not state:
            raise HTTPException(503, "BMS state engine not initialized")
        
        equipment = await state.get_equipment(equipment_id)
        if not equipment:
            raise HTTPException(404, f"Equipment {equipment_id} not found")
        
        # Get data points
        points = await state.get_points_by_equipment(equipment_id)
        
        return EquipmentStatusResponse(
            equipment_id=equipment.equipment_id,
            name=equipment.name,
            equipment_type=equipment.equipment_type.value,
            status=equipment.status.value,
            location=equipment.location,
            runtime_hours=equipment.runtime_hours,
            efficiency=equipment.efficiency,
            active_alarms=len(equipment.active_alarm_ids),
            last_maintenance=equipment.last_maintenance.isoformat() if equipment.last_maintenance else None,
            data_points=[p.to_dict() for p in points],
        )
    
    @app.get("/api/v1/equipment/{equipment_id}/history")
    async def get_equipment_history(
        equipment_id: str,
        point_id: Optional[str] = None,
        minutes: int = Query(60, ge=1, le=1440),
    ):
        """Get historical data for equipment points"""
        state = app.state.bms_state
        
        if not state:
            raise HTTPException(503, "BMS state engine not initialized")
        
        if point_id:
            history = await state.get_point_history(point_id, minutes)
            return {
                "point_id": point_id,
                "data": [
                    {"timestamp": t.isoformat(), "value": v}
                    for t, v in history
                ]
            }
        else:
            # Get all points for equipment
            points = await state.get_points_by_equipment(equipment_id)
            result = {}
            for p in points:
                hist = await state.get_point_history(p.point_id, minutes)
                result[p.point_id] = [
                    {"timestamp": t.isoformat(), "value": v}
                    for t, v in hist
                ]
            return result
    
    # ═══════════════════════════════════════════════════════════════════════
    # INSIGHTS ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/v1/insights/feed", response_model=List[InsightResponse])
    async def get_insights_feed(
        limit: int = Query(20, ge=1, le=100),
        insight_type: Optional[str] = None,
    ):
        """Get AI-generated insights feed"""
        # In a full implementation, this would query a database of insights
        # For now, generate from alarm engine analysis
        alarm_eng = app.state.alarm_engine
        
        insights = []
        
        if alarm_eng:
            analysis = alarm_eng.analyze()
            for item in analysis[:limit]:
                insights.append(InsightResponse(
                    insight_id=f"insight_{len(insights)}",
                    insight_type=item.get("type", "general"),
                    title=item.get("message", "")[:100],
                    description=item.get("message", ""),
                    priority=item.get("priority", "medium"),
                    confidence=0.8,
                    recommended_action="Review and acknowledge",
                    estimated_impact="",
                    created_at=datetime.now().isoformat(),
                ))
        
        return insights
    
    @app.post("/api/v1/insights/{insight_id}/acknowledge")
    async def acknowledge_insight(insight_id: str):
        """Acknowledge an insight"""
        return {"status": "acknowledged", "insight_id": insight_id}
    
    # ═══════════════════════════════════════════════════════════════════════
    # CHAT ENDPOINT
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        """
        Natural language query to Ops Copilot.
        
        Supports English and Arabic queries about:
        - Equipment status
        - Alarm explanations
        - Energy analysis
        - Maintenance recommendations
        - GSAS compliance
        
        The LLM automatically selects and executes relevant tools,
        then summarizes the results in natural language.
        """
        llm = app.state.llm_agent
        state = app.state.bms_state
        
        # Create BMS agent if not already set
        if not llm:
            try:
                from agent_bms.bms_llm_agent import BMSLLMAgent
                llm = BMSLLMAgent(
                    bms_state=app.state.bms_state,
                    alarm_engine=app.state.alarm_engine,
                    energy_analyzer=app.state.energy_analyzer,
                    predictive_engine=app.state.predictive_engine,
                )
                app.state.llm_agent = llm
            except Exception as e:
                logger.error(f"Failed to create BMS LLM agent: {e}")
                return ChatResponse(
                    response="LLM agent initialization failed. Please check API keys.",
                    confidence=0.0,
                    sources=[],
                    suggested_actions=["Set GROQ_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"],
                )
        
        try:
            # Build context from current state
            context = {}
            if state:
                snapshot = await state.get_snapshot()
                context["equipment_count"] = snapshot.get("equipment_count", 0)
                context["active_alarms"] = snapshot.get("active_alarm_count", 0)
                context["timestamp"] = datetime.now().isoformat()
            
            # Add user-provided context
            if request.context:
                context.update(request.context)
            
            # Call the BMS LLM agent
            response = await llm.chat(request.query, context)
            
            # Extract suggested actions from tool results
            suggested_actions = []
            for tr in response.tool_results:
                result = tr.get("result", {})
                if isinstance(result, dict):
                    if "recommendations" in result:
                        suggested_actions.extend(result["recommendations"][:2])
                    if "suggested_actions" in result:
                        suggested_actions.extend(result["suggested_actions"][:2])
            
            return ChatResponse(
                response=response.text,
                confidence=response.confidence,
                sources=response.sources,
                suggested_actions=suggested_actions[:5],  # Top 5 actions
            )
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            raise HTTPException(500, f"Chat processing failed: {str(e)}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # PREDICTIVE MAINTENANCE ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/v1/maintenance/predictions", response_model=List[MaintenancePredictionResponse])
    async def get_maintenance_predictions(
        risk_level: Optional[str] = Query(None, description="Filter by risk: low, medium, high, critical"),
    ):
        """Get failure predictions for all equipment"""
        pm_engine = app.state.predictive_engine
        state = app.state.bms_state
        
        if not pm_engine or not state:
            return []
        
        predictions = []
        equipment = await state.get_all_equipment()
        
        for eq in equipment:
            # In full implementation, would get features from state
            # For now, return placeholder
            predictions.append(MaintenancePredictionResponse(
                equipment_id=eq.equipment_id,
                equipment_name=eq.name,
                failure_probability=0.1,
                risk_level="low",
                predicted_rul_days=90,
                confidence=0.7,
                recommendation="Continue standard monitoring",
                contributing_factors=[],
            ))
        
        # Filter by risk level
        if risk_level:
            predictions = [p for p in predictions if p.risk_level == risk_level]
        
        return predictions
    
    @app.get("/api/v1/maintenance/equipment/{equipment_id}/health")
    async def get_equipment_health(equipment_id: str):
        """Get detailed health analysis for specific equipment"""
        pm_engine = app.state.predictive_engine
        state = app.state.bms_state
        
        if not state:
            raise HTTPException(503, "BMS state engine not initialized")
        
        equipment = await state.get_equipment(equipment_id)
        if not equipment:
            raise HTTPException(404, f"Equipment {equipment_id} not found")
        
        return {
            "equipment_id": equipment_id,
            "overall_health": "good",
            "health_score": 85,
            "trending": "stable",
            "risk_factors": [],
            "recommendations": [
                "Schedule preventive maintenance within 30 days",
                "Monitor efficiency trend",
            ],
        }
    
    # ═══════════════════════════════════════════════════════════════════════
    # ENERGY ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/v1/energy/consumption")
    async def get_energy_consumption(
        period: str = Query("today", description="today, week, month"),
    ):
        """Get energy consumption summary"""
        return {
            "period": period,
            "total_kwh": 4500.0,
            "baseline_kwh": 4200.0,
            "deviation_percent": 7.1,
            "peak_kw": 850.0,
            "peak_time": "14:30",
            "cost_qar": 675.0,
        }
    
    @app.get("/api/v1/energy/anomalies")
    async def get_energy_anomalies():
        """Get detected energy anomalies"""
        analyzer = app.state.energy_analyzer
        
        if not analyzer:
            return []
        
        patterns = analyzer.identify_waste_patterns()
        
        return [
            {
                "pattern_id": p.pattern_id,
                "pattern_type": p.pattern_type,
                "description": p.description,
                "estimated_savings_qar": p.estimated_waste_qar_annual,
                "occurrences": p.occurrences,
            }
            for p in patterns
        ]
    
    # ═══════════════════════════════════════════════════════════════════════
    # GSAS ENDPOINTS
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/v1/gsas/status")
    async def get_gsas_status():
        """Get GSAS compliance status"""
        return {
            "overall_score": 78,
            "target_score": 85,
            "certification_level": "3-Star",
            "categories": {
                "energy": {"score": 82, "target": 85, "status": "on_track"},
                "water": {"score": 75, "target": 80, "status": "needs_attention"},
                "indoor_environment": {"score": 80, "target": 85, "status": "on_track"},
                "materials": {"score": 70, "target": 80, "status": "needs_attention"},
            },
            "next_assessment": "2026-06-01",
            "recommendations": [
                "Reduce after-hours HVAC to improve energy score",
                "Implement water sub-metering for accurate tracking",
            ],
        }
    
    @app.get("/api/v1/gsas/report")
    async def generate_gsas_report(
        report_type: str = Query("monthly", description="monthly, quarterly, annual"),
    ):
        """Generate GSAS compliance report"""
        return {
            "report_type": report_type,
            "generated_at": datetime.now().isoformat(),
            "status": "generating",
            "download_url": None,  # Would be actual URL when generated
        }
    
    @app.post("/api/v1/gsas/gord-report")
    async def generate_gord_report(background_tasks: BackgroundTasks):
        """
        Generate GORD-compliant PDF report for GSAS Operations certification.
        
        This is the official report format required for submission to GORD
        (Gulf Organisation for Research & Development) for Operations
        certification renewal.
        
        The PDF includes:
        - Cover page with building info and scores
        - Executive summary
        - Category-by-category breakdown
        - Detailed criteria scores
        - BMS evidence section
        - Improvement recommendations
        - Signature blocks for FM and GORD reviewer
        """
        from agent_bms.gsas_reporter import GSASReporter
        
        # Get building info from state or use defaults
        state = app.state.bms_state
        building_id = "BUILDING-01"
        building_name = "Commercial Building"
        
        if state:
            snapshot = await state.get_snapshot()
            building_id = snapshot.get("building_id", building_id)
            building_name = snapshot.get("building_name", building_name)
        
        # Initialize reporter
        reporter = GSASReporter(building_id, building_name)
        reporter.initialize_criteria()
        
        # Get real BMS data if available
        energy_data = {}
        water_data = {}
        iaq_data = {}
        
        if app.state.energy_analyzer:
            summary = app.state.energy_analyzer.get_summary()
            if summary:
                baseline_deviation = summary.get("baseline_deviation_percent", 0)
                energy_data["consumption_vs_baseline"] = max(0, -baseline_deviation)  # Reduction is positive
                energy_data["submetering_coverage"] = 80  # Assume good coverage if we have analyzer
        
        # Update from BMS data
        reporter.update_from_bms(energy_data, water_data, iaq_data)
        
        # Generate PDF
        try:
            pdf_path = reporter.generate_gord_pdf()
            
            # Get status for response
            status = reporter.get_status()
            
            return {
                "status": "success",
                "report_id": reporter.generate_report().report_id,
                "pdf_path": pdf_path,
                "overall_score": status["overall_score"],
                "star_rating": status["star_rating"],
                "message": "GORD-compliant PDF report generated successfully. Ready for submission.",
                "next_steps": [
                    "Review the generated PDF",
                    "Get Facility Manager signature",
                    "Submit to GORD for certification"
                ]
            }
            
        except Exception as e:
            logger.error(f"GORD report generation failed: {e}")
            raise HTTPException(500, f"Report generation failed: {str(e)}")
    
    @app.get("/api/v1/reports/download/{filename}")
    async def download_report(filename: str):
        """Download a generated report"""
        import os
        from fastapi.responses import FileResponse
        
        # Ensure filename is safe (basic check)
        if ".." in filename or "/" in filename or "\\" in filename:
             raise HTTPException(400, "Invalid filename")
             
        file_path = os.path.join("reports", filename)
        
        if not os.path.exists(file_path):
            raise HTTPException(404, f"Report not found: {filename}")
            
        return FileResponse(
            file_path, 
            media_type="application/pdf", 
            filename=filename
        )
    
    @app.get("/api/v1/gsas/improvement-priorities")
    async def get_gsas_improvement_priorities():
        """
        Get prioritized list of GSAS improvements.
        
        Returns the top 10 improvements ranked by impact on overall score.
        """
        from agent_bms.gsas_reporter import GSASReporter
        
        reporter = GSASReporter()
        reporter.initialize_criteria()
        
        # Populate with sample data (in production, from BMS)
        reporter.update_from_bms(
            {"consumption_vs_baseline": 15},
            {"consumption_vs_baseline": 10},
            {"comfort_compliance": 85}
        )
        
        priorities = reporter.get_improvement_priorities()
        
        return {
            "count": len(priorities),
            "priorities": priorities,
            "estimated_score_gain": sum(p["potential_gain"] for p in priorities[:5])
        }
    
    # ═══════════════════════════════════════════════════════════════════════
    # HEALTH CHECK
    # ═══════════════════════════════════════════════════════════════════════
    
    @app.get("/api/health")
    async def health_check():
        """API health check"""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "components": {
                "bms_state": app.state.bms_state is not None,
                "alarm_engine": app.state.alarm_engine is not None,
                "energy_analyzer": app.state.energy_analyzer is not None,
                "predictive_engine": app.state.predictive_engine is not None,
                "llm_agent": app.state.llm_agent is not None,
            }
        }
    
    return app


# ═══════════════════════════════════════════════════════════════════════════
# STANDALONE SERVER
# ═══════════════════════════════════════════════════════════════════════════

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server standalone"""
    import uvicorn
    
    # Create app with no engines (for testing)
    app = create_api()
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
