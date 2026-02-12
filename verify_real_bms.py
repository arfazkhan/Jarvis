import asyncio
import logging
import sys
import os

# Add user site-packages where BAC0 is installed
sys.path.append(os.path.expanduser("~\\AppData\\Roaming\\Python\\Python312\\site-packages"))

from agent_unified.engines.real_bms import RealBMS

# Configure logs
logging.basicConfig(level=logging.INFO)

async def main():
    print("--- Testing RealBMS Connection ---")
    
    # 1. Provide Config matched to YABE Setup
    config = {
        "bacnet": {
            "local_address": "0.0.0.0",
            "port": 47809, # Port 47809 to allow YABE on 47808
            "device_id": 9999,
            "points": [
                {
                    "point_id": "CH-01/CHWST",
                    "device_id": 1001, # YABE Device
                    "object_type": "analogInput",
                    "object_instance": 1,
                    "name": "CHW Supply Temp",
                    "equipment_id": "CH-01",
                    "unit": "C"
                }
            ]
        }
    }
    
    bms = RealBMS(config)
    
    # 2. Connect
    print("Connecting to BACnet mesh...")
    connected = await bms.connect()
    
    if connected:
        print("✅ Connected! Scanning for YABE...")
        await asyncio.sleep(2) # Discovery
        
        # Check devices
        devices = bms.adapter.devices
        print(f"Discovered Devices: {len(devices)}")
        for d in devices.values():
            print(f" - {d.device_name} (ID: {d.device_id}, Vendor: {d.vendor_name})")
            
        # Check Equipment Tool Interface
        print("\nChecking Equipment Interface...")
        chiller = bms.get_equipment("CH-01")
        if chiller:
            print(f"✅ Found Chiller: {chiller.name}")
            
            # Check Points
            points = bms.get_points_by_equipment("CH-01")
            for p in points:
                print(f"   > {p.name}: {p.value} {p.unit}")
        else:
            print("⚠️ Chiller not found in inventory (Check config parsing)")
            
    else:
        print("❌ Connection Failed. BAC0 library missing or port blocked.")

    await bms.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
