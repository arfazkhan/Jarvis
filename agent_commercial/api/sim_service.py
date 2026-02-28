"""
Omega Simulation Backend Service
================================
Run the 90-day Omega Infinity stress test as a managed background 
task inside the FastAPI server, allowing observation via frontend.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel

from tests.omega_stress_test.omega_test_runner import OmegaTestRunner, OmegaTestConfig
from agent_commercial.api.sse_broadcaster import SSEBroadcaster

logger = logging.getLogger("arvis.sim_service")

class SimStatus(BaseModel):
    is_running: bool
    current_day: int
    total_days: int
    building_id: str
    status_message: str

class SimServiceMaster:
    """Manages the lifecycle of a background Omega simulation."""
    
    _instance = None
    
    def __new__(cls, broadcaster: SSEBroadcaster = None):
        if cls._instance is None:
            cls._instance = super(SimServiceMaster, cls).__new__(cls)
            cls._instance.broadcaster = broadcaster or SSEBroadcaster()
            cls._instance.runner: Optional[OmegaTestRunner] = None
            cls._instance.task: Optional[asyncio.Task] = None
            cls._instance.is_running = False
            cls._instance.config = None
            cls._instance.status_msg = "Idle"
        return cls._instance
        
    async def start_simulation(self, 
                               days: int = 90, 
                               time_scale: int = 5000, 
                               building_id: str = 'DOHA-TOWER-001',
                               persona: str = 'skeptical_steve'):
        """Starts the 90 day stress test as a background task."""
        if self.is_running:
            return {"status": "error", "message": "Simulation already running."}
            
        logger.info(f"Starting Omega Simulation Service: {days} days at {time_scale}x scale.")
        
        # Setup config
        self.config = OmegaTestConfig(
            simulation_days=days,
            time_scale=time_scale,
            use_real_llm=True, # Ensure real LLM usage
            output_dir="tests/omega_stress_test/results/api_run"
        )
        self.config.building_id = building_id
        # Instantiate runner
        try:
            self.runner = OmegaTestRunner(self.config)
        except Exception as e:
            logger.error(f"Failed to init OmegaTestRunner: {e}")
            return {"status": "error", "message": f"Failed to init runner: {e}"}
            
        self.is_running = True
        self.status_msg = "Running"
        
        # Hook into SSE logger via custom wrapper class if needed in future
        # For now, we rely on the standard print statements or logger. 
        # A more advanced version would redirect python stdout/logger to SSEBroadcaster
        
        # Start Task
        self.task = asyncio.create_task(self._run_task())
        return {"status": "success", "message": "Simulation started in background."}
        
    async def _run_task(self):
        try:
            # Overwrite simulate for broadcasting
            original_simulate = self.runner._simulate_arvis_cycle
            async def verbose_simulate(day, hour_data):
                hour = hour_data.get("hour", 0)
                if hour == 0:
                    self.status_msg = f"Starting Day {day}"
                    logger.info(self.status_msg)
                    await self.broadcaster.broadcast(f"[SIM] Starting Day {day}", "system")
                return await original_simulate(day, hour_data)
            
            self.runner._simulate_arvis_cycle = verbose_simulate

            await self.runner.run_full_simulation()
            
            self.status_msg = "Complete"
            await self.broadcaster.broadcast("[SIM] Ω∞ OMEGA INFINITY COMPLETE", "system")
            logger.info("Simulation task finished successfully.")
            
        except asyncio.CancelledError:
            self.status_msg = "Aborted"
            logger.warning("Simulation task was cancelled.")
            await self.broadcaster.broadcast("[SIM] Simulation aborted by user.", "system")
        except Exception as e:
            self.status_msg = f"Error: {str(e)}"
            logger.error(f"Simulation task failed: {e}")
            await self.broadcaster.broadcast(f"[SIM] FATAL ERROR: {e}", "system")
        finally:
            self.is_running = False
            self.runner = None

    async def stop_simulation(self):
        if not self.is_running or self.task is None:
            return {"status": "error", "message": "No running simulation to stop."}
            
        self.task.cancel()
        # Wait a moment for cancellation to process
        await asyncio.sleep(0.5) 
        return {"status": "success", "message": "Simulation aborted."}

    def get_status(self) -> SimStatus:
        curr_day = 0
        tot_days = 0
        bid = "none"
        if self.runner and self.config:
            curr_day = getattr(self.runner, 'current_day', 0)
            if curr_day == 0:
                # sometimes its stored on controller
                if hasattr(self.runner, 'sim_controller'):
                    curr_day = self.runner.sim_controller.pilot_day
            tot_days = self.config.simulation_days
            bid = self.config.building_id
            
        return SimStatus(
            is_running=self.is_running,
            current_day=curr_day,
            total_days=tot_days,
            building_id=bid,
            status_message=self.status_msg
        )
