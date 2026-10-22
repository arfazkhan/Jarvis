"""Small, calibrated decisions the agent loop makes about itself (e.g. whether to
re-search memory after an empty result). See reflector.py."""

from arvis_core.decision.reflector import ReflectionDecision, decide_reflection

__all__ = ["ReflectionDecision", "decide_reflection"]
