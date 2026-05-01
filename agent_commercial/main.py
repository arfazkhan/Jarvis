"""
ARVIS Ops Copilot - Main Entry Point
=====================================

Commercial Building Management System advisory AI.

This module provides:
- OpsCopilot class: Main orchestrator for BMS operations
- Integration with ARVIS core (LLMAgent, EventBus, etc.)
- CLI for development and testing

Usage:
    # As a module
    from agent_commercial.main import OpsCopilot
    copilot = OpsCopilot()
    await copilot.start()
    
    # CLI
    python -m agent_commercial.main --mode simulator
"""

import asyncio
import argparse
import logging
import signal
import sys
from typing import Optional, Dict, Any

from agent_commercial.bms_data_model import (
    Equipment,
    EquipmentType,
    EquipmentStatus,
    BMSDataPoint,
    PointType,
)
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.energy_analyzer import EnergyAnalyzer
from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine
from agent_commercial.bacnet_adapter import BACnetAdapter, BACnetSimulatorAdapter, BACnetPoint
from agent_commercial.api.routes import create_api
from agent_commercial.tools_schema import BMSToolHandler, get_bms_tools, get_ops_copilot_prompt
from agent_commercial.briefing_engine import BriefingGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("arvis.ops_copilot")


class OpsCopilot:
    """
    ARVIS Ops Copilot main orchestrator.
    
    Coordinates all BMS components:
    - BACnet/Modbus adapters for data acquisition
    - State engine for current values and history
    - Alarm engine for intelligent alarm processing
    - Energy analyzer for anomaly detection
    - Predictive maintenance engine for failure prediction
    - REST API for dashboard and integrations
    
    Example:
        >>> copilot = OpsCopilot(mode="simulator")
        >>> await copilot.start()
        >>> # Copilot is now running, serving API on port 8000
        >>> await copilot.stop()
    """
    
    def __init__(
        self,
        mode: str = "simulator",  # "simulator" | "bacnet" | "api_only"
        api_port: int = 8000,
        bacnet_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize Ops Copilot.
        
        Args:
            mode: Operating mode
                - "simulator": Use simulated BMS data (for development)
                - "bacnet": Connect to real BACnet devices
                - "api_only": API only, no data acquisition
            api_port: Port for REST API server
            bacnet_config: BACnet connection settings
        """
        self.mode = mode
        self.api_port = api_port
        self.bacnet_config = bacnet_config or {}
        
        # Core engines
        self.state_engine = BMSStateEngine()
        self.alarm_engine = AlarmEngine()
        self.energy_analyzer = EnergyAnalyzer()
        self.predictive_engine = PredictiveMaintenanceEngine()
        
        # Wire engines together
        self.predictive_engine.set_bms_state(self.state_engine)
        
        # Protocol adapter
        self.bacnet_adapter = None
        
        # Database persistence
        from agent_commercial.database import get_database
        self.database = get_database()
        
        # API server
        self.api_app = None
        self._api_server = None
        
        # Tool handler (for LLM integration)
        self.tool_handler = BMSToolHandler(
            bms_state=self.state_engine,
            alarm_engine=self.alarm_engine,
            energy_analyzer=self.energy_analyzer,
            predictive_engine=self.predictive_engine,
        )
        
        # Learning engine (Titans architecture)
        from agent_commercial.learning.learning_engine import get_learning_engine
        self.learning_engine = get_learning_engine(interval_minutes=30)
        
        # ═══════════════════════════════════════════════════════════════════════
        # CONNECTING THE MIND (Tier 15 Integration)
        # ═══════════════════════════════════════════════════════════════════════
        
        # Initialize the Cognitive Layer (The Mind)
        # This brings in: 
        # - World Model (Tier 11)
        # - Online Learner / Autopoiesis (Tier 12)
        # - Dreaming / Briefing Scheduler (Tier 13)
        # - Tool Economy (Tier 10)
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        
        logger.info("Initializing Cognitive Layer (BMSLLMAgent)...")
        self.llm_agent = BMSLLMAgent(
            bms_state=self.state_engine,
            alarm_engine=self.alarm_engine,
            energy_analyzer=self.energy_analyzer,
            predictive_engine=self.predictive_engine,
            # We pass the shared database if needed, but Agent usually handles its own memory
        )
        
        # Connect state engine to DB for persistence
        if hasattr(self.state_engine, 'set_database'):
            self.state_engine.set_database(self.database)
        
        # CONNECT MIND TO BODY (Smart Agency Upgrade)
        # Give AlarmEngine access to the Mind for semantic root cause analysis
        if hasattr(self.llm_agent, 'llm'):
            self.alarm_engine.set_llm_provider(self.llm_agent.llm)
        else:
             logger.warning("BMSLLMAgent has no 'llm' attribute - Smart Alarms disabled")
        
        # Expose key cognitive components to OpsCopilot for direct access if needed
        self.advisor = self.llm_agent.advisor
        self.online_learner = self.llm_agent.online_learner
        self.trust_calibrator = self.llm_agent.trust_calibrator
        
        # Note: shared learning_engine (Titans) is separate but compatible
        
        # State
        self._running = False
        self._tasks = []
        self.last_prediction = None  # For Cognitive Loop
        
        logger.info(f"OpsCopilot initialized in {mode} mode")
    
    # ═══════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════
    
    async def start(self) -> None:
        """Start the Ops Copilot"""
        logger.info("Starting ARVIS Ops Copilot...")
        
        self._running = True
        
        # Initialize based on mode
        if self.mode == "simulator":
            await self._start_simulator()
        elif self.mode == "bacnet":
            await self._start_bacnet()
        
        # Set up alarm engine with equipment topology
        equipment = await self.state_engine.get_all_equipment()
        self.alarm_engine.set_equipment_topology(equipment)
        
        # Start API server
        await self._start_api_server()
        
        # Wire up callbacks
        self._setup_callbacks()
        
        # Start learning engine (Titans loop)
        await self.learning_engine.start()
        
        logger.info(f"Ops Copilot started! API available at http://localhost:{self.api_port}/api/docs")
    
    async def stop(self) -> None:
        """Stop the Ops Copilot"""
        logger.info("Stopping Ops Copilot...")
        
        self._running = False
        
        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        
        # Stop learning engine
        await self.learning_engine.stop()
        
        # Stop adapter
        if self.bacnet_adapter:
            await self.bacnet_adapter.disconnect()
        
        # Stop API server
        if self._api_server:
            self._api_server.should_exit = True
        
        logger.info("Ops Copilot stopped")
    
    # ═══════════════════════════════════════════════════════════════════════
    # INITIALIZATION MODES
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _start_simulator(self) -> None:
        """Start in simulator mode with fake BMS data"""
        logger.info("Starting simulator mode...")
        
        # Use simulator adapter
        self.bacnet_adapter = BACnetSimulatorAdapter()
        await self.bacnet_adapter.connect()
        
        # Register simulated equipment
        await self._register_simulated_equipment()
        
        # Configure simulated points
        self._configure_simulated_points()
        
        # Register zone configurations for ghost detector
        await self._register_zone_configurations()
        
        # Start polling simulation
        self._tasks.append(
            asyncio.create_task(self._simulation_loop())
        )
        
        logger.info("Simulator mode started")
    
    async def _start_bacnet(self) -> None:
        """Start with real BACnet connection"""
        logger.info("Starting BACnet mode...")
        
        self.bacnet_adapter = BACnetAdapter(
            local_address=self.bacnet_config.get("local_address", "0.0.0.0"),
            local_port=self.bacnet_config.get("port", 47808),
        )
        
        success = await self.bacnet_adapter.connect()
        if not success:
            logger.error("Failed to connect to BACnet network")
            return
        
        # Discover devices
        devices = await self.bacnet_adapter.discover_devices()
        logger.info(f"Discovered {len(devices)} BACnet devices")
        
        # Load point config
        if "points_config" in self.bacnet_config:
            self.bacnet_adapter.load_points_from_config(self.bacnet_config["points_config"])
        
        # Start polling
        poll_interval = self.bacnet_config.get("poll_interval", 60)
        self.bacnet_adapter.start_polling(poll_interval)
        
        logger.info("BACnet mode started")
    
    async def _register_simulated_equipment(self) -> None:
        """Register simulated equipment in state engine"""
        from datetime import datetime, timedelta
        
        equipment = [
            Equipment(
                equipment_id="CH-01",
                name="Chiller 1",
                equipment_type=EquipmentType.CHILLER,
                location="Central Plant, Basement, Mechanical Room",
                status=EquipmentStatus.RUNNING,
                runtime_hours=15420,
                efficiency=0.82,
                last_maintenance=datetime.now() - timedelta(days=45),
            ),
            Equipment(
                equipment_id="AHU-01",
                name="Air Handler Unit 1",
                equipment_type=EquipmentType.AHU,
                location="Building A, Floor 1, Core",
                status=EquipmentStatus.RUNNING,
                runtime_hours=12300,
                efficiency=0.88,
                parent_equipment_id="CH-01",
            ),
            Equipment(
                equipment_id="AHU-02",
                name="Air Handler Unit 2",
                equipment_type=EquipmentType.AHU,
                location="Building A, Floor 2, Core",
                status=EquipmentStatus.RUNNING,
                runtime_hours=11800,
                efficiency=0.85,
                parent_equipment_id="CH-01",
            ),
            Equipment(
                equipment_id="VAV-01",
                name="VAV Box 1",
                equipment_type=EquipmentType.VAV,
                location="Building A, Floor 1, Zone 1",
                status=EquipmentStatus.RUNNING,
                parent_equipment_id="AHU-01",
            ),
            Equipment(
                equipment_id="VAV-02",
                name="VAV Box 2",
                equipment_type=EquipmentType.VAV,
                location="Building A, Floor 1, Zone 2",
                status=EquipmentStatus.RUNNING,
                parent_equipment_id="AHU-01",
            ),
            Equipment(
                equipment_id="METER-01",
                name="Main Electric Meter",
                equipment_type=EquipmentType.METER_ELECTRIC,
                location="Central Plant, Basement",
                status=EquipmentStatus.RUNNING,
            ),
        ]
        
        for eq in equipment:
            await self.state_engine.register_equipment(eq)
            # Also persist to database for dashboard queries
            await self.database.save_equipment({
                "equipment_id": eq.equipment_id,
                "name": eq.name,
                "equipment_type": eq.equipment_type.value,
                "status": eq.status.value,
                "location": eq.location,
                "runtime_hours": eq.runtime_hours,
                "efficiency": eq.efficiency * 100 if eq.efficiency else None,  # Convert to percentage
                "last_maintenance": eq.last_maintenance.isoformat() if eq.last_maintenance else None,
                "parent_equipment_id": eq.parent_equipment_id,
            })
        
        logger.info(f"Registered {len(equipment)} simulated equipment")
    
    def _configure_simulated_points(self) -> None:
        """Configure simulated data points"""
        points = [
            # Chiller points
            BACnetPoint(device_id=1001, object_type="analogInput", object_instance=1,
                       point_id="CH-01/CHWST", point_name="CHW Supply Temp",
                       equipment_id="CH-01", unit="°C"),
            BACnetPoint(device_id=1001, object_type="analogInput", object_instance=2,
                       point_id="CH-01/CHWRT", point_name="CHW Return Temp",
                       equipment_id="CH-01", unit="°C"),
            BACnetPoint(device_id=1001, object_type="analogInput", object_instance=3,
                       point_id="CH-01/KW", point_name="Chiller Power",
                       equipment_id="CH-01", unit="kW"),
            
            # AHU-01 points
            BACnetPoint(device_id=2001, object_type="analogInput", object_instance=1,
                       point_id="AHU-01/SAT", point_name="Supply Air Temp",
                       equipment_id="AHU-01", unit="°C"),
            BACnetPoint(device_id=2001, object_type="analogInput", object_instance=2,
                       point_id="AHU-01/RAT", point_name="Return Air Temp",
                       equipment_id="AHU-01", unit="°C"),
            BACnetPoint(device_id=2001, object_type="analogInput", object_instance=3,
                       point_id="AHU-01/SF_SPD", point_name="Supply Fan Speed",
                       equipment_id="AHU-01", unit="%"),
            
            # AHU-02 points
            BACnetPoint(device_id=2002, object_type="analogInput", object_instance=1,
                       point_id="AHU-02/SAT", point_name="Supply Air Temp",
                       equipment_id="AHU-02", unit="°C"),
            BACnetPoint(device_id=2002, object_type="analogInput", object_instance=2,
                       point_id="AHU-02/RAT", point_name="Return Air Temp",
                       equipment_id="AHU-02", unit="°C"),
            
            # Energy meter
            BACnetPoint(device_id=5001, object_type="analogInput", object_instance=1,
                       point_id="METER-01/KW", point_name="Building Power",
                       equipment_id="METER-01", unit="kW"),
        ]
        
        for point in points:
            self.bacnet_adapter.add_point(point)
        
        logger.info(f"Configured {len(points)} simulated points")
    
    async def _register_zone_configurations(self) -> None:
        """Register zone configurations for ghost detector and virtual sensors"""
        zones = [
            {
                "zone_id": "ZONE-01",
                "name": "Conference Room A",
                "floor": "1",
                "building": "Building A",
                "co2_point_id": "VAV-01/CO2",
                "vav_point_id": "VAV-01/DAMPER",
                "lighting_point_id": "VAV-01/LIGHT",
                "return_air_point_id": "AHU-01/RAT",
                "schedule_id": "WEEKDAY",
                "load_kw": 2.5,
            },
            {
                "zone_id": "ZONE-02",
                "name": "Open Office West",
                "floor": "1",
                "building": "Building A",
                "co2_point_id": "VAV-02/CO2",
                "vav_point_id": "VAV-02/DAMPER",
                "lighting_point_id": "VAV-02/LIGHT",
                "return_air_point_id": "AHU-01/RAT",
                "schedule_id": "WEEKDAY",
                "load_kw": 4.0,
            },
            {
                "zone_id": "ZONE-03",
                "name": "Executive Suite",
                "floor": "2",
                "building": "Building A",
                "co2_point_id": "AHU-02/CO2",
                "vav_point_id": "AHU-02/DAMPER",
                "lighting_point_id": "AHU-02/LIGHT",
                "return_air_point_id": "AHU-02/RAT",
                "schedule_id": "WEEKDAY",
                "load_kw": 3.0,
            },
        ]
        
        for zone in zones:
            await self.database.save_zone(zone)
        
        logger.info(f"Registered {len(zones)} zone configurations")
    
    async def _simulation_loop(self) -> None:
        """Background loop for simulating BMS data updates"""
        import random
        from agent_commercial.bms_data_model import EnergyReading
        
        while self._running:
            try:
                # Read all points
                points = await self.bacnet_adapter.read_all_points()
                
                # Update state engine
                for point in points:
                    self.state_engine.update_point_sync(point)
                
                # ═══════════════════════════════════════════════════════════════════
                # COGNITIVE LOOP (Tier 11 & 12 Activation)
                # ═══════════════════════════════════════════════════════════════════
                try:
                    # 1. PERCEIVE
                    current_state = await self.state_engine.get_current_values()
                    
                    # 2. VERIFY (Autopoiesis - Tier 12)
                    # If the Mind predicted this moment, check if it was right
                    if self.last_prediction:
                        # Feed the error signal back to the Online Learner
                        # This triggers self-repair if reality deviates from the mental model
                        self.llm_agent.online_learner.log_observation(
                            prediction=self.last_prediction,
                            actual=current_state
                        )

                    # 3. ANTICIPATE (Predictive Survival - Tier 11)
                    # Ask the Mind to dream the next time step
                    # "What will happen in 30 seconds?"
                    if hasattr(self.llm_agent, 'world_model'):
                        trajectory = self.llm_agent.world_model.simulate_action(
                            current_state=current_state,
                            action="wait", # Passive observation
                            horizon=1
                        )
                        if trajectory and trajectory.predicted_states:
                            self.last_prediction = trajectory.predicted_states[0]
                            
                except Exception as cognitive_err:
                    # Cognition should not crash the motor functions
                    logger.warning(f"Cognitive Loop Glitch: {cognitive_err}")
                    self.last_prediction = None
                # ═══════════════════════════════════════════════════════════════════
                
                # Add energy readings to analyzer AND persist to database
                for point in points:
                    if "KW" in point.point_id:
                        reading = EnergyReading(
                            meter_id=point.equipment_id,
                            value=point.value,
                            unit="kW",
                            timestamp=point.timestamp,
                        )
                        self.energy_analyzer.add_reading(reading)
                        
                        # Persist to database for dashboard
                        await self.database.save_energy_reading(
                            meter_id=point.equipment_id,
                            value=point.value,
                            unit="kW",
                            timestamp=point.timestamp,
                        )
                
                # Simulate occasional alarms
                if random.random() < 0.02:  # 2% chance each cycle
                    await self._simulate_random_alarm()
                
                await asyncio.sleep(30)  # 30 second intervals
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Simulation loop error: {e}")
                await asyncio.sleep(5)
    
    async def _simulate_random_alarm(self) -> None:
        """Simulate a random BMS alarm"""
        from agent_commercial.bms_data_model import Alarm, AlarmSeverity
        import random
        
        alarm_templates = [
            ("AHU-01", "High supply air temperature", AlarmSeverity.HIGH),
            ("AHU-02", "Supply fan VFD fault", AlarmSeverity.MEDIUM),
            ("CH-01", "Low chilled water flow", AlarmSeverity.HIGH),
            ("VAV-01", "Zone temperature out of range", AlarmSeverity.LOW),
            ("VAV-02", "Damper actuator fault", AlarmSeverity.MEDIUM),
        ]
        
        template = random.choice(alarm_templates)
        
        alarm = Alarm(
            equipment_id=template[0],
            message=template[1],
            severity=template[2],
        )
        
        processed = await self.alarm_engine.ingest_alarm(alarm)
        await self.state_engine.add_alarm(alarm)
        
        # Persist alarm to database
        await self.database.save_alarm({
            "alarm_id": alarm.alarm_id,
            "equipment_id": alarm.equipment_id,
            "message": alarm.message,
            "severity": alarm.severity.value,
            "state": alarm.state.value,
            "triggered_at": alarm.triggered_at.isoformat(),
        })
        
        if not processed.suppressed:
            logger.info(f"Simulated alarm: {alarm.message} ({alarm.severity.value})")
    
    # ═══════════════════════════════════════════════════════════════════════
    # API SERVER
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _start_api_server(self) -> None:
        """Start the FastAPI server"""
        import uvicorn
        
        self.api_app = create_api(
            bms_state=self.state_engine,
            alarm_engine=self.alarm_engine,
            energy_analyzer=self.energy_analyzer,
            predictive_engine=self.predictive_engine,

            llm_agent=self.llm_agent,  # CONNECTED: The Mind is now attached to the API
            advisor=self.advisor,  # Feedback loop
            trust_calibrator=self.trust_calibrator,  # Trust metrics
            briefing_engine=BriefingGenerator(
                building_id="default",
                bms_state=self.state_engine,
                alarm_engine=self.alarm_engine,
                energy_analyzer=self.energy_analyzer,
                skillbook=self.skillbook if hasattr(self, 'skillbook') else None,
                database=self.database,
            ),
        )
        
        config = uvicorn.Config(
            self.api_app,
            host="0.0.0.0",
            port=self.api_port,
            log_level="info",
        )
        self._api_server = uvicorn.Server(config)
        
        # Run in background
        self._tasks.append(
            asyncio.create_task(self._api_server.serve())
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════
    
    def _setup_callbacks(self) -> None:
        """Set up event callbacks between components"""
        
        # Point updates -> Energy analyzer
        if self.bacnet_adapter:
            self.bacnet_adapter.on_point_update(self._on_point_update)
    
    def _on_point_update(self, point: BMSDataPoint) -> None:
        """Handle point update from adapter"""
        self.state_engine.update_point_sync(point)
    
    # ═══════════════════════════════════════════════════════════════════════
    # LLM INTEGRATION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a BMS tool call from LLM.
        
        This method is called by the ARVIS ToolExecutor.
        """
        return await self.tool_handler.execute(tool_name, args)
    
    def get_tools(self):
        """Get tool definitions for LLM"""
        return get_bms_tools()
    
    def get_system_prompt(self, language: str = "en") -> str:
        """Get the Ops Copilot system prompt"""
        return get_ops_copilot_prompt(language)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

async def main(args):
    """Main entry point"""
    copilot = OpsCopilot(
        mode=args.mode,
        api_port=args.port,
    )
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def shutdown_handler():
        asyncio.create_task(copilot.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    try:
        await copilot.start()
        
        # Keep running until stopped
        while copilot._running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        pass
    finally:
        await copilot.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ARVIS Ops Copilot - AI-powered BMS Advisory"
    )
    parser.add_argument(
        "--mode",
        choices=["simulator", "bacnet", "api_only"],
        default="simulator",
        help="Operating mode (default: simulator)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API server port (default: 8000)"
    )
    
    args = parser.parse_args()
    
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║           ARVIS Ops Copilot - BMS Advisory AI            ║
    ║                                                           ║
    ║   AI-powered Building Management System Advisor          ║
    ║   For Qatar Commercial Buildings                          ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(main(args))
