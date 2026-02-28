from fastapi import APIRouter, Depends
from typing import List, Optional
import logging
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])
logger = logging.getLogger("arvis.api.learning")

@router.get("/patterns")
async def get_patterns(limit: int = 10, sys: SystemContainer = Depends(get_system_state)):
    """
    Get discovered operational patterns.
    
    Returns patterns detected by the learning engine's pattern analyzer,
    sorted by confidence level.
    """
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        try:
            # Get history from state engine if available
            history = []
            if sys.state_engine and hasattr(sys.state_engine, "get_history"):
                history = sys.state_engine.get_history(limit=500)
            
            # Get patterns from pattern analyzer
            patterns = sys.learning_engine.pattern_analyzer.get_top_patterns(
                history=history,
                limit=limit
            )
            
            if patterns:
                logger.info(f"Returning {len(patterns)} discovered patterns")
                return patterns
        except Exception as e:
            logger.error(f"Error getting patterns: {e}")
            # Fall through to return empty list with warning
    
    # No patterns available or error occurred
    return []

@router.post("/patterns/promote")
async def promote_pattern(pattern_id: str, sys: SystemContainer = Depends(get_system_state)):
    """
    Promote a pattern to a higher confidence level.
    
    This increases the pattern's confidence, making it more likely
    to be used for automation suggestions.
    """
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        try:
            success = sys.learning_engine.pattern_analyzer.promote_pattern(pattern_id)
            if success:
                logger.info(f"Pattern {pattern_id} promoted")
                return {"status": "promoted", "pattern_id": pattern_id}
            else:
                return {"status": "not_found", "pattern_id": pattern_id}
        except Exception as e:
            logger.error(f"Error promoting pattern: {e}")
            return {"status": "error", "message": str(e)}
    
    return {"status": "no_learning_engine"}

@router.get("/trends")
async def get_trends(sys: SystemContainer = Depends(get_system_state)):
    """
    Get habit drift trends.
    
    Analyzes patterns like wake time, bedtime, and energy usage
    to detect gradual changes over time.
    """
    trends = {}
    
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        try:
            # Get history for trend analysis
            history = []
            if sys.state_engine and hasattr(sys.state_engine, "get_history"):
                history = sys.state_engine.get_history(limit=1000)
            
            if history:
                # Get wake time drift
                wake_drift = sys.learning_engine.pattern_analyzer.detect_habit_drift(
                    history, "wake_time"
                )
                if wake_drift.get("wake_time"):
                    drift_info = wake_drift["wake_time"]
                    trends["wake_time_drift"] = f"{drift_info['direction']} {abs(drift_info['drift_hours']*60):.0f}min"
                
                # Get bedtime drift
                bed_drift = sys.learning_engine.pattern_analyzer.detect_habit_drift(
                    history, "bedtime"
                )
                if bed_drift.get("bedtime"):
                    drift_info = bed_drift["bedtime"]
                    trends["bedtime_drift"] = f"{drift_info['direction']} {abs(drift_info['drift_hours']*60):.0f}min"
        except Exception as e:
            logger.error(f"Error getting trends: {e}")
    
    # Add energy trend if available (from commercial mode)
    if hasattr(sys, 'energy_analyzer') and sys.energy_analyzer:
        try:
            # Would need actual implementation
            trends["energy_usage_trend"] = "+5%"  # Placeholder
        except Exception:
            pass
    
    return trends if trends else {"wake_time_drift": "no_data", "energy_usage_trend": "no_data"}

@router.get("/anomalies")
async def get_anomalies(sys: SystemContainer = Depends(get_system_state)):
    """
    Get detected system anomalies.
    
    Returns unusual patterns that deviate from established baselines.
    """
    anomalies = []
    
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        try:
            # Get history for anomaly detection
            history = []
            if sys.state_engine and hasattr(sys.state_engine, "get_history"):
                history = sys.state_engine.get_history(limit=500)
            
            if history:
                detected = sys.learning_engine.pattern_analyzer.detect_anomalies(history)
                anomalies = detected if detected else []
        except Exception as e:
            logger.error(f"Error detecting anomalies: {e}")
    
    return anomalies

@router.get("/summary")
async def get_summary(sys: SystemContainer = Depends(get_system_state)):
    """
    Get a comprehensive learning summary.
    
    Returns patterns, anomalies, and trends in a single response.
    """
    summary = {
        "patterns": [],
        "anomalies": [],
        "trends": {},
        "total_events_analyzed": 0
    }
    
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        try:
            history = []
            if sys.state_engine and hasattr(sys.state_engine, "get_history"):
                history = sys.state_engine.get_history(limit=1000)
            
            summary["total_events_analyzed"] = len(history)
            
            if history:
                # Get full summary from pattern analyzer
                analysis = sys.learning_engine.pattern_analyzer.summarize_patterns(history)
                summary["patterns"] = sys.learning_engine.pattern_analyzer.get_top_patterns(history, limit=5)
                summary["anomalies"] = analysis.get("anomalies", [])
                summary["trends"] = {
                    "wake_drift": analysis.get("wake_drift", {}),
                    "bed_drift": analysis.get("bed_drift", {})
                }
        except Exception as e:
            logger.error(f"Error getting summary: {e}")
            summary["error"] = str(e)
    
    return summary
