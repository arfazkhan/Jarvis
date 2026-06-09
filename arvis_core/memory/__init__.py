"""
ARVIS Memory System - Enterprise Grade
Multi-context persistent memory for 24/7 home automation.

BMS 7-tier façade: MemoryOrchestrator.query/write/archive_investigation/
recall_for_investigation/get_conversation. All types in types.py.
"""

from .orchestrator import MemoryOrchestrator
from .consolidator import MemoryConsolidator
from .preference_store import PreferenceStore
from .observation_store import ObservationStore
from .belief_store import BuildingBeliefStore
from .conversation_buffer import ConversationBuffer
from .context_builder import ContextBuilder
from .types import (
    MemoryTier,
    MemoryHit,
    MemoryRecord,
    RecallBundle,
    ConversationContext,
    StoreHealth,
)

__all__ = [
    'MemoryOrchestrator',
    'MemoryConsolidator',
    'PreferenceStore',
    'ObservationStore',
    'BuildingBeliefStore',
    'ConversationBuffer',
    'ContextBuilder',
    # BMS 7-tier types
    'MemoryTier',
    'MemoryHit',
    'MemoryRecord',
    'RecallBundle',
    'ConversationContext',
    'StoreHealth',
]
