"""
Building Physics Simulator — quasi-steady-state thermodynamic verification engine.

Patent Application 2, Claims 1-9.
"""
from agent_commercial.verifiers.simulator.engine import (
    BuildingPhysicsSimulator,
    ParsedAdvisory,
    PhysicalViolation,
    SimulationResult,
    ViolationLedger,
)

__all__ = [
    "BuildingPhysicsSimulator",
    "ParsedAdvisory",
    "PhysicalViolation",
    "SimulationResult",
    "ViolationLedger",
]
