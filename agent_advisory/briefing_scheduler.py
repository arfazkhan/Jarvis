"""
Proactive Briefing Scheduler
============================

Schedules and generates proactive briefings for building operators.
Briefings aggregate high-priority goals into actionable summaries.

Types of Briefings:
1. Daily Morning Briefing (7:00 AM): Top 3 priorities for the day.
2. Urgent Risk Alert (Real-time): Critical risks requiring immediate attention.
3. Weekly Strategy Review (Sunday 8:00 AM): Fleet optimization and long-term goals.
"""

import logging
import uuid
import json
from enum import Enum
from datetime import datetime, time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent_advisory.goal_generator import GoalGenerator, ProactiveGoal

logger = logging.getLogger("arvis.advisory.briefing")

class BriefingType(str, Enum):
    DAILY_MORNING = "daily_morning"
    URGENT_RISK = "urgent_risk"
    WEEKLY_STRATEGY = "weekly_strategy"

@dataclass
class Briefing:
    """A generated briefing for an operator"""
    briefing_id: str
    briefing_type: BriefingType
    building_id: str
    headline: str
    content: str
    goals: List[ProactiveGoal]
    created_at: datetime = field(default_factory=datetime.now)
    is_delivered: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "briefing_id": self.briefing_id,
            "briefing_type": self.briefing_type.value,
            "building_id": self.building_id,
            "headline": self.headline,
            "content": self.content,
            "goals_count": len(self.goals),
            "created_at": self.created_at.isoformat(),
            "is_delivered": self.is_delivered
        }

class BriefingGenerator:
    """Generates content for briefings"""
    
    @staticmethod
    def generate_daily_briefing(building_id: str, goals: List[ProactiveGoal]) -> Briefing:
        # Filter for high/medium priority
        priority_goals = [g for g in goals if g.priority in ["critical", "high", "medium"]]
        # Take top 3
        top_goals = priority_goals[:3]
        
        if not top_goals:
            content = "No critical issues detected. System operating normally."
            headline = "✅ All Systems Normal"
        else:
            headline = f"Create {len(top_goals)} Focus Actions for Today"
            content = "Good Morning. Here are your top priorities:\n\n"
            for i, goal in enumerate(top_goals, 1):
                icon = "🔴" if goal.priority == "critical" else "🟠" if goal.priority == "high" else "🔵"
                content += f"{i}. {icon} **{goal.title}**\n"
                content += f"   {goal.description}\n"
                if goal.potential_savings_qar > 0:
                    content += f"   💰 Impact: QAR {goal.potential_savings_qar:,.0f}/yr\n"
                content += "\n"
                
        return Briefing(
            briefing_id=str(uuid.uuid4()),
            briefing_type=BriefingType.DAILY_MORNING,
            building_id=building_id,
            headline=headline,
            content=content,
            goals=top_goals
        )

    @staticmethod
    def generate_urgent_alert(building_id: str, goal: ProactiveGoal) -> Briefing:
        return Briefing(
            briefing_id=str(uuid.uuid4()),
            briefing_type=BriefingType.URGENT_RISK,
            building_id=building_id,
            headline=f"🚨 URGENT: {goal.title}",
            content=f"CRITICAL RISK DETECTED\n\n{goal.description}\n\nRecommended Action:\n{goal.suggested_actions[0] if goal.suggested_actions else 'Inspect immediately'}",
            goals=[goal]
        )


class BriefingScheduler:
    """
    Schedules and manages proactive briefings.
    """
    
    def __init__(self, goal_generator: GoalGenerator, scheduler: Optional[AsyncIOScheduler] = None):
        self.goal_generator = goal_generator
        self.scheduler = scheduler or AsyncIOScheduler()
        self.generated_briefings: List[Briefing] = []
        self.active_building_ids: List[str] = []
        
    def start(self):
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
        logger.info("BriefingScheduler started")
        
    def add_building(self, building_id: str):
        """Add a building to schedule briefings for"""
        if building_id in self.active_building_ids:
            return
            
        self.active_building_ids.append(building_id)
        
        # Schedule Daily Morning Briefing (7:00 AM)
        self.scheduler.add_job(
            self._run_daily_briefing,
            CronTrigger(hour=7, minute=0),
            args=[building_id],
            id=f"daily_{building_id}",
            replace_existing=True
        )
        logger.info(f"Scheduled daily briefing for {building_id} at 7:00 AM")
        
        # Schedule Asset Monitoring (Hourly check for Urgent Risks)
        self.scheduler.add_job(
            self._run_urgent_check,
            CronTrigger(minute=0), # Every hour
            args=[building_id],
            id=f"urgent_{building_id}",
            replace_existing=True
        )
        
    async def _run_daily_briefing(self, building_id: str):
        """Generate and deliver daily briefing"""
        logger.info(f"Generating daily briefing for {building_id}")
        goals = self.goal_generator.generate_goals(building_id)
        briefing = BriefingGenerator.generate_daily_briefing(building_id, goals)
        self._deliver_briefing(briefing)
        
    async def _run_urgent_check(self, building_id: str):
        """Check for urgent risks requiring immediate alert"""
        goals = self.goal_generator.generate_goals(building_id)
        
        # Check for NEW critical goals
        for goal in goals:
            if goal.priority == "critical":
                # Check if we already alerted on this recently (simple dedupe logic omitted for brevity)
                briefing = BriefingGenerator.generate_urgent_alert(building_id, goal)
                self._deliver_briefing(briefing)
                
    def _deliver_briefing(self, briefing: Briefing):
        """Mock delivery mechanism"""
        briefing.is_delivered = True
        self.generated_briefings.append(briefing)
        # In production -> Send to WebSocket / Email / Notification Service
        logger.info(f"Delivered Briefing [{briefing.briefing_type.value}]: {briefing.headline}")
        
    def get_latest_briefing(self, building_id: str) -> Optional[Briefing]:
        """Get the most recent briefing for a building"""
        relevant = [b for b in self.generated_briefings if b.building_id == building_id]
        if not relevant:
            return None
        return sorted(relevant, key=lambda b: b.created_at, reverse=True)[0]
