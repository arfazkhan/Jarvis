"""
Embedding-Based Intent Router for ARVIS Swarm
==============================================

Replaces keyword matching with semantic similarity routing.
Uses sentence-transformers (all-MiniLM-L6-v2) to embed node descriptions
and match incoming queries against them via cosine similarity.

Falls back to keyword matching if sentence-transformers is unavailable.
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.swarm.intent_router")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None
    EMBEDDINGS_AVAILABLE = False
    logger.warning("sentence-transformers not available — falling back to keyword routing")

# Module-level singleton — shared with embeddings_store so weights load once per process.
_ROUTER_MODEL_CACHE: dict = {}  # keyed by model_name

def _get_router_model(model_name: str):
    import sys
    if not hasattr(sys, "_arvis_st_model_cache"):
        sys._arvis_st_model_cache = {}
    if model_name not in sys._arvis_st_model_cache and SentenceTransformer is not None:
        logger.info(f"[IntentRouter] Loading SentenceTransformer({model_name}) globally...")
        sys._arvis_st_model_cache[model_name] = SentenceTransformer(model_name)
    return sys._arvis_st_model_cache.get(model_name)


class EmbeddingIntentRouter:
    """
    Semantic intent router for the ARVIS Swarm Queen.

    Each swarm node is registered with a description of its purpose and tools.
    Incoming queries are embedded and matched against node embeddings via cosine
    similarity, returning the top-k most relevant nodes above a threshold.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._encoder = None
        self._node_embeddings: Dict[str, np.ndarray] = {}
        self._node_texts: Dict[str, str] = {}
        self._keyword_fallback: Dict[str, List[str]] = {}

    def _ensure_encoder(self):
        if self._encoder is None and EMBEDDINGS_AVAILABLE:
            self._encoder = _get_router_model(self._model_name)
            logger.info(f"[IntentRouter] Using embedding model: {self._model_name} (singleton)")

    def register_node(self, node_name: str, description: str, tool_names: List[str], keywords: Optional[List[str]] = None):
        """Register a swarm node for semantic routing."""
        text = f"{description}. Capable tools: {', '.join(tool_names[:15])}"
        self._node_texts[node_name] = text

        if keywords:
            self._keyword_fallback[node_name] = [k.lower() for k in keywords]

        self._ensure_encoder()
        if self._encoder:
            embedding = self._encoder.encode(text, normalize_embeddings=True)
            self._node_embeddings[node_name] = embedding

    def route(self, query: str, top_k: int = 3, threshold: float = 0.35) -> List[Tuple[str, float]]:
        """
        Route a query to the most relevant swarm nodes.

        Returns list of (node_name, similarity_score) tuples, sorted by relevance.
        """
        if self._encoder and self._node_embeddings:
            return self._route_semantic(query, top_k, threshold)
        return self._route_keywords(query, top_k)

    def _route_semantic(self, query: str, top_k: int, threshold: float) -> List[Tuple[str, float]]:
        query_embedding = self._encoder.encode(query, normalize_embeddings=True)

        scores = []
        for node_name, node_emb in self._node_embeddings.items():
            similarity = float(np.dot(query_embedding, node_emb))
            if similarity >= threshold:
                scores.append((node_name, similarity))

        scores.sort(key=lambda x: x[1], reverse=True)
        selected = scores[:top_k]

        if selected:
            logger.info(
                f"[IntentRouter] Semantic routing: {[(n, f'{s:.3f}') for n, s in selected]}"
            )
        else:
            logger.info("[IntentRouter] No nodes above threshold — using fallback")
            return self._route_keywords(query, top_k)

        return selected

    def _route_keywords(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """Keyword-based fallback when embeddings aren't available."""
        query_lower = query.lower()
        scores = []

        for node_name, keywords in self._keyword_fallback.items():
            match_count = sum(1 for kw in keywords if kw in query_lower)
            if match_count > 0:
                score = min(0.9, 0.4 + match_count * 0.15)
                scores.append((node_name, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# Pre-defined node descriptions and keywords for the commercial BMS swarm
NODE_REGISTRY = {
    "Energy_Agent": {
        "description": "Optimizes energy consumption, detects waste patterns, forecasts demand, calculates costs in QAR, tracks GSAS certification",
        "keywords": ["energy", "cost", "kwh", "consumption", "burn rate", "waste", "ghost", "occupancy", "gsas", "gord", "certification", "green", "benchmark", "power", "electricity", "bills", "tariff"],
    },
    "Alarm_Agent": {
        "description": "Triages BMS alarms, performs root cause analysis, correlates cascading failures, identifies nuisance alarms",
        "keywords": ["alarm", "fault", "broken", "alert", "cascade", "root cause", "critical", "emergency", "trip", "failure", "error", "warning"],
    },
    "Comfort_Agent": {
        "description": "Monitors thermal comfort, zone temperatures, humidity, CO2 levels, occupant satisfaction, and setpoint optimization",
        "keywords": ["hot", "cold", "comfort", "temperature", "humidity", "co2", "zone", "setpoint", "occupant", "thermal", "warm", "cool", "stuffy", "air quality"],
    },
    "Maintenance_Agent": {
        "description": "Predicts equipment failures, tracks remaining useful life, schedules preventive maintenance, monitors vibration and runtime",
        "keywords": ["maintenance", "life", "rul", "predict", "health", "work order", "pm", "lifecycle", "runtime", "hours", "degradation", "vibration", "repair", "replace", "overdue"],
    },
    "Sensor_Fusion_Agent": {
        "description": "Detects sensor drift and calibration issues, validates data quality, creates virtual sensors from correlated readings",
        "keywords": ["sensor", "drift", "calibration", "data quality", "reading", "stale", "virtual sensor", "accuracy", "measurement", "unreliable"],
    },
    "Strategic_Agent": {
        "description": "Performs root cause analysis, identifies correlations and trends, runs what-if simulations, builds fleet-wide intelligence",
        "keywords": ["why", "correlat", "cause", "what if", "simulate", "trust", "fleet", "goal", "compare", "trend", "pattern", "strategic", "long term", "analysis"],
    },
    "Planning_Agent": {
        "description": "Creates step-by-step operational plans, sequences maintenance tasks, schedules rollback procedures",
        "keywords": ["plan", "steps", "sequence", "how to", "schedule", "rollback", "procedure", "workflow", "order", "arrange"],
    },
    "Memory_Agent": {
        "description": "Recalls building history, past incidents, operator preferences, learned quirks, institutional knowledge from skillbook",
        "keywords": ["remember", "history", "before", "last time", "skillbook", "quirk", "learned", "knowledge", "experience", "past", "previously"],
    },
    "Briefing_Agent": {
        "description": "Generates morning briefings, shift handoffs, daily summaries, and proactive recommendations for facility managers",
        "keywords": ["briefing", "morning", "summary", "handoff", "shift", "today", "overview", "what should", "report", "daily"],
    },
    "Safety_Agent": {
        "description": "Enforces safety boundaries, prevents dangerous operations, monitors life-safety systems, checks ASHRAE compliance",
        "keywords": ["safety", "danger", "emergency", "life safety", "smoke", "fire", "evacuate", "limit", "override", "dangerous"],
    },
}


def build_intent_router() -> EmbeddingIntentRouter:
    """Factory function to create a pre-configured intent router for the commercial swarm."""
    router = EmbeddingIntentRouter()

    for node_name, config in NODE_REGISTRY.items():
        router.register_node(
            node_name=node_name,
            description=config["description"],
            tool_names=config.get("tools", []),
            keywords=config.get("keywords", []),
        )

    logger.info(f"Intent router built with {len(NODE_REGISTRY)} nodes, embeddings={'ON' if EMBEDDINGS_AVAILABLE else 'OFF'}")
    return router
