"""
Time-Scaled Omega Stress Test Runner
=====================================

Implements configurable time scaling (1x, 10x, 100x, 1000x) with real LLM integration.
Each simulated day executes actual cognitive processing through the unified LLM system.

Time Scale Modes:
- 1x: Real-time simulation (~24 hours per simulated day)
- 10x: 10x speedup (~2.4 hours per simulated day)
- 100x: 100x speedup (~14.4 minutes per simulated day)
- 1000x: 1000x speedup (~1.4 minutes per simulated day)
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.omega_stress_test.omega_test_runner import OmegaTestRunner
from tests.omega_stress_test.qatar_heatwave_scenario import QatarHeatwaveScenario
from tests.omega_stress_test.operator_simulator import OperatorSimulator
from tests.omega_stress_test.validation_monitor import ValidationMonitor
from tests.omega_stress_test.metrics import SimulationDay, PassFailStatus

logger = logging.getLogger("arvis.omega.time_scaled")

# Import unified LLM client
try:
    from agent_unified.llm import UnifiedLLM
    from agent_unified.prompts.system import ARVIS_SYSTEM_PROMPT
    UNIFIED_LLM_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Unified LLM not available: {e}")
    UNIFIED_LLM_AVAILABLE = False


class TimeScaledRunner(OmegaTestRunner):
    """
    Extended OmegaTestRunner with configurable time scaling and real LLM integration.
    """
    
    # Time scale constants (seconds of real time per simulated day)
    TIME_SCALES = {
        1: 86400,      # 1x: 24 hours real-time per simulated day
        10: 8640,      # 10x: 2.4 hours per simulated day
        100: 864,      # 100x: 14.4 minutes per simulated day
        1000: 86.4,    # 1000x: 1.44 minutes per simulated day
        10000: 8.64,   # 10000x: 8.64 seconds per simulated day (testing mode)
    }
    
    def __init__(
        self,
        time_scale: int = 1000,
        use_real_llm: bool = True,
        config: Optional['OmegaTestConfig'] = None,
        **kwargs
    ):
        """
        Initialize time-scaled runner.
        
        Args:
            time_scale: Time acceleration factor (1, 10, 100, 1000)
            use_real_llm: Whether to use real LLM calls (default: True)
            config: Optional OmegaTestConfig instance
            **kwargs: Additional arguments for OmegaTestConfig
        """
        # Import OmegaTestConfig
        from tests.omega_stress_test.omega_test_runner import OmegaTestConfig
        
        # Create or update config
        if config is None:
            config = OmegaTestConfig(
                time_scale=time_scale,
                use_real_llm=use_real_llm,
                **kwargs
            )
        else:
            config.time_scale = time_scale
            config.use_real_llm = use_real_llm
        
        super().__init__(config)
        
        self.time_scale = time_scale
        self.use_real_llm = use_real_llm and UNIFIED_LLM_AVAILABLE
        
        # Initialize unified LLM client
        self.llm_client = None
        if self.use_real_llm:
            try:
                self.llm_client = UnifiedLLM()
                logger.info("Unified LLM client initialized for real cognitive processing")
            except Exception as e:
                logger.error(f"Failed to initialize LLM client: {e}")
                self.use_real_llm = False
        
        # Track LLM call statistics
        self.llm_calls = 0
        self.llm_errors = 0
        self.total_llm_time = 0.0
        
        # Calculate timing
        self.seconds_per_day = self.TIME_SCALES.get(time_scale, 864)
        logger.info(f"Time scale: {time_scale}x ({self.seconds_per_day:.1f}s per simulated day)")
    
    # _build_cognitive_prompt is inherited from OmegaTestRunner
    # which includes the full JSON schema, equipment data, and directive prompting

    
    
    async def _run_day(self, day: int, phase: int):
        """Run a single simulation day with time scaling."""
        self.current_day = day
        
        daily_data = self.scenario.advance_day()
        
        sim_day = SimulationDay(
            day_number=day,
            phase=phase,
            date=datetime.fromisoformat(daily_data["date"]),
            outdoor_temp=daily_data["hourly_data"][15]["outdoor_temp"],
            humidity=daily_data["hourly_data"][15]["humidity"],
            occupancy_ratio=daily_data["hourly_data"][10]["occupancy"],
        )
        
        context = {
            "heatwave": self.scenario.climate.heatwave_active,
            "trust_level": self.operator.state.trust_level,
            "phase": phase,
        }
        
        advisories_today = 0
        for hour_data in daily_data["hourly_data"]:
            # Use parent's _simulate_arvis_cycle which handles LLM/component/simulated selection
            advisories = await self._simulate_arvis_cycle(day, hour_data)
            
            advisories_today += len(advisories)
            
            for advisory in advisories:
                response = self.operator.respond_to_advisory(
                    advisory,
                    context={
                        "hour": hour_data["hour"],
                        "heatwave": self.scenario.climate.heatwave_active,
                        "outdoor_temp": hour_data["outdoor_temp"],
                    }
                )
                
                self.monitor.record_operator_response(
                    day, advisory.get("id", "unknown"),
                    response.accepted, None
                )
        
        sim_day.advisory_count = advisories_today
        sim_day.trust_score = self.operator.state.trust_level
        sim_day.silent_briefing = advisories_today == 0
        
        self.monitor.record_day(sim_day)
        
        if day % 7 == 0 or day == 1:
            logger.info(
                f"Day {day}: temp={sim_day.outdoor_temp:.1f}C, "
                f"advisories={advisories_today}, "
                f"trust={sim_day.trust_score:.2f}, "
                f"llm_calls={self.llm_calls}"
            )
    
    def _generate_final_report(self) -> Dict[str, Any]:
        """Generate the final validation report with LLM statistics."""
        report = super()._generate_final_report()
        
        report["llm_statistics"] = {
            "total_calls": self.llm_calls,
            "errors": self.llm_errors,
            "total_time_seconds": self.total_llm_time,
            "avg_time_per_call": self.total_llm_time / max(1, self.llm_calls),
            "time_scale": self.time_scale,
            "real_llm_used": self.use_real_llm,
        }
        
        return report


async def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Time-Scaled Omega Stress Test Runner with Real LLM Integration"
    )
    parser.add_argument(
        "--time-scale",
        type=int,
        choices=[1, 10, 100, 1000, 10000],
        default=1000,
        help="Time scale factor (1=real-time, 1000=fast testing)"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable real LLM calls (use rule-based fallback)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="tests/omega_stress_test/results",
        help="Output directory for results"
    )
    parser.add_argument(
        "--building",
        type=str,
        default="DOHA-TOWER-001",
        help="Building identifier"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    seconds_per_day = TimeScaledRunner.TIME_SCALES.get(args.time_scale, 864)
    estimated_runtime = seconds_per_day * 90
    
    logger.info("=" * 60)
    logger.info("TIME-SCALED OMEGA STRESS TEST RUNNER")
    logger.info("=" * 60)
    logger.info(f"Time Scale: {args.time_scale}x")
    logger.info(f"Seconds per simulated day: {seconds_per_day:.1f}s")
    logger.info(f"Estimated total runtime: {estimated_runtime/3600:.1f} hours")
    logger.info(f"Real LLM: {'ENABLED' if not args.no_llm else 'DISABLED'}")
    logger.info("=" * 60)
    
    runner = TimeScaledRunner(
        time_scale=args.time_scale,
        use_real_llm=not args.no_llm,
        config=None,
        building_id=args.building,
        output_dir=args.output_dir
    )
    
    try:
        report = await runner.run_full_simulation()
        
        print("\n" + "=" * 60)
        print("SIMULATION COMPLETE")
        print("=" * 60)
        print(f"Overall Status: {report['overall_status']}")
        print(f"Total Advisories: {report['simulation_summary'].get('total_advisories', 'N/A')}")
        
        # Get final trust from trust_metrics or simulation_summary
        final_trust = report['simulation_summary'].get('final_trust')
        if final_trust is None and 'trust_metrics' in report:
            final_trust = report['trust_metrics'].get('final_trust', 1.0)
        if final_trust is not None:
            print(f"Final Trust: {final_trust:.2f}")
        
        print(f"Tests Passed: {report['simulation_summary'].get('tests_passed', 'N/A')}")
        
        if "llm_statistics" in report:
            stats = report["llm_statistics"]
            print(f"\nLLM Statistics:")
            print(f"  Total Calls: {stats['total_calls']}")
            print(f"  Errors: {stats['errors']}")
            print(f"  Avg Time/Call: {stats['avg_time_per_call']:.2f}s")
        
        print("=" * 60)
        
    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
        runner.monitor.save_report()


if __name__ == "__main__":
    asyncio.run(main())
