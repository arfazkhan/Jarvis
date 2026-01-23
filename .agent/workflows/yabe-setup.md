---
description: how to set up YABE BACnet simulator for testing
---

# YABE BACnet Simulator Setup

This workflow sets up YABE (Yet Another BACnet Explorer) for testing the ARVIS Ops Copilot BACnet adapter without physical hardware.

## Prerequisites
- Windows 10/11
- .NET Framework 4.5+ (usually pre-installed)
- BACnet/IP uses UDP port 47808

## Step 1: Download YABE

1. Go to: https://sourceforge.net/projects/yetanotherbacnetexplorer/files/
2. Download `Yabe_v2.1.0.zip` (latest stable)
3. Extract to: `C:\Tools\YABE\`

## Step 2: Configure Windows Firewall

Allow BACnet traffic:
```powershell
# Run as Administrator
netsh advfirewall firewall add rule name="BACnet/IP" dir=in action=allow protocol=UDP localport=47808
netsh advfirewall firewall add rule name="BACnet/IP Out" dir=out action=allow protocol=UDP localport=47808
```

## Step 3: Launch YABE

1. Run `Yabe.exe` from the extracted folder
2. Click `Add Device` button (green plus icon)
3. Select `BACnet/IP over UDP` 
4. Choose your network adapter (use 192.168.x.x or your local IP)
5. Click `Start` to begin discovery

## Step 4: Add Simulated BACnet Device

In YABE, create a simulated device:

1. Right-click in device tree → `Add Virtual Device`
2. Set Device Instance: `1001` (matches our BACnet adapter config)
3. Add objects:
   - Analog Input 1: "CHW Supply Temp" (value: 7.0, units: °C)
   - Analog Input 2: "CHW Return Temp" (value: 12.0, units: °C)
   - Analog Input 3: "Chiller Power" (value: 450, units: kW)
   - Analog Value 1: "Zone Temp Setpoint" (value: 23.0, units: °C)
   - Binary Input 1: "Chiller Status" (value: true/active)

## Step 5: Configure Ops Copilot BACnet Adapter

Create `config/bms_config.yaml`:
```yaml
bacnet:
  enabled: true
  local_address: "0.0.0.0"  # Listen on all interfaces
  port: 47809  # Use different port than YABE
  
  # Devices to poll (discovered or manual)
  devices:
    - device_id: 1001
      name: "Chiller Plant Controller"
      poll_interval: 30  # seconds
      
  # Points to read
  points:
    - point_id: "CH-01/CHWST"
      device_id: 1001
      object_type: "analogInput"
      object_instance: 1
      name: "CHW Supply Temp"
      equipment_id: "CH-01"
      unit: "°C"
      
    - point_id: "CH-01/CHWRT"
      device_id: 1001
      object_type: "analogInput"
      object_instance: 2
      name: "CHW Return Temp"
      equipment_id: "CH-01"
      unit: "°C"
      
    - point_id: "CH-01/KW"
      device_id: 1001
      object_type: "analogInput"
      object_instance: 3
      name: "Chiller Power"
      equipment_id: "CH-01"
      unit: "kW"
```

## Step 6: Test BACnet Connection

// turbo
```bash
python -c "from agent_bms.bacnet_adapter import BACnetAdapter; import asyncio; a = BACnetAdapter(); asyncio.run(a.connect()); print('Connected!')"
```

If BAC0 not installed:
```bash
pip install BAC0
```

## Step 7: Run Ops Copilot in BACnet Mode

```bash
python -m agent_bms.main --mode bacnet --port 8000
```

## Troubleshooting

### Device not discovered
- Check firewall rules
- Ensure YABE and adapter are on same subnet
- Try specifying device IP directly in config

### Read failures
- Verify object exists in YABE device
- Check object instance numbers match
- Ensure device is "online" in YABE

### Port conflicts
- YABE uses 47808 by default
- Set Ops Copilot to use 47809 or different port
- Stop YABE when running real BACnet adapter

## Alternative: Room Simulator

YABE includes a room temperature simulator:
1. In YABE: `Tools` → `Room Simulator`
2. Creates realistic HVAC simulation with:
   - Outside temperature
   - Room temperature
   - Heating/cooling setpoints
   - Occupancy simulation

This provides dynamic values that change over time for more realistic testing.
