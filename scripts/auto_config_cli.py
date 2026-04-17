#!/usr/bin/env python3
"""
ARVIS BMS Auto-Configurator CLI
===============================

Run this on-site at a new building to auto-generate bms_config.yaml.

Usage:
    python scripts/auto_config_cli.py --mode simulator
    python scripts/auto_config_cli.py --mode bacnet --port 47808 --building-id DOHA-TOWER-01

The tool will:
    1. Connect to BACnet network
    2. Discover all devices
    3. Enumerate all BACnet objects
    4. Ask LLM to infer equipment types + point semantics
    5. Write config/bms_config.yaml
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agent_unified.llm import UnifiedLLM
from agent_unified.engines.bacnet import BACnetAdapter, BACnetSimulatorAdapter
from agent_unified.engines.auto_config import AutoConfigurator


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


def get_bacnet_adapter(mode: str, port: int, local_address: str):
    if mode == "simulator":
        print("Using BACnet Simulator Adapter (no real hardware needed)")
        return BACnetSimulatorAdapter()
    else:
        print(f"Connecting to BACnet on {local_address}:{port}")
        return BACnetAdapter(
            local_address=local_address,
            local_port=port,
            device_id=999,
        )


async def main():
    parser = argparse.ArgumentParser(description="ARVIS BMS Auto-Configurator")
    parser.add_argument(
        "--mode",
        choices=["simulator", "bacnet"],
        default="simulator",
        help="bacnet = real hardware, simulator = mock data for testing",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=47808,
        help="BACnet/IP port (default: 47808)",
    )
    parser.add_argument(
        "--local-address",
        default="0.0.0.0",
        help="Local BACnet interface (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--building-id",
        default="AUTO-DISCOVERED",
        help="Building identifier (default: AUTO-DISCOVERED)",
    )
    parser.add_argument(
        "--output-dir",
        default="config",
        help="Output directory for config files (default: config)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--steps",
        type=str,
        default="1,2,3,4",
        help="Comma-separated steps to run: 1=discover, 2=read, 3=infer, 4=write (default: all)",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger("arvis.autoconfig.cli")

    steps = [int(s) for s in args.steps.split(",")]

    # Initialize components
    adapter = get_bacnet_adapter(args.mode, args.port, args.local_address)
    llm = UnifiedLLM()

    configurator = AutoConfigurator(
        bacnet_adapter=adapter,
        llm=llm,
        output_dir=args.output_dir,
        building_id=args.building_id,
    )

    try:
        if 1 in steps:
            devices = await configurator.step1_discover(timeout=30)
            print(f"\n✅ Step 1/4: Discovered {len(devices)} BACnet devices:")
            for d in devices:
                print(f"   [{d.device_id}] {d.device_name} @ {d.address} ({d.vendor_name})")

        if 2 in steps:
            await configurator.step2_read_objects()
            print(f"\n✅ Step 2/4: Object enumeration complete")
            for d in configurator.discovered_devices:
                total = sum(len(v) for v in d.objects.values())
                print(f"   {d.device_name}: {total} objects across {len(d.objects)} types")

        if 3 in steps:
            print(f"\n⏳ Step 3/4: LLM inference (sending to Groq)...")
            await configurator.step3_infer()
            print(f"\n✅ Step 3/4: Inferred {len(configurator.inferred_equipment)} equipment, "
                  f"{len(configurator.inferred_points)} points:")
            for eq in configurator.inferred_equipment:
                print(f"   {eq.equipment_id} ({eq.eq_type}) — confidence: {eq.confidence:.0%}")

        if 4 in steps:
            out_path = configurator.step4_write()
            print(f"\n✅ Step 4/4: Config written to {out_path}")
            print(f"\n   Discovery report: config/discovery_report.json")
            print(f"\n   Next: copy config/bms_config.yaml to your deployment server,")
            print(f"   then run: python -m agent_commercial.main --mode live")

    except Exception as e:
        logger.error(f"Configurator failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
