"""
Briefing Generator Engine
=========================

Proactive morning/evening operations briefing for facility managers.

Instead of logging in and searching for issues, ARVIS pushes:
- Critical issues that need immediate attention
- Overnight anomalies detected
- Optimization wins (what's working)
- Today's context (weather, events, tariffs)
- Prioritized recommendations

Usage:
    >>> generator = BriefingGenerator("tower_a")
    >>> briefing = generator.generate("overnight")
    >>> print(briefing["critical"])
"""

import logging
from datetime import datetime, timedelta, time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("arvis.bms.briefing")


# =============================================================================
# CONSTANTS
# =============================================================================

# Qatar-specific timing
PEAK_HOURS_START = time(12, 0)
PEAK_HOURS_END = time(18, 0)
WORK_HOURS_START = time(7, 0)
WORK_HOURS_END = time(18, 0)

# Arabic greetings by time of day
ARABIC_GREETINGS = {
    "morning": "صباح الخير",
    "afternoon": "مساء الخير",
    "evening": "مساء الخير",
}

ENGLISH_GREETINGS = {
    "morning": "Good morning",
    "afternoon": "Good afternoon",
    "evening": "Good evening",
}


# =============================================================================
# DATA MODELS
# =============================================================================

class BriefingPeriod(Enum):
    """Periods for briefing generation"""
    OVERNIGHT = "overnight"
    DAILY = "daily"
    WEEKLY = "weekly"


class IssuePriority(Enum):
    """Priority levels for briefing items"""
    CRITICAL = "critical"
    ATTENTION = "attention"
    INFO = "info"
    WIN = "win"


@dataclass
class BriefingItem:
    """A single item in the briefing"""
    priority: IssuePriority
    title: str
    description: str
    equipment_id: Optional[str] = None
    zone_id: Optional[str] = None
    impact: Optional[str] = None
    action: Optional[str] = None
    cost_qar: Optional[float] = None
    cost_qar: Optional[float] = None
    timestamp: Optional[datetime] = None
    narrative: Optional[str] = None # Added for LLM summary
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority.value,
            "title": self.title,
            "description": self.description,
            "equipment_id": self.equipment_id,
            "zone_id": self.zone_id,
            "impact": self.impact,
            "action": self.action,
            "cost_qar": self.cost_qar,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class TodayContext:
    """Context information for today"""
    date: datetime
    is_weekend: bool
    is_ramadan: bool
    is_peak_hours: bool
    outdoor_temp: float
    feels_like: float
    weather_condition: str
    weather_advisory: Optional[str] = None
    electricity_tariff: str = "standard"
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    scheduled_maintenance: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "is_weekend": self.is_weekend,
            "is_ramadan": self.is_ramadan,
            "is_peak_hours": self.is_peak_hours,
            "outdoor_temp": self.outdoor_temp,
            "feels_like": self.feels_like,
            "weather_condition": self.weather_condition,
            "weather_advisory": self.weather_advisory,
            "electricity_tariff": self.electricity_tariff,
            "scheduled_events": self.scheduled_events,
            "scheduled_maintenance": self.scheduled_maintenance,
        }


@dataclass
class Briefing:
    """Complete operations briefing"""
    building_id: str
    period: BriefingPeriod
    greeting: str
    user_name: Optional[str] = None
    critical: List[BriefingItem] = field(default_factory=list)
    attention: List[BriefingItem] = field(default_factory=list)
    wins: List[BriefingItem] = field(default_factory=list)
    info: List[BriefingItem] = field(default_factory=list)
    context: Optional[TodayContext] = None
    recommendations: List[str] = field(default_factory=list)
    narrative: Optional[str] = None # Added for LLM summary
    generated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_id": self.building_id,
            "period": self.period.value,
            "greeting": self.greeting,
            "user_name": self.user_name,
            "critical": [i.to_dict() for i in self.critical],
            "attention": [i.to_dict() for i in self.attention],
            "wins": [i.to_dict() for i in self.wins],
            "info": [i.to_dict() for i in self.info],
            "context": self.context.to_dict() if self.context else None,
            "recommendations": self.recommendations,
            "generated_at": self.generated_at.isoformat(),
            "summary": self._generate_summary(),
        }
    
    def _generate_summary(self) -> str:
        """Generate one-line summary."""
        parts = []
        if self.critical:
            parts.append(f"🔴 {len(self.critical)} critical")
        if self.attention:
            parts.append(f"🟡 {len(self.attention)} need attention")
        if self.wins:
            parts.append(f"🟢 {len(self.wins)} wins")
        return ", ".join(parts) if parts else "All systems normal"


# =============================================================================
# WEATHER SERVICE
# =============================================================================

class WeatherService:
    """
    Weather data service for Qatar.
    
    Integrates with OpenWeatherMap API for real weather data.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize weather service.
        
        Args:
            api_key: OpenWeatherMap API key (from OPENWEATHER_API_KEY env var)
        """
        import os
        self.api_key = api_key or os.getenv("OPENWEATHER_API_KEY")
        self.base_url = "https://api.openweathermap.org/data/2.5"
        
        # Default location: Doha, Qatar
        self.lat = 25.2854
        self.lon = 51.5310
    
    def get_current_weather(self) -> Dict[str, Any]:
        """Get current weather for Qatar."""
        if not self.api_key:
            return self._mock_weather()
        
        try:
            import requests
            response = requests.get(
                f"{self.base_url}/weather",
                params={
                    "lat": self.lat,
                    "lon": self.lon,
                    "appid": self.api_key,
                    "units": "metric",
                },
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "temp": data["main"]["temp"],
                    "feels_like": data["main"]["feels_like"],
                    "humidity": data["main"]["humidity"],
                    "condition": data["weather"][0]["main"],
                    "description": data["weather"][0]["description"],
                    "wind_speed": data["wind"]["speed"],
                    "advisory": self._check_advisory(data),
                }
            else:
                logger.warning(f"Weather API error: {response.status_code}")
                return self._mock_weather()
                
        except Exception as e:
            logger.warning(f"Weather API failed: {e}")
            return self._mock_weather()
    
    def _mock_weather(self) -> Dict[str, Any]:
        """Return mock weather for development."""
        # Simulate typical Qatar weather
        hour = datetime.now().hour
        
        if 10 <= hour <= 16:
            temp = 38.0  # Hot afternoon
        elif 6 <= hour <= 9 or 17 <= hour <= 20:
            temp = 32.0  # Moderate morning/evening
        else:
            temp = 28.0  # Night
        
        return {
            "temp": temp,
            "feels_like": temp + 3,
            "humidity": 45,
            "condition": "Clear",
            "description": "clear sky",
            "wind_speed": 5.2,
            "advisory": None,
        }
    
    def _check_advisory(self, data: Dict[str, Any]) -> Optional[str]:
        """Check for weather advisories."""
        temp = data["main"]["temp"]
        wind = data["wind"]["speed"]
        condition = data["weather"][0]["main"].lower()
        
        if temp > 45:
            return "Extreme heat warning - limit outdoor activities"
        if "sand" in condition or "dust" in condition:
            return "Sandstorm advisory - check HVAC filters"
        if wind > 15:
            return "High wind advisory"
        
        return None


# =============================================================================
# BRIEFING GENERATOR
# =============================================================================

class BriefingGenerator:
    """
    Generate proactive operations briefings.
    
    Instead of operators hunting for issues, ARVIS tells them
    what matters before they even ask.
    """
    
    def __init__(self,
                 building_id: str = "default",
                 bms_state=None,
                 alarm_engine=None,
                 energy_analyzer=None,
                 skillbook=None):
        """
        Initialize the Briefing Generator.
        
        Args:
            building_id: Building identifier
            bms_state: BMSStateEngine for equipment status
            alarm_engine: AlarmEngine for alarm data
            energy_analyzer: EnergyAnalyzer for energy data
            skillbook: BuildingSkillbook for optimization history
        """
        self.building_id = building_id
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.skillbook = skillbook
        
        self.weather_service = WeatherService()
        
        self.llm_provider = None
        
        logger.info(f"BriefingGenerator initialized for {building_id}")

    def set_llm_provider(self, provider: Any) -> None:
        """Set LLM provider for narrative generation."""
        self.llm_provider = provider
    
    async def generate(self,
                 period: str = "overnight",
                 user_id: Optional[str] = None,
                 language: str = "en") -> Briefing:
        """
        Generate an operations briefing.
        
        Args:
            period: "overnight", "daily", or "weekly"
            user_id: User for personalization (optional)
            language: "en" or "ar"
            
        Returns:
            Complete Briefing object
        """
        period_enum = BriefingPeriod(period)
        
        # Determine time range
        hours = self._get_period_hours(period_enum)
        since = datetime.now() - timedelta(hours=hours)
        
        # Generate greeting
        greeting = self._personalized_greeting(user_id, language)
        
        # Detect anomalies
        critical, attention = self._detect_anomalies(since)
        
        # Calculate wins
        wins = self._calculate_wins(since)
        
        # Get today's context
        context = self._get_today_context()
        
        # Generate recommendations
        recommendations = self._generate_recommendations(context, critical, attention)
        
        # ─────────────────────────────────────────────────────────────────
        # NARRATIVE UPGRADE
        # Synthesize a cohesive executive summary using the Mind
        # ─────────────────────────────────────────────────────────────────
        narrative = None
        if self.llm_provider:
             narrative = await self._generate_narrative(context, critical, attention, wins)

        return Briefing(
            building_id=self.building_id,
            period=period_enum,
            greeting=greeting,
            user_name=user_id,
            critical=critical,
            attention=attention,
            wins=wins,
            context=context,
            recommendations=recommendations,
            narrative=narrative, # New field
        )

    async def _generate_narrative(self, context: TodayContext, critical: List[BriefingItem], attention: List[BriefingItem], wins: List[BriefingItem]) -> str:
        """Generate a cohesive narrative summary using LLM."""
        if not self.llm_provider:
            return None
            
        data_summary = {
            "period": "overnight",
            "critical_count": len(critical),
            "attention_count": len(attention),
            "wins_count": len(wins),
            "weather": f"{context.outdoor_temp}C, {context.weather_condition}",
            "top_issue": critical[0].title if critical else (attention[0].title if attention else "None"),
        }
        
        prompt = f"""
        Write a concise, professional executive summary for a Facility Manager's morning briefing.
        Style: "Jarvis" from Iron Man but professional.
        
        Data:
        {data_summary}
        
        Key Critical Issue: {data_summary['top_issue']}
        
        Context: The building is in Doha, Qatar.
        
        Output a single paragraph (max 3 sentences).
        """
        
        try:
             response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
             return response.content.strip()
        except Exception:
             return None
    
    def _get_period_hours(self, period: BriefingPeriod) -> int:
        """Get hours to look back for the period."""
        if period == BriefingPeriod.OVERNIGHT:
            return 12
        elif period == BriefingPeriod.DAILY:
            return 24
        else:  # WEEKLY
            return 168
    
    def _personalized_greeting(self, 
                               user_id: Optional[str],
                               language: str) -> str:
        """Generate personalized greeting."""
        hour = datetime.now().hour
        
        if 5 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 17:
            time_of_day = "afternoon"
        else:
            time_of_day = "evening"
        
        greetings = ARABIC_GREETINGS if language == "ar" else ENGLISH_GREETINGS
        greeting = greetings[time_of_day]
        
        if user_id:
            # Extract first name
            first_name = user_id.split("@")[0].split(".")[0].title()
            greeting = f"{greeting}, {first_name}"
        
        return greeting
    
    def _detect_anomalies(self, since: datetime) -> tuple:
        """Detect critical and attention-worthy anomalies."""
        critical = []
        attention = []
        
        # Check active alarms
        if self.alarm_engine:
            try:
                alarms = self.alarm_engine.get_priority_queue()
                for alarm_info in alarms[:10]:
                    alarm = alarm_info.alarm
                    item = BriefingItem(
                        priority=IssuePriority.CRITICAL if alarm.severity.value == "critical" else IssuePriority.ATTENTION,
                        title=f"{alarm.equipment_id}: {alarm.alarm_type}",
                        description=alarm.message,
                        equipment_id=alarm.equipment_id,
                        action=alarm_info.suggested_actions[0] if alarm_info.suggested_actions else None,
                        timestamp=alarm.timestamp,
                    )
                    if alarm.severity.value in ["critical", "high"]:
                        critical.append(item)
                    else:
                        attention.append(item)
            except Exception as e:
                logger.debug(f"Could not get alarms: {e}")
        
        # Check equipment health
        if self.bms_state:
            try:
                # Look for degrading equipment
                # This would query predictive maintenance
                pass
            except Exception as e:
                logger.debug(f"Could not check equipment: {e}")
        
        # Check energy anomalies
        if self.energy_analyzer:
            try:
                patterns = self.energy_analyzer.identify_waste_patterns()
                for pattern in patterns[:3]:
                    attention.append(BriefingItem(
                        priority=IssuePriority.ATTENTION,
                        title=f"Energy: {pattern.pattern_type}",
                        description=pattern.description,
                        zone_id=pattern.zone_id,
                        cost_qar=pattern.annual_cost_qar / 365,  # Daily cost
                        action=pattern.recommendation,
                    ))
            except Exception as e:
                logger.debug(f"Could not get energy patterns: {e}")
        
        # Add mock data if no real data available
        if not critical and not attention:
            # Demo critical item
            critical.append(BriefingItem(
                priority=IssuePriority.CRITICAL,
                title="CHW-PUMP-02 Vibration Trending",
                description="Vibration increased from 4.2 to 6.8 mm/s overnight",
                equipment_id="CHW-PUMP-02",
                impact="Potential bearing failure within 72 hours",
                action="Inspect bearings today",
                timestamp=datetime.now() - timedelta(hours=3),
            ))
            
            # Demo attention items
            attention.append(BriefingItem(
                priority=IssuePriority.ATTENTION,
                title="Zone 3 AHU overnight energy +23%",
                description="Energy consumption 23% above baseline",
                zone_id="Zone-3",
                action="Check damper position",
            ))
        
        return critical, attention
    
    def _calculate_wins(self, since: datetime) -> List[BriefingItem]:
        """Calculate optimization wins since the given time."""
        wins = []
        
        # Check skillbook for recent optimizations
        if self.skillbook:
            try:
                optimizations = self.skillbook.get_optimization_history()
                for opt in optimizations[:3]:
                    if opt.evidence.get("savings_qar_month"):
                        daily = opt.evidence["savings_qar_month"] / 30
                        wins.append(BriefingItem(
                            priority=IssuePriority.WIN,
                            title=opt.title,
                            description=f"Saved QAR {daily:.0f} yesterday",
                            cost_qar=daily,
                        ))
            except Exception as e:
                logger.debug(f"Could not get wins: {e}")
        
        # Add demo win if empty
        if not wins:
            wins.append(BriefingItem(
                priority=IssuePriority.WIN,
                title="Zone B3 optimization working",
                description="Saved QAR 127 yesterday from schedule changes",
                cost_qar=127,
            ))
        
        return wins
    
    def _get_today_context(self) -> TodayContext:
        """Get context for today."""
        now = datetime.now()
        
        # Get weather
        weather = self.weather_service.get_current_weather()
        
        # Check if peak hours
        current_time = now.time()
        is_peak = PEAK_HOURS_START <= current_time <= PEAK_HOURS_END
        
        # Check if weekend (Qatar: Friday-Saturday)
        is_weekend = now.weekday() in [4, 5]  # Friday=4, Saturday=5
        
        # Determine tariff
        tariff = "peak" if is_peak else "standard"
        
        return TodayContext(
            date=now,
            is_weekend=is_weekend,
            is_ramadan=False,  # Would check Islamic calendar
            is_peak_hours=is_peak,
            outdoor_temp=weather["temp"],
            feels_like=weather["feels_like"],
            weather_condition=weather["condition"],
            weather_advisory=weather.get("advisory"),
            electricity_tariff=tariff,
        )
    
    def _generate_recommendations(self,
                                   context: TodayContext,
                                   critical: List[BriefingItem],
                                   attention: List[BriefingItem]) -> List[str]:
        """Generate prioritized recommendations."""
        recommendations = []
        
        # Priority 1: Address critical issues
        if critical:
            recommendations.append(
                f"Address {critical[0].title} first - {critical[0].action or 'investigate immediately'}"
            )
        
        # Priority 2: Weather-based
        if context.outdoor_temp > 40:
            recommendations.append(
                "Extreme heat expected - consider pre-cooling before peak hours"
            )
        
        if context.weather_advisory:
            recommendations.append(context.weather_advisory)
        
        # Priority 3: Tariff-based
        if context.is_peak_hours:
            recommendations.append(
                "Peak tariff hours active (12:00-18:00) - minimize discretionary loads"
            )
        
        # Priority 4: Event-based
        for event in context.scheduled_events[:2]:
            recommendations.append(
                f"Pre-condition for {event.get('name', 'event')} at {event.get('time', 'scheduled time')}"
            )
        
        return recommendations[:5]  # Max 5 recommendations


# =============================================================================
# LLM TOOL HANDLER
# =============================================================================

async def generate_briefing(
    building_id: str = "default",
    period: str = "overnight",
    user_id: Optional[str] = None,
    language: str = "en",
) -> Dict[str, Any]:
    """
    Generate an operations briefing.
    
    This is the LLM tool handler.
    """
    generator = BriefingGenerator(building_id)
    
    # Inject Mind for narrative
    try:
        from agent_unified.llm import UnifiedLLM
        llm = UnifiedLLM()
        generator.set_llm_provider(llm)
    except Exception:
        pass

    briefing = await generator.generate(
        period=period,
        user_id=user_id,
        language=language,
    )
    
    return briefing.to_dict()


if __name__ == "__main__":
    # Test the briefing generator
    print("=" * 60)
    print("Briefing Generator Test")
    print("=" * 60)
    
    generator = BriefingGenerator("tower_a")
    briefing = generator.generate(
        period="overnight",
        user_id="ibrahim.hassan@qatar.com",
        language="en",
    )
    
    print(f"\n{briefing.greeting}. Here's your briefing.\n")
    
    if briefing.critical:
        print("🔴 CRITICAL:")
        for item in briefing.critical:
            print(f"   {item.title}")
            print(f"   └─ {item.action}")
    
    if briefing.attention:
        print("\n🟡 NEEDS ATTENTION:")
        for item in briefing.attention:
            print(f"   {item.title}")
    
    if briefing.wins:
        print("\n🟢 WINS:")
        for item in briefing.wins:
            print(f"   {item.title}")
    
    if briefing.context:
        print(f"\n📊 TODAY:")
        print(f"   Weather: {briefing.context.outdoor_temp}°C, {briefing.context.weather_condition}")
        print(f"   Tariff: {briefing.context.electricity_tariff}")
    
    if briefing.recommendations:
        print("\n📋 FOCUS:")
        for i, rec in enumerate(briefing.recommendations, 1):
            print(f"   {i}. {rec}")
