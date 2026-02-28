"""
YABE BACnet Integration Test
============================

Test script for verifying BACnet communication with YABE simulator.

Prerequisites:
1. YABE running with virtual device (device ID 1001)
2. config/bms_config.yaml configured
3. BAC0 installed: pip install BAC0

Run:
    python scripts/test_yabe_connection.py
"""

import asyncio
import sys
import yaml
import logging
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_commercial.bacnet_adapter import BACnetAdapter, BACnetPoint, BACNET_AVAILABLE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yabe_test")


def load_config(config_path: str = "config/bms_config.yaml") -> dict:
    """Load BMS configuration from YAML"""
    path = Path(config_path)
    if not path.exists():
        logger.error(f"Config file not found: {config_path}")
        return {}
    
    with open(path, 'r') as f:
        return yaml.safe_load(f)


async def test_connection():
    """Test BACnet connection and device discovery"""
    print("\n" + "="*60)
    print("YABE BACnet Integration Test")
    print("="*60)
    
    # Check BAC0 availability
    if not BACNET_AVAILABLE:
        print("\n❌ BAC0 library not installed!")
        print("   Run: pip install BAC0")
        return False
    
    print("\n✅ BAC0 library available")
    
    # Load configuration
    config = load_config()
    if not config:
        print("\n❌ Could not load config/bms_config.yaml")
        return False
    
    bacnet_config = config.get("bacnet", {})
    print(f"\n📋 Config loaded:")
    print(f"   Local port: {bacnet_config.get('port', 47808)}")
    print(f"   Devices configured: {len(bacnet_config.get('devices', []))}")
    print(f"   Points configured: {len(config.get('points', []))}")
    
    # Create adapter
    adapter = BACnetAdapter(
        local_address=bacnet_config.get("local_address", "0.0.0.0"),
        local_port=bacnet_config.get("port", 47809),
    )
    
    # Connect
    print("\n🔌 Connecting to BACnet network...")
    try:
        success = await adapter.connect()
        if not success:
            print("❌ Connection failed!")
            return False
        print("✅ Connected to BACnet network")
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False
    
    # Discover devices
    print("\n🔍 Discovering devices (5 second timeout)...")
    print("   Make sure YABE is running with virtual device 1001")
    
    devices = await adapter.discover_devices(timeout_seconds=5)
    
    if devices:
        print(f"\n✅ Discovered {len(devices)} device(s):")
        for device in devices:
            print(f"   - {device.device_name} (ID: {device.device_id})")
            print(f"     Address: {device.address}")
            print(f"     Vendor: {device.vendor_name}")
    else:
        print("\n⚠️ No devices discovered")
        print("   Check that:")
        print("   1. YABE is running")
        print("   2. Virtual device is created (ID 1001)")
        print("   3. Firewall allows UDP port 47808")
        print("   4. Both on same subnet")
    
    # Load point configs
    if "points" in config:
        adapter.load_points_from_config(config)
        print(f"\n📊 Loaded {len(adapter.points)} points")
    
    # Try reading points if devices found
    if devices and adapter.points:
        print("\n📖 Reading points...")
        
        for point_id, point_config in adapter.points.items():
            if point_config.device_id in [d.device_id for d in devices]:
                try:
                    result = await adapter.read_point(point_config)
                    if result:
                        print(f"   ✅ {point_id}: {result.value} {result.unit}")
                    else:
                        print(f"   ⚠️ {point_id}: No response")
                except Exception as e:
                    print(f"   ❌ {point_id}: Error - {e}")
    
    # Disconnect
    await adapter.disconnect()
    print("\n✅ Disconnected")
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    print(f"BAC0 available: ✅")
    print(f"Connection: ✅")
    print(f"Devices discovered: {len(devices)}")
    print(f"Points configured: {len(adapter.points)}")
    
    return len(devices) > 0


async def main():
    """Main entry point"""
    try:
        success = await test_connection()
        
        if success:
            print("\n🎉 YABE integration test PASSED!")
            print("\nYou can now run Ops Copilot in BACnet mode:")
            print("   python -m agent_commercial.main --mode bacnet --port 8000")
        else:
            print("\n⚠️ YABE integration test had issues")
            print("\nFor now, use simulator mode:")
            print("   python -m agent_commercial.main --mode simulator --port 8000")
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
