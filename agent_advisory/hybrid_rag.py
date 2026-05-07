"""
Hybrid RAG Router
=================

Combines two retrieval paths:
- Vector search via TechnicalKnowledgeBase/Chroma for fuzzy semantic snippets.
- Tree search via a PageIndex-style document structure for section-level navigation.

Routing strategy:
1. Deterministic keyword matching (fast, cheap)
2. LLM fallback for ambiguous queries (when confidence < 0.6 or conflicting hints)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.advisory.hybrid_rag")


# ─── LLM Router Prompt ─────────────────────────────────────────────────────

LLM_ROUTER_PROMPT = """You are a retrieval strategy router for a building management system knowledge base.

Given a query about technical equipment manuals, decide which retrieval strategy is best:

**tree** - Use when:
- Query asks about document structure (section, chapter, page, where)
- Query needs procedural navigation (startup, shutdown, maintenance sequence)
- Query needs hierarchical context (overview, then drill-down)
- Example: "Where is the chiller startup procedure?", "Show me the maintenance section"

**vector** - Use when:
- Query asks for specific values, parameters, limits, setpoints
- Query mentions fault codes, alarms, error conditions
- Query needs exact technical data (temperature limits, pressure ratings)
- Example: "What is the CHW low temperature limit?", "What does alarm code E-23 mean?"

**hybrid** - Use when:
- Query needs both structure AND specific values
- Query asks about performance data (tables with ratings, capacities)
- Query is complex or ambiguous
- Example: "What are the capacity and COP ratings for this chiller?", "Show me the startup procedure and safety limits"

Reply ONLY with JSON:
```json
{
  "strategy": "tree" | "vector" | "hybrid",
  "reason": "brief explanation",
  "confidence": 0.0 to 1.0
}
```

Query: {query}

Respond now:"""


@dataclass
class TreeNodeRecord:
    node_id: str
    source: str
    doc_name: str
    title: str
    summary: str = ""
    hierarchy_path: str = ""
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    equipment_id: Optional[str] = None
    models_covered: List[str] = field(default_factory=list)
    text_preview: str = ""
    indexed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def searchable_text(self) -> str:
        return " ".join([
            self.doc_name,
            self.title,
            self.summary,
            self.hierarchy_path,
            " ".join(self.models_covered),
            self.text_preview,
        ]).lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "source": self.source,
            "doc_name": self.doc_name,
            "title": self.title,
            "summary": self.summary,
            "hierarchy_path": self.hierarchy_path,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "equipment_id": self.equipment_id,
            "models_covered": self.models_covered,
            "text_preview": self.text_preview,
            "indexed_at": self.indexed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TreeNodeRecord":
        return cls(**data)


class TreeKnowledgeBase:
    """
    Lightweight persistent tree index.

    This stores the structure ManualIngester already creates, making it queryable
    without adding PageIndex as a runtime dependency.
    """

    INDEX_FILE = "tree_index.json"

    def __init__(self, persist_directory: str = "data/tree_knowledge"):
        self.persist_path = Path(persist_directory)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.index_path = self.persist_path / self.INDEX_FILE
        self.nodes: List[TreeNodeRecord] = []
        self._load()

    def add_document_tree(
        self,
        source: str,
        doc_name: str,
        tree_structure: List[Dict[str, Any]],
        equipment_id: Optional[str] = None,
        replace_source: bool = True,
    ) -> int:
        if replace_source:
            self.nodes = [n for n in self.nodes if n.source != source]

        flat_nodes = self._flatten_tree(tree_structure)
        for i, node in enumerate(flat_nodes):
            title = node.get("title") or f"Section {i + 1}"
            models = node.get("models_covered") or []
            if not models and node.get("text"):
                models = self._extract_model_ids(node["text"])

            self.nodes.append(TreeNodeRecord(
                node_id=str(node.get("node_id") or f"{len(self.nodes) + 1:04d}"),
                source=source,
                doc_name=doc_name,
                title=title,
                summary=node.get("summary") or "",
                hierarchy_path=node.get("hierarchy_path") or title,
                start_index=node.get("start_index"),
                end_index=node.get("end_index"),
                equipment_id=equipment_id,
                models_covered=models,
                text_preview=(node.get("text") or "")[:1200],
            ))

        self._save()
        logger.info("Indexed %s tree nodes for %s", len(flat_nodes), doc_name)
        return len(flat_nodes)

    async def query(
        self,
        query: str,
        equipment_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        terms = self._query_terms(query)
        model_ids = self._extract_model_ids(query)
        scored = []

        for node in self.nodes:
            if equipment_id and node.equipment_id and node.equipment_id != equipment_id:
                continue

            text = node.searchable_text()
            score = 0.0
            for term in terms:
                if term in text:
                    score += 1.0
                if term in node.title.lower():
                    score += 1.2
                if term in node.summary.lower():
                    score += 0.7

            if model_ids and any(mid.lower() in text for mid in model_ids):
                score += 3.0

            if any(hint in text for hint in ("table", "performance", "capacity", "cop", "flow rate")):
                score += 0.4

            if score > 0:
                scored.append((score, node))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **node.to_dict(),
                "score": round(score, 3),
                "retrieval_path": "tree",
            }
            for score, node in scored[:limit]
        ]

    def stats(self) -> Dict[str, Any]:
        sources = {node.source for node in self.nodes}
        return {
            "nodes": len(self.nodes),
            "documents": len(sources),
            "persist_path": str(self.index_path),
        }

    def _load(self) -> None:
        if not self.index_path.exists():
            self.nodes = []
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            self.nodes = [TreeNodeRecord.from_dict(item) for item in data.get("nodes", [])]
        except Exception as e:
            logger.warning("Failed to load tree index %s: %s", self.index_path, e)
            self.nodes = []

    def _save(self) -> None:
        payload = {"nodes": [node.to_dict() for node in self.nodes]}
        self.index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _flatten_tree(self, nodes: List[Dict[str, Any]], parent_path: str = "") -> List[Dict[str, Any]]:
        flat = []
        for node in nodes:
            title = node.get("title", "Untitled")
            path = f"{parent_path} > {title}" if parent_path else title
            current = dict(node)
            current["hierarchy_path"] = node.get("hierarchy_path") or path
            flat.append(current)
            if node.get("nodes"):
                flat.extend(self._flatten_tree(node["nodes"], path))
        return flat

    def _query_terms(self, query: str) -> List[str]:
        stop = {"what", "where", "which", "show", "find", "tell", "about", "the", "and", "for", "with"}
        return [
            t for t in re.findall(r"[a-zA-Z0-9_.-]+", query.lower())
            if len(t) > 2 and t not in stop
        ]

    def _extract_model_ids(self, text: str) -> List[str]:
        return sorted(set(re.findall(r"\b(?:\d{4}[A-Z]?|[A-Z]{2,}\d{2,}[A-Z0-9-]*)\b", text or "")))


class HybridRAGRouter:
    """Routes a query to vector, tree, or both retrieval strategies.
    
    Uses a two-tier approach:
    1. Deterministic keyword matching (fast, cheap, no LLM call)
    2. LLM fallback for ambiguous queries (when confidence is low)
    """

    TREE_HINTS = {
        "section", "chapter", "where", "page", "pages", "manual", "procedure",
        "startup", "shutdown", "maintenance", "table of contents", "toc",
    }
    VECTOR_HINTS = {
        "setpoint", "limit", "alarm", "fault", "specific", "exact", "value",
        "temperature", "pressure", "code", "parameter",
    }
    HYBRID_HINTS = {
        "capacity", "cop", "eer", "flow", "flow rate", "performance",
        "rating", "table", "spec", "specification", "range",
    }

    def __init__(
        self,
        vector_kb: Optional[Any] = None,
        tree_kb: Optional[TreeKnowledgeBase] = None,
        llm: Optional[Any] = None,
        llm_confidence_threshold: float = 0.6,
    ):
        self.vector_kb = vector_kb
        self.tree_kb = tree_kb or TreeKnowledgeBase()
        self.llm = llm
        self.llm_confidence_threshold = llm_confidence_threshold

    def choose_strategy(self, query: str) -> Dict[str, Any]:
        """Deterministic router using keyword matching."""
        q = query.lower()
        matched_tree = sorted(h for h in self.TREE_HINTS if h in q)
        matched_vector = sorted(h for h in self.VECTOR_HINTS if h in q)
        matched_hybrid = sorted(h for h in self.HYBRID_HINTS if h in q)
        has_model_id = bool(re.search(r"\b(?:\d{4}[A-Z]?|[A-Z]{2,}\d{2,}[A-Z0-9-]*)\b", query))

        # Calculate confidence based on hint matches
        total_hints = len(matched_tree) + len(matched_vector) + len(matched_hybrid)
        confidence = min(1.0, total_hints / 3.0) if total_hints > 0 else 0.0

        if matched_hybrid:
            strategy = "hybrid"
        elif matched_tree and matched_vector:
            strategy = "hybrid"
        elif matched_tree:
            strategy = "tree"
        elif has_model_id or matched_vector:
            strategy = "vector"
        else:
            strategy = "hybrid"

        return {
            "strategy": strategy,
            "confidence": confidence,
            "reason": {
                "tree_hints": matched_tree,
                "vector_hints": matched_vector,
                "hybrid_hints": matched_hybrid,
                "has_model_id": has_model_id,
            },
        }

    async def choose_strategy_llm(self, query: str) -> Dict[str, Any]:
        """LLM-based router for ambiguous queries."""
        if not self.llm:
            logger.warning("LLM not available for routing, falling back to deterministic")
            return self.choose_strategy(query)

        try:
            from agent_unified.llm import UnifiedLLM
            llm = self.llm if hasattr(self.llm, 'ask') else UnifiedLLM()
            
            prompt = LLM_ROUTER_PROMPT.format(query=query)
            response = await llm.ask(prompt)
            
            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*"strategy"[^{}]*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "strategy": result.get("strategy", "hybrid"),
                    "confidence": result.get("confidence", 0.5),
                    "reason": result.get("reason", "LLM routing"),
                    "method": "llm",
                }
        except Exception as e:
            logger.warning("LLM routing failed: %s", e)

        # Fallback to deterministic
        return self.choose_strategy(query)

    async def retrieve(
        self,
        query: str,
        equipment_id: Optional[str] = None,
        limit: int = 5,
        strategy: str = "auto",
        use_llm_routing: bool = True,
    ) -> Dict[str, Any]:
        """Retrieve using tiered routing: deterministic first, LLM if ambiguous."""
        
        # Step 1: Try deterministic routing
        if strategy == "auto":
            decision = self.choose_strategy(query)
            
            # Step 2: Use LLM if confidence is low and LLM is available
            if (
                use_llm_routing 
                and decision["confidence"] < self.llm_confidence_threshold 
                and self.llm
            ):
                logger.info(
                    "Low confidence (%.2f) for query, using LLM routing",
                    decision["confidence"]
                )
                llm_decision = await self.choose_strategy_llm(query)
                if llm_decision.get("method") == "llm":
                    decision = llm_decision
        else:
            decision = {"strategy": strategy, "confidence": 1.0, "reason": {"forced": True}}

        selected = decision["strategy"]

        tree_results: List[Dict[str, Any]] = []
        vector_results: List[Dict[str, Any]] = []

        if selected in ("tree", "hybrid") and self.tree_kb:
            tree_results = await self.tree_kb.query(query, equipment_id=equipment_id, limit=limit)

        if selected in ("vector", "hybrid") and self.vector_kb:
            try:
                vector_results = await self.vector_kb.query_specs(query, equipment_id=equipment_id, limit=limit)
                for item in vector_results:
                    item["retrieval_path"] = "vector"
            except Exception as e:
                logger.warning("Vector retrieval failed, returning tree-only results: %s", e)

        # Auto-fallback if chosen strategy returns nothing
        if selected == "vector" and not vector_results and tree_results:
            selected = "tree"
        elif selected == "tree" and not tree_results and vector_results:
            selected = "vector"

        return {
            "query": query,
            "strategy": selected,
            "routing_method": decision.get("method", "deterministic"),
            "confidence": decision.get("confidence", 0.0),
            "decision": decision["reason"],
            "tree_results": tree_results,
            "vector_results": self._format_vector_results(vector_results),
            "combined": self._combine(tree_results, vector_results, limit),
        }

    def _format_vector_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted = []
        for item in results:
            meta = item.get("metadata", {})
            formatted.append({
                "content": item.get("content", ""),
                "metadata": meta,
                "distance": item.get("distance"),
                "retrieval_path": "vector",
                "source": meta.get("source"),
                "page_start": meta.get("page_start"),
                "page_end": meta.get("page_end"),
            })
        return formatted

    def _combine(
        self,
        tree_results: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        combined = []
        seen = set()

        for item in tree_results:
            key = ("tree", item.get("source"), item.get("node_id"))
            if key not in seen:
                seen.add(key)
                combined.append(item)

        for item in self._format_vector_results(vector_results):
            key = ("vector", item.get("source"), item.get("page_start"), item.get("content", "")[:80])
            if key not in seen:
                seen.add(key)
                combined.append(item)

        return combined[:limit]
