"""
Scenario Retriever
==================

Embedding-based retrieval of similar historical scenarios.
Uses ChromaDB for vector similarity search.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("arvis.advisory.agentic.retriever")

# Lazy imports
chromadb = None
SentenceTransformer = None

# Module-level model cache keyed by model name — prevents repeated 90MB loads.
_SCENARIO_MODEL_CACHE: dict = {}


def _ensure_chromadb():
    """Lazy import ChromaDB"""
    global chromadb
    if chromadb is None:
        try:
            import chromadb as chroma_module
            chromadb = chroma_module
            return True
        except ImportError:
            logger.warning("ChromaDB not installed")
            return False
    return True


def _ensure_sentence_transformers():
    """Lazy import sentence transformers"""
    global SentenceTransformer
    if SentenceTransformer is None:
        try:
            from sentence_transformers import (
                SentenceTransformer as ST
            )
            SentenceTransformer = ST
            return True
        except ImportError:
            logger.warning("sentence-transformers not installed")
            return False
    return True


def _get_scenario_model(model_name: str):
    import sys
    if not hasattr(sys, "_arvis_st_model_cache"):
        sys._arvis_st_model_cache = {}
    if model_name not in sys._arvis_st_model_cache and _ensure_sentence_transformers():
        sys._arvis_st_model_cache[model_name] = SentenceTransformer(model_name)
    return sys._arvis_st_model_cache.get(model_name)


class HistoricalScenario:
    """A historical scenario for RAG context"""
    
    def __init__(
        self,
        scenario_id: str,
        context_summary: str,
        issue_type: str,
        operator_action: str,
        outcome_quality: str,
        time_to_resolution_min: int = 0,
        cost_qar: float = 0.0,
        similarity_score: float = 0.0,
        metadata: Optional[Dict] = None
    ):
        self.scenario_id = scenario_id
        self.context_summary = context_summary
        self.issue_type = issue_type
        self.operator_action = operator_action
        self.outcome_quality = outcome_quality
        self.time_to_resolution_min = time_to_resolution_min
        self.cost_qar = cost_qar
        self.similarity_score = similarity_score
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "context": self.context_summary,
            "issue": self.issue_type,
            "action_taken": self.operator_action,
            "outcome": self.outcome_quality,
            "resolution_time_min": self.time_to_resolution_min,
            "cost_qar": self.cost_qar,
            "similarity": self.similarity_score,
        }


class ScenarioRetriever:
    """
    Retrieve similar historical scenarios using embeddings.
    
    Uses ChromaDB + sentence-transformers for semantic search.
    Falls back to keyword matching if dependencies unavailable.
    """
    
    COLLECTION_NAME = "qatar_scenarios"
    
    def __init__(
        self,
        persist_directory: Optional[str] = None,
        embedding_model: str = "all-MiniLM-L6-v2",
        equipment_graph = None  # EquipmentGraph for graph pre-filtering
    ):
        """
        Initialize scenario retriever.
        
        Args:
            persist_directory: Directory to persist ChromaDB
            embedding_model: Sentence transformer model name
            equipment_graph: EquipmentGraph instance for graph pre-filtering (3.1 enhancement)
        """
        self.persist_directory = persist_directory
        self.embedding_model_name = embedding_model
        self.equipment_graph = equipment_graph
        
        self.client = None
        self.collection = None
        self.embedder = None
        self.use_chromadb = False
        
        self._initialize()
        
        logger.info(
            "ScenarioRetriever initialized (chromadb=%s, graph=%s)", 
            self.use_chromadb,
            equipment_graph is not None
        )
    
    def _initialize(self):
        """Initialize ChromaDB and embedder"""
        # Try to initialize ChromaDB
        if _ensure_chromadb():
            try:
                if self.persist_directory:
                    self.client = chromadb.PersistentClient(
                        path=self.persist_directory
                    )
                else:
                    self.client = chromadb.Client()
                
                self.collection = self.client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"}
                )
                self.use_chromadb = True
            except Exception as e:
                logger.warning("ChromaDB init failed: %s", e)
        
        # Try to initialize embedder
        if _ensure_sentence_transformers():
            try:
                self.embedder = _get_scenario_model(self.embedding_model_name)
            except Exception as e:
                logger.warning("Sentence transformer init failed: %s", e)
    
    async def retrieve_similar(
        self,
        context: Dict[str, Any],
        issue_type: Optional[str] = None,
        k: int = 10
    ) -> List[HistoricalScenario]:
        """
        Retrieve similar historical scenarios.
        
        Args:
            context: Current operational context
            issue_type: Optional filter by issue type
            k: Number of scenarios to retrieve
            
        Returns:
            List of similar scenarios sorted by similarity
        """
        # Build query text from context
        query_text = self._build_query_text(context, issue_type)
        _eq_ctx = context.get("equipment_id") or context.get("equipment") or ""

        if self.use_chromadb and self.embedder:
            return await self._retrieve_with_embeddings(query_text, issue_type, k, equipment_id=_eq_ctx)
        else:
            return self._retrieve_fallback(context, issue_type, k)

    @staticmethod
    def _equip_type(eq: str) -> str:
        """Equipment-type prefix for scoping (AHU-07→AHU, Chiller-01→CH)."""
        import re as _re
        if not eq:
            return ""
        _m = _re.match(r'\s*([A-Za-z]+)', str(eq))
        _t = (_m.group(1).upper() if _m else "")
        return "CH" if _t.startswith("CH") else _t
    
    async def retrieve_with_graph_filter(
        self,
        context: Dict[str, Any],
        equipment_id: str,
        issue_type: Optional[str] = None,
        k: int = 10,
        graph_depth: int = 2
    ) -> List[HistoricalScenario]:
        """
        Graph-filtered retrieval (3.1 enhancement).
        
        Flow:
        1. Get equipment neighborhood from graph
        2. Restrict embedding search to scenarios involving this subgraph
        3. Return topologically valid scenarios only
        
        Args:
            context: Current operational context
            equipment_id: Equipment to filter by
            issue_type: Optional filter by issue type
            k: Number of scenarios to retrieve
            graph_depth: Neighborhood depth for graph filter
            
        Returns:
            List of similar scenarios restricted to equipment neighborhood
        """
        # If no graph, fall back to standard retrieval
        if not self.equipment_graph:
            return await self.retrieve_similar(context, issue_type, k)
        
        # Get equipment neighborhood
        neighborhood = self.equipment_graph.get_neighborhood(equipment_id, depth=graph_depth)
        logger.debug(f"Graph pre-filter: {equipment_id} neighborhood = {neighborhood}")
        
        # Build query text with equipment context
        context_with_equipment = {**context, "equipment_id": equipment_id}
        query_text = self._build_query_text(context_with_equipment, issue_type)
        
        if not self.use_chromadb or not self.embedder:
            return self._retrieve_fallback(context_with_equipment, issue_type, k)
        
        # Generate embedding
        query_embedding = self.embedder.encode(query_text).tolist()
        
        # Build where filter for graph neighborhood
        # ChromaDB supports $in operator for filtering
        where_filter = {}
        if issue_type:
            where_filter["issue_type"] = issue_type
        
        # Query ChromaDB with larger k, then filter by neighborhood
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k * 3,  # Fetch more to filter
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"]
            )
        except Exception as e:
            logger.error("ChromaDB query failed: %s", e)
            return []
        
        # Convert to HistoricalScenario objects and filter by neighborhood
        scenarios = []
        
        if results and results.get("ids") and results["ids"][0]:
            for i, scenario_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                
                # Graph filter: check if scenario equipment is in neighborhood
                scenario_equipment = metadata.get("equipment_id")
                if scenario_equipment and scenario_equipment not in neighborhood:
                    continue  # Skip - not in topological neighborhood
                
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                similarity = 1 - distance
                
                scenarios.append(HistoricalScenario(
                    scenario_id=scenario_id,
                    context_summary=results["documents"][0][i] if results.get("documents") else "",
                    issue_type=metadata.get("issue_type", "unknown"),
                    operator_action=metadata.get("operator_action", "unknown"),
                    outcome_quality=metadata.get("outcome_quality", "unknown"),
                    time_to_resolution_min=metadata.get("resolution_time_min", 0),
                    cost_qar=metadata.get("cost_qar", 0),
                    similarity_score=similarity,
                    metadata=metadata,
                ))
                
                if len(scenarios) >= k:
                    break
        
        logger.debug(f"Graph pre-filter: returned {len(scenarios)} scenarios (filtered from {len(results.get('ids', [[]])[0])})") 
        return scenarios
    
    async def _retrieve_with_embeddings(
        self,
        query_text: str,
        issue_type: Optional[str],
        k: int,
        equipment_id: str = ""
    ) -> List[HistoricalScenario]:
        """Retrieve using vector similarity"""
        # Generate embedding
        query_embedding = self.embedder.encode(query_text).tolist()
        _target_type = self._equip_type(equipment_id)
        
        # Build where filter
        where_filter = None
        if issue_type:
            where_filter = {"issue_type": issue_type}
        
        # Query ChromaDB
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
        except Exception as e:
            logger.error("ChromaDB query failed: %s", e)
            return []
        
        # Convert to HistoricalScenario objects
        scenarios = []
        
        if results and results.get("ids") and results["ids"][0]:
            _dropped = 0
            for i, scenario_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                # Equipment-type scope: a scenario learned on a different
                # equipment TYPE (e.g. an AHU damper case) must not be retrieved
                # for a chiller. Scenarios with no equipment tag stay (generic).
                if _target_type:
                    _scn_eq = metadata.get("equipment_id") or metadata.get("equipment") or ""
                    _scn_type = self._equip_type(_scn_eq)
                    if _scn_type and _scn_type != _target_type:
                        _dropped += 1
                        continue
                distance = results["distances"][0][i] if results.get("distances") else 1.0

                # Convert distance to similarity (cosine distance)
                similarity = 1 - distance

                scenarios.append(HistoricalScenario(
                    scenario_id=scenario_id,
                    context_summary=results["documents"][0][i] if results.get("documents") else "",
                    issue_type=metadata.get("issue_type", "unknown"),
                    operator_action=metadata.get("operator_action", "unknown"),
                    outcome_quality=metadata.get("outcome_quality", "unknown"),
                    time_to_resolution_min=metadata.get("resolution_time_min", 0),
                    cost_qar=metadata.get("cost_qar", 0),
                    similarity_score=similarity,
                    metadata=metadata,
                ))
        
        return scenarios
    
    def _retrieve_fallback(
        self,
        context: Dict[str, Any],
        issue_type: Optional[str],
        k: int
    ) -> List[HistoricalScenario]:
        """Fallback retrieval without embeddings"""
        # Return empty if no data
        # In production, would use keyword matching on stored scenarios
        logger.debug("Using fallback retrieval (no embeddings)")
        return []
    
    def _build_query_text(
        self,
        context: Dict[str, Any],
        issue_type: Optional[str]
    ) -> str:
        """Build query text from context"""
        parts = []
        
        if issue_type:
            parts.append(f"issue: {issue_type}")
        
        if context.get("equipment_id"):
            parts.append(f"equipment: {context['equipment_id']}")
        
        if context.get("outdoor_temp_c"):
            parts.append(f"outdoor temp: {context['outdoor_temp_c']}°C")
        
        if context.get("cooling_load_pct"):
            parts.append(f"cooling load: {context['cooling_load_pct']}%")
        
        if context.get("alarm_description"):
            parts.append(f"alarm: {context['alarm_description']}")
        
        return " | ".join(parts) if parts else "building operation scenario"
    
    def add_scenario(
        self,
        scenario_id: str,
        context: Dict[str, Any],
        issue_type: str,
        operator_action: str,
        outcome_quality: str,
        resolution_time_min: int = 0,
        cost_qar: float = 0.0
    ):
        """
        Add a new scenario to the database.
        
        Args:
            scenario_id: Unique identifier
            context: Context at time of scenario
            issue_type: Type of issue
            operator_action: What the operator did
            outcome_quality: How it turned out
            resolution_time_min: Time to resolve
            cost_qar: Cost incurred
        """
        if not self.use_chromadb or not self.embedder:
            logger.warning("Cannot add scenario without ChromaDB/embeddings")
            return
        
        # Build document text
        document = self._build_query_text(context, issue_type)
        document += f" | action: {operator_action} | outcome: {outcome_quality}"
        
        # Generate embedding
        embedding = self.embedder.encode(document).tolist()
        
        # Metadata
        metadata = {
            "issue_type": issue_type,
            "operator_action": operator_action,
            "outcome_quality": outcome_quality,
            "resolution_time_min": resolution_time_min,
            "cost_qar": cost_qar,
            "timestamp": datetime.now().isoformat(),
        }
        
        # Add context fields
        for key in ["equipment_id", "outdoor_temp_c", "building_id"]:
            if key in context:
                metadata[key] = context[key]
        
        # Upsert to ChromaDB
        self.collection.upsert(
            ids=[scenario_id],
            documents=[document],
            embeddings=[embedding],
            metadatas=[metadata]
        )
        
        logger.debug("Added scenario %s to retriever", scenario_id)
    
    def get_scenario_count(self) -> int:
        """Get number of stored scenarios"""
        if self.collection:
            return self.collection.count()
        return 0
