"""
BACnet Device Simulator
=======================

Creates a simulated BACnet device that YABE can discover and read.
Run this script, then in YABE click "Send WhoIs" to discover it.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    import BAC0
    
    print("\n" + "="*50)
    print("Starting BACnet Device Simulator")
    print("="*50)
    
    # Create device on port 47809 (different from YABE's 47808)
    print("\nCreating BACnet device on port 47809...")
    
    bacnet = BAC0.lite(port=47809)
    
    print(f"Device Name: {bacnet.this_device.objectName}")
    print(f"Device ID: {bacnet.this_device.objectIdentifier}")
    
    print("\n✅ BACnet device is running!")
    print("\nIn YABE:")
    print("1. Click 'Send WhoIs' (F2) to discover this device")
    print("2. You should see a device appear in the tree")
    print("\nPress Ctrl+C to stop...")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        bacnet.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
