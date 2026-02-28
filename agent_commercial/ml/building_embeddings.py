"""
Semantic Skill Matcher
======================

Sentence embedding-based semantic matching for Building Skillbook.

Uses:
- Sentence Transformers for encoding skills
- Cosine similarity for matching
- Clustering for related skills

Custom for BMS:
- HVAC terminology aware
- Equipment-context boosting
- Pattern similarity

Usage:
    >>> matcher = SemanticSkillMatcher()
    >>> similar = matcher.find_similar("chiller won't start in hot weather", top_k=5)
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger("arvis.ml.embeddings")

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Run: pip install sentence-transformers")

try:
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    StandardScaler = None  # Define as None for fallback

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    logger.warning("rank_bm25 not installed. BM25 matching will be disabled.")


# =============================================================================
# BMS TERMINOLOGY MAPPINGS
# =============================================================================

# Common abbreviations and their expansions for better matching
BMS_TERMINOLOGY = {
    "ahu": "air handling unit",
    "vav": "variable air volume",
    "fcu": "fan coil unit",
    "chw": "chilled water",
    "hw": "hot water",
    "sat": "supply air temperature",
    "rat": "return air temperature",
    "dat": "discharge air temperature",
    "mat": "mixed air temperature",
    "oat": "outdoor air temperature",
    "dp": "differential pressure",
    "vfd": "variable frequency drive",
    "rul": "remaining useful life",
    "cop": "coefficient of performance",
    "eer": "energy efficiency ratio",
    "bms": "building management system",
    "hvac": "heating ventilation air conditioning",
    "iaq": "indoor air quality",
}


# =============================================================================
# SEMANTIC SKILL MATCHER
# =============================================================================

class SemanticSkillMatcher:
    """
    Semantic matching for Building Skillbook using sentence embeddings.
    
    Encodes skills as vectors and finds semantically similar skills
    even when exact keywords don't match.
    """
    
    # Model to use (small but effective)
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    
    def __init__(self, model_name: str = DEFAULT_MODEL):
        """
        Initialize semantic matcher.
        
        Args:
            model_name: Sentence transformer model to use
        """
        self.model_name = model_name
        self.model = None
        
        # Cached embeddings
        self.skill_embeddings: Dict[str, np.ndarray] = {}
        self.skill_texts: Dict[str, str] = {}
        
        # Load model if available
        if ST_AVAILABLE:
            try:
                self.model = SentenceTransformer(model_name)
                logger.info(f"Loaded embedding model: {model_name}")
            except Exception as e:
                logger.warning(f"Failed to load model: {e}")
        
        self.is_available = self.model is not None
        
        # BM25 Matcher
        self.bm25_matcher = BM25Matcher() if BM25_AVAILABLE else None
    
    def _expand_terminology(self, text: str) -> str:
        """Expand BMS abbreviations for better matching."""
        text_lower = text.lower()
        
        for abbrev, expansion in BMS_TERMINOLOGY.items():
            # Replace standalone abbreviations
            text_lower = text_lower.replace(f" {abbrev} ", f" {expansion} ")
            text_lower = text_lower.replace(f" {abbrev}.", f" {expansion}.")
            text_lower = text_lower.replace(f" {abbrev},", f" {expansion},")
            
            # Also at start/end
            if text_lower.startswith(f"{abbrev} "):
                text_lower = f"{expansion} " + text_lower[len(abbrev) + 1:]
            if text_lower.endswith(f" {abbrev}"):
                text_lower = text_lower[:-len(abbrev) - 1] + f" {expansion}"
        
        return text_lower
    
    def encode(self, text: str) -> np.ndarray:
        """
        Encode text to embedding vector.
        
        Args:
            text: Text to encode
            
        Returns:
            Embedding vector
        """
        if not self.is_available:
            # Fallback: simple bag-of-words
            return self._simple_encode(text)
        
        # Expand terminology
        expanded = self._expand_terminology(text)
        
        return self.model.encode(expanded, convert_to_numpy=True)
    
    def _simple_encode(self, text: str) -> np.ndarray:
        """Simple fallback encoding (TF-IDF style)."""
        # Very basic word frequency vector
        words = text.lower().split()
        word_freq = {}
        
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        # Create fixed-size vector
        vector = np.zeros(100)
        for i, word in enumerate(list(word_freq.keys())[:100]):
            vector[i] = word_freq[word]
        
        # Normalize
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        
        return vector
    
    def add_skill(self, skill_id: str, text: str) -> None:
        """
        Add a skill to the matcher.
        
        Args:
            skill_id: Unique skill identifier
            text: Combined title + description
        """
        embedding = self.encode(text)
        self.skill_embeddings[skill_id] = embedding
        self.skill_texts[skill_id] = text
        
        # Also add to BM25
        if self.bm25_matcher:
            self.bm25_matcher.add_skill(skill_id, text)
    
    def find_similar(self, 
                     query: str,
                     top_k: int = 5,
                     threshold: float = 0.3) -> List[Tuple[str, float]]:
        """
        Find semantically and keyword-similar skills using Hybrid Search (RRF).
        
        Args:
            query: Query text
            top_k: Number of results
            threshold: Minimum similarity score (for semantic part)
            
        Returns:
            List of (skill_id, hybrid_score) tuples
        """
        if not self.skill_embeddings:
            return []
            
        # 1. Semantic Search
        semantic_similarities = []
        query_embedding = self.encode(query)
        
        for skill_id, skill_embedding in self.skill_embeddings.items():
            if self.is_available and SKLEARN_AVAILABLE:
                sim = cosine_similarity(
                    query_embedding.reshape(1, -1),
                    skill_embedding.reshape(1, -1)
                )[0, 0]
            else:
                dot = np.dot(query_embedding, skill_embedding)
                norm = np.linalg.norm(query_embedding) * np.linalg.norm(skill_embedding)
                sim = dot / (norm + 1e-8)
            
            if sim >= threshold:
                semantic_similarities.append((skill_id, float(sim)))
        
        semantic_similarities.sort(key=lambda x: x[1], reverse=True)
        
        # 2. BM25 Search
        bm25_results = []
        if self.bm25_matcher:
            bm25_results = self.bm25_matcher.find_similar(query, top_k=top_k * 2)
            
        # 3. Reciprocal Rank Fusion (RRF)
        # RRF score = 1 / (k + rank)
        k = 60 # Standard constant for RRF
        rrf_scores = {}
        
        # Add semantic ranks
        for rank, (skill_id, _) in enumerate(semantic_similarities):
            rrf_scores[skill_id] = rrf_scores.get(skill_id, 0) + 1.0 / (k + rank + 1)
            
        # Add BM25 ranks
        for rank, (skill_id, _) in enumerate(bm25_results):
            rrf_scores[skill_id] = rrf_scores.get(skill_id, 0) + 1.0 / (k + rank + 1)
            
        # Sort by RRF score
        hybrid_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        return hybrid_results[:top_k]
    
    def cluster_skills(self, n_clusters: int = 5) -> Dict[int, List[str]]:
        """
        Cluster skills into groups.
        
        Useful for organizing related skills.
        """
        if not SKLEARN_AVAILABLE or len(self.skill_embeddings) < n_clusters:
            return {}
        
        # Stack embeddings
        skill_ids = list(self.skill_embeddings.keys())
        embeddings = np.stack([self.skill_embeddings[sid] for sid in skill_ids])
        
        # K-Means clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings)
        
        # Group by cluster
        clusters = {}
        for skill_id, label in zip(skill_ids, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(skill_id)
        
        return clusters
    
    def get_skill_similarity_matrix(self) -> Dict[str, Dict[str, float]]:
        """
        Get pairwise similarity matrix for all skills.
        
        Useful for finding related skills.
        """
        skill_ids = list(self.skill_embeddings.keys())
        matrix = {}
        
        for sid1 in skill_ids:
            matrix[sid1] = {}
            for sid2 in skill_ids:
                if sid1 == sid2:
                    matrix[sid1][sid2] = 1.0
                else:
                    e1 = self.skill_embeddings[sid1]
                    e2 = self.skill_embeddings[sid2]
                    
                    if SKLEARN_AVAILABLE:
                        sim = cosine_similarity(e1.reshape(1, -1), e2.reshape(1, -1))[0, 0]
                    else:
                        dot = np.dot(e1, e2)
                        norm = np.linalg.norm(e1) * np.linalg.norm(e2)
                        sim = dot / (norm + 1e-8)
                    
                    matrix[sid1][sid2] = float(sim)
        
        return matrix


# =============================================================================
# BM25 KEYWORD MATCHER
# =============================================================================

class BM25Matcher:
    """
    Keyword-based matching using BM25Okapi for exact terminology hits.
    
    This provides robustness for exact IDs and equipment tags that
    semantic embeddings might occasionally dilute.
    """
    
    def __init__(self):
        self.skill_texts: Dict[str, str] = {}
        self.skill_ids: List[str] = []
        self.corpus: List[List[str]] = []
        self.bm25 = None
        
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer for BM25."""
        return text.lower().replace(".", " ").replace(",", " ").replace("-", " ").split()
        
    def add_skill(self, skill_id: str, text: str) -> None:
        """Add skill to BM25 corpus."""
        self.skill_texts[skill_id] = text
        if skill_id not in self.skill_ids:
            self.skill_ids.append(skill_id)
        
        # Rebuild corpus for simplicity in this V1 (low entry count expected < 1000)
        self.corpus = [self._tokenize(self.skill_texts[sid]) for sid in self.skill_ids]
        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
            
    def find_similar(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Find keyword-similar skills."""
        if not self.bm25 or not self.corpus:
            return []
            
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        
        # Sort by score
        results = []
        for idx, score in enumerate(scores):
            if score > 0:
                results.append((self.skill_ids[idx], float(score)))
                
        results.sort(key=lambda x: x[1], reverse=True)
        
        # Normalize scores to 0-1 range (heuristic)
        if results:
            max_score = results[0][1]
            if max_score > 0:
                results = [(sid, score / max_score) for sid, score in results]
                
        return results[:top_k]


# =============================================================================
# BUILDING ARCHETYPE CLASSIFIER
# =============================================================================

class BuildingArchetypeClassifier:
    """
    K-Means clustering for building archetypes.
    
    Classifies buildings into types based on usage patterns
    for peer comparison in fleet intelligence.
    """
    
    # Archetype names
    ARCHETYPE_NAMES = {
        0: "office_standard",
        1: "office_high_density",
        2: "retail_mall",
        3: "hotel_hospitality",
        4: "mixed_use",
        5: "data_center",
    }
    
    def __init__(self, n_archetypes: int = 6):
        self.n_archetypes = n_archetypes
        self.kmeans = None
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        self.feature_names = [
            "eui",  # Energy Use Intensity
            "occupancy_density",  # People per m²
            "operating_hours",  # Hours per week
            "cooling_ratio",  # % of energy for cooling
            "weekend_usage",  # % of weekday usage
            "base_load_ratio",  # Night load / day load
        ]
        self.is_trained = False
    
    def train(self, building_data: List[Dict[str, float]]) -> Dict[str, Any]:
        """
        Train the archetype classifier.
        
        Args:
            building_data: List of building feature dictionaries
            
        Returns:
            Training metrics
        """
        if not SKLEARN_AVAILABLE or len(building_data) < self.n_archetypes:
            return {"status": "failed", "error": "insufficient_data_or_sklearn"}
        
        # Create feature matrix
        X = np.array([
            [b.get(f, 0) for f in self.feature_names]
            for b in building_data
        ])
        
        # Scale
        X_scaled = self.scaler.fit_transform(X)
        
        # Fit K-Means
        self.kmeans = KMeans(
            n_clusters=min(self.n_archetypes, len(building_data)),
            random_state=42,
            n_init=10,
        )
        self.kmeans.fit(X_scaled)
        
        self.is_trained = True
        
        return {
            "status": "trained",
            "n_buildings": len(building_data),
            "n_archetypes": self.n_archetypes,
        }
    
    def classify(self, building_features: Dict[str, float]) -> Dict[str, Any]:
        """
        Classify a building into an archetype.
        """
        if not self.is_trained:
            return {"archetype": "unknown", "confidence": 0}
        
        # Create feature vector
        X = np.array([[building_features.get(f, 0) for f in self.feature_names]])
        X_scaled = self.scaler.transform(X)
        
        # Predict
        cluster = self.kmeans.predict(X_scaled)[0]
        
        # Calculate distance to cluster center for confidence
        center = self.kmeans.cluster_centers_[cluster]
        distance = np.linalg.norm(X_scaled[0] - center)
        confidence = 1 / (1 + distance)
        
        archetype = self.ARCHETYPE_NAMES.get(cluster, f"archetype_{cluster}")
        
        return {
            "archetype": archetype,
            "cluster_id": int(cluster),
            "confidence": float(confidence),
        }
    
    def get_peer_buildings(self, 
                          building_features: Dict[str, float],
                          all_buildings: List[Tuple[str, Dict[str, float]]]) -> List[str]:
        """
        Find buildings in the same archetype (peers).
        
        Args:
            building_features: Target building features
            all_buildings: List of (building_id, features) tuples
            
        Returns:
            List of peer building IDs
        """
        if not self.is_trained:
            return []
        
        target_archetype = self.classify(building_features)["cluster_id"]
        
        peers = []
        for building_id, features in all_buildings:
            archetype = self.classify(features)["cluster_id"]
            if archetype == target_archetype:
                peers.append(building_id)
        
        return peers


if __name__ == "__main__":
    print("=" * 60)
    print("Semantic Skill Matcher Test")
    print("=" * 60)
    
    matcher = SemanticSkillMatcher()
    
    # Add some skills
    skills = [
        ("skill_1", "Chiller trips when outdoor temperature exceeds 35 degrees celsius"),
        ("skill_2", "AHU filter replacement reduces energy consumption by 5%"),
        ("skill_3", "VAV damper gets stuck in cold weather"),
        ("skill_4", "Boiler efficiency drops below 80% after 6 months"),
        ("skill_5", "Chiller won't start on hot summer days due to high head pressure"),
        ("skill_6", "Zone temperature complaints increase when setpoint raised above 24C"),
    ]
    
    for skill_id, text in skills:
        matcher.add_skill(skill_id, text)
    
    # Find similar to query
    query = "chiller doesn't start in hot weather"
    similar = matcher.find_similar(query, top_k=3)
    
    print(f"\nQuery: '{query}'")
    print(f"\nSimilar skills:")
    for skill_id, score in similar:
        print(f"  {skill_id}: {score:.2f} - {matcher.skill_texts[skill_id][:50]}...")
    
    # Test archetype classifier
    print("\n" + "=" * 60)
    print("Building Archetype Classifier Test")
    print("=" * 60)
    
    classifier = BuildingArchetypeClassifier()
    
    # Sample building data
    buildings = [
        {"eui": 150, "occupancy_density": 0.1, "operating_hours": 55, 
         "cooling_ratio": 0.6, "weekend_usage": 0.2, "base_load_ratio": 0.3},
        {"eui": 200, "occupancy_density": 0.2, "operating_hours": 60, 
         "cooling_ratio": 0.65, "weekend_usage": 0.3, "base_load_ratio": 0.25},
        {"eui": 100, "occupancy_density": 0.05, "operating_hours": 40, 
         "cooling_ratio": 0.5, "weekend_usage": 0.1, "base_load_ratio": 0.4},
    ]
    
    # Not enough data to train, but test the interface
    print(f"\nArchetype classification requires training data first.")
