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
import aiosqlite
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections import defaultdict
from agent_commercial.graph import BMSGraph
from agent_commercial.ml.rag_optimizer import CrossEncoderReranker, BMSChunker

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
    FAULT_PATTERN = "fault_pattern"
    CONTRACTOR_NOTE = "contractor_note"
    SCHEDULE = "schedule"
    THRESHOLD = "threshold"
    PROCEDURE = "procedure"


class SkillStatus(Enum):
    """Status of a skill"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    UNVERIFIED = "unverified"
    SUPERSEDED = "superseded"
    HISTORICAL = "historical"


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
    context_signature: Dict[str, Any] = field(default_factory=dict)
    confidence_history: List[Dict[str, Any]] = field(default_factory=list)
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
            "context_signature": self.context_signature,
            "confidence_history": self.confidence_history,
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
            context_signature=data.get("context_signature", {}),
            confidence_history=data.get("confidence_history", []),
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
        
        # Initialize semantic matcher and topology graph
        from agent_commercial.ml.building_embeddings import SemanticSkillMatcher
        self.matcher = SemanticSkillMatcher()
        self.graph = BMSGraph()
        
        # RAG Optimization Components
        self.reranker = CrossEncoderReranker()
        self.chunker = BMSChunker(chunk_size=600, overlap=100)
        
        # Database path. Honors ARVIS_DB_PATH so test harnesses can
        # redirect skillbook to the same per-run isolated file as BMSDatabase.
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
        self._async_conn: Optional[aiosqlite.Connection] = None
        self._conn_lock = asyncio.Lock()   # guards _async_conn creation
        self._lock = asyncio.Lock()        # guards _initialized state
        self._initialized = False
        
        logger.info(f"BuildingSkillbook initialized for {building_id}")
    
    from contextlib import asynccontextmanager

    async def _get_async_conn(self) -> aiosqlite.Connection:
        """Return the persistent skillbook connection, creating it on first call."""
        async with self._conn_lock:
            if self._async_conn is None:
                conn = await aiosqlite.connect(self.db_path)
                conn.row_factory = aiosqlite.Row
                try:
                    await conn.execute("PRAGMA busy_timeout=60000")
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA synchronous=NORMAL")
                except Exception as e:
                    logger.warning(f"Failed to set Skillbook PRAGMAs: {e}")
                self._async_conn = conn
            return self._async_conn

    async def close(self) -> None:
        """Close the persistent skillbook connection."""
        async with self._conn_lock:
            if self._async_conn is not None:
                try:
                    await self._async_conn.close()
                except Exception:
                    pass
                finally:
                    self._async_conn = None

    @asynccontextmanager
    async def get_db(self):
        """Yield the persistent skillbook connection (no open/close per call)."""
        conn = await self._get_async_conn()
        yield conn
    
    async def ensure_initialized(self) -> None:
        """Initialize database tables for skillbook (Async)."""
        if self._initialized:
            return
            
        async with self._lock:
            # Re-check after acquiring lock
            if not self._initialized:
                await self._init_database()
                # Load existing skills into semantic matcher for immediate recall
                if self.matcher.is_available:
                    await self._load_skills_to_matcher()
                self._initialized = True
    
    async def _init_database(self) -> None:
        """Initialize database tables for skillbook (Async)."""
        conn = await self._get_async_conn()

        await conn.execute("""
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
                context_signature TEXT,
                confidence_history TEXT,
                tags TEXT,
                created_at TEXT,
                updated_at TEXT,
                created_by TEXT DEFAULT 'system'
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_building ON skills(building_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_equipment ON skills(equipment_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_type ON skills(skill_type)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                building_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                context TEXT,
                chosen_action TEXT NOT NULL,
                alternatives TEXT,
                confidence REAL,
                reasoning TEXT,
                outcome TEXT,
                outcome_quality TEXT,
                event_id TEXT,
                trajectory TEXT
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_building ON decisions(building_id)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_usage (
                usage_id TEXT PRIMARY KEY,
                building_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args TEXT,
                success INTEGER,
                error TEXT,
                duration_ms REAL,
                relevant_skill_id TEXT,
                FOREIGN KEY (relevant_skill_id) REFERENCES skills(skill_id)
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_usage_name ON tool_usage(tool_name)")

        await conn.commit()
        logger.info("Database schema initialized")

    async def _load_skills_to_matcher(self) -> None:
        """Load all skills from database into the semantic matcher (Async)."""
        try:
            conn = await self._get_async_conn()
            async with conn.execute(
                "SELECT skill_id, title, description FROM skills WHERE building_id = ?",
                (self.building_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    text = f"{row['title']} {row['description']}"
                    self.matcher.add_skill(row['skill_id'], text)
            logger.info(f"Loaded {len(rows)} skills into semantic matcher.")
        except Exception as e:
            logger.error(f"Error loading skills to matcher: {e}")
    
    async def add_skill(self, 
                  skill_type: str,
                  title: str,
                  description: str,
                  equipment_id: Optional[str] = None,
                  confidence: float = 0.5,
                  zone_id: Optional[str] = None,
                  contractor_id: Optional[str] = None,
                  evidence: Optional[Dict[str, Any]] = None,
                  context_signature: Optional[Dict[str, Any]] = None,
                  tags: Optional[List[str]] = None,
                  created_by: str = "system",
                  auto_chunk: bool = True) -> List[Skill]:
        """
        Add a learned skill or pattern to the skillbook.
        
        Args:
            skill_type: Type of skill (equipment_quirk, pattern, optimization, etc.)
            title: Short title for the skill
            description: Detailed description
            equipment_id: Related equipment (optional)
            confidence: Confidence score for the skill
            zone_id: Related zone (optional)
            contractor_id: Related contractor (optional)
            evidence: Supporting evidence/data
            tags: List of tags for categorization
            created_by: Who added this skill
            auto_chunk: Automatically chunk long descriptions
            
        Returns:
            List of created Skills
        """
        await self.ensure_initialized()
        created_skills = []
        
        # Determine if we should chunk
        descriptions = [description]
        if auto_chunk and len(description) > 1000:
            logger.info(f"Description too long ({len(description)} chars). Applying semantic chunking.")
            chunks = self.chunker.chunk_document(description)
            descriptions = [c["text"] for c in chunks]
            
        for i, desc in enumerate(descriptions):
            effective_title = title if len(descriptions) == 1 else f"{title} (Part {i+1})"
            
            skill_id = f"skill_{self.building_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{i}"
            
            skill = Skill(
                skill_id=skill_id,
                building_id=self.building_id,
                skill_type=SkillType(skill_type),
                title=effective_title,
                description=desc,
                confidence=confidence,
                equipment_id=equipment_id,
                zone_id=zone_id,
                contractor_id=contractor_id,
                evidence=evidence or {},
                context_signature=context_signature or {},
                tags=tags or [],
                created_by=created_by,
            )
            
            # Check for conflicts/duplicates
            existing = await self._find_similar_skills(skill)
            if existing:
                logger.info(f"Similar skill exists: {existing[0].skill_id}")
                await self._merge_skill_evidence(existing[0], skill)
                created_skills.append(existing[0])
            else:
                await self._save_skill(skill)
                logger.info(f"Added skill: {skill_id} - {effective_title}")
                created_skills.append(skill)
        
        return created_skills
    
    async def _save_skill(self, skill: Skill) -> None:
        """Save skill to database (Async)."""
        async with self.get_db() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO skills 
                (skill_id, building_id, skill_type, title, description,
                 confidence, verified_count, failed_count, status,
                 equipment_id, zone_id, contractor_id, evidence, context_signature, 
                 confidence_history, tags, created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(skill.context_signature),
                json.dumps(skill.confidence_history),
                json.dumps(skill.tags),
                skill.created_at.isoformat(),
                skill.updated_at.isoformat(),
                skill.created_by,
            ))
            await conn.commit()
            
        # Update semantic matcher
        if self.matcher.is_available:
            self.matcher.add_skill(skill.skill_id, f"{skill.title} {skill.description}")
    
    async def _find_similar_skills(self, skill: Skill) -> List[Skill]:
        """Find existing skills that are similar (Async)."""
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
        
        async with self.get_db() as conn:
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                
                similar = []
                for row in rows:
                    existing = self._row_to_skill(row)
                    # Check title similarity (simple)
                    if skill.title.lower() in existing.title.lower() or \
                       existing.title.lower() in skill.title.lower():
                        similar.append(existing)
                
                return similar
    
    async def _merge_skill_evidence(self, existing: Skill, new: Skill) -> None:
        """Merge evidence from new skill into existing (Async)."""
        # Merge evidence
        existing.evidence.update(new.evidence)
        
        # Increase confidence slightly
        existing.confidence = min(existing.confidence + 0.05, 1.0)
        existing.updated_at = datetime.now()
        
        await self._save_skill(existing)
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
            context_signature=json.loads(row["context_signature"]) if row["context_signature"] else {},
            confidence_history=json.loads(row["confidence_history"]) if row["confidence_history"] else [],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            created_by=row["created_by"],
        )
    
    async def verify_skill(self, skill_id: str, outcome: bool) -> None:
        """
        Update skill confidence based on verification outcome (Async).
        
        Args:
            skill_id: The skill to verify
            outcome: True if skill was confirmed, False if it failed
        """
        skill = await self.get_skill(skill_id)
        if not skill:
            logger.warning(f"Skill not found: {skill_id}")
            return
        
        if outcome:
            skill.verified_count += 1
            old_confidence = skill.confidence
            skill.confidence = self._bayesian_update(old_confidence, True)
            if skill.confidence >= 0.7 and skill.verified_count >= 3:
                skill.status = SkillStatus.ACTIVE
        else:
            skill.failed_count += 1
            old_confidence = skill.confidence
            skill.confidence = self._bayesian_update(old_confidence, False)
            if skill.confidence < 0.2:
                skill.status = SkillStatus.DEPRECATED
        
        # Record confidence history for Layer 3 Evidence Anchoring
        skill.confidence_history.append({
            "timestamp": datetime.now().isoformat(),
            "old_confidence": round(old_confidence, 3),
            "new_confidence": round(skill.confidence, 3),
            "outcome": outcome
        })
        
        skill.updated_at = datetime.now()
        await self._save_skill(skill)
        
        logger.info(f"Skill {skill_id} verified: {outcome}, confidence: {skill.confidence:.3f}")

    def _bayesian_update(self, prior: float, outcome: bool) -> float:
        """
        Calculate posterior probability using Bayes' Theorem.
        P(S|E) = P(E|S) * P(S) / P(E)
        """
        # Parameters for BMS domain sensitivity/specificity
        s = 0.85  # True Positive Rate (Sensitivity)
        f = 0.15  # False Positive Rate (1-Specificity)
        
        # Ensure prior is not 0 or 1 to avoid division by zero/saturation
        prior = max(0.01, min(0.99, prior))
        
        if outcome:
            # Positive evidence: skill is confirmed
            posterior = (s * prior) / (s * prior + f * (1 - prior))
        else:
            # Negative evidence: skill is refuted
            posterior = ((1 - s) * prior) / ((1 - s) * prior + (1 - f) * (1 - prior))
            
        return round(float(posterior), 4)
    
    async def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a specific skill by ID (Async)."""
        async with self.get_db() as conn:
            async with conn.execute(
                "SELECT * FROM skills WHERE skill_id = ?",
                (skill_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return self._row_to_skill(row) if row else None

    async def log_decision(self, decision_id: str, context: Dict[str, Any], chosen_action: str, 
                           alternatives: List[str], confidence: float, reasoning: str, 
                           event_id: Optional[str] = None, trajectory: Optional[Dict[str, Any]] = None) -> None:
        """Records a Swarm trajectory decision in the database for later MetaCognition analysis."""
        import json
        from datetime import datetime
        
        query = """
            INSERT INTO decisions 
            (decision_id, building_id, timestamp, context, chosen_action, alternatives, confidence, reasoning, event_id, trajectory) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            decision_id,
            self.building_id,
            datetime.now().isoformat(),
            json.dumps(context) if context else None,
            chosen_action,
            json.dumps(alternatives) if alternatives else None,
            confidence,
            reasoning,
            event_id,
            json.dumps(trajectory) if trajectory else None
        )
        
        async with self.get_db() as conn:
            await conn.execute(query, params)
            await conn.commit()

    async def update_decision_outcome(self, decision_id: str, outcome: str, quality: str) -> bool:
        """Updates a logged decision with its actual real-world outcome and quality ('good', 'poor')."""
        query = "UPDATE decisions SET outcome = ?, outcome_quality = ? WHERE decision_id = ?"
        async with self.get_db() as conn:
            cursor = await conn.execute(query, (outcome, quality, decision_id))
            await conn.commit()
            return cursor.rowcount > 0

    async def get_recent_decisions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves raw decision trajectories for MetaCognitive reflection."""
        import json
        query = "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?"
        decisions = []
        async with self.get_db() as conn:
            async with conn.execute(query, (limit,)) as cursor:
                async for row in cursor:
                    d = dict(row)
                    # parse json columns
                    for col in ['context', 'alternatives', 'trajectory']:
                        if d.get(col):
                            try:
                                d[col] = json.loads(d[col])
                            except:
                                d[col] = None
                    decisions.append(d)
    async def query_skillbook(self,
                              building_id: str,
                              context: Dict[str, Any],
                              equipment_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Query skillbook wrapper matching the interface called by InstitutionalStoreAdapter.
        """
        await self.ensure_initialized()
        query_context = {
            "query": context.get("query", ""),
            "situation_query": context.get("query", ""),
            "equipment_id": equipment_id,
            "building_id": building_id,
        }
        skills = await self.get_relevant_skills(query_context)
        return {
            "skills": [skill.to_dict() for skill in skills]
        }

    async def get_relevant_skills(self, 
                           context: Dict[str, Any],
                           limit: int = 10) -> List[Skill]:
        """
        Get skills relevant to the current context (Async).
        
        Args:
            context: Current situation (equipment_id, zone_id, skill_type, etc.)
            limit: Maximum number of skills to return
            
        Returns:
            List of relevant skills sorted by confidence
        """
        # --- LAYER 0: Relationship Trace (Graph Spreading) ---
        related_equipment = set()
        eq_id = context.get("equipment_id")
        if eq_id:
            related_equipment.add(eq_id)
            # Find immediately connected nodes to spread activation
            upstream = self.graph.get_upstream(eq_id)
            downstream = self.graph.get_downstream(eq_id)
            related_equipment.update(upstream)
            related_equipment.update(downstream)
            
        # --- LAYER 1: Semantic Recall & SQL Filtering ---
        skills = []
        
        # 1.1: Semantic Match (if supported by context)
        semantic_ids = []
        _semantic_query = context.get("situation_query") or context.get("query")
        if self.matcher.is_available and _semantic_query:
            similar = self.matcher.find_similar(
                _semantic_query,
                top_k=limit,
                threshold=context.get("similarity_threshold", 0.3)
            )
            semantic_ids = [s[0] for s in similar]
            
        # 1.2: Database Query (SQL Filter)
        query = """
            SELECT * FROM skills 
            WHERE building_id = ?
            AND status IN ('active', 'unverified', 'historical')
        """
        params = [self.building_id]
        
        if semantic_ids:
            placeholders = ",".join(["?"] * len(semantic_ids))
            query += f" AND skill_id IN ({placeholders})"
            params.extend(semantic_ids)
        else:
            # Fallback to hard filters if no semantic query
            if related_equipment:
                placeholders = ",".join(["?"] * len(related_equipment))
                query += f" AND (equipment_id IN ({placeholders}) OR equipment_id IS NULL)"
                params.extend(list(related_equipment))
            
            if context.get("zone_id"):
                query += " AND (zone_id = ? OR zone_id IS NULL)"
                params.append(context["zone_id"])
        
        if context.get("skill_type"):
            query += " AND skill_type = ?"
            params.append(context["skill_type"])
        
        async with self.get_db() as conn:
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                skills = [self._row_to_skill(row) for row in rows]

        # --- LAYER 2: Temporal Shaping ---
        current_time = datetime.now()
        for skill in skills:
            # Confidence decay over time (e.g. 5% reduction per month of inactivity)
            if skill.updated_at:
                days_old = (current_time - skill.updated_at).days
                if days_old > 30:
                    decay = min(0.5, (days_old // 30) * 0.05)
                    skill.confidence = max(0.1, skill.confidence - decay)

        # --- LAYER 3.5: Contextual Validity Checks ---
        validated_skills = []
        for skill in skills:
            drift = self._calculate_context_drift(skill.context_signature, context)
            
            if drift > 0.5:
                # High drift: Downgrade confidence and label as historical reference
                skill.confidence *= (1 - drift)
                skill.status = SkillStatus.HISTORICAL
                skill.tags.append("context_drift_detected")
            
            validated_skills.append(skill)

        # --- LAYER 3: Reranking (Cross-Encoder) ---
        if self.reranker.is_available and context.get("situation_query") and validated_skills:
            logger.info(f"Reranking {len(validated_skills)} candidates for query: {context['situation_query']}")
            # Convert to dict for reranker
            candidates = [s.to_dict() for s in validated_skills]
            reranked_dicts = self.reranker.rerank(context["situation_query"], candidates, top_n=limit)
            
            # Reconstruct skills with updated scores
            reranked_skills = []
            for d in reranked_dicts:
                s = Skill.from_dict(d)
                # Override confidence with reranked score if significant
                s.confidence = (s.confidence + d.get("rerank_score", 0)) / 2
                reranked_skills.append(s)
            
            return reranked_skills

        # Default sort by adjusted confidence
        validated_skills.sort(key=lambda x: x.confidence, reverse=True)
        return validated_skills[:limit]

    def _calculate_context_drift(self, signature: Dict[str, Any], current: Dict[str, Any]) -> float:
        """
        Calculate drift between memory context and current context.
        0.0 = identical, 1.0 = completely different.
        """
        if not signature:
            return 0.0
            
        mismatches = 0
        comparisons = 0
        
        # Check temperature deviation
        if "outdoor_temp" in signature and "outdoor_temp" in current:
            comparisons += 1
            temp_diff = abs(signature["outdoor_temp"] - current["outdoor_temp"])
            if temp_diff > 10:  # 10 degree delta is significant
                mismatches += 1
        
        # Check occupancy type
        if "occupancy_ratio" in signature and "occupancy_ratio" in current:
            comparisons += 1
            occ_diff = abs(signature["occupancy_ratio"] - current["occupancy_ratio"])
            if occ_diff > 0.4:  # 40% change in occupancy
                mismatches += 1
                
        # Check phase regression (e.g. Phase 4 should be wary of Phase 1 logic)
        if "phase" in signature and "phase" in current:
            comparisons += 1
            if signature["phase"] != current["phase"]:
                mismatches += 0.5 # Subtler impact
                
        return mismatches / max(1, comparisons)
    
    async def get_equipment_quirks(self, equipment_id: str) -> List[Skill]:
        """Get all quirks for a specific equipment (Async)."""
        return await self.get_relevant_skills({
            "equipment_id": equipment_id,
            "skill_type": "equipment_quirk",
        })
    
    async def get_optimization_history(self) -> List[Skill]:
        """Get all optimization attempts and their outcomes (Async)."""
        async with self.get_db() as conn:
            async with conn.execute("""
                SELECT * FROM skills 
                WHERE building_id = ?
                AND skill_type = 'optimization'
                ORDER BY created_at DESC
            """, (self.building_id,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_skill(row) for row in rows]
    
    async def get_contractor_notes(self, contractor_id: str) -> List[Skill]:
        """Get all notes about a specific contractor (Async)."""
        return await self.get_relevant_skills({
            "contractor_id": contractor_id,
            "skill_type": "contractor_note",
        })
    
    async def get_contractor_verification_rate(self, contractor_id: str) -> Dict[str, Any]:
        """Get verification statistics for a contractor (Async)."""
        async with self.get_db() as conn:
            async with conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN json_extract(evidence, '$.verified') = 1 THEN 1 ELSE 0 END) as verified,
                    SUM(CASE WHEN json_extract(evidence, '$.verified') = 0 THEN 1 ELSE 0 END) as unverified
                FROM skills 
                WHERE building_id = ?
                AND contractor_id = ?
                AND skill_type = 'contractor_note'
            """, (self.building_id, contractor_id)) as cursor:
                
                row = await cursor.fetchone()
                total = row[0] or 0
                verified = row[1] or 0
                
                return {
                    "contractor_id": contractor_id,
                    "total_work_orders": total,
                    "verified": verified,
                    "unverified": total - verified,
                    "verification_rate": verified / total if total > 0 else 0,
                }
    
    async def get_failure_history(self, 
                           equipment_id: Optional[str] = None,
                           days: int = 365) -> List[Skill]:
        """Get failure history for the building or specific equipment (Async)."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
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
        
        async with self.get_db() as conn:
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_skill(row) for row in rows]

    async def consolidate_skills(self) -> Dict[str, Any]:
        """
        Identify and merge redundant high-confidence skills (Async).
        Typically runs during maintenance windows/simulation nights.
        """
        logger.info(f"Starting skill consolidation for {self.building_id}")
        
        async with self.get_db() as conn:
            async with conn.execute(
                "SELECT * FROM skills WHERE building_id = ? AND status != 'deprecated'",
                (self.building_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                all_skills = [self._row_to_skill(row) for row in rows]
            
        merged_count = 0
        original_count = len(all_skills)
        
        # Group by type and equipment
        grouped = defaultdict(list)
        for s in all_skills:
            key = (s.skill_type.value, s.equipment_id)
            grouped[key].append(s)
            
        for key, skills in grouped.items():
            if len(skills) < 2:
                continue
                
            # Perform pairwise comparison for merging
            for i in range(len(skills)):
                for j in range(i + 1, len(skills)):
                    s1 = skills[i]
                    s2 = skills[j]
                    
                    if s1.status in [SkillStatus.DEPRECATED, SkillStatus.SUPERSEDED] or \
                       s2.status in [SkillStatus.DEPRECATED, SkillStatus.SUPERSEDED]:
                        continue
                        
                    # Calculate similarity
                    similarity = 0.0
                    if self.matcher.is_available:
                        sim_matrix = self.matcher.get_skill_similarity_matrix()
                        similarity = sim_matrix.get(s1.skill_id, {}).get(s2.skill_id, 0.0)
                    
                    # Merge if similarity > 0.75 (calibrated for BMS engineering patterns)
                    if similarity > 0.75:
                        logger.info(f"Consolidating redundant skills: {s1.skill_id} and {s2.skill_id}")
                        # Keep s1 as the primary, merge s2 into it
                        s1.verified_count += s2.verified_count
                        s1.failed_count += s2.failed_count
                        s1.evidence.update(s2.evidence)
                        s1.description += f" [Merged with {s2.skill_id}]"
                        
                        # Bayesian combine confidence
                        s1.confidence = self._bayesian_update(s1.confidence, True) # Give a 'boost' for redundancy
                        s1.updated_at = datetime.now()
                        
                        # Mark s2 as superseded
                        s2.status = SkillStatus.SUPERSEDED
                        s2.description += f" [Superseded by {s1.skill_id}]"
                        
                        await self._save_skill(s1)
                        await self._save_skill(s2)
                        merged_count += 1
                        
        return {
            "building_id": self.building_id,
            "original_skills": original_count,
            "merged": merged_count,
            "remaining_active": original_count - merged_count
        }
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get summary of skillbook contents (Async)."""
        async with self.get_db() as conn:
            async with conn.execute("""
                SELECT 
                    skill_type,
                    COUNT(*) as count,
                    AVG(confidence) as avg_confidence
                FROM skills 
                WHERE building_id = ?
                AND status != 'deprecated'
                GROUP BY skill_type
            """, (self.building_id,)) as cursor:
                
                by_type = {}
                total = 0
                rows = await cursor.fetchall()
                for row in rows:
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

    async def log_tool_usage(self,
                       tool_name: str,
                       args: Dict[str, Any],
                       success: bool,
                       duration_ms: float,
                       error: Optional[str] = None,
                       relevant_skill_id: Optional[str] = None) -> str:
        """Log tool usage for observability and institutional memory (Async)."""
        usage_id = f"tool_{self.building_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        async with self.get_db() as conn:
            await conn.execute("""
                INSERT INTO tool_usage 
                (usage_id, building_id, timestamp, tool_name, args, 
                 success, error, duration_ms, relevant_skill_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                usage_id,
                self.building_id,
                datetime.now().isoformat(),
                tool_name,
                json.dumps(args),
                1 if success else 0,
                error,
                duration_ms,
                relevant_skill_id
            ))
            await conn.commit()
        return usage_id

    async def get_tool_metrics(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve success metrics for tools (Async)."""
        query = "SELECT tool_name, COUNT(*) as total, SUM(success) as successful, AVG(duration_ms) as avg_duration FROM tool_usage WHERE building_id = ?"
        params = [self.building_id]
        if tool_name:
            query += " AND tool_name = ?"
            params.append(tool_name)
        query += " GROUP BY tool_name"
        
        async with self.get_db() as conn:
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                metrics = {row["tool_name"]: {
                    "total": row["total"],
                    "success_rate": row["successful"] / row["total"] if row["total"] > 0 else 0,
                    "avg_duration_ms": round(row["avg_duration"], 2)
                } for row in rows}
                
                return metrics


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

async def query_skillbook(
    building_id: str = "default",
    context: Optional[Dict[str, Any]] = None,
    skill_type: Optional[str] = None,
    equipment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query the building skillbook for relevant knowledge (Async).
    
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
    await skillbook.ensure_initialized()
    
    query_context = context or {}
    if skill_type:
        query_context["skill_type"] = skill_type
    if equipment_id:
        query_context["equipment_id"] = equipment_id
    
    skills = await skillbook.get_relevant_skills(query_context)
    summary = await skillbook.get_summary()
    
    # Wrap in MemoryAnchor style dictionary for the LLM
    anchored_skills = []
    for s in skills:
        skill_dict = s.to_dict()
        # Add a "humility_note" if context drift was detected (Layer 3.5 validation)
        if "context_drift_detected" in s.tags:
            skill_dict["humility_note"] = (
                "This resembles a past pattern, but current conditions (temp/occupancy) "
                "differ significantly. Treat as historical reference with caution."
            )
        anchored_skills.append(skill_dict)
    
    return {
        "skills": anchored_skills,
        "summary": summary,
    }


async def add_to_skillbook(
    skill_type: str,
    title: str,
    description: str,
    building_id: str = "default",
    equipment_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    context_signature: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Add a new skill to the building skillbook (Async).
    
    This is the LLM tool handler.
    
    Args:
        skill_type: Type (equipment_quirk, pattern, optimization, failure, contractor_note)
        title: Short title
        description: Detailed description
        building_id: Building identifier
        equipment_id: Related equipment (optional)
        zone_id: Related zone (optional)
        evidence: Supporting data (optional)
        context_signature: Current situation (optional)
        
    Returns:
        The created skill
    """
    skillbook = get_skillbook(building_id)
    await skillbook.ensure_initialized()
    
    skill = await skillbook.add_skill(
        skill_type=skill_type,
        title=title,
        description=description,
        equipment_id=equipment_id,
        zone_id=zone_id,
        evidence=evidence,
        context_signature=context_signature,
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
