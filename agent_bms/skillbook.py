"""
Building Skillbook
==================

Institutional memory for building-specific knowledge.

The Skillbook captures:
- Equipment quirks ("CH-02 trips if started above 35°C outdoor")
- Learned patterns ("Friday occupancy = 15% of weekday")
- Optimization history (what worked, what didn't)
- Contractor notes (verification rates, quality)
- Failure history (for predictive reference)

All skills have confidence scores that increase/decrease
based on verification outcomes.

Usage:
    >>> skillbook = BuildingSkillbook("tower_a")
    >>> skillbook.add_skill({
    ...     "type": "equipment_quirk",
    ...     "equipment_id": "CH-02",
    ...     "description": "Do not start if outdoor > 35°C",
    ...     "evidence": {"failure_count": 3}
    ... })
    >>> relevant = skillbook.get_relevant_skills({"equipment_id": "CH-02"})
"""

import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger("arvis.bms.skillbook")


# =============================================================================
# DATA MODELS
# =============================================================================

class SkillType(Enum):
    """Types of learned skills"""
    EQUIPMENT_QUIRK = "equipment_quirk"
    PATTERN = "pattern"
    OPTIMIZATION = "optimization"
    FAILURE = "failure"
    CONTRACTOR_NOTE = "contractor_note"
    SCHEDULE = "schedule"
    THRESHOLD = "threshold"


class SkillStatus(Enum):
    """Status of a skill"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    UNVERIFIED = "unverified"
    SUPERSEDED = "superseded"


@dataclass
class Skill:
    """A learned piece of building knowledge"""
    skill_id: str
    building_id: str
    skill_type: SkillType
    title: str
    description: str
    confidence: float = 0.5  # 0-1, starts neutral
    verified_count: int = 0
    failed_count: int = 0
    status: SkillStatus = SkillStatus.UNVERIFIED
    equipment_id: Optional[str] = None
    zone_id: Optional[str] = None
    contractor_id: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    created_by: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "building_id": self.building_id,
            "skill_type": self.skill_type.value,
            "title": self.title,
            "description": self.description,
            "confidence": self.confidence,
            "verified_count": self.verified_count,
            "failed_count": self.failed_count,
            "status": self.status.value,
            "equipment_id": self.equipment_id,
            "zone_id": self.zone_id,
            "contractor_id": self.contractor_id,
            "evidence": self.evidence,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(
            skill_id=data["skill_id"],
            building_id=data["building_id"],
            skill_type=SkillType(data["skill_type"]),
            title=data["title"],
            description=data["description"],
            confidence=data.get("confidence", 0.5),
            verified_count=data.get("verified_count", 0),
            failed_count=data.get("failed_count", 0),
            status=SkillStatus(data.get("status", "unverified")),
            equipment_id=data.get("equipment_id"),
            zone_id=data.get("zone_id"),
            contractor_id=data.get("contractor_id"),
            evidence=data.get("evidence", {}),
            tags=data.get("tags", []),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            created_by=data.get("created_by", "system"),
        )


# =============================================================================
# BUILDING SKILLBOOK
# =============================================================================

class BuildingSkillbook:
    """
    Persistent memory for building-specific knowledge.
    
    Every building develops its own "personality" - quirks, patterns,
    and learned optimizations. The Skillbook captures this institutional
    knowledge so it's never lost when staff changes.
    """
    
    def __init__(self, 
                 building_id: str = "default",
                 db_path: Optional[str] = None):
        """
        Initialize the Building Skillbook.
        
        Args:
            building_id: Unique building identifier
            db_path: Path to SQLite database (default: agent_bms/data/arvis_bms.db)
        """
        self.building_id = building_id
        
        # Database path
        if db_path is None:
            db_dir = Path(__file__).parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = str(db_dir / "arvis_bms.db")
        
        self.db_path = db_path
        self._init_database()
        
        logger.info(f"BuildingSkillbook initialized for {building_id}")
    
    def _init_database(self) -> None:
        """Initialize database tables for skillbook."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT PRIMARY KEY,
                    building_id TEXT NOT NULL,
                    skill_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    verified_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'unverified',
                    equipment_id TEXT,
                    zone_id TEXT,
                    contractor_id TEXT,
                    evidence TEXT,
                    tags TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    created_by TEXT DEFAULT 'system'
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_building 
                ON skills(building_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_equipment 
                ON skills(equipment_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_type 
                ON skills(skill_type)
            """)

            # Meta-Cognition: Decisions Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    building_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    context TEXT,
                    chosen_action TEXT,
                    alternatives TEXT,
                    confidence REAL,
                    reasoning TEXT,
                    outcome TEXT,
                    outcome_quality TEXT,
                    event_id TEXT
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_time 
                ON decisions(timestamp)
            """)
            
            conn.commit()
    
    def add_skill(self, 
                  skill_type: str,
                  title: str,
                  description: str,
                  equipment_id: Optional[str] = None,
                  zone_id: Optional[str] = None,
                  contractor_id: Optional[str] = None,
                  evidence: Optional[Dict[str, Any]] = None,
                  tags: Optional[List[str]] = None,
                  created_by: str = "system") -> Skill:
        """
        Add a new skill to the skillbook.
        
        Args:
            skill_type: Type of skill (equipment_quirk, pattern, optimization, etc.)
            title: Short title for the skill
            description: Detailed description
            equipment_id: Related equipment (optional)
            zone_id: Related zone (optional)
            contractor_id: Related contractor (optional)
            evidence: Supporting evidence/data
            tags: List of tags for categorization
            created_by: Who added this skill
            
        Returns:
            The created Skill object
        """
        skill_id = f"skill_{self.building_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        skill = Skill(
            skill_id=skill_id,
            building_id=self.building_id,
            skill_type=SkillType(skill_type),
            title=title,
            description=description,
            equipment_id=equipment_id,
            zone_id=zone_id,
            contractor_id=contractor_id,
            evidence=evidence or {},
            tags=tags or [],
            created_by=created_by,
        )
        
        # Check for conflicts/duplicates
        existing = self._find_similar_skills(skill)
        if existing:
            logger.info(f"Similar skill exists: {existing[0].skill_id}")
            # Increase confidence of existing instead of duplicating
            self._merge_skill_evidence(existing[0], skill)
            return existing[0]
        
        self._save_skill(skill)
        logger.info(f"Added skill: {skill_id} - {title}")
        
        return skill
    
    def _save_skill(self, skill: Skill) -> None:
        """Save skill to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skills 
                (skill_id, building_id, skill_type, title, description,
                 confidence, verified_count, failed_count, status,
                 equipment_id, zone_id, contractor_id, evidence, tags,
                 created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill.skill_id,
                skill.building_id,
                skill.skill_type.value,
                skill.title,
                skill.description,
                skill.confidence,
                skill.verified_count,
                skill.failed_count,
                skill.status.value,
                skill.equipment_id,
                skill.zone_id,
                skill.contractor_id,
                json.dumps(skill.evidence),
                json.dumps(skill.tags),
                skill.created_at.isoformat(),
                skill.updated_at.isoformat(),
                skill.created_by,
            ))
            conn.commit()
    
    def _find_similar_skills(self, skill: Skill) -> List[Skill]:
        """Find existing skills that are similar."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT * FROM skills 
                WHERE building_id = ? 
                AND skill_type = ?
                AND status != 'deprecated'
            """
            params = [self.building_id, skill.skill_type.value]
            
            if skill.equipment_id:
                query += " AND equipment_id = ?"
                params.append(skill.equipment_id)
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            similar = []
            for row in rows:
                existing = self._row_to_skill(row)
                # Check title similarity (simple)
                if skill.title.lower() in existing.title.lower() or \
                   existing.title.lower() in skill.title.lower():
                    similar.append(existing)
            
            return similar
    
    def _merge_skill_evidence(self, existing: Skill, new: Skill) -> None:
        """Merge evidence from new skill into existing."""
        # Merge evidence
        existing.evidence.update(new.evidence)
        
        # Increase confidence slightly
        existing.confidence = min(existing.confidence + 0.05, 1.0)
        existing.updated_at = datetime.now()
        
        self._save_skill(existing)
        logger.info(f"Merged evidence into existing skill: {existing.skill_id}")
    
    def _row_to_skill(self, row: sqlite3.Row) -> Skill:
        """Convert database row to Skill object."""
        return Skill(
            skill_id=row["skill_id"],
            building_id=row["building_id"],
            skill_type=SkillType(row["skill_type"]),
            title=row["title"],
            description=row["description"],
            confidence=row["confidence"],
            verified_count=row["verified_count"],
            failed_count=row["failed_count"],
            status=SkillStatus(row["status"]),
            equipment_id=row["equipment_id"],
            zone_id=row["zone_id"],
            contractor_id=row["contractor_id"],
            evidence=json.loads(row["evidence"]) if row["evidence"] else {},
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            created_by=row["created_by"],
        )
    
    def verify_skill(self, skill_id: str, outcome: bool) -> None:
        """
        Update skill confidence based on verification outcome.
        
        Args:
            skill_id: The skill to verify
            outcome: True if skill was confirmed, False if it failed
        """
        skill = self.get_skill(skill_id)
        if not skill:
            logger.warning(f"Skill not found: {skill_id}")
            return
        
        if outcome:
            skill.verified_count += 1
            skill.confidence = min(skill.confidence + 0.1, 1.0)
            if skill.confidence >= 0.7 and skill.verified_count >= 3:
                skill.status = SkillStatus.ACTIVE
        else:
            skill.failed_count += 1
            skill.confidence = max(skill.confidence - 0.2, 0.0)
            if skill.confidence < 0.2:
                skill.status = SkillStatus.DEPRECATED
        
        skill.updated_at = datetime.now()
        self._save_skill(skill)
        
        logger.info(f"Skill {skill_id} verified: {outcome}, confidence: {skill.confidence}")
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a specific skill by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM skills WHERE skill_id = ?",
                (skill_id,)
            )
            row = cursor.fetchone()
            return self._row_to_skill(row) if row else None
    
    def get_relevant_skills(self, 
                           context: Dict[str, Any],
                           limit: int = 10) -> List[Skill]:
        """
        Get skills relevant to the current context.
        
        Args:
            context: Current situation (equipment_id, zone_id, skill_type, etc.)
            limit: Maximum number of skills to return
            
        Returns:
            List of relevant skills sorted by confidence
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT * FROM skills 
                WHERE building_id = ?
                AND status IN ('active', 'unverified')
            """
            params = [self.building_id]
            
            if context.get("equipment_id"):
                query += " AND (equipment_id = ? OR equipment_id IS NULL)"
                params.append(context["equipment_id"])
            
            if context.get("zone_id"):
                query += " AND (zone_id = ? OR zone_id IS NULL)"
                params.append(context["zone_id"])
            
            if context.get("skill_type"):
                query += " AND skill_type = ?"
                params.append(context["skill_type"])
            
            if context.get("contractor_id"):
                query += " AND contractor_id = ?"
                params.append(context["contractor_id"])
            
            query += " ORDER BY confidence DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, params)
            return [self._row_to_skill(row) for row in cursor.fetchall()]
    
    def get_equipment_quirks(self, equipment_id: str) -> List[Skill]:
        """Get all quirks for a specific equipment."""
        return self.get_relevant_skills({
            "equipment_id": equipment_id,
            "skill_type": "equipment_quirk",
        })
    
    def get_optimization_history(self) -> List[Skill]:
        """Get all optimization attempts and their outcomes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM skills 
                WHERE building_id = ?
                AND skill_type = 'optimization'
                ORDER BY created_at DESC
            """, (self.building_id,))
            return [self._row_to_skill(row) for row in cursor.fetchall()]
    
    def get_contractor_notes(self, contractor_id: str) -> List[Skill]:
        """Get all notes about a specific contractor."""
        return self.get_relevant_skills({
            "contractor_id": contractor_id,
            "skill_type": "contractor_note",
        })
    
    def get_contractor_verification_rate(self, contractor_id: str) -> Dict[str, Any]:
        """Get verification statistics for a contractor."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN json_extract(evidence, '$.verified') = 1 THEN 1 ELSE 0 END) as verified,
                    SUM(CASE WHEN json_extract(evidence, '$.verified') = 0 THEN 1 ELSE 0 END) as unverified
                FROM skills 
                WHERE building_id = ?
                AND contractor_id = ?
                AND skill_type = 'contractor_note'
            """, (self.building_id, contractor_id))
            
            row = cursor.fetchone()
            total = row[0] or 0
            verified = row[1] or 0
            
            return {
                "contractor_id": contractor_id,
                "total_work_orders": total,
                "verified": verified,
                "unverified": total - verified,
                "verification_rate": verified / total if total > 0 else 0,
            }
    
    def get_failure_history(self, 
                           equipment_id: Optional[str] = None,
                           days: int = 365) -> List[Skill]:
        """Get failure history for the building or specific equipment."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT * FROM skills 
                WHERE building_id = ?
                AND skill_type = 'failure'
                AND created_at >= ?
            """
            params = [self.building_id, cutoff]
            
            if equipment_id:
                query += " AND equipment_id = ?"
                params.append(equipment_id)
            
            query += " ORDER BY created_at DESC"
            
            cursor = conn.execute(query, params)
            return [self._row_to_skill(row) for row in cursor.fetchall()]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of skillbook contents."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    skill_type,
                    COUNT(*) as count,
                    AVG(confidence) as avg_confidence
                FROM skills 
                WHERE building_id = ?
                AND status != 'deprecated'
                GROUP BY skill_type
            """, (self.building_id,))
            
            by_type = {}
            total = 0
            for row in cursor.fetchall():
                by_type[row[0]] = {
                    "count": row[1],
                    "avg_confidence": round(row[2], 2),
                }
                total += row[1]
            
            return {
                "building_id": self.building_id,
                "total_skills": total,
                "by_type": by_type,
            }
    
    def log_decision(self,
                     decision_id: str,
                     context: Dict[str, Any],
                     chosen_action: str,
                     alternatives: List[str],
                     confidence: float,
                     reasoning: str,
                     event_id: Optional[str] = None) -> None:
        """Log a cognitive decision for later reflection."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO decisions 
                (decision_id, building_id, timestamp, context, chosen_action,
                 alternatives, confidence, reasoning, event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision_id,
                self.building_id,
                datetime.now().isoformat(),
                json.dumps(context),
                chosen_action,
                json.dumps(alternatives),
                confidence,
                reasoning,
                event_id
            ))
            conn.commit()
            
    def update_decision_outcome(self, decision_id: str, outcome: str, quality: str) -> bool:
        """Update a decision with its observed outcome."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE decisions 
                SET outcome = ?, outcome_quality = ?
                WHERE decision_id = ?
            """, (outcome, quality, decision_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_recent_decisions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent decisions for reflection."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM decisions 
                WHERE building_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (self.building_id, limit))
            
            results = []
            for row in cursor.fetchall():
                # Safe JSON parsing
                try:
                    context = json.loads(row["context"]) if row["context"] else {}
                    alternatives = json.loads(row["alternatives"]) if row["alternatives"] else []
                except json.JSONDecodeError:
                    context = {}
                    alternatives = []
                    
                results.append({
                    "decision_id": row["decision_id"],
                    "timestamp": row["timestamp"],
                    "context": context,
                    "chosen_action": row["chosen_action"],
                    "alternatives": alternatives,
                    "confidence": row["confidence"],
                    "reasoning": row["reasoning"],
                    "outcome": row["outcome"],
                    "outcome_quality": row["outcome_quality"],
                    "event_id": row["event_id"]
                })
            return results


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_skillbooks: Dict[str, BuildingSkillbook] = {}


def get_skillbook(building_id: str = "default") -> BuildingSkillbook:
    """Get or create skillbook for a building."""
    if building_id not in _skillbooks:
        _skillbooks[building_id] = BuildingSkillbook(building_id)
    return _skillbooks[building_id]


# =============================================================================
# LLM TOOL HANDLERS
# =============================================================================

def query_skillbook(
    building_id: str = "default",
    context: Optional[Dict[str, Any]] = None,
    skill_type: Optional[str] = None,
    equipment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query the building skillbook for relevant knowledge.
    
    This is the LLM tool handler.
    
    Args:
        building_id: Building identifier
        context: Current context for relevance matching
        skill_type: Filter by skill type
        equipment_id: Filter by equipment
        
    Returns:
        Relevant skills and summary
    """
    skillbook = get_skillbook(building_id)
    
    query_context = context or {}
    if skill_type:
        query_context["skill_type"] = skill_type
    if equipment_id:
        query_context["equipment_id"] = equipment_id
    
    skills = skillbook.get_relevant_skills(query_context)
    summary = skillbook.get_summary()
    
    return {
        "skills": [s.to_dict() for s in skills],
        "summary": summary,
    }


def add_to_skillbook(
    skill_type: str,
    title: str,
    description: str,
    building_id: str = "default",
    equipment_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Add a new skill to the building skillbook.
    
    This is the LLM tool handler.
    
    Args:
        skill_type: Type (equipment_quirk, pattern, optimization, failure, contractor_note)
        title: Short title
        description: Detailed description
        building_id: Building identifier
        equipment_id: Related equipment (optional)
        zone_id: Related zone (optional)
        evidence: Supporting data (optional)
        
    Returns:
        The created skill
    """
    skillbook = get_skillbook(building_id)
    
    skill = skillbook.add_skill(
        skill_type=skill_type,
        title=title,
        description=description,
        equipment_id=equipment_id,
        zone_id=zone_id,
        evidence=evidence,
        created_by="ops_copilot",
    )
    
    return {
        "success": True,
        "skill": skill.to_dict(),
        "message": f"Skill added: {skill.title}",
    }


if __name__ == "__main__":
    # Test the skillbook
    print("=" * 60)
    print("Building Skillbook Test")
    print("=" * 60)
    
    skillbook = get_skillbook("tower_a")
    
    # Add some skills
    skill1 = skillbook.add_skill(
        skill_type="equipment_quirk",
        title="CH-02 high ambient startup issue",
        description="Do not start CH-02 if outdoor temperature > 35°C. Will trip on high head pressure.",
        equipment_id="CH-02",
        evidence={"failure_count": 3, "last_failure": "2024-07-15"},
    )
    
    skill2 = skillbook.add_skill(
        skill_type="pattern",
        title="Friday reduced occupancy",
        description="Friday occupancy is typically 15% of weekday average. Adjust HVAC schedules accordingly.",
        evidence={"avg_friday_occupancy": 0.15},
    )
    
    skill3 = skillbook.add_skill(
        skill_type="optimization",
        title="Zone B3 schedule setback",
        description="Implemented 26°C setback for Zone B3 after hours. Saves QAR 4,200/month.",
        zone_id="Zone-B3",
        evidence={"savings_qar_month": 4200, "implemented": "2024-11-01"},
    )
    
    # Verify a skill
    skillbook.verify_skill(skill1.skill_id, True)
    skillbook.verify_skill(skill1.skill_id, True)
    skillbook.verify_skill(skill1.skill_id, True)  # Now active
    
    # Query skills
    relevant = skillbook.get_relevant_skills({"equipment_id": "CH-02"})
    print(f"\nSkills for CH-02: {len(relevant)}")
    for s in relevant:
        print(f"  - {s.title} (confidence: {s.confidence})")
    
    # Get summary
    summary = skillbook.get_summary()
    print(f"\nSkillbook summary: {summary}")
