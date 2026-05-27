"""ARVIS Discovery Agent — autonomous BACnet point onboarding.

Phase 1: rule-based classification (bootstrap).
Phase 2: ML-driven classification, scaffolding in place, retrains nightly
once operator feedback labels accumulate.
"""

from arvis_core.discovery.service import (
    init_discovery,
    get_discovery_service,
    DiscoveryService,
    DiscoveryDecision,
)
from arvis_core.discovery.classifier import (
    HybridClassifier,
    PointCriticality,
    ClassificationResult,
    maybe_retrain_ml_model,
)
from arvis_core.discovery.registry import (
    ARVISPollRegistry,
    RegisteredPoint,
    PointState,
)
from arvis_core.discovery.audit import DiscoveryAuditLog
from arvis_core.discovery.security import (
    RateLimiter,
    RateLimitConfig,
    CapabilityToken,
    DISCOVERY_AGENT_CAPABILITIES,
    sign_action,
    verify_signature,
    is_critical_equipment,
    is_allowed_object_type,
)

# Convenience alias matching spec
try:
    from arvis_core.swarm.agents.discovery import DiscoveryAgent  # type: ignore
except Exception:  # pragma: no cover - optional swarm wiring
    DiscoveryAgent = None  # type: ignore

__all__ = [
    "init_discovery",
    "get_discovery_service",
    "DiscoveryService",
    "DiscoveryDecision",
    "DiscoveryAgent",
    "HybridClassifier",
    "PointCriticality",
    "ClassificationResult",
    "maybe_retrain_ml_model",
    "ARVISPollRegistry",
    "RegisteredPoint",
    "PointState",
    "DiscoveryAuditLog",
    "RateLimiter",
    "RateLimitConfig",
    "CapabilityToken",
    "DISCOVERY_AGENT_CAPABILITIES",
    "sign_action",
    "verify_signature",
    "is_critical_equipment",
    "is_allowed_object_type",
]
