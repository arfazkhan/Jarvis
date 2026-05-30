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
from datetime import datetime
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
from agent_commercial.modbus_adapter import ModbusAdapter, ModbusSimulatorAdapter
from agent_commercial.api.routes import create_api
from agent_commercial.tools_schema import BMSToolHandler, get_bms_tools, get_ops_copilot_prompt
from agent_commercial.briefing_engine import BriefingGenerator
from agent_commercial.water_meter_adapter import WaterMeterAdapter
from agent_commercial.virtual_sensors import (
    VirtualSensorRegistry,
    VirtualOccupancySensor,
    VirtualSATSensor,
    get_registry as get_virtual_sensor_registry,
)

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
        mode: str = "simulator",  # "simulator" | "bacnet" | "modbus" | "api_only"
        api_port: int = 8000,
        bacnet_config: Optional[Dict[str, Any]] = None,
        modbus_config: Optional[Dict[str, Any]] = None,
        cafm_config: Optional[Dict[str, Any]] = None,
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
        self.modbus_config = modbus_config or {}
        self.cafm_config = cafm_config or {}

        # Check lite mode
        from config.settings import ARVIS_LITE
        self.lite_mode = ARVIS_LITE

        if self.lite_mode:
            logger.info("═══ ARVIS LITE MODE ═══")

        # Core engines (always active)
        self.state_engine = BMSStateEngine()
        self.alarm_engine = AlarmEngine()
        self.energy_analyzer = EnergyAnalyzer()
        self.predictive_engine = PredictiveMaintenanceEngine()

        # Operator activity feed for concurrent awareness
        from agent_commercial.operator_activity import OperatorActivityFeed
        self.activity_feed = OperatorActivityFeed()
        self.water_adapter = WaterMeterAdapter(
            baseline_m3_monthly=2000.0,
            building_id="BUILDING-01"
        )

        # Virtual Sensor Registry — populated during _start_simulator / _start_bacnet
        self._virtual_sensor_registry = get_virtual_sensor_registry()

        # Wire engines together
        self.predictive_engine.set_bms_state(self.state_engine)

        # Protocol adapters
        self.bacnet_adapter = None
        self.modbus_adapter = None

        # CAFM integration (optional — only if cafm_config provided)
        self.cafm_integration = None
        if self.cafm_config:
            try:
                from agent_commercial.adapters.cafm_adapter import CAFMIntegration, create_cafm_adapter
                self.cafm_integration = CAFMIntegration(create_cafm_adapter(self.cafm_config))
                logger.info(f"CAFM integration ready ({self.cafm_config.get('type', 'rest')})")
            except Exception as e:
                logger.warning(f"CAFM integration init failed: {e}")

        # Database persistence
        from agent_commercial.database import get_database
        self.database = get_database()

        # Connect state engine to DB for persistence
        if hasattr(self.state_engine, 'set_database'):
            self.state_engine.set_database(self.database)

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

        # Learning engine (disabled in lite mode)
        if not self.lite_mode:
            from agent_commercial.learning.learning_engine import get_learning_engine
            self.learning_engine = get_learning_engine(interval_minutes=30)
        else:
            from agent_commercial.learning.learning_engine import get_learning_engine
            self.learning_engine = get_learning_engine(interval_minutes=0)

        # ═══════════════════════════════════════════════════════════════════════
        # COGNITIVE LAYER (Full mode only — lite skips swarm, world model, etc.)
        # ═══════════════════════════════════════════════════════════════════════

        from agent_commercial.bms_llm_agent import BMSLLMAgent

        if not self.lite_mode:
            logger.info("Initializing Full Cognitive Layer (BMSLLMAgent + Swarm)...")
            self.llm_agent = BMSLLMAgent(
                bms_state=self.state_engine,
                alarm_engine=self.alarm_engine,
                energy_analyzer=self.energy_analyzer,
                predictive_engine=self.predictive_engine,
            )
            self.llm_agent._activity_feed = self.activity_feed
        else:
            logger.info("Initializing Lite Cognitive Layer (BMSLLMAgent only, no swarm)...")
            self.llm_agent = BMSLLMAgent(
                bms_state=self.state_engine,
                alarm_engine=self.alarm_engine,
                energy_analyzer=self.energy_analyzer,
                predictive_engine=self.predictive_engine,
            )
            # Disable swarm in lite mode
            self.llm_agent.queen = None

        # Connect LLM to Alarm Engine for semantic root cause analysis
        if hasattr(self.llm_agent, 'llm'):
            self.alarm_engine.set_llm_provider(self.llm_agent.llm)
        else:
            logger.warning("BMSLLMAgent has no 'llm' attribute - Smart Alarms disabled")

        # Expose key cognitive components for direct access
        self.advisor = self.llm_agent.advisor
        self.online_learner = self.llm_agent.online_learner
        self.trust_calibrator = self.llm_agent.trust_calibrator

        # Skillbook — institutional building memory
        try:
            from agent_commercial.skillbook import BuildingSkillbook
            self.skillbook = BuildingSkillbook("default")
            logger.info("BuildingSkillbook initialised")
        except Exception as _sb_err:
            logger.warning(f"Skillbook init failed (non-critical): {_sb_err}")
            self.skillbook = None

        # MetaCognition — calibration + confidence tracking
        try:
            from agent_cognitive.meta_cognition import MetaCognition
            _building_id = getattr(self.state_engine, 'building_id', 'default')
            self.meta_cognition = MetaCognition(_building_id)
            # Share instance with llm_agent so both use same calibration state
            self.llm_agent.meta_cognition = self.meta_cognition
            logger.info("MetaCognition initialised and shared with llm_agent")
        except Exception as _mc_err:
            logger.warning(f"MetaCognition init failed (non-critical): {_mc_err}")
            self.meta_cognition = None

        # ── MemoryOrchestrator — unified 7-tier memory façade ────────────
        try:
            from arvis_core.memory import MemoryOrchestrator, MemoryTier
            from arvis_core.memory.adapters import (
                EpisodicStoreAdapter, ProceduralStoreAdapter, SemanticStoreAdapter,
                InstitutionalStoreAdapter, IdentityStoreAdapter,
                ResolutionStoreAdapter, T1WorkingAdapter,
            )
            from arvis_core.memory.device_alias_resolver import DeviceAliasResolver

            self.memory_orchestrator = MemoryOrchestrator()

            # T1 Working — cross-session conversation turns
            self.memory_orchestrator.register_adapter(
                MemoryTier.T1_WORKING,
                T1WorkingAdapter(db=self.database),
            )

            # T2 Episodic — investigation archive
            self.memory_orchestrator.register_adapter(
                MemoryTier.T2_EPISODIC,
                EpisodicStoreAdapter(db=self.database),
            )

            # T3 Procedural — distilled_rules + OperatorPatternStore
            try:
                from agent_commercial.learning.operator_patterns import OperatorPatternStore
                _op_patterns = OperatorPatternStore()
            except Exception:
                _op_patterns = None
            self.memory_orchestrator.register_adapter(
                MemoryTier.T3_PROCEDURAL,
                ProceduralStoreAdapter(db=self.database, pattern_store=_op_patterns),
            )

            # T4 Semantic — HybridRAGRouter
            _hybrid_rag = getattr(self.llm_agent, "hybrid_rag", None)
            if _hybrid_rag:
                self.memory_orchestrator.register_adapter(
                    MemoryTier.T4_SEMANTIC,
                    SemanticStoreAdapter(hybrid_rag=_hybrid_rag),
                )

            # T5 Institutional — BuildingSkillbook + scenario_retriever
            try:
                from agent_advisory.agentic.scenario_retriever import ScenarioRetriever
                _scenario_ret = ScenarioRetriever()
            except Exception:
                _scenario_ret = None
            self.memory_orchestrator.register_adapter(
                MemoryTier.T5_INSTITUTIONAL,
                InstitutionalStoreAdapter(
                    skillbook=self.skillbook,
                    scenario_retriever=_scenario_ret,
                ),
            )

            # T6 Identity — PreferenceStore + preference_learner
            try:
                from arvis_core.memory.preference_store import PreferenceStore
                _pref_store = PreferenceStore()
            except Exception:
                _pref_store = None
            try:
                from agent_advisory.preference_learner import PreferenceLearningEngine
                _pref_learner = PreferenceLearningEngine()
            except Exception:
                _pref_learner = None
            self.memory_orchestrator.register_adapter(
                MemoryTier.T6_IDENTITY,
                IdentityStoreAdapter(
                    preference_store=_pref_store,
                    preference_learner=_pref_learner,
                ),
            )

            # T7 Resolution — DeviceAliasResolver
            try:
                _resolver = DeviceAliasResolver()
            except Exception:
                _resolver = None
            self.memory_orchestrator.register_adapter(
                MemoryTier.T7_RESOLUTION,
                ResolutionStoreAdapter(resolver=_resolver),
            )

            # Share orchestrator with llm_agent, queen, and tool handler
            self.llm_agent.memory_orchestrator = self.memory_orchestrator
            if hasattr(self.llm_agent, "queen") and self.llm_agent.queen:
                self.llm_agent.queen.memory_orchestrator = self.memory_orchestrator
            # Mem-8: share with tool handlers so query_skillbook/hybrid_search go through façade
            if hasattr(self, "tool_handler") and self.tool_handler:
                self.tool_handler.memory_orchestrator = self.memory_orchestrator
            if hasattr(self.llm_agent, "tool_handler") and self.llm_agent.tool_handler:
                self.llm_agent.tool_handler.memory_orchestrator = self.memory_orchestrator

            logger.info("[ARVIS] MemoryOrchestrator wired with T1–T7 adapters + tool handlers")
        except Exception as _mo_err:
            logger.warning(f"MemoryOrchestrator init failed (non-critical): {_mo_err}")
            self.memory_orchestrator = None

        # ── TerminalAdvisoryStore — persistent critical advisory registry ──
        # Critical findings (life safety, predictive failure, compliance breach)
        # MUST survive across swarm turns until operator acknowledges. Without
        # this, operators can dismiss life-safety calls with one follow-up
        # question because each turn starts a fresh swarm.
        try:
            from agent_commercial.terminal_advisory_store import TerminalAdvisoryStore
            self.terminal_advisory_store = TerminalAdvisoryStore()
            # Wire into Queen so post-synthesis detection + pre-swarm injection work
            if hasattr(self.llm_agent, "queen") and self.llm_agent.queen:
                self.llm_agent.queen.terminal_advisory_store = self.terminal_advisory_store
            logger.info("[ARVIS] TerminalAdvisoryStore wired into Queen")
        except Exception as _tas_err:
            logger.warning(f"TerminalAdvisoryStore init failed (non-critical): {_tas_err}")
            self.terminal_advisory_store = None

        # ── B9: Autonomous Monitoring — Watchdog + Investigation Dispatcher ────
        # AnomalyWatchdog computes per-point rolling Z-score on every BMS update
        # and emits "anomaly_detected" events to EventBus. InvestigationDispatcher
        # subscribes and routes anomalies into autonomous Queen swarm investigations.
        # This makes ARVIS proactive (24/7 watchdog) instead of reactive (operator-prompted).
        self._watchdog = None
        self._dispatcher = None
        self._event_bus = None
        if not self.lite_mode:
            try:
                from arvis_core.event_bus.event_bus import EventBus
                from agent_commercial.anomaly_watchdog import AnomalyWatchdog
                from agent_commercial.investigation_dispatcher import InvestigationDispatcher

                self._event_bus = EventBus()

                # Physics hard-limit bounds (backstop for near-constant signals)
                _physics_bounds = {
                    "chw_supply": (4.0, 12.0),     # CHW supply temp (°C)
                    "cop": (1.5, 7.0),             # COP plausibility
                    "zone_temp": (18.0, 30.0),     # comfort zone (°C)
                    "sat": (10.0, 22.0),           # supply air temp (°C)
                    "condenser": (20.0, 40.0),     # condenser water (°C)
                    "filter_dp": (0.0, 500.0),     # filter DP (Pa)
                    "vibration": (0.0, 10.0),      # vibration (mm/s)
                }

                self._watchdog = AnomalyWatchdog(
                    event_bus=self._event_bus,
                    physics_bounds=_physics_bounds,
                    min_history=30,
                    cooldown_seconds=180,
                    db_conn=None,
                )

                # Dispatcher routes anomaly events → Queen swarm
                _queen = getattr(self.llm_agent, "queen", None)
                _sse = getattr(self, "sse_broadcaster", None)
                self._dispatcher = InvestigationDispatcher(
                    queen=_queen,
                    bms_state=self.state_engine,
                    sse_broadcaster=_sse,
                    memory_orchestrator=self.memory_orchestrator,
                    event_bus=self._event_bus,
                    max_concurrent=2,
                    cooldown_per_equipment=300,
                )

                # Register watchdog on every point update
                self.state_engine.on_point_update(self._watchdog.on_point_update)
                # Register autonomous alarm investigation
                self.state_engine.on_alarm(self._on_alarm_auto_investigate)

                # Expose watchdog to the LLM agent so investigations can surface
                # the real z-score for the equipment under analysis (demo screen 2/4).
                try:
                    self.llm_agent._watchdog = self._watchdog
                except Exception:
                    pass

                logger.info(
                    "[ARVIS] B9 Autonomous Monitor active: AnomalyWatchdog "
                    "+ InvestigationDispatcher wired, queue=2 max, 5min/equipment cooldown"
                )
            except Exception as _b9_err:
                logger.warning(f"B9 Autonomous Monitor init failed (non-critical): {_b9_err}")
                self._watchdog = None
                self._dispatcher = None
                self._event_bus = None

        # State
        self._running = False
        self._tasks = []
        self.last_prediction = None

        if self.lite_mode:
            logger.info(
                "ARVIS Lite initialized:\n"
                "  [x] BMS State Engine\n"
                "  [x] Alarm Engine\n"
                "  [x] Energy Analyzer (rule-based)\n"
                "  [x] Predictive Maintenance (ASHRAE defaults)\n"
                "  [x] GSAS Reporter\n"
                "  [x] Database Persistence\n"
                "  [ ] Cognitive Loop (disabled)\n"
                "  [ ] Swarm (disabled - single agent)\n"
                "  [ ] ML Models (rule-based fallbacks)\n"
                "  [ ] Fleet Intelligence (disabled)\n"
                "  [ ] Learning Engine (disabled)"
            )
        else:
            logger.info(f"OpsCopilot initialized in {mode} mode (full)")
    
    # ═══════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════
    
    async def start(self) -> None:
        """Start the Ops Copilot"""
        logger.info("Starting ARVIS Ops Copilot...")

        if self._watchdog:
            try:
                self._watchdog.db_conn = await self.database._get_async_connection()
                await self._watchdog.reload_thresholds()
            except Exception as e:
                logger.warning(f"Failed to initialize watchdog DB connection: {e}")

        self._running = True

        # Warm-start: restore previous state from DB snapshot
        restored = await self.state_engine.restore_from_snapshot()
        if restored:
            logger.info("Warm-start complete — state recovered from snapshot")

        # Warm-start: event correlator (load 24h history + learned patterns)
        try:
            from agent_commercial.event_correlator import EventCorrelator
            self._event_correlator = EventCorrelator(
                bms_state=self.state_engine,
                alarm_engine=self.alarm_engine,
                energy_analyzer=self.energy_analyzer,
            )
            await self._event_correlator.warm_start()

            # Wire LLM provider for semantic causality analysis
            if hasattr(self.llm_agent, 'llm') and self.llm_agent.llm:
                self._event_correlator.set_llm_provider(self.llm_agent.llm)

            # Feed alarm events to correlator for real-time correlation
            self.state_engine.on_alarm(self._on_alarm_for_correlator)
            # Sync alarms injected via state_engine into alarm_engine (ensures tool handler finds them)
            self.state_engine.on_alarm(self._on_alarm_sync_to_engine)
            logger.info("EventCorrelator wired: LLM + alarm callback active")
        except Exception as e:
            logger.debug(f"Event correlator warm-start skipped: {e}")

        # Initialize based on mode
        self._bms_connected = False
        if self.mode == "simulator":
            await self._start_simulator()
            self._bms_connected = True
        elif self.mode == "bacnet":
            _allow_offline = self.bacnet_config.get("allow_offline", False)
            try:
                await self._start_bacnet()
            except RuntimeError as _e:
                if _allow_offline:
                    logger.warning(f"BACnet offline — starting in degraded mode: {_e}")
                else:
                    raise
        elif self.mode == "modbus":
            await self._start_modbus()
            self._bms_connected = True

        # Set up alarm engine with equipment topology
        equipment = await self.state_engine.get_all_equipment()
        self.alarm_engine.set_equipment_topology(equipment)

        # Start API server
        await self._start_api_server()

        # Wire up callbacks
        self._setup_callbacks()

        # Start learning engine (Titans loop)
        await self.learning_engine.start()

        # Start Cognitive Loop (full mode only)
        self._cognitive_loop = None
        self.prediction_engine = None
        if not self.lite_mode:
            try:
                from arvis_core.event_bus.event_bus import EventBus
                from agent_cognitive.cognitive_loop import CognitiveLoop
                from agent_cognitive.prediction_engine import PredictionEngine

                event_bus = EventBus()
                self._cognitive_loop = CognitiveLoop(event_bus)
                self._cognitive_loop.set_bms_engines(
                    bms_state=self.state_engine,
                    alarm_engine=self.alarm_engine,
                    energy_analyzer=self.energy_analyzer,
                    pm_engine=self.predictive_engine,
                )
                self._cognitive_loop.load_checkpoint()
                self._cognitive_loop.start()

                # Prediction engine with warm-start
                self.prediction_engine = PredictionEngine(
                    building_id="default",
                    bms_state_engine=self.state_engine,
                )
                self.prediction_engine.load_baselines()

                logger.info("Cognitive Loop + Prediction Engine active")
            except Exception as e:
                logger.warning(f"Cognitive Loop init skipped: {e}")

        # Start periodic snapshot task (every 5 minutes)
        self._tasks.append(
            asyncio.create_task(self._snapshot_loop())
        )

        # Mem-9: Start nightly memory consolidation job
        self._tasks.append(
            asyncio.create_task(self._memory_consolidation_loop())
        )

        # Mem-7: Start document ingestion file watcher (watches data/manuals/)
        try:
            from agent_commercial.services.ingestion_watcher import IngestionWatcher
            _kb = getattr(self.llm_agent, "knowledge_base", None)
            _watcher = IngestionWatcher(knowledge_base=_kb)
            self._tasks.append(_watcher.start())
            logger.info("[Mem-7] IngestionWatcher started")
        except Exception as _iw_err:
            logger.warning(f"[Mem-7] IngestionWatcher init failed (non-critical): {_iw_err}")

        # Register and start the ThresholdCalibrator service!
        if not self.lite_mode:
            try:
                from agent_commercial.threshold_calibrator import ThresholdCalibrator
                self.calibrator = ThresholdCalibrator(
                    db_conn=await self.database._get_async_connection(),
                    event_bus=self._event_bus,
                    building_id="default"
                )
                self._tasks.append(
                    asyncio.create_task(self._calibration_loop())
                )
                logger.info("[Calibrator] ThresholdCalibrator service started!")
            except Exception as _cal_err:
                logger.warning(f"ThresholdCalibrator init failed (non-critical): {_cal_err}")

        # Terminal advisory escalation loop — hourly check for unack > 4h
        if getattr(self, "terminal_advisory_store", None) is not None:
            self._tasks.append(
                asyncio.create_task(self._terminal_escalation_loop())
            )
            logger.info("[TerminalAdvisory] Escalation loop started (checks every 1h, threshold 4h)")

        # Fix 4: FDD VAE bootstrap — 30s delayed so BMS data flows first
        self._tasks.append(asyncio.create_task(self._fdd_bootstrap_task()))
        logger.info("[ML-FDD] FDD bootstrap task scheduled (fires in 30s)")

        logger.info(f"Ops Copilot started! API available at http://localhost:{self.api_port}/api/docs")
    
    async def stop(self) -> None:
        """Stop the Ops Copilot"""
        logger.info("Stopping Ops Copilot...")

        self._running = False

        # Final snapshot before shutdown
        await self.state_engine.take_snapshot()
        if hasattr(self, '_event_correlator') and self._event_correlator:
            self._event_correlator.persist_patterns()
        logger.info("Final state snapshot saved")

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()

        # Stop cognitive loop
        if hasattr(self, '_cognitive_loop') and self._cognitive_loop:
            self._cognitive_loop.save_checkpoint()
            self._cognitive_loop.stop()

        # Save prediction baselines
        if hasattr(self, 'prediction_engine') and self.prediction_engine:
            self.prediction_engine.save_baselines()

        # Stop learning engine
        await self.learning_engine.stop()

        # Stop adapters
        if self.bacnet_adapter:
            await self.bacnet_adapter.disconnect()
        if self.modbus_adapter:
            await self.modbus_adapter.disconnect()

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

        # Register virtual sensors in the registry
        self._register_virtual_sensors()

        # Start polling simulation
        self._tasks.append(
            asyncio.create_task(self._simulation_loop())
        )

        logger.info("Simulator mode started")
    
    def _register_virtual_sensors(self) -> None:
        """Populate the VirtualSensorRegistry with known AHUs and zones."""
        registry = self._virtual_sensor_registry

        # SAT sensors — one per AHU
        for ahu_id in ("AHU-01", "AHU-02"):
            sensor_id = f"vsat_{ahu_id}"
            if sensor_id not in registry:
                registry.register(
                    sensor_id=sensor_id,
                    sensor_obj=VirtualSATSensor(),
                    sensor_type="sat",
                    description=f"Virtual supply-air temperature sensor for {ahu_id}",
                    equipment_ids=[ahu_id],
                )

        # Occupancy sensors — one per zone
        for zone_id in ("ZONE-01", "ZONE-02", "ZONE-03"):
            sensor_id = f"vocc_{zone_id}"
            if sensor_id not in registry:
                registry.register(
                    sensor_id=sensor_id,
                    sensor_obj=VirtualOccupancySensor(),
                    sensor_type="occupancy",
                    description=f"Virtual occupancy sensor for {zone_id}",
                    equipment_ids=[zone_id],
                )

        logger.info(
            f"VirtualSensorRegistry populated: {len(registry)} sensors "
            f"({', '.join(m['sensor_id'] for m in registry.get_all_registered())})"
        )

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
            self._bms_connected = False
            raise RuntimeError(
                "BACnet connection failed. Check network config or switch to mode='simulator'. "
                "Set bacnet_config['allow_offline']=True to start degraded (no live data)."
            )
        self._bms_connected = True
        
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
    
    async def _start_modbus(self) -> None:
        """Start with Modbus TCP connection"""
        logger.info("Starting Modbus mode...")

        host = self.modbus_config.get("host", "127.0.0.1")
        port = self.modbus_config.get("port", 502)
        unit_id = self.modbus_config.get("unit_id", 1)

        self.modbus_adapter = ModbusAdapter(host=host, port=port, unit_id=unit_id)
        success = await self.modbus_adapter.connect()
        if not success:
            logger.error(f"Failed to connect to Modbus device at {host}:{port}")
            logger.info("Falling back to Modbus simulator")
            self.modbus_adapter = ModbusSimulatorAdapter()
            await self.modbus_adapter.connect()

        if "registers" in self.modbus_config:
            count = self.modbus_adapter.load_points_from_config(self.modbus_config)
            logger.info(f"Loaded {count} Modbus register points")

        self.modbus_adapter.on_point_update(self._on_point_update)
        poll_interval = self.modbus_config.get("poll_interval", 30)
        await self.modbus_adapter.start_polling(poll_interval)
        logger.info(f"Modbus mode started (polling every {poll_interval}s)")

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
            Equipment(
                equipment_id="WTR-01",
                name="Main Water Meter",
                equipment_type=EquipmentType.METER_WATER,
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
            
            # Water meter
            BACnetPoint(device_id=6001, object_type="analogInput", object_instance=1,
                       point_id="WTR-01/TOTAL_M3", point_name="Total Water Consumption",
                       equipment_id="WTR-01", unit="m³"),
            BACnetPoint(device_id=6001, object_type="analogInput", object_instance=2,
                       point_id="WTR-01/FLOW_LPM", point_name="Water Flow Rate",
                       equipment_id="WTR-01", unit="L/min"),
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
                        await self.llm_agent.online_learner.log_observation(
                            prediction_type="world_model",
                            predicted_values=self.last_prediction.features,
                            actual_values=current_state
                        )

                    # 3. ANTICIPATE (Predictive Survival - Tier 11)
                    # Ask the Mind to dream the next time step
                    # "What will happen in 30 seconds?"
                    if hasattr(self.llm_agent, 'world_model'):
                        trajectory = self.llm_agent.world_model.simulate_action(
                            initial_context=current_state,
                            action="wait", # Passive observation
                            horizon=1
                        )
                        if trajectory and trajectory.predicted_states:
                            self.last_prediction = trajectory.predicted_states[0]
                            
                except Exception as cognitive_err:
                    # Cognition should not crash the motor functions
                    logger.warning(f"Cognitive Loop Glitch: {cognitive_err}")
                    self.last_prediction = None

                # 4. OUTCOME MEASUREMENT (read-only: check if past recommendations improved metrics)
                try:
                    await self._measure_pending_outcomes()
                except Exception as _om_err:
                    logger.debug("Outcome measurement skipped: %s", _om_err)
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
                    
                    if "TOTAL_M3" in point.point_id:
                        self.water_adapter.ingest_reading(
                            meter_id="MAIN",
                            value_m3=point.value,
                            timestamp=point.timestamp
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
    
    async def _snapshot_loop(self) -> None:
        """Periodic state snapshot for warm-start recovery (all components)."""
        while self._running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await self.state_engine.take_snapshot()

                # Prediction engine baselines
                if hasattr(self, 'prediction_engine') and self.prediction_engine:
                    self.prediction_engine.save_baselines()

                # Event correlator patterns
                if hasattr(self, '_event_correlator') and self._event_correlator:
                    self._event_correlator.persist_patterns()

                # Cognitive loop checkpoint (hourly — every 12th iteration)
                if hasattr(self, '_cognitive_loop') and self._cognitive_loop:
                    if not hasattr(self, '_snapshot_count'):
                        self._snapshot_count = 0
                    self._snapshot_count += 1
                    if self._snapshot_count % 12 == 0:
                        self._cognitive_loop.save_checkpoint()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Snapshot loop error: {e}")

    async def _terminal_escalation_loop(self) -> None:
        """
        Periodic terminal advisory escalation check. Runs hourly. For each
        ACTIVE advisory unacknowledged > 4h, fires escalation event (records
        in store + logs warning). In production this would emit SMS/email; for
        Marina pilot it's an auditable log + DB row.
        """
        while self._running:
            try:
                await asyncio.sleep(3600)  # 1 hour
                if self.terminal_advisory_store is not None:
                    escalated = await self.terminal_advisory_store.escalate_overdue(
                        threshold_hours=4.0,
                        building_id="default",
                    )
                    if escalated:
                        logger.warning(
                            f"[TerminalAdvisory] Escalation tick: {len(escalated)} advisory(ies) "
                            f"surpassed 4h ack threshold — escalation events fired"
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TerminalAdvisory] escalation loop error: {e}")

    async def _calibration_loop(self) -> None:
        """Periodic threshold calibration background loop."""
        logger.info("[Calibrator] Background calibration loop started.")
        
        # Initial catch-up on startup so we have baselines immediately!
        # Skip in simulator mode — scenarios will inject specific baselines manually.
        if self.mode != "simulator":
            try:
                await self._run_digest_catchup()
                await self.calibrator.run_calibration_cycle(trigger_source="startup")
            except Exception as e:
                logger.warning(f"[Calibrator] Initial startup calibration skipped: {e}")

        last_checked_date = None
        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Check current simulated date (from data_points)
                current_date = None
                query = "SELECT MAX(timestamp) as max_ts FROM data_points"
                async with self.database._execute(query) as cursor:
                    row = await cursor.fetchone()
                    if row and row["max_ts"]:
                        current_date = row["max_ts"][:10]

                if current_date and current_date != last_checked_date:
                    logger.info(f"[Calibrator] New date detected: {current_date}. Building daily digests...")
                    # Build digest for the day that just completed!
                    if last_checked_date:
                        await self.calibrator.digest_builder.build_digest_for_date(last_checked_date)

                    last_checked_date = current_date

                    # Daily auto-rollback safety check BEFORE recalibration so
                    # any blown calibrations from yesterday revert immediately.
                    try:
                        rolled = await self.calibrator.auto_rollback_check()
                        if rolled:
                            logger.warning(
                                f"[Calibrator] Auto-rollback reverted {rolled} scope(s) "
                                f"due to observed FP > 5x target."
                            )
                    except Exception as _rb_err:
                        logger.error(f"[Calibrator] auto_rollback_check failed: {_rb_err}")

                    await self.calibrator.run_calibration_cycle(trigger_source="daily_schedule")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Calibrator] Error in background calibration loop: {e}")

    async def _run_digest_catchup(self) -> None:
        """Catch up digests for all raw telemetry currently in the database."""
        logger.info("[Calibrator] Running daily digest catchup...")
        query_dates = "SELECT DISTINCT SUBSTR(timestamp, 1, 10) as date_str FROM data_points"
        async with self.database._execute(query_dates) as cursor:
            rows = await cursor.fetchall()
            dates = [r["date_str"] for r in rows if r["date_str"]]
            
        for d in sorted(dates):
            # Check if digest already exists
            check_query = "SELECT COUNT(*) as cnt FROM point_baselines WHERE date = ? AND building_id = ?"
            async with self.database._execute(check_query, (d, "default")) as cursor:
                row = await cursor.fetchone()
                if row and row["cnt"] > 0:
                    continue  # Already built
            
            logger.info(f"[Calibrator] Catching up digest for date: {d}")
            await self.calibrator.digest_builder.build_digest_for_date(d)

    async def _memory_consolidation_loop(self) -> None:
        """Nightly memory consolidation — stale rule decay + episodic distillation + skillbook decay."""
        await asyncio.sleep(3600)  # wait 1h after startup before first run
        while self._running:
            try:
                from arvis_core.memory.consolidator import MemoryConsolidator
                _mo = getattr(self, "memory_orchestrator", None)
                _llm = getattr(self.llm_agent, "llm", None)
                _consolidator = MemoryConsolidator(
                    orchestrator=_mo,
                    db=self.database,
                    llm=_llm,
                )
                _building_id = getattr(self.state_engine, "building_id", "default")
                await _consolidator.consolidate(building_id=_building_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Consolidator] Nightly job error: {e}")
            await asyncio.sleep(86400)  # 24h

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
        
        _goal_tracker = None
        if hasattr(self, '_cognitive_loop') and self._cognitive_loop:
            _goal_tracker = getattr(self._cognitive_loop, 'goal_tracker', None)

        self.api_app = create_api(
            bms_state=self.state_engine,
            alarm_engine=self.alarm_engine,
            energy_analyzer=self.energy_analyzer,
            predictive_engine=self.predictive_engine,

            llm_agent=self.llm_agent,
            advisor=self.advisor,
            trust_calibrator=self.trust_calibrator,
            water_adapter=self.water_adapter,
            cafm_integration=self.cafm_integration,
            virtual_sensor_registry=self._virtual_sensor_registry,
            goal_tracker=_goal_tracker,
            memory_orchestrator=getattr(self, "memory_orchestrator", None),
            skillbook=self.skillbook,
            meta_cognition=self.meta_cognition,
            briefing_engine=BriefingGenerator(
                building_id="default",
                bms_state=self.state_engine,
                alarm_engine=self.alarm_engine,
                energy_analyzer=self.energy_analyzer,
                skillbook=self.skillbook,
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
        
        # Point updates -> state engine (both adapters register here if both active)
        if self.bacnet_adapter:
            self.bacnet_adapter.on_point_update(self._on_point_update)
        if self.modbus_adapter:
            self.modbus_adapter.on_point_update(self._on_point_update)
    
    def _on_point_update(self, point: BMSDataPoint) -> None:
        """Handle point update from adapter"""
        self.state_engine.update_point_sync(point)

        # Feed filter DP readings into degradation predictor
        pid = (point.point_id or "").upper()
        if "FLT_DP" in pid or "FILTER_DP" in pid or "FILTER_DIFF" in pid:
            if point.value is not None and point.equipment_id:
                self.predictive_engine.filter_predictor.record_reading(
                    equipment_id=point.equipment_id,
                    dp_pa=float(point.value),
                )

    async def _measure_pending_outcomes(self) -> None:
        """
        Read telemetry to score past recommendations. Read-only — no BMS commands.
        Runs every simulation cycle; skips if no pending outcomes.
        """
        db = getattr(self, "database", None)
        if db is None:
            return
        try:
            pending = await db.get_pending_outcomes()
        except Exception:
            return

        if not pending:
            return

        for outcome in pending:
            try:
                # Read current energy metric (read-only telemetry)
                current_kwh = None
                if hasattr(self.state_engine, "_points"):
                    for pid, pt in self.state_engine._points.items():
                        if "KW" in pid.upper() and "TOTAL" in pid.upper():
                            current_kwh = getattr(pt, "value", None)
                            break

                baseline = outcome.get("baseline_kwh") or 0.0
                predicted_delta = outcome.get("predicted_kwh_delta") or 0.0

                if current_kwh is not None and baseline > 0:
                    actual_delta = current_kwh - baseline
                    accuracy = (
                        1.0 - abs(actual_delta - predicted_delta) / max(abs(predicted_delta), 1.0)
                        if predicted_delta != 0 else None
                    )
                    status = "measured"
                else:
                    actual_delta = None
                    accuracy = None
                    status = "no_telemetry"

                await db.update_outcome(
                    outcome["outcome_id"],
                    actual_kwh_delta=actual_delta,
                    outcome_status=status,
                    accuracy=accuracy,
                    measured_at=datetime.now().isoformat(),
                )

                # Feed result back to MetaCognition for calibration
                if accuracy is not None and hasattr(self, "llm_agent"):
                    _mc = getattr(self.llm_agent, "meta_cognition", None)
                    if _mc is not None:
                        _mc.record_outcome(
                            decision_id=outcome.get("recommendation_id", outcome["outcome_id"]),
                            outcome="success" if (accuracy or 0) > 0.7 else "miss",
                            quality="good" if (accuracy or 0) > 0.7 else "poor",
                        )
            except Exception as _e:
                logger.debug("Outcome measurement for %s failed: %s", outcome.get("outcome_id"), _e)

    def _on_alarm_sync_to_engine(self, alarm) -> None:
        """Sync alarms added via state_engine into alarm_engine for tool handler access."""
        if not hasattr(self, "alarm_engine") or not self.alarm_engine:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.alarm_engine.ingest_alarm(alarm))
            else:
                loop.run_until_complete(self.alarm_engine.ingest_alarm(alarm))
        except Exception as e:
            logger.debug(f"Alarm sync to engine failed (non-fatal): {e}")

    def _on_alarm_for_correlator(self, alarm) -> None:
        """Feed alarm events to EventCorrelator for real-time correlation."""
        if not hasattr(self, '_event_correlator') or not self._event_correlator:
            return

        from agent_commercial.event_correlator import Event, EventSource
        from datetime import datetime

        event = Event(
            event_id=alarm.alarm_id,
            source=EventSource.BMS_ALARM,
            timestamp=alarm.triggered_at if hasattr(alarm, 'triggered_at') else datetime.now(),
            event_type=getattr(alarm, 'alarm_type', 'unknown'),
            description=getattr(alarm, 'message', ''),
            equipment_id=getattr(alarm, 'equipment_id', None),
            zone_id=getattr(alarm, 'zone_id', None),
        )
        self._event_correlator.add_event(event)

        # Async correlation for significant alarms (high/critical)
        severity = getattr(alarm, 'severity', None)
        if severity and hasattr(severity, 'value') and severity.value in ('critical', 'high'):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._run_correlation(event))
            except RuntimeError:
                pass

        # Store significant alarms in FAISS for future semantic recall
        _sev = getattr(alarm, "severity", "low")
        _sev_str = _sev.value if hasattr(_sev, "value") else str(_sev)
        if _sev_str in ("high", "critical"):
            try:
                from agent_cognitive.embeddings_store import EmbeddingsStore
                _store = EmbeddingsStore()
                if _store.enabled:
                    _store.add_text(
                        text=f"{getattr(alarm, 'message', '')} on {getattr(alarm, 'equipment_id', '')}",
                        meta={
                            "equipment_id": getattr(alarm, "equipment_id", ""),
                            "severity": getattr(alarm, "severity", ""),
                            "timestamp": getattr(alarm, "triggered_at", ""),
                            "summary": getattr(alarm, "message", ""),
                            "type": "alarm",
                        }
                    )
            except Exception as _fe:
                logger.debug("FAISS alarm store skipped: %s", _fe)

    def _on_alarm_auto_investigate(self, alarm) -> None:
        """B9 callback: fire autonomous investigation for critical/high alarms."""
        if not self._dispatcher:
            return
        severity = getattr(alarm, "severity", None)
        severity_str = getattr(severity, "value", str(severity)).lower() if severity else ""
        if severity_str in ("critical", "high"):
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._dispatcher.investigate_alarm(alarm))
                else:
                    loop.run_until_complete(self._dispatcher.investigate_alarm(alarm))
            except Exception as e:
                logger.debug(f"Autonomous alarm investigation failed (non-fatal): {e}")

    async def _run_correlation(self, event) -> None:
        """Run correlation analysis for a significant alarm event."""
        try:
            result = await self._event_correlator.correlate(event.to_dict())
            if result.confidence > 0.5 and result.causal_chain:
                logger.info(
                    f"Correlation found: {event.equipment_id} → "
                    f"{len(result.causal_chain)} causal links (confidence: {result.confidence})"
                )
                # Store for grounding injection
                if not hasattr(self, '_recent_correlations'):
                    self._recent_correlations = []
                self._recent_correlations.append(result.to_dict())
                # Keep only last 20
                self._recent_correlations = self._recent_correlations[-20:]
        except Exception as e:
            logger.debug(f"Correlation analysis failed: {e}")
    
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

    async def _fdd_bootstrap_task(self) -> None:
        """Background task: waits for BMS data to accumulate, then trains FDD autoencoders."""
        await asyncio.sleep(300)  # 5 min — enough for sim to write ~60+ rows per equipment
        try:
            await self.train_fdd_autoencoders()
        except Exception as e:
            logger.warning(f"[ML-FDD] Bootstrap failed (non-critical): {e}")

    async def train_fdd_autoencoders(self) -> None:
        """
        Bootstrap the predictive engine's per-type VAE analyzers on a synthetic
        normal-operation baseline derived from current equipment metadata.

        IMPORTANT: detect_faults() consumes `predictive_engine.vae_analyzers`
        (EquipmentFeatures-shaped, columns == predictive_engine.feature_names),
        NOT the standalone fdd_autoencoder singletons. We must train *those*
        analyzers or detect_faults keeps reporting "VAE model not loaded".

        The VAE only needs a healthy baseline distribution to flag novelty, so
        we synthesize jittered normal samples per equipment from runtime/
        efficiency/maintenance metadata that P1 already seeded.
        """
        import numpy as np
        import pandas as pd
        from agent_commercial.predictive_maintenance import EquipmentFeatures

        engine = self.predictive_engine
        if engine is None or not getattr(engine, "vae_analyzers", None):
            logger.warning("[ML-FDD] No predictive_engine.vae_analyzers; skipping VAE bootstrap.")
            return

        logger.info("[ML-FDD] Bootstrapping predictive VAE analyzers from equipment baseline...")
        feature_names = engine.feature_names

        # Map BMS equipment_type.value -> vae_analyzers key
        type_key = {
            "air_handling_unit": "ahu",
            "ahu": "ahu",
            "chiller": "chiller",
            "vav": "vav",
            "vav_box": "vav",
        }

        try:
            all_equipment = await self.state_engine.get_all_equipment()
        except Exception as e:
            logger.error(f"[ML-FDD] Cannot list equipment: {e}")
            return

        # Bucket equipment by analyzer key
        buckets: Dict[str, list] = {}
        for eq in all_equipment:
            ev = getattr(getattr(eq, "equipment_type", None), "value", None)
            key = type_key.get((ev or "").lower())
            if key and key in engine.vae_analyzers:
                buckets.setdefault(key, []).append(eq)

        def _base_features(eq) -> EquipmentFeatures:
            last_maint = getattr(eq, "last_maintenance", None)
            days_since = (datetime.now() - last_maint).days if last_maint else 45
            return EquipmentFeatures(
                equipment_id=getattr(eq, "equipment_id", "EQ"),
                runtime_hours=float(getattr(eq, "runtime_hours", 3000.0) or 3000.0),
                start_stop_cycles=int(getattr(eq, "start_stop_cycles", 180) or 180),
                days_since_maintenance=int(days_since),
                efficiency=float(getattr(eq, "efficiency", 0.85) or 0.85),
            )

        for key, vae in engine.vae_analyzers.items():
            eqs = buckets.get(key, [])
            if not eqs:
                logger.warning(f"[ML-FDD] No equipment for analyzer '{key}'; skipping.")
                continue
            try:
                # Synthesize jittered normal samples: each equipment contributes
                # several near-baseline rows so the VAE learns the healthy manifold.
                rows = []
                samples_per_eq = max(8, vae.sequence_length * 3)
                for eq in eqs:
                    base = _base_features(eq).to_array().astype(float)
                    for _ in range(samples_per_eq):
                        jitter = 1.0 + np.random.uniform(-0.05, 0.05, size=base.shape)
                        rows.append(base * jitter)
                if len(rows) < max(10, vae.sequence_length * 2):
                    logger.warning(f"[ML-FDD] '{key}': only {len(rows)} samples; skipping.")
                    continue
                df = pd.DataFrame(rows, columns=feature_names)
                logger.info(f"[ML-FDD] Training VAE '{key}' on {len(df)} synthetic normal rows...")
                result = vae.train(df)
                if isinstance(result, dict) and result.get("status") == "trained":
                    logger.info(f"[ML-FDD] VAE '{key}' trained (is_trained={vae.is_trained}).")
                    try:
                        vae.save_model(result)
                    except Exception as _se:
                        logger.debug(f"[ML-FDD] VAE '{key}' save skipped: {_se}")
                else:
                    logger.warning(f"[ML-FDD] VAE '{key}' training did not complete: {result}")
            except Exception as e:
                logger.error(f"[ML-FDD] Error training VAE '{key}': {e}", exc_info=True)

        # Seed equipment_history so detect_faults has sequence context immediately
        try:
            for key, eqs in buckets.items():
                vae = engine.vae_analyzers.get(key)
                seqlen = getattr(vae, "sequence_length", 6)
                for eq in eqs:
                    eid = getattr(eq, "equipment_id", None)
                    if not eid:
                        continue
                    base = _base_features(eq)
                    engine.equipment_history.setdefault(eid, [])
                    while len(engine.equipment_history[eid]) < seqlen:
                        engine.equipment_history[eid].append(base)
        except Exception as e:
            logger.debug(f"[ML-FDD] equipment_history seeding skipped: {e}")



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
        choices=["simulator", "bacnet", "modbus", "api_only"],
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
