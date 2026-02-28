"""
Advisory System Scheduler
==========================

Scheduled jobs for Phase 1 Advisory System:
- Daily metrics calculation
- Weekly calibration retraining  
- Preference summary generation

Usage:
    from agent_commercial.advisory_scheduler import start_advisory_scheduler
    
    scheduler = start_advisory_scheduler(tracker, calibrator, preference_learner)
"""

import logging
from typing import Optional
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("arvis.advisory.scheduler")


class AdvisoryScheduler:
    """
    Scheduler for advisory system tasks.
    
    Runs background jobs to:
    - Calculate daily trust metrics
    - Retrain confidence calibrator
    - Generate preference summaries
    """
    
    def __init__(self, tracker, calibrator=None, preference_learner=None):
        """
        Initialize scheduler with advisory components.
        
        Args:
            tracker: RecommendationTracker instance
            calibrator: TrustCalibrator instance (optional)
            preference_learner: PreferenceLearningEngine instance (optional)
        """
        self.tracker = tracker
        self.calibrator = calibrator
        self.preference_learner = preference_learner
        
        self.scheduler = AsyncIOScheduler()
        self._setup_jobs()
        
        logger.info("Advisory scheduler initialized")
    
    def _setup_jobs(self):
        """Setup scheduled jobs"""
        
        # Daily metrics calculation (every day at midnight)
        self.scheduler.add_job(
            self._calculate_daily_metrics,
            CronTrigger(hour=0, minute=0),
            id="daily_metrics",
            name="Calculate Daily Trust Metrics",
            replace_existing=True
        )
        
        # Weekly calibrator retraining (every Sunday at 1 AM)
        if self.calibrator:
            self.scheduler.add_job(
                self._retrain_calibrator,
                CronTrigger(day_of_week='sun', hour=1, minute=0),
                id="weekly_calibration_training",
                name="Retrain Confidence Calibrator",
                replace_existing=True
            )
        
        # Weekly preference summary (every Monday at 8 AM)
        if self.preference_learner:
            self.scheduler.add_job(
                self._generate_preference_summaries,
                CronTrigger(day_of_week='mon', hour=8, minute=0),
                id="weekly_preference_summary",
                name="Generate Preference Summaries",
                replace_existing=True
            )
        
        logger.info("Scheduled %d advisory jobs", len(self.scheduler.get_jobs()))
    
    async def _calculate_daily_metrics(self):
        """Calculate and log daily trust metrics"""
        try:
            logger.info("=== Running Daily Metrics Calculation ===")
            
            # Calculate metrics for last 30 days
            metrics = self.tracker.calculate_trust_metrics(window_days=30)
            
            logger.info(
                "Daily Metrics Summary:\n"
                f"  • Total Recommendations: {metrics.total_recommendations}\n"
                f"  • Adoption Rate: {metrics.adoption_rate:.1%}\n"
                f"  • Accuracy When Followed: {metrics.accuracy_when_followed:.1%}\n"
                f"  • Calibration Error: {metrics.calibration_error:.2f}\n"
                f"  • Excellent Outcomes: {metrics.excellent_outcomes}\n"
                f"  • Good Outcomes: {metrics.good_outcomes}\n"
                f"  • Poor Outcomes: {metrics.poor_outcomes}"
            )
            
            # Alert if calibration error is high
            if metrics.calibration_error > 0.15:
                logger.warning(
                    "⚠️ High calibration error detected (%.2f). "
                    "Consider retraining calibrator.",
                    metrics.calibration_error
                )
            
            # Alert if adoption rate is low
            if metrics.adoption_rate < 0.5 and metrics.total_recommendations > 10:
                logger.warning(
                    "⚠️ Low adoption rate detected (%.1f%%). "
                    "ARVIS recommendations may not be trusted by operators.",
                    metrics.adoption_rate * 100
                )
                
        except Exception as e:
            logger.error("Error calculating daily metrics: %s", e, exc_info=True)
    
    async def _retrain_calibrator(self):
        """Retrain the confidence calibrator"""
        try:
            logger.info("=== Retraining Confidence Calibrator ===")
            
            if not self.calibrator:
                logger.warning("No calibrator configured, skipping retrain")
                return
            
            # Retrain using last 90 days of data
            old_calibration = self.calibrator.calibration_map.copy()
            self.calibrator.retrain(window_days=90)
            new_calibration = self.calibrator.calibration_map
            
            # Log changes
            logger.info("Calibration map updated:")
            for bucket in sorted(new_calibration.keys()):
                old_val = old_calibration.get(bucket, bucket)
                new_val = new_calibration[bucket]
                if abs(old_val - new_val) > 0.05:
                    logger.info(
                        "  Bucket %.1f: %.1f%% -> %.1f%% (Δ %.1f%%)",
                        bucket, old_val * 100, new_val * 100, (new_val - old_val) * 100
                    )
                    
        except Exception as e:
            logger.error("Error retraining calibrator: %s", e, exc_info=True)
    
    async def _generate_preference_summaries(self):
        """Generate weekly preference summaries for active operators"""
        try:
            logger.info("=== Generating Weekly Preference Summaries ===")
            
            if not self.preference_learner:
                logger.warning("No preference learner configured, skipping")
                return
            
            # Get all unique operator IDs from last 90 days
            from agent_advisory.database import AdvisoryDatabase
            db = self.preference_learner.db
            
            rows = db.fetch_all(
                """
                SELECT DISTINCT operator_id 
                FROM operator_preferences 
                WHERE timestamp >= ? 
                AND operator_id != 'unknown'
                ORDER BY operator_id
                """,
                (datetime.now().timestamp() - 90 * 24 * 60 * 60,)
            )
            
            operator_ids = [row["operator_id"] for row in rows]
            
            logger.info(f"Generating summaries for {len(operator_ids)} operators")
            
            for operator_id in operator_ids:
                summary = self.preference_learner.get_operator_preferences_summary(
                    operator_id=operator_id,
                    window_days=90
                )
                
                logger.info(
                    f"\n📊 Operator: {operator_id}\n"
                    f"  • Total Decisions: {summary['total_decisions']}\n"
                    f"  • Override Rate: {summary['override_rate']:.1%}\n"
                    f"  • Top Preferences: {len(summary['top_preferences'])}\n"
                    f"  • Insights: {', '.join(summary['insights']) if summary['insights'] else 'None'}"
                )
            
        except Exception as e:
            logger.error("Error generating preference summaries: %s", e, exc_info=True)
    
    def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info("Advisory scheduler started")
    
    def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
        logger.info("Advisory scheduler shutdown")


def start_advisory_scheduler(tracker, calibrator=None, preference_learner=None):
    """
    Convenience function to start the advisory scheduler.
    
    Args:
        tracker: RecommendationTracker instance
        calibrator: TrustCalibrator instance (optional)
        preference_learner: PreferenceLearningEngine instance (optional)
    
    Returns:
        AdvisoryScheduler instance (already started)
    """
    scheduler = AdvisoryScheduler(tracker, calibrator, preference_learner)
    scheduler.start()
    return scheduler
