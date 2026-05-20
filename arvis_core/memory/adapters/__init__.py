"""
Memory Tier Adapters
====================
Thin async wrappers that translate live ARVIS data sources into MemoryHit[].
Each adapter implements: async query(...) -> list[MemoryHit]
                          async write(record) -> str
"""
from .episodic import EpisodicStoreAdapter
from .procedural import ProceduralStoreAdapter
from .semantic import SemanticStoreAdapter
from .institutional import InstitutionalStoreAdapter
from .identity import IdentityStoreAdapter
from .resolution import ResolutionStoreAdapter
from .t1_working import T1WorkingAdapter

__all__ = [
    "EpisodicStoreAdapter",
    "ProceduralStoreAdapter",
    "SemanticStoreAdapter",
    "InstitutionalStoreAdapter",
    "IdentityStoreAdapter",
    "ResolutionStoreAdapter",
    "T1WorkingAdapter",
]
