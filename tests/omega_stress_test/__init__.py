"""
Ω∞ 90-Day Pilot Stress Test Suite
===================================

Comprehensive end-to-end pre-deployment validation for ARVIS commercial system.
Tests advisory-only deployment in Doha Office Building under heatwave context.

Usage:
    from tests.omega_stress_test import OmegaTestRunner
    
    runner = OmegaTestRunner()
    report = await runner.run_full_simulation()
"""

# from tests.omega_stress_test.omega_test_runner import OmegaTestRunner
from tests.omega_stress_test.operator_simulator import OperatorSimulator, OperatorPersona
from tests.omega_stress_test.validation_monitor import ValidationMonitor
from tests.omega_stress_test.qatar_heatwave_scenario import QatarHeatwaveScenario
from tests.omega_stress_test.test_cases import TestCaseRegistry
from tests.omega_stress_test.metrics import TrustMetrics, ValidationMetrics

__all__ = [
    # "OmegaTestRunner",
    "OperatorSimulator", 
    "OperatorPersona",
    "ValidationMonitor",
    "QatarHeatwaveScenario",
    "TestCaseRegistry",
    "TrustMetrics",
    "ValidationMetrics",
]

__version__ = "1.0.0"
