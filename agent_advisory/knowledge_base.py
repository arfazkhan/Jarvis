"""
Technical Knowledge Base
========================

Handles RAG (Retrieval-Augmented Generation) for technical manuals and 
building specifications. Integrated with ChromaDB for semantic search.

Capabilities:
1. Indexing of technical documents (PDF, Text).
2. Semantic retrieval of equipment-specific constraints.
3. Metadata-filtered search (e.g., search ONLY within 'Chiller' manuals).
"""

import logging
import uuid
import os
import asyncio
import chromadb
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("arvis.advisory.knowledge")

class GraphRAGNavigator:
    """
    Orchestrates Graph-RAG traversal.
    Uses structural context from the building graph to improve technical retrieval.
    """
    
    def __init__(self, knowledge_base, context_graph):
        self.kb = knowledge_base
        self.graph = context_graph

    async def query_system_specs(self, 
                                query: str, 
                                target_id: str, 
                                depth: int = 2) -> List[Dict[str, Any]]:
        """
        Retrieves specs for the target equipment AND its related system components.
        Example: Querying a VAV will also pull specs for its parent AHU and Chiller.
        """
        # 1. Get the 'neighborhood' from the knowledge graph
        logger.info(f"Graph-RAG: Navigating topology around {target_id} (depth={depth})")
        context_data = self.graph.get_context(target_id, depth=depth)
        
        # Extract all related equipment IDs from the subgraph
        related_ids = set([target_id])
        if "nodes" in context_data:
            for node in context_data["nodes"]:
                related_ids.add(node["id"])
        
        logger.info(f"Graph-RAG: Identified related system components: {related_ids}")
        
        # 2. Parallel query for all related components in Vector DB
        tasks = []
        for eq_id in related_ids:
            tasks.append(self.kb.query_specs(query, equipment_id=eq_id))
            
        # 3. Combine and deduplicate results
        results = await asyncio.gather(*tasks)
        flattened_results = [item for sublist in results for item in sublist]
        
        # Sort by relevance (distance)
        flattened_results.sort(key=lambda x: x.get("distance", 1.0))
        
        return flattened_results

class TechnicalKnowledgeBase:
    """
    Manages building-specific documentation and hardware specifications.
    Allows the advisor to ground recommendations in real manufacturer data.
    """
    
    def __init__(self, persist_directory: str = "data/knowledge_base"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            name="building_specs",
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"Technical Knowledge Base initialized at {persist_directory}")

    def index_technical_snippet(self, 
                                content: str, 
                                source: str, 
                                equipment_id: Optional[str] = None, 
                                manual_type: str = "specs",
                                chunk_type: str = "section",
                                tags: List[str] = None,
                                extra_metadata: Dict[str, Any] = None):
        """
        Add a technical fact or snippet to the knowledge base.
        
        Args:
            content: The text content to index
            source: Source file path
            equipment_id: Equipment ID to tag (e.g., "30XW-CHILLER")
            manual_type: Type of manual (specs, installation, service, controls, faults)
            chunk_type: Type of chunk (section, table, procedure, parameters, safety)
            tags: Additional tags
            extra_metadata: Arbitrary metadata to attach (e.g. structured table JSON)
        """
        doc_id = str(uuid.uuid4())
        metadata = {
            "source": source,
            "timestamp": datetime.now().isoformat(),
            "equipment_id": equipment_id or "general",
            "manual_type": manual_type,
            "chunk_type": chunk_type,
            "tags": ",".join(tags or [])
        }
        
        if extra_metadata:
            metadata.update(extra_metadata)
        
        self.collection.add(
            documents=[content],
            metadatas=[metadata],
            ids=[doc_id]
        )
        logger.info(f"Indexed {chunk_type} snippet from {source} for {equipment_id or 'General'}")

    async def query_specs(self, 
                          query: str, 
                          equipment_id: Optional[str] = None,
                          manual_types: Optional[List[str]] = None,
                          chunk_types: Optional[List[str]] = None,
                          limit: int = 3) -> List[Dict[str, Any]]:
        """
        Search for relevant technical specifications.
        
        Args:
            query: The search query
            equipment_id: Filter by equipment ID
            manual_types: Filter by manual types (specs, service, faults, etc.)
            chunk_types: Filter by chunk types (table, procedure, parameters, etc.)
            limit: Maximum results to return
        """
        where_filters = []
        expanded_query = query
        
        # ═══ Universal Query Expansion ═══
        # Normalize fuzzy model references (e.g., "30XWP" → "30XW-P")
        from agent_advisory.equipment_patterns import expand_query
        expanded_query = expand_query(query)
        
        if equipment_id:
            where_filters.append({"equipment_id": equipment_id})
        
        if manual_types:
            where_filters.append({"manual_type": {"$in": manual_types}})
        
        if chunk_types:
            where_filters.append({"chunk_type": {"$in": chunk_types}})
        
        # Combine filters with $and if multiple
        where_filter = None
        if len(where_filters) == 1:
            where_filter = where_filters[0]
        elif len(where_filters) > 1:
            where_filter = {"$and": where_filters}
        
        results = self.collection.query(
            query_texts=[expanded_query],
            n_results=limit,
            where=where_filter
        )
        
        formatted_results = []
        if results["documents"]:
            for i in range(len(results["documents"][0])):
                formatted_results.append({
                    "id": results["ids"][0][i], # Surfacing Chroma ID
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else 0
                })
            
        return formatted_results

    def get_equipment_profile(self, equipment_id: str) -> Dict[str, Any]:
        """
        Synthesize a summary of known specs for a specific piece of equipment.
        """
        results = self.collection.get(
            where={"equipment_id": equipment_id}
        )
        
        if not results["documents"]:
            return {"status": "no_data"}
            
        return {
            "equipment_id": equipment_id,
            "facts_stored": len(results["documents"]),
            "latest_update": max([m["timestamp"] for m in results["metadatas"]]) if results["metadatas"] else "N/A",
            "full_context": "\n---\n".join(results["documents"][:5])
        }
