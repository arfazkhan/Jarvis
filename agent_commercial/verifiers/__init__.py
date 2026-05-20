"""
Physics Verifiers for ARVIS
============================

Deterministic checks that validate diagnostic/causal claims against physics constraints.
Runs BEFORE any claim ships to operator. Failure → block.
"""

from agent_commercial.verifiers.physics import PhysicsVerifier, VerificationResult

__all__ = ["PhysicsVerifier", "VerificationResult"]
